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
git clone REPO_URL mihomo-proxy-kit && cd mihomo-proxy-kit && cp proxy.env.example proxy.env && nano proxy.env && bash ./install.sh
```

Or step by step:

```bash
git clone REPO_URL mihomo-proxy-kit
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
