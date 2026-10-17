import importlib, json, os, sys, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ui'))
kit_nl = importlib.import_module('kit_nl')
FIXTURE = ROOT / 'tests' / 'fixtures' / 'ui' / 'xui_config.json'


class ImportTests(unittest.TestCase):
    def test_no_side_effects_and_remote_composition(self):
        self.assertEqual(kit_nl.REMOTE, kit_nl.REMOTE_PARSE + kit_nl.REMOTE_DRIVER)
        self.assertEqual(kit_nl.SKIP_PORTS, {443})
        for name in ('ENV', 'load_env', 'ssh_rows', 'main', 'make_block', 'make_install_command', 'EXIT_PORTS'):
            self.assertFalse(hasattr(kit_nl, name), name)


class ParseTests(unittest.TestCase):
    def test_rows_from_fixture(self):
        ns = {}
        exec(kit_nl.REMOTE_PARSE, ns)
        config = json.loads(FIXTURE.read_text(encoding='utf-8'))
        rows = ns['rows_from_config'](config, lambda priv: 'PUB-' + priv)
        self.assertEqual(len(rows), 5)
        self.assertFalse([r for r in rows if r['network'] == 'ws'])
        for row in rows:
            self.assertTrue(row['exit'])
            self.assertIn('flow', row)
            self.assertIn('grpc', row)
            self.assertTrue(row['pbk'].startswith('PUB-'))


class SshCommandTests(unittest.TestCase):
    def test_defaults(self):
        cmd = kit_nl.ssh_command('root@h')
        self.assertEqual(cmd[0], 'ssh')
        self.assertIn('StrictHostKeyChecking=yes', cmd)
        self.assertNotIn('-p', cmd)
        self.assertEqual(cmd[-4:], ['--', 'root@h', 'python3', '-'])

    def test_port_key_and_known_hosts(self):
        cmd = kit_nl.ssh_command('u@h', 2222, '/k/id', '/d/known_hosts')
        self.assertEqual(cmd[cmd.index('-p') + 1], '2222')
        i = cmd.index('-i')
        self.assertEqual(cmd[i + 1], '/k/id')
        self.assertIn('IdentitiesOnly=yes', cmd)
        self.assertIn('UserKnownHostsFile=/d/known_hosts', cmd)
        self.assertIn('GlobalKnownHostsFile=/dev/null', cmd)
        self.assertLess(cmd.index('GlobalKnownHostsFile=/dev/null'), cmd.index('--'))
        self.assertEqual(cmd[cmd.index('--') + 1], 'u@h')

    def test_discover_passes_arguments(self):
        with mock.patch.object(kit_nl.subprocess, 'run') as run:
            run.return_value = mock.Mock(returncode=0, stdout='[]', stderr='')
            self.assertEqual(kit_nl.discover_rows('u@h', 22, None, '/kh'), [])
            args = run.call_args[0][0]
            self.assertIn('UserKnownHostsFile=/kh', args)

    def test_discover_error_carries_stderr(self):
        with mock.patch.object(kit_nl.subprocess, 'run') as run:
            run.return_value = mock.Mock(returncode=255, stdout='', stderr='Permission denied')
            with self.assertRaises(kit_nl.DiscoveryError) as ctx:
                kit_nl.discover_rows('u@h')
            self.assertIn('Permission denied', ctx.exception.stderr)


class MakeLinkTests(unittest.TestCase):
    ROW = {'port': 2088, 'uuid': 'u-1', 'email': 'phone', 'sni': 'dl.google.com', 'sid': 'ab', 'pbk': 'PUB',
           'network': 'tcp', 'flow': 'xtls-rprx-vision', 'grpc': '', 'multi': False, 'xhttp': {},
           'exit': '149.28.240.154'}

    def test_tcp_link(self):
        link = kit_nl.make_link(self.ROW, '185.245.107.19')
        self.assertTrue(link.startswith('vless://u-1@185.245.107.19:2088?'))
        self.assertIn('type=tcp', link)
        self.assertIn('pbk=PUB', link)
        self.assertIn('fp=chrome', link)
        self.assertIn('flow=xtls-rprx-vision', link)

    def test_server_ip_required(self):
        with self.assertRaises(ValueError):
            kit_nl.make_link(self.ROW, '')


class CheckTests(unittest.TestCase):
    def test_requires_arguments(self):
        with self.assertRaises(ValueError):
            kit_nl.check({}, '', '/x')
        with self.assertRaises(ValueError):
            kit_nl.check({}, '1.2.3.4', '')

    def test_missing_binary(self):
        with self.assertRaises(RuntimeError):
            kit_nl.check({'network': 'tcp'}, '1.2.3.4', '/nonexistent/xray')


