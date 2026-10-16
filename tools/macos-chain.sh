#!/usr/bin/env bash
# Sourced by install.sh (macOS) and tests. Bash 3.2 compatible: no associative arrays, no mapfile, no ${var,,}.
# Do NOT put set -euo pipefail in this file (the caller owns shell options). Every function
# must work under the caller's set -euo pipefail.

XRAY_VERSION="26.10.10"
XRAY_SOCKS_PORT="18080"
XRAY_AGENT_LABEL="com.mihomo.xray"

# NL port map for each USA exit. Must match NL_PORTS in tools/install-client.py
# (enforced by tests/test_macos_chain.py).
nl_allowed_ports() {
  case "$1" in
    108.61.222.91) echo "2083 2084 2085 2086" ;;
    149.28.240.154) echo "2087 2088 2089 2090" ;;
    *) return 1 ;;
  esac
}

# Returns 0 when PORT is an NL inbound for EXIT_IP. Otherwise prints the reason to stderr, returns 2.
nl_check_exit_port() {
  local exit_ip="${1:-}" port="${2:-}" allowed p list=""
  if ! allowed="$(nl_allowed_ports "$exit_ip")"; then
    echo "Unknown USA exit: $exit_ip (use 108.61.222.91 or 149.28.240.154)" >&2
    return 2
  fi
  for p in $allowed; do
    if [ "$p" = "$port" ]; then
      return 0
    fi
  done
  for p in $allowed; do
    if [ -n "$list" ]; then
      list="$list/$p"
    else
      list="$p"
    fi
  done
  echo "Exit $exit_ip needs NL port $list, but SERVER_PORT=$port" >&2
  return 2
}

# Prints "Invalid NAME in proxy.env" and returns 2 when VALUE does not match REGEX.
chain_check_value() {
  local name="$1" value="$2" re="$3"
  if ! [[ "$value" =~ $re ]]; then
    echo "Invalid $name in proxy.env" >&2
    return 2
  fi
  return 0
}

# Validates the settings that render_xray_client_json writes without escaping.
chain_validate_settings() {
  local re
  re='^[A-Za-z0-9.:-]+$'
  chain_check_value SERVER_IP "${SERVER_IP:-}" "$re" || return 2
  re='^[0-9]{1,5}$'
  chain_check_value SERVER_PORT "${SERVER_PORT:-}" "$re" || return 2
  if [ "$((10#${SERVER_PORT}))" -lt 1 ] || [ "$((10#${SERVER_PORT}))" -gt 65535 ]; then
    echo "Invalid SERVER_PORT in proxy.env" >&2
    return 2
  fi
  re='^[A-Za-z0-9_-]{1,64}$'
  chain_check_value UUID "${UUID:-}" "$re" || return 2
  re='^[A-Za-z0-9_-]+$'
  chain_check_value PUBLIC_KEY "${PUBLIC_KEY:-}" "$re" || return 2
  re='^[0-9A-Fa-f]{0,16}$'
  chain_check_value SHORT_ID "${SHORT_ID:-}" "$re" || return 2
  re='^[A-Za-z0-9.-]+$'
  chain_check_value REALITY_SERVER_NAME "${REALITY_SERVER_NAME:-}" "$re" || return 2
  case "${SERVER_NETWORK:-}" in
    xhttp)
      re='^/[A-Za-z0-9/_.~-]*$'
      chain_check_value XHTTP_PATH "${XHTTP_PATH:-}" "$re" || return 2
      re='^[a-z-]+$'
      chain_check_value XHTTP_MODE "${XHTTP_MODE:-}" "$re" || return 2
      ;;
    tcp) ;;
    grpc)
      re='^[A-Za-z0-9_./-]+$'
      chain_check_value GRPC_SERVICE_NAME "${GRPC_SERVICE_NAME:-}" "$re" || return 2
      ;;
    *)
      echo "Invalid SERVER_NETWORK in proxy.env" >&2
      return 2
      ;;
  esac
  re='^[a-z0-9_]+$'
  chain_check_value CLIENT_FINGERPRINT "${CLIENT_FINGERPRINT:-}" "$re" || return 2
  return 0
}

# Prints the Xray client JSON for the settings in the environment. Same document as
# xray_config() in tools/install-client.py with ADMIN_SSH_TUNNEL unset.
render_xray_client_json() {
  chain_validate_settings || return $?
  local flow="" net_extra=""
  case "$SERVER_NETWORK" in
    tcp) flow=',"flow":"xtls-rprx-vision"' ;;
    xhttp) net_extra="\"xhttpSettings\":{\"path\":\"${XHTTP_PATH}\",\"mode\":\"${XHTTP_MODE}\"}," ;;
    grpc) net_extra="\"grpcSettings\":{\"serviceName\":\"${GRPC_SERVICE_NAME}\"}," ;;
  esac
  printf '%s\n' '{"log":{"loglevel":"warning"},"inbounds":[{"listen":"127.0.0.1","port":18080,"protocol":"socks","settings":{"udp":true}}],"outbounds":[{"protocol":"vless","settings":{"vnext":[{"address":"'"$SERVER_IP"'","port":'"$((10#${SERVER_PORT}))"',"users":[{"id":"'"$UUID"'","encryption":"none"'"$flow"'}]}]},"streamSettings":{"network":"'"$SERVER_NETWORK"'","security":"reality",'"$net_extra"'"realitySettings":{"serverName":"'"$REALITY_SERVER_NAME"'","fingerprint":"'"$CLIENT_FINGERPRINT"'","password":"'"$PUBLIC_KEY"'","shortId":"'"$SHORT_ID"'"}}}]}'
}

