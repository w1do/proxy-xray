"""In-container CLI `kit` (installed as /usr/local/bin/kit).

  kit token | rotate-token | status | discover | check [--port N]

It drops root before touching any file, then talks to the running server on 127.0.0.1:4050 with the
same Host/Origin/cookie rules as the browser, so it never bypasses the guard.
Exit codes: 0 ok, 1 failed job, 2 usage or connection error.
"""
import argparse, http.client, json, os, secrets, sys, time
from pathlib import Path

import kit_apply, kit_db, kit_priv

SERVER_PORT = 4050


def public_port():
    return int(os.environ.get('KIT_PUBLIC_PORT', '4050'))


def token_path():
    return kit_db.data_dir() / 'ui-token'


def current_token():
    from server import load_or_create_token
    return load_or_create_token(token_path())


def login_url(token):
    return f'http://127.0.0.1:{public_port()}/login?t={token}'


def _request(method, path, token, body=None):
    port = public_port()
    conn = http.client.HTTPConnection('127.0.0.1', SERVER_PORT, timeout=30)
    headers = {'Host': f'127.0.0.1:{port}', 'Cookie': f'kit_session={token}'}
    data = None
    if method != 'GET':
        headers.update({'Origin': f'http://127.0.0.1:{port}', 'Content-Type': 'application/json'})
        data = json.dumps(body if body is not None else {}).encode('utf-8')
    try:
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        payload = json.loads(resp.read().decode('utf-8') or '{}')
    except (OSError, ValueError) as exc:
        raise CliError(f'Сервер недоступен: {exc.__class__.__name__}')
    finally:
        conn.close()
    if resp.status >= 400:
        raise CliError(payload.get('error', f'HTTP {resp.status}'))
    return payload


class CliError(Exception):
    pass


def follow_job(token, job_id):
    offset = 0
    while True:
        info = _request('GET', f'/api/jobs/{job_id}?offset={offset}', token)
        for line in info['lines']:
            print(line, flush=True)
        offset = info['next_offset']
        if info['status'] != 'running':
            print(info['summary'], flush=True)
            return 0 if info['status'] == 'ok' else 1
        time.sleep(1)


def cmd_token(args):
    print(login_url(current_token()))
    return 0


def cmd_rotate(args):
    token = secrets.token_urlsafe(32)
    kit_apply.atomic_write(token_path(), token)
    print(login_url(token))
    return 0


def cmd_status(args):
    state = _request('GET', '/api/state', current_token())
    print(json.dumps({'proxy': state['proxy'], 'nl': state['nl'], 'nl_host_trusted': state['nl_host_trusted'],
                      'active': state['active']}, ensure_ascii=False, indent=2))
    return 0


def cmd_discover(args):
    token = current_token()
    job = _request('POST', '/api/discover', token)
    return follow_job(token, job['job_id'])


def cmd_check(args):
    token = current_token()
    if args.port is None:
        job = _request('POST', '/api/check-all', token)
        return follow_job(token, job['job_id'])
    state = _request('GET', '/api/state', token)
    ids = [row['id'] for exit_ in state['exits'] for row in exit_['inbounds'] if row['port'] == args.port]
    if not ids:
        raise CliError(f'Вход с портом {args.port} не найден')
    code = 0
    for inbound_id in ids:
        job = _request('POST', f'/api/inbounds/{inbound_id}/check', token)
        code = max(code, follow_job(token, job['job_id']))
    return code


def build_parser():
    parser = argparse.ArgumentParser(prog='kit', description='Управление локальным UI и прокси')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('token', help='показать ссылку входа').set_defaults(func=cmd_token)
    sub.add_parser('rotate-token', help='заменить токен входа').set_defaults(func=cmd_rotate)
    sub.add_parser('status', help='состояние прокси и NL').set_defaults(func=cmd_status)
    sub.add_parser('discover', help='обнаружить входы NL').set_defaults(func=cmd_discover)
    check = sub.add_parser('check', help='проверить входы (все или один порт)')
    check.add_argument('--port', type=int, default=None)
    check.set_defaults(func=cmd_check)
    return parser


def main(argv=None):
    kit_priv.prepare_and_drop()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except CliError as exc:
        print(f'Ошибка: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
