import importlib, os, stat, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ui'))
kit_priv = importlib.import_module('kit_priv')


class PrivTests(unittest.TestCase):
    def test_non_root_is_noop(self):
        if os.geteuid() == 0:
            self.skipTest('running as root')
        kit_priv.prepare_and_drop()  # must return without changing identity
        self.assertNotEqual(os.getuid(), 0)

    def test_copy_key_mode_and_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'src'
            src.write_bytes(b'-----BEGIN OPENSSH PRIVATE KEY-----\ndummy\n')
            dst = Path(d) / 'ssh' / 'id_nl'
            kit_priv.copy_key(src, dst)
            self.assertEqual(dst.read_bytes(), src.read_bytes())
            self.assertEqual(stat.S_IMODE(os.stat(dst).st_mode), 0o600)
            kit_priv.copy_key(src, dst)
            self.assertEqual(stat.S_IMODE(os.stat(dst).st_mode), 0o600)


class ShouldCopyKeyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.mount = self.d / 'mount'
        self.key = self.d / 'key'

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_placeholder_is_not_copied(self):
        self.mount.write_bytes(b'')
        self.assertFalse(kit_priv.should_copy_key(self.mount))

    def test_missing_mount_is_not_copied(self):
        self.assertFalse(kit_priv.should_copy_key(self.mount))

    def test_real_key_is_copied(self):
        self.mount.write_bytes(b'KEY-BYTES')
        self.assertTrue(kit_priv.should_copy_key(self.mount))

    def test_identical_copy_needs_no_update(self):
        self.mount.write_bytes(b'KEY-BYTES')
        self.key.write_bytes(b'KEY-BYTES')
        self.assertFalse(kit_priv.key_needs_update(self.mount, self.key))

    def test_changed_key_needs_update(self):
        self.mount.write_bytes(b'NEW-BYTES')
        self.key.write_bytes(b'OLD-BYTES')
        self.assertTrue(kit_priv.key_needs_update(self.mount, self.key))


if __name__ == '__main__':
    unittest.main()
