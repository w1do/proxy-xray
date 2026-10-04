#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="$SCRIPT_DIR/proxy.env"
FALLBACK_ENV_FILE="$SCRIPT_DIR/.env"

# proxy.env is the only source of settings. Values inherited from the
# environment (a previous session, an IDE runner, a stale export) must not
# override it: a leftover RU_* adds a second, broken node and hijacks the
# routing, which surfaces as "Parse config error: proxy 1: invalid REALITY
# public key" and leaves the proxy down.
AMBIENT_OVERRIDES=""
for VAR in SERVER_IP UUID PUBLIC_KEY SHORT_ID REALITY_SERVER_NAME PROXY_PORT \
  CLIENT_FINGERPRINT EXPECTED_EXIT_IP RU_SERVER_IP RU_UUID RU_PUBLIC_KEY \
  RU_SHORT_ID RU_REALITY_SERVER_NAME CHAIN_MODE CHAIN_ALL; do
  if [ -n "${!VAR:-}" ]; then
    AMBIENT_OVERRIDES="$AMBIENT_OVERRIDES $VAR"
    unset "$VAR"
  fi
done
if [ -n "$AMBIENT_OVERRIDES" ]; then
  echo "Ignoring settings inherited from the environment:$AMBIENT_OVERRIDES"
  echo "Put them into proxy.env instead; it is the only source of settings."
fi

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
# chrome sends a large post-quantum ClientHello that gets dropped on some networks
CLIENT_FINGERPRINT="${CLIENT_FINGERPRINT:-firefox}"
RU_SERVER_IP="${RU_SERVER_IP:-}"
RU_UUID="${RU_UUID:-}"
RU_PUBLIC_KEY="${RU_PUBLIC_KEY:-}"
RU_SHORT_ID="${RU_SHORT_ID:-}"
RU_REALITY_SERVER_NAME="${RU_REALITY_SERVER_NAME:-dl.google.com}"
RU_BLOCK=""
CHAIN_MODE="${CHAIN_MODE:-0}"
PROXY_MEMBER="USA"
FINAL_TARGET="PROXY"
DEFAULT_EXIT_IP="$SERVER_IP"
if [ -n "$RU_SERVER_IP" ]; then
  if [ -z "$RU_UUID" ] || [ -z "$RU_PUBLIC_KEY" ] || [ -z "$RU_SHORT_ID" ]; then
    echo "RU_SERVER_IP is set: RU_UUID, RU_PUBLIC_KEY, RU_SHORT_ID are required."
    exit 2
  fi
  FINAL_TARGET="RU"
  # An "if" is required here: a standalone "test && cmd" list would abort the
  # script under set -e whenever CHAIN_MODE is not 1.
  if [ "$CHAIN_MODE" = "1" ]; then
    PROXY_MEMBER="RU-NODE"
  fi
  DEFAULT_EXIT_IP="$RU_SERVER_IP"
  RU_BLOCK="  - name: RU-NODE
    type: vless
    server: ${RU_SERVER_IP}
    port: 443
    uuid: ${RU_UUID}
    encryption: \"\"
    network: tcp
    tls: true
    skip-cert-verify: true
    udp: true
    flow: xtls-rprx-vision
    packet-encoding: xudp
    servername: ${RU_REALITY_SERVER_NAME}
    client-fingerprint: ${CLIENT_FINGERPRINT}
    reality-opts:
      public-key: ${RU_PUBLIC_KEY}
      short-id: ${RU_SHORT_ID}
"
fi
EXPECTED_EXIT_IP="${EXPECTED_EXIT_IP:-$DEFAULT_EXIT_IP}"

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
LOCK_DIR="$CONFIG_DIR/.install.lock"
KEEPALIVE="$BIN_DIR/mihomo-keepalive.sh"
SYSTEMD_UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SYSTEMD_UNIT="$SYSTEMD_UNIT_DIR/mihomo.service"
LAUNCH_AGENT="$HOME/Library/LaunchAgents/com.mihomo.proxy.plist"
CRON_BEGIN="# mihomo local proxy begin"
CRON_END="# mihomo local proxy end"

