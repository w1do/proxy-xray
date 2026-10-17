import importlib, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ui'))
kit_render = importlib.import_module('kit_render')

GOLDEN_NL = '149.28.240.154'


def db_row(**kw):
    row = {'port': 2088, 'uuid': '11111111-2222-3333-4444-555555555555', 'pbk': 'A' * 43, 'sid': 'ab', 'sni': 'dl.google.com',
           'network': 'tcp', 'flow': 'xtls-rprx-vision', 'grpc_service': '', 'xhttp_json': '{}'}
    row.update(kw)
    return row


class XrayGoldenTests(unittest.TestCase):
    def test_xhttp_2087(self):
        row = db_row(port=2087, network='xhttp', flow='', xhttp_json='{"path": "/dl", "mode": "auto"}')
        self.assertEqual(kit_render.xray_client_config(GOLDEN_NL, row), {
            'log': {'loglevel': 'warning'},
            'inbounds': [{'listen': '127.0.0.1', 'port': 18080, 'protocol': 'socks', 'settings': {'udp': True}}],
            'outbounds': [{'protocol': 'vless',
                           'settings': {'vnext': [{'address': GOLDEN_NL, 'port': 2087,
                                                   'users': [{'id': '11111111-2222-3333-4444-555555555555', 'encryption': 'none'}]}]},
                           'streamSettings': {'network': 'xhttp', 'security': 'reality',
                                              'xhttpSettings': {'path': '/dl', 'mode': 'auto'},
                                              'realitySettings': {'serverName': 'dl.google.com',
                                                                  'fingerprint': 'firefox', 'password': 'A' * 43,
                                                                  'shortId': 'ab'}}}]})

    def test_tcp_2088_has_vision_flow_only(self):
        cfg = kit_render.xray_client_config(GOLDEN_NL, db_row())
        user = cfg['outbounds'][0]['settings']['vnext'][0]['users'][0]
        self.assertEqual(user, {'id': '11111111-2222-3333-4444-555555555555', 'encryption': 'none', 'flow': 'xtls-rprx-vision'})
        self.assertNotIn('xhttpSettings', cfg['outbounds'][0]['streamSettings'])
        self.assertNotIn('grpcSettings', cfg['outbounds'][0]['streamSettings'])

    def test_grpc_2089(self):
        row = db_row(port=2089, network='grpc', flow='', grpc_service='svc')
        cfg = kit_render.xray_client_config(GOLDEN_NL, row)
        stream = cfg['outbounds'][0]['streamSettings']
        self.assertEqual(stream['grpcSettings'], {'serviceName': 'svc'})
        self.assertNotIn('flow', cfg['outbounds'][0]['settings']['vnext'][0]['users'][0])
        self.assertNotIn('xhttpSettings', stream)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            kit_render.xray_client_config('', db_row())
        with self.assertRaises(ValueError):
            kit_render.xray_client_config(GOLDEN_NL, db_row(pbk=''))
        with self.assertRaises(ValueError):
            kit_render.xray_client_config(GOLDEN_NL, db_row(network='grpc', grpc_service=''))


class MihomoTextTests(unittest.TestCase):
    def test_header_and_order(self):
        text = kit_render.mihomo_config([], 'PROXY')
        self.assertTrue(text.startswith('mixed-port: 7890\nallow-lan: true\nbind-address: "*"\n'))
        rules = [l for l in text.splitlines() if l.startswith('  - ') and ('DOMAIN' in l or 'MATCH' in l or 'GEO' in l)]
        self.assertEqual(rules[0], '  - DOMAIN,api.ipify.org,PROXY')
        self.assertEqual(rules[-1], '  - MATCH,PROXY')

    def test_disabled_rules_omitted(self):
        rows = [{'type': 'DOMAIN-SUFFIX', 'value': 'off.example', 'policy': 'DIRECT', 'no_resolve': False,
                 'enabled': False, 'note': ''},
                {'type': 'DOMAIN-SUFFIX', 'value': 'on.example', 'policy': 'DIRECT', 'no_resolve': False,
                 'enabled': True, 'note': ''}]
        text = kit_render.mihomo_config(rows, 'REJECT')
        self.assertNotIn('off.example', text)
        self.assertIn('  - DOMAIN-SUFFIX,on.example,DIRECT', text)
        self.assertTrue(text.rstrip().endswith('  - MATCH,REJECT'))

    def test_proxy_and_dns_blocks(self):
        text = kit_render.mihomo_config([], 'PROXY')
        self.assertIn('proxies:\n  - name: USA\n    type: socks5\n    server: 127.0.0.1\n    port: 18080\n    udp: true\n',
                      text)
        self.assertIn('dns:\n  enable: true\n  enhanced-mode: fake-ip\n  fake-ip-range: 198.18.0.1/16\n'
                      '  respect-rules: true\n', text)
        self.assertIn('    - https://1.1.1.1/dns-query\n    - https://8.8.8.8/dns-query\n', text)

    def test_yaml_if_available(self):
        try:
            import yaml
        except ImportError:
            self.skipTest('PyYAML не установлен')
        data = yaml.safe_load(kit_render.mihomo_config([], 'PROXY'))
        self.assertEqual(data['proxies'][0], {'name': 'USA', 'type': 'socks5', 'server': '127.0.0.1',
                                              'port': 18080, 'udp': True})
        self.assertEqual(data['dns']['fake-ip-range'], '198.18.0.1/16')


