import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('install_client', ROOT / 'tools' / 'install-client.py')
install_client = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(install_client)

BASE = {'SERVER_IP': '192.0.2.10', 'UUID': 'test-uuid',
        'PUBLIC_KEY': 'dummy-public-key', 'SHORT_ID': 'abcd1234'}


def env_for(port, network):
    env = dict(BASE, SERVER_PORT=str(port), SERVER_NETWORK=network)
    if network == 'grpc':
        env['GRPC_SERVICE_NAME'] = 'grpc-test'
    return env


class PortMapTests(unittest.TestCase):
    def test_nl_ports_map(self):
        self.assertEqual(install_client.NL_PORTS, {
            '108.61.222.91': frozenset({2083, 2084, 2085, 2086}),
            '149.28.240.154': frozenset({2087, 2088, 2089, 2090}),
        })

    def test_usa2_accepts_all_nl_ports(self):
        cases = ((2087, 'xhttp'), (2088, 'tcp'), (2089, 'grpc'), (2090, 'xhttp'))
        for port, network in cases:
            with self.subTest(port=port):
                row = install_client.profile_from_settings(env_for(port, network), '149.28.240.154')
                self.assertEqual(row['port'], port)

    def test_usa1_accepts_all_nl_ports(self):
        cases = ((2083, 'xhttp'), (2084, 'tcp'), (2085, 'grpc'), (2086, 'xhttp'))
        for port, network in cases:
            with self.subTest(port=port):
                row = install_client.profile_from_settings(env_for(port, network), '108.61.222.91')
                self.assertEqual(row['port'], port)

    def test_usa2_rejects_usa1_port(self):
        with self.assertRaises(RuntimeError) as context:
            install_client.profile_from_settings(env_for(2083, 'xhttp'), '149.28.240.154')
        self.assertIn('2087/2088/2089/2090', str(context.exception))

    def test_usa1_rejects_usa2_port(self):
        with self.assertRaises(RuntimeError) as context:
            install_client.profile_from_settings(env_for(2088, 'tcp'), '108.61.222.91')
        self.assertIn('2083/2084/2085/2086', str(context.exception))

    def test_default_port_is_lowest(self):
        self.assertEqual(install_client.profile_from_settings(BASE, '149.28.240.154')['port'], 2087)
        self.assertEqual(install_client.profile_from_settings(BASE, '108.61.222.91')['port'], 2083)


if __name__ == '__main__':
    unittest.main()
