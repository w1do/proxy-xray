#!/usr/bin/env bash
# Usage: bash server/setup-server.sh user@NEW_SERVER_IP [ssh options...]
# Installs Xray (VLESS+Reality on :443) on a fresh server over SSH and prints proxy.env values.
# KEEP_CONFIG=1  -> upload server/xray-config.json instead of generating new keys.
# CHAIN_USA=1 U_IP=.. U_ID=.. U_PK=.. U_SID=.. [U_SNI=..] -> forward only AI domains to the USA upstream.
# CHAIN_ALL=1 U_IP=.. U_ID=.. U_PK=.. U_SID=.. [U_SNI=..] -> forward ALL inbound traffic to the USA upstream.
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

CHAIN=""
if [ "${CHAIN_USA:-0}" = "1" ]; then
  CHAIN="CHAIN_USA=1 U_IP=${U_IP:?} U_ID=${U_ID:?} U_PK=${U_PK:?} U_SID=${U_SID:?} U_SNI=${U_SNI:-dl.google.com}"
elif [ "${CHAIN_ALL:-0}" = "1" ]; then
  CHAIN="CHAIN_ALL=1 U_IP=${U_IP:?} U_ID=${U_ID:?} U_PK=${U_PK:?} U_SID=${U_SID:?} U_SNI=${U_SNI:-dl.google.com}"
fi
"${SSH[@]}" "KEEP_CONFIG=${KEEP_CONFIG:-0} SNI=$SNI $CHAIN bash -s" <<'REMOTE'
set -euo pipefail
SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo"
export DEBIAN_FRONTEND=noninteractive
export TERM="${TERM:-dumb}"

# Do not install/reconfigure Xray if another service already owns its listen port.
if command -v ss >/dev/null 2>&1; then
  LISTENERS="$( $SUDO ss -H -ltnp 'sport = :443' 2>/dev/null || true )"
  if [ -n "$LISTENERS" ]; then
    echo "Port 443/tcp is already in use; Xray was not installed or restarted." >&2
    echo "$LISTENERS" >&2
    echo "Stop or reconfigure the listed service, then rerun this script." >&2
    exit 10
  fi
fi

if command -v apt-get >/dev/null; then
  if ! $SUDO apt-get update -qq; then
    echo "APT repository update failed. Check/disable the broken repository (for example pkg.cloudflare.com) and rerun." >&2
    exit 11
  fi
  $SUDO apt-get install -y -qq curl openssl ca-certificates unzip iproute2 >/dev/null
