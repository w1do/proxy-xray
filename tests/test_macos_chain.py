import hashlib
import importlib.util
import json
import os
import plistlib
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'tools' / 'macos-chain.sh'
_spec = importlib.util.spec_from_file_location('install_client', ROOT / 'tools' / 'install-client.py')
install_client = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(install_client)

# Settings that the bash library reads from the environment. They are removed from the
# inherited environment so that a developer's shell cannot change the test results.
SETTING_KEYS = {'SERVER_IP', 'SERVER_PORT', 'UUID', 'PUBLIC_KEY', 'SHORT_ID',
                'REALITY_SERVER_NAME', 'SERVER_NETWORK', 'XHTTP_PATH', 'XHTTP_MODE',
                'GRPC_SERVICE_NAME', 'CLIENT_FINGERPRINT'}

GOOD = {'SERVER_IP': '192.0.2.10', 'SERVER_PORT': '2087',
        'UUID': '11111111-2222-3333-4444-555555555555',
        'PUBLIC_KEY': 'A' * 43,  # 32 zero bytes in base64url: a dummy, but Xray accepts its length
        'SHORT_ID': 'abcd1234', 'REALITY_SERVER_NAME': 'dl.google.com',
        'CLIENT_FINGERPRINT': 'firefox', 'XHTTP_PATH': '/dl', 'XHTTP_MODE': 'auto',
        'SERVER_NETWORK': 'xhttp'}

SOCKS_BLOCK = ('  - name: USA\n    type: socks5\n    server: 127.0.0.1\n'
               '    port: 18080\n    udp: true\n')

XRAY_BIN = os.environ.get('XRAY_BIN') or str(Path.home() / '.local/bin/xray')


def run_bash(script, env=None):
    base = {k: v for k, v in os.environ.items()
            if not k.lower().endswith('_proxy') and k not in SETTING_KEYS}
    return subprocess.run(['bash', '-c', f'. "{LIB}"; {script}'],
                          env={**base, **(env or {})}, capture_output=True, text=True)


def mode_env(network, port):
    env = dict(GOOD, SERVER_NETWORK=network, SERVER_PORT=str(port))
    if network == 'grpc':
        env['GRPC_SERVICE_NAME'] = 'grpc-test'
    return env


class PortMapParityTests(unittest.TestCase):
    def test_bash_and_python_port_maps_match(self):
        for exit_ip, ports in install_client.NL_PORTS.items():
            with self.subTest(exit_ip=exit_ip):
                result = run_bash(f'nl_allowed_ports {exit_ip}')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(sorted(int(p) for p in result.stdout.split()), sorted(ports))
        result = run_bash('nl_allowed_ports 192.0.2.1')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')


class PortCheckTests(unittest.TestCase):
    def test_usa2_ports_accepted(self):
        for port in ('2088', '2089', '2090'):
            with self.subTest(port=port):
                result = run_bash(f'nl_check_exit_port 149.28.240.154 {port}')
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_usa2_rejects_usa1_port(self):
        result = run_bash('nl_check_exit_port 149.28.240.154 2083')
        self.assertEqual(result.returncode, 2)
        self.assertIn('2087/2088/2089/2090', result.stderr)

    def test_unknown_exit_rejected(self):
        result = run_bash('nl_check_exit_port 192.0.2.1 2083')
        self.assertEqual(result.returncode, 2)
        self.assertIn('Unknown USA exit: 192.0.2.1', result.stderr)


class XrayJsonParityTests(unittest.TestCase):
    def test_matches_linux_xray_config(self):
        for network, port in (('xhttp', 2087), ('tcp', 2088), ('grpc', 2089)):
            with self.subTest(network=network, port=port):
                env = mode_env(network, port)
                result = run_bash('render_xray_client_json', env)
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = install_client.xray_config(
                    env, install_client.profile_from_settings(env, '149.28.240.154'))
                self.assertEqual(json.loads(result.stdout), expected)


