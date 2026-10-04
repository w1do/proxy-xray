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

## Install

```bash
git clone REPO_URL mihomo-proxy-kit
cd mihomo-proxy-kit
cp proxy.env.example proxy.env
# Edit proxy.env and fill in the credentials.
bash ./install.sh
```

After install, open a new terminal or run:

```bash
source ~/.bashrc 2>/dev/null || true
source ~/.zshrc 2>/dev/null || true
```

Check:

```bash
curl https://api.ipify.org
```

It should show the USA server IP.