class DefaultRulesTests(unittest.TestCase):
    def test_default_rules(self):
        self.assertEqual(len(kit_render.DEFAULT_RULES), 13)
        self.assertEqual(kit_render.DEFAULT_RULES[11], ('DOMAIN-SUFFIX', 'xn--p1ai', 'DIRECT', False))
        self.assertEqual(kit_render.DEFAULT_RULES[10], ('DOMAIN-SUFFIX', 'ru', 'DIRECT', False))
        self.assertEqual(kit_render.DEFAULT_MATCH, 'PROXY')
        self.assertEqual(kit_render.KNOWN_EXITS['108.61.222.91']['ports'], (2083, 2084, 2085, 2086))
        self.assertEqual(kit_render.KNOWN_EXITS['149.28.240.154']['ports'], (2087, 2088, 2089, 2090))


class ValidateRuleTests(unittest.TestCase):
    def rule(self, **kw):
        base = {'type': 'DOMAIN-SUFFIX', 'value': 'example.com', 'policy': 'DIRECT'}
        base.update(kw)
        return kit_render.validate_rule(base)

    def test_idn_converted(self):
        self.assertEqual(self.rule(value='рф')['value'], 'xn--p1ai')

    def test_rejects_bad_values_without_echo(self):
        bad = ['a,b', 'x\ny', 'a#b', 'a"b', "a'b", '', 'x' * 254, 'has space.com']
        for value in bad:
            with self.assertRaises(ValueError) as ctx:
                self.rule(value=value)
            if value:
                self.assertNotIn(value, str(ctx.exception))

    def test_geoip_and_cidr(self):
        self.assertEqual(self.rule(type='GEOIP', value='ru', no_resolve=True)['value'], 'RU')
        self.assertTrue(self.rule(type='GEOIP', value='ru', no_resolve=True)['no_resolve'])
        self.assertEqual(self.rule(type='IP-CIDR', value='10.1.2.3/8')['value'], '10.0.0.0/8')
        with self.assertRaises(ValueError):
            self.rule(type='GEOIP', value='x')
        with self.assertRaises(ValueError):
            self.rule(type='IP-CIDR', value='not-an-ip')

    def test_no_resolve_dropped_for_domain(self):
        self.assertFalse(self.rule(no_resolve=True)['no_resolve'])

    def test_bad_type_policy_and_note(self):
        with self.assertRaises(ValueError):
            self.rule(type='IP')
        with self.assertRaises(ValueError):
            self.rule(policy='MAYBE')
        with self.assertRaises(ValueError):
            self.rule(note='x' * 201)

    def test_rule_line(self):
        self.assertEqual(kit_render.rule_line('GEOIP', 'PRIVATE', 'DIRECT', True),
                         '  - GEOIP,PRIVATE,DIRECT,no-resolve')


class ValidateRulesTests(unittest.TestCase):
    def test_limits_and_duplicates(self):
        ok = {'rules': [{'type': 'DOMAIN', 'value': 'a.example', 'policy': 'PROXY'}], 'match': 'DIRECT'}
        rules, match = kit_render.validate_rules(ok)
        self.assertEqual((len(rules), match), (1, 'DIRECT'))
        with self.assertRaises(ValueError):
            kit_render.validate_rules({'rules': [], 'match': 'NOPE'})
        dup = {'rules': [{'type': 'DOMAIN', 'value': 'a.example', 'policy': 'PROXY'}] * 2, 'match': 'PROXY'}
        with self.assertRaises(ValueError):
            kit_render.validate_rules(dup)
        many = {'rules': [{'type': 'DOMAIN', 'value': f'h{i}.example', 'policy': 'PROXY'} for i in range(501)],
                'match': 'PROXY'}
        with self.assertRaises(ValueError):
            kit_render.validate_rules(many)


