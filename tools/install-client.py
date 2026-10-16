#!/usr/bin/env python3
"""Install the WSL proxy with official Xray for Reality/XHTTP transport."""
import json
import gzip
import hashlib
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
XRAY = HOME / '.local/bin/xray'
MIHOMO = HOME / '.local/bin/mihomo'
XRAY_DIR = HOME / '.config/mihomo'
UNIT_DIR = HOME / '.config/systemd/user'
NO_PROXY_ENV = {k: v for k, v in os.environ.items() if not k.lower().endswith('_proxy')}


def run(args, **kwargs):
    return subprocess.run(args, env=NO_PROXY_ENV, text=True, capture_output=True,
                          timeout=kwargs.pop('timeout', 45), **kwargs)


def check(args, message, **kwargs):
    result = run(args, **kwargs)
    if result.returncode:
        detail = (result.stderr + '\n' + result.stdout).strip()[-800:]
        raise RuntimeError(f'{message}: {detail}')
    return result.stdout.strip()


def settings():
    values = {}
    for line in (ROOT / 'proxy.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key] = value.strip().strip('"\'')
    return values


def install_binaries(env):
    if platform.machine() != 'x86_64':
        raise RuntimeError('Этот установщик поддерживает Linux x86_64; бинарники для другой архитектуры не подготовлены')
    XRAY.parent.mkdir(parents=True, exist_ok=True)
    bundles = [(MIHOMO, ROOT / 'bin/mihomo-linux-amd64-compatible-v1.19.32.gz',
                'ba3ce607747a07f948fc35780e108a4a7c7f552a38b9bd4d115f313ebcb89c20',
                ['-v'], 'Mihomo Meta v1.19.32 '),
               (XRAY, ROOT / 'bin/xray-linux-amd64-v26.10.10.gz',
                'd285610cb2f9cce29944f19e51dde690ec261e4d300f637a79086a24d108421b',
                ['version'], 'Xray 26.10.10 ')]
    for binary, archive, expected_hash, version_args, expected_version in bundles:
        if binary.is_file() and run([str(binary), *version_args]).stdout.startswith(expected_version):
            continue
        if not archive.is_file():
            raise RuntimeError(f'В клоне отсутствует {archive.relative_to(ROOT)}')
        if hashlib.sha256(archive.read_bytes()).hexdigest() != expected_hash:
            raise RuntimeError(f'Контрольная сумма архива {binary.name} не совпала')
        with tempfile.NamedTemporaryFile(dir=XRAY.parent, delete=False) as handle:
            temporary = Path(handle.name)
        try:
            with gzip.open(archive, 'rb') as source, temporary.open('wb') as target:
                shutil.copyfileobj(source, target)
            temporary.chmod(0o755)
            installed_version = check([str(temporary), *version_args], f'{binary.name} не запускается')
            if not installed_version.startswith(expected_version):
                raise RuntimeError(f'Неверная версия {binary.name} в архиве')
            temporary.replace(binary)
        finally:
            temporary.unlink(missing_ok=True)
        print(f'{binary.name} установлен из архива репозитория')


def profile_from_settings(env, requested):
    expected_port = {'108.61.222.91': 2083, '149.28.240.154': 2087}[requested]
    port = int(env.get('SERVER_PORT') or expected_port)
    if port != expected_port:
        raise RuntimeError(f'Для выхода {requested} нужен вход NL:{expected_port}, а указан порт {port}')
    if env.get('SERVER_NETWORK', 'xhttp') != 'xhttp':
        raise RuntimeError('Для текущих серверов SERVER_NETWORK должен быть xhttp')
    for key in ('SERVER_IP', 'UUID', 'PUBLIC_KEY', 'SHORT_ID'):
        if not env.get(key):
            raise RuntimeError(f'В proxy.env отсутствует {key}')
    return {'port': port, 'uuid': env['UUID'],
            'sni': env.get('REALITY_SERVER_NAME', 'dl.google.com'),
            'sid': env['SHORT_ID'], 'pbk': env['PUBLIC_KEY'],
            'xhttp': {'path': env.get('XHTTP_PATH', '/dl'),
                      'mode': env.get('XHTTP_MODE', 'auto')},
            'exit': requested}


def xray_config(env, row):
    return {'log': {'loglevel': 'warning'},
            'inbounds': [{'listen': '127.0.0.1', 'port': 18080,
                          'protocol': 'socks', 'settings': {'udp': True}}],
            'outbounds': [{'protocol': 'vless',
                           'settings': {'vnext': [{'address': env['SERVER_IP'],
                                                  'port': row['port'],
                                                  'users': [{'id': row['uuid'], 'encryption': 'none'}]}]},
                           'streamSettings': {'network': 'xhttp', 'security': 'reality',
                                              'xhttpSettings': row['xhttp'],
                                              'realitySettings': {'serverName': row['sni'],
                                                                  'fingerprint': 'chrome',
                                                                  'password': row['pbk'],
                                                                  'shortId': row['sid']}}}]}


def mihomo_config():
    current = XRAY_DIR / 'config.yaml'
    if current.exists():
        old = current.read_text()
        match = re.search(r'(?ms)^proxies:\n.*?(?=^proxy-groups:)', old)
        if match:
            return old[:match.start()] + 'proxies:\n  - name: USA\n    type: socks5\n    server: 127.0.0.1\n    port: 18080\n    udp: true\n\n' + old[match.end():]
    return '''mixed-port: 7890
allow-lan: false
mode: rule
log-level: warning
proxies:
  - name: USA
    type: socks5
    server: 127.0.0.1
    port: 18080
    udp: true
proxy-groups:
  - name: PROXY
    type: select
    proxies:
      - USA
rules:
  - IP-CIDR,127.0.0.0/8,DIRECT,no-resolve
  - IP-CIDR,10.0.0.0/8,DIRECT,no-resolve
  - IP-CIDR,172.16.0.0/12,DIRECT,no-resolve
  - IP-CIDR,192.168.0.0/16,DIRECT,no-resolve
  - DOMAIN-SUFFIX,local,DIRECT
  - DOMAIN-SUFFIX,localhost,DIRECT
  - DOMAIN-SUFFIX,ru,DIRECT
  - DOMAIN-SUFFIX,рф,DIRECT
  - MATCH,PROXY
'''


def atomic_write(path, content, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.chmod(mode)
    temporary.replace(path)


def service(name, binary, config, log):
    return f'''[Unit]
Description={name} local proxy
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
ExecStart={binary} {config}
Restart=always
RestartSec=3
UnsetEnvironment=http_proxy https_proxy all_proxy no_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY WS_PROXY WSS_PROXY ws_proxy wss_proxy
StandardOutput=append:{log}
StandardError=append:{log}

[Install]
WantedBy=default.target
'''


def configure_shell():
    begin = '# mihomo local proxy begin'
    end = '# mihomo local proxy end'
    block = f'''{begin}
export http_proxy=http://127.0.0.1:7890
export https_proxy=$http_proxy
export all_proxy=socks5://127.0.0.1:7890
export no_proxy=localhost,127.0.0.1,::1
export HTTP_PROXY=$http_proxy
export HTTPS_PROXY=$https_proxy
export ALL_PROXY=$all_proxy
export NO_PROXY=$no_proxy
export WS_PROXY=$http_proxy
export WSS_PROXY=$http_proxy
export ws_proxy=$http_proxy
export wss_proxy=$http_proxy
{end}'''
    for path in (HOME / '.bashrc', HOME / '.zshrc'):
        current = path.read_text() if path.exists() else ''
        pattern = re.compile(r'(?ms)^' + re.escape(begin) + r'\n.*?^' + re.escape(end) + r'\n?')
        current = pattern.sub('', current).rstrip()
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        atomic_write(path, current + '\n\n' + block + '\n', mode)


def main():
    env = settings()
    requested = sys.argv[1] if len(sys.argv) > 1 else '149.28.240.154'
    if requested not in ('149.28.240.154', '108.61.222.91'):
        raise RuntimeError('Укажите IP USA2 149.28.240.154 или USA1 108.61.222.91')
    row = profile_from_settings(env, requested)
    install_binaries(env)
    config = xray_config(env, row)
    yaml = mihomo_config()
    with tempfile.TemporaryDirectory() as directory:
        xc = Path(directory) / 'xray.json'
        mc = Path(directory) / 'mihomo.yaml'
        xc.write_text(json.dumps(config))
        mc.write_text(yaml)
        check([str(XRAY), 'run', '-test', '-config', str(xc)], 'Ошибка конфигурации Xray')
        check([str(MIHOMO), '-t', '-f', str(mc)], 'Ошибка конфигурации Mihomo')
    XRAY_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write(XRAY_DIR / 'xray-client.json', json.dumps(config, indent=2) + '\n')
    atomic_write(XRAY_DIR / 'config.yaml', yaml)
    atomic_write(UNIT_DIR / 'xray-mihomo.service',
                 service('Xray', XRAY, f'run -config {XRAY_DIR / "xray-client.json"}',
                         XRAY_DIR / 'xray.log'), 0o644)
    atomic_write(UNIT_DIR / 'mihomo.service',
                 service('Mihomo', MIHOMO, f'-d {XRAY_DIR}', XRAY_DIR / 'mihomo.log'), 0o644)
    check(['systemctl', '--user', 'daemon-reload'], 'Не удалось перечитать systemd')
    check(['systemctl', '--user', 'enable', '--now', 'xray-mihomo.service'], 'Xray не запустился')
    check(['systemctl', '--user', 'restart', 'xray-mihomo.service'], 'Xray не перезапустился')
    check(['systemctl', '--user', 'enable', '--now', 'mihomo.service'], 'Mihomo не запустился')
    check(['systemctl', '--user', 'restart', 'mihomo.service'], 'Mihomo не перезапустился')
    for _ in range(8):
        time.sleep(1)
        result = run(['curl', '--noproxy', '', '-fsS', '--max-time', '12',
                      '-x', 'http://127.0.0.1:7890', 'https://api.ipify.org'], timeout=15)
        if result.returncode == 0 and result.stdout.strip() == requested:
            configure_shell()
            print(f'Установлено: WSL -> Xray -> NL:{row["port"]} -> {requested}')
            print('Локальный прокси: http://127.0.0.1:7890')
            print(f'Проверенный выходной IP: {requested}')
            return
    raise RuntimeError('Прокси не прошёл проверку IP. Xray: ' +
                       run(['systemctl', '--user', 'is-active', 'xray-mihomo.service']).stdout.strip() +
                       ', Mihomo: ' + run(['systemctl', '--user', 'is-active', 'mihomo.service']).stdout.strip() +
                       ', curl: ' + result.stderr.strip()[-250:])


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as error:
        print('Ошибка установки: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
