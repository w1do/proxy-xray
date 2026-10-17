"""Local web UI server (stdlib only). Listens on 0.0.0.0:4050 inside the kit container; the host publishes loopback only.

Entry: python3 /app/ui/server.py. Routes are listed in ROUTES; every request passes kit_guard.check_request first.
"""
import hmac, json, os, re, secrets, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import kit_apply, kit_db, kit_discovery, kit_guard, kit_import, kit_jobs, kit_nl, kit_priv, kit_render

HERE = Path(__file__).resolve().parent
BODY_LIMIT = 16 * 1024
SCAN_TTL = 300
IPV4_RE = re.compile(r'\d{1,3}(\.\d{1,3}){3}')
JOB_ID_RE = re.compile(r'\d{1,9}')
INBOUND_RE = re.compile(r'/api/inbounds/(\d{1,9})/(check|install)')
EXIT_RE = re.compile(r'/api/exits/([0-9.]+)/links')
ASSET_RE = re.compile(r'[A-Za-z0-9._-]+\.(js|css|svg|png|woff2)')
CONTENT_TYPES = {
    'html': 'text/html; charset=utf-8',
    'js': 'text/javascript; charset=utf-8',
    'css': 'text/css; charset=utf-8',
    'svg': 'image/svg+xml',
    'png': 'image/png',
    'woff2': 'font/woff2',
}


def build_static_map(root):
    """Immutable map of exact URL paths to files. Request paths are never joined onto the filesystem."""
    root = Path(root)
    mapping = {}
    index = root / 'index.html'
    if index.is_file() and not index.is_symlink():
        mapping['/'] = index
    assets = root / 'assets'
    if assets.is_dir():
        for path in sorted(assets.iterdir()):
            if path.is_file() and not path.is_symlink() and ASSET_RE.fullmatch(path.name):
                mapping[f'/assets/{path.name}'] = path
    return mapping


