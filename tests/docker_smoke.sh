#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"; cd "$ROOT"
export KIT_UI_PORT=14050 KIT_PROXY_PORT=17890 KIT_IMAGE=mihomo-proxy-kit:smoke
T="$(mktemp -d)"; ssh-keygen -q -t ed25519 -N '' -f "$T/dummy_key"; export KIT_SSH_KEY="$T/dummy_key"
DC=(docker compose -p kitsmoke)
cleanup() { "${DC[@]}" down -v >/dev/null 2>&1 || true; docker image rm -f "$KIT_IMAGE" >/dev/null 2>&1 || true; rm -rf "$T"; }
trap cleanup EXIT
docker image rm -f "$KIT_IMAGE" >/dev/null 2>&1 || true
"${DC[@]}" up -d --build
sleep 6
"${DC[@]}" ps --format '{{.Service}} {{.State}}' | grep -q '^kit running'
"${DC[@]}" ps --format '{{.Service}} {{.State}}' | grep -q '^proxy running'
ss -ltn | grep -q '127.0.0.1:14050' && ! ss -ltn | grep -qE '(0\.0\.0\.0|\*|\[::\]):(14050|17890)'
code() { curl -s --noproxy '*' -o /dev/null -w '%{http_code}' "$@"; }
[ "$(code http://127.0.0.1:14050/)" = 200 ]
[ "$(code -H 'Host: evil.example:14050' http://127.0.0.1:14050/api/state)" = 403 ]
[ "$(code http://127.0.0.1:14050/api/state)" = 401 ]
URL="$("${DC[@]}" exec -T kit kit token)"
J="$T/jar"; [ "$(code -c "$J" "$URL")" = 303 ]
curl -s --noproxy '*' -b "$J" http://127.0.0.1:14050/api/state | python3 -c 'import json,sys; s=json.load(sys.stdin); assert s["proxy"]["state"]=="idle", s["proxy"]; assert s["nl_key_mounted"] is True'
"${DC[@]}" exec -T kit sh -c 'ps -o user,args | grep "[s]erver.py" | grep -q "^kit\|^10001"'
[ "$("${DC[@]}" exec -T proxy id -u)" = 10001 ]
ASSET="$(curl -s --noproxy '*' http://127.0.0.1:14050/ | grep -o '/assets/index-[A-Za-z0-9_-]*\.js' | head -n1)"
[ -n "$ASSET" ] && [ "$(code "http://127.0.0.1:14050$ASSET")" = 200 ]
C="$(docker create "$KIT_IMAGE")"; docker cp -q "$C:/app/web" "$T/dist"; docker rm "$C" >/dev/null
WEB_DIST="$T/dist" python3 -m unittest tests.test_web_contract
docker run --rm --entrypoint sh "$KIT_IMAGE" -c 'test ! -e /app/proxy.env && test ! -e /app/servers && test ! -e /app/ui/static && test ! -e /app/web/node_modules && ls /app' | grep -qx ui
# amendment 2d: volume split
# `! cmd` does not trip `set -e`, so negative checks use explicit `if … then exit 1`
if "${DC[@]}" exec -T proxy sh -c 'touch /kit-gen/x' 2>/dev/null; then echo "proxy can write /kit-gen" >&2; exit 1; fi
if "${DC[@]}" exec -T kit sh -c 'touch /kit-state/x' 2>/dev/null; then echo "kit can write /kit-state" >&2; exit 1; fi
"${DC[@]}" exec -T proxy sh -c 'test -f /kit-state/status.json && test -d /kit-state/logs && test -L /kit-state/mihomo/geosite.dat && test ! -e /run-kit'
"${DC[@]}" exec -T kit sh -c 'test -r /kit-state/status.json && test ! -e /run-kit'
docker volume ls --format '{{.Name}}' | grep -qx kitsmoke_kit-gen
docker volume ls --format '{{.Name}}' | grep -qx kitsmoke_kit-state
if docker volume ls --format '{{.Name}}' | grep -qx kitsmoke_kit-run; then echo "kit-run volume still created" >&2; exit 1; fi
curl -sI --noproxy '*' http://127.0.0.1:14050/ | tr -d '\r' | grep -qx "Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
echo "SMOKE OK"
