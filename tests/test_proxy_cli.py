import contextlib, importlib, io, os, re, stat, sys, tempfile, unittest
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


class ProxyEnvTests(unittest.TestCase):
    BEGIN = '# >>> mihomo-proxy-kit >>>'
    END = '# <<< mihomo-proxy-kit <<<'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.env = dict(os.environ)
        os.environ['HOME'] = str(self.home)
        os.environ['SHELL'] = '/bin/bash'

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        self.tmp.cleanup()

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = proxy_cli.main(['env', *argv])
        return code, out.getvalue()

    def test_on_creates_block_once(self):
        rc = self.home / '.bashrc'
        self.assertEqual(self.run_cli('on')[0], 0)
        self.assertEqual(rc.read_text().count(self.BEGIN), 1)
        self.run_cli('on')
        text = rc.read_text()
        self.assertEqual(text.count(self.BEGIN), 1)
        self.assertEqual(text.count(self.END), 1)
        self.assertIn('export http_proxy=http://127.0.0.1:7890\n', text)
        self.assertIn('export no_proxy=localhost,127.0.0.1,::1\n', text)

    def test_on_replaces_block_in_place_with_new_port(self):
        rc = self.home / '.bashrc'
        rc.write_text('before\n')
        self.run_cli('on')
        self.run_cli('on', '--port', '7891')
        text = rc.read_text()
        self.assertEqual(text.count(self.BEGIN), 1)
        self.assertIn('http://127.0.0.1:7891', text)
        self.assertNotIn('7890', text)
        self.assertTrue(text.startswith('before\n'))

    def test_off_removes_only_the_block_and_keeps_other_lines_byte_identical(self):
        rc = self.home / '.bashrc'
        prefix = 'alias ll="ls -la"\r\nexport EDITOR=vim  # комментарий\n'
        suffix = '\nexport PATH="$HOME/bin:$PATH"'
        rc.write_bytes((prefix + '# >>> mihomo-proxy-kit >>>\nexport x=1\n# <<< mihomo-proxy-kit <<<\n' + suffix).encode('utf-8'))
        code, out = self.run_cli('off')
        self.assertEqual(code, 0)
        self.assertEqual(rc.read_bytes(), (prefix + suffix).encode('utf-8'))

    def test_off_without_block_changes_nothing(self):
        rc = self.home / '.bashrc'
        original = b'export A=1\n'
        rc.write_bytes(original)
        code, out = self.run_cli('off')
        self.assertEqual(code, 0)
        self.assertIn('Блока proxy', out)
        self.assertEqual(rc.read_bytes(), original)

    def test_block_without_end_marker_is_refused(self):
        rc = self.home / '.bashrc'
        original = (self.BEGIN + '\nexport A=1\n').encode('utf-8')
        rc.write_bytes(original)
        with self.assertRaises(RuntimeError):
            self.run_cli('on')
        self.assertEqual(rc.read_bytes(), original)

    def test_symlinked_rc_is_refused_and_real_file_unchanged(self):
        real = self.home / 'dotfiles-real-rc'
        real.write_text('export A=1\n')
        rc = self.home / '.bashrc'
        os.symlink(real, rc)
        with self.assertRaises(RuntimeError) as ctx:
            self.run_cli('on')
        self.assertIn(str(real), str(ctx.exception))
        self.assertTrue(rc.is_symlink())
        self.assertEqual(real.read_text(), 'export A=1\n')

    def test_zsh_vs_bash_target_selection(self):
        os.environ['SHELL'] = '/bin/zsh'
        self.run_cli('on')
        self.assertTrue((self.home / '.zshrc').exists())
        self.assertFalse((self.home / '.bashrc').exists())
        os.environ['SHELL'] = '/bin/bash'
        self.run_cli('on', '--shell', 'bash')
        self.assertTrue((self.home / '.bashrc').exists())
        self.assertIn('.bashrc', self.run_cli('status', '--shell', 'bash')[1])

    def test_status_outputs(self):
        self.assertIn('нет', self.run_cli('status')[1])
        self.run_cli('on')
        self.assertIn('есть', self.run_cli('status')[1])
        self.run_cli('off')
        self.assertIn('нет', self.run_cli('status')[1])

    def test_mode_is_kept(self):
        rc = self.home / '.bashrc'
        rc.write_text('export A=1\n')
        os.chmod(rc, 0o600)
        self.run_cli('on')
        self.assertEqual(stat.S_IMODE(os.stat(rc).st_mode), 0o600)

    def test_port_range_is_checked(self):
        with self.assertRaises(RuntimeError):
            self.run_cli('on', '--port', '70000')

    def test_env_commands_never_run_docker_or_ssh(self):
        with mock.patch.object(proxy_cli, 'run', side_effect=AssertionError('docker used')), \
                mock.patch.object(proxy_cli, 'run_remote', side_effect=AssertionError('ssh used')):
            self.run_cli('on')
            self.run_cli('status')
            self.run_cli('off')


