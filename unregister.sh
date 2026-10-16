#!/usr/bin/env bash
# Remove only files and settings created by this repository's install.sh.
set -euo pipefail

CONFIG_DIR="$HOME/.config/mihomo"
BIN_DIR="$HOME/.local/bin"
BIN="$BIN_DIR/mihomo"
KEEPALIVE="$BIN_DIR/mihomo-keepalive.sh"
SYSTEMD_UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/mihomo.service"
LAUNCH_AGENT="$HOME/Library/LaunchAgents/com.mihomo.proxy.plist"
XRAY_BIN="$BIN_DIR/xray"
XRAY_MARKER="$BIN_DIR/.xray-mihomo-kit.sha256"
XRAY_AGENT="$HOME/Library/LaunchAgents/com.mihomo.xray.plist"
SYSTEMD_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
CRON_BEGIN="# mihomo local proxy begin"
CRON_END="# mihomo local proxy end"
MARKER_BEGIN="# mihomo local proxy begin"
MARKER_END="# mihomo local proxy end"

remove_marked_block() {
  local file tmp
  file="$1"
  [ -f "$file" ] || return 0
  tmp="$(mktemp)"
  awk -v begin="$MARKER_BEGIN" -v end="$MARKER_END" '
    $0 == begin { skip = 1; next }
    $0 == end { skip = 0; next }
    $0 == "# mihomo local proxy" { legacy = 1; next }
    legacy && $0 == "" { legacy = 0; next }
    !skip && !legacy { print }
  ' "$file" > "$tmp"
  cat "$tmp" > "$file"
  rm -f "$tmp"
}

remove_cron_block() {
  local current tmp
  command -v crontab >/dev/null 2>&1 || return 0
  current="$(crontab -l 2>/dev/null || true)"
  printf '%s\n' "$current" | grep -qFx "$CRON_BEGIN" || return 0
  tmp="$(mktemp)"
  printf '%s\n' "$current" | awk -v begin="$CRON_BEGIN" -v end="$CRON_END" '
    $0 == begin { skip = 1; next }
    $0 == end { skip = 0; next }
    !skip { print }
  ' > "$tmp"
  crontab "$tmp"
  rm -f "$tmp"
}

remove_claude_proxy_env() {
  local settings
  settings="$HOME/.claude/settings.json"
  [ -f "$settings" ] || return 0
  command -v python3 >/dev/null 2>&1 || {
    echo "Claude Code settings retained: python3 is required to edit JSON safely." >&2
    return 0
  }
  python3 - "$settings" <<'PY'
import json
import os
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    data = json.load(handle)
env = data.get("env")
if not isinstance(env, dict):
    raise SystemExit(0)
for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    value = env.get(key)
    if isinstance(value, str) and value.startswith("http://127.0.0.1:"):
        del env[key]
if not env:
    data.pop("env", None)
with open(path, "w", encoding="utf-8") as handle:
    json.dump(data, handle, indent=2, ensure_ascii=False)
    handle.write("\n")
PY
}

stop_systemd() {
  command -v systemctl >/dev/null 2>&1 || return 0
  systemctl --user disable --now mihomo.service >/dev/null 2>&1 || true
  rm -f "$SYSTEMD_UNIT"
  systemctl --user disable --now xray-mihomo.service >/dev/null 2>&1 || true
  rm -f "$SYSTEMD_DIR/xray-mihomo.service"
  systemctl --user disable --now xhttp-nl-admin-tunnel.service >/dev/null 2>&1 || true
  rm -f "$SYSTEMD_DIR/xhttp-nl-admin-tunnel.service"
  systemctl --user daemon-reload >/dev/null 2>&1 || true
}

stop_launchd() {
  command -v launchctl >/dev/null 2>&1 || return 0
  launchctl bootout "gui/$(id -u)" "$LAUNCH_AGENT" >/dev/null 2>&1 || true
  launchctl unload "$LAUNCH_AGENT" >/dev/null 2>&1 || true
  rm -f "$LAUNCH_AGENT"
  launchctl bootout "gui/$(id -u)" "$XRAY_AGENT" >/dev/null 2>&1 || true
  launchctl unload "$XRAY_AGENT" >/dev/null 2>&1 || true
  rm -f "$XRAY_AGENT"
}

