import importlib, json, os, stat, sys, tempfile, threading, time, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ui'))
kit_apply = importlib.import_module('kit_apply')
kit_db = importlib.import_module('kit_db')
kit_jobs = importlib.import_module('kit_jobs')

EXIT = '149.28.240.154'
NL = {'host': '185.245.107.19', 'ssh_user': 'root', 'ssh_port': 22}


class FakeJob:
    def __init__(self):
        self.redactor = kit_jobs.Redactor()
        self.lines = []

    def append(self, text):
        self.lines.append(text)


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ)
        os.environ.update({'KIT_DATA_DIR': str(Path(self.tmp.name) / 'data'),
                           'KIT_GEN_DIR': str(Path(self.tmp.name) / 'run'), 'KIT_STATE_DIR': str(Path(self.tmp.name) / 'state')})
        self.run = Path(self.tmp.name) / 'run'
        self.state = Path(self.tmp.name) / 'state'
        self.state.mkdir(mode=0o700)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        self.tmp.cleanup()

    def test_write_bundle_modes_hashes_and_prev(self):
        g1 = kit_apply.write_bundle('X1', 'M1')
        self.assertEqual(g1, 1)
        self.assertEqual(stat.S_IMODE(os.stat(self.run / 'xray-client.json').st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.run / 'mihomo' / 'config.yaml').st_mode), 0o600)
        self.assertFalse((self.run / 'prev' / 'xray-client.json').exists())
        g2 = kit_apply.write_bundle('X2', None)
        self.assertEqual(g2, 2)
        self.assertEqual((self.run / 'prev' / 'xray-client.json').read_text(), 'X1')
        self.assertEqual(json.loads((self.run / 'generation.json').read_text()),
                         {'generation': 2, 'xray_sha256': kit_apply.sha256_text('X2'),
                          'mihomo_sha256': kit_apply.sha256_text('M1')})
        self.assertEqual((self.run / 'mihomo' / 'config.yaml').read_text(), 'M1')

    def test_restore_prev(self):
        self.assertIsNone(kit_apply.restore_prev())
        kit_apply.write_bundle('X1', 'M1')
        kit_apply.write_bundle('X2', 'M2')
        self.assertEqual(kit_apply.restore_prev(), 3)
        self.assertEqual((self.run / 'xray-client.json').read_text(), 'X1')
        self.assertEqual((self.run / 'mihomo' / 'config.yaml').read_text(), 'M1')

    def test_wait_applied_with_thread(self):
        def writer():
            time.sleep(0.6)
            kit_apply.atomic_write(self.state / 'status.json', json.dumps({'generation': 4, 'state': 'running'}))
        self.run.mkdir(mode=0o700)
        threading.Thread(target=writer).start()
        self.assertEqual(kit_apply.wait_applied(4, timeout=5)['state'], 'running')
        self.assertEqual(kit_apply.wait_applied(9, timeout=1)['state'], 'timeout')

    def test_proxy_state(self):
        self.assertEqual(kit_apply.proxy_state()['state'], 'down')
        self.run.mkdir(mode=0o700)
        kit_apply.atomic_write(self.state / 'status.json',
                               json.dumps({'generation': 2, 'state': 'running', 'error': None,
                                           'heartbeat': time.time() - 60}))
        self.assertEqual(kit_apply.proxy_state()['state'], 'down')
        kit_apply.atomic_write(self.state / 'status.json',
                               json.dumps({'generation': 2, 'state': 'running', 'error': None,
                                           'heartbeat': time.time()}))
        state = kit_apply.proxy_state()
        self.assertEqual((state['state'], state['generation']), ('running', 2))

    def _db_inbound(self):
        conn = kit_db.connect()
        kit_db.upsert_inbounds(conn, [{'port': 2088, 'uuid': '11111111-2222-3333-4444-555555555555', 'exit_ip': EXIT, 'exit_tag': 'USA2',
                                       'network': 'tcp', 'remark': 'r', 'flow': 'xtls-rprx-vision', 'pbk': 'S' * 43,
                                       'sid': 'abcdef', 'sni': 'dl.google.com', 'xhttp_json': '{}',
                                       'grpc_service': '', 'grpc_multi': 0}])
        row = kit_db.list_inbounds(conn)[0]
        conn.close()
        return row

    def test_install_success(self):
        row = self._db_inbound()
        job = FakeJob()
        with mock.patch.object(kit_apply, 'validate_bundle'), \
                mock.patch.object(kit_apply, 'wait_applied', return_value={'state': 'running', 'generation': 1}), \
                mock.patch.object(kit_apply, 'verify_exit', return_value=(True, EXIT)):
            status, ip, summary = kit_apply.install(job, NL['host'], row)
        self.assertEqual((status, ip), ('ok', EXIT))
        self.assertIn('Установлено', summary)
        conn = kit_db.connect()
        self.assertEqual(kit_db.get_active(conn)['inbound_id'], row['id'])
        conn.close()
        self.assertNotIn('S' * 43, '\n'.join(job.lines))

    def test_install_failure_rolls_back(self):
        row = self._db_inbound()
        kit_apply.write_bundle('OLD-X', 'OLD-M')
        job = FakeJob()
        with mock.patch.object(kit_apply, 'validate_bundle'), \
                mock.patch.object(kit_apply, 'wait_applied', return_value={'state': 'running'}), \
                mock.patch.object(kit_apply, 'verify_exit', return_value=(False, '1.1.1.1')):
            status, ip, summary = kit_apply.install(job, NL['host'], row)
        self.assertEqual(status, 'failed')
        self.assertIn('Восстановлена предыдущая конфигурация', summary)
        self.assertEqual((self.run / 'xray-client.json').read_text(), 'OLD-X')
        self.assertEqual(json.loads((self.run / 'generation.json').read_text())['generation'], 3)

    def test_install_failure_without_previous(self):
        row = self._db_inbound()
        with mock.patch.object(kit_apply, 'validate_bundle'), \
                mock.patch.object(kit_apply, 'wait_applied', return_value={'state': 'failed', 'error': 'x'}), \
                mock.patch.object(kit_apply, 'verify_exit', return_value=(False, '')):
            status, _, summary = kit_apply.install(FakeJob(), NL, row)
        self.assertEqual(status, 'failed')
        self.assertIn('Предыдущей конфигурации нет', summary)

    def test_apply_rules_without_active_writes_nothing(self):
        self._db_inbound()
        status, ip, summary = kit_apply.apply_rules(FakeJob(), NL)
        self.assertEqual((status, ip), ('ok', None))
        self.assertFalse((self.run / 'generation.json').exists())

    def test_validate_bundle_uses_tool_output_as_detail(self):
        bad = mock.Mock(returncode=1, stdout='', stderr='boom')
        with mock.patch.object(kit_apply.subprocess, 'run', return_value=bad):
            with self.assertRaises(kit_apply.BundleInvalid) as ctx:
                kit_apply.validate_bundle('{}', 'x: 1\n')
        self.assertEqual(str(ctx.exception), 'Конфигурация не прошла проверку: xray')
        self.assertEqual(ctx.exception.detail, 'boom')