# Prints the USA socks5 proxy entry for Mihomo's proxies: list (two-space indent).
render_usa_socks_block() {
  printf '%s\n' "  - name: USA" "    type: socks5" "    server: 127.0.0.1" "    port: ${XRAY_SOCKS_PORT}" "    udp: true"
}

# Prints the LaunchAgent plist that keeps the local Xray running.
render_xray_launch_agent() {
  local xray_bin="$1" config_file="$2" log_file="$3"
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${XRAY_AGENT_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${xray_bin}</string>
    <string>run</string>
    <string>-config</string>
    <string>${config_file}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${log_file}</string>
  <key>StandardErrorPath</key>
  <string>${log_file}</string>
</dict>
</plist>
EOF
}

# Prints "<asset> <sha256>" of the pinned official Xray release for MACHINE.
xray_darwin_asset() {
  case "$1" in
    arm64) echo "Xray-macos-arm64-v8a.zip 7b1711eaeefd90f27082cf49c311aa57dad44ac13146faab3f0c1601158ea6c8" ;;
    x86_64) echo "Xray-macos-64.zip f99119d4aa662ae2e9a2adf57eccf3dad1b43035ae2e06ccc3949c8256e33fd0" ;;
    *) return 1 ;;
  esac
}

# Prints the lowercase hex SHA-256 of FILE.
chain_sha256() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    return 1
  fi
}

# Returns 0 when BINARY reports the pinned Xray version on its first line.
xray_version_ok() {
  local version_line
  version_line="$("$1" version 2>/dev/null | head -n 1 || true)"
  case "$version_line" in
    "Xray ${XRAY_VERSION} "*) return 0 ;;
  esac
  return 1
}

# Returns 0 when BINARY is the file this kit installed: its sha256 equals the recorded MARKER value.
xray_owned_by_kit() {
  local binary="$1" marker="$2" recorded digest
  [ -f "$marker" ] || return 1
  recorded="$(cat "$marker" 2>/dev/null || true)"
  digest="$(chain_sha256 "$binary" || true)"
  [ -n "$recorded" ] && [ "$recorded" = "$digest" ]
}

# Renders the Xray client config (it holds the REALITY credentials) straight into a
# file that is created with mode 600: there is no window with a wider mode.
chain_write_xray_config() {
  local dest="$1"
  ( umask 077; render_xray_client_json > "$dest" ) || return $?
  chmod 600 "$dest"
}

# Creates DIR if needed and restricts it to its owner.
chain_secure_dir() {
  mkdir -p "$1" && chmod 700 "$1"
}

# Installs BIN_DIR/xray from the pinned official archive (local copy in SCRIPT_DIR/bin wins).
# Returns 0 on success, prints an error and returns 8 on failure.
install_xray_darwin() {
  local script_dir="$1" bin_dir="$2"
  local target="$bin_dir/xray" marker="$bin_dir/.xray-mihomo-kit.sha256"
  local info asset="" sha="" work new digest
  if [ -x "$target" ] && xray_version_ok "$target" && xray_owned_by_kit "$target" "$marker"; then
    echo "Xray ${XRAY_VERSION} already installed"
    return 0
  fi
  info="$(xray_darwin_asset "$(uname -m)" || true)"
  read -r asset sha <<< "$info" || true
  if [ -z "$asset" ]; then
    echo "No Xray build for $(uname -m)" >&2
    return 8
  fi
  work="$(mktemp -d)"
  if [ -f "$script_dir/bin/$asset" ]; then
    cp "$script_dir/bin/$asset" "$work/$asset" || { rm -rf "$work"; return 8; }
    echo "Using local Xray archive: $script_dir/bin/$asset"
  else
    if ! curl -fL --proto '=https' --proto-redir '=https' --tlsv1.2 -A "mihomo-private-installer" "https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VERSION}/${asset}" -o "$work/$asset"; then
      rm -rf "$work"
      echo "Xray download failed: $asset" >&2
      return 8
    fi
  fi
  if [ "$(chain_sha256 "$work/$asset" || true)" != "$sha" ]; then
    rm -rf "$work"
    echo "Xray archive checksum mismatch: $asset" >&2
    return 8
  fi
  mkdir -p "$work/x"
  if ! unzip -q -o "$work/$asset" xray -d "$work/x"; then
    rm -rf "$work"
    echo "Cannot unpack xray from $asset" >&2
    return 8
  fi
  chmod 755 "$work/x/xray"
  if ! xray_version_ok "$work/x/xray"; then
    rm -rf "$work"
    echo "Wrong Xray version in $asset" >&2
    return 8
  fi
  mkdir -p "$bin_dir"
  new="$(mktemp "$bin_dir/.xray.XXXXXX")" || { rm -rf "$work"; return 8; }
  if ! cp "$work/x/xray" "$new"; then
    rm -f "$new"
    rm -rf "$work"
    return 8
  fi
  chmod 755 "$new"
  if ! mv -f "$new" "$target"; then
    rm -f "$new"
    rm -rf "$work"
    return 8
  fi
  digest="$(chain_sha256 "$target" || true)"
  if [ -z "$digest" ] || ! ( umask 077; printf '%s\n' "$digest" > "$marker" ); then
    rm -rf "$work"
    echo "Cannot record ownership marker: $marker" >&2
    return 8
  fi
  chmod 600 "$marker"
  rm -rf "$work"
  echo "Xray ${XRAY_VERSION} installed: $target"
  return 0
}

# Returns 0 while something listens on 127.0.0.1:PORT (ss, else lsof, else /dev/tcp).
chain_port_listening() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -H -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}\$"
  elif command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
  else
    (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null
  fi
}
