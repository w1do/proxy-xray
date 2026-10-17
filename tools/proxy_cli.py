"""Единая команда `proxy`: статус, логи, проверка и обновление Xray на всех серверах."""
import argparse
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(os.environ['KIT_ROOT'])
SSH = ['ssh', '-F', '/dev/null', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=12',
       '-o', 'StrictHostKeyChecking=yes']
NODES = ['nl', 'usa1', 'usa2']
XRAY_BIN = {'nl': '/usr/local/x-ui/bin/xray-linux-amd64', 'usa1': 'xray', 'usa2': 'xray'}


def read_env(path):
    values = {}
    for line in path.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('\"\'')
    return values


def targets():
    env = read_env(ROOT / 'proxy.env')
    nl = env.get('SSH_TUNNEL_NL', 'root@' + env['SERVER_IP'])
    if not re.fullmatch(r'root@[A-Za-z0-9][A-Za-z0-9.:-]*', nl):
        raise RuntimeError('Некорректный SSH_TUNNEL_NL в proxy.env')
    usa = {'usa1': env.get('SSH_TUNNEL_SERVER', ''), 'usa2': env.get('SSH_TUNNEL_SERVER_2', '')}
    return {'nl': nl}, usa


def run_remote(node, script, timeout=120):
    """Выполнить python3-скрипт на узле; USA идут через NL (ProxyJump)."""
    nl, usa = targets()
    host = nl['nl'] if node == 'nl' else usa[node]
    if not host:
        raise RuntimeError(f'Для {node} нет адреса в proxy.env')
    jump = ['-J', nl['nl']] if node != 'nl' else []
    result = subprocess.run([*SSH, *jump, host, 'bash -s'], input=script, capture_output=True,
                            text=True, timeout=timeout)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def selected(names):
    if not names or names == ['all']:
        return NODES
    bad = [n for n in names if n not in NODES]
    if bad:
        raise RuntimeError('Неизвестный сервер: ' + ', '.join(bad) + '. Доступно: nl, usa1, usa2, all')
    return names


def status(_args):
    for node in NODES:
        script = (f"echo ACTIVE=$(systemctl is-active {'x-ui' if node == 'nl' else 'xray'} 2>/dev/null)\n"
                  f"echo VERSION=$({XRAY_BIN[node]} version 2>/dev/null | head -1)")
        try:
            code, out, _ = run_remote(node, script, timeout=60)
        except (RuntimeError, subprocess.SubprocessError) as exc:
            print(f'{node:5} ошибка: {exc}')
            continue
        fields = dict(l.split('=', 1) for l in out.splitlines() if '=' in l)
        print(f"{node:5} служба={fields.get('ACTIVE', '?'):8} {fields.get('VERSION', 'нет данных')}")
    return 0


def logs(args):
    lines = str(args.lines)
    for node in selected(args.servers):
        unit = 'x-ui' if node == 'nl' else 'xray'
        try:
            code, out, err = run_remote(node, f'journalctl -u {unit} -n {lines} --no-pager 2>&1', timeout=60)
        except (RuntimeError, subprocess.SubprocessError) as exc:
            print(f'===== {node}: ошибка: {exc}')
            continue
        print(f'===== {node} ({unit}, последние {lines} строк)')
        print(out if code == 0 else f'не удалось прочитать журнал (код {code})')
    return 0


def check(_args):
    return subprocess.run(['docker', 'compose', 'exec', '-T', 'kit', 'kit', 'check'], cwd=str(ROOT)).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(prog='proxy', description='Управление прокси NL → USA')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status', help='версия Xray и состояние служб на всех серверах').set_defaults(func=status)
    p_logs = sub.add_parser('logs', help='журналы серверов')
    p_logs.add_argument('servers', nargs='*', default=['all'], help='nl usa1 usa2 или all')
    p_logs.add_argument('-n', '--lines', type=int, default=50)
    p_logs.set_defaults(func=logs)
    sub.add_parser('check', help='проверить входы NL из контейнера (kit check)').set_defaults(func=check)
    p_update = sub.add_parser('update', help='обновить Xray на серверах до указанной версии')
    p_update.add_argument('version', help='например 26.10.10')
    p_update.add_argument('servers', nargs='*', default=['all'], help='nl usa1 usa2 или all')
    p_update.add_argument('--yes', action='store_true', help='не спрашивать подтверждение')
    args = parser.parse_args(argv)
    if args.command == 'update':
        from proxy_update import update
        return update(args, run_remote, selected)
    return args.func(args)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print('Ошибка: ' + str(exc))
        raise SystemExit(2)
