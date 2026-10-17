import importlib, http.client, json, os, re, sys, tempfile, threading, time, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ui'))
server = importlib.import_module('server')
kit_db = importlib.import_module('kit_db')
kit_discovery = importlib.import_module('kit_discovery')

PUBLIC = 14050
TOKEN = 'test-token-' + 'z' * 24
EXIT = '149.28.240.154'
NL_HOST = '185.245.107.19'
SECRET_UUID = 'aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb'
SECRET_PBK = 'S' * 43


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.env = dict(os.environ)
        os.environ.update({'KIT_DATA_DIR': str(Path(cls.tmp.name) / 'data'),
                           'KIT_GEN_DIR': str(Path(cls.tmp.name) / 'run'),
                           'KIT_STATE_DIR': str(Path(cls.tmp.name) / 'state'),
                           'KIT_SSH_KEY_FILE': str(Path(cls.tmp.name) / 'no-key'),
                           'KIT_PUBLIC_PORT': str(PUBLIC)})
        Path(cls.tmp.name, 'run').mkdir(mode=0o700)
        Path(cls.tmp.name, 'state', 'logs').mkdir(parents=True, mode=0o700)
        web = Path(cls.tmp.name) / 'web'
        (web / 'assets').mkdir(parents=True)
        (web / 'index.html').write_text('<!doctype html><title>t</title>', encoding='utf-8')
        (web / 'assets' / 'index-abc.js').write_text('console.log(1);', encoding='utf-8')
        (web / 'assets' / 'sub').mkdir()
        (web / 'assets' / 'sub' / 'x.js').write_text('x', encoding='utf-8')
        os.environ['KIT_WEB_ROOT'] = str(web)
        cls.srv = server.make_server(0, lambda: TOKEN, bind='127.0.0.1', public_port=PUBLIC)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        conn = kit_db.connect()
        kit_db.upsert_inbounds(conn, [{'port': 2088, 'uuid': SECRET_UUID, 'exit_ip': EXIT, 'exit_tag': 'USA2',
                                       'network': 'tcp', 'remark': 'phone', 'flow': 'xtls-rprx-vision',
                                       'pbk': SECRET_PBK, 'sid': 'a1b2', 'sni': 'dl.google.com',
                                       'xhttp_json': '{}', 'grpc_service': '', 'grpc_multi': 0}])
        conn.close()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        os.environ.clear()
        os.environ.update(cls.env)
        cls.tmp.cleanup()

    def req(self, method, path, body=None, cookie=True, host=f'127.0.0.1:{PUBLIC}', ctype='application/json'):
        headers = {'Host': host}
        if cookie:
            headers['Cookie'] = f'kit_session={TOKEN}'
        data = None
        if method != 'GET':
            headers['Origin'] = f'http://127.0.0.1:{PUBLIC}'
            if ctype:
                headers['Content-Type'] = ctype
            data = json.dumps(body if body is not None else {}).encode('utf-8')
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp.status, dict(resp.getheaders()), raw

    def js(self, *args, **kw):
        status, headers, raw = self.req(*args, **kw)
        return status, headers, (json.loads(raw) if raw and raw[:1] in b'{[' else raw)

    def test_root_and_assets_are_public(self):
        status, headers, raw = self.req('GET', '/', cookie=False)
        self.assertEqual(status, 200)
        self.assertIn('text/html', headers.get('Content-Type', ''))
        status, headers, _ = self.req('GET', '/assets/index-abc.js', cookie=False)
        self.assertEqual(status, 200)
        self.assertIn('text/javascript', headers.get('Content-Type', ''))

    def test_only_exact_map_hits_are_served(self):
        for path in ('/assets/../index.html', '/assets/%2e%2e/x', '/assets/sub/x.js', '/assets/missing.js',
                     '/src/main.jsx', '/static/app.js'):
            self.assertEqual(self.req('GET', path, cookie=False)[0], 404, path)

    def test_missing_index_returns_503(self):
        empty = Path(self.tmp.name) / 'empty'
        empty.mkdir()
        os.environ['KIT_WEB_ROOT'] = str(empty)
        try:
            srv = server.make_server(0, lambda: TOKEN, bind='127.0.0.1', public_port=PUBLIC)
        finally:
            os.environ['KIT_WEB_ROOT'] = str(Path(self.tmp.name) / 'web')
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            conn = http.client.HTTPConnection('127.0.0.1', srv.server_address[1], timeout=10)
            conn.request('GET', '/', headers={'Host': f'127.0.0.1:{PUBLIC}'})
            resp = conn.getresponse()
            self.assertEqual(resp.status, 503)
            self.assertIn('Интерфейс не собран', resp.read().decode('utf-8'))
            conn.close()
        finally:
            srv.shutdown()
            srv.server_close()

    def test_security_headers_present(self):
        status, headers, _ = self.req('GET', '/', cookie=False)
        self.assertEqual(headers.get('Cache-Control'), 'no-store')
        self.assertEqual(headers.get('Content-Security-Policy'),
                         "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; "
                         "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.assertNotIn('Access-Control-Allow-Origin', headers)

    def test_host_and_auth(self):
        self.assertEqual(self.req('GET', '/', host='evil.example:14050', cookie=False)[0], 403)
        self.assertEqual(self.req('GET', '/api/state', host='127.0.0.1:4050')[0], 403)
        self.assertEqual(self.req('GET', '/api/state', cookie=False)[0], 401)

    def test_login(self):
        status, headers, _ = self.req('GET', '/login?t=wrong', cookie=False)
        self.assertEqual(status, 403)
        status, headers, _ = self.req('GET', f'/login?t={TOKEN}', cookie=False)
        self.assertEqual(status, 303)
        self.assertIn('Max-Age=2592000', headers.get('Set-Cookie', ''))
        self.assertEqual(headers.get('Location'), '/')

    def test_state_has_no_secrets(self):
        status, _, raw = self.req('GET', '/api/state')
        self.assertEqual(status, 200)
        text = raw.decode('utf-8')
        for secret in (SECRET_UUID, SECRET_PBK, 'vless://', 'a1b2'):
            self.assertNotIn(secret, text)
        body = json.loads(text)
        self.assertEqual(body['proxy']['state'], 'down')
        self.assertEqual(body['exits'][0]['exit_ip'], EXIT)

    def test_nl_validation_and_links(self):
        status, _, _ = self.js('PUT', '/api/nl', {'host': '-bad', 'ssh_user': 'root', 'ssh_port': 22})
        self.assertEqual(status, 400)
        status, _, body = self.js('PUT', '/api/nl', {'host': NL_HOST, 'ssh_user': 'root', 'ssh_port': 22})
        self.assertEqual(status, 200)
        status, headers, body = self.js('GET', f'/api/exits/{EXIT}/links')
        self.assertEqual(status, 200)
        self.assertEqual(headers.get('Cache-Control'), 'no-store')
        self.assertTrue(body['items'][0]['link'].startswith('vless://'))
        self.assertEqual(body['items'][0]['network_label'], 'TCP+Vision')
        self.assertEqual(self.js('GET', '/api/exits/9.9.9.9/links')[0], 404)
        self.assertEqual(self.req('GET', f'/api/exits/{EXIT}/links', cookie=False)[0], 401)

    def test_rules_get_put(self):
        status, _, body = self.js('GET', '/api/rules')
        self.assertEqual(status, 200)
        self.assertEqual(body['match'], 'PROXY')
        self.assertEqual(len(body['rules']), 13)
        payload = {'rules': [{'type': 'DOMAIN-SUFFIX', 'value': 'example.org', 'policy': 'DIRECT',
                              'no_resolve': False, 'enabled': True, 'note': ''}], 'match': 'PROXY'}
        status, _, body = self.js('PUT', '/api/rules', payload)
        self.assertEqual((status, body['saved'], body['job_id']), (200, True, None))
        bad = {'rules': [{'type': 'DOMAIN', 'value': 'a,b', 'policy': 'DIRECT'}], 'match': 'PROXY'}
        self.assertEqual(self.js('PUT', '/api/rules', bad)[0], 400)
        self.assertEqual(self.req('PUT', '/api/rules', payload, ctype='text/plain')[0], 415)

    def test_install_needs_confirm(self):
        conn = kit_db.connect()
        inbound_id = kit_db.list_inbounds(conn)[0]['id']
        conn.close()
        self.assertEqual(self.js('POST', f'/api/inbounds/{inbound_id}/install', {})[0], 400)
        self.assertEqual(self.js('POST', f'/api/inbounds/{inbound_id}/install', {'confirm': False})[0], 400)

    def test_hostkey_scan_accept_flow(self):
        self.js('PUT', '/api/nl', {'host': NL_HOST, 'ssh_user': 'root', 'ssh_port': 22})
        keys = [{'type': 'ED25519', 'fingerprint': 'SHA256:fake'}]
        with mock.patch.object(kit_discovery, 'scan_host_key', return_value=['h ssh-ed25519 AAAA']), \
                mock.patch.object(kit_discovery, 'fingerprints', return_value=keys), \
                mock.patch.object(kit_discovery, 'trust_host_key') as trust:
            status, _, body = self.js('POST', '/api/nl/hostkey/scan', {})
            self.assertEqual(status, 200)
            self.assertEqual(body['keys'], keys)
            scan_id = body['scan_id']
            status, _, _ = self.js('POST', '/api/nl/hostkey/accept', {'scan_id': scan_id})
            self.assertEqual(status, 200)
            trust.assert_called_once()
            self.assertEqual(self.js('POST', '/api/nl/hostkey/accept', {'scan_id': scan_id})[0], 404)
            self.assertEqual(self.js('POST', '/api/nl/hostkey/accept', {'scan_id': 'nope'})[0], 404)

    def test_health_uses_proxy_and_expected_ip(self):
        fake = mock.Mock(returncode=0, stdout='9.9.9.9\n', stderr='')
        with mock.patch.object(server.subprocess, 'run', return_value=fake):
            status, _, body = self.js('POST', '/api/health', {})
        self.assertEqual(status, 200)
        self.assertEqual(body['ip'], '9.9.9.9')
        self.assertIsNone(body['expected_ip'])
        self.assertTrue(body['ok'])

    def test_job_unknown_and_logs(self):
        self.assertEqual(self.js('GET', '/api/jobs/999999')[0], 404)
        status, _, body = self.js('GET', '/api/proxy/logs?name=xray')
        self.assertEqual(status, 200)
        self.assertEqual(body['lines'], [])
        self.assertEqual(self.js('GET', '/api/proxy/logs?name=other')[0], 400)

    def test_proxy_logs_refuses_symlinked_logs_dir(self):
        real = Path(self.tmp.name) / 'elsewhere-logs'
        real.mkdir()
        (real / 'xray.log').write_text('SECRET-LOG-LINE\n', encoding='utf-8')
        logs = Path(self.tmp.name) / 'state' / 'logs'
        for entry in logs.iterdir():
            entry.unlink()
        logs.rmdir()
        os.symlink(real, logs)
        try:
            status, _, raw = self.req('GET', '/api/proxy/logs?name=xray')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(raw)['lines'], [])
            self.assertNotIn(b'SECRET-LOG-LINE', raw)
        finally:
            os.unlink(logs)
            logs.mkdir(mode=0o700)

    def test_head_root_has_security_headers(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        try:
            conn.request('HEAD', '/', headers={'Host': f'127.0.0.1:{PUBLIC}'})
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.getheader('Content-Security-Policy'),
                             "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; "
                             "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            resp.read()
        finally:
            conn.close()

    def logs_dir(self):
        d = Path(self.tmp.name) / 'state' / 'logs'
        os.makedirs(d, mode=0o700, exist_ok=True)
        return d

    def test_log_symlink_returns_empty_and_no_marker(self):
        target = Path(self.tmp.name) / 'planted-log.txt'
        target.write_text('MARKER-SECRET line\n', encoding='utf-8')
        link = self.logs_dir() / 'xray.log'
        try:
            os.symlink(target, link)
            status, _, raw = self.req('GET', '/api/proxy/logs?name=xray')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(raw)['lines'], [])
            self.assertNotIn(b'MARKER-SECRET', raw)
        finally:
            link.unlink(missing_ok=True)

    def test_log_fifo_returns_empty_without_hanging(self):
        fifo = self.logs_dir() / 'xray.log'
        try:
            os.mkfifo(fifo)
            status, _, raw = self.req('GET', '/api/proxy/logs?name=xray')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(raw)['lines'], [])
        finally:
            fifo.unlink(missing_ok=True)

    def test_large_log_returns_last_200_whole_lines(self):
        path = self.logs_dir() / 'xray.log'
        total = 100000
        try:
            with open(path, 'w', encoding='utf-8') as f:
                for i in range(1, total + 1):
                    f.write(f'{i:07d}xxx\n')
            self.assertGreater(path.stat().st_size, 1024 * 1024 - 100000)
            status, _, raw = self.req('GET', '/api/proxy/logs?name=xray')
            self.assertEqual(status, 200)
            lines = json.loads(raw)['lines']
            self.assertLessEqual(len(lines), 200)
            self.assertEqual(lines[-1], f'{total:07d}xxx')
            self.assertTrue(all(re.fullmatch(r'\d{7}xxx', line) for line in lines), 'partial line returned')
        finally:
            path.unlink(missing_ok=True)