stop_standalone_process() {
  local pid command
  [ -f "$CONFIG_DIR/mihomo.pid" ] || return 0
  pid="$(cat "$CONFIG_DIR/mihomo.pid" 2>/dev/null || true)"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 0
  kill -0 "$pid" 2>/dev/null || return 0
  command="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  if [[ "$command" == *"$BIN"* && "$command" == *"$CONFIG_DIR"* ]]; then
    kill "$pid" 2>/dev/null || true
  fi
}

stop_standalone_xray() {
  local pid command
  [ -f "$CONFIG_DIR/xray.pid" ] || return 0
  pid="$(cat "$CONFIG_DIR/xray.pid" 2>/dev/null || true)"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 0
  kill -0 "$pid" 2>/dev/null || return 0
  command="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  case "$command" in
    "$XRAY_BIN run"*) kill "$pid" 2>/dev/null || true ;;
  esac
}

# Removes ~/.local/bin/xray only when this kit installed it (marker holds its sha256).
# Without a marker: macOS keeps the file (not ours); Linux keeps the existing removal,
# because install-client.py installs xray without writing a marker.
remove_local_xray() {
  local recorded digest
  if [ ! -f "$XRAY_MARKER" ]; then
    if [ "$(uname -s)" = "Darwin" ]; then
      echo "Keeping $XRAY_BIN: no ownership marker, so this kit did not install it." >&2
      return 0
    fi
    rm -f "$XRAY_BIN"
    return 0
  fi
  recorded="$(cat "$XRAY_MARKER" 2>/dev/null || true)"
  digest=""
  if [ -f "$XRAY_BIN" ]; then
    if command -v shasum >/dev/null 2>&1; then
      digest="$(shasum -a 256 "$XRAY_BIN" 2>/dev/null | awk '{print $1}' || true)"
    elif command -v sha256sum >/dev/null 2>&1; then
      digest="$(sha256sum "$XRAY_BIN" 2>/dev/null | awk '{print $1}' || true)"
    fi
  fi
  if [ -n "$recorded" ] && [ "$recorded" = "$digest" ]; then
    rm -f "$XRAY_BIN" "$XRAY_MARKER"
  else
    echo "Keeping $XRAY_BIN: it does not match the ownership marker $XRAY_MARKER." >&2
  fi
}

stop_codex_daemon() {
  [ -d "$HOME/.codex/app-server-daemon" ] || return 0
  command -v codex >/dev/null 2>&1 || return 0
  timeout 20 codex app-server daemon stop >/dev/null 2>&1 || true
}

if [ "$(uname -s)" = "Darwin" ] && command -v networksetup >/dev/null 2>&1; then
  networksetup -listallnetworkservices | tail -n +2 | while IFS= read -r service; do
    case "$service" in ''|\**) continue ;; esac
    networksetup -setwebproxystate "$service" off >/dev/null 2>&1 || true
    networksetup -setsecurewebproxystate "$service" off >/dev/null 2>&1 || true
    networksetup -setsocksfirewallproxystate "$service" off >/dev/null 2>&1 || true
  done
fi

stop_systemd
stop_launchd
remove_cron_block
stop_standalone_process
stop_standalone_xray
stop_codex_daemon
remove_marked_block "$HOME/.bashrc"
remove_marked_block "$HOME/.zshrc"
remove_claude_proxy_env

rm -f "$BIN" "$KEEPALIVE"
remove_local_xray
rm -rf "$CONFIG_DIR"

unset http_proxy https_proxy all_proxy no_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY
unset WS_PROXY WSS_PROXY ws_proxy wss_proxy

echo "Mihomo and local Xray proxy removed: service, autostart, shell variables, Claude Code proxy env, binary and config."
echo "Open a new terminal, or run: exec \"${SHELL:-bash}\" -l"
