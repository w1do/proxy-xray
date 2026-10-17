import importlib, os, sys, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('KIT_ROOT', str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
proxy_cli = importlib.import_module('proxy_cli')
proxy_update = importlib.import_module('proxy_update')


class ClientCommandTests(unittest.TestCase):
    def record(self, argv_fn):
        calls = []

        def fake_run(argv):
            calls.append(list(argv))
            return 0

        with mock.patch.object(proxy_cli, 'run', side_effect=fake_run):
            code = argv_fn()
        return code, calls

    def test_status_is_docker_only(self):
        code, calls = self.record(lambda: proxy_cli.main(['status']))
        self.assertEqual(code, 0)
        self.assertEqual(calls, [['docker', 'compose', 'ps'],
                                 ['docker', 'compose', 'exec', '-T', 'kit', 'kit', 'status']])

    def test_logs_default_all_services(self):
        code, calls = self.record(lambda: proxy_cli.main(['logs']))
        self.assertEqual(calls, [['docker', 'compose', 'logs', '--tail', '50', 'kit'],
                                 ['docker', 'compose', 'logs', '--tail', '50', 'proxy']])

    def test_logs_single_service_and_lines(self):
        code, calls = self.record(lambda: proxy_cli.main(['logs', 'proxy', '-n', '7']))
        self.assertEqual(calls, [['docker', 'compose', 'logs', '--tail', '7', 'proxy']])

    def test_logs_rejects_unknown_service(self):
        with self.assertRaises(SystemExit):
            proxy_cli.build_parser().parse_args(['logs', 'nl'])

    def test_check_uses_kit_check(self):
        code, calls = self.record(lambda: proxy_cli.main(['check']))
        self.assertEqual(calls, [['docker', 'compose', 'exec', '-T', 'kit', 'kit', 'check']])

    def test_client_commands_never_invoke_ssh_or_host_services(self):
        for argv in (['status'], ['logs'], ['logs', 'kit'], ['check']):
            _, calls = self.record(lambda argv=argv: proxy_cli.main(argv))
            for call in calls:
                self.assertNotIn('ssh', call)
                self.assertNotIn('systemctl', call)
                self.assertNotIn('launchctl', call)
                self.assertEqual(call[:2], ['docker', 'compose'])

    def test_client_commands_do_not_call_remote_helpers(self):
        with mock.patch.object(proxy_cli, 'run_remote', side_effect=AssertionError('ssh used')):
            with mock.patch.object(proxy_cli, 'run', return_value=0):
                for argv in (['status'], ['logs'], ['check']):
                    self.assertEqual(proxy_cli.main(argv), 0)


class ServerCommandTests(unittest.TestCase):
    def test_server_status_uses_remote_helper_with_systemctl_only_there(self):
        scripts = []

        def fake_remote(node, script, timeout=120):
            scripts.append((node, script))
            return 0, 'ACTIVE=active\nVERSION=Xray 26.10.10', ''

        with mock.patch.object(proxy_cli, 'run_remote', side_effect=fake_remote), \
                mock.patch('builtins.print'):
            self.assertEqual(proxy_cli.main(['server', 'status']), 0)
        self.assertEqual([node for node, _ in scripts], ['nl', 'usa1', 'usa2'])
        self.assertIn('systemctl is-active x-ui', scripts[0][1])
        self.assertIn('/usr/local/x-ui/bin/xray-linux-amd64 version', scripts[0][1])

    def test_server_logs_selects_nodes(self):
        seen = []

        def fake_remote(node, script, timeout=120):
            seen.append((node, script))
            return 0, 'line', ''

        with mock.patch.object(proxy_cli, 'run_remote', side_effect=fake_remote), mock.patch('builtins.print'):
            proxy_cli.main(['server', 'logs', 'usa1', '-n', '5'])
        self.assertEqual(seen, [('usa1', 'journalctl -u xray -n 5 --no-pager 2>&1')])

    def test_server_logs_rejects_unknown_node(self):
        with self.assertRaises(RuntimeError):
            proxy_cli.selected(['bogus'])


class ProxyUpdateCheckTests(unittest.TestCase):
    def test_update_checks_through_docker_kit_check_from_repo_root(self):
        import argparse
        args = argparse.Namespace(version='26.10.10', servers=['usa1'], yes=True)

        def fake_remote(node, script, timeout=120):
            return 0, 'RESULT old=26.9.1 new=26.10.10', ''

        with mock.patch.object(proxy_update.subprocess, 'run', return_value=mock.Mock(returncode=0)) as run, \
                mock.patch('builtins.print'):
            code = proxy_update.update(args, fake_remote, lambda names: names)
        self.assertEqual(code, 0)
        run.assert_called_once_with(['docker', 'compose', 'exec', '-T', 'kit', 'kit', 'check'], cwd=str(ROOT))

    def test_no_vless_script_is_referenced(self):
        source = (ROOT / 'tools' / 'proxy_update.py').read_text(encoding='utf-8')
        self.assertNotIn('vless.sh', source)


if __name__ == '__main__':
    unittest.main()