class StartupTokenTests(unittest.TestCase):
    def test_main_does_not_print_the_token(self):
        import contextlib, io
        from unittest import mock
        buf = io.StringIO()
        fake_server = mock.Mock()
        with mock.patch.object(server.kit_priv, 'prepare_and_drop'), \
                mock.patch.object(server.kit_db, 'connect', return_value=mock.Mock()), \
                mock.patch.object(server.kit_db, 'mark_stale_jobs'), \
                mock.patch.object(server, 'make_token_getter', return_value=lambda: 'SECRET-TOKEN-VALUE'), \
                mock.patch.object(server, 'make_server', return_value=fake_server), \
                contextlib.redirect_stdout(buf):
            server.main()
        out = buf.getvalue()
        self.assertIn('Ссылка для входа: docker compose exec kit kit token', out)
        self.assertNotIn('SECRET-TOKEN-VALUE', out)
        self.assertNotIn('login?t=', out)
        fake_server.serve_forever.assert_called_once()

    def test_source_has_no_token_url_print(self):
        source = (ROOT / 'ui' / 'server.py').read_text(encoding='utf-8')
        self.assertNotIn('login?t=', source)

IMPORT_UUID = '11111111-2222-3333-4444-555555555555'
IMPORT_PBK = 'A' * 43
IMPORT_SID = 'abcd'
IMPORT_SNI = 'www.example.com'
IMPORT_HOST = '185.0.2.10'


