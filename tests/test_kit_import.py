import importlib, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ui'))
kit_import = importlib.import_module('kit_import')
kit_nl = importlib.import_module('kit_nl')

UUID = '11111111-2222-3333-4444-555555555555'
PBK = 'A' * 43
SERVER = '185.0.2.10'
EXIT = '149.28.240.154'


def with_query(link, extra):
    head, sep, fragment = link.partition('#')
    return head + '&' + extra + sep + fragment


def base_row(**kw):
    row = {'port': 2088, 'uuid': UUID, 'email': 'phone', 'sni': 'www.example.com', 'sid': 'abcd', 'pbk': PBK,
           'network': 'tcp', 'flow': 'xtls-rprx-vision', 'grpc': '', 'multi': False, 'xhttp': {}, 'exit': EXIT}
    row.update(kw)
    return row


def tcp_link(**kw):
    return kit_nl.make_link(base_row(**kw), SERVER)


def grpc_link(**kw):
    row = base_row(port=2089, network='grpc', flow='', grpc='svc', multi=True, **kw)
    return kit_nl.make_link(row, SERVER)


def xhttp_link(**kw):
    row = base_row(port=2087, network='xhttp', flow='', xhttp={'path': '/dl', 'mode': 'auto', 'host': 'cdn.example.com'}, **kw)
    return kit_nl.make_link(row, SERVER)


class ParseValidTests(unittest.TestCase):
    def test_tcp_vision(self):
        row = kit_import.parse_link(tcp_link())
        self.assertEqual(row, {'port': 2088, 'uuid': UUID, 'exit_ip': EXIT, 'exit_tag': '', 'network': 'tcp',
                               'remark': 'phone', 'flow': 'xtls-rprx-vision', 'pbk': PBK, 'sid': 'abcd',
                               'sni': 'www.example.com', 'xhttp_json': '{}', 'grpc_service': '', 'grpc_multi': 0,
                               'source': 'import', 'nl_host': SERVER})

    def test_grpc_multi(self):
        row = kit_import.parse_link(grpc_link())
        self.assertEqual((row['network'], row['grpc_service'], row['grpc_multi'], row['flow']), ('grpc', 'svc', 1, ''))
        self.assertEqual(row['exit_ip'], EXIT)
        self.assertEqual(row['source'], 'import')

    def test_xhttp_with_host(self):
        row = kit_import.parse_link(xhttp_link())
        self.assertEqual(row['network'], 'xhttp')
        self.assertEqual(row['xhttp_json'], '{"host": "cdn.example.com", "mode": "auto", "path": "/dl"}')
        self.assertEqual((row['port'], row['nl_host']), (2087, SERVER))

    def test_parse_links_returns_rows_and_no_errors(self):
        rows, errors = kit_import.parse_links([tcp_link(), grpc_link(), xhttp_link()])
        self.assertEqual(len(rows), 3)
        self.assertEqual(errors, [])


