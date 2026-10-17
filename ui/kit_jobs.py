"""Background jobs for the web UI: one at a time, redacted live log.

Install and rules apply are implemented in kit_apply.py and only dispatched from here.
Subprocesses use argv lists (no shell), stdin=/dev/null, env without *_proxy, and a process group
that is terminated on timeout.
"""
import os, re, signal, subprocess, threading
from pathlib import Path

import kit_db, kit_discovery

ROOT = Path(__file__).resolve().parents[1]
UUID_RE = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
VLESS_RE = re.compile(r'vless://\S+')
MAX_LINES = 5000


class Busy(RuntimeError):
    pass


def child_env():
    return {k: v for k, v in os.environ.items() if not k.lower().endswith('_proxy')}


class Redactor:
    def __init__(self, secrets=()):
        self.secrets = set()
        self.add(*secrets)

    def add(self, *values):
        for value in values:
            if value and len(str(value)) >= 4:
                self.secrets.add(str(value))

    def apply(self, text):
        text = str(text)
        for secret in sorted(self.secrets, key=len, reverse=True):
            text = text.replace(secret, '[REDACTED]')
        text = UUID_RE.sub('[UUID]', text)
        return VLESS_RE.sub('vless://[REDACTED]', text)


class Job:
    def __init__(self, job_id, secrets=()):
        self.id = job_id
        self.redactor = Redactor(secrets)
        self.lock = threading.Lock()
        self.lines = []
        self.dropped = 0
        log_dir = kit_db.data_dir() / 'logs'
        log_dir.mkdir(mode=0o700, exist_ok=True)
        os.chmod(log_dir, 0o700)
        self._fd = os.open(log_dir / f'job-{job_id}.log', os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        os.chmod(log_dir / f'job-{job_id}.log', 0o600)

    def append(self, text):
        for raw in str(text).splitlines() or ['']:
            line = self.redactor.apply(raw)
            with self.lock:
                self.lines.append(line)
                if len(self.lines) > MAX_LINES:
                    del self.lines[0]
                    self.dropped += 1
                os.write(self._fd, (line + '\n').encode('utf-8'))

    def close(self):
        with self.lock:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None

    def snapshot(self, offset):
        with self.lock:
            start = max(0, offset - self.dropped)
            return self.lines[start:], self.dropped + len(self.lines)


def read_log_file(job_id, offset):
    path = kit_db.data_dir() / 'logs' / f'job-{job_id}.log'
    try:
        with open(path, encoding='utf-8') as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        lines = []
    return lines[offset:], len(lines)


def run_streamed(job, argv, timeout):
    """Run argv, feed each line to job.append (if job given). Returns (returncode, raw_lines)."""
    proc = subprocess.Popen(argv, cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=child_env(), start_new_session=True)
    hard = {}

    def hard_kill():
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def soft_kill():
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        hard['timer'] = threading.Timer(5, hard_kill)
        hard['timer'].daemon = True
        hard['timer'].start()

    timer = threading.Timer(timeout, soft_kill)
    timer.daemon = True
    timer.start()
    lines = []
    try:
        for raw in proc.stdout:
            text = raw.rstrip('\n')
            lines.append(text)
            if job is not None:
                job.append(text)
        returncode = proc.wait()
    finally:
        timer.cancel()
        if 'timer' in hard:
            hard['timer'].cancel()
        proc.stdout.close()
    return returncode, lines


SAFE_ERRORS = ('SafeError', 'DiscoveryFailed', 'BundleInvalid', 'RunFileError')


def summarize_error(job, exc):
    """Summary text for a failed job. Only the user-facing error classes keep their message; anything else
    (subprocess errors print argv with key and known_hosts paths) gets a generic summary, and its detail goes to the
    redacted job log."""
    detail = getattr(exc, 'detail', '')
    if detail:
        job.append(detail)
    if type(exc).__name__ in SAFE_ERRORS:
        return str(exc)
    job.append(f'{type(exc).__name__}: {exc}')
    return 'Задача завершилась с ошибкой; подробности в журнале задачи'


class JobRunner:
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs = {}

    def start(self, kind, inbound_id, fn, secrets=()):
        if not self.lock.acquire(blocking=False):
            raise Busy()
        try:
            conn = kit_db.connect()
            try:
                job_id = kit_db.create_job(conn, kind, inbound_id)
            finally:
                conn.close()
            job = Job(job_id, secrets)
        except Exception:
            self.lock.release()
            raise
        self.jobs[job_id] = job
        threading.Thread(target=self._run, args=(job, fn), daemon=True).start()
        return job_id

    def _run(self, job, fn):
        try:
            status, result_ip, summary = fn(job)
        except Exception as exc:
            status, result_ip, summary = 'failed', None, summarize_error(job, exc)
        try:
            summary = job.redactor.apply(summary)
            conn = kit_db.connect()
            try:
                kit_db.finish_job(conn, job.id, status, result_ip, summary)
                kit_db.prune_jobs(conn)
            finally:
                conn.close()
        finally:
            job.close()
            self.lock.release()

    def read(self, job_id, offset):
        conn = kit_db.connect()
        try:
            row = kit_db.get_job(conn, job_id)
        finally:
            conn.close()
        if row is None:
            return None
        job = self.jobs.get(job_id)
        if job is not None and row['status'] == 'running':
            lines, next_offset = job.snapshot(offset)
        elif job is not None:
            lines, next_offset = job.snapshot(offset)
        else:
            lines, next_offset = read_log_file(job_id, offset)
        return {'lines': lines, 'next_offset': next_offset, 'status': row['status'],
                'result_ip': row['result_ip'], 'summary': row['summary']}


def running_job(conn):
    row = conn.execute("SELECT id, kind, inbound_id FROM jobs WHERE status = 'running' ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def discover_job(job, nl):
    nodes = kit_discovery.discover(nl)
    job.redactor.add(*[v for r in nodes for v in (r['uuid'], r['pbk'], r['sid'])])
    conn = kit_db.connect()
    try:
        stats = kit_db.upsert_inbounds(conn, nodes)
    finally:
        conn.close()
    for warning in kit_discovery.known_exit_warnings(nodes):
        job.append(warning)
    return 'ok', None, f"Найдено входов: {stats['total']}, новых: {stats['new']}"


def check_job(job, nl, inbound_ids):
    failed = 0
    for inbound_id in inbound_ids:
        conn = kit_db.connect()
        try:
            row = kit_db.get_inbound(conn, inbound_id)
            if row is None:
                continue
            job.redactor.add(row['uuid'], row['pbk'], row['sid'])
            label = f"NL:{row['port']} ({row['network']}) -> {row['exit_ip']}"
            host = kit_discovery.row_nl_host(row, nl)
            try:
                if host is None:
                    raise kit_discovery.SafeError('Не заданы настройки NL')
                ok, seen = kit_discovery.run_check(row, host)
                error = None if ok else ('Выход не совпал' if seen else 'Проверка не прошла')
            except Exception as exc:
                ok, seen = False, ''
                error = summarize_error(job, exc)
            kit_db.set_check(conn, inbound_id, ok, seen or None, error)
        finally:
            conn.close()
        if ok:
            job.append(f'{label}: OK {seen}')
        else:
            failed += 1
            job.append(f'{label}: ОШИБКА {seen or error}')
    total = len(inbound_ids)
    return ('ok' if failed == 0 else 'failed'), None, f'Проверено: {total}, ошибок: {failed}'


def install_job(job, nl_host, row):
    import kit_apply
    return kit_apply.install(job, nl_host, row)


def apply_rules_job(job, nl):
    import kit_apply
    return kit_apply.apply_rules(job, nl)
