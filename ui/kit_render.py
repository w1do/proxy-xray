"""Renders the Xray client JSON and the Mihomo YAML from DB rows, and validates user rules.

Pure functions only (no I/O). Rule text is re-validated here, so a bad rule can never reach the YAML.
"""
import ipaddress, re

RULE_TYPES = ('DOMAIN', 'DOMAIN-SUFFIX', 'DOMAIN-KEYWORD', 'GEOSITE', 'GEOIP', 'IP-CIDR')
POLICIES = ('PROXY', 'DIRECT', 'REJECT')
NO_RESOLVE_TYPES = ('GEOIP', 'IP-CIDR')
SYSTEM_RULES = (('DOMAIN', 'api.ipify.org', 'PROXY', False),)
DEFAULT_MATCH = 'PROXY'
DEFAULT_RULES = (
    ('DOMAIN-SUFFIX', 'openai.com', 'PROXY', False), ('DOMAIN-SUFFIX', 'chatgpt.com', 'PROXY', False),
    ('DOMAIN-SUFFIX', 'anthropic.com', 'PROXY', False), ('DOMAIN-SUFFIX', 'claude.ai', 'PROXY', False),
    ('DOMAIN-SUFFIX', 'telegram.org', 'PROXY', False), ('DOMAIN-SUFFIX', 't.me', 'PROXY', False),
    ('GEOIP', 'PRIVATE', 'DIRECT', True), ('DOMAIN-SUFFIX', 'local', 'DIRECT', False),
    ('DOMAIN-SUFFIX', 'localhost', 'DIRECT', False), ('GEOSITE', 'category-ru', 'DIRECT', False),
    ('DOMAIN-SUFFIX', 'ru', 'DIRECT', False), ('DOMAIN-SUFFIX', 'xn--p1ai', 'DIRECT', False),
    ('GEOIP', 'RU', 'DIRECT', False))
KNOWN_EXITS = {'108.61.222.91': {'label': 'USA1', 'ports': (2083, 2084, 2085, 2086)},
               '149.28.240.154': {'label': 'USA2', 'ports': (2087, 2088, 2089, 2090)}}
XRAY_SOCKS_PORT = 18080
MIXED_PORT = 7890
MAX_RULES = 500

DOMAIN_RE = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*')
UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
HOST_IPV4_RE = re.compile(r'(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}')
PBK_RE = re.compile(r'[A-Za-z0-9_-]{43}')
SID_RE = re.compile(r'(?:[0-9a-f]{2}){0,8}')
XHTTP_PATH_RE = re.compile(r'/[A-Za-z0-9._~/-]{0,255}')
XHTTP_MODES = ('auto', 'packet-up', 'stream-up', 'stream-one')
GRPC_SERVICE_RE = re.compile(r'[A-Za-z0-9._/-]{1,128}')
FINGERPRINTS = ('chrome', 'firefox', 'safari', 'ios', 'android', 'edge', '360', 'qq', 'random', 'randomized')
KEYWORD_RE = re.compile(r'[a-z0-9-]{1,63}')
GEOSITE_RE = re.compile(r'[A-Za-z0-9@!._-]{1,64}')
GEOIP_RE = re.compile(r'[A-Za-z0-9_-]{2,32}')
FORBIDDEN_CHARS = set(',#\'"\n\0')

DNS_BLOCK = """dns:
  enable: true
  enhanced-mode: fake-ip
  fake-ip-range: 198.18.0.1/16
  respect-rules: true
  proxy-server-nameserver:
    - system
  direct-nameserver:
    - system
  nameserver:
    - https://1.1.1.1/dns-query
    - https://8.8.8.8/dns-query"""


def _fail(index, text):
    prefix = f'Правило {index}: ' if index is not None else 'Правило: '
    raise ValueError(prefix + text)


def _check_value(value, index):
    if not isinstance(value, str):
        _fail(index, 'значение должно быть строкой')
    value = value.strip()
    if not 1 <= len(value) <= 253:
        _fail(index, 'значение должно быть от 1 до 253 символов')
    if any(ch.isspace() for ch in value) or any(ch in FORBIDDEN_CHARS for ch in value):
        _fail(index, 'значение содержит запрещённые символы')
    return value


def validate_rule(d, index=None):
    """Return {type, value, policy, no_resolve, enabled, note} or raise ValueError (the value is never echoed)."""
    if not isinstance(d, dict):
        _fail(index, 'ожидается объект')
    rtype = d.get('type')
    if rtype not in RULE_TYPES:
        _fail(index, 'недопустимый тип')
    policy = d.get('policy')
    if policy not in POLICIES:
        _fail(index, 'недопустимая политика')
    value = _check_value(d.get('value'), index)
    if rtype in ('DOMAIN', 'DOMAIN-SUFFIX'):
        value = value.lower().rstrip('.')
        try:
            value = value.encode('idna').decode('ascii')
        except UnicodeError:
            _fail(index, 'недопустимое доменное имя')
        if not DOMAIN_RE.fullmatch(value) or len(value) > 253:
            _fail(index, 'недопустимое доменное имя')
    elif rtype == 'DOMAIN-KEYWORD':
        value = value.lower()
        if not KEYWORD_RE.fullmatch(value):
            _fail(index, 'недопустимое ключевое слово')
    elif rtype == 'GEOSITE':
        if not GEOSITE_RE.fullmatch(value):
            _fail(index, 'недопустимое имя geosite')
    elif rtype == 'GEOIP':
        value = value.upper()
        if not GEOIP_RE.fullmatch(value):
            _fail(index, 'недопустимый код geoip')
    else:  # IP-CIDR
        try:
            value = str(ipaddress.IPv4Network(value, strict=False))
        except ValueError:
            _fail(index, 'недопустимая IPv4-подсеть')
    no_resolve = d.get('no_resolve', False)
    if not isinstance(no_resolve, bool):
        _fail(index, 'no_resolve должен быть логическим значением')
    no_resolve = no_resolve and rtype in NO_RESOLVE_TYPES
    enabled = d.get('enabled', True)
    if not isinstance(enabled, bool):
        _fail(index, 'enabled должен быть логическим значением')
    note = d.get('note', '')
    if note is None:
        note = ''
    if not isinstance(note, str) or len(note) > 200:
        _fail(index, 'примечание: строка не длиннее 200 символов')
    return {'type': rtype, 'value': value, 'policy': policy, 'no_resolve': no_resolve,
            'enabled': enabled, 'note': note}


