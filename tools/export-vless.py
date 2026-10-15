import json, os, subprocess, sys, tempfile, time
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
 if s.get('network')!='xhttp' or s.get('security')!='reality': continue
 r=s['realitySettings']; k=subprocess.run(['/usr/local/x-ui/bin/xray-linux-amd64','x25519','-i',r['privateKey']],capture_output=True,text=True,check=True).stdout
 pub=next(x.split(':',1)[1].strip() for x in k.splitlines() if x.lower().startswith(('password','public')))
 clients=i.get('settings',{}).get('clients',[])
 tag=i.get('tag')
 route=next((x for x in c.get('routing',{}).get('rules',[]) if tag in x.get('inboundTag',[])),{})
 o=out.get(route.get('outboundTag'),{}); v=o.get('settings',{}).get('vnext',[{}])[0]
 for cl in clients:
  rows.append({'port':i['port'],'uuid':cl['id'],'email':cl.get('email',''),'sni':r['serverNames'][0],'sid':r['shortIds'][0],'pbk':pub,'xhttp':s.get('xhttpSettings',{}),'exit':v.get('address','')})
print(json.dumps(rows))
'''

def ssh_rows():
    target=ENV.get('SSH_TUNNEL_NL','root@'+ENV['SERVER_IP'])
    r=subprocess.run(['ssh','-F','/dev/null','-o','BatchMode=yes','-o','ConnectTimeout=12',target,'python3','-'],input=REMOTE,text=True,capture_output=True,timeout=40)
    if r.returncode: raise RuntimeError('SSH к NL не выполнен; ссылки не изменены')
    return json.loads(r.stdout)

def make_link(row):
    p={'encryption':'none','security':'reality','sni':row['sni'],'fp':'chrome','pbk':row['pbk'],'sid':row['sid'],'type':'xhttp','path':row['xhttp'].get('path','/'),'mode':row['xhttp'].get('mode','auto')}
    if row['xhttp'].get('host'): p['host']=row['xhttp']['host']
    label=f"NL -> {row['exit']} XHTTP {row['email']}"
    return f"vless://{row['uuid']}@{ENV['SERVER_IP']}:{row['port']}?{urlencode(p,quote_via=quote)}#{quote(label)}"

def check(row):
    binary=Path('/home/dev/.local/bin/xray')
    if not binary.exists(): raise RuntimeError('Локальный Xray не найден')
    cfg={'log':{'loglevel':'warning'},'inbounds':[{'listen':'127.0.0.1','port':18083,'protocol':'socks','settings':{}}],'outbounds':[{'protocol':'vless','settings':{'vnext':[{'address':ENV['SERVER_IP'],'port':row['port'],'users':[{'id':row['uuid'],'encryption':'none'}]}]},'streamSettings':{'network':'xhttp','security':'reality','xhttpSettings':row['xhttp'],'realitySettings':{'serverName':row['sni'],'fingerprint':'chrome','password':row['pbk'],'shortId':row['sid']}}}]}
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
    rows=sorted(ssh_rows(),key=lambda x:x['port'])
    if not rows: raise RuntimeError('На NL нет XHTTP + REALITY входов')
    links=[make_link(x) for x in rows]
    path=ROOT/'servers'/'vless-links-xhttp.txt'
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.write_text('\n'.join(links)+'\n'); path.chmod(0o600)
    for row,link in zip(rows,links):
        print(f"NL:{row['port']} -> USA:{row['exit']} {link}")
    if '--check' in sys.argv:
        for row in rows:
            ok,seen=check(row); print(f"check {row['port']}: {'OK '+seen if ok else 'FAILED '+seen}")
            if not ok: return 1
    print(f'Saved: {path}')
    return 0

try: raise SystemExit(main())
except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as e:
    print('Ошибка: '+str(e),file=sys.stderr); raise SystemExit(2)
