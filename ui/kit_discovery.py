"""Discovery, host-key trust, check and link helpers for the web UI.

Uses kit_nl (SSH discovery, vless links, temporary Xray check) and kit_render (KNOWN_EXITS).
Raw SSH output is attached to exceptions as `detail` and is only ever written to the redacted job log.
"""
import json, os, re, subprocess, tempfile
from pathlib import Path

import kit_db, kit_nl, kit_render

HOST_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}')
IPV4_RE = re.compile(r'\d{1,3}(\.\d{1,3}){3}')
USER_RE = re.compile(r'[a-z_][a-z0-9_-]{0,31}')
SUPPORTED_NETWORKS = ('xhttp', 'tcp', 'grpc')
KEY_TYPE_RE = re.compile(r'^\S+\s+(SHA256:\S+)\s+.*\((\w+)\)\s*$')
DEFAULT_KEY_FILE = '/tmp/kit-ssh/id_nl'


def _is_host(value):
    return bool(HOST_RE.fullmatch(value) or IPV4_RE.fullmatch(value))


def validate_nl(data):
    """Return normalized NL settings or raise ValueError. Error texts never echo the rejected value."""
    if not isinstance(data, dict):
        raise ValueError('Ожидается объект с настройками NL')
    host = data.get('host')
    if not isinstance(host, str) or not _is_host(host):
        raise ValueError('Хост NL: недопустимое значение')
    user = data.get('ssh_user') or 'root'
    if not isinstance(user, str) or not USER_RE.fullmatch(user):
        raise ValueError('SSH-пользователь: недопустимое значение')
    port = data.get('ssh_port', 22)
    if port is None:
        port = 22
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError('SSH-порт: целое число от 1 до 65535')
    return {'host': host, 'ssh_user': user, 'ssh_port': port}


def normalize(raw):
    """Map one kit_nl row to inbounds columns. Returns None for unsupported transports."""
    if raw.get('network') not in SUPPORTED_NETWORKS:
        return None
    return {
        'port': int(raw['port']),
        'uuid': str(raw['uuid']),
        'exit_ip': str(raw.get('exit', '')),
        'exit_tag': str(raw.get('exit_tag', '') or ''),
        'network': raw['network'],
        'remark': str(raw.get('email', '') or ''),
        'flow': str(raw.get('flow', '') or ''),
        'pbk': str(raw.get('pbk', '')),
        'sid': str(raw.get('sid', '')),
        'sni': str(raw.get('sni', '')),
        'xhttp_json': json.dumps(raw.get('xhttp') or {}, sort_keys=True),
        'grpc_service': str(raw.get('grpc', '') or ''),
        'grpc_multi': int(bool(raw.get('multi'))),
    }


def installable(network, port, exit_ip):
    return network in SUPPORTED_NETWORKS and port not in kit_nl.SKIP_PORTS and bool(exit_ip)


def exit_label(exit_ip, exit_tag):
    return kit_render.KNOWN_EXITS.get(exit_ip, {}).get('label') or exit_tag or exit_ip


def known_exit_warnings(rows):
    """Log-only warnings for inbounds whose port is outside the expected range of a known exit."""
    lines = []
    for row in rows:
        known = kit_render.KNOWN_EXITS.get(row['exit_ip'])
        if known and row['port'] not in known['ports']:
            low, high = min(known['ports']), max(known['ports'])
            lines.append(f"Вход NL:{row['port']} ведёт на {known['label']}, но не входит в ожидаемые порты "
                         f"{low}-{high}")
    return lines


class SafeError(RuntimeError):
    """A user-facing message that is safe to show in the job summary. Any other exception gets a generic summary."""


class DiscoveryFailed(RuntimeError):
    """Message is safe for the browser; `detail` holds raw ssh stderr for the redacted log only."""
    detail = ''


def paths():
    """(known_hosts path, key file path). The known_hosts file lives in the data volume."""
    ssh_dir = kit_db.data_dir() / 'ssh'
    ssh_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(ssh_dir, 0o700)
    known = ssh_dir / 'known_hosts'
    if not known.exists():
        os.close(os.open(known, os.O_CREAT | os.O_WRONLY, 0o600))
    os.chmod(known, 0o600)
    return known, os.environ.get('KIT_SSH_KEY_FILE', DEFAULT_KEY_FILE)


