#!/usr/bin/env python3
"""Render a Mihomo config.yaml for one NL entry (xhttp, tcp or grpc) from proxy.env values."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NETWORKS = ('xhttp', 'tcp', 'grpc')
REQUIRED = ('SERVER_IP', 'SERVER_PORT', 'UUID', 'PUBLIC_KEY', 'SHORT_ID')


def read_env(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('"\'')
    return values


def proxy_block(env):
    network = env.get('SERVER_NETWORK') or ('xhttp' if env.get('XHTTP_PATH') else 'tcp')
    if network not in NETWORKS:
        raise ValueError(f'SERVER_NETWORK must be one of {", ".join(NETWORKS)}, got {network}')
    missing = [key for key in REQUIRED if not env.get(key)]
    if missing:
        raise ValueError('Missing settings: ' + ', '.join(missing))
    lines = [
        '  - name: USA',
        '    type: vless',
        f'    server: {env["SERVER_IP"]}',
        f'    port: {env["SERVER_PORT"]}',
        f'    uuid: {env["UUID"]}',
        '    encryption: ""',
        f'    network: {network}',
        '    tls: true',
        '    skip-cert-verify: true',
        '    udp: true',
    ]
    if network == 'xhttp':
        lines += ['    xhttp-opts:',
                  f'      path: {env.get("XHTTP_PATH") or "/"}',
                  f'      mode: {env.get("XHTTP_MODE", "auto")}']
    elif network == 'tcp':
        lines += ['    flow: xtls-rprx-vision']
    else:
        service = env.get('GRPC_SERVICE_NAME')
        if not service:
            raise ValueError('SERVER_NETWORK=grpc requires GRPC_SERVICE_NAME')
        lines += ['    grpc-opts:', f'      grpc-service-name: {service}']
    lines += [
        '    packet-encoding: xudp',
        f'    servername: {env.get("REALITY_SERVER_NAME", "dl.google.com")}',
        f'    client-fingerprint: {env.get("CLIENT_FINGERPRINT", "firefox")}',
        '    reality-opts:',
        f'      public-key: {env["PUBLIC_KEY"]}',
        f'      short-id: {env["SHORT_ID"]}',
    ]
    return '\n'.join(lines)


def render(env):
    return f"""mixed-port: {env.get('PROXY_PORT', '7890')}
allow-lan: false
mode: rule
log-level: info
ipv6: false

dns:
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
    - https://8.8.8.8/dns-query

proxies:
{proxy_block(env)}

proxy-groups:
  - name: PROXY
    type: select
    proxies:
      - USA

rules:
  - DOMAIN-SUFFIX,openai.com,PROXY
  - DOMAIN-SUFFIX,chatgpt.com,PROXY
  - DOMAIN-SUFFIX,anthropic.com,PROXY
  - DOMAIN-SUFFIX,claude.ai,PROXY
  - DOMAIN-SUFFIX,telegram.org,PROXY
  - DOMAIN-SUFFIX,t.me,PROXY
  - GEOIP,PRIVATE,DIRECT,no-resolve
  - DOMAIN-SUFFIX,local,DIRECT
  - DOMAIN-SUFFIX,localhost,DIRECT
  - GEOSITE,category-ru,DIRECT
  - DOMAIN-SUFFIX,ru,DIRECT
  - GEOIP,RU,DIRECT
  - MATCH,PROXY
"""


def main(argv):
    if len(argv) != 2:
        print('usage: mihomo-config.py PROXY_ENV_FILE', file=sys.stderr)
        return 2
    sys.stdout.write(render(read_env(argv[1])))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