class ValidationTests(unittest.TestCase):
    def test_uuid_with_quote_rejected(self):
        result = run_bash('chain_validate_settings', dict(GOOD, UUID='bad"uuid'))
        self.assertEqual(result.returncode, 2)
        self.assertIn('Invalid UUID', result.stderr)

    def test_unknown_network_rejected(self):
        result = run_bash('chain_validate_settings', dict(GOOD, SERVER_NETWORK='ws'))
        self.assertEqual(result.returncode, 2)

    def test_port_out_of_range_rejected(self):
        result = run_bash('chain_validate_settings', dict(GOOD, SERVER_PORT='70000'))
        self.assertEqual(result.returncode, 2)

    def test_render_refuses_invalid_settings(self):
        result = run_bash('render_xray_client_json', dict(GOOD, UUID='bad"uuid'))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')


class SocksBlockTests(unittest.TestCase):
    def test_socks_block_text(self):
        result = run_bash('render_usa_socks_block')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, SOCKS_BLOCK)

    def test_socks_block_parses_as_yaml(self):
        try:
            import yaml
        except ImportError:
            self.skipTest('PyYAML is not installed; exact text is checked instead')
        result = run_bash('render_usa_socks_block')
        self.assertEqual(yaml.safe_load('proxies:\n' + result.stdout)['proxies'][0],
                         {'name': 'USA', 'type': 'socks5', 'server': '127.0.0.1',
                          'port': 18080, 'udp': True})


class LaunchAgentTests(unittest.TestCase):
    def test_plist_keys(self):
        result = run_bash('render_xray_launch_agent /u/.local/bin/xray '
                          '/u/.config/mihomo/xray-client.json /u/.config/mihomo/xray.log')
        self.assertEqual(result.returncode, 0, result.stderr)
        plist = plistlib.loads(result.stdout.encode())
        self.assertEqual(plist['Label'], 'com.mihomo.xray')
        self.assertEqual(plist['ProgramArguments'],
                         ['/u/.local/bin/xray', 'run', '-config', '/u/.config/mihomo/xray-client.json'])
        self.assertIs(plist['RunAtLoad'], True)
        self.assertIs(plist['KeepAlive'], True)
        self.assertEqual(plist['StandardOutPath'], '/u/.config/mihomo/xray.log')
        self.assertEqual(plist['StandardErrorPath'], '/u/.config/mihomo/xray.log')


class AssetTests(unittest.TestCase):
    def test_arm64_asset(self):
        result = run_bash('xray_darwin_asset arm64')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(),
                         'Xray-macos-arm64-v8a.zip 7b1711eaeefd90f27082cf49c311aa57dad44ac13146faab3f0c1601158ea6c8')

    def test_x86_64_asset(self):
        result = run_bash('xray_darwin_asset x86_64')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(),
                         'Xray-macos-64.zip f99119d4aa662ae2e9a2adf57eccf3dad1b43035ae2e06ccc3949c8256e33fd0')

    def test_unknown_machine_rejected(self):
        result = run_bash('xray_darwin_asset aarch64')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')

    def test_sha256_of_abc(self):
        with tempfile.TemporaryDirectory() as directory:
            sample = Path(directory) / 'sample.txt'
            sample.write_bytes(b'abc')
            result = run_bash(f'chain_sha256 "{sample}"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(),
                         'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')


class SecureWriteTests(unittest.TestCase):
    def test_config_file_is_0600_even_under_umask_022(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'xray-client.json'
            result = run_bash(f'umask 022; chain_write_xray_config "{dest}"', GOOD)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o600)
            config = json.loads(dest.read_text())
            self.assertEqual(config['outbounds'][0]['settings']['vnext'][0]['port'], 2087)

    def test_config_dir_is_0700_even_under_umask_022(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'mihomo'
            result = run_bash(f'umask 022; chain_secure_dir "{target}"')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)


def fake_uname(machine='x86_64'):
    return f'uname() {{ echo {machine}; }}; '