def validate_rules(payload):
    """Return (rules, match) or raise ValueError."""
    if not isinstance(payload, dict):
        raise ValueError('Ожидается объект с правилами')
    raw = payload.get('rules')
    if not isinstance(raw, list):
        raise ValueError('Поле rules должно быть списком')
    if len(raw) > MAX_RULES:
        raise ValueError(f'Не больше {MAX_RULES} правил')
    match = payload.get('match')
    if match not in POLICIES:
        raise ValueError('MATCH: недопустимая политика')
    rules, seen = [], set()
    for index, item in enumerate(raw, start=1):
        rule = validate_rule(item, index)
        key = (rule['type'], rule['value'])
        if key in seen:
            raise ValueError(f'Правило {index}: дубликат')
        seen.add(key)
        rules.append(rule)
    return rules, match


def rule_line(t, v, p, no_resolve):
    return f'  - {t},{v},{p}' + (',no-resolve' if no_resolve else '')


def xray_client_config(nl_host, row, fingerprint='firefox'):
    """Client Xray config: local SOCKS on 127.0.0.1:18080 -> VLESS+REALITY to NL:<row port>."""
    if not nl_host or not row.get('uuid') or not row.get('pbk') or not row.get('sni'):
        raise ValueError('Не заданы хост NL, uuid, pbk или sni')
    # Defence in depth for both sources (discovered and imported rows): every value that reaches the rendered JSON is re-checked.
    if (not UUID_RE.fullmatch(str(row['uuid'])) or not PBK_RE.fullmatch(str(row['pbk']))
            or not SID_RE.fullmatch(str(row.get('sid', ''))) or not DOMAIN_RE.fullmatch(str(row['sni']).lower())):
        raise ValueError('Недопустимые параметры входа')
    if row['network'] == 'xhttp':
        path = _json_dict(row.get('xhttp_json')).get('path', '/dl')
        if not XHTTP_PATH_RE.fullmatch(str(path)):
            raise ValueError('Недопустимые параметры входа')
    net = row['network']
    user = {'id': row['uuid'], 'encryption': 'none'}
    if net == 'tcp':
        user['flow'] = 'xtls-rprx-vision'
    stream = {'network': net, 'security': 'reality'}
    if net == 'xhttp':
        xhttp = _json_dict(row.get('xhttp_json'))
        stream['xhttpSettings'] = {'path': xhttp.get('path', '/dl'), 'mode': xhttp.get('mode', 'auto')}
    if net == 'grpc':
        if not row.get('grpc_service'):
            raise ValueError('Для gRPC не задано имя сервиса')
        stream['grpcSettings'] = {'serviceName': row['grpc_service']}
    stream['realitySettings'] = {'serverName': row['sni'], 'fingerprint': fingerprint,
                                 'password': row['pbk'], 'shortId': row['sid']}
    return {
        'log': {'loglevel': 'warning'},
        'inbounds': [{'listen': '127.0.0.1', 'port': XRAY_SOCKS_PORT, 'protocol': 'socks',
                      'settings': {'udp': True}}],
        'outbounds': [{'protocol': 'vless',
                       'settings': {'vnext': [{'address': nl_host, 'port': row['port'], 'users': [user]}]},
                       'streamSettings': stream}],
    }


def _json_dict(text):
    import json
    try:
        value = json.loads(text or '{}')
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def mihomo_config(rules, match):
    """Mihomo YAML text. `rules` are DB rows; disabled rows are skipped and each rule is re-validated."""
    if match not in POLICIES:
        raise ValueError('MATCH: недопустимая политика')
    lines = [
        f'mixed-port: {MIXED_PORT}',
        'allow-lan: true',
        'bind-address: "*"',
        'mode: rule',
        'log-level: warning',
        'ipv6: false',
        '',
        DNS_BLOCK,
        '',
        'proxies:',
        '  - name: USA',
        '    type: socks5',
        '    server: 127.0.0.1',
        f'    port: {XRAY_SOCKS_PORT}',
        '    udp: true',
        '',
        'proxy-groups:',
        '  - name: PROXY',
        '    type: select',
        '    proxies:',
        '      - USA',
        '',
        'rules:',
    ]
    for t, v, p, nr in SYSTEM_RULES:
        lines.append(rule_line(t, v, p, nr))
    for index, row in enumerate(rules, start=1):
        if not row.get('enabled', True):
            continue
        rule = validate_rule(row, index)
        lines.append(rule_line(rule['type'], rule['value'], rule['policy'], rule['no_resolve']))
    lines.append(f'  - MATCH,{match}')
    return '\n'.join(lines) + '\n'
