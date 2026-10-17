"""Команда `proxy`.

Клиент (Docker): `status`, `logs`, `check` работают только через `docker compose` в корне проекта.
Никакого ssh, systemctl или файлов на хосте.

Администрирование серверов: `server status`, `server logs`, `server update`. Они ходят по ssh на NL/USA
по адресам из proxy.env (только для администратора серверов, не для клиента).
"""
import argparse
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

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

TOP_DESCRIPTION = """\
Команда proxy управляет прокси на вашем компьютере.

Прокси — это посредник: ваши программы выходят в интернет через выбранный
сервер. Панель в браузере и прокси работают в Docker. Поэтому клиентские
команды ничего не ставят в систему и работают только через Docker.

Команды:
  status        проверить, работает ли прокси
  logs          посмотреть журналы контейнеров
  check         проверить входы на сервере NL
  env           включить или выключить прокси в терминале
  server        администрирование серверов (только для владельца)

Примеры:
  proxy status                  проверить, всё ли работает
  proxy env on                  пустить терминал через прокси
  proxy logs kit -n 100         последние 100 строк журнала панели
  proxy check                   проверить входы NL

Подробная справка по любой команде: proxy <команда> --help
"""

STATUS_HELP = """\
Проверяет, работают ли контейнеры kit и proxy, и что говорит панель.

Когда использовать: если панель или прокси не отвечают, или чтобы
убедиться, что всё запущено после перезагрузки компьютера.

Пример:
  proxy status

Что означает вывод:
  kit running     панель запущена и открывается в браузере
  proxy running   прокси запущен и слушает порт 7890
  служба proxy    состояние прокси, которое сообщает панель:
    running       прокси работает с выбранным входом
    idle          прокси ждёт первой установки
    failed        прокси не смог применить настройки
    down          прокси не работает, обычно порт 7890 занят

Что делать, если плохо:
  kit не running      выполните proxy logs kit и проверьте ошибки
  proxy down          порт 7890 занят старой установкой, см. README,
                      раздел «Переход со старой установки»
  нет ответа          выполните docker compose up -d в папке проекта
"""

LOGS_HELP = """\
Показывает последние строки журналов контейнеров kit и proxy.

Когда использовать: если что-то сломалось и нужно найти причину. Журнал
kit — это работа панели. Журнал proxy — работа прокси (Xray и Mihomo).

Примеры:
  proxy logs                    журналы обоих контейнеров, по 50 строк
  proxy logs kit -n 100         последние 100 строк панели
  proxy logs proxy              последние строки прокси

Что означает вывод:
  Каждая строка — одно событие. Сообщения с словом error или ошибка
  показывают, что пошло не так. Строки «Откройте» и «Ссылка для входа»
  нужны только при первом запуске и содержат подсказку, как войти.

Что делать, если плохо:
  журнал пустой      контейнер ещё не запускался: docker compose up -d
  нет контейнера     проверьте папку проекта и docker compose ps
"""

CHECK_HELP = """\
Проверяет входы на сервере NL изнутри панели: каждый вход открывается
через временный Xray, и выходной IP сравнивается с ожидаемым.

Когда использовать: после установки или если прокси перестал
пропускать трафик. Нужны запущенные контейнеры.

Пример:
  proxy check

Что означает вывод:
  NL:2088 (tcp) -> <IP> : OK <IP>    вход работает, IP выхода совпал
  ... : ОШИБКА ...                   вход не работает, причина в конце строки
  Проверено: N, ошибок: M            итог: M должно быть 0

Что делать, если плохо:
  ОШИБКА Проверка не прошла    проверьте ключ и доступ к NL в панели
  Выход не совпал              вход ведёт не на тот сервер: проверьте вход
  Не заданы настройки NL       в панели укажите сервер NL
  нет контейнера kit           docker compose up -d в папке проекта
"""

ENV_HELP = """\
Прокси в терминале: добавляет или удаляет блок в файле оболочки.
Работает только на этом компьютере. Docker и ssh не используются.

Команды: on, off, status. Файл выбирается по вашей оболочке:
~/.zshrc для zsh, ~/.bashrc для остальных.

Пример:
  proxy env on
"""

ENV_ON_HELP = """\
Добавляет в файл оболочки блок с адресом прокси. Если блок уже есть,
он заменяется на месте, второй блок не добавляется.

Когда использовать: один раз, после установки, чтобы команды в
терминале (curl, git, pip) шли через прокси.

Примеры:
  proxy env on                  порт 7890 (по умолчанию)
  proxy env on --port 7891      другой порт
  proxy env on --shell zsh      записать в ~/.zshrc

После команды выполните source ~/.bashrc (или ~/.zshrc), либо откройте
новое окно терминала.

Что делать, если плохо:
  файл — символическая ссылка  команда не работает с ссылками, укажите
                               настоящий файл, путь напечатан в ошибке
  порт вне диапазона           порт от 1 до 65535
"""