class ApiError(Exception):
    def __init__(self, status, message, extra=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = dict(extra or {})


def load_or_create_token(path):
    path = Path(path)
    try:
        return path.read_text(encoding='utf-8').strip()
    except FileNotFoundError:
        pass
    token = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(token)
    os.chmod(path, 0o600)
    return token


def make_token_getter(path=None):
    path = Path(path) if path else kit_db.data_dir() / 'ui-token'
    cache = {'mtime': None, 'value': None}
    lock = threading.Lock()

    def get():
        with lock:
            try:
                mtime = path.stat().st_mtime_ns
            except FileNotFoundError:
                mtime = None
            if mtime is None or mtime != cache['mtime']:
                cache['value'] = load_or_create_token(path)
                cache['mtime'] = path.stat().st_mtime_ns
            return cache['value']
    return get


def _public_port(port=None):
    return int(port or os.environ.get('KIT_PUBLIC_PORT', '4050'))


def _nl_key_mounted():
    return kit_discovery.key_available()


def state_payload(conn):
    nl = kit_db.get_nl(conn)
    known, key = kit_discovery.paths()
    trusted = bool(nl) and kit_discovery.is_trusted(nl['host'], nl['ssh_port'], known)
    active = kit_db.get_active(conn)
    active_id = active['inbound_id'] if active else None
    exits, index = [], {}
    for row in kit_db.list_inbounds(conn):
        ip = row['exit_ip']
        if ip not in index:
            index[ip] = {'exit_ip': ip, 'label': kit_discovery.exit_label(ip, row['exit_tag']), 'inbounds': []}
            exits.append(index[ip])
        index[ip]['inbounds'].append(kit_db.public_inbound(
            row, kit_discovery.installable(row['network'], row['port'], ip), active=(row['id'] == active_id)))
    return {
        'nl': nl,
        'nl_key_mounted': kit_discovery.key_available(),
        'nl_host_trusted': trusted,
        'proxy': kit_apply.proxy_state(),
        'active': ({'inbound_id': active['inbound_id'], 'applied_at': active['applied_at']} if active else None),
        'exits': exits,
        'rules': {'count': len(kit_db.get_rules(conn)), 'match': kit_db.get_match(conn)},
        'job': kit_jobs.running_job(conn),
        'jobs': kit_db.list_jobs(conn, 10),
    }


class Api:
    """Handlers return (status, payload). `server` supplies runner, scans and the public port."""

    def __init__(self, server):
        self.server = server

    def _conn(self):
        return kit_db.connect()

    def _start(self, kind, inbound_id, fn):
        try:
            return self.server.runner.start(kind, inbound_id, fn)
        except kit_jobs.Busy:
            raise ApiError(409, 'Уже выполняется другая операция')

    def _nl_or_400(self, conn):
        nl = kit_db.get_nl(conn)
        if not nl:
            raise ApiError(400, 'Сначала укажите настройки NL')
        return nl

    def state(self, body):
        conn = self._conn()
        try:
            return 200, state_payload(conn)
        finally:
            conn.close()

    def put_nl(self, body):
        try:
            data = kit_discovery.validate_nl(body)
        except ValueError as exc:
            raise ApiError(400, str(exc))
        conn = self._conn()
        try:
            kit_db.save_nl(conn, data['host'], data['ssh_user'], data['ssh_port'])
            return 200, state_payload(conn)
        finally:
            conn.close()

    def hostkey_scan(self, body):
        conn = self._conn()
        try:
            nl = self._nl_or_400(conn)
        finally:
            conn.close()
        try:
            lines = kit_discovery.scan_host_key(nl['host'], nl['ssh_port'])
            keys = kit_discovery.fingerprints(lines)
        except RuntimeError as exc:
            raise ApiError(400, str(exc))
        except (OSError, subprocess.SubprocessError):
            raise ApiError(400, 'NL: ssh-keyscan не выполнен')
        known, _ = kit_discovery.paths()
        trusted = kit_discovery.is_trusted(nl['host'], nl['ssh_port'], known)
        scan_id = secrets.token_urlsafe(16)
        with self.server.scan_lock:
            self._prune_scans()
            self.server.scans[scan_id] = (lines, nl['host'], nl['ssh_port'], time.monotonic() + SCAN_TTL)
        return 200, {'scan_id': scan_id, 'host': nl['host'], 'port': nl['ssh_port'], 'keys': keys,
                     'already_trusted': trusted}

    def _prune_scans(self):
        now = time.monotonic()
        for key in [k for k, v in self.server.scans.items() if v[3] < now]:
            del self.server.scans[key]

    def hostkey_accept(self, body):
        scan_id = body.get('scan_id') if isinstance(body, dict) else None
        if not isinstance(scan_id, str) or not scan_id:
            raise ApiError(404, 'Проверка ключа не найдена или устарела')
        with self.server.scan_lock:
            self._prune_scans()
            entry = self.server.scans.pop(scan_id, None)
        if entry is None:
            raise ApiError(404, 'Проверка ключа не найдена или устарела')
        lines, host, port, _ = entry
        known, _ = kit_discovery.paths()
        kit_discovery.trust_host_key(lines, host, port, known)
        return 200, {'trusted': True}

    def discover(self, body):
        if not kit_discovery.key_available():
            raise ApiError(400, 'SSH-ключ не подключён: задайте KIT_SSH_KEY и перезапустите контейнеры')
        conn = self._conn()
        try:
            nl = self._nl_or_400(conn)
        finally:
            conn.close()
        job_id = self._start('discover', None, lambda job: kit_jobs.discover_job(job, nl))
        return 202, {'job_id': job_id}

    def check_one(self, inbound_id):
        conn = self._conn()
        try:
            nl = kit_db.get_nl(conn)
            row = kit_db.get_inbound(conn, inbound_id)
            if row is None:
                raise ApiError(404, 'Вход не найден')
            if kit_discovery.row_nl_host(row, nl) is None:
                raise ApiError(400, 'Сначала укажите настройки NL')
        finally:
            conn.close()
        job_id = self._start('check', inbound_id, lambda job: kit_jobs.check_job(job, nl, [inbound_id]))
        return 202, {'job_id': job_id}

    def check_all(self, body):
        conn = self._conn()
        try:
            nl = kit_db.get_nl(conn)
            ids = [r['id'] for r in kit_db.list_inbounds(conn)]
        finally:
            conn.close()
        if not ids:
            raise ApiError(400, 'Нет входов: сначала обнаружьте входы')
        job_id = self._start('check', None, lambda job: kit_jobs.check_job(job, nl, ids))
        return 202, {'job_id': job_id}

    def install(self, inbound_id, body):
        if not isinstance(body, dict) or body.get('confirm') is not True:
            raise ApiError(400, 'Подтвердите установку')
        conn = self._conn()
        try:
            nl = kit_db.get_nl(conn)
            row = kit_db.get_inbound(conn, inbound_id)
        finally:
            conn.close()
        if row is None or not row['present']:
            raise ApiError(404, 'Вход не найден')
        if not kit_discovery.installable(row['network'], row['port'], row['exit_ip']):
            raise ApiError(400, 'Этот вход нельзя установить')
        host = kit_discovery.row_nl_host(row, nl)
        if host is None:
            raise ApiError(400, 'Сначала укажите настройки NL')
        job_id = self._start('install', inbound_id, lambda job: kit_jobs.install_job(job, host, row))
        return 202, {'job_id': job_id}

    def exit_links(self, exit_ip):
        if not IPV4_RE.fullmatch(exit_ip):
            raise ApiError(404, 'Выход не найден')
        conn = self._conn()
        try:
            nl = kit_db.get_nl(conn)
            exit_rows = [r for r in kit_db.list_inbounds(conn) if r['exit_ip'] == exit_ip]
            if not exit_rows:
                raise ApiError(404, 'Выход не найден')
            items = kit_discovery.links_for_exit(conn, nl, exit_ip)
            if not items:
                raise ApiError(400, 'Сначала укажите настройки NL')
            return 200, {'exit_ip': exit_ip, 'items': items}
        finally:
            conn.close()

    def import_links(self, body):
        raw = body.get('links') if isinstance(body, dict) else None
        if not isinstance(raw, list) or not raw:
            raise ApiError(400, 'Нет ссылок')
        if len(raw) > kit_import.MAX_IMPORT_LINKS:
            raise ApiError(400, f'Не больше {kit_import.MAX_IMPORT_LINKS} ссылок')
        links = []
        for number, item in enumerate(raw, start=1):
            text = item.strip() if isinstance(item, str) else None
            if (text is None or not 1 <= len(text) <= kit_import.MAX_LINK_LEN
                    or not all(0x21 <= ord(ch) <= 0x7e for ch in text)):
                raise ApiError(400, f'Ссылка {number}: слишком длинная или недопустимые символы')
            links.append(text)
        rows, errors = kit_import.parse_links(links)
        if errors:
            raise ApiError(400, 'Ссылки не импортированы', extra={'errors': errors})
        conn = self._conn()
        try:
            if kit_jobs.running_job(conn):
                raise ApiError(409, 'Уже выполняется другая операция')
            result = kit_db.replace_imported(conn, rows)
        finally:
            conn.close()
        items = [{'index': n, 'port': r['port'], 'network': r['network'], 'exit_ip': r['exit_ip'], 'remark': r['remark']}
                 for n, r in enumerate(rows, start=1)]
        return 200, {'imported': result['total'], 'removed': result['removed'], 'items': items}

    def get_rules(self, body):
        conn = self._conn()
        try:
            return 200, {'rules': kit_db.get_rules(conn), 'match': kit_db.get_match(conn),
                         'types': list(kit_render.RULE_TYPES), 'policies': list(kit_render.POLICIES),
                         'system': [{'type': t, 'value': v, 'policy': p} for t, v, p, _ in kit_render.SYSTEM_RULES]}
        finally:
            conn.close()

    def put_rules(self, body):
        try:
            rules, match = kit_render.validate_rules(body)
        except ValueError as exc:
            raise ApiError(400, str(exc))
        conn = self._conn()
        try:
            active = kit_db.get_active(conn)
            inbound = kit_db.get_inbound(conn, active['inbound_id']) if active and active['inbound_id'] else None
            if inbound is None:
                if kit_jobs.running_job(conn):
                    raise ApiError(409, 'Уже выполняется другая операция')
                kit_db.replace_rules(conn, rules, match)
                return 200, {'saved': True, 'job_id': None}
        finally:
            conn.close()
        saved = threading.Event()
        job_id = self._start('apply_rules', None,
                             lambda job: (saved.wait(30), kit_jobs.apply_rules_job(job, None))[1])
        conn = self._conn()
        try:
            kit_db.replace_rules(conn, rules, match)
        finally:
            conn.close()
        saved.set()
        return 200, {'saved': True, 'job_id': job_id}

    def health(self, body):
        conn = self._conn()
        try:
            active = kit_db.get_active(conn)
            inbound = kit_db.get_inbound(conn, active['inbound_id']) if active and active['inbound_id'] else None
        finally:
            conn.close()
        expected = inbound['exit_ip'] if inbound else None
        proxy = os.environ.get('KIT_PROXY_URL', 'http://proxy:7890')
        try:
            r = subprocess.run(['curl', '--noproxy', '', '-fsS', '--max-time', '10', '-x', proxy,
                                'https://api.ipify.org'], capture_output=True, text=True,
                               env=kit_jobs.child_env(), timeout=13, stdin=subprocess.DEVNULL)
            ip = r.stdout.strip() if r.returncode == 0 and IPV4_RE.fullmatch(r.stdout.strip()) else ''
        except subprocess.SubprocessError:
            ip = ''
        ok = bool(ip) and (expected is None or ip == expected)
        return 200, {'ok': ok, 'ip': ip or None, 'expected_ip': expected, 'at': kit_db.now()}

    def proxy_logs(self, name):
        if name not in ('xray', 'mihomo'):
            raise ApiError(400, 'Неизвестный журнал')
        # Amendment 2d: logs live in kit-state (read-only for kit). The logs dir is opened with O_NOFOLLOW|O_DIRECTORY.
        try:
            fd = kit_apply.open_state_dir('logs')
        except kit_apply.RunFileError:
            fd = None
        tail = None
        if fd is not None:
            try:
                tail = kit_apply.read_regular_tail(f'{name}.log', dir_fd=fd)
            except kit_apply.RunFileError:
                tail = None
            finally:
                os.close(fd)
        lines = []
        if tail is not None:
            data, truncated = tail
            lines = data.decode('utf-8', errors='replace').splitlines()
            if truncated and lines:
                lines = lines[1:]  # the first line of a mid-file read may be partial
            lines = lines[-200:]
        conn = self._conn()
        try:
            secrets_list = [v for r in kit_db.list_inbounds(conn, present_only=False)
                            for v in (r['uuid'], r['pbk'], r['sid'])]
        finally:
            conn.close()
        redactor = kit_jobs.Redactor(secrets_list)
        return 200, {'lines': [redactor.apply(x) for x in lines], 'redacted': True}

    def job(self, job_id, offset):
        info = self.server.runner.read(job_id, offset)
        if info is None:
            raise ApiError(404, 'Задача не найдена')
        return 200, info


ROUTES = [
    ('GET', re.compile(r'/api/state'), lambda api, m, b, q: api.state(b)),
    ('PUT', re.compile(r'/api/nl'), lambda api, m, b, q: api.put_nl(b)),
    ('POST', re.compile(r'/api/nl/hostkey/scan'), lambda api, m, b, q: api.hostkey_scan(b)),
    ('POST', re.compile(r'/api/nl/hostkey/accept'), lambda api, m, b, q: api.hostkey_accept(b)),
    ('POST', re.compile(r'/api/discover'), lambda api, m, b, q: api.discover(b)),
    ('POST', re.compile(r'/api/check-all'), lambda api, m, b, q: api.check_all(b)),
    ('POST', re.compile(r'/api/inbounds/import'), lambda api, m, b, q: api.import_links(b)),
    ('POST', INBOUND_RE, lambda api, m, b, q: (api.check_one(int(m.group(1))) if m.group(2) == 'check'
                                                 else api.install(int(m.group(1)), b))),
    ('GET', EXIT_RE, lambda api, m, b, q: api.exit_links(m.group(1))),
    ('GET', re.compile(r'/api/rules'), lambda api, m, b, q: api.get_rules(b)),
    ('PUT', re.compile(r'/api/rules'), lambda api, m, b, q: api.put_rules(b)),
    ('POST', re.compile(r'/api/health'), lambda api, m, b, q: api.health(b)),
    ('GET', re.compile(r'/api/proxy/logs'), lambda api, m, b, q: api.proxy_logs(
        (q.get('name') or [''])[0])),
    ('GET', re.compile(r'/api/jobs/(\d{1,9})'), lambda api, m, b, q: api.job(
        int(m.group(1)), _offset(q))),
]


def _offset(query):
    try:
        return max(0, int((query.get('offset') or ['0'])[0]))
    except ValueError:
        return 0


def make_server(port, token_getter, bind='0.0.0.0', public_port=None):
    public = _public_port(public_port)

    class Handler(BaseHTTPRequestHandler):
        server_version = 'kit'
        sys_version = ''
        timeout = 30  # seconds per socket operation: a stalled client cannot hold a thread forever

        def log_request(self, code='-', size='-'):
            print(f'{self.command} {urlsplit(self.path).path} {code}', flush=True)

        def log_error(self, format, *args):
            pass

        def _send(self, status, body, content_type, extra=None):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            for name, value in kit_guard.SECURITY_HEADERS.items():
                self.send_header(name, value)
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)

        def _json(self, status, payload, extra=None):
            self._send(status, json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                       'application/json; charset=utf-8', extra)

        def _serve_static(self, path):
            static_map = self.server.static_map
            if path == '/' and '/' not in static_map:
                self._json(503, {'error': 'Интерфейс не собран'})
                return
            target = static_map.get(path)
            if target is None:
                self._json(404, {'error': 'Не найдено'})
                return
            try:
                body = target.read_bytes()
            except OSError:
                self._json(404, {'error': 'Не найдено'})
                return
            self._send(200, body, CONTENT_TYPES.get(target.suffix.lstrip('.'), 'application/octet-stream'))

        def _dispatch(self, method):
            parts = urlsplit(self.path)
            path = parts.path
            token = token_getter()
            headers = dict(self.headers.items())
            denied = kit_guard.check_request(method, self.path, headers, token, public)
            if denied is not None:
                status, reason = denied
                messages = {401: 'Нужен вход: выполните docker compose exec kit kit token', 403: 'Запрос отклонён',
                            404: 'Не найдено', 405: 'Метод не разрешён', 415: 'Ожидается JSON'}
                self._json(status, {'error': messages.get(status, reason)})
                return
            if method == 'GET' and path == '/login':
                query = parse_qs(parts.query)
                supplied = (query.get('t') or [''])[0]
                if token and hmac.compare_digest(supplied.encode('utf-8'), token.encode('utf-8')):
                    self._send(303, b'', 'text/plain; charset=utf-8',
                               {'Location': '/', 'Set-Cookie': kit_guard.session_cookie(token)})
                else:
                    self._json(403, {'error': 'Неверная ссылка входа. Выполните: docker compose exec kit kit token'})
                return
            if method in ('GET', 'HEAD') and (path == '/' or path.startswith('/assets/')):
                self._serve_static(path)
                return
            try:
                length = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                self._json(400, {'error': 'Некорректный Content-Length'})
                return
            if length < 0:
                self._json(400, {'error': 'Некорректный Content-Length'})
                return
            if length > BODY_LIMIT:
                self._json(413, {'error': 'Слишком большой запрос'})
                return
            body = {}
            if method != 'GET':
                raw = self.rfile.read(length) if length else b''
                try:
                    body = json.loads(raw.decode('utf-8') or '{}')
                except (ValueError, UnicodeDecodeError):
                    self._json(400, {'error': 'Некорректный JSON'})
                    return
            api = Api(self.server)
            for route_method, pattern, handler in ROUTES:
                match = pattern.fullmatch(path)
                if match and route_method == method:
                    try:
                        status, payload = handler(api, match, body, parse_qs(parts.query))
                    except ApiError as exc:
                        self._json(exc.status, {'error': exc.message, **exc.extra})
                        return
                    except Exception:
                        print('internal error', path, flush=True)
                        self._json(500, {'error': 'Внутренняя ошибка'})
                        return
                    self._json(status, payload)
                    return
            self._json(404, {'error': 'Не найдено'})

        def do_GET(self):
            self._dispatch('GET')

        def do_HEAD(self):
            self._dispatch('HEAD')

        def do_PUT(self):
            self._dispatch('PUT')

        def do_POST(self):
            self._dispatch('POST')

    server = ThreadingHTTPServer((bind, port), Handler)
    server.daemon_threads = True
    server.runner = kit_jobs.JobRunner()
    server.scans = {}
    server.scan_lock = threading.Lock()
    server.token_getter = token_getter
    server.static_map = build_static_map(Path(os.environ.get('KIT_WEB_ROOT', '/app/web')))
    return server


def main():
    kit_priv.prepare_and_drop()
    os.umask(0o077)
    conn = kit_db.connect()
    try:
        kit_db.mark_stale_jobs(conn)
    finally:
        conn.close()
    token_getter = make_token_getter()
    token_getter()  # creates the token file on first start; the token itself is never printed
    public = _public_port()
    server = make_server(4050, token_getter, bind='0.0.0.0', public_port=public)
    print('Ссылка для входа: docker compose exec kit kit token', flush=True)
    server.serve_forever()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
