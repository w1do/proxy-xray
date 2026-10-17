"""Proxy container entrypoint: supervises xray (127.0.0.1:18080) and mihomo (127.0.0.1:7890, published).

Stdlib only. Amendment 2d split the old shared volume: kit writes generation.json, the configs and prev/ into
gen_dir (/kit-gen), which this process mounts read-only and never modifies. This process writes only into state_dir
(/kit-state): status.json, logs/ and the mihomo home (cache.db and geo symlinks). It restarts only the children whose
inputs changed, re-checks each config hash right before spawning, and writes status.json.
"""
import hashlib, json, os, signal, socket, stat, subprocess, sys, time
from pathlib import Path

XRAY_PORT = 18080
MIHOMO_PORT = 7890
GEO_FILES = ('geoip.dat', 'geoip.metadb', 'geosite.dat')
BACKOFF = (3, 6, 12, 30)
LOG_MAX_BYTES = 5 * 1024 * 1024


NOT_REGULAR = 'not-regular'


def ensure_real_dir(path):
    """Create a real directory (0700). A symlink or a non-directory in its place raises OSError (never followed)."""
    path = Path(path)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        path.mkdir(mode=0o700)
        return
    if not stat.S_ISDIR(st.st_mode):
        raise OSError(f'{path.name}: not a real directory')


