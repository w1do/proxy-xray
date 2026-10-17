"""Request guard for the local web UI. Pure functions, no sockets.

check_request() returns None when a request is allowed, otherwise (status, reason).
Rule order: Host allowlist, static/login, session cookie, Origin / JSON / Sec-Fetch-Site for writes.
"""
import hmac

SESSION_COOKIE = 'kit_session'

SECURITY_HEADERS = {
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer',
    'Content-Security-Policy': ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
                                "frame-ancestors 'none'"),
}


def allowed_hosts(port):
    return {f'127.0.0.1:{port}', f'localhost:{port}'}


def allowed_origins(port):
    return {f'http://127.0.0.1:{port}', f'http://localhost:{port}'}


def _header(headers, name):
    lname = name.lower()
    for key, value in headers.items():
        if key.lower() == lname:
            return value
    return None


def _session_value(cookie_header):
    for part in (cookie_header or '').split(';'):
        name, sep, value = part.strip().partition('=')
        if sep and name == SESSION_COOKIE:
            return value
    return None


def check_request(method, path, headers, token, port):
    path = path.split('?', 1)[0]
    host = _header(headers, 'Host')
    if not host or host not in allowed_hosts(port):
        return 403, 'host'
    if method in ('GET', 'HEAD') and (path == '/' or path.startswith('/assets/')):
        return None
    if path == '/login':
        return None if method == 'GET' else (405, 'method')
    if not path.startswith('/api/'):
        return 404, 'not found'
    session = _session_value(_header(headers, 'Cookie'))
    if session is None or not token or not hmac.compare_digest(session.encode('utf-8', 'replace'),
                                                                token.encode('utf-8')):
        return 401, 'session'
    if method != 'GET':
        origin = _header(headers, 'Origin')
        if not origin or origin not in allowed_origins(port):
            return 403, 'origin'
        content_type = _header(headers, 'Content-Type') or ''
        if not content_type.lower().startswith('application/json'):
            return 415, 'content-type'
        fetch_site = _header(headers, 'Sec-Fetch-Site')
        if fetch_site is not None and fetch_site != 'same-origin':
            return 403, 'fetch-site'
    return None


def session_cookie(token):
    return f'{SESSION_COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000'
