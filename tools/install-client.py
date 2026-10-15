#!/usr/bin/env python3
"""Install the WSL proxy with official Xray for Reality/XHTTP transport."""
import json
import os
from pathlib import Path
import re
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
        raise RuntimeError(f'{message}: {result.stderr.strip()[-500:]}')
    return result.stdout.strip()


def settings():
    values = {}
    for line in (ROOT / 'proxy.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key] = value.strip().strip('"\'')
    return values


REMOTE = r'''import json, subprocess
c=json.load(open('/usr/local/x-ui/bin/config.json'))
out={o.get('tag'):o for o in c.get('outbounds',[])}
rows=[]
for i in c.get('inbounds',[]):
 s=i.get('streamSettings',{})
 if s.get('network')!='xhttp' or s.get('security')!='reality': continue
 r=s['realitySettings']; k=subprocess.run(['/usr/local/x-ui/bin/xray-linux-amd64','x25519','-i',r['privateKey']],capture_output=True,text=True,check=True).stdout
 pub=next(x.split(':',1)[1].strip() for x in k.splitlines() if x.lower().startswith(('password','public')))
 route=next((x for x in c.get('routing',{}).get('rules',[]) if i.get('tag') in x.get('inboundTag',[])),{})
 v=out.get(route.get('outboundTag'),{}).get('settings',{}).get('vnext',[{}])[0]
 for cl in i.get('settings',{}).get('clients',[]):
  rows.append({'port':i['port'],'uuid':cl['id'],'sni':r['serverNames'][0],'sid':r['shortIds'][0],'pbk':pub,'xhttp':s.get('xhttpSettings',{}),'exit':v.get('address','')})
print(json.dumps(rows))'''


def remote_profiles(env):
    target = env.get('SSH_TUNNEL_NL', 'root@' + env['SERVER_IP'])
    result = run(['ssh', '-F', '/dev/null', '-o', 'BatchMode=yes',
                  '-o', 'ConnectTimeout=10', target, 'python3', '-'],
                 input=REMOTE, timeout=35)
    if result.returncode:
        raise RuntimeError('Не удалось прочитать текущую конфигурацию NL по SSH')
    return json.loads(result.stdout)


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
  - GEOIP,PRIVATE,DIRECT,no-resolve
  - DOMAIN-SUFFIX,ru,DIRECT
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
    if not XRAY.exists() or not MIHOMO.exists():
        raise RuntimeError('Нужны локальные Xray и Mihomo в ~/.local/bin')
    rows = remote_profiles(env)
    row = next((r for r in rows if r['exit'] == requested), None)
    if row is None:
        raise RuntimeError('На NL не найден XHTTP-маршрут к ' + requested)
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
