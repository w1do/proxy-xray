import importlib, os, stat, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ui'))
kit_jobs = importlib.import_module('kit_jobs')
kit_db = importlib.import_module('kit_db')


class RedactorTests(unittest.TestCase):
    def test_masks_secrets_uuid_and_vless(self):
        r = kit_jobs.Redactor(['secret-pbk-value', 'ab'])
        text = r.apply('pbk=secret-pbk-value id=12345678-1234-1234-1234-123456789abc vless://u@h:1?x=y')
        self.assertNotIn('secret-pbk-value', text)
        self.assertNotIn('12345678-1234', text)
        self.assertIn('[UUID]', text)
        self.assertIn('vless://[REDACTED]', text)
        self.assertNotIn('ab', [s for s in r.secrets if len(s) < 4])


class EnvAndStreamTests(unittest.TestCase):
    def test_child_env_has_no_proxy_vars(self):
        os.environ['KIT_TEST_proxy'] = '1'
        os.environ['https_proxy'] = 'http://x'
        try:
            env = kit_jobs.child_env()
            self.assertNotIn('https_proxy', env)
            self.assertNotIn('KIT_TEST_proxy', env)
        finally:
            os.environ.pop('KIT_TEST_proxy', None)
            os.environ.pop('https_proxy', None)

    def test_run_streamed_lines_and_timeout(self):
        rc, lines = kit_jobs.run_streamed(None, ['python3', '-c', 'print("a"); print("b")'], 10)
        self.assertEqual((rc, lines), (0, ['a', 'b']))
        start = time.monotonic()
        rc, _ = kit_jobs.run_streamed(None, ['python3', '-c', 'import time; time.sleep(30)'], 1)
        self.assertNotEqual(rc, 0)
        self.assertLess(time.monotonic() - start, 15)


class JobRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get('KIT_DATA_DIR')
        os.environ['KIT_DATA_DIR'] = self.tmp.name

    def tearDown(self):
        if self.old is None:
            os.environ.pop('KIT_DATA_DIR', None)
        else:
            os.environ['KIT_DATA_DIR'] = self.old
        self.tmp.cleanup()

    def test_busy_and_log_mode(self):
        runner = kit_jobs.JobRunner()
        release = []

        def slow(job):
            job.append('line one vless://a@b:1')
            while not release:
                time.sleep(0.05)
            return 'ok', None, 'done'

        job_id = runner.start('discover', None, slow)
        with self.assertRaises(kit_jobs.Busy):
            runner.start('discover', None, slow)
        release.append(1)
        for _ in range(100):
            info = runner.read(job_id, 0)
            if info['status'] != 'running':
                break
            time.sleep(0.05)
        self.assertEqual(info['status'], 'ok')
        log = Path(self.tmp.name) / 'logs' / f'job-{job_id}.log'
        self.assertEqual(stat.S_IMODE(os.stat(log).st_mode), 0o600)
        self.assertNotIn('a@b', log.read_text())

    def test_failed_job_detail_is_logged_redacted(self):
        runner = kit_jobs.JobRunner()

        def boom(job):
            exc = RuntimeError('summary text')
            exc.detail = 'raw uuid 12345678-1234-1234-1234-123456789abc'
            raise exc

        job_id = runner.start('check', None, boom)
        for _ in range(100):
            info = runner.read(job_id, 0)
            if info['status'] != 'running':
                break
            time.sleep(0.05)
        self.assertEqual(info['status'], 'failed')
        self.assertNotIn('12345678-1234', (Path(self.tmp.name) / 'logs' / f'job-{job_id}.log').read_text())

    def test_install_argv_removed(self):
        self.assertFalse(hasattr(kit_jobs, 'install_argv'))
        self.assertFalse(hasattr(kit_jobs, 'INSTALL_TIMEOUT'))
        self.assertTrue(callable(kit_jobs.apply_rules_job))


class JobSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get('KIT_DATA_DIR')
        os.environ['KIT_DATA_DIR'] = self.tmp.name

    def tearDown(self):
        if self.old is None:
            os.environ.pop('KIT_DATA_DIR', None)
        else:
            os.environ['KIT_DATA_DIR'] = self.old
        self.tmp.cleanup()

    def run_job(self, exc):
        import subprocess
        runner = kit_jobs.JobRunner()

        def fn(job):
            raise exc

        job_id = runner.start('discover', None, fn)
        for _ in range(200):
            info = runner.read(job_id, 0)
            if info['status'] != 'running':
                break
            time.sleep(0.05)
        conn = kit_db.connect()
        try:
            return kit_db.get_job(conn, job_id)
        finally:
            conn.close()

    def test_timeout_summary_is_generic(self):
        import subprocess
        exc = subprocess.TimeoutExpired(cmd=['ssh', '-i', '/tmp/kit-ssh/id_nl', '-o',
                                             'UserKnownHostsFile=/data/ssh/known_hosts', 'root@h'], timeout=40)
        row = self.run_job(exc)
        self.assertEqual(row['status'], 'failed')
        self.assertNotIn('/tmp/kit-ssh/id_nl', row['summary'])
        self.assertNotIn('known_hosts', row['summary'])
        self.assertEqual(row['summary'], 'Задача завершилась с ошибкой; подробности в журнале задачи')

    def test_safe_error_keeps_its_message(self):
        import kit_discovery
        row = self.run_job(kit_discovery.SafeError('NL: ssh-keyscan не получил ключи'))
        self.assertEqual(row['summary'], 'NL: ssh-keyscan не получил ключи')


class CheckHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ)
        os.environ['KIT_DATA_DIR'] = self.tmp.name

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        self.tmp.cleanup()

    def test_discovered_row_without_nl_settings_fails_with_fixed_message(self):
        import kit_db
        conn = kit_db.connect()
        try:
            kit_db.upsert_inbounds(conn, [{'port': 2088, 'uuid': '11111111-2222-3333-4444-555555555501',
                                           'exit_ip': '149.28.240.154', 'exit_tag': 'USA2', 'network': 'tcp',
                                           'remark': 'd', 'flow': '', 'pbk': 'A' * 43, 'sid': 'ab', 'sni': 'x.example',
                                           'xhttp_json': '{}', 'grpc_service': '', 'grpc_multi': 0}])
            inbound_id = kit_db.list_inbounds(conn)[0]['id']
        finally:
            conn.close()

        class FakeJob:
            def __init__(self):
                self.redactor = kit_jobs.Redactor()
                self.lines = []

            def append(self, text):
                self.lines.append(text)

        job = FakeJob()
        status, _, summary = kit_jobs.check_job(job, None, [inbound_id])
        self.assertEqual(status, 'failed')
        self.assertEqual(summary, 'Проверено: 1, ошибок: 1')
        conn = kit_db.connect()
        try:
            self.assertEqual(kit_db.get_inbound(conn, inbound_id)['check_error'], 'Не заданы настройки NL')
        finally:
            conn.close()


if __name__ == '__main__':
    unittest.main()
