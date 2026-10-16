# nl-usa2-ports-macos-xray-chain

## Open questions (non-blocking; defaults below are applied unless the user overrides)

1. **Xray for macOS: ship zips in `bin/` or download?** Default in this spec: download the pinned
   official zip from GitHub (v26.10.10) and verify its SHA-256. If the official zip is placed in
   `bin/` under its official name, it is used offline with the same check. The zips are NOT
   committed by this change (about 21 MB each). Say so if you want them committed.
2. **`install.sh` without an IP argument on macOS.** Default: legacy behaviour is kept (no
   NL port check, `EXPECTED_EXIT_IP` from `proxy.env` or `SERVER_IP`, old network inference).
   Linux keeps its own default (USA2). Say so if macOS should also default to USA2.
3. **Linux arm64.** Decision: NOT included. `bin/` has no linux-arm64 Mihomo, the Python
   installer pins hashes only for the shipped x86_64 archives, and there is no arm64 machine to
   verify on. The existing error `Этот установщик поддерживает Linux x86_64` stays. Follow-up change.
4. **Real macOS run** can only be done by the user on a Mac (see Test strategy, section M).

## Problem statement

1. `bash install.sh 149.28.240.154` (Linux/WSL) rejects the live NL inbounds 2088, 2089, 2090
   for USA2 with `Для выхода 149.28.240.154 нужен вход NL:2087, а указан порт 2088`.
   Cause: `tools/install-client.py`, `profile_from_settings()`:
   ```python
   allowed_ports = {'108.61.222.91': {2083, 2084, 2085, 2086}, '149.28.240.154': {2087}}[requested]
   ```
   Live NL (185.245.107.19), verified 2026-10-16 with `bash vless.sh --check`:
   USA1 108.61.222.91 ← 2083 XHTTP, 2084 TCP+Vision, 2085 gRPC, 2086 XHTTP;
   USA2 149.28.240.154 ← 2087 XHTTP, 2088 TCP+Vision, 2089 gRPC, 2090 XHTTP.
2. `set-proxy-env.sh` usage text (lines 2 and 12) says `SERVER_PORT=2083|2087`.
3. On macOS, `install.sh` runs its bash path and makes Mihomo speak VLESS/REALITY to NL directly.
   Mihomo 1.19.32 fails REALITY against Xray >= 26.9.30, which is why NL is pinned to Xray
   26.3.27. Linux already uses app → Mihomo `127.0.0.1:7890` → local Xray `127.0.0.1:18080` →
   NL → USA and works. macOS must use the same chain, the same transports (xhttp, tcp+vision,
   grpc), the same NL port/exit mapping, and have an uninstall/rollback path.

## Goals and non-goals

Goals:
- USA2 accepts NL ports 2087, 2088, 2089, 2090; USA1 keeps 2083-2086; cross-exit ports are rejected.
- One NL port map, enforced identically by the Python installer (Linux) and `install.sh` (macOS);
  a test fails if they diverge.
- macOS: local Xray 26.10.10 (official build, SHA-256 pinned) under a LaunchAgent
  `com.mihomo.xray`, Mihomo's `USA` proxy becomes `socks5 127.0.0.1:18080`.
- `install.sh <USA_IP>` on macOS validates exit/port and checks the exit IP, like Linux.
- Opt-out `XRAY_CHAIN=0` restores the current direct Mihomo mode on macOS (rollback without revert).
- `unregister.sh` removes the Xray parts on both OSes.
- All macOS logic that can be unit-tested is tested on this Linux machine.

Non-goals:
- No server-side change (NL, USA1, USA2 untouched). No NL Xray upgrade.
- No change to the Linux install flow other than the port map.
- No Linux arm64 support. No checksum for the macOS Mihomo download (unchanged behaviour).
- No change to `tools/mihomo-config.py`, `mihomo-keepalive.sh`, `vless.sh`, `proxy`.

## Current architecture analysis

- `install.sh` line 5-7: on `uname -s` = Linux it `exec`s `python3 tools/install-client.py "$@"`.
  Everything after that line runs only on non-Linux, i.e. macOS in practice (the Linux branches
  of the platform `case` are dead code; leave them).
- `tools/install-client.py` (Linux): `settings()` reads `proxy.env`; `profile_from_settings(env,
  requested)` validates the port and builds `row`; `xray_config(env, row)` builds the Xray client
  JSON (socks inbound 127.0.0.1:18080 udp, VLESS outbound with REALITY, `flow` only for tcp,
  `xhttpSettings` only for xhttp, `grpcSettings` only for grpc, `realitySettings.password` =
  public key, fingerprint default `firefox`); systemd user units `xray-mihomo.service` and
  `mihomo.service`; exit check by `api.ipify.org` equals the requested IP. Network default `xhttp`,
  `XHTTP_PATH` default `/dl`, `XHTTP_MODE` default `auto`.
