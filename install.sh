#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="$SCRIPT_DIR/proxy.env"
FALLBACK_ENV_FILE="$SCRIPT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
elif [ -f "$FALLBACK_ENV_FILE" ]; then
  # shellcheck disable=SC1090
  . "$FALLBACK_ENV_FILE"
fi

SERVER_IP="${SERVER_IP:-}"
UUID="${UUID:-}"
PUBLIC_KEY="${PUBLIC_KEY:-}"
SHORT_ID="${SHORT_ID:-}"
REALITY_SERVER_NAME="${REALITY_SERVER_NAME:-dl.google.com}"
PROXY_PORT="${PROXY_PORT:-7890}"
EXPECTED_EXIT_IP="${EXPECTED_EXIT_IP:-$SERVER_IP}"

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
NEW_BIN="$(mktemp "$BIN_DIR/.mihomo.XXXXXX")"
cleanup() {
  rm -f "$TMP_FILE" "$NEW_BIN"
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

gzip -dc "$TMP_FILE" > "$NEW_BIN"
chmod +x "$NEW_BIN"
# Replace by renaming a fully written file. Truncating BIN in place fails with
# ETXTBSY on Linux when the old Mihomo process is still executing that inode.
mv -f "$NEW_BIN" "$BIN"

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
    encryption: ""
    network: tcp
    tls: true
    skip-cert-verify: true
    udp: true
    flow: xtls-rprx-vision
    packet-encoding: xudp
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

rules:
  - DOMAIN-SUFFIX,openai.com,PROXY
  - DOMAIN-SUFFIX,chatgpt.com,PROXY
  - DOMAIN-SUFFIX,oaiusercontent.com,PROXY
  - DOMAIN-SUFFIX,oaistatic.com,PROXY
  - DOMAIN-SUFFIX,jetbrains.ai,PROXY
  - DOMAIN-SUFFIX,jetbrains.cloud,PROXY
  - DOMAIN-SUFFIX,jetbrains.com,PROXY
  - DOMAIN,api.app.prod.grazie.aws.intellij.net,PROXY
  - DOMAIN-SUFFIX,grazie.ai,PROXY
  - DOMAIN-SUFFIX,anthropic.com,PROXY
  - DOMAIN-SUFFIX,claude.ai,PROXY
  - DOMAIN-SUFFIX,claude.com,PROXY
  - DOMAIN-SUFFIX,claudeusercontent.com,PROXY
  - DOMAIN-SUFFIX,console.anthropic.com,PROXY
  - GEOIP,PRIVATE,DIRECT,no-resolve
  - MATCH,PROXY
EOF

if [ -f "$PID_FILE" ]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID" 2>/dev/null || true
    sleep 1
  fi
fi

env -u http_proxy -u https_proxy -u all_proxy -u no_proxy \
  -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u NO_PROXY \
  -u WS_PROXY -u WSS_PROXY -u ws_proxy -u wss_proxy \
  nohup "$BIN" -d "$CONFIG_DIR" > "$LOG_FILE" 2>&1 &
MIHOMO_PID="$!"
echo "$MIHOMO_PID" > "$PID_FILE"

sleep 1
if ! kill -0 "$MIHOMO_PID" 2>/dev/null; then
  echo "Mihomo failed to start. See: $LOG_FILE" >&2
  exit 4
fi

export http_proxy="http://127.0.0.1:${PROXY_PORT}"
export https_proxy="$http_proxy"
export all_proxy="socks5://127.0.0.1:${PROXY_PORT}"
export no_proxy="localhost,127.0.0.1,::1"
export HTTP_PROXY="$http_proxy"
export HTTPS_PROXY="$https_proxy"
export ALL_PROXY="$all_proxy"
export NO_PROXY="$no_proxy"
export WS_PROXY="$http_proxy"
export WSS_PROXY="$http_proxy"
export ws_proxy="$http_proxy"
export wss_proxy="$http_proxy"

MARKER_BEGIN="# mihomo local proxy begin"
MARKER_END="# mihomo local proxy end"
for RC in "$HOME/.bashrc" "$HOME/.zshrc"; do
  touch "$RC"
  TMP_RC="$(mktemp)"
  awk -v begin="$MARKER_BEGIN" -v end="$MARKER_END" '
    $0 == begin { skip = 1; next }
    $0 == end { skip = 0; next }
    $0 == "# mihomo local proxy" { legacy = 1; next }
    legacy && $0 == "" { legacy = 0; next }
    !skip && !legacy { print }
  ' "$RC" > "$TMP_RC"
  cat "$TMP_RC" > "$RC"
  rm -f "$TMP_RC"
  cat >> "$RC" <<EOF

# mihomo local proxy begin
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
# mihomo local proxy end
EOF
done

set +u
# shellcheck disable=SC1090
. "$HOME/.bashrc" 2>/dev/null || true
set -u

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

echo "Checking HTTPS through the USA proxy..."
EXIT_IP=""
for _ in 1 2 3 4 5 6; do
  EXIT_IP="$(curl --noproxy '' --connect-timeout 10 --max-time 20 -fsS \
    -x "http://127.0.0.1:${PROXY_PORT}" https://api.ipify.org 2>/dev/null)" && break
  EXIT_IP=""
  sleep 3
done
if [ -z "$EXIT_IP" ] && ! EXIT_IP="$(curl --noproxy '' --retry 1 --retry-connrefused --retry-delay 1 \
  --connect-timeout 10 --max-time 20 -fsS \
  -x "http://127.0.0.1:${PROXY_PORT}" https://api.ipify.org)"; then
  echo "Mihomo was started, but the HTTPS proxy check failed." >&2
  echo "Expected exit IP: $EXPECTED_EXIT_IP" >&2
  echo "Check the VLESS/Reality server and its settings. Log: $LOG_FILE" >&2
  echo "Last Mihomo log lines:" >&2
  tail -n 30 "$LOG_FILE" >&2 || true
  exit 5
fi

if [ "$EXIT_IP" != "$EXPECTED_EXIT_IP" ]; then
  echo "Mihomo proxy returned unexpected exit IP: $EXIT_IP" >&2
  echo "Expected exit IP: $EXPECTED_EXIT_IP" >&2
  echo "Log: $LOG_FILE" >&2
  echo "Last Mihomo log lines:" >&2
  tail -n 30 "$LOG_FILE" >&2 || true
  exit 6
fi

echo
echo "Mihomo is running on 127.0.0.1:${PROXY_PORT}"
echo "Config: $CONFIG_DIR/config.yaml"
echo "Log: $LOG_FILE"
echo
echo "Verified exit IP: $EXIT_IP"
echo
echo "Open a new terminal, or run:"
echo "source ~/.bashrc 2>/dev/null || true"
echo "source ~/.zshrc 2>/dev/null || true"
