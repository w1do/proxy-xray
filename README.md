# Mihomo USA Proxy Kit

Keep the repository private if it contains proxy credentials. Anyone with access
to `proxy.env` can use the proxy. The real `proxy.env` file is ignored by Git.

## Files

- `install.sh` - one-command installer for macOS and Linux/WSL.
- `proxy.env` - local USA proxy credentials and routing target (not committed).
- `proxy.env.example` - template for creating your local `proxy.env`.
- `bin/` - put the matching Mihomo `.gz` archives here to avoid downloading during install.

## Recommended archives

- Linux/WSL x64: `bin/mihomo-linux-amd64-compatible-v1.19.32.gz`
- macOS Apple Silicon: `bin/mihomo-darwin-arm64-v1.19.32.gz`
- macOS Intel: `bin/mihomo-darwin-amd64-compatible-v1.19.32.gz`

## Quick start (one command)

Prerequisites: `git`, `curl`, `bash` (macOS or Linux/WSL). Mihomo is bundled
for Linux x64; on other platforms it is downloaded from GitHub automatically.

You need the proxy credentials from your server: `SERVER_IP`, `UUID`,
`PUBLIC_KEY`, `SHORT_ID`.

```bash
git clone git@github.com:w1do/proxy-xray.git mihomo-proxy-kit && cd mihomo-proxy-kit && cp proxy.env.example proxy.env && nano proxy.env && bash ./install.sh
```

Or step by step:

```bash
git clone git@github.com:w1do/proxy-xray.git mihomo-proxy-kit
cd mihomo-proxy-kit
cp proxy.env.example proxy.env
nano proxy.env        # fill in SERVER_IP, UUID, PUBLIC_KEY, SHORT_ID
bash ./install.sh
```

The script installs Mihomo to `~/.local/bin`, writes `~/.config/mihomo/config.yaml`,
starts the proxy on `127.0.0.1:7890`, adds proxy variables to `~/.bashrc` and
`~/.zshrc`, enables the system proxy on macOS, and verifies that the exit IP
equals `SERVER_IP`. Success looks like `Verified exit IP: <SERVER_IP>`.

After install, open a new terminal or run:

```bash
source ~/.bashrc 2>/dev/null || true
```

Check:

```bash
curl https://api.ipify.org
```

It should show the USA server IP.

## Логи и проверка проксирования

Лог Mihomo: `~/.config/mihomo/mihomo.log`.

```bash
# открыть и следить в реальном времени (Ctrl+C - выход)
tail -f ~/.config/mihomo/mihomo.log

# последние 50 строк
tail -n 50 ~/.config/mihomo/mihomo.log
```

Каждое соединение пишется строкой вида
`[TCP] 127.0.0.1:48012 --> api.openai.com:443 match DomainSuffix(openai.com) using PROXY[USA]`.
Фрагмент `using PROXY[USA]` означает, что запрос ушёл через USA-сервер.
`DIRECT` - напрямую (только локальные адреса).

Посмотреть проксирование нужных сервисов (OpenAI/ChatGPT, Anthropic/Claude, JetBrains AI):

```bash
# в одном терминале - фильтр лога по сервисам
tail -f ~/.config/mihomo/mihomo.log | grep -Ei 'openai|chatgpt|anthropic|claude|jetbrains|grazie'

# в другом - сделать запрос
curl -sI https://api.openai.com >/dev/null
curl -sI https://claude.ai >/dev/null
```

В логе должны появиться строки с `using PROXY[USA]`. Ошибки подключения ищите так:
`grep -Ei 'error|timeout|fail' ~/.config/mihomo/mihomo.log`.

Проверить, что процесс жив: `kill -0 $(cat ~/.config/mihomo/mihomo.pid) && echo running`.
Список сервисов, идущих через прокси, - блок `rules:` в `~/.config/mihomo/config.yaml`
(остальной трафик тоже идёт через `PROXY` по правилу `MATCH`).

## Settings (`proxy.env`)

- `SERVER_IP`, `UUID`, `PUBLIC_KEY`, `SHORT_ID` - required.
- `REALITY_SERVER_NAME` - default `dl.google.com`.
- `PROXY_PORT` - default `7890`.
- `EXPECTED_EXIT_IP` - default `SERVER_IP`.

## Troubleshooting

- Log: `~/.config/mihomo/mihomo.log`.
- Re-run `bash ./install.sh` any time; it restarts Mihomo with the current settings.
- Stop: `kill $(cat ~/.config/mihomo/mihomo.pid)`.
- Exit codes: 2 missing settings, 3 no Mihomo asset, 4 failed to start, 5 proxy check failed, 6 unexpected exit IP.
