"""NL discovery over SSH, vless link building and a temporary Xray check.

Moved from the former host installer (openspec local-web-ui, section B). No module-level side effects.
"""
import json, subprocess, tempfile, time
from pathlib import Path
from urllib.parse import quote, urlencode

REMOTE_PARSE = r'''
def route_for(rules, tag, email):
 # Xray semantics: rules are evaluated in order and the first match wins. A rule matches a client when
 # it has no user list or the client's email is in it, AND it has no inboundTag list or the inbound tag is in it.
 # Rules without outboundTag (balancer rules) are skipped.
 for x in rules:
  if not x.get('outboundTag'): continue
  # Rules with any other condition (ip, domain, protocol, port, ...) match only some traffic, not the whole client.
  if set(x) - {'type','outboundTag','user','inboundTag','ruleTag'}: continue
  if x.get('user') and email not in x['user']: continue
  if x.get('inboundTag') and tag not in x['inboundTag']: continue
  return x
 return {}
def rows_from_config(c, derive_pub):
 out={o.get('tag'):o for o in c.get('outbounds',[])}
 rows=[]
 for i in c['inbounds']:
  s=i.get('streamSettings',{})
  if s.get('network') not in ('xhttp','tcp','grpc') or s.get('security')!='reality': continue
  r=s['realitySettings']; pub=derive_pub(r['privateKey'])
  clients=i.get('settings',{}).get('clients',[])
  tag=i.get('tag')
  rules=c.get('routing',{}).get('rules',[])
  for cl in clients:
   route=route_for(rules, tag, cl.get('email',''))
   o=out.get(route.get('outboundTag'),{}); v=o.get('settings',{}).get('vnext',[{}])[0]
   rows.append({'port':i['port'],'uuid':cl['id'],'email':cl.get('email',''),'sni':r['serverNames'][0],'sid':r['shortIds'][0],'pbk':pub,'network':s['network'],'flow':cl.get('flow') or '','grpc':s.get('grpcSettings',{}).get('serviceName',''),'multi':bool(s.get('grpcSettings',{}).get('multiMode')),'xhttp':s.get('xhttpSettings',{}),'exit':v.get('address',''),'exit_tag':route.get('outboundTag','')})
 return rows
'''
REMOTE_DRIVER = r'''
import json, subprocess, sys
CFG = sys.argv[1] if len(sys.argv) > 1 else '/usr/local/x-ui/bin/config.json'
XB = sys.argv[2] if len(sys.argv) > 2 else '/usr/local/x-ui/bin/xray' + '-linux-amd64'
def _pub(pk):
 k=subprocess.run([XB,'x25519','-i',pk],capture_output=True,text=True,check=True).stdout
 return next(x.split(':',1)[1].strip() for x in k.splitlines() if x.lower().startswith(('password','public')))
print(json.dumps(rows_from_config(json.load(open(CFG)), _pub)))
'''
REMOTE = REMOTE_PARSE + REMOTE_DRIVER

SKIP_PORTS = {443}
MODE_NAME = {'xhttp': 'XHTTP', 'tcp': 'TCP', 'grpc': 'gRPC'}


class DiscoveryError(RuntimeError):
    def __init__(self, returncode, stderr):
        super().__init__(f'ssh rc={returncode}')
        self.returncode = returncode
        self.stderr = stderr


def ssh_command(target, ssh_port=22, key_path=None, known_hosts=None):
    cmd = ['ssh', '-F', '/dev/null', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=12', '-o', 'StrictHostKeyChecking=yes',
           '-o', 'UpdateHostKeys=no', '-o', 'PasswordAuthentication=no', '-o', 'ForwardAgent=no']
    if ssh_port != 22:
        cmd += ['-p', str(ssh_port)]
    if key_path:
        cmd += ['-i', str(key_path), '-o', 'IdentitiesOnly=yes']
    if known_hosts:
        cmd += ['-o', f'UserKnownHostsFile={known_hosts}', '-o', 'GlobalKnownHostsFile=/dev/null']
    return cmd + ['--', target, 'python3', '-']


def discover_rows(target, ssh_port=22, key_path=None, known_hosts=None, timeout=40):
    r = subprocess.run(ssh_command(target, ssh_port, key_path, known_hosts), input=REMOTE, text=True,
                       capture_output=True, timeout=timeout)
    if r.returncode:
        raise DiscoveryError(r.returncode, r.stderr[-400:])
    return json.loads(r.stdout)


def make_link(row, server_ip):
    if not server_ip:
        raise ValueError('server_ip is required')
    net = row['network']
    p = {'encryption': 'none', 'security': 'reality', 'sni': row['sni'], 'fp': 'chrome', 'pbk': row['pbk'],
         'sid': row['sid'], 'type': net}
    if net == 'xhttp':
        p.update({'path': row['xhttp'].get('path', '/'), 'mode': row['xhttp'].get('mode', 'auto')})
        if row['xhttp'].get('host'):
            p['host'] = row['xhttp']['host']
    elif net == 'tcp':
        p['headerType'] = 'none'
        if row['flow']:
            p['flow'] = row['flow']
    else:
        p.update({'serviceName': row['grpc'], 'mode': 'multi' if row['multi'] else 'gun'})
    label = f"NL -> {row['exit']} {MODE_NAME[net]} {row['email']}"
    return f"vless://{row['uuid']}@{server_ip}:{row['port']}?{urlencode(p, quote_via=quote)}#{quote(label)}"


def check(row, server_ip, xray_bin, socks_port=18083):
    if not server_ip:
        raise ValueError('server_ip is required')
    if not xray_bin:
        raise ValueError('xray_bin is required')
    binary = Path(xray_bin)
    if not binary.exists():
        raise RuntimeError('Локальный Xray не найден')
    net = row['network']
    user = {'id': row['uuid'], 'encryption': 'none'}
    if row['flow']:
        user['flow'] = row['flow']
    stream = {'network': net, 'security': 'reality',
              'realitySettings': {'serverName': row['sni'], 'fingerprint': 'chrome', 'password': row['pbk'],
                                  'shortId': row['sid']}}
    if net == 'xhttp':
        stream['xhttpSettings'] = row['xhttp']
    if net == 'grpc':
        stream['grpcSettings'] = {'serviceName': row['grpc']}
    cfg = {'log': {'loglevel': 'warning'},
           'inbounds': [{'listen': '127.0.0.1', 'port': socks_port, 'protocol': 'socks', 'settings': {}}],
           'outbounds': [{'protocol': 'vless', 'settings': {'vnext': [{'address': server_ip, 'port': row['port'],
                                                                        'users': [user]}]},
                          'streamSettings': stream}]}
    with tempfile.TemporaryDirectory() as d:
        c = Path(d) / 'config.json'
        c.write_text(json.dumps(cfg))
        log = open(Path(d) / 'xray.log', 'w')
        p = subprocess.Popen([str(binary), 'run', '-c', str(c)], stdout=log, stderr=log)
        try:
            time.sleep(1)
            r = subprocess.run(['curl', '--noproxy', '', '-fsS', '--max-time', '20', '-x',
                                f'socks5h://127.0.0.1:{socks_port}', 'https://api.ipify.org'],
                               capture_output=True, text=True)
            return r.returncode == 0 and r.stdout.strip() == row['exit'], r.stdout.strip()
        finally:
            p.terminate()
            p.wait(timeout=5)
            log.close()