# Which supervisor keeps Mihomo running after a reboot and restarts it on a
# crash. A systemd user unit is preferred on Linux (event-driven restart, and it
# starts without a login via linger); cron is the fallback for Linux without a
# reachable user manager; macOS uses a LaunchAgent. "none" keeps the old
# start-once behaviour.
SUPERVISOR="none"
if [ "$OS" = "Darwin" ] && command -v launchctl >/dev/null 2>&1; then
  SUPERVISOR="launchd"
elif [ "$OS" = "Linux" ]; then
  if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
    SUPERVISOR="systemd"
  elif command -v crontab >/dev/null 2>&1; then
    SUPERVISOR="cron"
  fi
fi

# Render the systemd user unit. Restart=always with a disabled start limit makes
# the service come back after any failure instead of ending in a failed state;
# UnsetEnvironment mirrors the "env -u" used by the nohup path so a leaked proxy
# variable in the user manager environment cannot make Mihomo connect to itself.
# The log stays at the path documented in README.md.
write_systemd_unit() {
  mkdir -p "$SYSTEMD_UNIT_DIR"
  cat > "$SYSTEMD_UNIT" <<EOF
[Unit]
Description=Mihomo local proxy (NL -> USA chain)
StartLimitIntervalSec=0

[Service]
Type=simple
ExecStart=${BIN} -d ${CONFIG_DIR}
Restart=always
RestartSec=3
UnsetEnvironment=http_proxy https_proxy all_proxy no_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY WS_PROXY WSS_PROXY ws_proxy wss_proxy
StandardOutput=append:${LOG_FILE}
StandardError=append:${LOG_FILE}

[Install]
WantedBy=default.target
EOF
}

# Render the macOS LaunchAgent. RunAtLoad starts it at login, KeepAlive restarts
# it after a crash.
write_launch_agent() {
  mkdir -p "$(dirname "$LAUNCH_AGENT")"
  cat > "$LAUNCH_AGENT" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.mihomo.proxy</string>
  <key>ProgramArguments</key>
  <array>
    <string>${BIN}</string>
    <string>-d</string>
    <string>${CONFIG_DIR}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG_FILE}</string>
  <key>StandardErrorPath</key>
  <string>${LOG_FILE}</string>
</dict>
</plist>
EOF
}

# Strip our marked block from the user crontab, preserving unrelated entries.
cron_without_block() {
  (crontab -l 2>/dev/null || true) | awk -v begin="$CRON_BEGIN" -v end="$CRON_END" '
    $0 == begin { skip = 1; next }
    $0 == end { skip = 0; next }
    !skip { print }
  '
}

install_cron_watchdog() {
  local tmp
  tmp="$(mktemp)"
  cron_without_block > "$tmp"
  cat >> "$tmp" <<EOF
$CRON_BEGIN
@reboot bash ${KEEPALIVE} >> ${LOG_FILE} 2>&1
* * * * * bash ${KEEPALIVE} >> ${LOG_FILE} 2>&1
$CRON_END
EOF
  crontab "$tmp" 2>/dev/null || echo "Warning: could not install the cron watchdog." >&2
  rm -f "$tmp"
}

remove_cron_watchdog() {
  local tmp
  # Nothing to remove: do not create an empty crontab for users who never had one.
  if ! (crontab -l 2>/dev/null || true) | grep -qF "$CRON_BEGIN"; then
    return 0
  fi
  tmp="$(mktemp)"
  cron_without_block > "$tmp"
  crontab "$tmp" 2>/dev/null || true
  rm -f "$tmp"
}

mkdir -p "$CONFIG_DIR" "$BIN_DIR"

