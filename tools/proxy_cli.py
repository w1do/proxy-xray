"""Команда `proxy`.

Клиент (Docker): `status`, `logs`, `check` работают только через `docker compose` в корне проекта.
Никакого ssh, systemctl или файлов на хосте.

Администрирование серверов: `server status`, `server logs`, `server update`. Они ходят по ssh на NL/USA
по адресам из proxy.env (только для администратора серверов, не для клиента).
"""
import argparse
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(os.environ['KIT_ROOT'])
SSH = ['ssh', '-F', '/dev/null', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=12',
       '-o', 'StrictHostKeyChecking=yes']
NODES = ['nl', 'usa1', 'usa2']
SERVICES = ['kit', 'proxy']


def run(argv):
    """Единственная точка запуска внешних команд: тесты подменяют эту функцию."""
    return subprocess.run(argv, cwd=str(ROOT)).returncode


def compose(*args):
    return run(['docker', 'compose', *args])


# ---- клиент: только Docker -------------------------------------------------------------------

def client_status(_args):
    code = compose('ps')
    return max(code, compose('exec', '-T', 'kit', 'kit', 'status'))


def client_logs(args):
    services = SERVICES if args.service == 'all' else [args.service]
    code = 0
    for service in services:
        code = max(code, compose('logs', '--tail', str(args.lines), service))
    return code


def client_check(_args):
    return compose('exec', '-T', 'kit', 'kit', 'check')


# ---- администрирование серверов: ssh по proxy.env --------------------------------------------

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
    """Выполнить bash-скрипт на узле; USA идут через NL (ProxyJump)."""
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


def server_status(_args):
    # Версия Xray на NL — бинарник 3x-ui; на USA — системный xray.
    xray_bin = {'nl': '/usr/local/x-ui/bin/xray-linux-amd64', 'usa1': 'xray', 'usa2': 'xray'}
    for node in NODES:
        script = (f"echo ACTIVE=$(systemctl is-active {'x-ui' if node == 'nl' else 'xray'} 2>/dev/null)\n"
                  f"echo VERSION=$({xray_bin[node]} version 2>/dev/null | head -1)")
        try:
            code, out, _ = run_remote(node, script, timeout=60)
        except (RuntimeError, subprocess.SubprocessError) as exc:
            print(f'{node:5} ошибка: {exc}')
            continue
        fields = dict(l.split('=', 1) for l in out.splitlines() if '=' in l)
        print(f"{node:5} служба={fields.get('ACTIVE', '?'):8} {fields.get('VERSION', 'нет данных')}")
    return 0


def server_logs(args):
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


def server_update(args):
    from proxy_update import update
    return update(args, run_remote, selected)


# ---- разбор аргументов -----------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(prog='proxy', description='Прокси-клиент в Docker и администрирование серверов')
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('status', help='состояние контейнеров kit и proxy и состояние клиента').set_defaults(func=client_status)

    p_logs = sub.add_parser('logs', help='журналы контейнеров')
    p_logs.add_argument('service', nargs='?', default='all', choices=SERVICES + ['all'],
                        help='kit, proxy или all (по умолчанию all)')
    p_logs.add_argument('-n', '--lines', type=int, default=50, help='сколько последних строк')
    p_logs.set_defaults(func=client_logs)

    sub.add_parser('check', help='проверить входы NL из контейнера (kit check)').set_defaults(func=client_check)

    p_server = sub.add_parser('server', help='администрирование серверов NL/USA по ssh (только для администратора)')
    srv = p_server.add_subparsers(dest='server_command', required=True)
    srv.add_parser('status', help='версия Xray и служба на серверах').set_defaults(func=server_status)
    p_slogs = srv.add_parser('logs', help='журналы служб на серверах')
    p_slogs.add_argument('servers', nargs='*', default=['all'], help='nl usa1 usa2 или all')
    p_slogs.add_argument('-n', '--lines', type=int, default=50)
    p_slogs.set_defaults(func=server_logs)
    p_update = srv.add_parser('update', help='обновить Xray на серверах до указанной версии')
    p_update.add_argument('version', help='например 26.10.10')
    p_update.add_argument('servers', nargs='*', default=['all'], help='nl usa1 usa2 или all')
    p_update.add_argument('--yes', action='store_true', help='не спрашивать подтверждение')
    p_update.set_defaults(func=server_update)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print('Ошибка: ' + str(exc))
        raise SystemExit(2)