class SymlinkRefusalTests(unittest.TestCase):
    MARKER = 'SECRET-MARKER-DO-NOT-COPY'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ)
        os.environ.update({'KIT_DATA_DIR': str(Path(self.tmp.name) / 'data'),
                           'KIT_GEN_DIR': str(Path(self.tmp.name) / 'run'), 'KIT_STATE_DIR': str(Path(self.tmp.name) / 'state')})
        self.run = Path(self.tmp.name) / 'run'
        self.state = Path(self.tmp.name) / 'state'
        self.state.mkdir(mode=0o700)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        self.tmp.cleanup()

    def _db_inbound(self):
        conn = kit_db.connect()
        kit_db.upsert_inbounds(conn, [{'port': 2088, 'uuid': '11111111-2222-3333-4444-555555555555', 'exit_ip': EXIT, 'exit_tag': 'USA2',
                                       'network': 'tcp', 'remark': 'r', 'flow': 'xtls-rprx-vision', 'pbk': 'S' * 43,
                                       'sid': 'abcdef', 'sni': 'dl.google.com', 'xhttp_json': '{}',
                                       'grpc_service': '', 'grpc_multi': 0}])
        row = kit_db.list_inbounds(conn)[0]
        conn.close()
        return row

    def plant(self, name):
        target = Path(self.tmp.name) / 'planted-target'
        target.write_text(self.MARKER, encoding='utf-8')
        self.run.mkdir(mode=0o700, exist_ok=True)
        os.symlink(target, self.run / name)
        return target

    def prev_texts(self):
        prev = self.run / 'prev'
        if not prev.exists():
            return []
        return [p.read_text(encoding='utf-8') for p in prev.iterdir() if p.is_file() and not p.is_symlink()]

    def test_write_bundle_refuses_symlinked_current_file(self):
        target = self.plant('xray-client.json')
        (self.run / 'mihomo').mkdir(mode=0o700, exist_ok=True)
        (self.run / 'mihomo' / 'config.yaml').write_text('M-OLD', encoding='utf-8')
        with self.assertRaises(kit_apply.RunFileError):
            kit_apply.write_bundle('X-NEW', 'M-NEW')
        self.assertFalse(any(self.MARKER in t for t in self.prev_texts()))
        self.assertEqual(target.read_text(encoding='utf-8'), self.MARKER)

    def test_restore_prev_refuses_symlinked_prev_file(self):
        self.run.mkdir(mode=0o700)
        (self.run / 'xray-client.json').write_text('X-SAFE', encoding='utf-8')
        (self.run / 'mihomo').mkdir(mode=0o700)
        (self.run / 'mihomo' / 'config.yaml').write_text('M-SAFE', encoding='utf-8')
        prev = self.run / 'prev'
        prev.mkdir(mode=0o700)
        (prev / 'mihomo-config.yaml').write_text('M-PREV', encoding='utf-8')
        target = Path(self.tmp.name) / 'planted-prev'
        target.write_text(self.MARKER, encoding='utf-8')
        os.symlink(target, prev / 'xray-client.json')
        with self.assertRaises(kit_apply.RunFileError):
            kit_apply.restore_prev()
        self.assertEqual((self.run / 'xray-client.json').read_text(encoding='utf-8'), 'X-SAFE')
        self.assertEqual((self.run / 'mihomo' / 'config.yaml').read_text(encoding='utf-8'), 'M-SAFE')

    def test_symlinked_generation_file_refused(self):
        self.run.mkdir(mode=0o700)
        target = Path(self.tmp.name) / 'planted-gen'
        target.write_text('{"generation": 7, "xray_sha256": "", "mihomo_sha256": ""}', encoding='utf-8')
        os.symlink(target, self.run / 'generation.json')
        with self.assertRaises(kit_apply.RunFileError):
            kit_apply.write_bundle('X', 'M')
        self.assertIn('"generation": 7', target.read_text(encoding='utf-8'))

    def test_symlinked_status_is_not_read(self):
        self.run.mkdir(mode=0o700)
        target = Path(self.tmp.name) / 'planted-status'
        target.write_text('{"generation": 1, "state": "running", "heartbeat": %f}' % time.time(), encoding='utf-8')
        os.symlink(target, self.state / 'status.json')
        self.assertIsNone(kit_apply.read_status())

    def test_apply_rules_redacts_pbk_in_job_log(self):
        row = self._db_inbound()
        conn = kit_db.connect()
        kit_db.set_active(conn, row['id'], 1)
        conn.close()
        kit_apply.write_bundle('X-CUR', 'M-CUR')
        kit_jobs_mod = kit_jobs
        runner = kit_jobs_mod.JobRunner()
        def fn(job):
            return kit_apply.apply_rules(job, NL)
        with mock.patch.object(kit_apply, 'validate_bundle',
                               side_effect=kit_apply.BundleInvalid('Конфигурация не прошла проверку: mihomo')) as vb:
            vb.side_effect.detail = 'mihomo: bad key ' + 'S' * 43 + ' and sid abcdef'
            job_id = runner.start('apply_rules', None, fn)
            for _ in range(200):
                info = runner.read(job_id, 0)
                if info['status'] != 'running':
                    break
                time.sleep(0.05)
        log = (Path(self.tmp.name) / 'data' / 'logs' / f'job-{job_id}.log').read_text(encoding='utf-8')
        self.assertIn('[REDACTED]', log)
        self.assertNotIn('S' * 43, log)


class TailReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_returns_none(self):
        self.assertIsNone(kit_apply.read_regular_tail(self.d / 'nope.log'))

    def test_symlink_is_refused(self):
        target = self.d / 'target.log'
        target.write_text('MARKER-SECRET', encoding='utf-8')
        os.symlink(target, self.d / 'link.log')
        with self.assertRaises(kit_apply.RunFileError):
            kit_apply.read_regular_tail(self.d / 'link.log')

    def test_fifo_is_refused_without_blocking(self):
        fifo = self.d / 'pipe.log'
        os.mkfifo(fifo)
        result = {}

        def attempt():
            try:
                kit_apply.read_regular_tail(fifo)
                result['outcome'] = 'returned'
            except kit_apply.RunFileError:
                result['outcome'] = 'refused'

        t = threading.Thread(target=attempt, daemon=True)
        t.start()
        t.join(2)
        self.assertFalse(t.is_alive(), 'FIFO read blocked')
        self.assertEqual(result.get('outcome'), 'refused')

    def test_hard_link_is_refused(self):
        original = self.d / 'a.log'
        original.write_text('x', encoding='utf-8')
        os.link(original, self.d / 'b.log')
        with self.assertRaises(kit_apply.RunFileError):
            kit_apply.read_regular_tail(self.d / 'b.log')

    def test_large_file_is_tail_truncated_to_limit(self):
        big = self.d / 'big.log'
        big.write_bytes(b'a' * (300 * 1024))
        data, truncated = kit_apply.read_regular_tail(big)
        self.assertEqual(len(data), 262144)
        self.assertTrue(truncated)

    def test_small_file_is_not_truncated(self):
        small = self.d / 'small.log'
        small.write_text('line one\nline two\n', encoding='utf-8')
        data, truncated = kit_apply.read_regular_tail(small)
        self.assertEqual(data, b'line one\nline two\n')
        self.assertFalse(truncated)


class DirectoryAndAtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ)
        self.run = Path(self.tmp.name) / 'run'
        os.environ.update({'KIT_GEN_DIR': str(self.run), 'KIT_STATE_DIR': str(Path(self.tmp.name) / 'state'),
                           'KIT_DATA_DIR': str(Path(self.tmp.name) / 'data')})
        self.state = Path(self.tmp.name) / 'state'
        self.state.mkdir(mode=0o700)
        self.run.mkdir(mode=0o700)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        self.tmp.cleanup()

    def test_symlinked_mihomo_dir_refused_and_target_untouched(self):
        target = Path(self.tmp.name) / 'elsewhere'
        target.mkdir()
        os.symlink(target, self.run / 'mihomo')
        with self.assertRaises(kit_apply.RunFileError):
            kit_apply.write_bundle('X', 'M')
        self.assertEqual(os.listdir(target), [])
        self.assertFalse((self.run / 'xray-client.json').exists())

    def test_symlinked_prev_dir_refused_and_target_untouched(self):
        target = Path(self.tmp.name) / 'elsewhere-prev'
        target.mkdir()
        os.symlink(target, self.run / 'prev')
        with self.assertRaises(kit_apply.RunFileError):
            kit_apply.write_bundle('X', 'M')
        self.assertEqual(os.listdir(target), [])

    def test_written_file_is_0600_and_no_temp_left(self):
        kit_apply.write_bundle('X', 'M')
        for name in ('xray-client.json', 'mihomo/config.yaml', 'generation.json'):
            self.assertEqual(stat.S_IMODE(os.stat(self.run / name).st_mode), 0o600, name)
        leftovers = [p for p in list(self.run.glob('.tmp-*')) + list((self.run / 'mihomo').glob('.tmp-*'))]
        self.assertEqual(leftovers, [])

    def test_forced_replace_failure_leaves_no_temp(self):
        with mock.patch.object(kit_apply.os, 'replace', side_effect=OSError('boom')):
            with self.assertRaises(OSError):
                kit_apply.atomic_write(self.run / 'x.txt', 'data')
        self.assertEqual([p.name for p in self.run.iterdir() if p.name.startswith('.tmp-')], [])
        self.assertFalse((self.run / 'x.txt').exists())


class StateSplitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ)
        self.gen = Path(self.tmp.name) / 'gen'
        self.state = Path(self.tmp.name) / 'state'
        self.gen.mkdir(mode=0o700)
        self.state.mkdir(mode=0o700)
        os.environ.update({'KIT_GEN_DIR': str(self.gen), 'KIT_STATE_DIR': str(self.state),
                           'KIT_DATA_DIR': str(Path(self.tmp.name) / 'data')})

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        self.tmp.cleanup()

    def test_read_status_from_state_dir(self):
        (self.state / 'status.json').write_text(json.dumps({'generation': 2, 'state': 'running'}), encoding='utf-8')
        (self.gen / 'status.json').write_text(json.dumps({'generation': 9, 'state': 'failed'}), encoding='utf-8')
        status = kit_apply.read_status()
        self.assertEqual((status['generation'], status['state']), (2, 'running'))

    def test_read_status_symlinked_state_dir_is_none(self):
        real = Path(self.tmp.name) / 'elsewhere'
        real.mkdir()
        (real / 'status.json').write_text(json.dumps({'generation': 1, 'state': 'running'}), encoding='utf-8')
        os.rmdir(self.state)
        os.symlink(real, self.state)
        self.assertIsNone(kit_apply.read_status())

    def test_open_state_dir_missing_is_none(self):
        os.rmdir(self.state)
        self.assertIsNone(kit_apply.open_state_dir())
        self.assertIsNone(kit_apply.open_state_dir('logs'))

    def test_write_bundle_never_touches_state_dir(self):
        if os.geteuid() == 0:
            self.skipTest('root ignores directory modes')
        before = sorted(os.listdir(self.state))
        os.chmod(self.state, 0o500)
        try:
            kit_apply.write_bundle('X1', 'M1')
            kit_apply.write_bundle('X2', 'M2')
            kit_apply.restore_prev()
            self.assertEqual(sorted(os.listdir(self.state)), before)
        finally:
            os.chmod(self.state, 0o700)

    def test_first_install_without_prior_generation(self):
        self.assertEqual(kit_apply.write_bundle('X', 'M'), 1)
        self.assertEqual((self.gen / 'xray-client.json').read_text(), 'X')
        self.assertEqual((self.gen / 'mihomo' / 'config.yaml').read_text(), 'M')
        self.assertTrue((self.gen / 'generation.json').is_file())
        self.assertEqual(os.listdir(self.gen / 'prev'), [])

    def test_apply_rules_active_without_xray_file(self):
        conn = kit_db.connect()
        kit_db.upsert_inbounds(conn, [{'port': 2088, 'uuid': 'uuid-x', 'exit_ip': EXIT, 'exit_tag': 'USA2',
                                       'network': 'tcp', 'remark': 'r', 'flow': 'xtls-rprx-vision', 'pbk': 'A' * 43,
                                       'sid': 'cafe', 'sni': 'dl.google.com', 'xhttp_json': '{}',
                                       'grpc_service': '', 'grpc_multi': 0}])
        row = kit_db.list_inbounds(conn)[0]
        kit_db.set_active(conn, row['id'], 1)
        conn.close()
        status, ip, summary = kit_apply.apply_rules(FakeJob(), NL)
        self.assertEqual((status, ip), ('ok', None))
        self.assertEqual(summary, 'Правила сохранены; будут применены при установке')
        self.assertFalse((self.gen / 'generation.json').exists())


if __name__ == '__main__':
    unittest.main()