@unittest.skipUnless(shutil.which(os.environ.get('KIT_MIHOMO_BIN', 'mihomo')) or
                     os.access(os.path.expanduser('~/.local/bin/mihomo'), os.X_OK), 'mihomo binary not available')
class MihomoBinaryTests(unittest.TestCase):
    def test_mihomo_t(self):
        binary = os.environ.get('KIT_MIHOMO_BIN') or os.path.expanduser('~/.local/bin/mihomo')
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'config.yaml'
            path.write_text(kit_render.mihomo_config([], 'PROXY'))
            r = subprocess.run([binary, '-t', '-d', d, '-f', str(path)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


@unittest.skipUnless(os.environ.get('KIT_XRAY_BIN') or os.access(os.path.expanduser('~/.local/bin/xray'), os.X_OK),
                     'xray binary not available')
class XrayBinaryTests(unittest.TestCase):
    def test_xray_test_on_golden_configs(self):
        import json
        binary = os.environ.get('KIT_XRAY_BIN') or os.path.expanduser('~/.local/bin/xray')
        import base64
        key = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode()
        rows = [db_row(port=2087, network='xhttp', flow='', pbk=key, xhttp_json='{"path": "/dl", "mode": "auto"}'),
                db_row(pbk=key), db_row(port=2089, network='grpc', flow='', pbk=key, grpc_service='svc')]
        for row in rows:
            with tempfile.TemporaryDirectory() as d:
                path = Path(d) / 'xray.json'
                path.write_text(json.dumps(kit_render.xray_client_config(GOLDEN_NL, row)))
                r = subprocess.run([binary, 'run', '-test', '-config', str(path)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class Amendment2dRenderTests(unittest.TestCase):
    def test_mihomo_config_has_no_providers_ui_or_auto_update(self):
        text = kit_render.mihomo_config([], 'PROXY')
        for word in ('proxy-providers', 'rule-providers', 'external-ui', 'external-controller'):
            self.assertNotIn(word, text)
        self.assertNotIn('geo-auto-update: true', text)

    def test_xray_config_has_no_file_logs(self):
        cfg = kit_render.xray_client_config(GOLDEN_NL, db_row())
        self.assertEqual(cfg['log'], {'loglevel': 'warning'})


class Amendment2eRenderTests(unittest.TestCase):
    def test_bad_values_are_rejected(self):
        cases = [{'uuid': 'not-a-uuid'}, {'pbk': 'A' * 42}, {'pbk': 'A' * 42 + '+'}, {'sid': 'abc'},
                 {'sid': 'ab' * 9}, {'sni': 'bad_name'}, {'uuid': '11111111-2222-3333-4444-55555555555'}]
        for override in cases:
            with self.subTest(override=override):
                with self.assertRaises(ValueError) as ctx:
                    kit_render.xray_client_config(GOLDEN_NL, db_row(**override))
                self.assertEqual(str(ctx.exception), 'Недопустимые параметры входа')

    def test_bad_xhttp_path_is_rejected(self):
        row = db_row(network='xhttp', flow='', xhttp_json='{"path": "/a b", "mode": "auto"}')
        with self.assertRaises(ValueError):
            kit_render.xray_client_config(GOLDEN_NL, row)

    def test_constants_have_exact_patterns(self):
        self.assertEqual(kit_render.UUID_RE.pattern, r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
        self.assertEqual(kit_render.PBK_RE.pattern, r'[A-Za-z0-9_-]{43}')
        self.assertEqual(kit_render.SID_RE.pattern, r'(?:[0-9a-f]{2}){0,8}')
        self.assertEqual(kit_render.XHTTP_PATH_RE.pattern, r'/[A-Za-z0-9._~/-]{0,255}')
        self.assertEqual(kit_render.GRPC_SERVICE_RE.pattern, r'[A-Za-z0-9._/-]{1,128}')
        self.assertEqual(kit_render.XHTTP_MODES, ('auto', 'packet-up', 'stream-up', 'stream-one'))
        self.assertIn('chrome', kit_render.FINGERPRINTS)
        self.assertIn('randomized', kit_render.FINGERPRINTS)


if __name__ == '__main__':
    unittest.main()