- `install.sh` (macOS): bash 3.2 compatible; reads `proxy.env` (fallback `.env`); infers
  `SERVER_NETWORK` (xhttp if `XHTTP_PATH` set, else tcp); builds `NETWORK_BLOCK`/`FLOW_BLOCK`;
  installs Mihomo from `bin/` or GitHub; writes `config.yaml` with a VLESS `USA` proxy; LaunchAgent
  `com.mihomo.proxy` (`write_launch_agent`); exit check via chatgpt `cdn-cgi/trace` against
  `EXPECTED_EXIT_IP`; macOS system proxy via `networksetup`; exit codes 2-7 in use.
- `unregister.sh` (repo root): removes Mihomo, its systemd unit / LaunchAgent / cron block,
  shell blocks; does not know about local Xray (README says so).
- Tests: `tests/test_mihomo_config.py` (unittest, loads a `tools/*.py` module via
  `importlib.util.spec_from_file_location`, skips the binary check when the binary is absent).
  No test covers `tools/install-client.py` yet.
- OpenSpec layout: `openspec/changes/<id>/` with `.openspec.yaml` + `proposal.md`.

## Relevant files and symbols

- `tools/install-client.py`: `profile_from_settings`, `main` (exit list check), `xray_config`.
- `install.sh`: Linux `exec` (line 5-7), `AMBIENT_OVERRIDES` loop, settings defaults block,
  `SERVER_NETWORK` inference + `case`, `write_launch_agent`, Mihomo install (`mv -f "$NEW_BIN" "$BIN"`),
  config heredoc `cat > "$TMP_CONFIG" <<EOF` (`proxies:` section), supervisor `case`, stop/start
  section, `port_is_listening`, final `case "$SUPERVISOR"` messages.
- `set-proxy-env.sh`: lines 2, 9 (`ALLOWED`), 12.
- `unregister.sh`: `stop_systemd`, `stop_launchd`, `stop_standalone_process`, final `rm -f`.
- `README.md`: launch section, NL ports table, `Обслуживание` (unregister line).
- `tests/test_mihomo_config.py`: style reference only (not modified).

## Proposed architecture

1. Single NL port map:
   - Python: module constant `NL_PORTS` in `tools/install-client.py`.
   - Bash: function `nl_allowed_ports` in new file `tools/macos-chain.sh`.
   - Test `test_bash_and_python_port_maps_match` enforces equality.
2. New sourced bash library `tools/macos-chain.sh` (no top-level side effects; only variable
   constants and functions; bash 3.2 compatible) holding all new macOS logic so it is testable
   from Python unittest via `bash -c '. tools/macos-chain.sh; <function>'` on Linux.
3. `install.sh` on macOS: optional first argument = USA exit IP ("NL mode"). With `XRAY_CHAIN`
   (default `1`), install Xray, write `xray-client.json`, run it under LaunchAgent
   `com.mihomo.xray` (or nohup when `launchctl` is missing), wait for 127.0.0.1:18080, then run
   Mihomo with `USA = socks5 127.0.0.1:18080`. `XRAY_CHAIN=0` keeps the old direct VLESS block
   and removes any Xray agent/process left by a previous run.
4. `unregister.sh` also removes `xray-mihomo.service`, `xhttp-nl-admin-tunnel.service`,
   `com.mihomo.xray.plist`, standalone Xray process, `~/.local/bin/xray`.

## Detailed implementation plan

### A. `tools/install-client.py`
- Add after `NO_PROXY_ENV = ...` (module level):
  ```python
  NL_PORTS = {'108.61.222.91': frozenset({2083, 2084, 2085, 2086}),
              '149.28.240.154': frozenset({2087, 2088, 2089, 2090})}
  ```
- In `profile_from_settings`, replace the dict literal line with
  `allowed_ports = NL_PORTS[requested]`. Do not change the rest of the function (error text
  format stays: ports joined by `/`, sorted).
- In `main`, replace `if requested not in ('149.28.240.154', '108.61.222.91'):` with
  `if requested not in NL_PORTS:`. Keep the message text unchanged.

### B. `set-proxy-env.sh`
- Line 2 and line 12: replace `SERVER_PORT=2083|2087` with `SERVER_PORT=2083-2086|2087-2090`.
  Nothing else on those lines changes.
- Line 9 `ALLOWED=...`: append ` XRAY_CHAIN` at the end of the list (inside the quotes).

### C. New file `tools/macos-chain.sh`
Header: `#!/usr/bin/env bash` and a comment `# Sourced by install.sh (macOS) and tests. Bash 3.2 compatible: no associative arrays, no mapfile, no ${var,,}.`
Do NOT put `set -euo pipefail` in this file (the caller owns shell options). Every function
must work under the caller's `set -euo pipefail`.

