"""Install and rules apply: render -> validate -> write bundle -> proxy applies -> verify exit IP -> rollback on failure.

Amendment 2d split the old shared volume in two.
- kit-gen ($KIT_GEN_DIR, /kit-gen): written by kit only (generation.json, configs, prev/). The proxy mounts it read-only.
- kit-state ($KIT_STATE_DIR, /kit-state): written by proxy only (status.json, logs, mihomo home). kit mounts it read-only and
  treats every entry as hostile input (open_state_dir with O_NOFOLLOW and dir_fd).
The proxy container reads generation.json and restarts its children; this module never talks to the proxy container
directly except through curl via $KIT_PROXY_URL for the exit check.
"""
import hashlib, json, os, secrets, stat, subprocess, tempfile, time
from datetime import datetime, timezone
from pathlib import Path

import kit_db, kit_jobs, kit_render

HEARTBEAT_MAX_AGE = 15
GEO_FILES = ('geoip.dat', 'geoip.metadb', 'geosite.dat')


class RunFileError(RuntimeError):
    """A run-dir entry is not a regular file (symlink, directory, ...). It is never read or followed."""


def read_regular_bytes(path, dir_fd=None):
    """Bytes of a regular file, None when missing. Symlinks and other non-regular files raise RunFileError."""
    path = Path(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    except OSError:
        raise RunFileError(f'{path.name}: не обычный файл (символическая ссылка или недоступен)') from None
    with os.fdopen(fd, 'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise RunFileError(f'{path.name}: не обычный файл')
        return f.read()


def read_regular_text(path):
    data = read_regular_bytes(path)
    return None if data is None else data.decode('utf-8')


LOG_TAIL_BYTES = 262144


def read_regular_tail(path, max_bytes=LOG_TAIL_BYTES, dir_fd=None):
    """Last max_bytes of a regular file as (bytes, truncated). None when missing.
    Symlinks, FIFOs, devices, directories and hard links (nlink != 1) raise RunFileError. O_NONBLOCK keeps a FIFO from blocking."""
    path = Path(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    except OSError:
        raise RunFileError(f'{path.name}: не обычный файл (символическая ссылка или недоступен)') from None
    with os.fdopen(fd, 'rb') as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise RunFileError(f'{path.name}: не обычный файл или есть жёсткая ссылка')
        truncated = st.st_size > max_bytes
        if truncated:
            f.seek(st.st_size - max_bytes)
        return f.read(max_bytes), truncated


def ensure_real_dir(path):
    """Create a real directory with mode 0700. A symlink or a non-directory in its place is refused."""
    path = Path(path)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        path.mkdir(mode=0o700)
        return
    if not stat.S_ISDIR(st.st_mode):
        raise RunFileError(f'{path.name}: не каталог')


class BundleInvalid(RuntimeError):
    """Message is safe for the browser; `detail` is the raw tool output for the redacted job log only."""
    detail = ''


def gen_dir():
    return Path(os.environ.get('KIT_GEN_DIR', '/kit-gen'))


def state_dir():
    return Path(os.environ.get('KIT_STATE_DIR', '/kit-state'))


def open_state_dir(sub=None):
    """fd of kit-state (or of its subdirectory `sub`) opened with O_DIRECTORY|O_NOFOLLOW. Never creates anything.
    Missing → None; any other failure (symlink, not a directory) → RunFileError."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        fd = os.open(state_dir(), flags)
    except FileNotFoundError:
        return None
    except OSError:
        raise RunFileError('каталог состояния недоступен или не каталог') from None
    if sub is None:
        return fd
    try:
        sub_fd = os.open(sub, flags, dir_fd=fd)
    except FileNotFoundError:
        os.close(fd)
        return None
    except OSError:
        os.close(fd)
        raise RunFileError(f'{sub}: не каталог или символическая ссылка') from None
    os.close(fd)
    return sub_fd


def sha256_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest() if text else ''


def _file_text(path):
    return read_regular_text(path)


def open_real_dir(path):
    """fd of a real directory (no symlink at any level of the final component). Refuses anything else."""
    ensure_real_dir(path)
    try:
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        raise RunFileError(f'{Path(path).name}: не каталог или символическая ссылка') from None


def atomic_write(path, text, mode=0o600):
    """Write through the parent's directory fd only: temp name with O_EXCL|O_NOFOLLOW, fchmod, fsync, then rename.
    Nothing is resolved by path after the directory is opened."""
    path = Path(path)
    dfd = open_real_dir(path.parent)
    tmp = '.tmp-' + secrets.token_hex(8)
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=dfd)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            os.fchmod(f.fileno(), mode)
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path.name, src_dir_fd=dfd, dst_dir_fd=dfd)
    except BaseException:
        try:
            os.unlink(tmp, dir_fd=dfd)
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(dfd)


def _xray_path():
    return gen_dir() / 'xray-client.json'


def _mihomo_path():
    return gen_dir() / 'mihomo' / 'config.yaml'


def _gen_path():
    return gen_dir() / 'generation.json'


def _prev_dir():
    return gen_dir() / 'prev'


def validate_bundle(xray_json, mihomo_yaml):
    geo = Path(os.environ.get('KIT_GEO_DIR', '/opt/kit/geo'))
    xray_bin = os.environ.get('KIT_XRAY_BIN', '/usr/local/bin/xray')
    mihomo_bin = os.environ.get('KIT_MIHOMO_BIN', '/usr/local/bin/mihomo')
    with tempfile.TemporaryDirectory() as d:
        x = Path(d) / 'xray.json'
        m = Path(d) / 'config.yaml'
        x.write_text(xray_json, encoding='utf-8')
        m.write_text(mihomo_yaml, encoding='utf-8')
        r = subprocess.run([xray_bin, 'run', '-test', '-config', str(x)], capture_output=True, text=True,
                           timeout=20, env=kit_jobs.child_env(), stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            err = BundleInvalid('Конфигурация не прошла проверку: xray')
            err.detail = r.stdout + r.stderr
            raise err
        home = Path(d) / 'home'
        home.mkdir()
        for name in GEO_FILES:
            (home / name).symlink_to(geo / name)
        r = subprocess.run([mihomo_bin, '-t', '-d', str(home), '-f', str(m)], capture_output=True, text=True,
                           timeout=30, env=kit_jobs.child_env(), stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            err = BundleInvalid('Конфигурация не прошла проверку: mihomo')
            err.detail = r.stdout + r.stderr
            raise err


def write_bundle(xray_json=None, mihomo_yaml=None):
    run = gen_dir()
    ensure_real_dir(run)
    os.chmod(run, 0o700)
    # Validate every directory the bundle touches before anything is read or written.
    ensure_real_dir(run / 'mihomo')
    prev = _prev_dir()
    ensure_real_dir(prev)
    cur_x, cur_m = _file_text(_xray_path()), _file_text(_mihomo_path())
    if cur_x is not None and cur_m is not None:
        # atomic_write replaces the directory entry (temp file + os.replace), so a planted symlink is replaced, not followed.
        atomic_write(prev / 'xray-client.json', cur_x)
        atomic_write(prev / 'mihomo-config.yaml', cur_m)
    if xray_json is not None:
        atomic_write(_xray_path(), xray_json)
    if mihomo_yaml is not None:
        atomic_write(_mihomo_path(), mihomo_yaml)
    final_x, final_m = _file_text(_xray_path()), _file_text(_mihomo_path())
    old = read_generation_file()
    gen = (old or {}).get('generation', 0) + 1
    atomic_write(_gen_path(), json.dumps({'generation': gen, 'xray_sha256': sha256_text(final_x or ''),
                                          'mihomo_sha256': sha256_text(final_m or '')}))
    return gen


def read_generation_file():
    data = read_regular_bytes(_gen_path())
    if data is None:
        return None
    try:
        return json.loads(data.decode('utf-8'))
    except ValueError:
        return None


def restore_prev():
    ensure_real_dir(gen_dir())
    prev = _prev_dir()
    ensure_real_dir(prev)
    px_text = read_regular_text(prev / 'xray-client.json')
    pm_text = read_regular_text(prev / 'mihomo-config.yaml')
    if px_text is None or pm_text is None:
        return None
    return write_bundle(px_text, pm_text)


def read_status():
    """Current status.json from kit-state, or None (missing, refused, invalid)."""
    try:
        fd = open_state_dir()
    except RunFileError:
        return None
    if fd is None:
        return None
    try:
        data = read_regular_bytes('status.json', dir_fd=fd)
    except RunFileError:
        return None
    finally:
        os.close(fd)
    if data is None:
        return None
    try:
        return json.loads(data.decode('utf-8'))
    except ValueError:
        return None


def wait_applied(generation, timeout=25):
    deadline = time.monotonic() + timeout
    while True:
        status = read_status()
        if status and status.get('generation') == generation and status.get('state') in ('running', 'failed'):
            return status
        if time.monotonic() >= deadline:
            return {'state': 'timeout'}
        time.sleep(0.5)


def verify_exit(expected, tries=3):
    proxy = os.environ.get('KIT_PROXY_URL', 'http://proxy:7890')
    ip = ''
    for attempt in range(tries):
        if attempt:
            time.sleep(1)
        try:
            r = subprocess.run(['curl', '--noproxy', '', '-fsS', '--max-time', '10', '-x', proxy,
                                'https://api.ipify.org'],
                               capture_output=True, text=True, env=kit_jobs.child_env(), timeout=13,
                               stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            continue
        ip = r.stdout.strip()
        if r.returncode == 0 and ip == expected:
            return True, ip
    return False, ip


def _rules_and_match():
    conn = kit_db.connect()
    try:
        return kit_db.get_rules(conn), kit_db.get_match(conn)
    finally:
        conn.close()


def _reason(status, ip, expected):
    if status.get('state') != 'running':
        error = status.get('error') or status.get('state')
        return f'прокси не применил конфигурацию ({error})'
    if ip and ip != expected:
        return f'выходной IP {ip} не совпал с ожидаемым'
    return 'проверка выходного IP не прошла'


def _rollback(job, reason, ip):
    restored = restore_prev()
    if restored is None:
        return 'failed', ip, f'Установка не удалась: {reason}. Предыдущей конфигурации нет'
    status = wait_applied(restored)
    job.append(f"Прокси-контейнер после отката: {status.get('state')}")
    return 'failed', ip, f'Установка не удалась: {reason}. Восстановлена предыдущая конфигурация'


def install(job, nl_host, row):
    job.redactor.add(row['uuid'], row['pbk'], row['sid'])
    rules, match = _rules_and_match()
    xray_text = json.dumps(kit_render.xray_client_config(nl_host, row), indent=2) + '\n'
    mihomo_text = kit_render.mihomo_config(rules, match)
    job.append('Проверка конфигурации…')
    validate_bundle(xray_text, mihomo_text)
    gen = write_bundle(xray_text, mihomo_text)
    job.append(f'Применение (поколение {gen})…')
    status = wait_applied(gen)
    if status.get('state') != 'running':
        job.append(f"Прокси-контейнер: {status.get('state')}")
        return _rollback(job, _reason(status, '', row['exit_ip']), None)
    job.append('Прокси-контейнер: running')
    ok, ip = verify_exit(row['exit_ip'])
    job.append(f'Выходной IP: {ip or "не получен"}')
    if not ok:
        return _rollback(job, _reason(status, ip, row['exit_ip']), ip or None)
    conn = kit_db.connect()
    try:
        kit_db.set_active(conn, row['id'], gen)
    finally:
        conn.close()
    return 'ok', ip, f"Установлено: NL:{row['port']} -> {row['exit_ip']}"


def apply_rules(job, nl):
    conn = kit_db.connect()
    try:
        active = kit_db.get_active(conn)
        inbound = kit_db.get_inbound(conn, active['inbound_id']) if active and active['inbound_id'] else None
    finally:
        conn.close()
    if inbound is None:
        return 'ok', None, 'Правила сохранены; будут применены при установке'
    job.redactor.add(inbound['uuid'], inbound['pbk'], inbound['sid'])
    rules, match = _rules_and_match()
    mihomo_text = kit_render.mihomo_config(rules, match)
    current_xray = _file_text(_xray_path())
    if current_xray is None:
        return 'ok', None, 'Правила сохранены; будут применены при установке'
    job.append('Проверка правил…')
    validate_bundle(current_xray, mihomo_text)
    gen = write_bundle(None, mihomo_text)
    job.append(f'Применение правил (поколение {gen})…')
    status = wait_applied(gen)
    if status.get('state') != 'running':
        return _rollback(job, _reason(status, '', inbound['exit_ip']), None)
    ok, ip = verify_exit(inbound['exit_ip'])
    job.append(f'Выходной IP: {ip or "не получен"}')
    if not ok:
        return _rollback(job, _reason(status, ip, inbound['exit_ip']), ip or None)
    return 'ok', ip, 'Правила применены'


def proxy_state():
    status = read_status()
    now = datetime.now(timezone.utc).timestamp()
    heartbeat = status.get('heartbeat') if status else None
    age = round(now - heartbeat, 1) if isinstance(heartbeat, (int, float)) else None
    if status is None or age is None or age > HEARTBEAT_MAX_AGE:
        return {'state': 'down', 'error': None, 'generation': None, 'heartbeat_age': age}
    return {'state': status.get('state'), 'error': status.get('error'), 'generation': status.get('generation'),
            'heartbeat_age': age}
