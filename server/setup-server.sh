#!/usr/bin/env bash
# Usage: bash server/setup-server.sh user@NEW_SERVER_IP [ssh options...]
# Installs Xray (VLESS+Reality on :443) on a fresh server over SSH and prints proxy.env values.
# KEEP_CONFIG=1  -> upload server/xray-config.json instead of generating new keys.
set -euo pipefail

TARGET="${1:-}"
[ -n "$TARGET" ] || { echo "Usage: $0 user@host [ssh options]"; exit 2; }
shift || true
DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SNI="${REALITY_SERVER_NAME:-dl.google.com}"
SSH=(ssh -o StrictHostKeyChecking=accept-new "$@" "$TARGET")

if [ "${KEEP_CONFIG:-0}" = "1" ]; then
  [ -f "$DIR/xray-config.json" ] || { echo "No $DIR/xray-config.json"; exit 2; }
  "${SSH[@]}" 'cat > /tmp/xray-config.json' < "$DIR/xray-config.json"
fi

"${SSH[@]}" "KEEP_CONFIG=${KEEP_CONFIG:-0} SNI=$SNI bash -s" <<'REMOTE'
set -euo pipefail
SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo"
export DEBIAN_FRONTEND=noninteractive
if command -v apt-get >/dev/null; then $SUDO apt-get update -qq && $SUDO apt-get install -y -qq curl openssl ca-certificates unzip >/dev/null
elif command -v dnf >/dev/null; then $SUDO dnf install -y -q curl openssl ca-certificates unzip
elif command -v yum >/dev/null; then $SUDO yum install -y -q curl openssl ca-certificates unzip
fi
curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh -o /tmp/xray-install.sh
$SUDO bash /tmp/xray-install.sh install >/dev/null
CFG=/usr/local/etc/xray/config.json
if [ "$KEEP_CONFIG" = "1" ]; then
  $SUDO install -m 644 /tmp/xray-config.json "$CFG"; rm -f /tmp/xray-config.json
else
  UUID="$(xray uuid)"
  KEYS="$(xray x25519)"
  PRIV="$(echo "$KEYS" | awk -F': *' 'tolower($1) ~ /private/ {print $2}')"
  PUB="$(echo "$KEYS" | awk -F': *' 'tolower($1) ~ /(^public|password)/ {print $2}')"
  SID="$(openssl rand -hex 8)"
  $SUDO tee "$CFG" >/dev/null <<EOF
{
  "log": {"loglevel": "warning"},
  "inbounds": [{
    "port": 443, "protocol": "vless",
    "settings": {"clients": [{"id": "$UUID", "flow": "xtls-rprx-vision"}], "decryption": "none"},
    "streamSettings": {
      "network": "tcp", "security": "reality",
      "realitySettings": {
        "show": false, "dest": "$SNI:443", "xver": 0,
        "serverNames": ["$SNI"], "privateKey": "$PRIV", "shortIds": ["$SID"]
      }
    }
  }],
  "outbounds": [{"protocol": "freedom"}]
}
EOF
fi
# open port 443 if a firewall is active
if command -v ufw >/dev/null && $SUDO ufw status | grep -q active; then $SUDO ufw allow 443/tcp >/dev/null; fi
if command -v firewall-cmd >/dev/null && $SUDO firewall-cmd --state >/dev/null 2>&1; then $SUDO firewall-cmd --permanent --add-port=443/tcp >/dev/null && $SUDO firewall-cmd --reload >/dev/null; fi
# enable BBR
echo "net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr" | $SUDO tee /etc/sysctl.d/99-bbr.conf >/dev/null; $SUDO sysctl --system >/dev/null 2>&1 || true
$SUDO systemctl enable xray >/dev/null 2>&1
$SUDO systemctl restart xray
sleep 1
$SUDO systemctl is-active --quiet xray || { $SUDO journalctl -u xray -n 20 --no-pager; exit 1; }
if [ "$KEEP_CONFIG" != "1" ]; then
  echo "=== proxy.env ==="
  echo "SERVER_IP=$(curl -fsS4 https://api.ipify.org)"
  echo "UUID=$UUID"
  echo "PUBLIC_KEY=$PUB"
  echo "SHORT_ID=$SID"
  echo "REALITY_SERVER_NAME=$SNI"
else
  echo "Xray is running with the uploaded config."
fi
REMOTE