class ParseRejectTests(unittest.TestCase):
    def assertRejected(self, text, message):
        with self.assertRaises(ValueError) as ctx:
            kit_import.parse_link(text)
        self.assertEqual(str(ctx.exception), message)
        self.assertNotIn(text, str(ctx.exception))

    def test_bad_scheme(self):
        self.assertRejected('vmess://' + tcp_link()[len('vless://'):], 'Не vless-ссылка')

    def test_bad_uuid(self):
        self.assertRejected(tcp_link().replace(UUID, 'not-a-uuid'), 'Некорректный uuid')

    def test_uuid_short(self):
        self.assertRejected(tcp_link().replace(UUID, '11111111-2222-3333-4444-55555555555'), 'Некорректный uuid')

    def test_bad_pbk_short(self):
        self.assertRejected(tcp_link().replace(PBK, 'A' * 42), 'Некорректный pbk')

    def test_bad_pbk_plus(self):
        self.assertRejected(tcp_link().replace(PBK, 'A' * 42 + '+'), 'Некорректный pbk')

    def test_bad_sid(self):
        self.assertRejected(tcp_link().replace('sid=abcd', 'sid=abc'), 'Некорректный sid')
        self.assertRejected(tcp_link().replace('sid=abcd', 'sid=' + 'ab' * 9), 'Некорректный sid')

    def test_security_tls(self):
        self.assertRejected(tcp_link().replace('security=reality', 'security=tls'), 'Нужен security=reality')

    def test_encryption_not_none(self):
        self.assertRejected(tcp_link().replace('encryption=none', 'encryption=aes'), 'Неподдерживаемое шифрование')

    def test_type_ws(self):
        self.assertRejected(tcp_link().replace('type=tcp', 'type=ws'), 'Неподдерживаемый тип транспорта')

    def test_unknown_key(self):
        self.assertRejected(with_query(tcp_link(), 'spx=%2F'), 'неизвестный параметр')

    def test_duplicate_key(self):
        self.assertRejected(with_query(tcp_link(), 'sni=other.example.com'), 'параметр повторяется')

    def test_tcp_header_type_not_none(self):
        self.assertRejected(tcp_link().replace('headerType=none', 'headerType=http'), 'Неподдерживаемый headerType')

    def test_bad_sni(self):
        self.assertRejected(tcp_link().replace('sni=www.example.com', 'sni=bad_name'), 'Некорректный sni')

    def test_invalid_fingerprint(self):
        self.assertRejected(tcp_link().replace('fp=chrome', 'fp=netscape'), 'Некорректный отпечаток клиента')

    def test_port_443(self):
        self.assertRejected(tcp_link().replace('@185.0.2.10:2088', '@185.0.2.10:443'), 'порт 443 не устанавливается')

    def test_port_zero(self):
        self.assertRejected(tcp_link().replace(':2088?', ':0?'), 'Некорректный порт')

    def test_ipv6_host(self):
        self.assertRejected(tcp_link().replace('@185.0.2.10:2088', '@[::1]:2088'), 'IPv6-адреса не поддерживаются')

    def test_host_with_underscore(self):
        self.assertRejected(tcp_link().replace('@185.0.2.10:2088', '@bad_host.example:2088'), 'Некорректный адрес сервера')

    def test_missing_label(self):
        self.assertRejected(tcp_link().split('#')[0], 'в подписи нет IP выхода')

    def test_label_without_ipv4_exit(self):
        self.assertRejected(tcp_link().split('#')[0] + '#NL%20-%3E%20example.com%20TCP%20x', 'в подписи нет IP выхода')

    def test_label_mode_mismatch(self):
        self.assertRejected(grpc_link().replace('gRPC', 'TCP'), 'подпись не совпадает с типом')

    def test_xhttp_without_path(self):
        self.assertRejected(xhttp_link().replace('path=%2Fdl&', ''), 'Некорректный path')

    def test_grpc_without_service(self):
        self.assertRejected(grpc_link().replace('serviceName=svc&', ''), 'Некорректный serviceName')

    def test_grpc_invalid_mode(self):
        self.assertRejected(grpc_link().replace('mode=multi', 'mode=bogus'), 'Некорректный mode')

    def test_tcp_with_service_name(self):
        self.assertRejected(with_query(tcp_link(), 'serviceName=svc'), 'Лишний параметр для tcp')

    def test_control_char_in_label(self):
        self.assertRejected(tcp_link().split('#')[0] + '#NL%20-%3E%20' + EXIT + '%20TCP%20a%0Ab', 'в подписи нет IP выхода')


class ParseLinksDuplicateTests(unittest.TestCase):
    def test_duplicate_uuid_port_is_error_at_second_index(self):
        rows, errors = kit_import.parse_links([tcp_link(), tcp_link()])
        self.assertEqual(len(rows), 1)
        self.assertEqual(errors, [{'index': 2, 'error': 'дубликат'}])


class ImportModuleTests(unittest.TestCase):
    def test_module_has_no_subprocess_and_caps_are_set(self):
        source = (ROOT / 'ui' / 'kit_import.py').read_text(encoding='utf-8')
        self.assertNotIn('import subprocess', source)
        self.assertNotIn('from subprocess', source)
        self.assertEqual(kit_import.MAX_IMPORT_LINKS, 40)
        self.assertEqual(kit_import.MAX_LINK_LEN, 1024)


if __name__ == '__main__':
    unittest.main()
