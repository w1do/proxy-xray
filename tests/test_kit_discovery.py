import importlib, os, shutil, stat, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ui'))
kit_discovery = importlib.import_module('kit_discovery')
kit_nl = importlib.import_module('kit_nl')

HAS_KEYGEN = shutil.which('ssh-keygen') is not None


class ValidateNlTests(unittest.TestCase):
    def test_accept(self):
        self.assertEqual(kit_discovery.validate_nl({'host': '185.245.107.19', 'ssh_user': 'root', 'ssh_port': 22}),
                         {'host': '185.245.107.19', 'ssh_user': 'root', 'ssh_port': 22})
        self.assertEqual(kit_discovery.validate_nl({'host': 'nl.example.com'})['ssh_user'], 'root')

    def test_reject_without_echo(self):
        cases = [{'host': '-oProxyCommand=x'}, {'host': 'a b'}, {'host': 'h', 'ssh_user': 'R O O T'},
                 {'host': 'h', 'ssh_port': 0}, {'host': 'h', 'ssh_port': True}, {'host': 'h', 'ssh_port': 70000},
                 'nope']
        for case in cases:
            with self.assertRaises(ValueError) as ctx:
                kit_discovery.validate_nl(case)
            if isinstance(case, dict) and isinstance(case.get('host'), str) and case['host'] != 'h':
                self.assertNotIn(case['host'], str(ctx.exception))

    def test_key_path_is_gone(self):
        with self.assertRaises(ValueError):
            kit_discovery.validate_nl(None)
        self.assertNotIn('ssh_key_path', kit_discovery.validate_nl({'host': 'h', 'ssh_key_path': '/etc/x'}))


class InstallableTests(unittest.TestCase):
    def test_table(self):
        self.assertTrue(kit_discovery.installable('tcp', 2088, '149.28.240.154'))
        self.assertFalse(kit_discovery.installable('tcp', 443, '149.28.240.154'))
        self.assertFalse(kit_discovery.installable('ws', 8443, '149.28.240.154'))
        self.assertFalse(kit_discovery.installable('tcp', 2088, ''))

    def test_labels(self):
        self.assertEqual(kit_discovery.exit_label('149.28.240.154', ''), 'USA2')
        self.assertEqual(kit_discovery.exit_label('1.2.3.4', 'custom'), 'custom')
        self.assertEqual(kit_discovery.exit_label('1.2.3.4', ''), '1.2.3.4')

    def test_known_exit_warning(self):
        rows = [{'port': 2083, 'exit_ip': '149.28.240.154'}, {'port': 2088, 'exit_ip': '149.28.240.154'},
                {'port': 2083, 'exit_ip': '108.61.222.91'}]
        warnings = kit_discovery.known_exit_warnings(rows)
        self.assertEqual(len(warnings), 1)
        self.assertIn('NL:2083', warnings[0])
        self.assertIn('USA2', warnings[0])
        self.assertIn('2087-2090', warnings[0])


class FingerprintTests(unittest.TestCase):
    def test_parse_stubbed_keygen(self):
        out = ('256 SHA256:AbC+/def1234567890123456789012345678901234567 [185.245.107.19]:22 (ED25519)\n'
               '3072 SHA256:XyZ/zz0987654321098765432109876543210987654 [185.245.107.19]:22 (RSA)\n')
        with mock.patch.object(kit_discovery.subprocess, 'run') as run:
            run.return_value = mock.Mock(returncode=0, stdout=out, stderr='')
            got = kit_discovery.fingerprints(['x ssh-ed25519 AAA'])
        self.assertEqual(got, [{'type': 'ED25519', 'fingerprint': 'SHA256:AbC+/def1234567890123456789012345678901234567'},
                               {'type': 'RSA', 'fingerprint': 'SHA256:XyZ/zz0987654321098765432109876543210987654'}])

    def test_no_keys_raises(self):
        with mock.patch.object(kit_discovery.subprocess, 'run') as run:
            run.return_value = mock.Mock(returncode=1, stdout='', stderr='bad')
            with self.assertRaises(RuntimeError):
                kit_discovery.fingerprints(['x ssh-ed25519 AAA'])


@unittest.skipUnless(HAS_KEYGEN, 'ssh-keygen not installed')
class KnownHostsTests(unittest.TestCase):
    def test_trust_replaces_host_entries_and_sets_mode(self):
        with tempfile.TemporaryDirectory() as d:
            known = Path(d) / 'known_hosts'
            known.write_text('10.9.9.9 ssh-ed25519 AAAAOLD\n', encoding='utf-8')
            new_line = '185.245.107.19 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINEWKEYDATAFORTEST'
            self.assertFalse(kit_discovery.is_trusted('185.245.107.19', 22, known))
            kit_discovery.trust_host_key([new_line], '185.245.107.19', 22, known)
            text = known.read_text(encoding='utf-8')
            self.assertIn('AAAAINEWKEYDATAFORTEST', text)
            self.assertIn('10.9.9.9', text)
            self.assertEqual(stat.S_IMODE(os.stat(known).st_mode), 0o600)
            self.assertFalse(Path(str(known) + '.old').exists())

    def test_trust_creates_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            known = Path(d) / 'known_hosts'
            kit_discovery.trust_host_key(['[10.0.0.1]:2222 ssh-ed25519 AAAAFAKE'], '10.0.0.1', 2222, known)
            self.assertTrue(known.exists())
            self.assertEqual(stat.S_IMODE(os.stat(known).st_mode), 0o600)


class DiscoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ)
        os.environ['KIT_DATA_DIR'] = self.tmp.name
        os.environ['KIT_SSH_KEY_FILE'] = str(Path(self.tmp.name) / 'id_nl')

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        self.tmp.cleanup()

    def nl(self):
        return {'host': '185.245.107.19', 'ssh_user': 'root', 'ssh_port': 22}

    def test_missing_key_raises_before_ssh(self):
        with mock.patch.object(kit_nl, 'discover_rows') as dr:
            with self.assertRaises(kit_discovery.DiscoveryFailed) as ctx:
                kit_discovery.discover(self.nl())
            self.assertIn('KIT_SSH_KEY', str(ctx.exception))
            dr.assert_not_called()

    def test_error_mapping(self):
        Path(os.environ['KIT_SSH_KEY_FILE']).write_text('dummy')
        cases = [('Host key verification failed.', 'ключ хоста'),
                 ('Permission denied (publickey).', 'SSH-ключ не принят'),
                 ('Connection timed out', 'SSH не выполнен')]
        for stderr, expected in cases:
            with mock.patch.object(kit_nl, 'discover_rows', side_effect=kit_nl.DiscoveryError(255, stderr)):
                with self.assertRaises(kit_discovery.DiscoveryFailed) as ctx:
                    kit_discovery.discover(self.nl())
            self.assertIn(expected, str(ctx.exception))
            self.assertEqual(ctx.exception.detail, stderr)

    def test_success_normalizes_and_drops_unsupported(self):
        Path(os.environ['KIT_SSH_KEY_FILE']).write_text('dummy')
        raw = [{'port': 2088, 'uuid': 'u', 'exit': '149.28.240.154', 'network': 'tcp', 'email': 'e', 'flow': 'f',
                'pbk': 'p', 'sid': 's', 'sni': 'n', 'xhttp': {}, 'grpc': '', 'multi': False},
               {'port': 8443, 'uuid': 'u2', 'exit': '1.1.1.1', 'network': 'ws'}]
        with mock.patch.object(kit_nl, 'discover_rows', return_value=raw) as dr:
            rows = kit_discovery.discover(self.nl())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['port'], 2088)
        self.assertEqual(dr.call_args[0][2], os.environ['KIT_SSH_KEY_FILE'])
        self.assertTrue(dr.call_args[0][3].endswith('known_hosts'))


class KeyAndHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key = Path(self.tmp.name) / 'key'

    def tearDown(self):
        self.tmp.cleanup()

    def test_key_available(self):
        self.assertFalse(kit_discovery.key_available(self.key))
        self.key.write_bytes(b'')
        self.assertFalse(kit_discovery.key_available(self.key))
        self.key.write_bytes(b'x')
        self.assertTrue(kit_discovery.key_available(self.key))

    def test_row_nl_host(self):
        self.assertEqual(kit_discovery.row_nl_host({'source': 'import', 'nl_host': '185.0.2.10'}, None), '185.0.2.10')
        self.assertIsNone(kit_discovery.row_nl_host({'source': 'import', 'nl_host': ''}, {'host': 'x'}))
        self.assertEqual(kit_discovery.row_nl_host({'source': 'discover', 'nl_host': ''}, {'host': 'nl.example'}), 'nl.example')
        self.assertIsNone(kit_discovery.row_nl_host({'source': 'discover', 'nl_host': ''}, None))

    def test_links_for_exit_uses_per_row_host_and_skips_hostless(self):
        import kit_db
        conn = kit_db.connect(Path(self.tmp.name) / 'kit.db')
        try:
            conn.execute("INSERT INTO inbounds (port, uuid, exit_ip, network, pbk, sid, sni, discovered_at, source, nl_host, remark) "
                         "VALUES (2088, '11111111-2222-3333-4444-555555555501', '149.28.240.154', 'tcp', 'A', 'ab', 'x.example', "
                         "'2026-10-16T00:00:00Z', 'import', '185.0.2.10', 'imp')")
            conn.execute("INSERT INTO inbounds (port, uuid, exit_ip, network, pbk, sid, sni, discovered_at, source, nl_host, remark) "
                         "VALUES (2089, '11111111-2222-3333-4444-555555555502', '149.28.240.154', 'tcp', 'A', 'ab', 'x.example', "
                         "'2026-10-16T00:00:00Z', 'discover', '', 'disc')")
            conn.commit()
            with_nl = kit_discovery.links_for_exit(conn, {'host': '192.0.2.1'}, '149.28.240.154')
            self.assertEqual([i['port'] for i in with_nl], [2088, 2089])
            self.assertIn('@185.0.2.10:2088', with_nl[0]['link'])
            self.assertIn('@192.0.2.1:2089', with_nl[1]['link'])
            without_nl = kit_discovery.links_for_exit(conn, None, '149.28.240.154')
            self.assertEqual([i['port'] for i in without_nl], [2088])
        finally:
            conn.close()


if __name__ == '__main__':
    unittest.main()
