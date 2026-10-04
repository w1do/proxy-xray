#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
CONFIG="${1:-$HOME/.config/mihomo/config.yaml}"
ENV_FILE="$SCRIPT_DIR/proxy.env"

if [ ! -f "$CONFIG" ]; then
  echo "Config not found: $CONFIG"
  exit 2
fi

python3 - "$CONFIG" "$ENV_FILE" <<'PY'
import re
import shlex
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
env_path = Path(sys.argv[2])
config = config_path.read_text()

def find(pattern: str, name: str) -> str:
    match = re.search(pattern, config, re.MULTILINE)
    if not match:
        raise SystemExit(f"Could not find {name} in {config_path}")
    return match.group(1).strip().strip('"').strip("'")

values = {
    "SERVER_IP": find(r"(?m)^\s*server:\s*(.+)$", "server"),
    "UUID": find(r"(?m)^\s*uuid:\s*(.+)$", "uuid"),
    "PUBLIC_KEY": find(r"(?m)^\s*public-key:\s*(.+)$", "public-key"),
    "SHORT_ID": find(r"(?m)^\s*short-id:\s*(.+)$", "short-id"),
    "REALITY_SERVER_NAME": find(r"(?m)^\s*servername:\s*(.+)$", "servername"),
    "PROXY_PORT": "7890",
}

lines = [
    "# Keep this repository private.",
    "# Anyone with access to this file can use the proxy.",
    "",
]
for key, value in values.items():
    lines.append(f"{key}={shlex.quote(value)}")

env_path.write_text("\n".join(lines) + "\n")
print(f"Updated: {env_path}")
PY