def write_fake_xray(path, version):
    path.write_text(f'#!/bin/sh\necho "Xray {version} (fake)"\n')
    path.chmod(0o755)


class XrayInstallIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.script_dir = Path(self.tmp.name) / 'kit'
        self.bin_dir = Path(self.tmp.name) / 'bin'
        (self.script_dir / 'bin').mkdir(parents=True)
        self.bin_dir.mkdir()
        self.archive = self.script_dir / 'bin' / 'Xray-macos-64.zip'

    def tearDown(self):
        self.tmp.cleanup()

    def install(self):
        script = fake_uname() + f'install_xray_darwin "{self.script_dir}" "{self.bin_dir}"'
        return run_bash(script)

    def test_bogus_archive_fails_checksum_and_installs_nothing(self):
        self.archive.write_bytes(b'not a zip')
        result = self.install()
        self.assertEqual(result.returncode, 8, result.stdout + result.stderr)
        self.assertIn('Xray archive checksum mismatch', result.stderr)
        self.assertFalse((self.bin_dir / 'xray').exists())
        self.assertFalse((self.bin_dir / '.xray-mihomo-kit.sha256').exists())

    def test_wrong_version_binary_without_marker_is_not_trusted(self):
        write_fake_xray(self.bin_dir / 'xray', '1.0.0')
        self.archive.write_bytes(b'not a zip')
        result = self.install()
        self.assertEqual(result.returncode, 8)
        self.assertNotIn('already installed', result.stdout)

    def test_matching_marker_is_trusted(self):
        fake = self.bin_dir / 'xray'
        write_fake_xray(fake, '26.10.10')
        digest = hashlib.sha256(fake.read_bytes()).hexdigest()
        (self.bin_dir / '.xray-mihomo-kit.sha256').write_text(digest + '\n')
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('already installed', result.stdout)

    def test_mismatched_marker_forces_reinstall(self):
        fake = self.bin_dir / 'xray'
        write_fake_xray(fake, '26.10.10')
        (self.bin_dir / '.xray-mihomo-kit.sha256').write_text('0' * 64 + '\n')
        self.archive.write_bytes(b'not a zip')
        result = self.install()
        self.assertEqual(result.returncode, 8)
        self.assertNotIn('already installed', result.stdout)

    def test_version_check_rejects_wrong_version(self):
        fake = Path(self.tmp.name) / 'xray-old'
        write_fake_xray(fake, '1.0.0')
        result = run_bash(f'xray_version_ok "{fake}"')
        self.assertEqual(result.returncode, 1)

    def test_version_check_accepts_pinned_version(self):
        fake = Path(self.tmp.name) / 'xray-ok'
        write_fake_xray(fake, XRAY_VERSION_PIN)
        result = run_bash(f'xray_version_ok "{fake}"')
        self.assertEqual(result.returncode, 0, result.stderr)


XRAY_VERSION_PIN = '26.10.10'


@unittest.skipUnless(os.path.isfile(XRAY_BIN) and os.access(XRAY_BIN, os.X_OK),
                     'Xray binary not found (set XRAY_BIN or install ~/.local/bin/xray)')
class XrayBinaryValidationTests(unittest.TestCase):
    def test_bash_rendered_config_passes_xray_test(self):
        for network, port in (('xhttp', 2087), ('tcp', 2088), ('grpc', 2089)):
            with self.subTest(network=network):
                result = run_bash('render_xray_client_json', mode_env(network, port))
                self.assertEqual(result.returncode, 0, result.stderr)
                with tempfile.TemporaryDirectory() as directory:
                    config = Path(directory) / 'xray.json'
                    config.write_text(result.stdout)
                    check = subprocess.run([XRAY_BIN, 'run', '-test', '-config', str(config)],
                                           capture_output=True, text=True)
                self.assertEqual(check.returncode, 0, check.stdout + check.stderr)


if __name__ == '__main__':
    unittest.main()
