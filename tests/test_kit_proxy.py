import importlib, json, os, stat, sys, tempfile, threading, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ui'))
kit_proxy = importlib.import_module('kit_proxy')


class ProxyHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_generation(self):
        self.assertIsNone(kit_proxy.read_generation(self.d / 'missing.json'))
        bad = self.d / 'bad.json'
        bad.write_text('{not json')
        self.assertIsNone(kit_proxy.read_generation(bad))
        wrong = self.d / 'wrong.json'
        wrong.write_text(json.dumps({'generation': '1', 'xray_sha256': '', 'mihomo_sha256': ''}))
        self.assertIsNone(kit_proxy.read_generation(wrong))
        ok = self.d / 'ok.json'
        ok.write_text(json.dumps({'generation': 2, 'xray_sha256': 'a', 'mihomo_sha256': 'b'}))
        self.assertEqual(kit_proxy.read_generation(ok)['generation'], 2)

    def test_file_sha256(self):
        self.assertEqual(kit_proxy.file_sha256(self.d / 'none'), '')
        f = self.d / 'f'
        f.write_bytes(b'abc')
        self.assertEqual(kit_proxy.file_sha256(f),
                         'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')

    def test_plan_restarts_table(self):
        a = {'xray_sha256': 'x1', 'mihomo_sha256': 'm1'}
        cases = [
            (a, {'xray_sha256': 'x1', 'mihomo_sha256': 'm1'}, {'xray': True, 'mihomo': True}, set()),
            (a, {'xray_sha256': 'x2', 'mihomo_sha256': 'm1'}, {'xray': True, 'mihomo': True}, {'xray'}),
            (a, {'xray_sha256': 'x1', 'mihomo_sha256': 'm2'}, {'xray': True, 'mihomo': True}, {'mihomo'}),
            (a, a, {'xray': False, 'mihomo': True}, {'xray'}),
            (a, a, {'xray': True, 'mihomo': False}, {'mihomo'}),
            (None, a, {'xray': False, 'mihomo': False}, {'xray', 'mihomo'}),
        ]
        for applied, wanted, running, expected in cases:
            self.assertEqual(kit_proxy.plan_restarts(applied, wanted, running), expected)

    def test_status_is_stale(self):
        now = 1000.0
        self.assertTrue(kit_proxy.status_is_stale(None, now))
        self.assertTrue(kit_proxy.status_is_stale({'heartbeat': now - 16}, now))
        self.assertFalse(kit_proxy.status_is_stale({'heartbeat': now - 5}, now))

    def test_write_status_atomic_and_mode(self):
        path = self.d / 'status.json'
        kit_proxy.write_status(path, generation=3, state='running', error=None, restarts=0)
        data = json.loads(path.read_text())
        self.assertEqual((data['generation'], data['state']), (3, 'running'))
        self.assertIn('heartbeat', data)
        self.assertAlmostEqual(data['heartbeat'], time.time(), delta=5)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertFalse((self.d / 'status.json.tmp').exists())


class ProxySymlinkTests(unittest.TestCase):
    MARKER = 'SECRET-MARKER-DO-NOT-READ'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_symlinked_generation_is_refused(self):
        target = self.d / 'target.json'
        target.write_text(json.dumps({'generation': 3, 'xray_sha256': 'a', 'mihomo_sha256': 'b'}))
        link = self.d / 'generation.json'
        os.symlink(target, link)
        self.assertIsNone(kit_proxy.read_generation(link))

    def test_symlinked_config_hash_never_matches(self):
        target = self.d / 'secret.txt'
        target.write_text(self.MARKER)
        link = self.d / 'xray-client.json'
        os.symlink(target, link)
        digest = kit_proxy.file_sha256(link)
        self.assertEqual(digest, kit_proxy.NOT_REGULAR)
        self.assertNotEqual(digest, kit_proxy.file_sha256(target))

    def test_status_write_does_not_follow_planted_tmp_link(self):
        target = self.d / 'victim.txt'
        target.write_text(self.MARKER)
        os.symlink(target, self.d / 'status.json.tmp')
        kit_proxy.write_status(self.d / 'status.json', generation=1, state='running', error=None, restarts=0)
        self.assertEqual(target.read_text(), self.MARKER)
        self.assertEqual(json.loads((self.d / 'status.json').read_text())['state'], 'running')


class SupervisorDirTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.run = self.d / 'run'
        self.state = self.d / 'state'
        self.geo = self.d / 'geo'
        self.geo.mkdir()
        self.env = dict(os.environ)
        os.environ.update({'KIT_GEN_DIR': str(self.run), 'KIT_STATE_DIR': str(self.state), 'KIT_GEO_DIR': str(self.geo)})

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        self.tmp.cleanup()

    def test_symlinked_logs_dir_fails_start_and_writes_nothing_into_target(self):
        self.state.mkdir(mode=0o700)
        target = self.d / 'elsewhere'
        target.mkdir()
        os.symlink(target, self.state / 'logs')
        sup = kit_proxy.Supervisor()
        sup.start()
        self.assertFalse(sup.dir_ok)
        status = json.loads((self.state / 'status.json').read_text())
        self.assertEqual(status['state'], 'failed')
        self.assertEqual(status['error'], 'Каталог /kit-state повреждён')
        self.assertEqual(os.listdir(target), [])

    def test_fifo_child_log_returns_devnull_without_blocking(self):
        self.state.mkdir(mode=0o700)
        (self.state / 'logs').mkdir(mode=0o700)
        os.mkfifo(self.state / 'logs' / 'xray.log')
        sup = kit_proxy.Supervisor()
        result = {}

        def attempt():
            fd = sup._log_file('xray')
            result['fd'] = fd
            result['char'] = stat.S_ISCHR(os.fstat(fd).st_mode)

        t = threading.Thread(target=attempt, daemon=True)
        t.start()
        t.join(2)
        self.assertFalse(t.is_alive(), 'FIFO log open blocked')
        self.assertTrue(result['char'])
        os.close(result['fd'])

    def test_precreated_0644_log_becomes_0600(self):
        self.state.mkdir(mode=0o700)
        (self.state / 'logs').mkdir(mode=0o700)
        log = self.state / 'logs' / 'xray.log'
        log.write_text('old\n')
        os.chmod(log, 0o644)
        sup = kit_proxy.Supervisor()
        fd = sup._log_file('xray')
        try:
            self.assertEqual(stat.S_IMODE(os.fstat(fd).st_mode), 0o600)
        finally:
            os.close(fd)
        self.assertEqual(stat.S_IMODE(os.stat(log).st_mode), 0o600)


class SpawnIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.run = self.d / 'run'
        self.run.mkdir(mode=0o700)
        (self.run / 'mihomo').mkdir(mode=0o700)
        self.state = self.d / 'state'
        self.state.mkdir(mode=0o700)
        (self.state / 'logs').mkdir(mode=0o700)
        self.geo = self.d / 'geo'
        self.geo.mkdir()
        self.env = dict(os.environ)
        os.environ.update({'KIT_GEN_DIR': str(self.run), 'KIT_STATE_DIR': str(self.state), 'KIT_GEO_DIR': str(self.geo)})
        self.xray_good, self.mihomo_good = 'XRAY-GOOD', 'MIHOMO-GOOD'
        (self.run / 'xray-client.json').write_text(self.xray_good)
        (self.run / 'mihomo' / 'config.yaml').write_text(self.mihomo_good)
        self.gen = {'generation': 1,
                    'xray_sha256': kit_proxy.file_sha256(self.run / 'xray-client.json'),
                    'mihomo_sha256': kit_proxy.file_sha256(self.run / 'mihomo' / 'config.yaml')}

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        self.tmp.cleanup()

    def status(self):
        return json.loads((self.state / 'status.json').read_text())

    def test_tampered_xray_config_never_spawns(self):
        from unittest import mock
        (self.run / 'xray-client.json').write_text('XRAY-TAMPERED')
        sup = kit_proxy.Supervisor()
        sup.wanted = dict(self.gen)
        with mock.patch.object(kit_proxy.subprocess, 'Popen') as popen:
            sup._apply()
        popen.assert_not_called()
        self.assertEqual(self.status()['state'], 'failed')
        self.assertEqual(self.status()['error'], 'Файлы конфигурации не совпали с поколением')
        self.assertIsNone(sup.applied)

    def test_crash_restart_with_tampered_mihomo_config_is_refused(self):
        from unittest import mock
        sup = kit_proxy.Supervisor()
        sup.applied = dict(self.gen)
        dead = mock.Mock()
        dead.poll.return_value = 1
        dead.returncode = 1
        sup.procs['mihomo'] = dead
        sup.next_try['mihomo'] = 0
        (self.run / 'mihomo' / 'config.yaml').write_text('MIHOMO-TAMPERED')
        with mock.patch.object(kit_proxy.subprocess, 'Popen') as popen:
            sup._watch_children()
        popen.assert_not_called()
        self.assertIsNone(sup.applied)
        self.assertEqual(self.status()['state'], 'failed')
        self.assertEqual(self.status()['error'], 'Файлы конфигурации не совпали с поколением')

    def test_matching_hash_spawns_once(self):
        from unittest import mock
        sup = kit_proxy.Supervisor()
        sup.applied = dict(self.gen)
        live = mock.Mock()
        live.poll.return_value = None
        sup.procs['mihomo'] = live  # only xray needs a restart
        sup.wanted = dict(self.gen)
        with mock.patch.object(kit_proxy.subprocess, 'Popen', return_value=mock.Mock(poll=lambda: None)) as popen, \
                mock.patch.object(kit_proxy, '_wait_port', return_value=True):
            sup._apply()
        self.assertEqual(popen.call_count, 1)
        self.assertIn('xray', popen.call_args[0][0][0])
        self.assertEqual(self.status()['state'], 'running')


class StateSplitProxyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.gen = self.d / 'gen'
        self.state = self.d / 'state'
        self.geo = self.d / 'geo'
        for path in (self.gen, self.state, self.geo):
            path.mkdir(mode=0o700)
        for name in kit_proxy.GEO_FILES:
            (self.geo / name).write_bytes(b'')
        self.env = dict(os.environ)
        os.environ.update({'KIT_GEN_DIR': str(self.gen), 'KIT_STATE_DIR': str(self.state), 'KIT_GEO_DIR': str(self.geo)})

    def tearDown(self):
        for path in (self.gen, self.gen / 'mihomo'):
            try:
                os.chmod(path, 0o700)
            except OSError:
                pass
        os.environ.clear()
        os.environ.update(self.env)
        self.tmp.cleanup()

    def test_start_creates_state_only(self):
        before = sorted(os.listdir(self.gen))
        sup = kit_proxy.Supervisor()
        sup.start()
        self.assertTrue((self.state / 'logs').is_dir())
        self.assertTrue((self.state / 'mihomo' / 'geosite.dat').is_symlink())
        self.assertEqual(json.loads((self.state / 'status.json').read_text())['state'], 'idle')
        self.assertEqual(sorted(os.listdir(self.gen)), before)

    def test_proxy_cannot_write_config(self):
        from unittest import mock
        if os.geteuid() == 0:
            self.skipTest('root ignores directory modes')
        xray_text, mihomo_text = 'XRAY-OK', 'MIHOMO-OK'
        (self.gen / 'xray-client.json').write_text(xray_text)
        (self.gen / 'mihomo').mkdir(mode=0o700)
        (self.gen / 'mihomo' / 'config.yaml').write_text(mihomo_text)
        gen = {'generation': 1,
               'xray_sha256': kit_proxy.file_sha256(self.gen / 'xray-client.json'),
               'mihomo_sha256': kit_proxy.file_sha256(self.gen / 'mihomo' / 'config.yaml')}
        (self.gen / 'generation.json').write_text(json.dumps(gen))
        os.chmod(self.gen / 'xray-client.json', 0o400)
        os.chmod(self.gen / 'mihomo' / 'config.yaml', 0o400)
        os.chmod(self.gen / 'mihomo', 0o500)
        os.chmod(self.gen, 0o500)
        calls = []

        class FakeProc:
            def poll(self):
                return None

            def send_signal(self, sig):
                pass

            def wait(self, timeout=None):
                return 0

            def kill(self):
                pass

        def recorder(cmd, **kw):
            calls.append(cmd)
            return FakeProc()

        sup = kit_proxy.Supervisor()
        sup.start()
        with mock.patch.object(kit_proxy.subprocess, 'Popen', side_effect=recorder), \
                mock.patch.object(kit_proxy, '_wait_port', return_value=True):
            sup._check_generation()
            sup._apply()
        self.assertEqual(json.loads((self.state / 'status.json').read_text())['state'], 'running')
        self.assertEqual(calls[0], [sup.xray_bin, 'run', '-config', str(self.gen / 'xray-client.json')])
        self.assertEqual(calls[1], [sup.mihomo_bin, '-d', str(self.state / 'mihomo'), '-f', str(self.gen / 'mihomo' / 'config.yaml')])
        self.assertEqual(sorted(p.name for p in self.gen.iterdir()), sorted(['xray-client.json', 'mihomo', 'generation.json']))
        self.assertEqual((self.gen / 'xray-client.json').read_text(), xray_text)

    def test_start_symlinked_state_dir_fails(self):
        target = self.d / 'elsewhere'
        target.mkdir()
        os.rmdir(self.state)
        os.symlink(target, self.state)
        sup = kit_proxy.Supervisor()
        sup.start()
        self.assertFalse(sup.dir_ok)
        self.assertEqual(sup.state, 'failed')
        self.assertEqual(sup.error, 'Каталог /kit-state повреждён')

    def test_module_source_has_no_run_dir(self):
        source = (ROOT / 'ui' / 'kit_proxy.py').read_text(encoding='utf-8')
        self.assertNotIn('KIT_RUN_DIR', source)
        self.assertNotIn('run_dir', source)


if __name__ == '__main__':
    unittest.main()
