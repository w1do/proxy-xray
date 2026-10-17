import os, shutil, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / 'install-cli.sh'
WRAPPER = ROOT / 'proxy'


class InstallCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / 'home'
        self.home.mkdir()
        self.other = Path(self.tmp.name) / 'elsewhere'
        self.other.mkdir()
        self.link = self.home / '.local' / 'bin' / 'proxy'
        # PATH is fixed: only system tools, with ~/.local/bin deliberately absent.
        self.env = {'HOME': str(self.home), 'PATH': '/usr/bin:/bin'}

    def tearDown(self):
        self.tmp.cleanup()

    def run_install(self, *args, cwd=None):
        return subprocess.run(['bash', str(INSTALL), *args], env=self.env, cwd=str(cwd or self.other),
                              capture_output=True, text=True)

    def test_install_creates_symlink_to_repo_proxy(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.link.is_symlink())
        self.assertEqual(os.path.realpath(self.link), os.path.realpath(WRAPPER))

    def test_second_run_is_a_noop(self):
        self.run_install()
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Already installed', result.stdout)
        self.assertEqual(os.path.realpath(self.link), os.path.realpath(WRAPPER))

    def test_refuses_to_overwrite_regular_file(self):
        self.link.parent.mkdir(parents=True)
        self.link.write_text('mine')
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('regular file', result.stderr)
        self.assertEqual(self.link.read_text(), 'mine')

    def test_refuses_to_overwrite_foreign_symlink(self):
        self.link.parent.mkdir(parents=True)
        foreign = self.other / 'other-proxy'
        foreign.write_text('x')
        os.symlink(foreign, self.link)
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(os.readlink(self.link), str(foreign))

    def test_remove_deletes_only_its_own_symlink(self):
        self.run_install()
        result = self.run_install('--remove')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.link.exists() or self.link.is_symlink())

    def test_remove_refuses_foreign_symlink(self):
        self.link.parent.mkdir(parents=True)
        foreign = self.other / 'other-proxy'
        foreign.write_text('x')
        os.symlink(foreign, self.link)
        result = self.run_install('--remove')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.link.is_symlink())

    def test_prints_path_line_and_does_not_edit_rc(self):
        result = self.run_install()
        self.assertIn('export PATH="$HOME/.local/bin:$PATH"', result.stdout)
        self.assertFalse((self.home / '.bashrc').exists())
        self.assertFalse((self.home / '.zshrc').exists())

    def test_wrapper_through_symlink_from_other_folder_resolves_repo_root(self):
        self.run_install()
        stub_dir = Path(self.tmp.name) / 'stub'
        stub_dir.mkdir()
        stub = stub_dir / 'python3'
        stub.write_text('#!/bin/bash\necho "KIT_ROOT=$KIT_ROOT"\necho "SCRIPT=$1"\n')
        os.chmod(stub, 0o755)
        env = dict(self.env, PATH=f'{stub_dir}:/usr/bin:/bin')
        result = subprocess.run(['bash', str(self.link), 'status'], env=env, cwd=str(self.other),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'KIT_ROOT={ROOT}', result.stdout)
        self.assertIn(f'SCRIPT={ROOT}/tools/proxy_cli.py', result.stdout)


if __name__ == '__main__':
    unittest.main()