ENV_OFF_HELP = """\
Удаляет блок прокси из файла оболочки. Строки вне блока не меняются.
Если блока нет, ничего не меняется.

Когда использовать: если прокси в терминале больше не нужен.

Пример:
  proxy env off

После команды откройте новое окно терминала.

Что делать, если плохо:
  блок не удаляется   проверьте, что файл не ссылка и что строки блока
                      не изменены вручную; строки блока начинаются с
                      «# >>> mihomo-proxy-kit >>>»
"""

ENV_STATUS_HELP = """\
Показывает, есть ли в файле оболочки блок прокси.

Когда использовать: чтобы проверить, включён ли прокси в терминале.

Пример:
  proxy env status

Что означает вывод:
  блок proxy есть    терминал будет пользоваться прокси в новых окнах
  блок proxy нет     прокси в терминале не включён: proxy env on
"""

SERVER_HELP = """\
Администрирование серверов NL, USA1 и USA2 по ssh. Адреса берутся из
файла proxy.env. Клиенту эти команды не нужны.

Команды: status, logs, update. Каждая работает по ssh с сервером.

Пример:
  proxy server status
"""

SERVER_STATUS_HELP = """\
Показывает версию Xray и состояние службы на каждом сервере.

Когда использовать: перед обновлением, или чтобы проверить сервер.

Пример:
  proxy server status

Что означает вывод:
  служба=active   служба работает
  служба=inactive служба остановлена: проверьте сервер вручную
  VERSION         версия Xray на сервере

Что делать, если плохо:
  ошибка соединения   проверьте proxy.env и доступ по ssh с этой машины
  нет данных          сервер не ответил: попробуйте позже
"""

SERVER_LOGS_HELP = """\
Показывает последние строки журнала службы на серверах.

Когда использовать: если сервер ведёт себя странно.

Примеры:
  proxy server logs                  журналы всех серверов
  proxy server logs usa1 -n 100      100 строк с USA1
  proxy server logs nl usa2          журналы NL и USA2

Что делать, если плохо:
  неизвестный сервер   допустимы nl, usa1, usa2, all
"""

SERVER_UPDATE_HELP = """\
Обновляет Xray на серверах до указанной версии, по одному серверу.
После каждого сервера выполняется проверка. Если проверка не прошла,
сервер откатывается, и обновление останавливается.

Когда использовать: только администратору, когда выходит новая версия Xray.
Эта команда ещё не запускалась на реальных серверах: сначала проверьте её
на одном USA.

Примеры:
  proxy server update 26.10.10 usa1      обновить только USA1
  proxy server update 26.10.10 --yes     обновить все без вопроса

Без --yes команда спрашивает подтверждение и просит ввести yes.

Что делать, если плохо:
  версия не совпала   сервер откатился; проверьте, что версия существует
  проверка не прошла  сервер откатился автоматически; смотрите журнал
"""


# Текст сообщений argparse по-русски. argparse берёт каждую строку через функцию `_`
# (внутри модуля). Здесь эта функция заменяется таблицей; нет перевода — остаётся английский оригинал.
RU_MESSAGES = {
    'usage: ': 'использование: ',
    'positional arguments': 'аргументы',
    'options': 'опции',
    'show this help message and exit': 'показать эту справку и выйти',
    'unrecognized arguments: %s': 'не распознаны аргументы: %s',
    'the following arguments are required: %s': 'не указаны обязательные аргументы: %s',
    'one of the arguments %s is required': 'нужен один из аргументов: %s',
    'invalid choice: %(value)r (choose from %(choices)s)':
        'неверный выбор: %(value)r (выберите из: %(choices)s)',
    'invalid %(type)s value: %(value)r': 'неверное значение (%(type)s): %(value)r',
    'expected one argument': 'нужен один аргумент',
    'expected at most one argument': 'нужно не больше одного аргумента',
    'expected at least one argument': 'нужен хотя бы один аргумент',
    'argument %(argument_name)s: %(message)s': 'аргумент %(argument_name)s: %(message)s',
    '%(prog)s: error: %(message)s\n': '%(prog)s: ошибка: %(message)s\n',
    'not allowed with argument %s': 'нельзя вместе с аргументом %s',
    'unexpected option string: %s': 'неизвестная опция: %s',
    'ambiguous option: %(option)s could match %(matches)s':
        'неоднозначная опция: %(option)s может быть: %(matches)s',
    ' (default: %(default)s)': ' (по умолчанию: %(default)s)',
}


def _ru(message):
    return RU_MESSAGES.get(message, message)


