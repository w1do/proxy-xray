import json, os, shlex, subprocess, sys, tempfile, time
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
ENV = {line.split('=', 1)[0]: line.split('=', 1)[1].strip().strip('"\'')
       for line in (ROOT / 'proxy.env').read_text().splitlines()
       if '=' in line and not line.lstrip().startswith('#')}
REMOTE = r'''
import json, subprocess
c=json.load(open('/usr/local/x-ui/bin/config.json'))
out={o.get('tag'):o for o in c.get('outbounds',[])}
rows=[]
for i in c['inbounds']:
 s=i.get('streamSettings',{})
 if s.get('network') not in ('xhttp','tcp','grpc') or s.get('security')!='reality': continue
 r=s['realitySettings']; k=subprocess.run(['/usr/local/x-ui/bin/xray-linux-amd64','x25519','-i',r['privateKey']],capture_output=True,text=True,check=True).stdout
 pub=next(x.split(':',1)[1].strip() for x in k.splitlines() if x.lower().startswith(('password','public')))
 clients=i.get('settings',{}).get('clients',[])
 tag=i.get('tag')
 route=next((x for x in c.get('routing',{}).get('rules',[]) if tag in x.get('inboundTag',[])),{})
 o=out.get(route.get('outboundTag'),{}); v=o.get('settings',{}).get('vnext',[{}])[0]
 for cl in clients:
  rows.append({'port':i['port'],'uuid':cl['id'],'email':cl.get('email',''),'sni':r['serverNames'][0],'sid':r['shortIds'][0],'pbk':pub,'network':s['network'],'flow':cl.get('flow') or '','grpc':s.get('grpcSettings',{}).get('serviceName',''),'multi':bool(s.get('grpcSettings',{}).get('multiMode')),'xhttp':s.get('xhttpSettings',{}),'exit':v.get('address','')})
print(json.dumps(rows))
'''

EXIT_PORTS={'108.61.222.91','149.28.240.154'}
SKIP_PORTS={443}
MODE_NAME={'xhttp':'XHTTP','tcp':'TCP','grpc':'gRPC'}

def ssh_rows():
    target=ENV.get('SSH_TUNNEL_NL','root@'+ENV['SERVER_IP'])
    r=subprocess.run(['ssh','-F','/dev/null','-o','BatchMode=yes','-o','ConnectTimeout=12',target,'python3','-'],input=REMOTE,text=True,capture_output=True,timeout=40)
    if r.returncode: raise RuntimeError('SSH к NL не выполнен; ссылки не изменены')
    return json.loads(r.stdout)

def make_link(row):
    net=row['network']
    p={'encryption':'none','security':'reality','sni':row['sni'],'fp':'chrome','pbk':row['pbk'],'sid':row['sid'],'type':net}
    if net=='xhttp':
        p.update({'path':row['xhttp'].get('path','/'),'mode':row['xhttp'].get('mode','auto')})
        if row['xhttp'].get('host'): p['host']=row['xhttp']['host']
    elif net=='tcp':
        p['headerType']='none'
        if row['flow']: p['flow']=row['flow']
    else:
        p.update({'serviceName':row['grpc'],'mode':'multi' if row['multi'] else 'gun'})
    label=f"NL -> {row['exit']} {MODE_NAME[net]} {row['email']}"
    return f"vless://{row['uuid']}@{ENV['SERVER_IP']}:{row['port']}?{urlencode(p,quote_via=quote)}#{quote(label)}"

def make_install_command(row, existing=False):
    settings = {
        'SERVER_IP': ENV['SERVER_IP'],
        'SERVER_PORT': row['port'],
        'UUID': row['uuid'],
        'PUBLIC_KEY': row['pbk'],
        'SHORT_ID': row['sid'],
        'REALITY_SERVER_NAME': row['sni'],
        'SERVER_NETWORK': row['network'],
    }
    if row['network'] == 'xhttp':
        settings['XHTTP_PATH'] = row['xhttp'].get('path', '/dl')
        settings['XHTTP_MODE'] = row['xhttp'].get('mode', 'auto')
    if row['network'] == 'grpc':
        settings['GRPC_SERVICE_NAME'] = row['grpc']
    if existing:
        settings['ADMIN_SSH_TUNNEL'] = '1'
    arguments = ' '.join(shlex.quote(f'{key}={value}') for key, value in settings.items())
    prefix = (f'cd {shlex.quote(str(ROOT))} && ' if existing else
              'git clone https://github.com/w1do/proxy-xray.git proxy && cd proxy && ')
    return (prefix + f'bash ./set-proxy-env.sh {arguments} && '
            f'bash ./install.sh {shlex.quote(str(row["exit"]))}')