def import_link(port=2088, label_exit='149.28.240.154', remark='phone'):
    import kit_nl
    row = {'port': port, 'uuid': IMPORT_UUID, 'email': remark, 'sni': IMPORT_SNI, 'sid': IMPORT_SID, 'pbk': IMPORT_PBK,
           'network': 'tcp', 'flow': 'xtls-rprx-vision', 'grpc': '', 'multi': False, 'xhttp': {}, 'exit': label_exit}
    return kit_nl.make_link(row, IMPORT_HOST)


def import_grpc_link(port=2089):
    import kit_nl
    row = {'port': port, 'uuid': IMPORT_UUID, 'email': 'grpc-x', 'sni': IMPORT_SNI, 'sid': IMPORT_SID, 'pbk': IMPORT_PBK,
           'network': 'grpc', 'flow': '', 'grpc': 'svc', 'multi': True, 'xhttp': {}, 'exit': '149.28.240.154'}
    return kit_nl.make_link(row, IMPORT_HOST)


def import_xhttp_link(port=2087):
    import kit_nl
    row = {'port': port, 'uuid': IMPORT_UUID, 'email': 'xh', 'sni': IMPORT_SNI, 'sid': IMPORT_SID, 'pbk': IMPORT_PBK,
           'network': 'xhttp', 'flow': '', 'grpc': '', 'multi': False,
           'xhttp': {'path': '/dl', 'mode': 'auto'}, 'exit': '149.28.240.154'}
    return kit_nl.make_link(row, IMPORT_HOST)


class ImportServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.env = dict(os.environ)
        base = Path(cls.tmp.name)
        for name in ('data', 'gen', 'state'):
            (base / name).mkdir(mode=0o700)
        os.environ.update({'KIT_DATA_DIR': str(base / 'data'), 'KIT_GEN_DIR': str(base / 'gen'),
                           'KIT_STATE_DIR': str(base / 'state'), 'KIT_SSH_KEY_FILE': str(base / 'no-key'),
                           'KIT_PUBLIC_PORT': str(PUBLIC)})
        cls.srv = server.make_server(0, lambda: TOKEN, bind='127.0.0.1', public_port=PUBLIC)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        os.environ.clear()
        os.environ.update(cls.env)
        cls.tmp.cleanup()

    def call(self, method, path, body=None, cookie=True):
        headers = {'Host': f'127.0.0.1:{PUBLIC}'}
        if cookie:
            headers['Cookie'] = f'kit_session={TOKEN}'
        data = None
        if method != 'GET':
            headers.update({'Origin': f'http://127.0.0.1:{PUBLIC}', 'Content-Type': 'application/json'})
            data = json.dumps(body if body is not None else {}).encode('utf-8')
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        try:
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            return resp.status, raw
        finally:
            conn.close()

    def test_import_tcp_grpc_xhttp_three_links_and_no_secret_in_response(self):
        links = [import_link(2088), import_grpc_link(2089), import_xhttp_link(2087)]
        status, raw = self.call('POST', '/api/inbounds/import', {'links': links})
        self.assertEqual(status, 200)
        body = json.loads(raw)
        self.assertEqual(body['imported'], 3)
        self.assertEqual(sorted(i['network'] for i in body['items']), ['grpc', 'tcp', 'xhttp'])
        for secret in (IMPORT_UUID, IMPORT_PBK, IMPORT_SID, IMPORT_SNI, IMPORT_HOST, 'vless://'):
            self.assertNotIn(secret.encode(), raw)
    def test_bad_link_stores_nothing_and_does_not_echo(self):
        before = self.call('GET', '/api/state')[1]
        marker = 'MARKERnoecho7'
        base = import_link(2088)
        head, sep, fragment = base.partition('#')
        bad = head + f'&{marker}=1' + sep + fragment  # the marker is an unknown query key inside the bad link
        status, raw = self.call('POST', '/api/inbounds/import', {'links': [import_link(2089, remark='ok'), bad]})
        self.assertEqual(status, 400)
        body = json.loads(raw)
        self.assertEqual(body['errors'], [{'index': 2, 'error': 'неизвестный параметр'}])
        self.assertNotIn(marker.encode(), raw)
        self.assertEqual(self.call('GET', '/api/state')[1], before)
    def test_empty_and_too_many_links_are_rejected(self):
        status, raw = self.call('POST', '/api/inbounds/import', {'links': []})
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(raw)['error'], 'Нет ссылок')
        links = [import_link(2000 + n) for n in range(41)]
        self.assertEqual(len(set(links)), 41)
        status, raw = self.call('POST', '/api/inbounds/import', {'links': links})
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(raw)['error'], 'Не больше 40 ссылок')
    def test_oversized_body_is_413(self):
        status, _ = self.call('POST', '/api/inbounds/import', {'links': ['x' * 17000]})
        self.assertEqual(status, 413)

    def test_import_without_cookie_is_401(self):
        self.assertEqual(self.call('POST', '/api/inbounds/import', {'links': [import_link()]}, cookie=False)[0], 401)

    def test_running_job_blocks_import_with_409(self):
        import kit_db
        conn = kit_db.connect()
        job_id = kit_db.create_job(conn, 'discover', None)
        conn.close()
        try:
            status, _ = self.call('POST', '/api/inbounds/import', {'links': [import_link(2090)]})
            self.assertEqual(status, 409)
        finally:
            conn = kit_db.connect()
            kit_db.finish_job(conn, job_id, 'ok', None, 'done')
            conn.close()

    def test_import_then_install_never_uses_ssh(self):
        import subprocess
        from unittest import mock
        import kit_apply, kit_discovery, kit_nl
        real_run, real_popen = subprocess.run, subprocess.Popen

        def forbid(argv, *a, **kw):
            name = Path(argv[0]).name if argv else ''
            if name in ('ssh', 'ssh-keyscan', 'ssh-keygen'):
                raise AssertionError('ssh used')

        def guarded_run(argv, *a, **kw):
            forbid(argv)
            return real_run(argv, *a, **kw)

        class GuardedPopen(real_popen):
            def __init__(self, argv, *a, **kw):
                forbid(argv)
                super().__init__(argv, *a, **kw)

        def boom(*a, **kw):
            raise AssertionError('ssh used')

        patches = [mock.patch.object(kit_nl, 'discover_rows', boom), mock.patch.object(kit_nl, 'ssh_command', boom),
                   mock.patch.object(kit_discovery, 'scan_host_key', boom), mock.patch.object(kit_discovery, 'discover', boom),
                   mock.patch.object(subprocess, 'run', guarded_run), mock.patch.object(subprocess, 'Popen', GuardedPopen),
                   mock.patch.object(kit_apply, 'validate_bundle', lambda *a, **kw: None),
                   mock.patch.object(kit_apply, 'wait_applied', lambda g, timeout=25: {'state': 'running', 'generation': g}),
                   mock.patch.object(kit_apply, 'verify_exit', lambda expected, tries=3: (True, '149.28.240.154'))]
        for p in patches:
            p.start()
        try:
            status, raw = self.call('POST', '/api/inbounds/import', {'links': [import_link(2088)]})
            self.assertEqual(status, 200)
            state = json.loads(self.call('GET', '/api/state')[1])
            inbound = [i for e in state['exits'] for i in e['inbounds'] if i['port'] == 2088][0]
            self.assertFalse(state['nl_key_mounted'])
            status, raw = self.call('POST', f"/api/inbounds/{inbound['id']}/install", {'confirm': True})
            self.assertEqual(status, 202)
            job_id = json.loads(raw)['job_id']
            info = {}
            for _ in range(300):
                info = json.loads(self.call('GET', f'/api/jobs/{job_id}?offset=0')[1])
                if info['status'] != 'running':
                    break
                time.sleep(0.1)
            self.assertEqual(info['status'], 'ok', info.get('summary'))
            gen = json.loads((Path(os.environ['KIT_GEN_DIR']) / 'xray-client.json').read_text())
            vnext = gen['outbounds'][0]['settings']['vnext'][0]
            self.assertEqual((vnext['address'], vnext['port']), (IMPORT_HOST, 2088))
            state = json.loads(self.call('GET', '/api/state')[1])
            self.assertEqual(state['active']['inbound_id'], inbound['id'])
            self.assertFalse(state['nl_key_mounted'])
            for secret in (IMPORT_UUID, IMPORT_PBK, IMPORT_SID, IMPORT_SNI, 'vless://'):
                self.assertNotIn(secret, self.call('GET', '/api/state')[1].decode())
            status, raw = self.call('GET', '/api/exits/149.28.240.154/links')
            self.assertEqual(status, 200)
            self.assertIn(f'@{IMPORT_HOST}:2088', json.loads(raw)['items'][0]['link'])
            status, raw = self.call('PUT', '/api/rules', {'rules': [], 'match': 'PROXY'})
            self.assertEqual(status, 200)
            rules_job = json.loads(raw)['job_id']
            for _ in range(300):
                info = json.loads(self.call('GET', f'/api/jobs/{rules_job}?offset=0')[1])
                if info['status'] != 'running':
                    break
                time.sleep(0.1)
            self.assertEqual(info['status'], 'ok', info.get('summary'))
            status, raw = self.call('POST', '/api/discover', {})
            self.assertEqual(status, 400)
            self.assertIn('SSH-ключ не подключён', json.loads(raw)['error'])
        finally:
            for p in patches:
                p.stop()


