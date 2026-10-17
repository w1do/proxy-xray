"""Команда `proxy`.

Клиент (Docker): `status`, `logs`, `check` работают только через `docker compose` в корне проекта.
Никакого ssh, systemctl или файлов на хосте.

Администрирование серверов: `server status`, `server logs`, `server update`. Они ходят по ssh на NL/USA
по адресам из proxy.env (только для администратора серверов, не для клиента).
"""
import argparse
import os
import secrets
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


# ---- терминал: блок proxy в файле оболочки (только на хосте, без docker и ssh) ---------------

ENV_BEGIN = '# >>> mihomo-proxy-kit >>>'
ENV_END = '# <<< mihomo-proxy-kit <<<'
DEFAULT_PROXY_PORT = 7890


def env_block(port):
    return [
        ENV_BEGIN + '\n',
        f'export http_proxy=http://127.0.0.1:{port}\n',
        f'export https_proxy=http://127.0.0.1:{port}\n',
        f'export all_proxy=socks5://127.0.0.1:{port}\n',
        'export no_proxy=localhost,127.0.0.1,::1\n',
        ENV_END + '\n',
    ]


def rc_path(shell=None):
    """~/.zshrc for zsh, otherwise ~/.bashrc. `shell` overrides $SHELL."""
    name = shell or ('zsh' if os.environ.get('SHELL', '').endswith('zsh') else 'bash')
    if name not in ('bash', 'zsh'):
        raise RuntimeError('Оболочка должна быть bash или zsh')
    return Path.home() / ('.zshrc' if name == 'zsh' else '.bashrc')


def find_block(lines):
    """(start, end) indexes of the marked block, inclusive, or None."""
    starts = [i for i, line in enumerate(lines) if line.rstrip('\r\n') == ENV_BEGIN]
    if not starts:
        return None
    start = starts[0]
    for i in range(start + 1, len(lines)):
        if lines[i].rstrip('\r\n') == ENV_END:
            return start, i
    raise RuntimeError('В файле есть начало блока proxy без конца; исправьте файл вручную')


def read_lines(path):
    """Lines with their line endings kept (bytes are decoded, never newline-translated)."""
    if not path.exists():
        return []
    return path.read_bytes().decode('utf-8').splitlines(keepends=True)


def write_atomic(path, lines):
    """Write through a temp file in the same directory, keep the mode, then os.replace. Symlinks are refused."""
    if os.path.islink(path):
        raise RuntimeError(f'{path} — символическая ссылка; реальный файл: {os.path.realpath(path)}. Файл не изменён.')
    mode = path.stat().st_mode & 0o7777 if path.exists() else 0o644
    tmp = path.with_name(f'.{path.name}.tmp-{secrets.token_hex(4)}')
    tmp.write_bytes(''.join(lines).encode('utf-8'))
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def env_on(args):
    if not 1 <= args.port <= 65535:
        raise RuntimeError('Порт должен быть от 1 до 65535')
    path = rc_path(args.shell)
    if os.path.islink(path):
        raise RuntimeError(f'{path} — символическая ссылка; реальный файл: {os.path.realpath(path)}. Файл не изменён.')
    lines = read_lines(path)
    block = env_block(args.port)
    found = find_block(lines)
    if found:
        start, end = found
        new = lines[:start] + block + lines[end + 1:]
        action = 'Блок обновлён'
    else:
        if lines and not lines[-1].endswith('\n'):
            lines[-1] += '\n'
        new = lines + block
        action = 'Блок добавлен'
    write_atomic(path, new)
    print(f'{action}: {path} (порт {args.port}).')
    print(f'Чтобы применить в текущем окне: source {path}   (или откройте новое окно терминала)')
    return 0


def env_off(args):
    path = rc_path(args.shell)
    if os.path.islink(path):
        raise RuntimeError(f'{path} — символическая ссылка; реальный файл: {os.path.realpath(path)}. Файл не изменён.')
    lines = read_lines(path)
    found = find_block(lines)
    if not found:
        print(f'Блока proxy в {path} нет. Ничего не изменено.')
        return 0
    start, end = found
    write_atomic(path, lines[:start] + lines[end + 1:])
    print(f'Блок proxy удалён из {path}. Откройте новое окно терминала.')
    return 0


def env_status(args):
    path = rc_path(args.shell)
    present = find_block(read_lines(path)) is not None
    print(f'{path}: блок proxy {"есть" if present else "нет"}.')
    return 0


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

    p_env = sub.add_parser('env', help='прокси в терминале: блок в ~/.bashrc или ~/.zshrc (только на этом компьютере)')
    env_sub = p_env.add_subparsers(dest='env_command', required=True)
    for name, func, text in (('on', env_on, 'добавить или обновить блок proxy'),
                             ('off', env_off, 'удалить блок proxy'),
                             ('status', env_status, 'показать, есть ли блок')):
        p_action = env_sub.add_parser(name, help=text)
        p_action.add_argument('--shell', choices=['bash', 'zsh'], default=None,
                              help='файл оболочки (по умолчанию по $SHELL)')
        if name == 'on':
            p_action.add_argument('--port', type=int, default=DEFAULT_PROXY_PORT,
                                  help=f'порт прокси (по умолчанию {DEFAULT_PROXY_PORT})')
        p_action.set_defaults(func=func)

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