class HelpTextTests(unittest.TestCase):
    def all_parsers(self):
        """Every (name, parser) pair in the command tree, depth first."""
        import argparse
        found = []

        def walk(parser, prefix):
            for action in parser._actions:
                if isinstance(action, argparse._SubParsersAction):
                    for name, sub in action.choices.items():
                        path = f"{prefix} {name}".strip()
                        found.append((path, sub))
                        walk(sub, path)

        walk(proxy_cli.build_parser(), '')
        return found

    def test_every_subcommand_has_description_and_example(self):
        parsers = self.all_parsers()
        names = [name for name, _ in parsers]
        for expected in ('status', 'logs', 'check', 'env', 'env on', 'env off', 'env status',
                         'server', 'server status', 'server logs', 'server update'):
            self.assertIn(expected, names)
        for name, parser in parsers:
            with self.subTest(command=name):
                text = parser.description or ''
                self.assertTrue(text.strip(), 'empty description')
                self.assertTrue('Пример' in text or 'proxy ' in text, 'no example')

    def test_help_lines_are_under_80_characters(self):
        for name, parser in self.all_parsers():
            for line in (parser.description or '').splitlines():
                self.assertLess(len(line), 80, f'{name}: {line!r}')

    def test_help_exits_zero_without_running_anything(self):
        commands = [['--help'], ['status', '--help'], ['logs', '--help'], ['check', '--help'],
                    ['env', '--help'], ['env', 'on', '--help'], ['env', 'off', '--help'],
                    ['env', 'status', '--help'], ['server', '--help'], ['server', 'status', '--help'],
                    ['server', 'logs', '--help'], ['server', 'update', '--help']]
        for argv in commands:
            with self.subTest(argv=argv):
                with mock.patch.object(proxy_cli, 'run', side_effect=AssertionError('docker used')), \
                        mock.patch.object(proxy_cli, 'run_remote', side_effect=AssertionError('ssh used')), \
                        mock.patch.object(proxy_cli.subprocess, 'run', side_effect=AssertionError('subprocess used')), \
                        mock.patch('builtins.print'), \
                        mock.patch('sys.stdout', new_callable=io.StringIO):
                    with self.assertRaises(SystemExit) as ctx:
                        proxy_cli.main(argv)
                self.assertEqual(ctx.exception.code, 0)


class HelpLocalizationTests(unittest.TestCase):
    URLS = ['https://w1do.ru', 'https://t.me/W1DO_DIGITAL', 'https://www.youtube.com/@w1do_digital']
    ENGLISH = ['usage:', 'options:', 'positional arguments', 'show this help', 'subcommands:']

    class FakeTTY(io.StringIO):
        def __init__(self, tty):
            super().__init__()
            self._tty = tty

        def isatty(self):
            return self._tty

    def help_texts(self):
        texts = {'': proxy_cli.build_parser().format_help()}
        for name, parser in HelpTextTests().all_parsers():
            texts[name] = parser.format_help()
        return texts

    def test_help_has_no_english_labels(self):
        with mock.patch('sys.stdout', self.FakeTTY(False)):
            for name, text in self.help_texts().items():
                with self.subTest(command=name or 'proxy'):
                    for word in self.ENGLISH:
                        self.assertNotIn(word, text)
                    self.assertIn('использование:', text)
                    self.assertIn('показать эту справку и выйти', text)

    def test_contacts_only_in_top_help(self):
        with mock.patch('sys.stdout', self.FakeTTY(False)):
            texts = self.help_texts()
        for url in self.URLS:
            self.assertEqual(texts[''].count(url), 1)
        for name, text in texts.items():
            if name:
                self.assertNotIn('https://', text, name)

    def test_plain_urls_and_no_escape_bytes_when_not_a_tty(self):
        with mock.patch('sys.stdout', self.FakeTTY(False)):
            text = proxy_cli.build_parser().format_help()
        for url in self.URLS:
            self.assertIn(url, text)
        self.assertNotIn('\x1b', text)

    def test_tty_wraps_each_url_in_osc8_and_keeps_visible_text(self):
        import re
        with mock.patch('sys.stdout', self.FakeTTY(True)), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('NO_COLOR', None)
            text = proxy_cli.build_parser().format_help()
        for url in self.URLS:
            self.assertIn(f'\x1b]8;;{url}\x1b\\{url}\x1b]8;;\x1b\\', text)
        visible = re.sub(r'\x1b\]8;;[^\x1b]*\x1b\\', '', text)
        for url in self.URLS:
            self.assertIn(url, visible)

    def test_no_color_disables_hyperlinks_on_a_tty(self):
        with mock.patch('sys.stdout', self.FakeTTY(True)), mock.patch.dict(os.environ, {'NO_COLOR': '1'}):
            text = proxy_cli.build_parser().format_help()
        self.assertNotIn('\x1b', text)
        for url in self.URLS:
            self.assertIn(url, text)

    def test_argparse_errors_are_in_russian(self):
        err = io.StringIO()
        with mock.patch('sys.stderr', err), self.assertRaises(SystemExit) as ctx:
            proxy_cli.build_parser().parse_args(['logs', 'nl'])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn('неверный выбор', err.getvalue())
        self.assertIn('ошибка:', err.getvalue())
        self.assertNotIn('invalid choice', err.getvalue())


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