class RequestHardeningTests(ServerTests):
    def raw(self, method, path, headers):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            conn.request(method, path, headers=headers)
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            conn.close()

    def base_headers(self):
        return {'Host': f'127.0.0.1:{PUBLIC}', 'Cookie': f'kit_session={TOKEN}',
                'Origin': f'http://127.0.0.1:{PUBLIC}', 'Content-Type': 'application/json'}

    def test_post_login_is_not_allowed(self):
        status, _ = self.raw('POST', f'/login?t={TOKEN}', {'Host': f'127.0.0.1:{PUBLIC}'})
        self.assertEqual(status, 405)

    def test_negative_content_length_is_rejected_without_hanging(self):
        headers = dict(self.base_headers(), **{'Content-Length': '-1'})
        status, _ = self.raw('PUT', '/api/rules', headers)
        self.assertEqual(status, 400)

    def test_non_numeric_content_length_is_rejected(self):
        headers = dict(self.base_headers(), **{'Content-Length': 'abc'})
        status, _ = self.raw('PUT', '/api/rules', headers)
        self.assertEqual(status, 400)

    def test_oversized_content_length_is_rejected(self):
        headers = dict(self.base_headers(), **{'Content-Length': str(server.BODY_LIMIT + 1)})
        status, _ = self.raw('PUT', '/api/rules', headers)
        self.assertEqual(status, 413)


if __name__ == '__main__':
    unittest.main()