Constants:
```bash
XRAY_VERSION="26.10.10"
XRAY_SOCKS_PORT="18080"
XRAY_AGENT_LABEL="com.mihomo.xray"
```

Functions (exact names and contracts):

1. `nl_allowed_ports EXIT_IP` — prints space-separated ports and returns 0:
   `108.61.222.91` → `2083 2084 2085 2086`; `149.28.240.154` → `2087 2088 2089 2090`;
   anything else → prints nothing, returns 1. Implement with `case`.
2. `nl_check_exit_port EXIT_IP PORT` — returns 0 if PORT is in `nl_allowed_ports EXIT_IP`.
   Otherwise prints to stderr and returns 2:
   - unknown exit: `Unknown USA exit: <EXIT_IP> (use 108.61.222.91 or 149.28.240.154)`
   - wrong port: `Exit <EXIT_IP> needs NL port <p1>/<p2>/<p3>/<p4>, but SERVER_PORT=<PORT>`
     (ports in ascending order joined by `/`).
3. `chain_validate_settings` — reads globals `SERVER_IP SERVER_PORT UUID PUBLIC_KEY SHORT_ID
   REALITY_SERVER_NAME SERVER_NETWORK XHTTP_PATH XHTTP_MODE GRPC_SERVICE_NAME CLIENT_FINGERPRINT`.
   Checks with `[[ "$v" =~ regex ]]`; on the first failure prints
   `Invalid <NAME> in proxy.env` to stderr and returns 2. Rules:
   - `SERVER_IP` `^[A-Za-z0-9.:-]+$`
   - `SERVER_PORT` `^[0-9]{1,5}$` and 1..65535
   - `UUID` `^[A-Za-z0-9_-]{1,64}$`
   - `PUBLIC_KEY` `^[A-Za-z0-9_-]+$`
   - `SHORT_ID` `^[0-9A-Fa-f]{0,16}$`
   - `REALITY_SERVER_NAME` `^[A-Za-z0-9.-]+$`
   - `SERVER_NETWORK` one of `xhttp tcp grpc`
   - when xhttp: `XHTTP_PATH` `^/[A-Za-z0-9/_.~-]*$`, `XHTTP_MODE` `^[a-z-]+$`
   - when grpc: `GRPC_SERVICE_NAME` `^[A-Za-z0-9_./-]+$`
   - `CLIENT_FINGERPRINT` `^[a-z0-9_]+$`
   Store each regex in a local variable before `[[ =~ $re ]]` (bash 3.2 quoting rule).
   Purpose: the JSON below is produced by `printf` without escaping, so only these
   character sets are allowed.
4. `render_xray_client_json` — reads the same globals (call `chain_validate_settings` first;
   if it fails, return its status). Prints one JSON document to stdout whose parsed value is
   exactly what `xray_config(env, row)` in `tools/install-client.py` returns with
   `ADMIN_SSH_TUNNEL` unset:
   ```
   {"log":{"loglevel":"warning"},
    "inbounds":[{"listen":"127.0.0.1","port":18080,"protocol":"socks","settings":{"udp":true}}],
    "outbounds":[{"protocol":"vless",
      "settings":{"vnext":[{"address":"<SERVER_IP>","port":<SERVER_PORT as number>,
        "users":[{"id":"<UUID>","encryption":"none"<, "flow":"xtls-rprx-vision" only for tcp>}]}]},
      "streamSettings":{"network":"<SERVER_NETWORK>","security":"reality",
        <"xhttpSettings":{"path":"<XHTTP_PATH>","mode":"<XHTTP_MODE>"}, only for xhttp>
        <"grpcSettings":{"serviceName":"<GRPC_SERVICE_NAME>"}, only for grpc>
        "realitySettings":{"serverName":"<REALITY_SERVER_NAME>","fingerprint":"<CLIENT_FINGERPRINT>",
          "password":"<PUBLIC_KEY>","shortId":"<SHORT_ID>"}}}]}
   ```
   Build optional fragments in local variables with `case "$SERVER_NETWORK"`, then one `printf`.
   Port numbers are emitted unquoted.
5. `render_usa_socks_block` — prints exactly (two-space indent, as in the `proxies:` list):
   ```
     - name: USA
       type: socks5
       server: 127.0.0.1
       port: 18080
       udp: true
   ```
6. `render_xray_launch_agent XRAY_BIN CONFIG_FILE LOG_FILE` — prints a plist in the same style
   as `write_launch_agent` in `install.sh`: `Label` = `com.mihomo.xray`; `ProgramArguments` =
   `XRAY_BIN`, `run`, `-config`, `CONFIG_FILE`; `RunAtLoad` true; `KeepAlive` true;
   `StandardOutPath` and `StandardErrorPath` = `LOG_FILE`.
