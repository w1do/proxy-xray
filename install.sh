#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="$SCRIPT_DIR/proxy.env"

if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi

SERVER_IP="${SERVER_IP:-}"
UUID="${UUID:-}"
PUBLIC_KEY="${PUBLIC_KEY:-}"
SHORT_ID="${SHORT_ID:-}"
REALITY_SERVER_NAME="${REALITY_SERVER_NAME:-dl.google.com}"
PROXY_PORT="${PROXY_PORT:-7890}"

if [ -z "$SERVER_IP" ] || [ -z "$UUID" ] || [ -z "$PUBLIC_KEY" ] || [ -z "$SHORT_ID" ]; then
  echo "Missing settings in proxy.env."
  echo "Required: SERVER_IP, UUID, PUBLIC_KEY, SHORT_ID"
  exit 2
fi

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS-$ARCH" in
  Darwin-arm64)
    ASSET_REGEX='mihomo-darwin-arm64.*\.gz$'
    ASSET_GLOBS=("mihomo-darwin-arm64-*.gz")
    ;;
  Darwin-x86_64)
    ASSET_REGEX='mihomo-darwin-amd64-compatible.*\.gz$'
    ASSET_GLOBS=("mihomo-darwin-amd64-compatible-*.gz")
    ;;
  Linux-x86_64)
    ASSET_REGEX='mihomo-linux-amd64-(compatible|v1).*\.gz$'
    ASSET_GLOBS=("mihomo-linux-amd64-compatible-*.gz" "mihomo-linux-amd64-v1-*.gz" "mihomo-linux-amd64-*.gz")
    ;;
  Linux-aarch64|Linux-arm64)
    ASSET_REGEX='mihomo-linux-arm64.*\.gz$'
    ASSET_GLOBS=("mihomo-linux-arm64-*.gz")
    ;;
  *)
    echo "Unsupported platform: $OS $ARCH"
    exit 2
    ;;
esac

CONFIG_DIR="$HOME/.config/mihomo"
BIN_DIR="$HOME/.local/bin"
BIN="$BIN_DIR/mihomo"
PID_FILE="$CONFIG_DIR/mihomo.pid"
LOG_FILE="$CONFIG_DIR/mihomo.log"

mkdir -p "$CONFIG_DIR" "$BIN_DIR"

TMP_FILE="$(mktemp)"
cleanup() {
  rm -f "$TMP_FILE"
}
trap cleanup EXIT

LOCAL_GZ=""
for ROOT in "$SCRIPT_DIR/bin" "$SCRIPT_DIR"; do
  for PATTERN in "${ASSET_GLOBS[@]}"; do
    for CANDIDATE in "$ROOT"/$PATTERN; do
      if [ -f "$CANDIDATE" ]; then
        LOCAL_GZ="$CANDIDATE"
        break 3
      fi
    done
  done
done

if [ -n "$LOCAL_GZ" ]; then
  echo "Using local Mihomo archive:"
  echo "$LOCAL_GZ"
  cp "$LOCAL_GZ" "$TMP_FILE"
else
  echo "No local Mihomo archive found. Trying GitHub download..."
  RELEASE_JSON="$(curl -fsSL \
    -A "mihomo-private-installer" \
    -H "Accept: application/vnd.github+json" \
    https://api.github.com/repos/MetaCubeX/mihomo/releases/latest)"

  URL="$(printf '%s\n' "$RELEASE_JSON" \
    | grep -Eo '"browser_download_url": *"[^"]+"' \
    | sed -E 's/^"browser_download_url": *"//; s/"$//' \
    | grep -E "/${ASSET_REGEX}" \
    | head -n 1)"

  if [ -z "$URL" ]; then
    echo "Could not find a matching Mihomo asset for: $OS $ARCH"
    echo "Put the matching .gz archive into: $SCRIPT_DIR/bin"
    exit 3
  fi

  echo "Downloading:"
  echo "$URL"
  curl -fL -A "mihomo-private-installer" "$URL" -o "$TMP_FILE"
fi

gzip -dc "$TMP_FILE" > "$BIN"
chmod +x "$BIN"

cat > "$CONFIG_DIR/config.yaml" <<EOF
mixed-port: ${PROXY_PORT}
allow-lan: false
mode: rule
log-level: info
ipv6: false

dns:
  enable: true
  enhanced-mode: fake-ip
  fake-ip-range: 198.18.0.1/16
  nameserver:
    - https://1.1.1.1/dns-query
    - https://8.8.8.8/dns-query