def read_regular_bytes(path):
    """Bytes of a regular file, None when missing. Symlinks and other non-regular files raise OSError."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, 'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise OSError('not a regular file')
        return f.read()


def read_generation(path):
    """Parsed generation.json or None (missing, symlink, invalid JSON, or wrong types)."""
    try:
        raw = read_regular_bytes(path)
        if raw is None:
            return None
        data = json.loads(raw.decode('utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get('generation'), int) or isinstance(data.get('generation'), bool):
        return None
    for key in ('xray_sha256', 'mihomo_sha256'):
        if not isinstance(data.get(key), str):
            return None
    return data


def file_sha256(path):
    """Hex digest, '' when missing, NOT_REGULAR for a symlink or other non-regular file (never matches a declared hash)."""
    try:
        data = read_regular_bytes(path)
    except OSError:
        return NOT_REGULAR
    if data is None:
        return ''
    return hashlib.sha256(data).hexdigest()


def plan_restarts(applied, wanted, running):
    """Children to restart: changed hash, or not running."""
    applied = applied or {}
    plan = set()
    if applied.get('xray_sha256') != wanted.get('xray_sha256') or not running.get('xray'):
        plan.add('xray')
    if applied.get('mihomo_sha256') != wanted.get('mihomo_sha256') or not running.get('mihomo'):
        plan.add('mihomo')
    return plan


def status_is_stale(status, now, max_age=15):
    if not isinstance(status, dict) or not isinstance(status.get('heartbeat'), (int, float)):
        return True
    return now - status['heartbeat'] > max_age


def write_status(path, **fields):
    fields['heartbeat'] = time.time()
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    try:
        os.unlink(tmp)  # never write through a planted link
    except FileNotFoundError:
        pass
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(json.dumps(fields))
    os.replace(tmp, path)


def _port_open(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.5):
            return True
    except OSError:
        return False


def _wait_port(port, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.2)
    return False


def _child_env():
    return {k: v for k, v in os.environ.items() if not k.lower().endswith('_proxy')}


class Supervisor:
    def __init__(self):
        self.gen_dir = Path(os.environ.get('KIT_GEN_DIR', '/kit-gen'))
        self.state_dir = Path(os.environ.get('KIT_STATE_DIR', '/kit-state'))
        self.xray_bin = os.environ.get('KIT_XRAY_BIN', '/usr/local/bin/xray')
        self.mihomo_bin = os.environ.get('KIT_MIHOMO_BIN', '/usr/local/bin/mihomo')
        self.geo = Path(os.environ.get('KIT_GEO_DIR', '/opt/kit/geo'))
        self.procs = {}
        self.applied = None
        self.wanted = None
        self.seen_generation = None
        self.restarts = 0
        self.attempts = {'xray': 0, 'mihomo': 0}
        self.next_try = {'xray': 0.0, 'mihomo': 0.0}
        self.started_at = {}
        self.state = 'idle'
        self.error = None
        self.stop_flag = False
        self.dir_ok = True

    @property
    def status_path(self):
        return self.state_dir / 'status.json'

    def _status(self):
        write_status(self.status_path, generation=(self.applied or {}).get('generation'), state=self.state,
                     error=self.error, restarts=self.restarts)

    def start(self):
        os.umask(0o077)
        try:
            ensure_real_dir(self.state_dir)
            for sub in ('mihomo', 'logs'):
                ensure_real_dir(self.state_dir / sub)
        except OSError:
            self.dir_ok = False
            self.state, self.error = 'failed', 'Каталог /kit-state повреждён'
            self._status()
            return
        for name in GEO_FILES:
            link = self.state_dir / 'mihomo' / name
            if not link.exists() and not link.is_symlink():
                link.symlink_to(self.geo / name)
        self.state = 'idle'
        self._status()

    def _log_file(self, name):
        log_dir = self.state_dir / 'logs'
        path = log_dir / f'{name}.log'
        try:
            if os.lstat(path).st_size > LOG_MAX_BYTES:
                os.replace(path, log_dir / f'{name}.log.1')
        except FileNotFoundError:
            pass
        except OSError:
            pass
        try:
            fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        except OSError:
            return os.open(os.devnull, os.O_WRONLY)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            return os.open(os.devnull, os.O_WRONLY)
        os.fchmod(fd, 0o600)
        return fd

    def _config_path(self, name):
        return self.gen_dir / 'xray-client.json' if name == 'xray' else self.gen_dir / 'mihomo' / 'config.yaml'

    def _spawn(self, name, gen):
        """Start one child only if its config still matches the generation right before Popen. False = do not start."""
        if not gen:
            return False
        expected = gen.get('xray_sha256') if name == 'xray' else gen.get('mihomo_sha256')
        if not expected or file_sha256(self._config_path(name)) != expected:
            return False
        cmd = ([self.xray_bin, 'run', '-config', str(self._config_path('xray'))] if name == 'xray'
               else [self.mihomo_bin, '-d', str(self.state_dir / 'mihomo'), '-f', str(self._config_path('mihomo'))])
        fd = self._log_file(name)
        try:
            self.procs[name] = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=fd, stderr=fd,
                                                env=_child_env())
        finally:
            os.close(fd)
        self.started_at[name] = time.monotonic()
        return True

    def _stop(self, name):
        proc = self.procs.pop(name, None)
        if proc is None or proc.poll() is not None:
            return
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    def _running(self):
        return {name: (name in self.procs and self.procs[name].poll() is None) for name in ('xray', 'mihomo')}

    def _check_generation(self):
        gen = read_generation(self.gen_dir / 'generation.json')
        if gen is None or gen['generation'] == self.seen_generation:
            return
        self.seen_generation = gen['generation']
        if (file_sha256(self.gen_dir / 'xray-client.json') != gen['xray_sha256']
                or file_sha256(self.gen_dir / 'mihomo' / 'config.yaml') != gen['mihomo_sha256']):
            self.state, self.error = 'failed', 'Файлы конфигурации не совпали с поколением'
            self.wanted = None
            self._status()
            return
        self.wanted = gen

    def _integrity_failed(self):
        self._stop('mihomo')
        self._stop('xray')
        self.applied = None
        self.wanted = None
        self.state, self.error = 'failed', 'Файлы конфигурации не совпали с поколением'
        self._status()

    def _apply(self):
        plan = plan_restarts(self.applied, self.wanted, self._running())
        self.state, self.error = 'running', None
        self._status()
        for name in ('xray', 'mihomo'):
            if name not in plan:
                continue
            self._stop(name)
            if not self._spawn(name, self.wanted):
                self._integrity_failed()
                return
            port = XRAY_PORT if name == 'xray' else MIHOMO_PORT
            if not _wait_port(port, 10):
                self.state = 'failed'
                self.error = 'Xray не открыл 18080' if name == 'xray' else 'Mihomo не открыл 7890'
                self.applied = None
                self.wanted = None
                self._status()
                return
        self.applied = self.wanted
        self.wanted = None
        self._status()

    def _watch_children(self):
        now = time.monotonic()
        if self.applied is None:
            return
        for name in ('xray', 'mihomo'):
            proc = self.procs.get(name)
            if proc is None or proc.poll() is None:
                if now - self.started_at.get(name, now) > 60:
                    self.attempts[name] = 0
                continue
            if now < self.next_try[name]:
                continue
            delay = BACKOFF[min(self.attempts[name], len(BACKOFF) - 1)]
            self.attempts[name] += 1
            self.restarts += 1
            print(f'child {name} exited with {proc.returncode}; restarting in {delay}s', flush=True)
            self.next_try[name] = now + delay
            if not self._spawn(name, self.applied):
                self._integrity_failed()
                return
            self._status()

    def _handle_signal(self, signum, frame):
        self.stop_flag = True

    def run_loop(self):
        self.start()
        last_beat = 0.0
        while not self.stop_flag:
            if self.dir_ok:
                self._check_generation()
                if self.wanted is not None:
                    self._apply()
                self._watch_children()
            if time.monotonic() - last_beat >= 5:
                self._status()
                last_beat = time.monotonic()
            time.sleep(1)
        for name in ('mihomo', 'xray'):
            self._stop(name)
        self.state = 'idle'
        self._status()
        return 0

    def run(self):
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        return self.run_loop()


def main():
    return Supervisor().run()


if __name__ == '__main__':
    raise SystemExit(main())