class RoutingPerClientTests(unittest.TestCase):
    def config(self, rules):
        reality = {'privateKey': 'PRIV', 'serverNames': ['dl.google.com'], 'shortIds': ['ab']}
        return {
            'inbounds': [{'tag': 'inbound-443', 'port': 443,
                          'settings': {'clients': [
                              {'id': 'uuid-main', 'email': 'main', 'flow': 'xtls-rprx-vision'},
                              {'id': 'uuid-s2', 'email': 'server-2@install-server.local', 'flow': 'xtls-rprx-vision'}]},
                          'streamSettings': {'network': 'tcp', 'security': 'reality', 'realitySettings': reality}}],
            'outbounds': [
                {'tag': 'usa1', 'settings': {'vnext': [{'address': '108.61.222.91', 'port': 443}]}},
                {'tag': 'usa2', 'settings': {'vnext': [{'address': '149.28.240.154', 'port': 443}]}}],
            'routing': {'rules': rules},
        }

    def parse(self, config):
        ns = {}
        exec(kit_nl.REMOTE_PARSE, ns)
        return {r['email']: r['exit'] for r in ns['rows_from_config'](config, lambda k: 'PUB-' + k)}

    def test_each_client_gets_its_own_exit(self):
        rules = [{'type': 'field', 'user': ['main'], 'outboundTag': 'usa1'},
                 {'type': 'field', 'user': ['server-2@install-server.local'], 'outboundTag': 'usa2'}]
        self.assertEqual(self.parse(self.config(rules)),
                         {'main': '108.61.222.91', 'server-2@install-server.local': '149.28.240.154'})

    def test_inbound_rule_is_fallback_when_no_user_rule(self):
        rules = [{'type': 'field', 'inboundTag': ['inbound-443'], 'outboundTag': 'usa2'}]
        self.assertEqual(set(self.parse(self.config(rules)).values()), {'149.28.240.154'})

    def test_inbound_rule_before_user_rule_wins(self):
        rules = [{'type': 'field', 'inboundTag': ['inbound-443'], 'outboundTag': 'usa2'},
                 {'type': 'field', 'user': ['main'], 'outboundTag': 'usa1'}]
        got = self.parse(self.config(rules))
        self.assertEqual(got['main'], '149.28.240.154')
        self.assertEqual(got['server-2@install-server.local'], '149.28.240.154')

    def test_user_rule_before_inbound_rule_wins(self):
        rules = [{'type': 'field', 'user': ['main'], 'outboundTag': 'usa1'},
                 {'type': 'field', 'inboundTag': ['inbound-443'], 'outboundTag': 'usa2'}]
        got = self.parse(self.config(rules))
        self.assertEqual(got['main'], '108.61.222.91')
        self.assertEqual(got['server-2@install-server.local'], '149.28.240.154')

    def test_no_matching_rule_gives_empty_exit(self):
        rules = [{'type': 'field', 'user': ['someone-else'], 'outboundTag': 'usa1'}]
        rows = self.rows(self.config(rules))
        self.assertTrue(all(r['exit'] == '' and r['exit_tag'] == '' for r in rows))

    def test_rule_for_other_inbound_is_not_applied(self):
        rules = [{'type': 'field', 'inboundTag': ['inbound-other'], 'outboundTag': 'usa1'}]
        rows = self.rows(self.config(rules))
        self.assertTrue(all(r['exit'] == '' for r in rows))

    def test_balancer_rule_without_outbound_is_skipped(self):
        rules = [{'type': 'field', 'user': ['main'], 'balancerTag': 'bal'},
                 {'type': 'field', 'user': ['main'], 'outboundTag': 'usa1'}]
        got = self.parse(self.config(rules))
        self.assertEqual(got['main'], '108.61.222.91')

    def rows(self, config):
        ns = {}
        exec(kit_nl.REMOTE_PARSE, ns)
        return ns['rows_from_config'](config, lambda k: 'PUB-' + k)


class SshHardeningTests(unittest.TestCase):
    def test_argv_contains_hardening_options(self):
        cmd = kit_nl.ssh_command('root@h')
        for option in ('UpdateHostKeys=no', 'PasswordAuthentication=no', 'ForwardAgent=no',
                       'BatchMode=yes', 'StrictHostKeyChecking=yes'):
            self.assertIn(option, cmd)
        self.assertEqual(cmd[cmd.index('--') + 1], 'root@h')


if __name__ == '__main__':
    unittest.main()