proxies:
  - name: USA
    type: vless
    server: ${SERVER_IP}
    port: 443
    uuid: ${UUID}
    encryption: none
    network: tcp
    tls: true
    udp: true
    flow: xtls-rprx-vision
    servername: ${REALITY_SERVER_NAME}
    client-fingerprint: chrome
    reality-opts:
      public-key: ${PUBLIC_KEY}
      short-id: ${SHORT_ID}

proxy-groups:
  - name: PROXY
    type: select
    proxies:
      - USA
      - DIRECT

rules:
  - DOMAIN-SUFFIX,openai.com,USA
  - DOMAIN-SUFFIX,chatgpt.com,USA
  - DOMAIN-SUFFIX,oaiusercontent.com,USA
  - DOMAIN-SUFFIX,oaistatic.com,USA
  - DOMAIN-SUFFIX,jetbrains.ai,USA
  - DOMAIN-SUFFIX,jetbrains.cloud,USA
  - DOMAIN-SUFFIX,jetbrains.com,USA
  - DOMAIN,api.app.prod.grazie.aws.intellij.net,USA
  - DOMAIN-SUFFIX,grazie.ai,USA
  - DOMAIN-SUFFIX,anthropic.com,USA
  - DOMAIN-SUFFIX,claude.ai,USA
  - DOMAIN-SUFFIX,claude.com,USA
  - DOMAIN-SUFFIX,claudeusercontent.com,USA
  - DOMAIN-SUFFIX,console.anthropic.com,USA
  - GEOIP,PRIVATE,DIRECT,no-resolve
  - MATCH,USA
EOF

if [ -f "$PID_FILE" ]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID" 2>/dev/null || true
    sleep 1
  fi
fi

nohup "$BIN" -d "$CONFIG_DIR" > "$LOG_FILE" 2>&1 &
echo "$!" > "$PID_FILE"

for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS --max-time 1 -x "http://127.0.0.1:${PROXY_PORT}" http://cp.cloudflare.com/generate_204 >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

MARKER="# mihomo local proxy"
for RC in "$HOME/.bashrc" "$HOME/.zshrc"; do
  touch "$RC"
  if ! grep -q "$MARKER" "$RC"; then
    cat >> "$RC" <<EOF

# mihomo local proxy
export http_proxy=http://127.0.0.1:${PROXY_PORT}
export https_proxy=http://127.0.0.1:${PROXY_PORT}
export all_proxy=socks5://127.0.0.1:${PROXY_PORT}
export no_proxy=localhost,127.0.0.1,::1
export HTTP_PROXY=\$http_proxy
export HTTPS_PROXY=\$https_proxy
export ALL_PROXY=\$all_proxy
export NO_PROXY=\$no_proxy
export WS_PROXY=http://127.0.0.1:${PROXY_PORT}
export WSS_PROXY=http://127.0.0.1:${PROXY_PORT}
export ws_proxy=http://127.0.0.1:${PROXY_PORT}
export wss_proxy=http://127.0.0.1:${PROXY_PORT}
EOF
  fi
done

if [ "$OS" = "Darwin" ] && command -v networksetup >/dev/null 2>&1; then
  echo "Enabling macOS system proxy on all network services..."
  networksetup -listallnetworkservices | tail -n +2 | while IFS= read -r SERVICE; do
    [ -z "$SERVICE" ] && continue
    case "$SERVICE" in
      \**) continue ;;
    esac
    networksetup -setwebproxy "$SERVICE" 127.0.0.1 "$PROXY_PORT" >/dev/null 2>&1 || true
    networksetup -setsecurewebproxy "$SERVICE" 127.0.0.1 "$PROXY_PORT" >/dev/null 2>&1 || true
    networksetup -setsocksfirewallproxy "$SERVICE" 127.0.0.1 "$PROXY_PORT" >/dev/null 2>&1 || true
    networksetup -setwebproxystate "$SERVICE" on >/dev/null 2>&1 || true
    networksetup -setsecurewebproxystate "$SERVICE" on >/dev/null 2>&1 || true
    networksetup -setsocksfirewallproxystate "$SERVICE" on >/dev/null 2>&1 || true
  done
fi

echo
echo "Mihomo is running on 127.0.0.1:${PROXY_PORT}"
echo "Config: $CONFIG_DIR/config.yaml"
echo "Log: $LOG_FILE"
echo
echo "Test:"
curl -x "http://127.0.0.1:${PROXY_PORT}" -fsS https://api.ipify.org || true
echo
echo "Open a new terminal, or run:"
echo "source ~/.bashrc 2>/dev/null || true"
echo "source ~/.zshrc 2>/dev/null || true"
