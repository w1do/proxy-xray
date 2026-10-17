import importlib, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ui'))
kit_guard = importlib.import_module('kit_guard')

PUBLIC = 14050
TOKEN = 'tok-' + 'x' * 20


def headers(host=f'127.0.0.1:{PUBLIC}', cookie=None, origin=None, ctype='application/json', fetch=None):
    h = {'Host': host}
    if cookie is not None:
        h['Cookie'] = cookie
    if origin is not None:
        h['Origin'] = origin
    if ctype is not None:
        h['Content-Type'] = ctype
    if fetch is not None:
        h['Sec-Fetch-Site'] = fetch
    return h


class GuardTests(unittest.TestCase):
    def test_host_must_match_public_port(self):
        self.assertEqual(kit_guard.check_request('GET', '/', headers(f'127.0.0.1:{PUBLIC}'), TOKEN, PUBLIC), None)
        self.assertEqual(kit_guard.check_request('GET', '/', headers('127.0.0.1:4050'), TOKEN, PUBLIC)[0], 403)
        self.assertEqual(kit_guard.check_request('GET', '/', headers('evil.example:14050'), TOKEN, PUBLIC)[0], 403)
        self.assertEqual(kit_guard.check_request('GET', '/', headers(None), TOKEN, PUBLIC)[0], 403)

    def test_localhost_host_allowed(self):
        self.assertIsNone(kit_guard.check_request('GET', '/', headers(f'localhost:{PUBLIC}'), TOKEN, PUBLIC))

    def test_assets_and_login_are_public(self):
        self.assertIsNone(kit_guard.check_request('GET', '/assets/index-abc.js', headers(), TOKEN, PUBLIC))
        self.assertIsNone(kit_guard.check_request('HEAD', '/', headers(), TOKEN, PUBLIC))
        self.assertIsNone(kit_guard.check_request('GET', '/login?t=abc', headers(), TOKEN, PUBLIC))

    def test_old_static_prefix_is_not_public(self):
        self.assertEqual(kit_guard.check_request('GET', '/static/app.js', headers(), TOKEN, PUBLIC)[0], 404)

    def test_api_needs_cookie(self):
        self.assertEqual(kit_guard.check_request('GET', '/api/state', headers(), TOKEN, PUBLIC)[0], 401)
        self.assertEqual(kit_guard.check_request('GET', '/api/state', headers(cookie='kit_session=bad'), TOKEN,
                                                 PUBLIC)[0], 401)
        self.assertIsNone(kit_guard.check_request('GET', '/api/state',
                                                  headers(cookie=f'kit_session={TOKEN}'), TOKEN, PUBLIC))

    def test_write_checks(self):
        cookie = f'kit_session={TOKEN}'
        origin = f'http://127.0.0.1:{PUBLIC}'
        ok = headers(cookie=cookie, origin=origin)
        self.assertIsNone(kit_guard.check_request('PUT', '/api/nl', ok, TOKEN, PUBLIC))
        self.assertEqual(kit_guard.check_request('PUT', '/api/nl', headers(cookie=cookie), TOKEN, PUBLIC)[0], 403)
        bad_origin = headers(cookie=cookie, origin='http://127.0.0.1:4050')
        self.assertEqual(kit_guard.check_request('PUT', '/api/nl', bad_origin, TOKEN, PUBLIC)[0], 403)
        no_json = headers(cookie=cookie, origin=origin, ctype='text/plain')
        self.assertEqual(kit_guard.check_request('POST', '/api/discover', no_json, TOKEN, PUBLIC)[0], 415)
        cross = headers(cookie=cookie, origin=origin, fetch='cross-site')
        self.assertEqual(kit_guard.check_request('POST', '/api/discover', cross, TOKEN, PUBLIC)[0], 403)

    def test_unknown_path(self):
        self.assertEqual(kit_guard.check_request('GET', '/nope', headers(), TOKEN, PUBLIC)[0], 404)

    def test_cookie_flags(self):
        cookie = kit_guard.session_cookie(TOKEN)
        for flag in ('HttpOnly', 'SameSite=Strict', 'Path=/', 'Max-Age=2592000'):
            self.assertIn(flag, cookie)
        self.assertNotIn('Secure', cookie)

    def test_csp_exact(self):
        self.assertEqual(kit_guard.SECURITY_HEADERS['Content-Security-Policy'], "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

    def test_csp_inline_only_for_styles(self):
        directives = dict(part.strip().split(' ', 1) for part in kit_guard.SECURITY_HEADERS['Content-Security-Policy'].split(';'))
        self.assertEqual(directives['script-src'], "'self'")
        self.assertEqual(directives['style-src'], "'self' 'unsafe-inline'")
        self.assertNotIn("'unsafe-inline'", directives['script-src'])
        self.assertNotIn("'unsafe-eval'", ''.join(directives.values()))

    def test_csp_and_no_cors(self):
        csp = kit_guard.SECURITY_HEADERS['Content-Security-Policy']
        self.assertIn("script-src 'self'", csp)
        self.assertIn('img-src', csp)
        self.assertIn('data:', csp)
        for name in kit_guard.SECURITY_HEADERS:
            self.assertFalse(name.lower().startswith('access-control-'))


if __name__ == '__main__':
    unittest.main()
