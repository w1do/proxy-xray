"""Tests for tools/mihomo-config.py. Run: python3 -m unittest discover -s tests -v"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import importlib.util

spec = importlib.util.spec_from_file_location('mihomo_config', ROOT / 'tools' / 'mihomo-config.py')
mihomo_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mihomo_config)

MIHOMO = Path(os.environ.get('MIHOMO_BIN', Path.home() / '.local/bin/mihomo'))

BASE = {
    'SERVER_IP': '192.0.2.10',
    'UUID': '00000000-0000-4000-8000-000000000001',
    'PUBLIC_KEY': 'AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8',
    'SHORT_ID': 'abcdef0123456789',
    'REALITY_SERVER_NAME': 'dl.google.com',
}


def env_for(network, **extra):
    env = dict(BASE)
    if network == 'xhttp':
        env.update(SERVER_PORT='2083', SERVER_NETWORK='xhttp', XHTTP_PATH='/dl', XHTTP_MODE='auto')
    elif network == 'tcp':
        env.update(SERVER_PORT='2084', SERVER_NETWORK='tcp')
    elif network == 'grpc':
        env.update(SERVER_PORT='2085', SERVER_NETWORK='grpc', GRPC_SERVICE_NAME='grpc-test')
    env.update(extra)
    return env


def render_parsed(env):
    return yaml.safe_load(mihomo_config.render(env))


class RenderTests(unittest.TestCase):
    def test_xhttp_block(self):
        usa = render_parsed(env_for('xhttp'))['proxies'][0]
        self.assertEqual(usa['network'], 'xhttp')
        self.assertEqual(usa['xhttp-opts'], {'path': '/dl', 'mode': 'auto'})
        self.assertNotIn('flow', usa)
        self.assertEqual(usa['port'], 2083)

    def test_tcp_block_uses_vision_flow(self):
        usa = render_parsed(env_for('tcp'))['proxies'][0]
        self.assertEqual(usa['network'], 'tcp')
        self.assertEqual(usa['flow'], 'xtls-rprx-vision')
        self.assertNotIn('xhttp-opts', usa)
        self.assertNotIn('grpc-opts', usa)
        self.assertEqual(usa['port'], 2084)

    def test_grpc_block(self):
        usa = render_parsed(env_for('grpc'))['proxies'][0]
        self.assertEqual(usa['network'], 'grpc')
        self.assertEqual(usa['grpc-opts'], {'grpc-service-name': 'grpc-test'})
        self.assertNotIn('flow', usa)
        self.assertEqual(usa['port'], 2085)

    def test_reality_fields_present(self):
        usa = render_parsed(env_for('tcp'))['proxies'][0]
        self.assertEqual(usa['servername'], 'dl.google.com')
        self.assertEqual(usa['reality-opts'], {'public-key': BASE['PUBLIC_KEY'], 'short-id': 'abcdef0123456789'})
        self.assertTrue(usa['tls'])

    def test_network_inferred_from_xhttp_path_when_unset(self):
        env = env_for('xhttp')
        del env['SERVER_NETWORK']
        self.assertEqual(render_parsed(env)['proxies'][0]['network'], 'xhttp')
        env = env_for('tcp')
        del env['SERVER_NETWORK']
        self.assertEqual(render_parsed(env)['proxies'][0]['network'], 'tcp')

    def test_proxy_group_and_final_rule(self):
        config = render_parsed(env_for('tcp'))
        self.assertEqual(config['proxy-groups'][0]['proxies'], ['USA'])
        self.assertEqual(config['rules'][-1], 'MATCH,PROXY')


class ErrorTests(unittest.TestCase):
    def test_unknown_network_rejected(self):
        with self.assertRaises(ValueError):
            mihomo_config.render(env_for('tcp', SERVER_NETWORK='ws'))

    def test_missing_required_key_rejected(self):
        for key in ('SERVER_IP', 'SERVER_PORT', 'UUID', 'PUBLIC_KEY', 'SHORT_ID'):
            env = env_for('tcp')
            env.pop(key, None)
            with self.subTest(key=key), self.assertRaises(ValueError):
                mihomo_config.render(env)

    def test_grpc_without_service_name_rejected(self):
        env = env_for('grpc')
        del env['GRPC_SERVICE_NAME']
        with self.assertRaises(ValueError):
            mihomo_config.render(env)


class CliTests(unittest.TestCase):
    def test_cli_reads_proxy_env_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'proxy.env'
            path.write_text('\n'.join(f'{k}={v}' for k, v in env_for('grpc').items()) + '\n')
            result = subprocess.run([sys.executable, str(ROOT / 'tools' / 'mihomo-config.py'), str(path)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(yaml.safe_load(result.stdout)['proxies'][0]['network'], 'grpc')

    def test_cli_usage_error(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tools' / 'mihomo-config.py')],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)


@unittest.skipUnless(MIHOMO.is_file() and os.access(MIHOMO, os.X_OK), 'mihomo binary not installed')
class MihomoValidationTests(unittest.TestCase):
    def test_mihomo_accepts_each_mode(self):
        for network in ('xhttp', 'tcp', 'grpc'):
            with self.subTest(network=network), tempfile.TemporaryDirectory() as tmp:
                config = Path(tmp) / 'config.yaml'
                config.write_text(mihomo_config.render(env_for(network)))
                result = subprocess.run([str(MIHOMO), '-d', tmp, '-f', str(config), '-t'],
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