TMP_FILE="$(mktemp)"
NEW_BIN="$(mktemp "$BIN_DIR/.mihomo.XXXXXX")"
TMP_CONFIG="$CONFIG_DIR/.config.yaml.new"
cleanup() {
  rm -f "$TMP_FILE" "$NEW_BIN" "$TMP_CONFIG"
  rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT

# An IDE plugin or an agent can start a second install.sh at the same moment.
# Without serialization the two runs kill each other's Mihomo and one of them
# reports a bogus "failed to start", so only one run may work at a time.
WAITED=0
while ! mkdir "$LOCK_DIR" 2>/dev/null; do
  # A lock left behind by a killed run is stale after five minutes.
  if [ -n "$(find "$LOCK_DIR" -maxdepth 0 -mmin +5 2>/dev/null || true)" ]; then
    rm -rf "$LOCK_DIR"
    continue
  fi
  if [ "$WAITED" -ge 60 ]; then
    echo "Another install.sh run is still in progress: $LOCK_DIR" >&2
    exit 7
  fi
  sleep 1
  WAITED=$((WAITED + 1))
done

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

cat > "$TMP_CONFIG" <<EOF
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
    client-fingerprint: ${CLIENT_FINGERPRINT}
    reality-opts:
      public-key: ${PUBLIC_KEY}
      short-id: ${SHORT_ID}
${RU_BLOCK}
proxy-groups:
  - name: PROXY
    type: select
    proxies:
      - ${PROXY_MEMBER}
$( [ -n "$RU_SERVER_IP" ] && printf '  - name: RU\n    type: select\n    proxies:\n      - RU-NODE\n' )

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
  - MATCH,${FINAL_TARGET}
EOF
# Publish the config atomically: a concurrent Mihomo start must never read a
# half-written file, which surfaces as a bogus "Parse config error".
mv -f "$TMP_CONFIG" "$CONFIG_DIR/config.yaml"

port_is_listening() {
  if command -v ss >/dev/null 2>&1; then
    ss -H -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${PROXY_PORT}\$"
  elif command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"${PROXY_PORT}" -sTCP:LISTEN >/dev/null 2>&1
  else
    (exec 3<>"/dev/tcp/127.0.0.1/${PROXY_PORT}") 2>/dev/null
  fi
}

# Register the supervisor that will own Mihomo from now on, so it survives a
# reboot and is restarted after a crash. The installer hands the process over to
# it below; the plain nohup path is only used when no supervisor is available.
if [ -f "$SCRIPT_DIR/mihomo-keepalive.sh" ]; then
  cp -f "$SCRIPT_DIR/mihomo-keepalive.sh" "$KEEPALIVE"
  chmod +x "$KEEPALIVE"
fi
if [ "$SUPERVISOR" = "cron" ] && [ ! -f "$KEEPALIVE" ]; then
  echo "Warning: mihomo-keepalive.sh is missing; the cron watchdog is skipped." >&2
  SUPERVISOR="none"
fi
case "$SUPERVISOR" in
  systemd)
    write_systemd_unit
    remove_cron_watchdog
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    systemctl --user enable mihomo.service >/dev/null 2>&1 || true
    # Without linger a user unit starts only at login; linger makes it start at
    # boot, which is the point on WSL and headless machines.
    loginctl enable-linger "$USER" >/dev/null 2>&1 || true
    ;;
  cron)
    install_cron_watchdog
    # A unit left by an earlier install would restart Mihomo on its own and fight
    # the watchdog for the port.
    if [ -f "$SYSTEMD_UNIT" ]; then
      systemctl --user disable --now mihomo.service >/dev/null 2>&1 || true
      rm -f "$SYSTEMD_UNIT"
      systemctl --user daemon-reload >/dev/null 2>&1 || true
    fi
    ;;
  launchd)
    write_launch_agent
    ;;
esac

# Stop the instance of the previous run. The pid file alone is not enough: a
# leftover instance (or one started outside install.sh) keeps the port busy and
# makes the new process exit with "address already in use".
if [ "$SUPERVISOR" = "systemd" ]; then
  systemctl --user stop mihomo.service >/dev/null 2>&1 || true
fi
if [ -f "$PID_FILE" ]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID" 2>/dev/null || true
  fi
fi
for RUNNING_PID in $(pgrep -x mihomo 2>/dev/null || true); do
  kill "$RUNNING_PID" 2>/dev/null || true
done

# Wait for the port to be released before starting the new instance.
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if port_is_listening; then
    sleep 1
  else
    break
  fi
done