def discover(nl):
    known, key = paths()
    if not os.path.isfile(key):
        raise DiscoveryFailed('NL: SSH-ключ не смонтирован (KIT_SSH_KEY)')
    port, user, host = nl['ssh_port'], nl['ssh_user'], nl['host']
    try:
        raw = kit_nl.discover_rows(f'{user}@{host}', port, key, str(known))
    except kit_nl.DiscoveryError as exc:
        if 'Host key verification failed' in exc.stderr:
            message = 'NL: ключ хоста не подтверждён. Нажмите «Проверить ключ хоста» в настройках NL'
        elif 'Permission denied' in exc.stderr:
            message = 'NL: SSH-ключ не принят (проверьте KIT_SSH_KEY и authorized_keys на NL)'
        else:
            message = f'NL: SSH не выполнен (код {exc.returncode})'
        failure = DiscoveryFailed(message)
        failure.detail = exc.stderr
        raise failure from None
    rows = [normalize(r) for r in raw]
    return [r for r in rows if r is not None]


def _host_target(host, port):
    return host if port == 22 else f'[{host}]:{port}'


def scan_host_key(host, port):
    """Public host keys from ssh-keyscan for exactly this host and port."""
    target = _host_target(host, port)
    r = subprocess.run(['ssh-keyscan', '-T', '10', '-p', str(port), '-t', 'ed25519,ecdsa,rsa', host],
                       capture_output=True, text=True, timeout=20)
    lines = []
    for line in r.stdout.splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        fields = line.split()
        if len(fields) >= 3 and fields[0] == target:
            lines.append(line.strip())
    if not lines:
        raise SafeError('NL: ssh-keyscan не получил ключи')
    return lines


def fingerprints(lines):
    """[{type, fingerprint}] computed by ssh-keygen -l -E sha256 from the scanned lines."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'keys.pub'
        path.write_text('\n'.join(lines) + '\n')
        r = subprocess.run(['ssh-keygen', '-l', '-E', 'sha256', '-f', str(path)],
                           capture_output=True, text=True, timeout=20)
    out = []
    for line in r.stdout.splitlines():
        m = KEY_TYPE_RE.match(line.strip())
        if m:
            out.append({'type': m.group(2), 'fingerprint': m.group(1)})
    if not out:
        raise SafeError('NL: не удалось вычислить отпечатки ключей')
    return out


def trust_host_key(lines, host, port, known_hosts):
    """Replace this host's entries in known_hosts with the confirmed lines (0600)."""
    target = _host_target(host, port)
    known = Path(known_hosts)
    if not known.exists():
        os.close(os.open(known, os.O_CREAT | os.O_WRONLY, 0o600))
    subprocess.run(['ssh-keygen', '-R', target, '-f', str(known)], capture_output=True, text=True, timeout=20)
    old = Path(str(known) + '.old')
    if old.exists():
        old.unlink()
    with open(known, 'a', encoding='utf-8') as f:
        for line in lines:
            f.write(line + '\n')
    os.chmod(known, 0o600)


def is_trusted(host, port, known_hosts):
    known = Path(known_hosts)
    if not known.is_file():
        return False
    r = subprocess.run(['ssh-keygen', '-F', _host_target(host, port), '-f', str(known)],
                       capture_output=True, text=True, timeout=20)
    return r.returncode == 0


def export_row(db_row):
    return {
        'port': db_row['port'],
        'uuid': db_row['uuid'],
        'email': db_row['remark'],
        'sni': db_row['sni'],
        'sid': db_row['sid'],
        'pbk': db_row['pbk'],
        'network': db_row['network'],
        'flow': db_row['flow'],
        'grpc': db_row['grpc_service'],
        'multi': bool(db_row['grpc_multi']),
        'xhttp': json.loads(db_row['xhttp_json'] or '{}'),
        'exit': db_row['exit_ip'],
    }


def run_check(db_row, nl_host):
    """Returns (ok, seen_ip). Uses a local xray on 127.0.0.1:18083 only; the live proxy is not touched."""
    return kit_nl.check(export_row(db_row), nl_host, os.environ.get('KIT_XRAY_BIN', '/usr/local/bin/xray'))


def key_available(path=None):
    """True when the NL key is a regular, non-empty file (an empty docker/no-key placeholder counts as no key)."""
    p = path or os.environ.get('KIT_SSH_KEY_FILE', DEFAULT_KEY_FILE)
    try:
        return os.path.isfile(p) and os.path.getsize(p) > 0
    except OSError:
        return False


def row_nl_host(row, nl):
    """NL server address for one inbound: imported rows carry their own host, discovered rows use the saved NL settings."""
    if row.get('source') == 'import':
        return row.get('nl_host') or None
    return nl['host'] if nl else None


def links_for_exit(conn, nl, exit_ip):
    """vless links of every stored inbound on one exit. Rows without a usable NL host are skipped."""
    items = []
    for row in kit_db.list_inbounds(conn):
        if row['exit_ip'] != exit_ip:
            continue
        host = row_nl_host(row, nl)
        if not host:
            continue
        items.append({'id': row['id'], 'port': row['port'], 'network_label': kit_db.network_label(row),
                      'remark': row['remark'],
                      'link': kit_nl.make_link(export_row(row), host)})
    return sorted(items, key=lambda x: x['port'])
