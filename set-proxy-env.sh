#!/usr/bin/env bash
# Usage: bash ./set-proxy-env.sh SERVER_IP=... SERVER_PORT=2083-2086|2087-2090 UUID=... PUBLIC_KEY=... SHORT_ID=... [KEY=VALUE ...]
# Writes proxy.env from KEY=VALUE arguments (mode 600). Then run: bash ./install.sh <USA_IP>
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="$SCRIPT_DIR/proxy.env"
REQUIRED="SERVER_IP SERVER_PORT UUID PUBLIC_KEY SHORT_ID"
ALLOWED="$REQUIRED SERVER_NETWORK XHTTP_PATH XHTTP_MODE GRPC_SERVICE_NAME REALITY_SERVER_NAME PROXY_PORT CLIENT_FINGERPRINT EXPECTED_EXIT_IP ADMIN_SSH_TUNNEL RU_SERVER_IP RU_UUID RU_PUBLIC_KEY RU_SHORT_ID RU_REALITY_SERVER_NAME CHAIN_MODE CHAIN_ALL XRAY_CHAIN"

if [ "$#" -eq 0 ]; then
  echo "Usage: bash ./set-proxy-env.sh SERVER_IP=... SERVER_PORT=2083-2086|2087-2090 UUID=... PUBLIC_KEY=... SHORT_ID=..."
  exit 2
fi

value_of() {
  local name="VALUE_$1"
  printf '%s' "${!name:-}"
}

for ARG in "$@"; do
  case "$ARG" in
    *=*) KEY="${ARG%%=*}"; VALUE="${ARG#*=}" ;;
    *) echo "Expected KEY=VALUE, got: ${ARG%%=*}" >&2; exit 2 ;;
  esac
  case " $ALLOWED " in
    *" $KEY "*) ;;
    *) echo "Unknown setting: $KEY" >&2; exit 2 ;;
  esac
  if ! [[ "$VALUE" =~ ^[A-Za-z0-9._:/-]+$ ]]; then
    echo "Invalid value for $KEY: allowed characters are letters, digits, . _ : / -" >&2
    exit 2
  fi
  printf -v "VALUE_$KEY" '%s' "$VALUE"
done

if [ -f "$ENV_FILE" ]; then
  while IFS= read -r LINE || [ -n "$LINE" ]; do
    case "$LINE" in
      ''|'#'*) continue ;;
    esac
    KEY="${LINE%%=*}"
    VALUE="${LINE#*=}"
    case " $ALLOWED " in
      *" $KEY "*) ;;
      *) continue ;;
    esac
    if [ -z "$(value_of "$KEY")" ] && [ -n "$VALUE" ]; then
      printf -v "VALUE_$KEY" '%s' "$VALUE"
    fi
  done < "$ENV_FILE"
fi

for KEY in $REQUIRED; do
  if [ -z "$(value_of "$KEY")" ]; then
    echo "Missing required setting: $KEY" >&2
    exit 2
  fi
done

if [ -f "$ENV_FILE" ]; then
  cp -p "$ENV_FILE" "$ENV_FILE.bak"
  echo "Previous proxy.env saved as proxy.env.bak"
fi

umask 077
{
  echo "# Keep this file private. Anyone with it can use the proxy."
  for KEY in $ALLOWED; do
    if [ -n "$(value_of "$KEY")" ]; then
      echo "$KEY=$(value_of "$KEY")"
    fi
  done
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo "Written: $ENV_FILE (mode 600)"
echo "Settings: $(for KEY in $ALLOWED; do [ -n "$(value_of "$KEY")" ] && printf '%s ' "$KEY"; done)"
