#!/usr/bin/env bash
# Route AI coding CLIs (Claude Code, Codex) through the local Mihomo proxy.
#
# Terminal sessions inherit the proxy from ~/.bashrc / ~/.zshrc, but tools that
# are started outside a shell (IDE extensions, background daemons) do not. This
# script pins the proxy in their own settings so the NL -> USA chain is used
# regardless of how they are launched. It is idempotent.
#
# Usage: bash ./setup-ai-cli-proxy.sh
# Set AI_CLI_PROXY=0 to leave the CLI configs untouched (install.sh passes it through).
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

PROXY_PORT="${PROXY_PORT:-7890}"
PROXY_URL="http://127.0.0.1:${PROXY_PORT}"
NO_PROXY_VALUE="localhost,127.0.0.1,::1"

if [ "${AI_CLI_PROXY:-1}" = "0" ]; then
  echo "AI_CLI_PROXY=0: AI CLI proxy setup skipped."
  exit 0
fi

# Claude Code applies the "env" block of ~/.claude/settings.json to every
# session (that is also how ANTHROPIC_BASE_URL is set), including sessions
# started from an IDE, so the proxy belongs there rather than only in the shell.
CLAUDE_SETTINGS="$HOME/.claude/settings.json"
if [ -f "$CLAUDE_SETTINGS" ] || command -v claude >/dev/null 2>&1; then
  if command -v python3 >/dev/null 2>&1; then
    mkdir -p "$(dirname "$CLAUDE_SETTINGS")"
    python3 - "$CLAUDE_SETTINGS" "$PROXY_URL" "$NO_PROXY_VALUE" <<'PY'
import json
import os
import sys

path, proxy_url, no_proxy = sys.argv[1], sys.argv[2], sys.argv[3]
data = {}
if os.path.exists(path):
    with open(path, encoding="utf-8") as handle:
        try:
            data = json.load(handle)
        except ValueError:
            sys.stderr.write("error: %s is not valid JSON, leaving it untouched\n" % path)
            sys.exit(1)

wanted = {
    "HTTP_PROXY": proxy_url,
    "HTTPS_PROXY": proxy_url,
    "http_proxy": proxy_url,
    "https_proxy": proxy_url,
}
# NO_PROXY is a policy choice: keep whatever is already configured (for example
# "http://127.0.0.1:1", which forces everything through the proxy) and only seed
# a sane default when the key is missing.
defaults = {"NO_PROXY": no_proxy, "no_proxy": no_proxy}
environment = data.setdefault("env", {})
changed = {key: value for key, value in wanted.items() if environment.get(key) != value}
changed.update({key: value for key, value in defaults.items() if key not in environment})
if changed:
    environment.update(changed)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print("Claude Code: %d proxy setting(s) written to %s" % (len(changed), path))
else:
    print("Claude Code: proxy settings already in place.")
PY
  else
    echo "Claude Code: python3 not found, set HTTPS_PROXY in ~/.claude/settings.json manually." >&2
  fi
fi

# The Codex CLI runs a long-lived app-server daemon (IDE extensions talk to it
# too). It inherits the proxy environment of whoever started it, so refresh it
# when it predates the proxy install or when it was started by a non-proxied
# parent. The environment of a running process is only readable on Linux
# (/proc), which is where WSL and the servers of this kit live.
CODEX_STATE_DIR="$HOME/.codex/app-server-daemon"
if [ "$(uname -s)" = "Linux" ] && [ -d "$CODEX_STATE_DIR" ] && command -v codex >/dev/null 2>&1; then
  daemon_pid() {
    sed -n 's/.*"pid":\([0-9]*\).*/\1/p' "$CODEX_STATE_DIR/daemon.pid" 2>/dev/null | head -n 1
  }
  daemon_uses_proxy() {
    [ -n "$1" ] && kill -0 "$1" 2>/dev/null \
      && tr '\0' '\n' < "/proc/$1/environ" 2>/dev/null | grep -qx "HTTPS_PROXY=$PROXY_URL"
  }

  OLD_PID="$(daemon_pid || true)"
  if daemon_uses_proxy "$OLD_PID"; then
    echo "Codex: app-server daemon already uses the proxy."
  else
    echo "Codex: refreshing the app-server daemon to pick up the proxy..."
    timeout 20 codex app-server daemon stop >/dev/null 2>&1 || true
    timeout 30 codex app-server daemon start >/dev/null 2>&1 || true
    if daemon_uses_proxy "$(daemon_pid || true)"; then
      echo "Codex: app-server daemon now uses the proxy."
    else
      echo "Codex: could not confirm the daemon proxy; run: codex app-server daemon restart" >&2
    fi
  fi
fi