def make_block(row, link):
    port, exit_ip, net = row['port'], row['exit'], row['network']
    mode = {'xhttp': 'XHTTP + REALITY', 'tcp': 'TCP + REALITY (xtls-rprx-vision)', 'grpc': 'gRPC + REALITY'}[net]
    return '\n'.join([
        f'# NL:{port} -> USA {exit_ip} | режим: {mode} | клиент: {row["email"] or "без имени"}',
        '# Установка, новый клиент (из домашнего каталога):',
        make_install_command(row),
        '# Установка, переключить эту WSL (только администратор, нужен SSH root к NL):',
        make_install_command(row, existing=True),
        '# Подключение:',
        f'# 1. Выполните строку «новый клиент». При успехе установщик выводит выходной IP {exit_ip}.',
        f'# 2. Проверка: curl -x http://127.0.0.1:7890 https://api.ipify.org должен вернуть {exit_ip}.',
        f'# 3. Приложение (v2rayN, Streisand, Hiddify и др.): импорт ссылки ниже; протокол VLESS, транспорт {MODE_NAME[net]}, безопасность REALITY, порт {port}.',
        f'# {link}',
    ])

def check(row):
    binary=Path('/home/dev/.local/bin/xray')
    if not binary.exists(): raise RuntimeError('Локальный Xray не найден')
    net=row['network']
    user={'id':row['uuid'],'encryption':'none'}
    if row['flow']: user['flow']=row['flow']
    stream={'network':net,'security':'reality','realitySettings':{'serverName':row['sni'],'fingerprint':'chrome','password':row['pbk'],'shortId':row['sid']}}
    if net=='xhttp': stream['xhttpSettings']=row['xhttp']
    if net=='grpc': stream['grpcSettings']={'serviceName':row['grpc']}
    cfg={'log':{'loglevel':'warning'},'inbounds':[{'listen':'127.0.0.1','port':18083,'protocol':'socks','settings':{}}],'outbounds':[{'protocol':'vless','settings':{'vnext':[{'address':ENV['SERVER_IP'],'port':row['port'],'users':[user]}]},'streamSettings':stream}]}
    with tempfile.TemporaryDirectory() as d:
        c=Path(d)/'config.json'; c.write_text(json.dumps(cfg)); log=open(Path(d)/'xray.log','w')
        p=subprocess.Popen([str(binary),'run','-c',str(c)],stdout=log,stderr=log)
        try:
            time.sleep(1)
            r=subprocess.run(['curl','--noproxy','','-fsS','--max-time','20','-x','socks5h://127.0.0.1:18083','https://api.ipify.org'],capture_output=True,text=True)
            return r.returncode==0 and r.stdout.strip()==row['exit'],r.stdout.strip()
        finally:
            p.terminate(); p.wait(timeout=5); log.close()

def main():
    found=sorted(ssh_rows(),key=lambda x:x['port'])
    rows=[x for x in found if x['exit'] in EXIT_PORTS and x['port'] not in SKIP_PORTS]
    for x in found:
        if x not in rows: print(f"Пропущен NL:{x['port']} ({x['network']}): выход {x['exit']}, не клиентский вход", file=sys.stderr)
    if not rows: raise RuntimeError('На NL нет входов REALITY для USA1/USA2')
    links=[make_link(x) for x in rows]
    path=ROOT/'servers'/'vless-links-xhttp.txt'
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.write_text('\n'.join(links)+'\n'); path.chmod(0o600)
    commands_path=ROOT/'servers'/'client-install-commands.txt'
    commands_path.write_text(
        '# Скопируйте ОДНУ нужную строку; не запускайте весь файл. Содержит доступ к VPN.\n\n' +
        '\n\n'.join(make_block(row, link) for row, link in zip(rows, links))+'\n')
    commands_path.chmod(0o600)
    for row,link in zip(rows,links):
        print(f"NL:{row['port']} -> USA:{row['exit']} {link}")
    if '--check' in sys.argv:
        for row in rows:
            ok,seen=check(row); print(f"check {row['port']}: {'OK '+seen if ok else 'FAILED '+seen}")
            if not ok: return 1
    print(f'Saved: {path}')
    print(f'Saved: {commands_path}')
    return 0

try: raise SystemExit(main())
except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as e:
    print('Ошибка: '+str(e),file=sys.stderr); raise SystemExit(2)
