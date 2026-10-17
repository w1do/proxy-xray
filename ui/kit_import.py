"""Import of vless:// links made by the owner's kit (amendment 2e, import-only mode).

Pure parsing, no I/O and no subprocess. Every rule is an allowlist; error messages are fixed strings and never echo
any part of the link. Parsed secrets are returned only to the caller, which stores them in the DB.
"""
import json, re
from urllib.parse import parse_qs, unquote, urlsplit

import kit_nl, kit_render

MAX_IMPORT_LINKS = 40
MAX_LINK_LEN = 1024
LABEL_RE = re.compile(r'NL -> (?P<exit>\S+) (?P<mode>XHTTP|TCP|gRPC)(?: (?P<remark>[^\x00-\x1f\x7f]{1,64}))?')
ALLOWED_KEYS = frozenset({'encryption', 'security', 'type', 'sni', 'fp', 'pbk', 'sid', 'flow', 'headerType',
                          'path', 'mode', 'host', 'serviceName'})
TYPES = ('tcp', 'grpc', 'xhttp')


def _fail(message):
    raise ValueError(message)


def _one(query, key):
    values = query.get(key)
    return None if values is None else values[0]


def parse_link(text):
    """Return the inbound row for one vless:// link, or raise ValueError with a fixed Russian message."""
    try:
        url = urlsplit(text)
    except ValueError:
        _fail('Ссылка не разбирается')
    if url.scheme != 'vless':
        _fail('Не vless-ссылка')
    netloc = url.netloc
    if '@' not in netloc or url.password is not None or not url.username:
        _fail('В ссылке нет uuid')
    if '[' in netloc or ']' in netloc:
        _fail('IPv6-адреса не поддерживаются')
    if url.path:
        _fail('Лишний путь в ссылке')
    uuid = url.username.lower()
    if not kit_render.UUID_RE.fullmatch(uuid):
        _fail('Некорректный uuid')
    host = (url.hostname or '').lower()
    if not (kit_render.HOST_IPV4_RE.fullmatch(host)
            or (len(host) <= 253 and '.' in host and kit_render.DOMAIN_RE.fullmatch(host))):
        _fail('Некорректный адрес сервера')
    try:
        port = url.port
    except ValueError:
        port = None
    if port is None or not 1 <= port <= 65535:
        _fail('Некорректный порт')
    if port in kit_nl.SKIP_PORTS:
        _fail('порт 443 не устанавливается')
    try:
        raw_query = parse_qs(url.query, keep_blank_values=True, strict_parsing=True) if url.query else {}
    except ValueError:
        _fail('Некорректные параметры')
    for key, values in raw_query.items():
        if key not in ALLOWED_KEYS:
            _fail('неизвестный параметр')
        if len(values) != 1:
            _fail('параметр повторяется')
    query = {key: values[0] for key, values in raw_query.items()}

    if query.get('encryption', 'none') != 'none':
        _fail('Неподдерживаемое шифрование')
    if query.get('security') != 'reality':
        _fail('Нужен security=reality')
    net = query.get('type')
    if net not in TYPES:
        _fail('Неподдерживаемый тип транспорта')
    sni = (query.get('sni') or '').lower()
    if not sni or len(sni) > 253 or not kit_render.DOMAIN_RE.fullmatch(sni):
        _fail('Некорректный sni')
    if 'fp' in query and query['fp'] not in kit_render.FINGERPRINTS:
        _fail('Некорректный отпечаток клиента')
    pbk = query.get('pbk')
    if pbk is None or not kit_render.PBK_RE.fullmatch(pbk):
        _fail('Некорректный pbk')
    sid = query.get('sid')
    if sid is None:
        _fail('Нет sid')
    sid = sid.lower()
    if not kit_render.SID_RE.fullmatch(sid):
        _fail('Некорректный sid')

    flow, xhttp_json, grpc_service, grpc_multi = '', '{}', '', 0
    if net == 'tcp':
        if query.get('flow') not in (None, '', 'xtls-rprx-vision'):
            _fail('Неподдерживаемый flow')
        if query.get('headerType') not in (None, 'none'):
            _fail('Неподдерживаемый headerType')
        if any(key in query for key in ('path', 'mode', 'host', 'serviceName')):
            _fail('Лишний параметр для tcp')
        flow = query.get('flow') or ''
    elif net == 'xhttp':
        if any(key in query for key in ('flow', 'headerType', 'serviceName')):
            _fail('Лишний параметр для xhttp')
        path = query.get('path')
        if path is None or not kit_render.XHTTP_PATH_RE.fullmatch(path):
            _fail('Некорректный path')
        mode = query.get('mode', 'auto')
        if mode not in kit_render.XHTTP_MODES:
            _fail('Некорректный mode')
        data = {'path': path, 'mode': mode}
        if 'host' in query:
            host_value = query['host'].lower()
            if len(host_value) > 253 or not kit_render.DOMAIN_RE.fullmatch(host_value):
                _fail('Некорректный host')
            data['host'] = host_value
        xhttp_json = json.dumps(data, sort_keys=True)
    else:  # grpc
        if any(key in query for key in ('flow', 'headerType', 'path', 'host')):
            _fail('Лишний параметр для grpc')
        service = query.get('serviceName')
        if service is None or not kit_render.GRPC_SERVICE_RE.fullmatch(service):
            _fail('Некорректный serviceName')
        mode = query.get('mode', 'gun')
        if mode not in ('gun', 'multi'):
            _fail('Некорректный mode')
        grpc_service = service
        grpc_multi = 1 if mode == 'multi' else 0

    try:
        label = unquote(url.fragment, errors='strict')
    except UnicodeError:
        _fail('в подписи нет IP выхода')
    match = LABEL_RE.fullmatch(label)
    if match is None or not kit_render.HOST_IPV4_RE.fullmatch(match.group('exit')):
        _fail('в подписи нет IP выхода')
    if match.group('mode') != kit_nl.MODE_NAME[net]:
        _fail('подпись не совпадает с типом')

    return {
        'port': port,
        'uuid': uuid,
        'exit_ip': match.group('exit'),
        'exit_tag': '',
        'network': net,
        'remark': match.group('remark') or '',
        'flow': flow,
        'pbk': pbk,
        'sid': sid,
        'sni': sni,
        'xhttp_json': xhttp_json,
        'grpc_service': grpc_service,
        'grpc_multi': grpc_multi,
        'source': 'import',
        'nl_host': host,
    }


def parse_links(links):
    """Return (rows, errors). errors = [{'index': 1-based, 'error': message}]. A repeated (port, uuid) is an error."""
    rows, errors, seen = [], [], set()
    for index, text in enumerate(links, start=1):
        try:
            row = parse_link(text)
        except ValueError as exc:
            errors.append({'index': index, 'error': str(exc)})
            continue
        key = (row['port'], row['uuid'])
        if key in seen:
            errors.append({'index': index, 'error': 'дубликат'})
            continue
        seen.add(key)
        rows.append(row)
    return rows, errors