# Start through the chosen supervisor so exactly one process owns the port.
MIHOMO_PID=""
case "$SUPERVISOR" in
  systemd)
    systemctl --user restart mihomo.service || true
    MIHOMO_PID="$(systemctl --user show -p MainPID --value mihomo.service 2>/dev/null || true)"
    ;;
  launchd)
    launchctl bootout "gui/$(id -u)" "$LAUNCH_AGENT" >/dev/null 2>&1 || true
    if ! launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENT" >/dev/null 2>&1; then
      launchctl unload "$LAUNCH_AGENT" >/dev/null 2>&1 || true
      launchctl load -w "$LAUNCH_AGENT" >/dev/null 2>&1 || true
    fi
    MIHOMO_PID="$(pgrep -x mihomo 2>/dev/null | head -n 1 || true)"
    ;;
  *)
    env -u http_proxy -u https_proxy -u all_proxy -u no_proxy \
      -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u NO_PROXY \
      -u WS_PROXY -u WSS_PROXY -u ws_proxy -u wss_proxy \
      nohup "$BIN" -d "$CONFIG_DIR" > "$LOG_FILE" 2>&1 &
    MIHOMO_PID="$!"
    ;;
esac
if [ -n "$MIHOMO_PID" ]; then
  echo "$MIHOMO_PID" > "$PID_FILE"
fi

# Readiness: the process must stay alive and actually take the port.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if [ -z "$MIHOMO_PID" ] && [ "$SUPERVISOR" = "systemd" ]; then
    MIHOMO_PID="$(systemctl --user show -p MainPID --value mihomo.service 2>/dev/null || true)"
  fi
  if [ -n "$MIHOMO_PID" ] && ! kill -0 "$MIHOMO_PID" 2>/dev/null; then
    break
  fi
  if port_is_listening; then
    break
  fi
  sleep 1
done
if [ -z "$MIHOMO_PID" ] || ! kill -0 "$MIHOMO_PID" 2>/dev/null; then
  # A concurrent launcher (IDE plugin, another shell) may have taken the port
  # with the same config while this run was starting its own instance. Adopt
  # that instance instead of reporting a failure that is not real.
  if port_is_listening; then
    ADOPTED_PID="$(pgrep -x mihomo 2>/dev/null | head -n 1 || true)"
    if [ -n "$ADOPTED_PID" ]; then
      MIHOMO_PID="$ADOPTED_PID"
      echo "$MIHOMO_PID" > "$PID_FILE"
      echo "Another Mihomo instance already serves 127.0.0.1:${PROXY_PORT}; using it."
    fi
  fi
fi
if [ -z "$MIHOMO_PID" ] || ! kill -0 "$MIHOMO_PID" 2>/dev/null; then
  echo "Mihomo failed to start. See: $LOG_FILE" >&2
  if [ "$SUPERVISOR" = "systemd" ]; then
    systemctl --user --no-pager status mihomo.service >&2 2>/dev/null || true
  fi
  echo "Last Mihomo log lines:" >&2
  tail -n 20 "$LOG_FILE" >&2 || true
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
echo
case "$SUPERVISOR" in
  systemd)
    echo "Always-on: systemd user service 'mihomo.service' is enabled with linger,"
    echo "so Mihomo starts at boot and restarts after a crash."
    ;;
  launchd)
    echo "Always-on: LaunchAgent 'com.mihomo.proxy' (RunAtLoad + KeepAlive),"
    echo "so Mihomo starts at login and restarts after a crash."
    ;;
  cron)
    echo "Always-on: crontab watchdog 'mihomo-keepalive.sh' runs at reboot and every minute."
    ;;
  *)
    echo "Always-on: not configured (no systemd user manager, crontab or launchctl)." >&2
    echo "Mihomo will NOT start or restart by itself; re-run install.sh after a reboot." >&2
    ;;
esac

if [ -f "$SCRIPT_DIR/setup-ai-cli-proxy.sh" ]; then
  echo
  echo "Routing AI CLIs (Claude Code, Codex) through the proxy..."
  AI_CLI_PROXY="${AI_CLI_PROXY:-1}" bash "$SCRIPT_DIR/setup-ai-cli-proxy.sh" || true
fi