argparse._ = _ru

CONTACT_LINKS = [
    ('Сайт', 'https://w1do.ru'),
    ('Telegram', 'https://t.me/W1DO_DIGITAL'),
    ('YouTube', 'https://www.youtube.com/@w1do_digital'),
]


def links_enabled():
    """Clickable links only in a terminal that does not ask for plain output (NO_COLOR)."""
    return sys.stdout.isatty() and 'NO_COLOR' not in os.environ


def hyperlink(url, label):
    """OSC 8 hyperlink: the label is clickable in terminals that support it, plain text otherwise."""
    if not links_enabled():
        return label
    return f'\x1b]8;;{url}\x1b\\{label}\x1b]8;;\x1b\\'


def contacts():
    lines = ['Контакты автора:']
    for name, url in CONTACT_LINKS:
        lines.append(f'  {name}: {hyperlink(url, url)}')
    return '\n'.join(lines) + '\n'


def _help_flag(parser):
    parser.add_argument('-h', '--help', action='help', help='показать эту справку и выйти')
    parser._positionals.title = 'аргументы'
    parser._optionals.title = 'опции'
    return parser


def make_parser(epilog=None, **kwargs):
    kwargs.setdefault('formatter_class', argparse.RawDescriptionHelpFormatter)
    return _help_flag(argparse.ArgumentParser(add_help=False, epilog=epilog, **kwargs))


def sub_parser(container, name, **kwargs):
    kwargs.setdefault('formatter_class', argparse.RawDescriptionHelpFormatter)
    return _help_flag(container.add_parser(name, add_help=False, **kwargs))


def build_parser():
    parser = make_parser(prog='proxy', description=TOP_DESCRIPTION, epilog=contacts())
    sub = parser.add_subparsers(dest='command', required=True, metavar='команда')

    sub_parser(sub, 'status', help='проверить, работает ли прокси',
               description=STATUS_HELP).set_defaults(func=client_status)

    p_logs = sub_parser(sub, 'logs', help='посмотреть журналы контейнеров', description=LOGS_HELP)
    p_logs.add_argument('service', nargs='?', default='all', choices=SERVICES + ['all'],
                        help='kit (панель), proxy (прокси) или all (оба); по умолчанию all')
    p_logs.add_argument('-n', '--lines', type=int, default=50,
                        help='сколько последних строк показать; по умолчанию 50')
    p_logs.set_defaults(func=client_logs)

    sub_parser(sub, 'check', help='проверить входы на сервере NL',
               description=CHECK_HELP).set_defaults(func=client_check)

    p_env = sub_parser(sub, 'env', help='прокси в терминале: включить, выключить, проверить',
                       description=ENV_HELP)
    env_sub = p_env.add_subparsers(dest='env_command', required=True, metavar='действие')
    for name, func, text, body in (('on', env_on, 'включить прокси в терминале', ENV_ON_HELP),
                                   ('off', env_off, 'выключить прокси в терминале', ENV_OFF_HELP),
                                   ('status', env_status, 'проверить, включён ли прокси', ENV_STATUS_HELP)):
        p_action = sub_parser(env_sub, name, help=text, description=body)
        p_action.add_argument('--shell', choices=['bash', 'zsh'], default=None,
                              help='файл оболочки: bash (~/.bashrc) или zsh (~/.zshrc); '
                                   'по умолчанию определяется сама')
        if name == 'on':
            p_action.add_argument('--port', type=int, default=DEFAULT_PROXY_PORT,
                                  help=f'порт прокси; по умолчанию {DEFAULT_PROXY_PORT}')
        p_action.set_defaults(func=func)

    p_server = sub_parser(sub, 'server', help='администрирование серверов (только владелец)',
                          description=SERVER_HELP)
    srv = p_server.add_subparsers(dest='server_command', required=True, metavar='действие')
    sub_parser(srv, 'status', help='версия Xray и служба на серверах',
               description=SERVER_STATUS_HELP).set_defaults(func=server_status)
    p_slogs = sub_parser(srv, 'logs', help='журналы служб на серверах', description=SERVER_LOGS_HELP)
    p_slogs.add_argument('servers', nargs='*', default=['all'],
                         help='nl, usa1, usa2 или all; по умолчанию all')
    p_slogs.add_argument('-n', '--lines', type=int, default=50,
                         help='сколько последних строк; по умолчанию 50')
    p_slogs.set_defaults(func=server_logs)
    p_update = sub_parser(srv, 'update', help='обновить Xray на серверах', description=SERVER_UPDATE_HELP)
    p_update.add_argument('version', help='версия Xray, например 26.10.10')
    p_update.add_argument('servers', nargs='*', default=['all'],
                          help='nl, usa1, usa2 или all; по умолчанию all')
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
