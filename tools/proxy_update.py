"""Обновление Xray на серверах с проверкой и откатом; вызывается командой `proxy update`."""
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(os.environ['KIT_ROOT'])
NL_BIN = '/usr/local/x-ui/bin/xray-linux-amd64'


def usa_script(version, target):
    return f'''set -e
OLD=$(xray version | head -1 | awk '{{print $2}}')
curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh -o /root/xray-install.sh
bash /root/xray-install.sh install --version v{target} >/dev/null
rm -f /root/xray-install.sh
systemctl restart xray
sleep 2
systemctl is-active --quiet xray
echo "RESULT old=$OLD new=$(xray version | head -1 | awk '{{print $2}}')"
'''


def nl_script(version, target):
    return f'''set -e
OLD=$({NL_BIN} version | head -1 | awk '{{print $2}}')
cp -p {NL_BIN} {NL_BIN}.bak-proxy
command -v unzip >/dev/null || apt-get install -y unzip >/dev/null
TMP=$(mktemp -d)
curl -fsSL https://github.com/XTLS/Xray-core/releases/download/v{target}/Xray-linux-64.zip -o $TMP/x.zip
unzip -q $TMP/x.zip xray -d $TMP
install -m 755 $TMP/xray {NL_BIN}
rm -rf $TMP
systemctl restart x-ui
sleep 3
systemctl is-active --quiet x-ui
echo "RESULT old=$OLD new=$({NL_BIN} version | head -1 | awk '{{print $2}}')"
'''


def rollback_script(node, old):
    if node == 'nl':
        return f'cp -p {NL_BIN}.bak-proxy {NL_BIN} && systemctl restart x-ui && echo ROLLED_BACK'
    return (f'bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" '
            f'@ install --version v{old} >/dev/null && systemctl restart xray && echo ROLLED_BACK')


def parse(out):
    match = re.search(r'RESULT old=(\S*) new=(\S*)', out)
    return match.groups() if match else None


def update(args, run_remote, selected):
    if not re.fullmatch(r'\d+\.\d+\.\d+', args.version):
        raise RuntimeError('Версия должна быть в виде 26.10.10')
    nodes = selected(args.servers)
    print(f'Обновление Xray до {args.version}: серверы {", ".join(nodes)}.')
    print('Порядок: по одному; после каждого — проверка docker compose exec -T kit kit check, при провале откат узла и остановка.')
    if not args.yes and input('Продолжить? Введи yes: ').strip().lower() != 'yes':
        print('Отменено; ничего не изменено.')
        return 1
    for node in nodes:
        script = nl_script if node == 'nl' else usa_script
        code, out, err = run_remote(node, script(args.version, args.version), timeout=900)
        result = parse(out)
        if code != 0 or result is None:
            print(f'{node}: обновление не завершилось (код {code}); откат.')
            if result and result[0]:
                run_remote(node, rollback_script(node, result[0]), timeout=900)
            return 2
        old, new = result
        print(f'{node}: {old} -> {new}')
        if new != args.version:
            print(f'{node}: версия не совпала с {args.version}; откат на {old}.')
            run_remote(node, rollback_script(node, old), timeout=900)
            return 2
        if subprocess.run(['docker', 'compose', 'exec', '-T', 'kit', 'kit', 'check'], cwd=str(ROOT)).returncode != 0:
            print(f'{node}: проверка XHTTP не прошла; откат на {old}.')
            run_remote(node, rollback_script(node, old), timeout=900)
            return 2
    print('Готово: все выбранные серверы обновлены и проверены.')
    return 0