7. `xray_darwin_asset MACHINE` — prints `<asset> <sha256>` and returns 0:
   - `arm64` → `Xray-macos-arm64-v8a.zip 7b1711eaeefd90f27082cf49c311aa57dad44ac13146faab3f0c1601158ea6c8`
   - `x86_64` → `Xray-macos-64.zip f99119d4aa662ae2e9a2adf57eccf3dad1b43035ae2e06ccc3949c8256e33fd0`
   - otherwise prints nothing, returns 1.
   (Verified 2026-10-16 against the GitHub API asset digests and the official `.dgst` files of
   release v26.10.10.)
8. `chain_sha256 FILE` — prints the lowercase hex SHA-256 of FILE using `shasum -a 256` if
   available, else `sha256sum`; returns 1 if neither exists.
9. `install_xray_darwin SCRIPT_DIR BIN_DIR` — installs `BIN_DIR/xray`, returns 0 on success,
   prints an error to stderr and returns 8 on any failure. Steps:
   1. `target="$BIN_DIR/xray"`. If `target` is executable and the first line of
      `"$target" version` starts with `Xray ${XRAY_VERSION} ` → print
      `Xray ${XRAY_VERSION} already installed` and return 0.
   2. `read -r asset sha <<< "$(xray_darwin_asset "$(uname -m)")"`; if empty →
      `No Xray build for $(uname -m)`, return 8.
   3. `work="$(mktemp -d)"`; remove it on every return path (no `trap` that overrides the
      caller's `EXIT` trap — use explicit `rm -rf "$work"` before each return).
   4. If `"$SCRIPT_DIR/bin/$asset"` is a file, copy it to `"$work/$asset"` and print
      `Using local Xray archive: <path>`; else
      `curl -fL -A "mihomo-private-installer" "https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VERSION}/${asset}" -o "$work/$asset"`.
   5. If `chain_sha256 "$work/$asset"` != `sha` → `Xray archive checksum mismatch: <asset>`, return 8.
   6. `unzip -q -o "$work/$asset" xray -d "$work/x"`; `chmod 755 "$work/x/xray"`; its
      `version` first line must start with `Xray ${XRAY_VERSION} ` else
      `Wrong Xray version in <asset>`, return 8.
   7. `new="$(mktemp "$BIN_DIR/.xray.XXXXXX")"`; `cp "$work/x/xray" "$new"`; `chmod 755 "$new"`;
      `mv -f "$new" "$target"`; print `Xray ${XRAY_VERSION} installed: $target`.
10. `chain_port_listening PORT` — same three-way logic as `port_is_listening` in `install.sh`
    (`ss`, else `lsof`, else `/dev/tcp`), parameterised by PORT.

### D. `install.sh` (all edits are after the Linux `exec` line, i.e. macOS only)
1. Right after line 7 (`fi` closing the Linux `exec`), add:
   ```bash
   # shellcheck disable=SC1091
   . "$SCRIPT_DIR/tools/macos-chain.sh"
   USA_EXIT="${1:-}"
   ```
2. Add `XRAY_CHAIN` to the `for VAR in ...` list of `AMBIENT_OVERRIDES`.
3. After `GRPC_SERVICE_NAME="${GRPC_SERVICE_NAME:-}"` and BEFORE the `if [ -z "${SERVER_NETWORK:-}" ]`
   inference, add NL-mode defaults (Linux parity):
   ```bash
   XRAY_CHAIN="${XRAY_CHAIN:-1}"
   case "$XRAY_CHAIN" in 0|1) ;; *) echo "XRAY_CHAIN must be 0 or 1" >&2; exit 2 ;; esac
   if [ -n "$USA_EXIT" ]; then
     SERVER_NETWORK="${SERVER_NETWORK:-xhttp}"
     if [ "$SERVER_NETWORK" = "xhttp" ]; then XHTTP_PATH="${XHTTP_PATH:-/dl}"; fi
   fi
   ```
4. After the existing `EXPECTED_EXIT_IP="${EXPECTED_EXIT_IP:-$DEFAULT_EXIT_IP}"` line add:
   ```bash
   if [ -n "$USA_EXIT" ]; then
     nl_check_exit_port "$USA_EXIT" "$SERVER_PORT" || exit 2
     EXPECTED_EXIT_IP="$USA_EXIT"
   fi
   USE_XRAY_CHAIN=0
   if [ "$(uname -s)" = "Darwin" ] && [ "$XRAY_CHAIN" = "1" ]; then USE_XRAY_CHAIN=1; fi
   ```
5. After the existing missing-settings check (`Required: SERVER_IP, UUID, PUBLIC_KEY, SHORT_ID`
   block), add: `if [ "$USE_XRAY_CHAIN" = "1" ]; then chain_validate_settings || exit 2; fi`.
6. Next to `LAUNCH_AGENT=...` add:
   ```bash
   XRAY_BIN="$BIN_DIR/xray"
   XRAY_CONFIG="$CONFIG_DIR/xray-client.json"
   XRAY_LOG="$CONFIG_DIR/xray.log"
   XRAY_PID_FILE="$CONFIG_DIR/xray.pid"
   XRAY_AGENT="$HOME/Library/LaunchAgents/${XRAY_AGENT_LABEL}.plist"
   ```
7. Add `"$CONFIG_DIR/.xray-client.json.new"` to the `rm -f` list in `cleanup()`.
8. After `mv -f "$NEW_BIN" "$BIN"`, add:
   ```bash
   if [ "$USE_XRAY_CHAIN" = "1" ]; then
     install_xray_darwin "$SCRIPT_DIR" "$BIN_DIR" || exit 8
     render_xray_client_json > "$CONFIG_DIR/.xray-client.json.new" || exit 8
     chmod 600 "$CONFIG_DIR/.xray-client.json.new"
     if ! XRAY_TEST="$("$XRAY_BIN" run -test -config "$CONFIG_DIR/.xray-client.json.new" 2>&1)"; then
       echo "Xray config test failed:" >&2; printf '%s\n' "$XRAY_TEST" | tail -n 20 >&2; exit 8
     fi
     mv -f "$CONFIG_DIR/.xray-client.json.new" "$XRAY_CONFIG"
     USA_PROXY_BLOCK="$(render_usa_socks_block)"
   fi
   ```
9. In the config heredoc, replace the whole `  - name: USA` VLESS block (from `  - name: USA`
   through `      short-id: ${SHORT_ID}`) with `${USA_PROXY_BLOCK}`. Before the heredoc, when
   `USE_XRAY_CHAIN` is `0`, set `USA_PROXY_BLOCK` to the exact current VLESS block text
   (same lines, same `${NETWORK_BLOCK}` / `${FLOW_BLOCK}` substitutions) so legacy output is
   byte-identical. `${RU_BLOCK}` stays right after it, unchanged.
10. Supervisor `case`, `launchd)` branch: after `write_launch_agent` add
    `if [ "$USE_XRAY_CHAIN" = "1" ]; then render_xray_launch_agent "$XRAY_BIN" "$XRAY_CONFIG" "$XRAY_LOG" > "$XRAY_AGENT"; fi`.
11. Before the comment `# Stop the instance of the previous run.` add an Xray section:
    - Always (both values of `USE_XRAY_CHAIN`): if `launchctl` exists,
      `launchctl bootout "gui/$(id -u)" "$XRAY_AGENT" >/dev/null 2>&1 || true`; if
      `XRAY_PID_FILE` holds a live pid whose `ps -p <pid> -o args=` contains `$XRAY_BIN`, kill it
      and remove the pid file.
    - If `USE_XRAY_CHAIN` = `0`: `rm -f "$XRAY_AGENT"` and continue (legacy mode).
    - If `USE_XRAY_CHAIN` = `1`: wait up to 10 s for `chain_port_listening 18080` to become false;
      then start: `launchd` → `launchctl bootstrap "gui/$(id -u)" "$XRAY_AGENT"` with the same
      `unload`/`load -w` fallback as Mihomo; otherwise `env -u <same proxy vars as the Mihomo
      nohup line> nohup "$XRAY_BIN" run -config "$XRAY_CONFIG" >> "$XRAY_LOG" 2>&1 &` and write
      `$!` to `XRAY_PID_FILE`. Then wait up to 15 s for `chain_port_listening 18080`; on timeout
      print `Xray did not open 127.0.0.1:18080. See: $XRAY_LOG`, `tail -n 20 "$XRAY_LOG"` to
      stderr and `exit 9`.
12. The Mihomo kill loop `for RUNNING_PID in $(pgrep -x mihomo ...)` stays as is (it only kills
    `mihomo`, not `xray`).
13. Exit-IP failure messages (exit 5 and 6): when `USE_XRAY_CHAIN` = `1`, additionally print
    `Last Xray log lines:` and `tail -n 30 "$XRAY_LOG"` to stderr.
14. Final summary: when `USE_XRAY_CHAIN` = `1` print
    `Chain: Mihomo 127.0.0.1:${PROXY_PORT} -> Xray 127.0.0.1:18080 -> ${SERVER_IP}:${SERVER_PORT} -> ${EXPECTED_EXIT_IP}`
    and, in the `launchd)` message branch, `LaunchAgent 'com.mihomo.xray' keeps Xray running.`

### E. `unregister.sh`
- Add variables: `XRAY_BIN="$BIN_DIR/xray"`,
  `XRAY_AGENT="$HOME/Library/LaunchAgents/com.mihomo.xray.plist"`,
  `SYSTEMD_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"`.
- `stop_systemd`: also `disable --now` and remove `xray-mihomo.service` and
  `xhttp-nl-admin-tunnel.service` units from `SYSTEMD_DIR` (same pattern as `mihomo.service`),
  then one `daemon-reload`.
- `stop_launchd`: also `bootout`/`unload`/`rm -f` `XRAY_AGENT`.
- `stop_standalone_process`: also handle `$CONFIG_DIR/xray.pid` with `$XRAY_BIN` in the args check.
- Final `rm -f` adds `"$XRAY_BIN"`. Final echo: `Mihomo and local Xray proxy removed: ...`
  (keep the rest of the sentence).

### F. `README.md`
- NL ports table: list all 8 inbounds (2083 XHTTP, 2084 TCP+Vision, 2085 gRPC, 2086 XHTTP → USA1;
  2087 XHTTP, 2088 TCP+Vision, 2089 gRPC, 2090 XHTTP → USA2).
- Launch section: USA1 accepts `SERVER_PORT` 2083-2086, USA2 2087-2090; each port has its own UUID;
  for 2084/2088 set `SERVER_NETWORK=tcp`, for 2085/2089 `SERVER_NETWORK=grpc` and `GRPC_SERVICE_NAME`.
- New subsection `macOS`: same command `bash install.sh <USA_IP>`; chain Mihomo → Xray 26.10.10
  (downloaded from the official release, SHA-256 checked, or taken from `bin/` if the official zip
  is placed there) → NL → USA; LaunchAgents `com.mihomo.proxy` and `com.mihomo.xray`; logs
  `~/.config/mihomo/mihomo.log` and `~/.config/mihomo/xray.log`; `XRAY_CHAIN=0` in `proxy.env`
  returns to direct Mihomo mode; real run on a Mac not yet verified.
- `Обслуживание`: replace the `tools/unregister.sh` line with `bash unregister.sh` — removes Mihomo,
  local Xray, their services/LaunchAgents and shell settings on Linux and macOS.

## Data-flow and control-flow description

macOS, `bash install.sh 149.28.240.154`, `XRAY_CHAIN` unset:
args → source `tools/macos-chain.sh` → read `proxy.env` → NL defaults (xhttp, `/dl`) →
`nl_check_exit_port` → `EXPECTED_EXIT_IP=149.28.240.154` → `chain_validate_settings` →
Mihomo binary → `install_xray_darwin` → `render_xray_client_json` → `xray run -test` →
`xray-client.json` → `config.yaml` with `USA = socks5 127.0.0.1:18080` → LaunchAgents written →
Xray agent restarted, wait 18080 → Mihomo restarted, wait 7890 → shell blocks, system proxy →
exit IP via 7890 == 149.28.240.154 → AI CLI setup.
Traffic: app → Mihomo 127.0.0.1:7890 → Xray socks 127.0.0.1:18080 → NL:<port> (VLESS+REALITY,
xhttp/tcp+vision/grpc) → USA.

Linux: unchanged except `NL_PORTS`.

## API, database, UI, or domain changes

- New `proxy.env` key `XRAY_CHAIN` (`1` default, `0` legacy), macOS only; accepted by `set-proxy-env.sh`.
- New optional first argument of `install.sh` on macOS (USA exit IP).
- New files on macOS: `~/.local/bin/xray`, `~/.config/mihomo/xray-client.json` (600),
  `~/.config/mihomo/xray.log`, `~/.config/mihomo/xray.pid` (nohup path only),
  `~/Library/LaunchAgents/com.mihomo.xray.plist`.
- New exit codes in `install.sh`: 8 (Xray install/config), 9 (Xray did not listen).
- No database, no server API.

## Validation and error-handling rules

- Python: unknown exit → existing message; port not in `NL_PORTS[exit]` → existing message format,
  now listing `2087/2088/2089/2090` for USA2.
- Bash: `nl_check_exit_port` messages above, exit 2. `chain_validate_settings` exit 2.
  Xray install/checksum/version/config-test failure exit 8. Xray not listening exit 9.
- Never print `UUID`, `PUBLIC_KEY`, `SHORT_ID` in error messages (only key names).
- `xray-client.json` contains secrets: mode 600, written via temp file + `mv`.

## Authorization and security considerations

- Xray binary integrity: pinned SHA-256 of the official zip; version string check before replace.
- JSON injection is prevented by the strict character-set validation before `printf` rendering.
- No secrets in logs, tests, or the spec. Tests use RFC 5737 / dummy values only.
- `unregister.sh` deletes only paths created by the installers.

## Backward-compatibility considerations

- USA1 2083-2086 and USA2 2087 behave exactly as before on Linux.
- macOS without an IP argument: no port check, old network inference, old `EXPECTED_EXIT_IP`;
  but the Xray chain is used (default `XRAY_CHAIN=1`). `XRAY_CHAIN=0` gives the old config byte-for-byte.
- `RU_*` / `CHAIN_MODE` unchanged: `RU-NODE` stays a direct Mihomo VLESS node.
- The Linux branches in the bash path stay dead code; nothing removed.

## Test strategy

Command (from repo root): `python3 -m unittest discover -s tests -v`
Plus: `bash -n install.sh tools/macos-chain.sh unregister.sh set-proxy-env.sh`
Plus, only if installed: `shellcheck install.sh tools/macos-chain.sh unregister.sh set-proxy-env.sh`
(report "shellcheck not installed" otherwise; do not install it).
Plus: `python3 -m py_compile tools/install-client.py`.

New file `tests/test_install_client.py` (load `tools/install-client.py` with
`importlib.util.spec_from_file_location('install_client', ...)`, same as the existing test;
import has no side effects). `BASE` env with dummy values like `tests/test_mihomo_config.py`.
Class `PortMapTests`:
- `test_usa2_accepts_all_nl_ports`: for 2087, 2088, 2089, 2090 (subTest) →
  `profile_from_settings(env, '149.28.240.154')['port'] == p`. Use `SERVER_NETWORK='tcp'` for 2088,
  `'grpc'` + `GRPC_SERVICE_NAME='grpc-test'` for 2089, `'xhttp'` otherwise.
- `test_usa1_accepts_all_nl_ports`: same for 2083-2086 with `'108.61.222.91'`.
- `test_usa2_rejects_usa1_port`: 2083 for USA2 → `RuntimeError`, message contains `2087/2088/2089/2090`.
- `test_usa1_rejects_usa2_port`: 2088 for USA1 → `RuntimeError`.
- `test_default_port_is_lowest`: no `SERVER_PORT` → USA2 2087, USA1 2083.

New file `tests/test_macos_chain.py`; helper
`run_bash(script, env=None)` = `subprocess.run(['bash', '-c', f'. "{ROOT}/tools/macos-chain.sh"; {script}'], env={**os.environ minus *_proxy, **env}, capture_output=True, text=True)`.
Classes and cases:
- `PortMapParityTests.test_bash_and_python_port_maps_match`: for each exit in Python `NL_PORTS`,
  `nl_allowed_ports <exit>` split to ints == sorted Python set; `nl_allowed_ports 192.0.2.1` returns 1.
- `PortCheckTests`: `nl_check_exit_port 149.28.240.154 2088|2089|2090` rc 0;
  `nl_check_exit_port 149.28.240.154 2083` rc 2 and stderr contains `2087/2088/2089/2090`;
  `nl_check_exit_port 192.0.2.1 2083` rc 2.
- `XrayJsonParityTests.test_matches_linux_xray_config` (subTest for xhttp/2087, tcp/2088,
  grpc/2089): `json.loads(stdout of render_xray_client_json)` == `install_client.xray_config(env,
  install_client.profile_from_settings(env, '149.28.240.154'))`, with explicit
  `REALITY_SERVER_NAME=dl.google.com`, `CLIENT_FINGERPRINT=firefox`, `XHTTP_PATH=/dl`, `XHTTP_MODE=auto`.
- `ValidationTests`: `UUID` containing `"` → rc 2, stderr `Invalid UUID`; `SERVER_NETWORK=ws` → rc 2;
  `SERVER_PORT=70000` → rc 2.
- `SocksBlockTests`: `yaml.safe_load('proxies:\n' + stdout)['proxies'][0]` ==
  `{'name':'USA','type':'socks5','server':'127.0.0.1','port':18080,'udp':True}`.
- `LaunchAgentTests`: `plistlib.loads(stdout.encode())` of
  `render_xray_launch_agent /u/.local/bin/xray /u/.config/mihomo/xray-client.json /u/.config/mihomo/xray.log`
  has `Label` `com.mihomo.xray`, `ProgramArguments` `[bin,'run','-config',cfg]`, `RunAtLoad` and
  `KeepAlive` True, both log paths == log.
- `AssetTests`: `xray_darwin_asset arm64` and `x86_64` print the exact asset + hash above;
  `xray_darwin_asset aarch64` rc 1; `chain_sha256` of a temp file containing `abc` ==
  `ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad`.
- `XrayBinaryValidationTests` (`skipUnless` `~/.local/bin/xray` or `XRAY_BIN` env is executable):
  for each mode, write the bash-rendered JSON to a temp file and run `xray run -test -config <file>`
  → rc 0.

M. Manual, user on a Mac only (not runnable here): `bash install.sh 149.28.240.154` with each of
2087/2088/2089/2090 (and the matching UUID/network), expect `Verified exit IP: 149.28.240.154`,
`launchctl print gui/$(id -u)/com.mihomo.xray` shows running; `XRAY_CHAIN=0` run restores direct mode;
`bash unregister.sh` removes both agents and `~/.local/bin/xray`.

## Acceptance criteria

1. `profile_from_settings(env, '149.28.240.154')` accepts 2087-2090 and rejects 2083; USA1 accepts
   2083-2086 and rejects 2087-2090.
2. `set-proxy-env.sh` usage lines read `SERVER_PORT=2083-2086|2087-2090`; `XRAY_CHAIN` is in `ALLOWED`.
3. Bash and Python port maps are identical (test).
4. Bash-rendered Xray JSON equals Python `xray_config()` for xhttp, tcp, grpc (test), and passes
   `xray run -test` when the binary is present.
5. Xray LaunchAgent plist parses and has the specified keys (test).
6. `install.sh` with `XRAY_CHAIN=0` produces the same `USA` VLESS block as before (review of diff).
7. `unregister.sh` handles xray unit/agent/pid/binary (review of diff).
8. `python3 -m unittest discover -s tests -v` passes (binary-dependent tests may skip with a reason);
   `bash -n` passes on all four shell files; shellcheck clean if installed.
9. Only the allowed files are changed.

## Rollback considerations

- Code: `git revert` of the change commit.
- macOS user without revert: set `XRAY_CHAIN=0` in `proxy.env` (or `bash set-proxy-env.sh ... XRAY_CHAIN=0`)
  and re-run `bash install.sh`: removes the Xray agent, Mihomo goes direct again.
- Full removal: `bash unregister.sh`.
- Linux: only the port map changed; reverting the constant restores old behaviour.

## Explicit list of files allowed to be modified

- `tools/install-client.py`
- `set-proxy-env.sh`
- `install.sh`
- `unregister.sh`
- `README.md`
- New: `tools/macos-chain.sh`
- New: `tests/test_install_client.py`
- New: `tests/test_macos_chain.py`
- This change's files under `openspec/changes/nl-usa2-ports-macos-xray-chain/` (checkboxes/notes only)

Forbidden: `proxy.env`, `.env*`, `servers/*`, `bin/*`, `tests/test_mihomo_config.py`,
`tools/mihomo-config.py`, any server-side script.

## Ordered implementation steps for the Implementer

1. Section A (`tools/install-client.py`). Run `python3 -m py_compile tools/install-client.py`.
2. Create `tests/test_install_client.py` (Test strategy). Run
   `python3 -m unittest tests.test_install_client -v` → all pass.
3. Section B (`set-proxy-env.sh`). Run `bash -n set-proxy-env.sh`.
4. Section C: create `tools/macos-chain.sh` exactly as specified.
5. Create `tests/test_macos_chain.py`. Run `python3 -m unittest tests.test_macos_chain -v` → all pass
   (the binary validation class may skip).
6. Section D (`install.sh`), steps D.1-D.14 in order. Run `bash -n install.sh`.
7. Section E (`unregister.sh`). Run `bash -n unregister.sh`.
8. Section F (`README.md`).
9. Run full checks: `python3 -m unittest discover -s tests -v`;
   `bash -n install.sh tools/macos-chain.sh unregister.sh set-proxy-env.sh`;
   `command -v shellcheck && shellcheck install.sh tools/macos-chain.sh unregister.sh set-proxy-env.sh`.
10. Do NOT run `install.sh` or `unregister.sh` on this machine (they change the live WSL setup).
11. Report the changed/new file list for the memory sync.

## Implementation status

Evidence: checks output (43 unit tests OK, `bash -n` OK, `py_compile` OK, shellcheck not installed and not run),
Reviewer `APPROVED`, Security reviewer `APPROVED` after one correction cycle, and a real `bash install.sh 149.28.240.154`
run on WSL that succeeded for all 8 inbounds (2083-2090), each with the exit IP verified. The final WSL state is NL:2087 → 149.28.240.154.

Acceptance criteria:
1. Met. Port tests for USA1 and USA2 pass (`tests/test_install_client.py`).
2. Met (review of diff): usage lines and `XRAY_CHAIN` in `ALLOWED`.
3. Met. `test_bash_and_python_port_maps_match` passes.
4. Partly met. The parity test passes. `xray run -test` on the bash-rendered JSON is not shown in the checks output, so it is not confirmed.
5. Met. The plist test passes.
6. Not proven by a run. Verified by review of the diff only.
7. Met (review of diff). Not run on this machine.
8. Partly met. Unit tests, `bash -n` and `py_compile` pass. shellcheck was not run.
9. Met (Reviewer scope check).

Not verified:
- A real macOS run (manual, the user on a Mac). Pending: `bash install.sh 149.28.240.154` for each of 2087-2090, `XRAY_CHAIN=0`, `bash unregister.sh`.
- The macOS LaunchAgent test in `launchctl print` proves that the job is loaded, not that the listener on 127.0.0.1:18080 is Xray.

Residual risks:
- R2: an existing `~/.local/bin/xray` without the kit marker is replaced on macOS.
- On Linux, `unregister.sh` without a marker still removes `~/.local/bin/xray`, as before.
- shellcheck was not run.
- Linux arm64 is not supported (non-goal, follow-up change).
