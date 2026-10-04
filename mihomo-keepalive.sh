#!/usr/bin/env bash
# Keep the local Mihomo proxy alive: start it when it is down and leave a
# healthy instance untouched. This is the fallback supervisor used when the
# systemd user manager is unavailable (see install.sh), and it also works as a
# manual "make sure the proxy is up" command. It is idempotent and serialised
# with flock so overlapping cron runs cannot start two processes.
#
# Usage: bash ./mihomo-keepalive.sh
# Overrides: MIHOMO_CONFIG_DIR, MIHOMO_BIN, PROXY_PORT, LOG_FILE.
set -euo pipefail

CONFIG_DIR="${MIHOMO_CONFIG_DIR:-$HOME/.config/mihomo}"
BIN="${MIHOMO_BIN:-$HOME/.local/bin/mihomo}"
PID_FILE="$CONFIG_DIR/mihomo.pid"
LOG_FILE="${LOG_FILE:-$CONFIG_DIR/mihomo.log}"
LOCK_FILE="$CONFIG_DIR/.keepalive.lock"

# The port comes from the config install.sh wrote, so callers do not have to
# pass it explicitly.
PROXY_PORT="${PROXY_PORT:-}"
if [ -z "$PROXY_PORT" ] && [ -f "$CONFIG_DIR/config.yaml" ]; then
  PROXY_PORT="$(sed -n 's/^mixed-port:[[:space:]]*//p' "$CONFIG_DIR/config.yaml" | tr -d ' ' | head -n 1)"
fi
PROXY_PORT="${PROXY_PORT:-7890}"

[ -x "$BIN" ] || { echo "mihomo-keepalive: binary not found: $BIN" >&2; exit 1; }
[ -d "$CONFIG_DIR" ] || { echo "mihomo-keepalive: config dir not found: $CONFIG_DIR" >&2; exit 1; }

port_is_listening() {
  if command -v ss >/dev/null 2>&1; then
    ss -H -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${PROXY_PORT}\$"
  elif command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"${PROXY_PORT}" -sTCP:LISTEN >/dev/null 2>&1
  else
    (exec 3<>"/dev/tcp/127.0.0.1/${PROXY_PORT}") 2>/dev/null
  fi
}

alive_pid() {
  [ -f "$PID_FILE" ] || return 1
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

log_line() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') mihomo-keepalive: $*"
}

# One keepalive at a time.
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  flock -n 9 || exit 0
fi

# Healthy: the port is served. Refresh the pid file when it is missing or stale.
if port_is_listening; then
  if ! alive_pid; then
    ADOPTED_PID="$(pgrep -x mihomo 2>/dev/null | head -n 1 || true)"
    if [ -n "$ADOPTED_PID" ]; then
      echo "$ADOPTED_PID" > "$PID_FILE"
    fi
  fi
  exit 0
fi

# The port is not served: drop any stale process, then start a fresh instance.
if [ -f "$PID_FILE" ]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$OLD_PID" ]; then
    kill "$OLD_PID" 2>/dev/null || true
  fi
fi
for RUNNING_PID in $(pgrep -x mihomo 2>/dev/null || true); do
  kill "$RUNNING_PID" 2>/dev/null || true
done
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if port_is_listening; then
    sleep 1
  else
    break
  fi
done

log_line "starting Mihomo on 127.0.0.1:${PROXY_PORT} (config: ${CONFIG_DIR})"
env -u http_proxy -u https_proxy -u all_proxy -u no_proxy \
  -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u NO_PROXY \
  -u WS_PROXY -u WSS_PROXY -u ws_proxy -u wss_proxy \
  nohup "$BIN" -d "$CONFIG_DIR" >> "$LOG_FILE" 2>&1 &
NEW_PID="$!"
echo "$NEW_PID" > "$PID_FILE"

for _ in 1 2 3 4 5 6 7 8 9 10; do
  if ! kill -0 "$NEW_PID" 2>/dev/null; then
    log_line "Mihomo exited immediately; see ${LOG_FILE}"
    exit 1
  fi
  if port_is_listening; then
    break
  fi
  sleep 1
done
if port_is_listening; then
  log_line "Mihomo is up (pid ${NEW_PID})."
else
  log_line "Mihomo started but ${PROXY_PORT} is not listening yet; see ${LOG_FILE}"
fi