elif command -v dnf >/dev/null; then $SUDO dnf install -y -q curl openssl ca-certificates unzip
elif command -v yum >/dev/null; then $SUDO yum install -y -q curl openssl ca-certificates unzip
fi
curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh -o /tmp/xray-install.sh
$SUDO bash /tmp/xray-install.sh install >/dev/null
CFG=/usr/local/etc/xray/config.json
OUT='"outbounds": [{"protocol": "freedom", "tag": "direct"}]'
if [ "${CHAIN_USA:-0}" = "1" ]; then
  AI='"domain:openai.com","domain:chatgpt.com","domain:oaiusercontent.com","domain:oaistatic.com","domain:anthropic.com","domain:claude.ai","domain:claude.com","domain:claudeusercontent.com","domain:jetbrains.ai","domain:jetbrains.cloud","domain:jetbrains.com","domain:grazie.ai","domain:intellij.net"'
  OUT="\"outbounds\": [
    {\"tag\":\"usa\",\"protocol\":\"vless\",\"settings\":{\"vnext\":[{\"address\":\"$U_IP\",\"port\":443,\"users\":[{\"id\":\"$U_ID\",\"flow\":\"xtls-rprx-vision\",\"encryption\":\"none\"}]}]},
     \"streamSettings\":{\"network\":\"raw\",\"security\":\"reality\",\"realitySettings\":{\"serverName\":\"$U_SNI\",\"fingerprint\":\"firefox\",\"publicKey\":\"$U_PK\",\"shortId\":\"$U_SID\"}}},
    {\"tag\":\"direct\",\"protocol\":\"freedom\"}],
  \"routing\": {\"rules\":[{\"type\":\"field\",\"domain\":[$AI],\"outboundTag\":\"usa\"}]}"
fi
if [ "${CHAIN_ALL:-0}" = "1" ]; then
  OUT="\"outbounds\": [
    {\"tag\":\"to-usa\",\"protocol\":\"vless\",\"settings\":{\"vnext\":[{\"address\":\"$U_IP\",\"port\":443,\"users\":[{\"id\":\"$U_ID\",\"flow\":\"xtls-rprx-vision\",\"encryption\":\"none\"}]}]},
     \"streamSettings\":{\"network\":\"raw\",\"security\":\"reality\",\"realitySettings\":{\"serverName\":\"$U_SNI\",\"fingerprint\":\"chrome\",\"publicKey\":\"$U_PK\",\"shortId\":\"$U_SID\"}}},
    {\"tag\":\"direct\",\"protocol\":\"freedom\"}],
  \"routing\": {\"rules\":[{\"type\":\"field\",\"inboundTag\":[\"vless-reality-in\"],\"outboundTag\":\"to-usa\"}]}"
fi
if [ "$KEEP_CONFIG" != "1" ] && $SUDO test -f "$CFG"; then
  $SUDO cp -a "$CFG" "$CFG.backup.$(date +%Y%m%d-%H%M%S)"
fi
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
    "tag": "vless-reality-in", "listen": "0.0.0.0",
    "port": 443, "protocol": "vless",
    "settings": {"clients": [{"id": "$UUID", "flow": "xtls-rprx-vision"}], "decryption": "none"},
    "streamSettings": {
      "network": "raw", "security": "reality",
      "realitySettings": {
        "show": false, "target": "$SNI:443", "xver": 0,
        "serverNames": ["$SNI"], "privateKey": "$PRIV", "shortIds": ["$SID"]
      }
    }
  }],
  $OUT
}
EOF
fi
$SUDO chown nobody:nogroup "$CFG" 2>/dev/null || $SUDO chown nobody "$CFG" 2>/dev/null || true
$SUDO chmod 600 "$CFG"
$SUDO xray run -test -config "$CFG"
# open port 443 if a firewall is active
if command -v ufw >/dev/null && $SUDO ufw status | grep -q active; then $SUDO ufw allow 443/tcp >/dev/null; fi
if command -v firewall-cmd >/dev/null && $SUDO firewall-cmd --state >/dev/null 2>&1; then $SUDO firewall-cmd --permanent --add-port=443/tcp >/dev/null && $SUDO firewall-cmd --reload >/dev/null; fi
# enable BBR
echo "net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr" | $SUDO tee /etc/sysctl.d/99-bbr.conf >/dev/null; $SUDO sysctl --system >/dev/null 2>&1 || true
$SUDO systemctl enable xray >/dev/null 2>&1
$SUDO systemctl restart xray
sleep 1
$SUDO systemctl is-active --quiet xray || { $SUDO journalctl -u xray -n 50 --no-pager; exit 1; }
$SUDO ss -H -ltnp '( sport = :443 )'
if [ "$KEEP_CONFIG" != "1" ] && [ "${CHAIN_ALL:-0}" = "1" ]; then
  NL_IP="$(curl -fsS4 https://api.ipify.org 2>/dev/null || true)"
  [ -n "$NL_IP" ] || { echo "Could not determine NL public IPv4 address." >&2; exit 12; }
  $SUDO tee /root/nl-client-values.txt >/dev/null <<EOF
SERVER_IP=$NL_IP
UUID=$UUID
PUBLIC_KEY=$PUB
SHORT_ID=$SID
SERVER_NAME=$SNI
EOF
  $SUDO chmod 600 /root/nl-client-values.txt
  echo "Relay configured (CHAIN_ALL=1): all inbound traffic is forwarded to the USA upstream."
  echo "Client values written to /root/nl-client-values.txt (mode 600)."
elif [ "$KEEP_CONFIG" != "1" ]; then
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
