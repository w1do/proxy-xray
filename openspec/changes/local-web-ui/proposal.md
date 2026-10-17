# local-web-ui (revision 2: Docker-only)

> **Revision 2, 2026-10-16.** This revision replaces revision 1, the host `ui.sh` design that ran
> `install.sh` on the host. The user's new requirements:
> - The kit is Docker-only. `docker compose up -d` brings up the UI and the proxy.
> - Rules (sites) can be edited in the UI.
> - A server detail view shows copyable `vless://` links with QR codes.
> - The host install path is removed.
>
> Change `nl-usa2-ports-macos-xray-chain` (macOS host chain, USA2 ports) is **superseded**. Its
> reusable parts are carried over (see "MOVE / REPLACE"); its files are deleted in the REMOVE step.
>
> **Amendment 2a, 2026-10-16 (frontend only).** The user asked for a real React project, so the vendored
> React UMD + htm frontend is replaced. Changes:
> - New Vite + React 19 project in `web/`, written in plain JSX, with an exact-pinned `package.json` and a committed `package-lock.json`.
> - It is built in a pinned `node` Docker stage; the output `web/dist` is served by `ui/server.py`.
> - `ui/static/**`, the vendored JS files and their hash pins are dropped.
> - The API contract and the rules for the links endpoint are unchanged.

> **Amendment 2b, 2026-10-16 (frontend UI, user-approved shadcn/ui; correction cycle 1 adds the routing and NL-parser rules).**
> - Styling: Tailwind CSS v4 with the Vite plugin, and shadcn/ui-style components copied into the repo (hand-written
>   following the shadcn conventions; the shadcn CLI was not run, and no node_modules is committed). These are the only new dependencies:
>   - runtime: `@radix-ui/react-checkbox` 1.3.11, `@radix-ui/react-dialog` 1.1.23, `@radix-ui/react-label` 2.1.15,
>     `@radix-ui/react-select` 2.3.7, `@radix-ui/react-separator` 1.1.15, `@radix-ui/react-slot` 1.3.3,
>     `@radix-ui/react-switch` 1.3.7, `@radix-ui/react-tabs` 1.1.21, `@radix-ui/react-tooltip` 1.2.16,
>     `class-variance-authority` 0.7.1, `clsx` 2.1.1, `tailwind-merge` 3.7.0;
>   - dev: `tailwindcss` 4.3.3, `@tailwindcss/vite` 4.3.3.
>   All exact pins, each the newest stable release published before 2026-10-02 (two weeks before the change date). The existing pins are unchanged.
> - Files: `web/src/lib/utils.js` (`cn`) and `web/src/components/ui/{alert,badge,button,card,checkbox,dialog,input,label,select,separator,switch,table,tabs,tooltip}.jsx` (14 files).
> - `web/vite.config.js` adds the `@tailwindcss/vite` plugin. `web/src/app.css` starts with `@import "tailwindcss";` and defines the shadcn theme as CSS variables (light by default, dark via `prefers-color-scheme`).
> - `tests/test_web_contract.py`: the pinned dependency sets are updated to the pins above and the vite config check also requires `@tailwindcss/vite`. No check is weakened.
> - Code rule: `style={{ }}` stays forbidden and is not used. Radix sets its own positioning styles through the CSSOM, which the CSP allows.
> - CSP decision (resolved by amendment 2d-B): the Radix modal Dialog inserts a scroll-lock `<style>` through react-remove-scroll-bar.
>   This was refused under `style-src 'self'`. It is now allowed: the CSP has `style-src 'self' 'unsafe-inline'`, `script-src 'self'` is
>   unchanged, and body scroll is locked behind the modal. `Dialog modal={false}` is not used.
> - Routing (correction cycle 1): REMOTE_PARSE evaluates Xray routing rules in order and the first match wins. A rule matches a client
>   when it has no `user` list or the client's email is in it, AND it has no `inboundTag` list or the inbound tag is in it. Rules without
>   `outboundTag` (balancer rules) are skipped. No match gives an empty exit and exit_tag. The 443 installability block is unchanged.
>
> **Amendment 2c, 2026-10-16 (Opus escalation after correction cycle 2; security hardening of the shared `/run-kit` volume).**
> Threat model: `kit` and `proxy` run as the same uid 10001 and share `/run-kit` read-write. A compromised `proxy`
> (mihomo/xray RCE) can create, replace or remove any entry in `/run-kit`. The `kit` container holds the NL SSH key copy,
> `/data/ui-token` and the DB, so every `kit` read or write inside `/run-kit` treats the entries as hostile.
> Required changes (all are part of APPROVED; nothing below is optional):
> - **2c-1 (log reader).** `kit_apply.read_regular_tail(path, max_bytes=LOG_TAIL_BYTES)` with `LOG_TAIL_BYTES = 262144`:
>   `os.open(path, O_RDONLY|O_NOFOLLOW|O_NONBLOCK)`; missing → `None`; any other `OSError` → `RunFileError`;
>   `fstat` not `S_ISREG` or `st_nlink != 1` → `RunFileError`; if `st_size > max_bytes` seek to `st_size - max_bytes`;
>   `read(max_bytes)` (never more, even if the file grows). Returns `(data: bytes, truncated: bool)`.
>   `Api.proxy_logs` uses it; `None` or `RunFileError` → `lines = []`; when `truncated`, the first (partial) line is dropped;
>   then the last 200 lines, redacted as before. `Path.read_text` is not used on anything under `/run-kit`.
> - **2c-2 (directories).** `kit_apply.open_real_dir(path) -> int` (`ensure_real_dir(path)` then
>   `os.open(path, O_RDONLY|O_DIRECTORY|O_NOFOLLOW)`; `OSError` → `RunFileError`). `atomic_write` works only through that
>   directory fd: temp name `.tmp-<secrets.token_hex(8)>` created with `O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW` and `dir_fd`,
>   `os.fchmod(fd, mode)`, write, `os.fsync`, `os.replace(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)`; on any error the temp is
>   unlinked with `dir_fd` (ignore `FileNotFoundError`). No `mkdir(exist_ok=True)` and no path-based `os.chmod` remain in
>   `kit_apply.atomic_write`. In `kit_proxy.Supervisor.start`, `RUN/mihomo` and `RUN/logs` are created with a local
>   `ensure_real_dir` (same semantics; raises `OSError`), so a symlinked directory is refused, the status becomes
>   `failed` with error `Каталог /run-kit повреждён`, and the supervisor keeps running without children.
> - **2c-3 (child log file).** `Supervisor._log_file` uses `os.lstat` for the rotation size check, opens with
>   `O_CREAT|O_WRONLY|O_APPEND|O_NOFOLLOW|O_NONBLOCK`, checks `fstat` is `S_ISREG` (otherwise closes it and uses `/dev/null`),
>   and uses `os.fchmod(fd, 0o600)`. No path-based `os.chmod`.
> - **2c-4 (re-hash before every spawn).** `Supervisor._spawn(name, gen) -> bool` re-runs `file_sha256` on that child's config
>   (`xray-client.json` vs `gen['xray_sha256']`, `mihomo/config.yaml` vs `gen['mihomo_sha256']`) immediately before `Popen`, in
>   `_apply` and in the crash-restart path of `_watch_children`. On a mismatch it does not spawn and returns `False`; the caller
>   stops both children, sets `applied = wanted = None`, `state = 'failed'`,
>   `error = 'Файлы конфигурации не совпали с поколением'`. **Residual window (accepted):** the child opens its config after the
>   check (milliseconds), and mihomo keeps using its home dir (`RUN/mihomo`: cache, geo links) at runtime. This is a
>   consistency check against torn or stale files, not a privilege boundary: the only writers of `/run-kit` are `kit` (which
>   authors the configs anyway) and `proxy` (which would only be tampering with itself).
> - **2c-5 (login token not in container logs).** `server.main()` no longer prints the token. It prints
>   `Ссылка для входа: docker compose exec kit kit token` only. `kit token` is the only documented way to get the URL.
> - **2c-6 (`.gitignore`).** The four `servers/...` lines are replaced by `servers/*` and `!servers/README.md`.
> - **2c-7 (README).** The dedicated key is generated without a passphrase (`-N ''`), with the trade-off note.
> Deferred with recorded risk (owner decision, see "Known risks"): cookie scoping (session id). The `kit-run` mount split
> was deferred here and is now done by amendment 2d.

> **Amendment 2d, 2026-10-16 (owner decisions: (A) split the shared `kit-run` volume; (B) relax `style-src` for Radix).**
> Everything below is mandatory. Where an older section disagrees, 2d wins; the older sections are updated in place.
>
> **2d-A. Volume split.** `kit-run` (`/run-kit`, shared read-write) is replaced by two volumes:
>
> | Volume | Mount point | `kit` | `proxy` | Contents | Only writer |
> |---|---|---|---|---|---|
> | `kit-gen` | `/kit-gen` | rw | **ro** (`:ro`) | `generation.json`, `xray-client.json`, `mihomo/config.yaml`, `prev/xray-client.json`, `prev/mihomo-config.yaml` | `kit` |
> | `kit-state` | `/kit-state` | **ro** (`:ro`) | rw | `status.json`, `logs/xray.log`, `logs/xray.log.1`, `logs/mihomo.log`, `logs/mihomo.log.1`, `mihomo/` (mihomo home: `cache.db` + 3 geodata symlinks) | `proxy` |
>
> `kit` writes nothing to `kit-state` (its mount is read-only; Docker refuses writes with `EROFS`).
> `proxy` writes nothing to `kit-gen`.
> - Env vars: `KIT_RUN_DIR` is removed everywhere (code, Dockerfile, tests, README). It is replaced by `KIT_GEN_DIR` (default `/kit-gen`) and
>   `KIT_STATE_DIR` (default `/kit-state`). Python defaults: `os.environ.get('KIT_GEN_DIR', '/kit-gen')` and
>   `os.environ.get('KIT_STATE_DIR', '/kit-state')`.
> - **Child commands (exact):**
>   - xray: `[KIT_XRAY_BIN, 'run', '-config', '<KIT_GEN_DIR>/xray-client.json']`.
>   - mihomo: `[KIT_MIHOMO_BIN, '-d', '<KIT_STATE_DIR>/mihomo', '-f', '<KIT_GEN_DIR>/mihomo/config.yaml']`.
>   - `-d` is mihomo's home dir and `-f` is its config file (flags `d` and `f` in `main.go` of v1.19.32).
>   - In the container, mihomo's home and config path come only from these flags. `CLASH_HOME_DIR` and `CLASH_CONFIG_FILE`
>     are not set, and `_child_env()` keeps passing the env through unchanged except for `*_proxy`.
> - **What mihomo v1.19.32 writes into `-d`.** Sources: the v1.19.32 code (`main.go`, `config/initial.go`, `constant/path.go`,
>   `component/profile/cachefile/cache.go`, `config/config.go`) and the MetaCubeX wiki (Context7 `/websites/wiki_metacubex_one_en`).
>   A probe on 2026-10-17 confirmed the list: mihomo v1.19.32 and xray 26.10.10 from the local kit image, uid 10001, `read_only`,
>   `cap_drop: ALL`, the gen volume mounted `:ro`.
>   1. `config.Init(homeDir)` runs `MkdirAll(homeDir)`. The dir already exists, so nothing is created. It writes a default
>      `mixed-port: 7890` file only when the `-f` file is missing; the supervisor spawns only after the hash check, so the file is always present.
>   2. `cache.db` (bbolt, `<home>/cache.db`) is created on first use, because `profile.store-selected` defaults to `true`. The process
>      umask is 077, so its mode is 0600. If it cannot be opened, mihomo logs `[CacheFile] can't open cache file` and keeps running.
>   3. Geodata is read from `<home>`: `geoip.metadb` (MMDB, `geodata-mode` false), `geosite.dat`, and `geoip.dat` (only when `geodata-mode` is true).
>      mihomo downloads a missing geodata file into `<home>` only when a rule needs it and the file is absent. The 3 symlinks to
>      `/opt/kit/geo` are always present, and `geo-auto-update` defaults to `false`, so no download happens.
>   4. Nothing else is written. The kit config has no `proxy-providers`, `rule-providers`, `external-ui` or `external-controller`, so there
>      are no provider files, UI dir or `SAFE_PATHS` needs. The new `test_kit_render` assertion below enforces this.
>   Probe result: after mihomo ran with GEOIP and GEOSITE rules, `<home>` held exactly `cache.db` (0600) plus the 3 symlinks, and the
>   `-f` dir was unchanged.
>   Paths `proxy` may write: `/kit-state/status.json`, `/kit-state/.status.json.tmp` (current `write_status` temp name, unchanged),
>   `/kit-state/logs/{xray,mihomo}.log{,.1}`, `/kit-state/mihomo/{cache.db,geoip.dat,geoip.metadb,geosite.dat}`, and `/tmp` (tmpfs).
>   That is exactly the rw mount plus tmpfs.
> - **What xray 26.10.10 writes.** Nothing. `xray_client_config` sets only `log.loglevel` (no `log.access` or `log.error` file), and it has no routing,
>   so no geo assets are loaded. The probe ran `xray run -config /kit-gen/xray-client.json` on the `:ro` mount, and xray started with no file writes.
>   The new `test_kit_render` assertion keeps `log` equal to `{'loglevel': 'warning'}`.
> - **Ownership.** The Dockerfile creates `/kit-gen` and `/kit-state` owned by `10001:10001` with mode 0700. On first mount, Docker copies the image
>   dir's owner and mode into an empty named volume. The probe showed this works when the `:ro` mount comes up first (kit) and the
>   rw mount later (proxy), and the reverse. `kit_priv.prepare_and_drop` chowns only `KIT_GEN_DIR` (as before for the run dir) and never
>   touches `KIT_STATE_DIR` (read-only for kit).
> - **kit reads of `kit-state` (hostile input, 2c readers kept).** New `kit_apply.open_state_dir(sub=None) -> int|None`:
>   - Opens `state_dir()` with `O_RDONLY|O_DIRECTORY|O_NOFOLLOW`.
>   - If `sub` is given, opens `sub` relative to that fd (`dir_fd`) with the same flags and closes the parent fd.
>   - Missing at any step → `None`. Any other `OSError` → `RunFileError`. It never creates anything.
>   - `read_regular_bytes(path, dir_fd=None)` and `read_regular_tail(path, max_bytes=LOG_TAIL_BYTES, dir_fd=None)` get a keyword
>     `dir_fd`, passed to `os.open`. With a `dir_fd`, `path` is a bare file name.
>   - `read_status()` opens `open_state_dir()` and reads `status.json` with `dir_fd`.
>   - `Api.proxy_logs` opens `open_state_dir('logs')` and reads `<name>.log` with `dir_fd`.
>   - `None` or `RunFileError` → no status / `lines = []`. The fds are always closed (`try/finally`).
>   - A symlinked `logs` directory is now refused too (2c only refused a symlinked final component).
> - **kit writes of `kit-gen`.** These are unchanged (2c-2 directory-fd `atomic_write`). They now target `gen_dir()`. `proxy` can no longer plant
>   entries there, so the fd checks stay as defense in depth.
> - **proxy (`kit_proxy.Supervisor`).** Two attributes replace `self.run_dir`: `self.gen_dir` and `self.state_dir`. The proxy only reads
>   `gen_dir` (`generation.json`, the two configs, with the existing `O_NOFOLLOW` readers) and never creates or modifies anything under it.
>   `start()` runs `ensure_real_dir` on `state_dir`, `state_dir/'mihomo'` and `state_dir/'logs'`, and makes the geo symlinks in
>   `state_dir/'mihomo'`. On `OSError` the state is `failed` with error `Каталог /kit-state повреждён`. `status_path` = `state_dir/'status.json'`.
>   `_log_file` uses `state_dir/'logs'`. `_config_path` uses `gen_dir`.
> - **No prior generation.** This covers a fresh install and the state right after migration. `kit` starts normally: `write_bundle` creates
>   `gen_dir/mihomo` and `gen_dir/prev` with `ensure_real_dir` on first install, and `read_generation_file()` returns `None` → generation 1.
>   `proxy` sees no `generation.json` and stays `idle`. `apply_rules` with an active inbound but no `xray-client.json` already returns
>   `('ok', None, 'Правила сохранены; будут применены при установке')`. This is unchanged and now covered by a test.
> - **2c re-read.** In 2c, `/run-kit` means: configs, generation and `prev/` → `/kit-gen`; status, logs and mihomo home → `/kit-state`.
>   2c-4's residual window stays. It is now a check against a torn or stale write by `kit` only, because `proxy` cannot write the configs.
> - **Migration (owner steps).** The old `kit-run` volume holds only rebuildable data, so it is not migrated. Its generations are rewritten by the
>   next install or apply. Steps:
>   1. `docker compose down` (WITHOUT `-v`; `-v` would also delete `kit-data`: DB, token, known_hosts).
>   2. `docker compose up -d --build`. This creates `mihomo-proxy-kit_kit-gen` and `mihomo-proxy-kit_kit-state`.
>   3. In the UI, press «Установить» again on the inbound that was active. Until then `proxy` is `idle` and 7890 is closed. The DB, rules,
>      token and host keys are kept.
>   4. Delete the old volume: `docker volume rm mihomo-proxy-kit_kit-run`. If the project was started with `-p <name>`, the volume is
>      `<name>_kit-run`.
>
> **2d-B. CSP: `style-src 'self' 'unsafe-inline'` (owner decision; `script-src 'self'` unchanged).**
> The exact header (the only allowed value, in `kit_guard.SECURITY_HEADERS['Content-Security-Policy']`):
> `default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`
> - Reason: the Radix modal `Dialog` scroll lock uses `react-remove-scroll-bar`, which inserts a `<style>` element at runtime. With
>   `style-src 'self'` the browser refuses it, and body scroll is not locked behind the modal.
> - Rejected alternatives:
>   - `Dialog modal={false}`: drops the modal focus trap and outside-pointer blocking, which is an accessibility regression.
>   - A hash: the injected CSS text depends on the computed scrollbar width and gap mode, so it is not stable and cannot be pinned.
>   - A nonce: the server would have to template a fresh nonce into every `index.html` response and into the CSP header, and the static map
>     serves fixed bytes by design. The app would also have to read the nonce back from the DOM and hand it to the library's
>     style-singleton through a global setter before the first render.
>     That adds per-response templating and global mutable state to work around one third-party `<style>`, so it is rejected.
>   - Neither a hash nor a nonce fits a library-injected element. The `<style>` text is generated at runtime, and the nonce would need server-side
>     templating that this design does not have.
> - Residual risk:
>   - `'unsafe-inline'` in `style-src` allows inline `<style>` elements and `style` attributes. It cannot run script, because `script-src 'self'` stays,
>     with no `'unsafe-inline'` or `'unsafe-eval'`.
>   - The worst case of an injected stylesheet is CSS-selector-based exfiltration (attribute selectors + `url()`), and it is blocked here: `img-src 'self' data:`,
>     `default-src 'none'` (fonts and other fetches blocked) and `connect-src 'self'` give no third-party sink.
>   - The app renders no user-supplied HTML or style: no `innerHTML` or `dangerouslySetInnerHTML`, and `style={{` is banned by `test_web_contract`.
>   - The other directives are unchanged.
> - The 2b code rule stays: `style={{ }}` is forbidden in `web/src`, and `web/index.html` and the built `index.html` still contain no `<style>`.
>   The relaxation exists only for the library's runtime element.

> **Amendment 2e, 2026-10-17 (owner request: import-only mode for a user without NL access).**
> Scenario: a friend runs the kit without SSH access to NL. The owner gives him `vless://` links (made by `kit_nl.make_link`). He pastes them,
> opens a server and presses «Установить». There is no SSH key, no NL settings and no host-key step. Everything below is mandatory; defaults
> for the 2e open questions are at the end of this block and apply unless the owner overrides them.
>
> **2e-1. Compose: the SSH key is optional.**
> - `services.kit.volumes` key bind: `source: ${KIT_SSH_KEY:-./docker/no-key}` replaces `${KIT_SSH_KEY:-${HOME}/.ssh/id_ed25519}`. The rest is
>   unchanged: `type: bind`, `target: /run/secrets/nl_ssh_key`, `read_only: true`, `bind.create_host_path: false`.
> - New committed file `docker/no-key`: empty (0 bytes). Set `chmod 0600` in the working tree. Git records only 100644, which is harmless for an
>   empty file. `.dockerignore` already keeps `docker/` out of the image. `git check-ignore docker/no-key` must print nothing.
> - With no `.env` and no `KIT_SSH_KEY`, `docker compose up -d --build` works: the bind source exists, so `create_host_path: false` is satisfied.
> - The owner sets `KIT_SSH_KEY=/home/<user>/.ssh/<key>` in `.env` (documented in `docker/env.example` and the README) to use discovery.
>   This is a behaviour change: the old default `~/.ssh/id_ed25519` is no longer mounted implicitly (open question 2e-Q1).
> - Interaction with 2d: none. The key bind is on `kit` only; `proxy` still gets no key, and the `kit-gen` / `kit-state` mounts and modes are unchanged.
>   Imported rows live in the `kit-data` DB like discovered rows, and an install writes `kit-gen` exactly as before.
> - "Key available" now means a regular, non-empty file:
>   - `kit_priv.prepare_and_drop` copies the mount only when `os.path.getsize(mount) > 0`. An empty placeholder is not copied, so
>     `/tmp/kit-ssh/id_nl` does not exist.
>   - New `kit_discovery.key_available(path=None) -> bool` = `os.path.isfile(p) and os.path.getsize(p) > 0` with `p = path or paths()[1]`.
>     `OSError` → `False`. `state_payload`'s `nl_key_mounted` and `server._nl_key_mounted()` use it.
>   - `Api.discover` returns 400 `SSH-ключ не подключён: задайте KIT_SSH_KEY и перезапустите контейнеры` when `key_available()` is false,
>     checked before the NL-settings check.
>
> **2e-2. Backend: `POST /api/inbounds/import`.**
> - Body `{"links": [str, …]}`. The global 16 KiB body limit stays and applies.
>   - `links` must be a list of 1..`MAX_IMPORT_LINKS` = 40 strings.
>   - Each string is stripped and must be 1..`MAX_LINK_LEN` = 1024 chars, ASCII-printable only (`0x21..0x7e`, no spaces or control chars).
>   - Violations → 400 with no per-link list: `Нет ссылок` / `Не больше 40 ссылок` / `Ссылка N: слишком длинная или недопустимые символы`.
> - Guarded like every API call: session, Origin, `Content-Type: application/json`. Route:
>   `('POST', re.compile(r'/api/inbounds/import'), lambda api, m, b, q: api.import_links(b))`. Place it BEFORE the `INBOUND_RE` route
>   (`INBOUND_RE` cannot match `import`, but keep the order explicit).
> - A running job → 409 `Уже выполняется другая операция`, and nothing is stored.
> - New module `ui/kit_import.py` (stdlib + `kit_render`, `kit_nl`; no `subprocess`, no I/O). `parse_link(text) -> dict` raises `ValueError` with a
>   Russian message that never contains any part of the link. Rules, in this order:
>   1. `urllib.parse.urlsplit(text)`: scheme `vless`. The netloc has a username (the uuid), no password, a hostname and an explicit port.
>      There is no path (or `''`).
>   2. uuid: lowercased, `kit_render.UUID_RE` = `[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}`.
>   3. host: `kit_render.HOST_IPV4_RE` = `(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}` or lowercase
>      `kit_render.DOMAIN_RE` (≤253 chars, must contain a dot). An IPv6 or bracketed host is rejected.
>   4. port: int 1..65535, and not in `kit_nl.SKIP_PORTS` (443 → `порт 443 не устанавливается`).
>   5. query: `parse_qs(query, keep_blank_values=True, strict_parsing=True)`. Each key appears at most once. Allowed keys exactly:
>      `encryption, security, type, sni, fp, pbk, sid, flow, headerType, path, mode, host, serviceName`. Any other key → `неизвестный параметр`.
>      - `encryption` is absent or `none`. `security` is `reality` (required).
>      - `type` ∈ `tcp|grpc|xhttp` (required).
>      - `sni`: required, lowercase `DOMAIN_RE`, ≤253.
>      - `fp`: optional, ∈ `kit_render.FINGERPRINTS` = (`chrome`,`firefox`,`safari`,`ios`,`android`,`edge`,`360`,`qq`,`random`,`randomized`).
>        It is validated only and not stored; the render uses `firefox` as for discovered rows (2e-Q4).
>      - `pbk`: required, `kit_render.PBK_RE` = `[A-Za-z0-9_-]{43}`.
>      - `sid`: required (may be empty), lowercased, `kit_render.SID_RE` = `(?:[0-9a-f]{2}){0,8}`.
>      - `tcp`: `flow` ∈ {absent, `''`, `xtls-rprx-vision`}; `headerType` absent or `none`; `path`, `mode`, `host` and `serviceName` absent.
>      - `xhttp`: `path` required, `kit_render.XHTTP_PATH_RE` = `/[A-Za-z0-9._~/-]{0,255}`. `mode` optional ∈ `kit_render.XHTTP_MODES` =
>        (`auto`,`packet-up`,`stream-up`,`stream-one`), default `auto`. `host` optional, lowercase `DOMAIN_RE`. `flow`, `headerType` and `serviceName` absent.
>      - `grpc`: `serviceName` required, `kit_render.GRPC_SERVICE_RE` = `[A-Za-z0-9._/-]{1,128}`. `mode` optional ∈ `gun|multi`, default `gun`.
>        `flow`, `headerType`, `path` and `host` absent.
>   6. fragment (label): `urllib.parse.unquote(fragment, errors='strict')` must fullmatch
>      `kit_import.LABEL_RE` = `NL -> (?P<exit>\S+) (?P<mode>XHTTP|TCP|gRPC)(?: (?P<remark>[^\x00-\x1f\x7f]{1,64}))?`.
>      - `exit` must fullmatch `HOST_IPV4_RE`; otherwise `в подписи нет IP выхода`.
>      - `mode` must equal `kit_nl.MODE_NAME[type]`; otherwise `подпись не совпадает с типом`.
>      - A missing or non-matching label → `в подписи нет IP выхода`.
>      - This is exactly the format of `kit_nl.make_link`: `NL -> <exit> <MODE> <email>`.
>   Output row (the `inbounds` columns):
>   - `port`, `uuid`, `exit_ip` = exit, `exit_tag` = `''`, `network` = type, `remark` = remark or `''`, `flow` (tcp only, else `''`), `pbk`, `sid`, `sni`.
>   - `xhttp_json` = `json.dumps({'path', 'mode'[, 'host']}, sort_keys=True)` for xhttp, else `'{}'`.
>   - `grpc_service` (grpc, else `''`), `grpc_multi` = 1 iff mode `multi`.
>   - `source` = `'import'`, `nl_host` = host.
>   `parse_links(links) -> (rows, errors)`:
>   - `errors` = `[{'index': i (1-based), 'error': msg}]`.
>   - A second link with the same `(port, uuid)` → `дубликат`.
> - `Api.import_links(body)`: validate the body (caps above) → `parse_links`. If there are any errors → 400
>   `{"error": "Ссылки не импортированы", "errors": [...]}` and nothing is stored (all-or-nothing, 2e-Q2). Otherwise
>   `kit_db.replace_imported(conn, rows)`. A `kit_db.ImportConflict(index)` → 400 with
>   `errors: [{index, error: 'такой вход уже обнаружен через NL'}]`.
>   200 `{"imported": n, "removed": k, "items": [{"index", "port", "network", "exit_ip", "remark"}]}`.
>   The response never contains the uuid, pbk, sid, sni, host or link.
> - `ApiError(status, message, extra=None)`. The dispatcher sends `{'error': message, **(extra or {})}`. `extra` is used only by `import_links`.
> - Logging: the access log already prints only method, path and status. `import_links` writes nothing to job logs or stdout. The error messages
>   never echo input.
> - DB (`kit_db`): `SCHEMA_VERSION = 2` and `MIGRATIONS = [V1_SQL, V2_SQL]`, where
>   `V2_SQL = "ALTER TABLE inbounds ADD COLUMN source TEXT NOT NULL DEFAULT 'discover' CHECK (source IN ('discover','import'));\nALTER TABLE inbounds ADD COLUMN nl_host TEXT NOT NULL DEFAULT '';"`.
>   Existing rows become `source='discover'`, `nl_host=''`.
>   - `class ImportConflict(ValueError)` with attribute `index`.
>   - `replace_imported(conn, rows) -> {'total': n, 'removed': k}`, all in one `with conn:` transaction, deterministic:
>     1. For each row in order: if a row with the same `(port, uuid)` has `source='discover'` → raise `ImportConflict(i)` (1-based). The
>        transaction rolls back.
>     2. Delete `source='import'` rows whose `(port, uuid)` is not in the new set. `removed` = their count. `active.inbound_id` becomes NULL through the
>        FK if the active row is among them; the running proxy keeps its generation.
>     3. Upsert each new row: `INSERT … ON CONFLICT(port, uuid) DO UPDATE SET` every link-derived column, `source='import'`, `nl_host`,
>        `present=1`, `discovered_at`. Ids and `check_*` of re-imported rows are kept.
>   - `upsert_inbounds` (discovery): `UPDATE inbounds SET present = 0 WHERE source = 'discover'` (imported rows are never hidden by
>     discovery). The ON CONFLICT clause also sets `source='discover', nl_host=''`, so a discovered row wins over an imported duplicate.
>   - `PUBLIC_INBOUND_KEYS` and `public_inbound` add `source` (`'discover'|'import'`). `nl_host` is never public.
>
> **2e-3. Install, check, rules and links for imported rows: no SSH, no NL settings.**
> - `kit_discovery.row_nl_host(row, nl) -> str|None`: `row['nl_host']` when `row['source'] == 'import'`, else `nl['host']` if `nl`, else `None`.
> - `kit_apply.install(job, nl_host, row)` (was `nl`) uses `xray_client_config(nl_host, row)`. `kit_jobs.install_job(job, nl_host, row)`.
> - `Api.install`: load the row and keep the 404 and installable checks. Then `host = row_nl_host(row, kit_db.get_nl(conn))`; `None` → 400
>   `Сначала укажите настройки NL`. Start `install_job(job, host, row)`. There is no host-key or key check here; there never was one for install.
> - `kit_jobs.check_job(job, nl, ids)`: uses `kit_discovery.row_nl_host(row, nl)` per row. `None` → that row fails with `Не заданы настройки NL`.
>   `nl` may be `None`. `Api.check_one` and `Api.check_all` no longer call `_nl_or_400`; they pass `kit_db.get_nl(conn)`. `check_one` returns 400
>   `Сначала укажите настройки NL` for a discovered row when NL is not set.
>   The check runs a local xray (`kit_nl.check`) and never uses SSH.
> - `Api.put_rules`: drop the `_nl_or_400` call, so rules apply with an imported active inbound and no NL settings. Pass `None` to
>   `apply_rules_job` (`kit_apply.apply_rules` never reads `nl`; it reuses the current `xray-client.json`).
> - `Api.exit_links` / `kit_discovery.links_for_exit(conn, nl, exit_ip)` (was `nl_host`): each row uses `row_nl_host(row, nl)`, and rows with `None` are
>   skipped. If the exit has rows but none has a host → 400 `Сначала укажите настройки NL`. `_nl_or_400` is removed from `exit_links`.
> - `kit_render`: add the constants named in 2e-2. `xray_client_config` also checks `UUID_RE.fullmatch(uuid)`, `PBK_RE.fullmatch(pbk)`,
>   `SID_RE.fullmatch(sid)` and `DOMAIN_RE.fullmatch(sni.lower())`, and for xhttp `XHTTP_PATH_RE.fullmatch(path)` when present. A failure →
>   `ValueError('Недопустимые параметры входа')`. This is defense in depth for both sources.
> - The import, install, check, rules and links paths call no `ssh`, `ssh-keyscan` or `ssh-keygen`. Only `discover`, `hostkey/scan` and `hostkey/accept` do.
>
> **2e-4. UI.**
> - New `web/src/components/ImportLinks.jsx` (shadcn `Card`, `Button`, `Alert`, `Label`; a plain `<textarea>` with Tailwind classes, no
>   `style={{`). It has the title «Импорт ссылок», the hint «По одной ссылке vless:// в строке. Ссылки хранятся только в этой панели», and the
>   button «Импортировать».
>   - Submit: split on `\n`, trim, drop empty lines. More than 40 → local error `Не больше 40 ссылок`. Then
>     `api('POST', '/api/inbounds/import', {links})`.
>   - On 200: clear the textarea, show `Импортировано: N` (and `, удалено: K` when K > 0), and call `onImported()` (= `refresh`).
>   - On `ApiError`: keep the text and show `err.message` plus, from `err.data.errors`, one line per item `Строка {index}: {error}`.
>   - Disabled while `busy`. Links are never put in web storage, URLs or logs. React state holds them only until success.
> - `web/src/api.js`: `ApiError(status, message, data)` sets `this.data = data`. `api()` passes the parsed body.
> - `App.jsx`:
>   - `state.nl_key_mounted === false`: render `<ImportLinks busy={jobRunning} onImported={refresh} />` in place of `<NlSettings …/>`. NL settings,
>     the host-key dialog and «Обнаружить» are hidden.
>   - `true`: render `<NlSettings …/>` as now, then a secondary `Button variant="outline"` «Импорт ссылок» that toggles the same `<ImportLinks …/>` below it.
> - Imported servers appear in the same `ExitList` / `ServerView`, with the same «Проверить», «Установить» and links buttons.
>   `ServerView` shows a `Badge` «импорт» for inbounds with `source === 'import'`.
>
> **2e-5. Security.**
> - The imported links are secrets: each one is a full VLESS client credential (uuid, pbk, sid). They are stored in the friend's `kit-data` DB
>   (`/data/kit.db`, 0600, uid 10001) like discovered rows. They reach the browser only through the existing links endpoint; `/api/state` and
>   every other response stay secret-free, and job logs redact them (`job.redactor.add` in install/check as today).
> - A friend's instance can use the links only as a VPN client of NL (VLESS+REALITY to the given port): exactly what the owner granted by
>   sharing them. They give no SSH, no 3x-ui panel and no NL admin access, and the friend's kit never contacts NL over SSH.
>   Revocation is the owner's job on NL: delete or rotate that client's uuid in 3x-ui. The friend's install then fails `verify_exit` and rolls back.
> - Anyone who can open the friend's UI (token holder) can read the links through the links endpoint. That is the same exposure as for the owner's
>   discovered links.
> - Parser hardening: strict allowlists and caps; all-or-nothing writes; no echo of input in errors; the render re-validates (2e-3).
>
> **2e open questions (defaults applied unless the owner says otherwise):**
> - 2e-Q1: the default key source becomes `./docker/no-key`. The owner must set `KIT_SSH_KEY` in `.env` for discovery. Default: yes; the README
>   migration note says so.
> - 2e-Q2: an import with any bad link stores nothing (all-or-nothing). Default: yes.
> - 2e-Q3: unknown query parameters (e.g. `spx` from other clients) are rejected. Default: reject (the owner's links never contain them).
> - 2e-Q4: the link's `fp` is validated but not used; the render keeps `firefox` like discovered rows. Default: yes.
> - 2e-Q5: port-443 links are rejected at import (they are not installable anyway). Default: yes.

> Amendment 2a also fixes:
> - **Compose build collision.** Only `kit` has `build:`; `proxy` reuses the image with `pull_policy: never`.
> - **README admin lines.** Lines about scripts that do not exist in this repo are dropped.
> - **Step-14 reference grep.** It now has an exact command and an allowlist.

## Open questions (defaults below are applied unless the user overrides)

1. **REMOVE list approval (REQUIRED before step 14).** The files listed in "REMOVE" are deleted
   only after the user says yes. Default: none are deleted until the yes is given. If the answer is no, step 14 is
   skipped and everything else still ships.
2. **Uncommitted work of the superseded change** (`install.sh`, `set-proxy-env.sh`, `unregister.sh`,
   `tools/install-client.py`, `README.md`, `tools/macos-chain.sh`, `tests/test_install_client.py`,
   `tests/test_macos_chain.py`). Default: the orchestrator or the user commits it once, as is, with the message
   `Host installer: USA2 ports + macOS chain (superseded by Docker)` BEFORE step 14. History then
   keeps a working host installer for rollback. The alternative is to discard it.
3. **NL host key trust.** Default: the UI runs `ssh-keyscan`, shows the SHA256 fingerprints, and the user
   confirms. Only the confirmed keys are written to `known_hosts` in the data volume. SSH always
   runs with `StrictHostKeyChecking=yes`. The alternative is `accept-new` (no confirmation).
4. **Host-side proxy settings** (shell `http_proxy` block, macOS system proxy). Default: these are not managed
   by the kit. The README gives the env lines and the macOS `networksetup` commands. The existing shell blocks
   written by the old installer keep working because they point to `127.0.0.1:7890`.
   `setup-ai-cli-proxy.sh` stays.
5. **QR codes.** Default: included, using npm `qrcode-generator` 2.0.4 (exact pin, no dependencies, MIT). Say no to drop it.
6. **Admin tools config.** Default: `proxy` / `tools/proxy_cli.py` keep reading `proxy.env`, which becomes an
   admin-only file with the keys `SERVER_IP`, `SSH_TUNNEL_NL`, `SSH_TUNNEL_SERVER`, `SSH_TUNNEL_SERVER_2`.
   `proxy.env.example` is rewritten to those keys only.
7. **Image distribution.** Default: the image is built locally by `docker compose up -d --build`. It is not pushed to a registry.
8. **UDP through the published port.** Default: TCP only (HTTP and SOCKS5 CONNECT). SOCKS5 UDP ASSOCIATE through
   Docker port publishing is not supported.
9. **Frontend toolchain versions (amendment 2a).** Default: React/ReactDOM 19.3.0, Vite 8.3.2,
   `@vitejs/plugin-react` 6.1.1, qrcode-generator 2.0.4, Node `24.21.0-alpine3.23`. Each is the newest release that
   is at least 2 weeks old.
   - React 19.3.1 (2026-10-14) changes only the React Server Components transport, which this SPA does not use.
   - Node 24.22.0 (2026-10-14) is newer than 2 weeks.
   - Say so if you want either of them now; otherwise they are bumped in a later change.
10. **JavaScript or TypeScript (amendment 2a).** Default: plain JavaScript + JSX. It needs no `tsc` or type packages, gives
    the smallest toolchain, and the repo has no TS elsewhere. Say so to use TypeScript (adds `typescript` and
    `@types/react*` dev dependencies and a type-check step).

## Problem statement

The current client install runs on the host: `vless.sh` writes `servers/*.txt` with command lines that contain secrets,
then `set-proxy-env.sh` and `install.sh` run on the host, with systemd units on Linux and LaunchAgents on macOS.
There are two platform code paths (Python on Linux, bash on macOS) and committed binaries in `bin/`.
The user wants:
- one `docker compose up -d` that always runs;
- a UI on `127.0.0.1:4050` where they enter the NL settings once, see the exits and inbounds, check them, and install one with a click;
- editable site rules;
- copyable `vless://` links for phone clients (INCY etc.);
- a local proxy on `127.0.0.1:7890`;
- no host install path.

## Goals and non-goals

Goals:
- Two services from one image: `kit` (UI, API, discovery, checks, rendering) and `proxy` (supervises
  Mihomo :7890 → Xray :18080 → NL:<port>). Both use `restart: unless-stopped`.
- Published ports go only to the host loopback: UI `127.0.0.1:${KIT_UI_PORT:-4050}`, proxy `127.0.0.1:${KIT_PROXY_PORT:-7890}`.
- The image is built for linux/amd64 or linux/arm64, whichever the build host is. Mihomo v1.19.32 and Xray 26.10.10 are
  downloaded from the official releases at build time and SHA-256 verified for each arch. Geodata is copied from
  the digest-pinned `metacubex/mihomo:v1.19.32` image and SHA-256 verified.
- SQLite (named volume) stores the NL settings, discovered inbounds, check results, jobs, rules, the match policy and the active selection.
- Install means: render the Xray JSON and Mihomo YAML, validate them (`xray run -test`, `mihomo -t`), hand them to
  the proxy container through the shared volume, wait for it to apply them, verify the exit IP through the proxy, and roll back on failure.
- Rules editor (DOMAIN, DOMAIN-SUFFIX, DOMAIN-KEYWORD, GEOSITE, GEOIP, IP-CIDR → PROXY, DIRECT or REJECT, plus MATCH)
  with defaults taken from the current `tools/mihomo-config.py` rules.
- Server view with `vless://` links and QR codes, from a dedicated endpoint fetched on demand.
- No Docker socket, no privileged mode, non-root runtime, a read-only root filesystem, no secrets in image layers.
- In-container CLI `kit`: `docker compose exec kit kit token|rotate-token|status|discover|check`.

Non-goals:
- No host install path, no systemd, LaunchAgents or cron, no macOS system proxy management.
- No server-side (NL/USA) changes. No 3x-ui API, no client creation.
- No registry publishing, no cross-arch build on this machine (it has no buildx/binfmt).
- No HTTPS and no remote access to the UI.
- No UDP through the published proxy port.

## Current architecture analysis

- `tools/export-vless.py` (working tree, partial section-A refactor done): `load_env`, `ENV`, `REMOTE_PARSE`
  (`rows_from_config(c, derive_pub)`), `REMOTE_DRIVER`, `REMOTE`, `EXIT_PORTS`, `SKIP_PORTS={443}`, `MODE_NAME`,
  `DiscoveryError(returncode, stderr)`, `ssh_command(target, ssh_port, key_path)`, `discover_rows(...)`,
  `ssh_rows`, `make_link(row, server_ip)` (fp `chrome`), `make_install_command`, `make_block`,
  `check(row, server_ip, xray_bin, socks_port)` (temporary Xray + curl to ipify via socks5h), `main` (CLI only).
- `tools/install-client.py`: `xray_config(env, row)` is the client Xray JSON that has been verified against NL
  (socks 127.0.0.1:18080 udp, VLESS + REALITY, `flow` only for tcp, `xhttpSettings {path, mode}` only for xhttp,
  `grpcSettings` only for grpc, fingerprint default `firefox`). It also has `NL_PORTS`, binary install, systemd units and
  `configure_shell`.
- `tools/mihomo-config.py`: `render(env)` holds the DNS block (fake-ip, DoH, `respect-rules`) and the rules list:
  `openai.com, chatgpt.com, anthropic.com, claude.ai, telegram.org, t.me → PROXY; GEOIP PRIVATE DIRECT
  no-resolve; local, localhost DIRECT; GEOSITE category-ru DIRECT; ru DIRECT; GEOIP RU DIRECT; MATCH PROXY`.
  `tools/install-client.py` `mihomo_config()` also has `рф → DIRECT`.
- `migrate-docker.md`: confirms that `metacubex/mihomo` ships `geoip.dat`, `geosite.dat` and `geoip.metadb`, and that a published
  port needs `allow-lan: true` + `bind-address: "*"` (Mihomo binds 127.0.0.1 otherwise). It also says to publish loopback only and to
  disable host supervisors so that two Mihomo instances do not fight over 7890.
- Partial UI implementation (uncommitted, revision 1): `ui/kit_db.py`, `ui/kit_guard.py`,
  `ui/kit_discovery.py`, `ui/kit_jobs.py`, `tests/fixtures/ui/xui_config.json` (inbounds 443 tcp, 2083 xhttp,
  2087 xhttp, 2088 tcp, 2089 grpc, 8443 ws). There are no tests for them yet.
- Server admin: `proxy` (wrapper) → `tools/proxy_cli.py` (+ `tools/proxy_update.py`). It reads `proxy.env` keys
  `SERVER_IP`, `SSH_TUNNEL_NL`, `SSH_TUNNEL_SERVER(_2)`. Its `check` runs `vless.sh --check`.
  `server/setup-server.sh` is for server setup. `tools/install-server.sh`, `backup.sh` and `restore.sh` **do not exist**
  in this repo (checked 2026-10-16).
- Verified on this WSL on 2026-10-16:
  - Docker 29.1.3 and Compose 2.40.3. There is no buildx plugin, but `docker compose build` uses BuildKit (Bake
    warning) and sets `TARGETARCH`.
  - Compose nested defaults `${A:-${HOME}/x}` work.
  - `python:3.12-alpine3.22` has `apk add openssh-client openssh-keygen curl ca-certificates`, which gives `ssh`, `ssh-keyscan`,
    `ssh-keygen` and `curl`. busybox gives `wget`, `unzip`, `sha256sum` and `gunzip`. SQLite is 3.49.2.

## Relevant files and symbols

See "MOVE / REPLACE", "File plan" and "Explicit list of files allowed to be modified".

## Proposed architecture

```
host (WSL/Linux Docker Engine, or macOS Docker Desktop)
  browser ── http://127.0.0.1:4050 ──┐                 apps ── http/socks5 127.0.0.1:7890 ──┐
                                     v                                                      v
  ┌──────────── container "kit" (image mihomo-proxy-kit:local) ──┐   ┌──── container "proxy" (same image) ─────┐
  │ docker-init → python3 /app/ui/server.py (uid 10001 after drop)│   │ docker-init → python3 /app/ui/kit_proxy.py │
  │   :4050 HTTP API + static React UI                            │   │   (uid 10001)                            │
  │   jobs: discover (ssh NL), check (xray :18083 + curl),        │   │   child: xray run -config                │
  │         install / apply_rules (render → validate → write)     │   │          /kit-gen/xray-client.json :18080│
  │   ssh key: /run/secrets/nl_ssh_key (ro) → /tmp/kit-ssh/id_nl  │   │   child: mihomo -d /kit-state/mihomo     │
  │ volumes: kit-data:/data (db, logs, known_hosts, ui-token)     │   │     -f /kit-gen/mihomo/config.yaml :7890 │
  │   kit-gen:/kit-gen  RW (configs, generation, prev) ───────────┼───┼─► kit-gen:/kit-gen  RO                  │
  │   kit-state:/kit-state RO ◄───────────────────────────────────┼───┼── kit-state:/kit-state RW (status.json,  │
  │                                                               │   │     logs/, mihomo home: cache.db, geo)   │
  │ health/verify: curl -x http://proxy:7890 https://api.ipify.org│──►│                                          │
  └───────────────────────────────────────────────────────────────┘   └──────────────────────────────────────────┘
                     │ ssh (NL only, StrictHostKeyChecking=yes)                │ VLESS+REALITY
                     v                                                         v
                 NL 185.245.107.19 (3x-ui, Xray 26.3.27) ──── routing ────► USA1 / USA2 exits
```

Load-bearing decisions:
1. **Two containers, one image, no Docker socket.** `proxy` publishes 7890, and `kit` publishes 4050.
   - If host port 7890 is busy (old host Mihomo), only `proxy` fails to start. The UI still runs and explains the cause
     (its heartbeat is missing).
   - The proxy container gets no SSH key, no DB and no token (least privilege).
   - Reconfiguration goes through volumes with a generation file (amendment 2d). `kit` writes `kit-gen`, which `proxy` mounts read-only.
     `proxy` writes `kit-state`, which `kit` mounts read-only. No API is involved, and nothing runs in the other container.
2. **Chain = the host installer chain.** Mihomo `USA` = socks5 127.0.0.1:18080 → Xray (client JSON ported from
   `install-client.py` `xray_config`) → NL:<port>. This client-side Xray 26.10.10 works against NL Xray 26.3.27 (verified by the user).
3. **Install no longer depends on `NL_PORTS`.** Every discovered inbound with network xhttp, tcp or grpc whose port is
   not in `SKIP_PORTS={443}` can be installed. The old port map (USA1 2083–2086, USA2 2087–2090) is
   reused only as `KNOWN_EXITS` labels and as a non-blocking warning in the discovery log.
4. **Backend: Python 3.12 stdlib.** `ThreadingHTTPServer` on `0.0.0.0:4050` inside the container. The host publishes
   loopback only, and the guard checks `Host` against the PUBLIC port.
5. **Frontend: a Vite + React 19 project in `web/`, plain JSX, built inside Docker (amendment 2a).**
   - Node is needed only in the image build stage, never on the user's host, so the old reason for avoiding a
     build step no longer applies.
   - React 19 instead of 18: there is no UMD constraint any more, and 19 is the current major line.
   - Exact pins, with the lockfile committed:
     - Runtime: `react` 19.3.0, `react-dom` 19.3.0, `qrcode-generator` 2.0.4.
     - Dev only: `vite` 8.3.2, `@vitejs/plugin-react` 6.1.1.
   - No UI framework and no router. Plain CSS.
   - Verified 2026-10-16 with a scratch prototype in `node:24.21.0-alpine3.23` (npm lockfile v3):
     - Works: `npm install --package-lock-only`, `npm ci --ignore-scripts`, `vite build`. `--ignore-scripts` is safe because
       the only package with an install script is `fsevents`, which is macOS-only and optional.
     - The lockfile contains the `@rolldown/binding-linux-arm64-musl` and x64 bindings, so a lock made on amd64 also works for arm64 builds.
     - With `build.modulePreload.polyfill=false`, `dist/index.html` has exactly one
       `<script type="module" crossorigin src="/assets/index-<hash>.js">` and one `<link rel="stylesheet" href="/assets/index-<hash>.css">`.
       There is no inline script or style.
     - The bundle has no `eval(` or `new Function` (about 240 KB, 75 KB gzip).
   - The CSP keeps `script-src 'self'`. `style-src` is `'self' 'unsafe-inline'` (amendment 2d-B); the exact header is in 2d-B.
6. **Pinned binaries** (digests from the GitHub release API; the Xray digests also match the official `.dgst` files; the
   mihomo amd64 digest equals the hash pinned for `bin/` in `install-client.py`):
   | arch | asset | sha256 |
   |---|---|---|
   | amd64 | `mihomo-linux-amd64-compatible-v1.19.32.gz` | `ba3ce607747a07f948fc35780e108a4a7c7f552a38b9bd4d115f313ebcb89c20` |
   | arm64 | `mihomo-linux-arm64-v1.19.32.gz` | `9dd862e28b46ff7d775f169cceebc28deccaa0a9e804237d421cd2571e0caba0` |
   | amd64 | `Xray-linux-64.zip` (v26.10.10) | `72a5fde819713a103c6fc26a87aa025c1518c918a34eba4bc38d64dc0728e5d9` |
   | arm64 | `Xray-linux-arm64-v8a.zip` (v26.10.10) | `58e339e67827220175b3a1c6f66f48ccd086b79209f30ba1c0bcb47885d4c22a` |
   Base images (index digests, multi-arch):
   - `python:3.12-alpine3.22@sha256:a190708a2dec1bd18b1decb539f8e8f5407abaa9bf39cacda583f7f8c11db322`
   - `metacubex/mihomo:v1.19.32@sha256:bac1a74de365ea59270ba134016762c6be05654d55246518de256113bd1c225e`
   Geodata in that image (identical for amd64 and arm64, verified):
   `geoip.dat 3cf2236c19063c1c80803368cca5ff589c5033129fdf9ba154230c689b81fc2a`,
   `geoip.metadb 76ad4ba5d45b1d35b57c3ef26a31c420f7e5afa1e03baf18a47f2d2c933f783b`,
   `geosite.dat bff76f6b4d87c3a4c7d9612b926e762b21ba4fe2c5bf8c5a43af25fe8de71b7e`.
7. **Privileges.**
   - `kit` starts as root only to copy the read-only mounted SSH key into tmpfs (`/tmp/kit-ssh/id_nl`, mode 0600, owned by
     10001). Then it drops to 10001:10001 (`setgroups([])`, `setgid`, `setuid`), which removes all capabilities.
   - Allowed capabilities: `CHOWN, SETUID, SETGID, DAC_READ_SEARCH` only.
   - `proxy` runs as 10001 from the start with `cap_drop: ALL`.
   - Both use `no-new-privileges`, `read_only: true`, tmpfs `/tmp`, and `init: true`.
8. **Token.**
   - Generated once with `secrets.token_urlsafe(32)` into `/data/ui-token` (0600). It persists, so the link can be bookmarked.
   - Not printed at startup (amendment 2c-5); `kit token` prints the login URL and `kit rotate-token` replaces it.
   - The server re-reads the file when its mtime changes, so rotation needs no restart.
   - Cookie: `HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000`.
9. **vless links reach the browser only through `GET /api/exits/<exit_ip>/links`.** This is the one intentional
   exception to "no secrets to the browser". The links never appear in list responses, logs or job output (`Redactor`
   masks `vless://…`). The browser keeps them only in component state and drops them when the panel closes.
10. **A fixed system rule `DOMAIN,api.ipify.org,PROXY` is always rendered first.** Exit verification and health checks
    therefore do not depend on user rules or MATCH.

## Container contract

Paths and environment (set in the Dockerfile; overridable for tests):
`KIT_DATA_DIR=/data`, `KIT_GEN_DIR=/kit-gen`, `KIT_STATE_DIR=/kit-state` (amendment 2d; `KIT_RUN_DIR` no longer exists), `KIT_GEO_DIR=/opt/kit/geo`, `KIT_XRAY_BIN=/usr/local/bin/xray`,
`KIT_MIHOMO_BIN=/usr/local/bin/mihomo`, `KIT_SSH_KEY_MOUNT=/run/secrets/nl_ssh_key`,
`KIT_SSH_KEY_FILE=/tmp/kit-ssh/id_nl`, `KIT_PUBLIC_PORT` (compose: `${KIT_UI_PORT:-4050}`),
`KIT_PROXY_URL` (compose: `http://proxy:7890`), `KIT_WEB_ROOT=/app/web` (built frontend), `HOME=/tmp/kit-home`,
`PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`.

`/data` (kit only): `kit.db` 0600, `logs/job-<id>.log` 0600, `ssh/known_hosts` 0600 (dir 0700), `ui-token` 0600.
`/kit-gen` (volume `kit-gen`; `kit` rw, `proxy` ro; amendment 2d):
- `generation.json` `{"generation": int, "xray_sha256": hex, "mihomo_sha256": hex}`
- `xray-client.json` 0600
- `mihomo/config.yaml` 0600 (config only; passed to mihomo with `-f`)
- `prev/xray-client.json`, `prev/mihomo-config.yaml` 0600 (the previous pair)

`/kit-state` (volume `kit-state`; `proxy` rw, `kit` ro; amendment 2d):
- `status.json` (written by proxy) `{"generation", "state": "idle|running|failed", "error", "heartbeat": epoch, "restarts"}`
- `logs/xray.log`, `logs/mihomo.log` 0600 (+ `.1` after rotation)
- `mihomo/` = mihomo home (`-d`): `cache.db` 0600 and symlinks `geoip.dat`, `geoip.metadb`, `geosite.dat` → `/opt/kit/geo/…`

### `Dockerfile` (repo root)

```dockerfile
# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM node:24.21.0-alpine3.23@sha256:9ec4a2e289874ed0d722e1772ec2de45d2801541db8612f3638b26f128c69ac2 AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY web/ ./
RUN npm run build && test -f dist/index.html

FROM --platform=$BUILDPLATFORM python:3.12-alpine3.22@sha256:a190708a2dec1bd18b1decb539f8e8f5407abaa9bf39cacda583f7f8c11db322 AS fetch
ARG TARGETARCH
WORKDIR /fetch
RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) M=mihomo-linux-amd64-compatible-v1.19.32.gz; MS=ba3ce607747a07f948fc35780e108a4a7c7f552a38b9bd4d115f313ebcb89c20; \
             X=Xray-linux-64.zip; XS=72a5fde819713a103c6fc26a87aa025c1518c918a34eba4bc38d64dc0728e5d9 ;; \
      arm64) M=mihomo-linux-arm64-v1.19.32.gz; MS=9dd862e28b46ff7d775f169cceebc28deccaa0a9e804237d421cd2571e0caba0; \
             X=Xray-linux-arm64-v8a.zip; XS=58e339e67827220175b3a1c6f66f48ccd086b79209f30ba1c0bcb47885d4c22a ;; \
      *) echo "unsupported TARGETARCH=$TARGETARCH" >&2; exit 1 ;; \
    esac; \
    wget -q -O m.gz "https://github.com/MetaCubeX/mihomo/releases/download/v1.19.32/$M"; \
    echo "$MS  m.gz" | sha256sum -c -; \
    wget -q -O x.zip "https://github.com/XTLS/Xray-core/releases/download/v26.10.10/$X"; \
    echo "$XS  x.zip" | sha256sum -c -; \
    gunzip -c m.gz > mihomo; unzip -q x.zip xray; chmod 0755 mihomo xray

FROM metacubex/mihomo:v1.19.32@sha256:bac1a74de365ea59270ba134016762c6be05654d55246518de256113bd1c225e AS geo

FROM python:3.12-alpine3.22@sha256:a190708a2dec1bd18b1decb539f8e8f5407abaa9bf39cacda583f7f8c11db322
RUN apk add --no-cache openssh-client openssh-keygen curl ca-certificates \
 && addgroup -S -g 10001 kit && adduser -S -D -H -u 10001 -G kit -h /tmp/kit-home kit \
 && mkdir -p /data /kit-gen /kit-state /opt/kit/geo \
 && chown 10001:10001 /data /kit-gen /kit-state && chmod 0700 /data /kit-gen /kit-state
COPY --from=fetch /fetch/mihomo /fetch/xray /usr/local/bin/
COPY --from=geo /root/.config/mihomo/geoip.dat /root/.config/mihomo/geoip.metadb /root/.config/mihomo/geosite.dat /opt/kit/geo/
RUN cd /opt/kit/geo \
 && printf '%s  %s\n' \
      3cf2236c19063c1c80803368cca5ff589c5033129fdf9ba154230c689b81fc2a geoip.dat \
      76ad4ba5d45b1d35b57c3ef26a31c420f7e5afa1e03baf18a47f2d2c933f783b geoip.metadb \
      bff76f6b4d87c3a4c7d9612b926e762b21ba4fe2c5bf8c5a43af25fe8de71b7e geosite.dat | sha256sum -c - \
 && chmod 0644 /opt/kit/geo/* \
 && /usr/local/bin/xray version | head -n1 | grep -q '^Xray 26.10.10 ' \
 && /usr/local/bin/mihomo -v | grep -q 'v1.19.32'
COPY ui/ /app/ui/
COPY --from=web /web/dist/ /app/web/
RUN printf '#!/bin/sh\nexec python3 /app/ui/kit_cli.py "$@"\n' > /usr/local/bin/kit \
 && chmod 0755 /usr/local/bin/kit && python3 -m compileall -q /app/ui
ENV KIT_DATA_DIR=/data KIT_GEN_DIR=/kit-gen KIT_STATE_DIR=/kit-state KIT_GEO_DIR=/opt/kit/geo \
    KIT_XRAY_BIN=/usr/local/bin/xray KIT_MIHOMO_BIN=/usr/local/bin/mihomo \
    KIT_SSH_KEY_MOUNT=/run/secrets/nl_ssh_key KIT_SSH_KEY_FILE=/tmp/kit-ssh/id_nl \
    KIT_WEB_ROOT=/app/web HOME=/tmp/kit-home PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 4050 7890
CMD ["python3", "/app/ui/server.py"]
```
If the version checks or a `sha256sum -c` fail, the build fails. Never weaken a check; report the failure instead.
The `web` stage runs on `$BUILDPLATFORM` because its output (JS/CSS) does not depend on the arch. `npm ci` fails
if `package-lock.json` does not match `package.json`, and that failure is intended.
Node image digest: index digest of tag `24.21.0-alpine3.23` from the Docker Hub API (2026-09-18). The prototype build
pulled and ran it on this WSL.

### `.dockerignore` (whitelist; nothing else enters the build context)
```
*
!ui/
!web/
ui/**/__pycache__
web/node_modules
web/dist
```

### `compose.yaml` (repo root)

```yaml
name: mihomo-proxy-kit

x-hardening: &hardening
  image: ${KIT_IMAGE:-mihomo-proxy-kit:local}   # overridable so the smoke test never touches the user's tag
  restart: unless-stopped
  init: true
  read_only: true
  tmpfs:
    - /tmp:mode=1777,size=64m
  security_opt:
    - no-new-privileges:true
  cap_drop: [ALL]
  logging:
    driver: json-file
    options: {max-size: "5m", max-file: "3"}

services:
  proxy:
    <<: *hardening
    pull_policy: never          # reuse the image built by `kit`; never pull or build it separately
    user: "10001:10001"
    command: ["python3", "/app/ui/kit_proxy.py"]
    ports:
      - "127.0.0.1:${KIT_PROXY_PORT:-7890}:7890"
    volumes:
      - kit-gen:/kit-gen:ro       # amendment 2d: configs written by kit; proxy can only read them
      - kit-state:/kit-state      # amendment 2d: proxy's own status.json, logs/, mihomo home (-d)

  kit:
    <<: *hardening
    build: .                    # the ONLY service with build: (amendment 2a)
    user: "0:0"
    cap_add: [CHOWN, SETUID, SETGID, DAC_READ_SEARCH]
    command: ["python3", "/app/ui/server.py"]
    environment:
      KIT_PUBLIC_PORT: "${KIT_UI_PORT:-4050}"
      KIT_PROXY_URL: "http://proxy:7890"
    ports:
      - "127.0.0.1:${KIT_UI_PORT:-4050}:4050"
    volumes:
      - kit-data:/data
      - kit-gen:/kit-gen          # amendment 2d: kit is the only writer
      - kit-state:/kit-state:ro   # amendment 2d: proxy state is read-only (and untrusted) for kit
      - type: bind
        source: ${KIT_SSH_KEY:-./docker/no-key}   # amendment 2e: empty committed placeholder; set KIT_SSH_KEY for discovery
        target: /run/secrets/nl_ssh_key
        read_only: true
        bind:
          create_host_path: false

volumes:
  kit-data: {}
  kit-gen: {}
  kit-state: {}
```
The file must contain no `docker.sock`, no `privileged`, no `network_mode: host`, and no `pid: host`.

**Compose diff for amendment 2d (exact; nothing else in `compose.yaml` changes):**
- `services.proxy.volumes`: `- kit-run:/run-kit` → `- kit-gen:/kit-gen:ro` and `- kit-state:/kit-state` (this order).
- `services.kit.volumes`: `- kit-run:/run-kit` → `- kit-gen:/kit-gen` and `- kit-state:/kit-state:ro`, placed right after `- kit-data:/data`
  and before the SSH-key bind entry.
- Top-level `volumes:`: `kit-run: {}` → `kit-gen: {}` and `kit-state: {}`.
- The hardening anchor is unchanged: `read_only`, `cap_drop: [ALL]`, `no-new-privileges`, tmpfs `/tmp`, `init`, logging. So are the
  `user:` lines (`proxy` 10001, `kit` 0 → drop to 10001), `cap_add`, the loopback-only `ports:`, `pull_policy`, the single `build:`, and the
  key bind. There is no `docker.sock`.
- The proxy's writable set is the `kit-state` volume plus tmpfs `/tmp`. That is exactly the 2d-A list of paths mihomo, xray and the supervisor write.

**Build collision fix (amendment 2a).** In revision 2 both services had `build: .` with the same `image:` tag. Compose
then builds them in parallel, and a first run fails with `image mihomo-proxy-kit:local already exists`. The fix:
- Exactly one service (`kit`) has `build: .`.
- `proxy` has the same `image:` and `pull_policy: never`.
- No `depends_on` is added, so `proxy` still starts when `kit` cannot (e.g. 4050 busy) and the reverse.

Verified on this WSL (Compose 2.40.3, Docker 29.1.3, throwaway project `ctest`, ports 18890/18891, cleaned up afterwards)
with a minimal image:
- `docker compose up -d` with no prior image: the image is built once and both services run.
- `docker compose up -d --build`, with and without a prior image: both services run.
- `docker compose build` then `up -d`: both run.
- After a Dockerfile change, `up -d --build` recreates BOTH containers on the new image ID.
`docker/env.example` (committed) documents `KIT_UI_PORT`, `KIT_PROXY_PORT`, `KIT_SSH_KEY` and `KIT_IMAGE` (leave it at the default). Users copy it to `.env`
(gitignored) or export the variables. It holds paths and ports only, never secrets.

## MOVE / REPLACE (what replaces each host-path piece)

| From | To | Notes |
|---|---|---|
| `tools/export-vless.py`: `REMOTE_PARSE`, `REMOTE_DRIVER`, `REMOTE`, `SKIP_PORTS`, `MODE_NAME`, `DiscoveryError`, `ssh_command`, `discover_rows`, `make_link`, `check` | `ui/kit_nl.py` | Moved verbatim from the partial refactor. Changes: `ssh_command(..., known_hosts=None)` adds `-o UserKnownHostsFile=<p>`; `make_link(row, server_ip)` requires `server_ip`; `check(row, server_ip, xray_bin, socks_port=18083)` requires `server_ip` and `xray_bin`. Dropped: `ENV`, `load_env`, `ssh_rows`, `EXIT_PORTS`, `make_install_command`, `make_block`, `main`. |
| `vless.sh`, `vless.sh --check` | UI server view (links, QR) + `docker compose exec kit kit check` | |
| `tools/install-client.py` `xray_config` | `ui/kit_render.py` `xray_client_config(nl_host, row, fingerprint='firefox')` | Same dict as `xray_config(env,row)` with `ADMIN_SSH_TUNNEL` unset; xhttp `{path, mode}` only. Golden test = the JSON documented in the superseded spec (bash/Python parity reused as fixed expectations). |
| `tools/install-client.py` `NL_PORTS` / `tools/macos-chain.sh` `nl_allowed_ports` | `ui/kit_render.py` `KNOWN_EXITS` | Labels plus a discovery warning only, not enforced. |
| `tools/install-client.py` binary install + pinned hashes; `tools/macos-chain.sh` `xray_darwin_asset`/`install_xray_darwin` | `Dockerfile` fetch stage | Linux amd64/arm64 assets pinned (table above). Darwin assets are no longer needed. |
| `tools/install-client.py` systemd units; `install.sh` LaunchAgents; `mihomo-keepalive.sh` | compose `restart: unless-stopped` + `ui/kit_proxy.py` child supervisor | |
| `tools/install-client.py` `configure_shell`; `install.sh` system proxy | README "Как приложения используют прокси" | Not automated (open question 4). |
| `tools/mihomo-config.py` `render` DNS block + rules | `ui/kit_render.py` `mihomo_config()` + `DEFAULT_RULES` | `USA` becomes socks5 to Xray; `allow-lan: true`, `bind-address: "*"`. |
| `set-proxy-env.sh`, `proxy.env` (client) | SQLite `nl_settings`, `inbounds`, `active` + UI | |
| `fill-proxy-env-from-current-config.sh` | UI discovery | |
| `unregister.sh` | `docker compose down` (`-v` wipes data) + README migration commands for old host services | |
| `migrate-docker.md` | README section "Переход с установки на хосте" | |
| `bin/*` | Dockerfile downloads with pinned SHA-256 | |
| `tests/test_install_client.py`, `tests/test_macos_chain.py`, `tests/test_mihomo_config.py` | `tests/test_kit_render.py` | Ports the relevant assertions. |
| `tools/proxy_cli.py` `check` (`vless.sh --check`) | `docker compose exec -T kit kit check` (cwd repo root) | |

## File plan

### Partial work from revision 1 (already in the working tree)
| File | Decision |
|---|---|
| `ui/kit_db.py` | **KEEP + CHANGE** (section C): schema edits, rules/kv/active, seeding. |
| `ui/kit_guard.py` | **KEEP + CHANGE** (section F): `port` = public port; cookie `Max-Age=2592000`. Nothing else. |
| `ui/kit_discovery.py` | **KEEP + CHANGE** (section D): import `kit_nl` directly; drop `install_client`, `detect_active`, `nl_suggestion`, `ADMIN_TUNNEL_PORT`, the key-path field. |
| `ui/kit_jobs.py` | **KEEP + CHANGE** (section E): delete `install_argv`, `EXIT_IP_RE`, `INSTALL_SETUP_TIMEOUT`, `INSTALL_TIMEOUT`; rewrite `install_job`; add `apply_rules_job`. Keep the rest verbatim. |
| `tests/fixtures/ui/xui_config.json` | **KEEP** as is. |
| `tools/export-vless.py` (section-A refactor) | **MOVE** its code to `ui/kit_nl.py` (section B). The file itself is deleted in step 14. |

### New
- `Dockerfile`, `.dockerignore`, `compose.yaml`, `docker/env.example`
- `ui/kit_nl.py`, `ui/kit_render.py`, `ui/kit_apply.py`, `ui/kit_proxy.py`, `ui/kit_priv.py`,
  `ui/kit_cli.py`, `ui/server.py`
- `web/package.json`, `web/package-lock.json`, `web/vite.config.js`, `web/index.html`, `web/src/main.jsx`,
  `web/src/App.jsx`, `web/src/api.js`, `web/src/app.css`, and `web/src/components/{LoginHint,StatusBar,NlSettings,HostKeyDialog,ExitList,ServerView,LinksModal,QrCode,RulesEditor,JobLog}.jsx`
  (section L)
- There is no `ui/static/` directory and there are no vendored JS files (amendment 2a).
- `tests/test_kit_nl.py`, `tests/test_kit_db.py`, `tests/test_kit_guard.py`, `tests/test_kit_discovery.py`,
  `tests/test_kit_render.py`, `tests/test_kit_jobs.py`, `tests/test_kit_apply.py`, `tests/test_kit_proxy.py`,
  `tests/test_kit_priv.py`, `tests/test_kit_server.py`, `tests/test_web_contract.py`, `tests/test_docker_files.py`
- `tests/docker_smoke.sh`

### Changed
- `README.md`: full rewrite (section J). Keep the content of the existing "Команда proxy" section and the server-admin notes.
- `.gitignore` (section I)
- `tools/proxy_cli.py`: only the `check` function and its help text (section K)
- `proxy.env.example`: rewritten to admin-only keys (section K). Write it fresh; it holds no secrets.
- `openspec/changes/nl-usa2-ports-macos-xray-chain/proposal.md`: insert one line after the title:
  `> Status: SUPERSEDED by openspec/changes/local-web-ui (Docker-only). Not implemented further.`

### REMOVE (step 14, only after the user's explicit yes)
| Path | Replaced by |
|---|---|
| `install.sh` | kit install job (`ui/kit_apply.py`) |
| `set-proxy-env.sh` | SQLite + UI |
| `unregister.sh` | `docker compose down [-v]` + README migration commands |
| `tools/install-client.py` | `ui/kit_render.py`, Dockerfile, compose |
| `tools/macos-chain.sh` | container chain |
| `tools/mihomo-config.py` | `ui/kit_render.py` |
| `tools/export-vless.py` | `ui/kit_nl.py` |
| `vless.sh` | UI links view, `kit check` |
| `mihomo-keepalive.sh` | `restart: unless-stopped` + `kit_proxy.py` |
| `fill-proxy-env-from-current-config.sh` | UI discovery |
| `migrate-docker.md` | README migration section |
| `task.md` | obsolete original prompt |
| `bin/mihomo-darwin-amd64-compatible-v1.19.32.gz`, `bin/mihomo-darwin-arm64-v1.19.32.gz`, `bin/mihomo-linux-amd64-compatible-v1.19.32.gz`, `bin/xray-linux-amd64-v26.10.10.gz`, `bin/.gitkeep` | Dockerfile pinned downloads |
| `tests/test_install_client.py`, `tests/test_macos_chain.py`, `tests/test_mihomo_config.py` | `tests/test_kit_render.py` |
| `tests/__pycache__/`, `tools/__pycache__/` (untracked) | gitignored |

### KEEP (server admin and docs; not part of the client install)
- `proxy`, `tools/proxy_cli.py` (only `check` changes), `tools/proxy_update.py`, `server/setup-server.sh`
- `setup-ai-cli-proxy.sh` (points host AI CLIs at `127.0.0.1:7890`, which is still valid)
- `docs/history-before-cleanup.md`, `AGENTS.md`, `openspec/**`, `.memoryignore`
- `proxy.env.example` (rewritten). The user's own `proxy.env` is never touched.
- Not present in this repo: `tools/install-server.sh`, `backup.sh`, `restore.sh`, so there is nothing to keep or remove.

## Detailed implementation plan

### B. `ui/kit_nl.py` (moved from `tools/export-vless.py`)
- Copy verbatim from the current working-tree `tools/export-vless.py`: `REMOTE_PARSE`, `REMOTE_DRIVER`,
  `REMOTE`, `SKIP_PORTS`, `MODE_NAME`, `DiscoveryError`, `discover_rows`, `make_link`, `check`, and their imports.
- `ssh_command(target, ssh_port=22, key_path=None, known_hosts=None)`: same as now. When `known_hosts` is set, add
  `-o UserKnownHostsFile=<known_hosts>` and `-o GlobalKnownHostsFile=/dev/null` before `--`.
  `discover_rows(target, ssh_port=22, key_path=None, known_hosts=None, timeout=40)` passes them through.
- `make_link(row, server_ip)` and `check(row, server_ip, xray_bin, socks_port=18083)`: the parameters are required and
  there is no `ENV` fallback. Everything else in the bodies is unchanged.
- No module-level side effects.

### C. `ui/kit_db.py`
1. Rewrite `V1_SQL` (the DB was never released, so no v2 is needed):
   - `nl_settings`: drop the column `ssh_key_path`.
   - `jobs.kind` CHECK: `('discover','check','install','apply_rules')`.
   - Add:
     ```sql
     CREATE TABLE rules (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       position INTEGER NOT NULL,
       type TEXT NOT NULL CHECK (type IN ('DOMAIN','DOMAIN-SUFFIX','DOMAIN-KEYWORD','GEOSITE','GEOIP','IP-CIDR')),
       value TEXT NOT NULL,
       policy TEXT NOT NULL CHECK (policy IN ('PROXY','DIRECT','REJECT')),
       no_resolve INTEGER NOT NULL DEFAULT 0,
       enabled INTEGER NOT NULL DEFAULT 1,
       note TEXT NOT NULL DEFAULT '',
       UNIQUE (type, value));
     CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
     CREATE TABLE active (
       id INTEGER PRIMARY KEY CHECK (id = 1),
       inbound_id INTEGER REFERENCES inbounds(id) ON DELETE SET NULL,
       generation INTEGER NOT NULL, applied_at TEXT NOT NULL);
     ```
2. `data_dir()`: unchanged (the container sets `KIT_DATA_DIR=/data`).
3. `get_nl` / `save_nl(conn, host, ssh_user, ssh_port)`: drop the key path.
4. New functions:
   - `seed_rules(conn, defaults, match)`: if `kv.rules_seeded` is absent, insert `defaults` in order and set
     `kv.match_policy=match` and `kv.rules_seeded='1'`, in one transaction. It is called from `connect()` after `migrate`, with
     `kit_render.DEFAULT_RULES` and `kit_render.DEFAULT_MATCH`. Import `kit_render` lazily inside `connect` to avoid
     cycles.
   - `get_rules(conn) -> list[dict]` ordered by `position`.
   - `replace_rules(conn, rules, match)`: one transaction. `DELETE FROM rules`, insert with positions `0..n-1`, set `kv.match_policy`.
   - `get_match(conn) -> str` (default `'PROXY'`).
   - `get_active(conn) -> dict|None`, `set_active(conn, inbound_id, generation)`.
5. `public_inbound(row, installable, label)`: add the key `network_label` (`'TCP+Vision'` if network is tcp and
   flow is set, `'TCP'`, `'XHTTP'`, `'gRPC'`) and the key `active` (bool, passed in). The allowlist test is
   updated accordingly. Still never `uuid, pbk, sid, sni, xhttp_json, grpc_service`.

### D. `ui/kit_discovery.py`
- Replace `_tool`, `export_vless` and `install_client` with `import kit_nl, kit_render`.
- `validate_nl(data)` → `{host, ssh_user, ssh_port}`. Remove the `ssh_key_path` branch; keep the validators.
- `installable(network, port, exit_ip)` = `network in SUPPORTED_NETWORKS and port not in kit_nl.SKIP_PORTS and bool(exit_ip)`.
- `exit_label(exit_ip, exit_tag)` = `kit_render.KNOWN_EXITS.get(exit_ip, {}).get('label') or exit_tag or exit_ip`.
- `known_exit_warnings(rows) -> list[str]`: for rows whose `exit_ip` is in `KNOWN_EXITS` and whose port is not in its
  `ports`, return `Вход NL:<port> ведёт на <label>, но не входит в ожидаемые порты <a>-<b>`. Log only.
- `paths()` → `known_hosts = data_dir/'ssh'/'known_hosts'` (create dir 0700, file 0600 if missing) and
  `key = os.environ['KIT_SSH_KEY_FILE']` (default `/tmp/kit-ssh/id_nl`).
- `discover(nl)`: call `kit_nl.discover_rows(f'{user}@{host}', port, key if os.path.isfile(key) else None,
  known_hosts)`. Map errors as follows:
  - `Host key verification failed` → `NL: ключ хоста не подтверждён. Нажмите «Проверить ключ хоста» в настройках NL`
  - `Permission denied` → `NL: SSH-ключ не принят (проверьте KIT_SSH_KEY и authorized_keys на NL)`
  - Key file missing → `NL: SSH-ключ не смонтирован (KIT_SSH_KEY)`, raised before running ssh.
  - Otherwise → unchanged.
- `scan_host_key(host, port) -> list[str]`: run `['ssh-keyscan', '-T', '10', '-p', str(port), '-t',
  'ed25519,ecdsa,rsa', host]` (host is already validated, so it cannot start with `-`) with timeout 20. Return the non-comment
  lines whose first field equals `host` (port 22) or `[host]:port`. Raise `RuntimeError('NL: ssh-keyscan не получил
  ключи')` if there are none.
- `fingerprints(lines) -> list[{'type','fingerprint'}]`: write the lines to a temp file, run `ssh-keygen -l -E sha256 -f <tmp>`,
  and parse `<bits> SHA256:<b64> <host> (<TYPE>)`.
- `trust_host_key(lines, host, port, known_hosts)`: run `ssh-keygen -R <host or [host]:port> -f known_hosts` (ignore
  rc 1), delete `known_hosts.old`, append the lines, chmod 0600.
- `is_trusted(host, port, known_hosts) -> bool`: `ssh-keygen -F <host or [host]:port> -f known_hosts` rc 0.
- Delete `detect_active`, `_client_selection`, `nl_suggestion`, `ADMIN_TUNNEL_PORT`, `IPV4` key-path logic.
- `run_check(db_row, nl_host)`: `kit_nl.check(export_row(row), nl_host, os.environ.get('KIT_XRAY_BIN',
  '/usr/local/bin/xray'))`.
- `links_for_exit(conn, nl_host, exit_ip) -> list[dict]`: present inbounds of that exit ordered by port →
  `{id, port, network_label, remark, link: kit_nl.make_link(export_row(row), nl_host)}`.

### E. `ui/kit_jobs.py`
- Delete `install_argv`, `EXIT_IP_RE`, `INSTALL_SETUP_TIMEOUT`, `INSTALL_TIMEOUT`.
- `discover_job(job, nl)`: after upsert, `job.append` each `known_exit_warnings` line.
- `install_job(job, nl, row)` → `return kit_apply.install(job, nl, row)`.
- `apply_rules_job(job, nl)` → `return kit_apply.apply_rules(job, nl)`.
- Everything else (Busy, child_env, Redactor, Job, read_log_file, run_streamed, JobRunner, running_job,
  check_job) stays.

### F. `ui/kit_guard.py`
- Callers pass `port = int(os.environ.get('KIT_PUBLIC_PORT', '4050'))`.
- `session_cookie(token)` → `f'{SESSION_COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000'`.
- Static rule (amendment 2a): `GET`/`HEAD` on `/` or on a path starting with `/assets/` is allowed without a session, instead of `/static/`.

### G. `ui/kit_render.py`
```python
RULE_TYPES = ('DOMAIN', 'DOMAIN-SUFFIX', 'DOMAIN-KEYWORD', 'GEOSITE', 'GEOIP', 'IP-CIDR')
POLICIES = ('PROXY', 'DIRECT', 'REJECT')
NO_RESOLVE_TYPES = ('GEOIP', 'IP-CIDR')
SYSTEM_RULES = (('DOMAIN', 'api.ipify.org', 'PROXY', False),)
DEFAULT_MATCH = 'PROXY'
DEFAULT_RULES = (
    ('DOMAIN-SUFFIX', 'openai.com', 'PROXY', False), ('DOMAIN-SUFFIX', 'chatgpt.com', 'PROXY', False),
    ('DOMAIN-SUFFIX', 'anthropic.com', 'PROXY', False), ('DOMAIN-SUFFIX', 'claude.ai', 'PROXY', False),
    ('DOMAIN-SUFFIX', 'telegram.org', 'PROXY', False), ('DOMAIN-SUFFIX', 't.me', 'PROXY', False),
    ('GEOIP', 'PRIVATE', 'DIRECT', True), ('DOMAIN-SUFFIX', 'local', 'DIRECT', False),
    ('DOMAIN-SUFFIX', 'localhost', 'DIRECT', False), ('GEOSITE', 'category-ru', 'DIRECT', False),
    ('DOMAIN-SUFFIX', 'ru', 'DIRECT', False), ('DOMAIN-SUFFIX', 'xn--p1ai', 'DIRECT', False),
    ('GEOIP', 'RU', 'DIRECT', False))
KNOWN_EXITS = {'108.61.222.91': {'label': 'USA1', 'ports': (2083, 2084, 2085, 2086)},
               '149.28.240.154': {'label': 'USA2', 'ports': (2087, 2088, 2089, 2090)}}
XRAY_SOCKS_PORT = 18080
MIXED_PORT = 7890
```
DB rows from `DEFAULT_RULES` get `enabled=1` and `note=''`.

- `validate_rule(d) -> dict` returns `{type, value, policy, no_resolve, enabled, note}` or raises `ValueError('Правило <n>: …')`.
  The message never contains the value.
  - `type` must be in `RULE_TYPES`; `policy` must be in `POLICIES`.
  - `value` must be a str, trimmed, 1..253 chars, with no whitespace and none of `, # ' " \n \0`.
  - DOMAIN and DOMAIN-SUFFIX: lowercase, strip the trailing `.`, convert with `value.encode('idna').decode('ascii')`
    (UnicodeError → invalid), then fullmatch
    `[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*`.
  - DOMAIN-KEYWORD: `[a-z0-9-]{1,63}` after lowercasing.
  - GEOSITE: `[A-Za-z0-9@!._-]{1,64}`.
  - GEOIP: `[A-Za-z0-9_-]{2,32}`, stored uppercase.
  - IP-CIDR: `ipaddress.IPv4Network(value, strict=False)`, stored as `str(net)`.
  - `no_resolve` is a bool, and only allowed when `type in NO_RESOLVE_TYPES` (otherwise it is forced to False).
  - `enabled` is a bool, default True. `note` is a str of at most 200 chars and is never rendered.
- `validate_rules(payload) -> (rules, match)`: `payload['rules']` is a list of at most 500 items, `match` must be in
  `POLICIES`, and duplicate `(type, value)` → ValueError.
- `rule_line(t, v, p, no_resolve) -> str` = `f'  - {t},{v},{p}' + (',no-resolve' if no_resolve else '')`.
- `xray_client_config(nl_host, row, fingerprint='firefox') -> dict`, where `row` is a DB inbound row. The result is identical to
  `install-client.xray_config` with `ADMIN_SSH_TUNNEL` unset:
  - `{'log':{'loglevel':'warning'}`
  - `'inbounds':[{'listen':'127.0.0.1','port':18080,'protocol':'socks','settings':{'udp':True}}]`
  - `'outbounds':[{'protocol':'vless','settings':{'vnext':[{'address':nl_host,'port':row['port'],'users':[{'id':uuid,'encryption':'none', + 'flow':'xtls-rprx-vision' only for tcp}]}]}`
  - `'streamSettings':{'network':net,'security':'reality', + 'xhttpSettings':{'path':x.get('path','/dl'),'mode':x.get('mode','auto')} only for xhttp, + 'grpcSettings':{'serviceName':row['grpc_service']} only for grpc, 'realitySettings':{'serverName':row['sni'],'fingerprint':fingerprint,'password':row['pbk'],'shortId':row['sid']}}}]}`
  - Raise ValueError if `nl_host`, `uuid`, `pbk` or `sni` is empty, or if grpc has no service name.
- `mihomo_config(rules, match) -> str`, where `rules` are enabled DB rows. Text, exactly:
  ```
  mixed-port: 7890
  allow-lan: true
  bind-address: "*"
  mode: rule
  log-level: warning
  ipv6: false

  dns:            (same 11 lines as tools/mihomo-config.py render(): enable, enhanced-mode fake-ip,
                   fake-ip-range 198.18.0.1/16, respect-rules true, proxy-server-nameserver [system],
                   direct-nameserver [system], nameserver [https://1.1.1.1/dns-query, https://8.8.8.8/dns-query])

  proxies:
    - name: USA
      type: socks5
      server: 127.0.0.1
      port: 18080
      udp: true

  proxy-groups:
    - name: PROXY
      type: select
      proxies:
        - USA

  rules:
    - DOMAIN,api.ipify.org,PROXY        (SYSTEM_RULES first)
    - <enabled user rules in position order>
    - MATCH,<match>
  ```
  Each rule is re-validated with `validate_rule` before rendering, as defence in depth.

### H. `ui/kit_apply.py`
- (amendment 2d) `run_dir()` is removed. In its place:
  - `gen_dir()` = `Path(os.environ.get('KIT_GEN_DIR', '/kit-gen'))`, holding `xray-client.json`, `mihomo/config.yaml`,
    `generation.json` and `prev/`. `_xray_path`, `_mihomo_path`, `_gen_path`, `_prev_dir`, `write_bundle` and `restore_prev` use it
    (rename `run` → `gen` in `write_bundle`; same logic).
  - `state_dir()` = `Path(os.environ.get('KIT_STATE_DIR', '/kit-state'))`, holding `status.json` and `logs/`. It is read only, through
    `open_state_dir(sub=None)` (2d-A); nothing in `kit` writes there.
  - `read_regular_bytes(path, dir_fd=None)` and `read_regular_tail(path, max_bytes=LOG_TAIL_BYTES, dir_fd=None)` get a keyword `dir_fd`.
  - `read_status()` = `fd = open_state_dir()`; `None` → `None`; else `read_regular_bytes('status.json', dir_fd=fd)` in `try/finally os.close(fd)`.
    `RunFileError` → `None`; invalid JSON → `None`.
- `sha256_text(s)`, `atomic_write(path, text, mode=0o600)` (temp in the same dir + `os.replace`).
- `validate_bundle(xray_json, mihomo_yaml)`:
  - In a `tempfile.TemporaryDirectory()`, write both files.
  - Run `[KIT_XRAY_BIN, 'run', '-test', '-config', x]` with timeout 20.
  - Create `home/` with symlinks to `$KIT_GEO_DIR/{geoip.dat,geoip.metadb,geosite.dat}` and run
    `[KIT_MIHOMO_BIN, '-t', '-d', home, '-f', m]` with timeout 30.
  - Non-zero → `RuntimeError('Конфигурация не прошла проверку: xray|mihomo')`. The raw output goes only to the redacted job log.
- `write_bundle(xray_json=None, mihomo_yaml=None) -> int`:
  - Copy the current files (if any) to `prev/` (0600).
  - Write the given files atomically. A `None` file stays as is.
  - Read the old generation (0 if missing) and write `generation.json` with `generation+1` and the sha256 of BOTH current
    files (empty string if a file is missing).
  - Return the new generation.
- `restore_prev() -> int|None`: if `prev/` holds both files, copy them back, bump the generation and return it. Otherwise return None.
- `read_status()` → dict or None.
- `wait_applied(generation, timeout=25)`: poll `status.json` every 0.5 s until `generation` matches and
  `state in ('running','failed')`. Returns the status, or `{'state':'timeout'}`.
- `verify_exit(expected, tries=3)`: `curl --noproxy '' -fsS --max-time 10 -x $KIT_PROXY_URL https://api.ipify.org`
  through `subprocess.run(..., env=kit_jobs.child_env(), timeout=13)`, with 1 s between tries. Returns `(ok, ip)`.
- `install(job, nl, row)`:
  1. Add the redaction secrets.
  2. `x = json.dumps(xray_client_config(nl['host'], row), indent=2)`, `m = mihomo_config(enabled rules, match)`.
  3. `validate_bundle` → `write_bundle(x, m)` → `wait_applied`.
  4. If the state is not running → rollback.
  5. `verify_exit(row['exit_ip'])`. On success: `set_active(row.id, gen)` and return `('ok', ip, 'Установлено: NL:<port> -> <exit_ip>')`.
  6. **Rollback**: `restore_prev()`, then `wait_applied`. Return `('failed', ip, 'Установка не удалась: <reason>. Восстановлена предыдущая конфигурация')`,
     or `'... Предыдущей конфигурации нет'`.
  7. Log lines (job): `Проверка конфигурации…`, `Применение (поколение N)…`, `Прокси-контейнер: <state>`,
     `Выходной IP: <ip>`.
- `apply_rules(job, nl)`:
  - With no active inbound, return `('ok', None, 'Правила сохранены; будут применены при установке')`.
  - Otherwise render only the mihomo config, then `validate_bundle(current xray file text, m)` → `write_bundle(None, m)` →
    `wait_applied` → `verify_exit(active exit)`. On failure, roll back the same way.
- `proxy_state()`: status from `read_status()`.
  - Missing, or `heartbeat` older than 15 s → `{'state':'down', 'error': None, 'generation': None, 'heartbeat_age': age|None}`.
  - Otherwise `{'state', 'error', 'generation', 'heartbeat_age'}`.

### I. `ui/kit_proxy.py` (proxy container entrypoint, stdlib only)
- Pure helpers (tested):
  - `read_generation(path) -> dict|None`: None on missing or invalid JSON or wrong types.
  - `file_sha256(path) -> str` (empty string if missing).
  - `plan_restarts(applied: dict, wanted: dict, running: dict) -> set`: contains `'xray'` if the xray hash changed
    or xray is not running; `'mihomo'` if the mihomo hash changed or mihomo is not running.
  - `status_is_stale(status, now, max_age=15)`.
  - `write_status(path, **fields)`: atomic, 0600, adds `heartbeat=time.time()`.
- `class Supervisor`:
  - (amendment 2d) `__init__`: `self.gen_dir = Path(os.environ.get('KIT_GEN_DIR', '/kit-gen'))`,
    `self.state_dir = Path(os.environ.get('KIT_STATE_DIR', '/kit-state'))`. `self.run_dir` is removed. `gen_dir` is read-only for the proxy:
    no `ensure_real_dir`, `mkdir`, `write_status`, `symlink_to` or `open(... O_WRONLY/O_CREAT)` may target it.
  - `start()`: `os.umask(0o077)`. `ensure_real_dir` on `STATE`, `STATE/mihomo` and `STATE/logs` (0700). Create symlinks
    `STATE/mihomo/{geoip.dat,geoip.metadb,geosite.dat}` → `$KIT_GEO_DIR/...` if missing, and write status `idle` to `STATE/status.json`.
    On `OSError`: `failed`, error `Каталог /kit-state повреждён`.
  - Main loop, every 1 s:
    1. Read the generation. If it is new: check that the declared hashes equal `file_sha256` of the files; on a mismatch, write status
       `failed`, `error='Файлы конфигурации не совпали с поколением'` and wait for the next tick.
    2. Restart per `plan_restarts`, in order: stop mihomo if it is in the set, stop/start xray if it is in the set, wait for `127.0.0.1:18080`
       (10 s), start mihomo, wait for `127.0.0.1:7890` (10 s).
    3. Status `running` or `failed` with error `Xray не открыл 18080` / `Mihomo не открыл 7890` (no raw log
       text in status).
    4. Crash watch: if an applied child exited, restart it after a backoff of 3, 6, 12 or 30 s (reset after 60 s up),
       increment `restarts` and log one line to stdout.
    5. Heartbeat every 5 s.
  - Children (amendment 2d): `subprocess.Popen([XRAY, 'run', '-config', str(GEN/'xray-client.json')])` and
    `[MIHOMO, '-d', str(STATE/'mihomo'), '-f', str(GEN/'mihomo'/'config.yaml')]`, `stdin=DEVNULL`, stdout/stderr appended to `STATE/logs/<name>.log`
    (opened 0600). Rotate before each start: if larger than 5 MiB, rename to `.1`. Env without `*_proxy`.
  - Stop: SIGTERM, wait 5 s, SIGKILL.
  - SIGTERM/SIGINT on the supervisor → stop both children, write status `idle`, exit 0.
- `main()` → `Supervisor().run()`; `if __name__ == '__main__': raise SystemExit(main())`.

### J0. `ui/kit_priv.py`
- `prepare_and_drop(uid=10001, gid=10001)`, called first by `server.py` and `kit_cli.py`:
  - If `os.geteuid() != 0`, return (no-op on the host and in tests).
  - If `$KIT_SSH_KEY_MOUNT` is a regular file and `$KIT_SSH_KEY_FILE` does not exist or differs: create its parent dir 0700
    owned by uid:gid, copy the bytes (`os.open(..., O_WRONLY|O_CREAT|O_TRUNC, 0o600)`) and chown it. The content is never logged.
  - Ensure `$KIT_DATA_DIR` and `$KIT_GEN_DIR` are owned by uid:gid (chown only the top dir if needed). Amendment 2d: `$KIT_STATE_DIR`
    is never chowned or chmodded by `kit` (it is mounted read-only; its ownership comes from the image dir via Docker's volume copy-up).
  - Create `$HOME` (0700, chown).
  - `os.setgroups([])`, `os.setgid(gid)`, `os.setuid(uid)`. If `os.getuid() == 0` afterwards, raise SystemExit
    `Не удалось сбросить права root`.
- `copy_key(src, dst)` is a separate function so it can be tested on the host with temp paths (no chown when not root).

### J1. `ui/server.py`
- Start-up order: `kit_priv.prepare_and_drop()` → `os.umask(0o077)` → DB connect + `mark_stale_jobs` → token
  load-or-create (`/data/ui-token`, 0600, `secrets.token_urlsafe(32)`) → `make_server(4050, token_getter)` bound to
  `('0.0.0.0', 4050)` → print only `Ссылка для входа: docker compose exec kit kit token` (amendment 2c-5: the token is never
  printed to stdout, so it never reaches `docker compose logs`). Formerly: print `Откройте: http://127.0.0.1:<KIT_PUBLIC_PORT>/login?t=<token>` and
  `Повторно: docker compose exec kit kit token`.
- `make_server(port, token_getter, bind='0.0.0.0') -> ThreadingHTTPServer`. Tests use `bind='127.0.0.1', port=0`.
  `token_getter()` re-reads the token file when its mtime changes.
- Handler rules from revision 1, unchanged:
  - `log_message` prints the method, the path without the query string, and the status.
  - `check_request` on every request, with the public port.
  - Static files (amendment 2a):
    - Root: `Path(os.environ.get('KIT_WEB_ROOT', '/app/web'))`.
    - At startup, build an immutable map `{'/': root/'index.html'}` plus `'/assets/<name>'` for each regular file
      directly in `root/assets` whose name fullmatches `[A-Za-z0-9._-]+\.(js|css|svg|png|woff2)`.
    - Serve only exact map hits. Never join a request path onto the filesystem; any other path → 404. That includes
      `..`, percent-encoded forms and subdirectories.
    - Content types: html `text/html; charset=utf-8`, js `text/javascript; charset=utf-8`,
      css `text/css; charset=utf-8`, svg `image/svg+xml`, png `image/png`, woff2 `font/woff2`.
    - If `index.html` is missing, `/` returns 503 `{"error":"Интерфейс не собран"}`.
    - SPA routes are not used (no router), so there is no fallback.
  - 16 KiB body limit, JSON only, `SECURITY_HEADERS` on every response, never `Access-Control-*`.
- API:
  | Method | Path | Body | Response |
  |---|---|---|---|
  | GET | `/api/state` | — | `{nl, nl_key_mounted: bool, nl_host_trusted: bool, proxy: proxy_state(), active: {inbound_id, applied_at}\|null, exits: [{exit_ip, label, inbounds: [public_inbound…]}], rules: {count, match}, job, jobs}` |
  | PUT | `/api/nl` | `{host, ssh_user, ssh_port}` | 200 state / 400 |
  | POST | `/api/nl/hostkey/scan` | `{}` | 200 `{scan_id, host, port, keys:[{type,fingerprint}], already_trusted}` |
  | POST | `/api/nl/hostkey/accept` | `{scan_id}` | 200 `{trusted:true}`; 404 if the scan is unknown or expired (TTL 300 s, single use) |
  | POST | `/api/discover` | `{}` | 202 `{job_id}` / 400 if NL is not set / 409 |
  | POST | `/api/inbounds/<id>/check` | `{}` | 202 / 404 |
  | POST | `/api/check-all` | `{}` | 202 |
  | POST | `/api/inbounds/<id>/install` | `{"confirm": true}` | 202 / 400 |
  | POST | `/api/inbounds/import` (amendment 2e) | `{links:[str]}` (1..40, each ≤1024) | 200 `{imported, removed, items:[{index, port, network, exit_ip, remark}]}` / 400 `{error, errors?:[{index, error}]}` / 409 |
  | GET | `/api/exits/<exit_ip>/links` | — | 200 `{exit_ip, items:[{id, port, network_label, remark, link}]}` / 404 |
  | GET | `/api/rules` | — | `{rules:[{type,value,policy,no_resolve,enabled,note}], match, types, policies}` |
  | PUT | `/api/rules` | `{rules:[…], match}` | 200 `{saved:true, job_id: int\|null}`. Starts `apply_rules` when an active inbound exists; 409 if busy (nothing saved) |
  | POST | `/api/health` | `{}` | `{ok, ip, expected_ip, at}` via `KIT_PROXY_URL` |
  | GET | `/api/proxy/logs?name=xray\|mihomo` | — | `{lines: last 200, redacted}` |
  | GET | `/api/jobs/<id>?offset=n` | — | as in revision 1 |
  - `<id>` must fullmatch `\d{1,9}`; `<exit_ip>` must fullmatch the IPv4 regex.
  - The scan endpoint stores `{scan_id: (lines, host, port, expires)}` in memory. `accept` writes exactly those lines.
  - Pending scans are pruned on each call.
- `main()` and `if __name__ == '__main__': raise SystemExit(main())`.

### J2. `ui/kit_cli.py` (`/usr/local/bin/kit`)
- First call: `kit_priv.prepare_and_drop()`, so files never become owned by root.
- Subcommands (argparse):
  - `token`: print `http://127.0.0.1:<KIT_PUBLIC_PORT>/login?t=<token>`.
  - `rotate-token`: write a new token (0600) and print the new URL.
  - `status`, `discover`, `check [--port N]`: thin HTTP client to `http://127.0.0.1:4050` inside the container with headers
    `Host: 127.0.0.1:<public>`, `Origin: http://127.0.0.1:<public>`, cookie = token, and JSON. It polls jobs every 1 s and prints the job lines.
    Exit 0 when the job is ok, 1 when it failed, 2 on a usage or connection error.
  - `check` without `--port` → check-all. With `--port` → the present inbound(s) with that port.

### K. Admin tooling
- `tools/proxy_cli.py` `check(_args)`: `return subprocess.run(['docker', 'compose', 'exec', '-T', 'kit', 'kit',
  'check'], cwd=str(ROOT)).returncode`. Help text: `проверить входы NL из контейнера (kit check)`. No other change.
- `proxy.env.example`: write fresh (do not read the old file):
  ```
  # Только для администрирования серверов (команда ./proxy). Клиент работает в Docker и этот файл не использует.
  SERVER_IP=185.245.107.19
  SSH_TUNNEL_NL=root@185.245.107.19
  SSH_TUNNEL_SERVER=root@108.61.222.91
  SSH_TUNNEL_SERVER_2=root@149.28.240.154
  ```

### L. Frontend `web/` (amendment 2a: Vite + React 19, plain JSX)

Layout and exact contents:
- `web/package.json`:
  ```json
  {
    "name": "mihomo-proxy-kit-web",
    "private": true,
    "version": "0.0.0",
    "type": "module",
    "scripts": { "dev": "vite", "build": "vite build" },
    "dependencies": { "qrcode-generator": "2.0.4", "react": "19.3.0", "react-dom": "19.3.0" },
    "devDependencies": { "@vitejs/plugin-react": "6.1.1", "vite": "8.3.2" }
  }
  ```
  No other dependencies. Versions are exact, never `^` or `~`.
- `web/package-lock.json`: generated, never hand-edited. Command, from the repo root, running Node only inside the pinned image:
  ```bash
  docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -e npm_config_cache=/tmp/.npm \
    -v "$PWD/web":/web -w /web \
    node:24.21.0-alpine3.23@sha256:9ec4a2e289874ed0d722e1772ec2de45d2801541db8612f3638b26f128c69ac2 \
    npm install --package-lock-only --ignore-scripts --no-audit --no-fund
  ```
  Commit the result. To regenerate after a version change, run the same command.
- `web/vite.config.js`:
  ```js
  import { defineConfig } from 'vite';
  import react from '@vitejs/plugin-react';

  const KIT = process.env.KIT_DEV_API || 'http://127.0.0.1:4050';
  const forwardAsKit = {
    target: KIT,
    changeOrigin: true,
    configure: (proxy) => proxy.on('proxyReq', (req) => req.setHeader('origin', KIT)),
  };

  export default defineConfig({
    plugins: [react()],
    base: '/',
    build: { outDir: 'dist', assetsDir: 'assets', sourcemap: false, modulePreload: { polyfill: false } },
    server: { host: '127.0.0.1', port: 5173, strictPort: true,
              proxy: { '/api': forwardAsKit, '/login': forwardAsKit } },
  });
  ```
  The `server` block is for developers only (`npm run dev`); it is not part of the image. The dev server binds
  127.0.0.1. The proxy rewrites `Origin` and `Host` to the kit's public origin so that the unchanged guard accepts the
  requests. In the dev workflow the developer opens `http://127.0.0.1:5173/login?t=<token>`.
- `web/index.html`:
  ```html
  <!doctype html>
  <html lang="ru">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Proxy Kit</title>
    </head>
    <body>
      <div id="root"></div>
      <script type="module" src="/src/main.jsx"></script>
    </body>
  </html>
  ```
  No inline script or style, and no external URLs.
- `web/src/main.jsx`: `createRoot(document.getElementById('root')).render(<StrictMode><App /></StrictMode>)`, importing `./app.css`.
- `web/src/api.js`:
  - `api(method, path, body)` → `fetch(path, {method, credentials: 'same-origin', headers: body !== undefined ?
    {'Content-Type': 'application/json'} : {}, body: body !== undefined ? JSON.stringify(body) : undefined})`.
  - It throws `ApiError(status, error)` on a non-2xx response. A 401 sets a module-level flag that `App` reads (via a callback).
  - Also `pollJob(id, onUpdate)`: every 1000 ms `GET /api/jobs/<id>?offset=n` until the status is not `running`. It returns a cancel function.
- `web/src/App.jsx`:
  - State: `state` (from `/api/state`), `needLogin`, `selectedExit` (exit_ip or null), `jobId`, `tab` (`servers` | `rules`).
  - Loads `/api/state` on mount, after each finished job, and every 10 s while no job runs (for the proxy heartbeat).
  - Layout: `StatusBar` at the top; then `NlSettings`; then tabs "Серверы" (`ExitList`, or `ServerView` when an exit is
    selected) and "Правила" (`RulesEditor`); `JobLog` at the bottom when `jobId` is set. While a job runs, every component gets
    `busy=true`, which disables all action buttons.
- Components in `web/src/components/`. The behaviour is identical to revision 2 L; only the files are split:
  - `LoginHint.jsx`: shown on 401 (text from revision 2).
  - `StatusBar.jsx`: proxy state (`running`/`idle`/`failed`/`down`), the active inbound (label, port, `network_label`),
    a "Проверить прокси" button (POST /api/health → IP and OK/ошибка), and "Журнал xray / mihomo" (GET /api/proxy/logs,
    last 200 lines in a `<pre>`). When `proxy.state` is `down`, it shows the proxy-down banner with the
    port-7890 explanation and the exact migration commands (README section 8) and `docker compose up -d`. When `failed`, it shows `proxy.error`.
  - `NlSettings.jsx`: form host, user (default `root`), port (22); "Сохранить" (PUT /api/nl); key-mounted state; host-key
    state with a "Проверить ключ хоста" button that opens `HostKeyDialog`; "Обнаружить входы" (POST /api/discover), enabled only when
    NL is saved, the key is mounted and the host is trusted.
  - `HostKeyDialog.jsx`: POST /api/nl/hostkey/scan, a fingerprint list (type + SHA256), the comparison hint from revision 2,
    "Подтвердить" (POST accept with `scan_id`) and "Отмена".
  - `ExitList.jsx`: one card per exit (label, IP, inbound count, active badge). Click → `onSelect(exit_ip)`. Also "Проверить все" (POST /api/check-all).
  - `ServerView.jsx`: the back button; a table of the exit's inbounds (port, `network_label`, remark, check result + time,
    "Проверить", and "Установить" with `window.confirm('Переключить прокси на NL:<port> -> <label>?')` → POST install
    `{confirm:true}`); an "Активен" badge; and a "Показать ссылки" button that opens `LinksModal`.
  - `LinksModal.jsx`:
    - On open, GET `/api/exits/<ip>/links`. For each item, show port, `network_label`, remark, the link in a read-only `<input>`, a
      "Копировать" button (`navigator.clipboard.writeText`, with a fallback that selects the input) and `<QrCode value={link} />`.
    - The links are held only in this component's `useState`, set to `[]` on close, and dropped on unmount.
    - Never use `localStorage`/`sessionStorage`, never log them, and never put them in a URL.
  - `QrCode.jsx`: `import qrcode from 'qrcode-generator'`; `useMemo` → `const q = qrcode(0, 'M'); q.addData(value); q.make();`.
    Render `<svg viewBox="0 0 N N" className="qr" shapeRendering="crispEdges">`, where N = module count + 8 (quiet zone 4), with one
    white background `<rect>` and one `<rect x y width=1 height=1>` per dark module. Do not use `createSvgTag`,
    `createDataURL`, `innerHTML` or `dangerouslySetInnerHTML`.
  - `RulesEditor.jsx`: revision-2 behaviour (GET /api/rules; editable table; add, move, delete; MATCH select; the read-only
    system rule; "Сохранить и применить" → PUT /api/rules → when `job_id` is set, hand it to `App`; show server errors).
  - `JobLog.jsx`: uses `pollJob`; a `<pre>` with the lines; summary and result IP at the end; calls `onDone` when finished.
- `web/src/app.css`: plain CSS (system font, `.card`, table, buttons, `.ok` green, `.fail` red, `pre` max-height 50vh with
  scroll, `.qr { width: 220px; height: 220px; }`, modal overlay), and light/dark via `prefers-color-scheme`.
- Code rules: never use `dangerouslySetInnerHTML`, `innerHTML`, `eval`, `new Function`, `localStorage`, `sessionStorage`, absolute
  `http(s)://` URLs or the `style={{…}}` prop (use classes). All fetches are same-origin relative paths.

### I2. `.gitignore`
Amendment 2c-6: the final `.gitignore` has no `servers/<file>` lines; the whole directory is ignored by
```
servers/*
!servers/README.md
```
(`.gitignore` never hides tracked files, so nothing already committed under `servers/` is affected.)

Keep the existing lines. Append:
```
# Docker-only kit
.env
data/
*.db
*.db-journal
*.db-wal
*.db-shm
__pycache__/
web/node_modules/
web/dist/
```
After step 14, delete only these now-obsolete lines: `bin/.git/`, `servers/vless-links-xhttp.txt`,
`servers/client-install-commands.txt`. Keep all other existing lines, including `server/xray-config.json`,
`servers/xray-*-config.json` (server admin) and the `proxy.env*` lines (admin file).

### J. `README.md` (full rewrite, Russian, keep "Команда proxy" content)
Sections:
1. Что это: схема `приложения → 127.0.0.1:7890 (Mihomo) → Xray → NL → USA1/USA2`.
2. Требования:
   - Docker Engine on WSL/Linux, or Docker Desktop on macOS (Apple Silicon and Intel). The image is built for the arch
     of the machine (amd64/arm64).
   - Internet access to github.com and Docker Hub during the build.
   - An SSH key with root access to NL.
3. Запуск: `git clone … && cd …`, optionally `cp docker/env.example .env` (`KIT_SSH_KEY`, ports),
   `docker compose up -d --build`, then `docker compose exec kit kit token` (amendment 2c-5; no `docker compose logs kit | grep login`).
4. Первая настройка: NL host, confirm the host key, discover, check, install.
5. Правила (сайты): types, policies, MATCH; the system rule.
6. Ссылки для телефона: the server view, copy and QR. Warning: a link is an access key, do not share it.
7. Как приложения используют прокси:
   - `http://127.0.0.1:7890` (HTTP) and `socks5://127.0.0.1:7890`.
   - Shell env lines (the same block as the old installer's).
   - `bash setup-ai-cli-proxy.sh`.
   - macOS system proxy: `networksetup -setwebproxy "Wi-Fi" 127.0.0.1 7890`, `-setsecurewebproxy`, `-setsocksfirewallproxy`,
     and to turn it off, `-setwebproxystate "Wi-Fi" off` etc.
   - WSL note: Windows apps reach `127.0.0.1:7890` through WSL localhost forwarding (default on; if not, use the WSL IP).
   - UDP is not supported through the published port.
8. Переход с установки на хосте (run these BEFORE `docker compose up -d`; the kit never stops them itself):
   - Linux/WSL:
     ```bash
     systemctl --user disable --now mihomo.service xray-mihomo.service xhttp-nl-admin-tunnel.service 2>/dev/null || true
     crontab -l 2>/dev/null | grep -n mihomo || true   # удалите строки mihomo-keepalive вручную: crontab -e
     ss -ltnp 'sport = :7890'                          # должно быть пусто
     ```
   - macOS:
     ```bash
     for L in com.mihomo.proxy com.mihomo.xray; do
       launchctl bootout "gui/$(id -u)/$L" 2>/dev/null || true
       launchctl disable "gui/$(id -u)/$L"
     done
     lsof -nP -iTCP:7890 -sTCP:LISTEN                  # должно быть пусто
     ```
   - Optional cleanup of the old files: `~/.local/bin/{mihomo,xray}`, `~/.config/mihomo/`,
     `~/.config/systemd/user/{mihomo,xray-mihomo,xhttp-nl-admin-tunnel}.service`,
     `~/Library/LaunchAgents/com.mihomo.{proxy,xray}.plist`. This is manual, listed for the user, and the kit does not delete them.
   - Return to the host install: `git checkout <commit before this change>` (see Rollback).
9. Обновление: `git pull && docker compose up -d --build`. Удаление: `docker compose down` (`-v` deletes the DB,
   keys trust and configs).
10. Администрирование серверов: the existing "Команда proxy" content, plus `proxy.env` being admin-only, `server/setup-server.sh`.
    Amendment 2a: when copying that content, DROP every line that mentions `tools/install-server.sh`, `tools/backup.sh`
    or `tools/restore.sh`. Those scripts do not exist in this repo (checked 2026-10-16), and documenting missing tools is wrong.
    Do not replace them with "external" notes. Keep only commands that exist: `./proxy status|logs|check|update`,
    `bash server/setup-server.sh …`.
11. Безопасность: loopback-only ports, token, the data volume holds secrets, links are secrets.
12. Для разработчиков (amendment 2a): the frontend lives in `web/` (Vite + React). Node is not needed to run the kit.
    - To change the UI: run the containers, then either `cd web && npm ci && npm run dev` with a local Node
      ≥ 22.12, or the same commands in the pinned node image via `docker run`. Open `http://127.0.0.1:5173/login?t=<token>`.
    - The dev server proxies `/api` and `/login` to `http://127.0.0.1:4050` (`KIT_DEV_API` overrides it).
    - Lockfile regeneration: the command from section L.

## Data-flow and control-flow description

1. `docker compose up -d --build`:
   - `proxy` starts, creates `/kit-state/{mihomo,logs}` and writes `/kit-state/status.json` `idle`. `/kit-gen` has no `generation.json` yet, so
     7890 is not open (amendment 2d).
   - `kit` starts as root, copies the key, drops to 10001, migrates and seeds the DB, and prints the login URL.
2. The browser opens `/login?t=…`, gets the cookie, then `/` and `/api/state`.
3. `PUT /api/nl`. Hostkey scan → the user compares the fingerprint → accept → `known_hosts` in `/data/ssh`.
4. Discover job: ssh NL with `StrictHostKeyChecking=yes`, the copied key and `UserKnownHostsFile` → rows → upsert.
   Known-exit warnings are logged.
5. Check job: a temporary Xray on 127.0.0.1:18083 inside `kit` → curl ipify → `set_check`. The proxy is not touched.
6. Install job: render → validate (xray -test, mihomo -t) → `write_bundle` (prev saved, generation+1) → `proxy` sees the
   generation and restarts xray/mihomo as needed → status `running` → `kit` verifies ipify via `proxy:7890`
   (system rule → PROXY) == exit IP → `active` saved. On failure: restore prev → generation+1 → job failed.
7. Rules save → `replace_rules` → (if active) apply_rules job → only mihomo restarts → verify.
8. Server view → `GET /api/exits/<ip>/links` → links rendered and QR codes built client-side → cleared on close.
9. Host apps → `127.0.0.1:7890` → Docker port publish → mihomo (allow-lan, bind `*`) → USA socks → Xray → NL → exit.

## API, database, UI, or domain changes

- The API is in J1. The DB schema is v1 (C).
- Docker artifacts: `Dockerfile`, `compose.yaml`, `.dockerignore`, `docker/env.example`.
- Host-side files after the migration: none created by the kit (only the Docker volumes `mihomo-proxy-kit_kit-data`,
  `mihomo-proxy-kit_kit-gen` and `mihomo-proxy-kit_kit-state`; amendment 2d removes `mihomo-proxy-kit_kit-run`, see the 2d migration steps).

## Validation and error-handling rules

- All input is validated server-side: NL (D), rules (G), ids/IPs by regex, `confirm is True`, body ≤ 16 KiB.
- Error JSON `{"error": "<русский текст>"}` never contains secrets, raw stderr or the rejected value.
- Raw subprocess output goes only to the redacted job log.
- Exceptions in a job → job `failed`, and the server keeps running. The proxy supervisor never crashes on a bad generation
  (status `failed`, the old children keep running if hashes do not match).
- Busy → 409. A missing key mount, an untrusted host key, or a proxy that is down each get a specific UI message.

## Authorization and security considerations

Security reviewer checklist:
1. **Ports**: every `ports:` entry in `compose.yaml` starts with `127.0.0.1:`. Verify on the host with
   `ss -ltn` that nothing listens on `0.0.0.0:4050` or `0.0.0.0:7890`.
2. **No Docker socket, no `privileged`, no host network or pid**. `cap_drop: ALL`. `kit` cap_add is limited to
   CHOWN/SETUID/SETGID/DAC_READ_SEARCH, and the effective uid after the drop is 10001 (check `ps -o user,args` in the container).
   `proxy` runs as 10001. `no-new-privileges`, `read_only`, tmpfs `/tmp`.
3. **Image layers**: the `.dockerignore` whitelist; `docker image history --no-trunc` and a filesystem listing show no
   `proxy.env`, `.env`, `servers/`, keys or `.memory`. Base images and assets are digest/sha256 pinned, and the build fails on a mismatch.
4. **SSH key**: bind-mounted read-only with `create_host_path: false`; copied to tmpfs with 0600 owned by 10001; never
   logged, never in the DB, never returned. The `proxy` container has no key.
5. **Host key trust**: `StrictHostKeyChecking=yes` always; keyscan results are bound to a single-use `scan_id` with a 300 s TTL;
   only the scanned lines are written; host and port are validated before `ssh-keyscan`.
6. **Guard**: Host allowlist uses the PUBLIC port; the order of the Origin, Content-Type and Sec-Fetch-Site checks; missing headers; constant-time
   token compare; cookie flags + Max-Age; the token is only in `/data/ui-token` 0600 and is never printed to stdout, so it is not in
   `docker compose logs` (amendment 2c-5); `kit token` prints the URL; `rotate-token` works without a restart; the access log has no query strings.
7. **The links endpoint is the only secret-bearing response**: authenticated, `no-store`, fetched on demand, absent from
   `/api/state` and every other response, never logged (Redactor masks `vless://`); the frontend keeps the links only in component state,
   with no web storage; QR codes are built without innerHTML.
8. **No other secrets in responses**: the `public_inbound` allowlist; job logs are redacted (uuid, pbk, sid, generic UUIDs, vless).
9. **Subprocess safety**: argv lists only; `ssh` with `--`, `BatchMode`, `-F /dev/null`; `ssh-keyscan` and `ssh-keygen` with
   validated host and port; timeouts and process-group kill; env without proxy variables.
10. **Rule injection**: `validate_rule` forbids `,`, `#`, quotes, whitespace and newlines; rendering re-validates.
11. **Mihomo `allow-lan: true`** is reachable only through the loopback publish and the project's compose network (the `kit`
    container). No other services are on that network.
12. **File modes**: `/data`, `/kit-gen` and `/kit-state` 0700; db, logs, configs, known_hosts, token, `status.json` and `cache.db` 0600; `umask 077`.
13. **Static and CSP**: the static map is built at startup from `KIT_WEB_ROOT` (no request-path joins). The CSP is exactly
    `default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`
    (amendment 2d-B). `'unsafe-inline'` appears only in `style-src`, and `script-src` is `'self'` alone (no `'unsafe-inline'`, no `'unsafe-eval'`).
    The built `index.html` has no inline scripts or styles, `web/src` has no `style={{`, `innerHTML` or `dangerouslySetInnerHTML`, and there are no CORS headers.
    Frontend supply chain: exact pins + committed lockfile with integrity hashes; `npm ci --ignore-scripts` in a
    digest-pinned node stage; `node_modules` and dev tooling are not in the final image (only `web/dist`); the dev
    server binds 127.0.0.1 only and is never started in Docker.
14. **kit CLI** drops root before touching files; it is a client to the server and does not bypass the guard.
15. **Rollback** on a failed install restores the previous working config, so a failed install does not leave the user without a proxy.
16. **Volume split (amendment 2d) and `/kit-state` as hostile input for `kit` (amendment 2c).**
    - `compose.yaml`: `proxy` mounts `kit-gen:/kit-gen:ro` and `kit-state:/kit-state`; `kit` mounts `kit-gen:/kit-gen` and
      `kit-state:/kit-state:ro`. No `kit-run` and no `/run-kit` remain anywhere.
    - Verify in the running stack: `docker compose exec -T proxy touch /kit-gen/x` fails (read-only file system), and so does
      `docker compose exec -T kit touch /kit-state/x`.
    - `proxy` therefore cannot change `generation.json`, the configs or `prev/`. A rollback can only reinstall a bundle that `kit` wrote.
    - Every `kit` read under `/kit-state` (status, logs) goes through `open_state_dir` (`O_DIRECTORY|O_NOFOLLOW` at the top dir and at `logs`,
      never creating anything), then a `dir_fd` open with `O_NOFOLLOW` and an `fstat` `S_ISREG` check. The log reader also opens `O_NONBLOCK`,
      refuses `st_nlink != 1` and reads at most 256 KiB.
    - `status.json` content is untrusted: the `proxy_state` fields go to the UI as data only, and `wait_applied` uses only `generation` and `state`.
    - Every `kit` write under `/kit-gen` goes through a directory fd (2c-2). There is no path-based `chmod`, `read_text` or `mkdir(exist_ok=True)`
      on `/kit-gen` or `/kit-state` entries in `kit_apply.py`, `server.py` or `kit_proxy.py`.
17. **Config integrity before spawn (amendment 2c-4).** `kit_proxy` re-hashes a child's config against the applied generation
    immediately before every spawn, including crash restarts. Residual window: between that check and the child's own open of the file.
    After 2d, only `kit` can write the file, so the window only matters for a torn write by `kit`.
18. **Proxy writable set (amendment 2d).** `proxy` can write only `/kit-state` (`status.json`, its temp file, `logs/*.log{,.1}`,
    `mihomo/cache.db` and the geo symlinks) and tmpfs `/tmp`. Its root fs is read-only and `/kit-gen` is read-only. mihomo runs with
    `-d /kit-state/mihomo -f /kit-gen/mihomo/config.yaml`.
19. **Import-only mode (amendment 2e).** `POST /api/inbounds/import` is guarded like every API call and capped (40 links, 1024 chars each, 16 KiB body).
    Parsing is allowlist-based (`kit_import.parse_link`), all-or-nothing, and never echoes input. Imported secrets are stored in `/data/kit.db` and
    are returned only by the links endpoint. Import, install, check, rules and links run no `ssh`, `ssh-keyscan` or `ssh-keygen` (test-enforced). An empty
    `docker/no-key` placeholder counts as "no key" (`key_available`); the key bind stays read-only with `create_host_path: false`.

**Known risks:**
- Finding 6, cookie scoping (owner decision pending; not implemented): the session cookie is the static token itself. A random server-side session id is the planned hardening; it is a design change, so it is left open until the owner decides.
- **CLOSED by amendment 2d: kit-run mount split.** `kit-gen` is read-only for `proxy` and `kit-state` is read-only for `kit`. A compromised
  `proxy` can no longer rewrite the configs, `generation.json` or `prev/`, so the "rollback reinstalls a proxy-chosen config" risk below no longer applies.
- **Remaining after 2d (accepted):**
  - A compromised `proxy` can still write anything into its own `kit-state`. It can forge `status.json` (claim `running` or any generation, fake
    `error` text), plant symlinks, FIFOs or hard links, and fill `logs/`. `kit` treats all of it as untrusted input through the 2c readers, which are
    kept and now also refuse a symlinked `logs` dir. A forged `running` cannot activate a bundle by itself: `install` still requires
    `verify_exit` to see the expected exit IP.
  - A compromised `proxy` can still control traffic through 7890, including what `verify_exit` sees (the ipify answer goes through it). That is inherent
    to the proxy's role, and TLS to ipify limits it to routing choices.
  - Disk use: `kit-state` has no quota. Log rotation bounds the supervisor's own logs, but a compromised `proxy` can fill the Docker disk.
    This is not mitigated (no volume quota on the local driver).
  - CSP `style-src 'unsafe-inline'` (amendment 2d-B): CSS injection only, no script execution; see the 2d-B residual-risk note.
  - Imported links (amendment 2e) are VLESS client secrets stored in the importing user's DB. That instance can use them only as a VPN client of NL;
    it has no SSH or panel access. Revocation is done on NL by removing or rotating that client's uuid. Whoever holds that instance's UI token can
    read the links through the links endpoint.
- Historical, superseded by amendment 2d: stronger kit-run mount split: `kit-run` is shared read-write by both containers. Splitting it into a kit-writable and a proxy-read-only mount is the planned hardening; it changes the compose layout, so it is left open until the owner decides.
  Escalation decision (amendment 2c): **recommended as a separate follow-up change, not required for this change.** Reasons:
  (1) after 2c-1..2c-3 every known `kit`-side symlink/FIFO/hard-link vector on the shared volume is closed by fd-based checks;
  (2) the split does not remove the class: `kit` must still read `status.json` and `logs/*.log` written by `proxy`, so the 2c readers are needed in either layout;
  (3) it changes the compose layout and the existing `kit-run` volume (migration), and needs the mihomo home dir (`-d`, cache, geo links) moved
  to a proxy-writable volume with the config passed by `-f`, which must be re-verified against mihomo v1.19.32 docs;
  (4) what it does add is that `proxy` can no longer rewrite the configs or `generation.json` that `kit` reads back for `prev/` and rollback.
  Residual risk until then: a compromised `proxy` can poison `prev/` and the current configs, so a later rollback may reinstall a proxy-chosen
  config (the proxy is already compromised in that case, and `kit` validates every bundle with `xray run -test` / `mihomo -t` before writing).

## Backward-compatibility considerations

- This is a breaking change by design: the host install path is removed (after the user's yes).
- Existing host users must stop the old services first (README section 8). Their old shell env blocks keep working.
- `proxy` admin commands keep working: they still read `proxy.env`, and only `check` changes (it needs the containers up).
- The superseded change's useful parts are reused: the port map as `KNOWN_EXITS`, the Xray client JSON as a golden test,
  and the pinned mihomo amd64 hash (identical).

## Test strategy

Host commands (no Docker needed), repo root:
```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile ui/*.py tools/proxy_cli.py
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -e npm_config_cache=/tmp/.npm -v "$PWD/web":/web -w /web \
  node:24.21.0-alpine3.23@sha256:9ec4a2e289874ed0d722e1772ec2de45d2801541db8612f3638b26f128c69ac2 \
  sh -c 'npm ci --ignore-scripts --no-audit --no-fund && npm run build'
WEB_DIST=web/dist python3 -m unittest tests.test_web_contract -v
command -v shellcheck >/dev/null && shellcheck tests/docker_smoke.sh || echo "shellcheck not installed"
docker compose config -q
```
Unit tests set `KIT_DATA_DIR`, `KIT_GEN_DIR`, `KIT_STATE_DIR` (amendment 2d; `KIT_RUN_DIR` is gone), `KIT_GEO_DIR` and `KIT_SSH_KEY_FILE` to temp dirs. They never run real ssh to NL,
never touch `~/.config`, and never bind 4050 or 7890. Tests load ui modules via `sys.path.insert(0, ROOT/'ui')`.

| File | Cases |
|---|---|
| `test_kit_nl.py` | import has no side effects; `rows_from_config` on the fixture → 5 rows (ws skipped) with exit, exit_tag, flow, grpc, xhttp, `pbk=='PUB-'+priv`; `REMOTE == REMOTE_PARSE + REMOTE_DRIVER`; `ssh_command` defaults, `-p`, `-i`+`IdentitiesOnly`, `UserKnownHostsFile` + `GlobalKnownHostsFile=/dev/null`, `--` before target; `make_link` uses `server_ip` and has `type=`, `pbk=`, `fp=chrome` |
| `test_kit_db.py` | v1 tables incl. rules/kv/active; migrate is idempotent; modes 0600/0700; seeding happens once (delete all rules → reconnect → still empty); `replace_rules` positions; `get_match` default; active set/get; upsert keeps check_*; `public_inbound` allowlist (no uuid/pbk/sid/sni/xhttp_json/grpc_service); user_version 99 → RuntimeError |
| `test_kit_guard.py` | revision-1 matrix with public port 14050 (Host `127.0.0.1:4050` rejected when public is 14050); cookie has `Max-Age=2592000`; CSP; no Access-Control; `GET /assets/index-abc.js` without a cookie → allowed, `GET /static/app.js` → 404 (amendment 2a) |
| `test_kit_discovery.py` | validate_nl accept/reject (no echo); `installable` (2088 tcp True, 443 False, ws False, empty exit False); `exit_label`; `known_exit_warnings` (2083 on USA2 → one warning); `fingerprints` parsing with stubbed `ssh-keygen` output; `trust_host_key` on a temp known_hosts (replace + 0600); discover error mapping (host key, permission, missing key) with `kit_nl.discover_rows` stubbed |
| `test_kit_render.py` | golden `xray_client_config` for xhttp(2087)/tcp(2088)/grpc(2089) == literal dicts (from the superseded spec's parity contract); `mihomo_config` text: starts with `mixed-port: 7890\nallow-lan: true\nbind-address: "*"`, system rule first, disabled rules omitted, MATCH last; if `yaml` importable, `safe_load` gives proxies[0] == `{'name':'USA','type':'socks5','server':'127.0.0.1','port':18080,'udp':True}` and the DNS dict equals the old `tools/mihomo-config.py` DNS dict (literal copy); `DEFAULT_RULES` contains the 12 non-MATCH rules of the old `tools/mihomo-config.py` in the same relative order, plus `DOMAIN-SUFFIX,xn--p1ai,DIRECT` right after `ru` (13 total); `validate_rule` table (IDN `рф`→`xn--p1ai`, `a,b`, `x\ny`, `#`, `"`, empty, 254 chars, bad GEOIP, CIDR normalisation, no_resolve dropped for DOMAIN); `validate_rules` (>500, duplicate, bad match); `KNOWN_EXITS` ports equal the superseded map; `mihomo -t` on a rendered config without GEO rules — `skipUnless` `$KIT_MIHOMO_BIN` or `~/.local/bin/mihomo` is executable; `xray run -test` on the golden configs — `skipUnless` `$KIT_XRAY_BIN` or `~/.local/bin/xray` |
| `test_kit_apply.py` | `write_bundle` files 0600, prev copied, generation+1 with correct hashes, `None` keeps a file; `restore_prev`; `wait_applied` with a status file written by a thread; `proxy_state` down/stale/running; `install` success and failure+rollback with stubbed `validate_bundle`, `wait_applied`, `verify_exit`; `apply_rules` without active → ok, no files written |
| `test_kit_proxy.py` | `read_generation` (missing, bad JSON, wrong types); `plan_restarts` table; `status_is_stale`; `write_status` atomic + 0600 + heartbeat; `Supervisor` with fake children (`python3 -c` scripts opening sockets on ephemeral ports via patched port constants) is optional — skip if it is not simple |
| `test_kit_jobs.py` | Redactor; child_env; JobRunner Busy; run_streamed lines; timeout kill; log 0600; `install_argv` no longer exists |
| `test_kit_priv.py` | non-root → no-op; `copy_key` to a temp path → 0600 and same bytes |
| `test_kit_server.py` | ephemeral server (`bind='127.0.0.1', port=0`, public port 14050, stubs, `KIT_WEB_ROOT` = temp dir with `index.html` and `assets/index-abc.js`): `/` 200 html; `/assets/index-abc.js` 200 `text/javascript`; `/assets/../index.html`, `/assets/%2e%2e/x`, `/assets/sub/x.js`, `/assets/missing.js`, `/src/main.jsx` → 404; `/` with no index.html → 503; login 303/403; state 200 and contains no uuid/pbk/sid/`vless://`; links endpoint returns links with `Cache-Control: no-store`, 404 for an unknown exit, 401 without cookie; rules GET/PUT valid/invalid; install without confirm → 400; hostkey scan/accept with stubbed `scan_host_key`/`fingerprints` (unknown scan_id → 404, second accept → 404); health with stubbed curl |
| `test_web_contract.py` (replaces `test_kit_static.py`) | **Source contract** (always runs): `web/package.json` dependencies are exactly `{react: 19.3.0, react-dom: 19.3.0, qrcode-generator: 2.0.4}` and devDependencies exactly `{vite: 8.3.2, @vitejs/plugin-react: 6.1.1}`, with no `^`/`~`; `web/package-lock.json` exists, `lockfileVersion` 3, and the root package's versions match; `vite.config.js` contains `polyfill: false` and `sourcemap: false`; `web/index.html` has exactly one `<script type="module" src="/src/main.jsx">`, no inline script body, no `<style>`, no `on*=` attributes; no file under `web/src/` contains `dangerouslySetInnerHTML`, `innerHTML`, `eval(`, `new Function`, `localStorage`, `sessionStorage`, `http://`, `https://` or `style={{`. **Built-output contract** (`skipUnless` `WEB_DIST` env or `web/dist/index.html` exists): every `<script>` has a `src` starting with `/assets/` and an empty body; every `<link>` `href` starts with `/assets/`; no `<style>`, no `on*=`, no `//` or `http` URLs; every referenced file exists; every file in `dist/assets` has a name matching the server allowlist regex; no `.map` files; no built JS contains `eval(` or `new Function` |
| `test_docker_files.py` | `compose.yaml` text: no `docker.sock`, `privileged`, `network_mode`, `pid:`; each line under `ports:` matches `- "127.0.0.1:`; `read_only: true`; `cap_drop: [ALL]`; `create_host_path: false`. Dockerfile contains the 4 asset hashes, 3 geodata hashes, the python and mihomo base digests, the line `FROM --platform=$BUILDPLATFORM node:24.21.0-alpine3.23@sha256:9ec4a2e289874ed0d722e1772ec2de45d2801541db8612f3638b26f128c69ac2 AS web`, `npm ci --ignore-scripts`, `COPY --from=web /web/dist/ /app/web/`, `KIT_WEB_ROOT=/app/web`, `USER 10001:10001`, and no `COPY . `. `compose.yaml` has exactly one `build:` line (under `kit`), `proxy` has `pull_policy: never`, the image line is
`${KIT_IMAGE:-mihomo-proxy-kit:local}`, and there is no `depends_on`. `.dockerignore` first line is `*` and it contains `!web/`, `web/node_modules`, `web/dist` |
| **2d** `test_kit_guard.py` | `test_csp_exact`: `kit_guard.SECURITY_HEADERS['Content-Security-Policy'] == CSP` where `CSP` is the exact 2d-B string (module-level constant in the test). `test_csp_inline_only_for_styles`: split the CSP on `;`, strip, map directive → sources; `'unsafe-inline'` occurs only in `style-src`; `script-src` sources == `["'self'"]`; no `'unsafe-eval'` anywhere; `style-src` sources == `["'self'", "'unsafe-inline'"]`. The existing `script-src 'self'` / `img-src` / `data:` / no `Access-Control-*` asserts stay. |
| **2d** `test_kit_server.py` | `test_security_headers_present`: `assertEqual(headers['Content-Security-Policy'], <exact 2d-B string>)` (replaces the substring check). setUp: `KIT_RUN_DIR` → `KIT_GEN_DIR` = `<tmp>/gen` and `KIT_STATE_DIR` = `<tmp>/state` (create both 0700, plus `state/logs`); every existing proxy-log test writes into `state/logs`. New `test_proxy_logs_refuses_symlinked_logs_dir`: `state/logs` is a symlink to a temp dir that contains `xray.log` with a line → `GET /api/proxy/logs?name=xray` 200 with `lines == []`. |
| **2d** `test_kit_apply.py` | setUp sets `KIT_GEN_DIR`/`KIT_STATE_DIR` (no `KIT_RUN_DIR`); existing cases read and write under `gen/` (configs, generation, prev) and put `status.json` under `state/`. New: `test_read_status_from_state_dir` (status written in `state/` is returned; one written in `gen/` is ignored); `test_read_status_symlinked_state_dir_is_none` (`state` is a symlink → `None`); `test_open_state_dir_missing_is_none`; `test_write_bundle_never_touches_state_dir` (skip if `os.geteuid() == 0`: `chmod 0o500` on `state/`, run `write_bundle(x, m)` twice and `restore_prev()`, `sorted(os.listdir(state))` unchanged, restore mode in `finally`); `test_first_install_without_prior_generation` (empty `gen/` without `mihomo/` and `prev/` → `write_bundle(x, m) == 1`, both files and `generation.json` exist, `prev/` empty); `test_apply_rules_active_without_xray_file` (active inbound in DB, no `gen/xray-client.json` → `('ok', None, 'Правила сохранены; будут применены при установке')`, no file written). |
| **2d** `test_kit_proxy.py` | setUp sets `KIT_GEN_DIR`, `KIT_STATE_DIR`, `KIT_GEO_DIR` (temp geo dir with 3 empty files). `test_start_creates_state_only`: `Supervisor().start()` creates `state/mihomo` (3 symlinks), `state/logs` and `state/status.json` (`state == 'idle'`), and `os.listdir(gen)` is unchanged. `test_proxy_cannot_write_config` (skip if `os.geteuid() == 0`): write a valid generation (`generation.json` + `xray-client.json` + `mihomo/config.yaml` with matching sha256) into `gen/`, then `chmod 0o400` on the files and `0o500` on `gen/mihomo` and `gen/`. Patch `kit_proxy.subprocess.Popen` with a recorder that returns a fake proc (`poll()` → `None`, no-op `send_signal`/`wait`/`kill`) and patch `kit_proxy._wait_port` → `True`. Run `start()`, `_check_generation()`, `_apply()`. Assert `state == 'running'`; the recorded commands are exactly `[xray_bin, 'run', '-config', str(gen/'xray-client.json')]` and `[mihomo_bin, '-d', str(state/'mihomo'), '-f', str(gen/'mihomo'/'config.yaml')]`; the recursive listing of `gen/` (names + sha256) is unchanged; log files exist under `state/logs`. Restore modes in `finally`. `test_start_symlinked_state_dir_fails`: `state/logs` is a symlink → status `failed`, error `Каталог /kit-state повреждён`. Also grep the module source: no `KIT_RUN_DIR` and no `run_dir`. |
| **2d** `test_kit_render.py` | `mihomo_config(...)` output contains none of `proxy-providers`, `rule-providers`, `external-ui`, `external-controller`, `geo-auto-update: true`; `xray_client_config(...)['log'] == {'loglevel': 'warning'}` (no file logs). |
| **2d** `test_docker_files.py` | Text: `compose.yaml` and `Dockerfile` contain no `kit-run`, `/run-kit` or `KIT_RUN_DIR`; Dockerfile contains `KIT_GEN_DIR=/kit-gen`, `KIT_STATE_DIR=/kit-state` and `chown 10001:10001 /data /kit-gen /kit-state`. `test_compose_volume_modes` (`skipUnless shutil.which('docker')` and `docker compose version` exits 0): run `docker compose -f compose.yaml config --format json` with `env={**os.environ, 'KIT_SSH_KEY': <temp file>}` and `cwd=ROOT`, timeout 30; non-zero exit → fail. In the JSON, `services.proxy.volumes` contains `{type: volume, source: kit-gen, target: /kit-gen, read_only: True}` and a `kit-state` → `/kit-state` entry without `read_only` true; `services.kit.volumes` contains `kit-gen` → `/kit-gen` without `read_only` true and `{source: kit-state, target: /kit-state, read_only: True}`; `sorted(top-level volumes) == ['kit-data', 'kit-gen', 'kit-state']`; both services keep `read_only: True`, `cap_drop == ['ALL']`, `security_opt` contains `no-new-privileges:true`; every published port has `host_ip == '127.0.0.1'`. |
| **2d** `test_web_contract.py` | No change. It asserts no CSP string. Its `<style>`, `style={{`, `innerHTML` and `dangerouslySetInnerHTML` bans stay and must still pass. |
| **2e** `test_kit_import.py` (new) | Fixture links built with `kit_nl.make_link` from literal rows (fake uuid `11111111-2222-3333-4444-555555555555`, pbk `'A'*43`, sid `abcd`, sni `www.example.com`, host `185.0.2.10`, exit `149.28.240.154`) for tcp (flow `xtls-rprx-vision`, port 2088), grpc (`serviceName` `svc`, multi, port 2089) and xhttp (path `/dl`, mode `auto`, host `cdn.example.com`, port 2087). `parse_link` returns the exact expected dict for each, including `source='import'`, `nl_host`, `exit_ip`, `remark`, `xhttp_json` (sorted keys), `grpc_multi=1`. Reject, each with an `assertRaises(ValueError)` whose message does NOT contain the offending substring: bad scheme (`vmess://`), uuid `not-a-uuid`, uuid with 31 hex, pbk 42 chars, pbk with `+`, sid `abc` (odd), sid 18 hex, `security=tls`, `type=ws`, unknown key `spx=/`, a duplicated key (`sni=a&sni=b`), port 443, port 0, IPv6 host `[::1]`, host with `_`, missing label, label `NL -> example.com TCP x` (no IPv4 exit), label `NL -> 1.2.3.4 gRPC x` on a tcp link (mode mismatch), xhttp without `path`, grpc without `serviceName`, tcp with `serviceName`, a control char in the label. `parse_links`: two identical links → error `дубликат` at index 2; 41 links are rejected by the server cap (see server row). `kit_import` source has no `subprocess` import. |
| **2e** `test_kit_db.py` | v2: `PRAGMA user_version == 2`; a v1 DB (created with `V1_SQL` + `user_version=1` and one row) migrates to v2 with `source='discover'`, `nl_host=''`. `replace_imported`: insert 2 → ids; re-import the same 2 → same ids, `check_*` kept; import a set with 1 of them → `removed == 1`; an `active` row pointing at the removed id becomes NULL; a row conflicting with a `source='discover'` row raises `ImportConflict` with the right index, and the DB is unchanged (rollback). `upsert_inbounds` does not set `present=0` on import rows. `public_inbound` has `source` and no `nl_host`. The user_version 99 → RuntimeError case stays. |
| **2e** `test_kit_server.py` | `POST /api/inbounds/import`: the 3 fixture links → 200, `imported == 3`, and the response text contains none of the uuid, pbk, sid, sni, host or `vless://`. One bad link among good ones → 400 with `errors == [{'index': 2, 'error': …}]`, nothing stored, and the response does not contain a unique marker put into the bad link. `[]` → 400. 41 links → 400. A 17 KiB body → 413 (existing limit). A running job → 409. Without a cookie → 401. **Import-then-install without SSH:** no NL settings in the DB, `KIT_SSH_KEY_FILE` points to a missing file. Patch `kit_nl.discover_rows`, `kit_nl.ssh_command`, `kit_discovery.scan_host_key`, `kit_discovery.discover` with stubs that raise `AssertionError('ssh used')`, and patch `subprocess.run` and `subprocess.Popen` with wrappers that raise `AssertionError` when `argv[0]` basename is `ssh`, `ssh-keyscan` or `ssh-keygen` and otherwise delegate. Stub `kit_apply.validate_bundle` (no-op), `kit_apply.wait_applied` (→ `{'state':'running','generation':gen}`) and `kit_apply.verify_exit` (→ `(True, '149.28.240.154')`). Import → `POST /api/inbounds/<tcp id>/install {"confirm": true}` → 202 → poll `/api/jobs/<id>` until not running → `ok`. `gen/xray-client.json` has `outbounds[0].settings.vnext[0].address == '185.0.2.10'` and port 2088. `/api/state` `active.inbound_id` == that id, `nl_key_mounted is False`, and the state text contains no uuid, pbk, sid, sni or `vless://`. `GET /api/exits/149.28.240.154/links` → 200, and items contain links with host `185.0.2.10` (the only allowed secret response). `PUT /api/rules` with an imported active inbound and no NL settings → 200 (no `_nl_or_400`). `POST /api/discover` with no key → 400 key message. |
| **2e** `test_kit_discovery.py` | `key_available`: missing → False, empty file → False, 1-byte file → True. `row_nl_host`: import row → its `nl_host`; discover row + nl → `nl['host']`; discover row + `None` → `None`. `links_for_exit` with mixed rows and `nl=None` → only import rows. |
| **2e** `test_kit_priv.py` | `prepare_and_drop` is root-only and is not run in tests. Add a unit test for the new pure helper `kit_priv.should_copy_key(mount) -> bool` (regular file with size > 0); `prepare_and_drop` uses it. Empty → False, missing → False, non-empty → True. |
| **2e** `test_kit_render.py` | `xray_client_config` raises `ValueError` for a row with a bad uuid, pbk, sid or sni (each). The golden configs still pass unchanged. The new regex constants exist with the exact patterns from 2e-2. |
| **2e** `test_docker_files.py` | `compose.yaml` contains `source: ${KIT_SSH_KEY:-./docker/no-key}` and `create_host_path: false`. `docker/no-key` exists with size 0. In `test_compose_volume_modes`, a second `docker compose config --format json` run without `KIT_SSH_KEY` (removed from the env) gives the `kit` bind source `== str(ROOT / 'docker' / 'no-key')` with `read_only: True`. `docker/env.example` documents `KIT_SSH_KEY`. |
| **2e** `test_web_contract.py` | Source contract: `web/src/components/ImportLinks.jsx` exists. The existing bans (no `style={{`, `innerHTML`, `localStorage`, `sessionStorage`, `http(s)://`) cover it automatically. No dependency changes. |

Docker smoke test `tests/docker_smoke.sh` (bash, `set -euo pipefail`). It uses project `kitsmoke` and ports 14050/17890, so the user's
live 4050/7890 are untouched:
```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"; cd "$ROOT"
export KIT_UI_PORT=14050 KIT_PROXY_PORT=17890 KIT_IMAGE=mihomo-proxy-kit:smoke
T="$(mktemp -d)"; ssh-keygen -q -t ed25519 -N '' -f "$T/dummy_key"; export KIT_SSH_KEY="$T/dummy_key"
DC=(docker compose -p kitsmoke)
cleanup() { "${DC[@]}" down -v >/dev/null 2>&1 || true; docker image rm "$KIT_IMAGE" >/dev/null 2>&1 || true; rm -rf "$T"; }
trap cleanup EXIT
docker image rm "$KIT_IMAGE" >/dev/null 2>&1 || true   # first-run path: no prior image
"${DC[@]}" up -d --build                                         # exactly the user's command (plus -p and ports)
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
docker run --rm --entrypoint sh "$KIT_IMAGE" -c 'test ! -e /app/proxy.env && test ! -e /app/servers && ls /app' | grep -qx ui
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
```
The implementer may adjust only the mechanics (e.g. how `ps` output is matched), never the assertions. It runs without contacting NL.

Manual E2E (only with the user's explicit approval; uses the real NL and SSH key, still on ports 14050/17890 so the live
proxy is untouched):
- `KIT_SSH_KEY=~/.ssh/<key> KIT_UI_PORT=14050 KIT_PROXY_PORT=17890 docker compose -p kitsmoke up -d`
- NL settings → scan → compare with `ssh-keygen -lF 185.245.107.19` → accept → discover (8 inbounds) → check-all → install
  2088
- `curl --noproxy '*' -x http://127.0.0.1:17890 https://api.ipify.org` → `149.28.240.154`
- Rules: add `DOMAIN-SUFFIX,ifconfig.me,DIRECT` → applied → `curl -x … https://ifconfig.me` shows the host's own IP
- Links view: 4 links for USA2; import one into a phone client
- `docker compose -p kitsmoke down -v`

macOS (user only): `docker compose up -d --build` on Apple Silicon builds arm64; same E2E.

## Acceptance criteria

1. `docker compose up -d --build` on WSL brings up `kit` and `proxy` with `restart: unless-stopped`. Ports are published on
   127.0.0.1 only (`ss -ltn`). There is no Docker socket mount.
2. The image is built for the host arch; mihomo, xray and geodata are SHA-256 verified at build time; there are no secrets in the image (smoke).
3. `kit` serves as uid 10001 after the drop; `proxy` runs as uid 10001; read-only rootfs; caps as specified.
4. Login URL from `kit token` only; `docker compose logs kit` contains no token (amendment 2c-5); guard tests pass (public port aware).
5. The DB in the `kit-data` volume has schema v1 with rules seeded once from the old defaults; files 0600, dirs 0700.
6. Host key scan/confirm flow works; SSH uses `StrictHostKeyChecking=yes` with the volume's `known_hosts`.
7. Discover, check, install (render → validate → apply → verify → rollback on failure) and rules apply work per spec
   (unit tests; manual E2E with approval).
8. Server view shows `vless://` links and QR codes only through the links endpoint; no other response or log contains secrets.
9. The UI shows "proxy down / port 7890 busy" with migration commands and never stops host services.
10. `python3 -m unittest discover -s tests -v` passes; `py_compile`, the containerised `npm ci && npm run build`,
    `WEB_DIST=web/dist python3 -m unittest tests.test_web_contract`, and `docker compose config -q` pass;
    `bash tests/docker_smoke.sh` prints `SMOKE OK`.
11. After the user's yes: every REMOVE path is gone, and the test suite still passes. The reference grep (amendment 2a)
    must print nothing:
    ```bash
    git grep --untracked -nE 'install\.sh|set-proxy-env|unregister\.sh|vless\.sh|mihomo-config\.py|export-vless|install-client|macos-chain|mihomo-keepalive|fill-proxy-env|migrate-docker|task\.md|bin/(mihomo|xray)-' -- . \
      ':!openspec/**' ':!docs/history-before-cleanup.md' ':!AGENTS.md' ':!.memory/**' ':!.memoryignore' \
      ':!setup-ai-cli-proxy.sh' ':!server/**' ':!tools/proxy_update.py' ':!proxy' ':!README.md'
    ```
    Allowlist rules:
    - `openspec/**`, `docs/history-before-cleanup.md` and `AGENTS.md` are history or instructions and may mention the removed names.
    - `setup-ai-cli-proxy.sh`, `server/**`, `tools/proxy_update.py` and `proxy` are KEEP files the implementer may not edit. Any hit in
      them is REPORTED to the orchestrator, not fixed. Check them with the same pattern restricted to those paths.
    - `README.md` may match only the token `mihomo-keepalive`, and only inside section 8 "Переход с установки на хосте"
      (the crontab cleanup hint). Check: `git grep -nE '<same pattern>' -- README.md` prints only such lines.
    - Code and tests in `ui/`, `web/` and `tests/` must not match. Comments say "former host installer" instead of file names.
12. README describes only the Docker flow plus server admin; `proxy check` uses `kit check`.
13. (amendment 2a) The frontend is the Vite React project in `web/` with exact pins and a committed lockfile. The image
    contains `/app/web/index.html` and `/app/web/assets/*` and no `node_modules` or `ui/static`. The built-output contract
    passes on the image's `/app/web` (smoke). There are no vendored JS files in the repo.
14. (amendment 2d-A) `compose.yaml` mounts `kit-gen` rw in `kit` and `:ro` in `proxy`, and `kit-state` rw in `proxy` and `:ro` in `kit`.
    `kit-run`, `/run-kit` and `KIT_RUN_DIR` appear nowhere in `Dockerfile`, `compose.yaml` or `ui/`. In `tests/` they appear only
    inside the negative assertions of `test_docker_files.py`, `test_kit_proxy.py` and `docker_smoke.sh`. In `README.md` they appear only
    in the migration subsection.
    The smoke test proves that `proxy` cannot write `/kit-gen` and `kit` cannot write `/kit-state`. mihomo runs with
    `-d /kit-state/mihomo -f /kit-gen/mihomo/config.yaml`. A fresh stack with no prior generation starts with `proxy` `idle`.
    All existing hardening is unchanged (read_only, cap_drop ALL, no-new-privileges, uid 10001, tmpfs `/tmp`, loopback-only ports, no docker.sock).
15. (amendment 2d-B) Every response carries exactly the 2d-B CSP. In the browser, opening a modal Dialog produces no CSP
    violation in the console and body scroll is locked (manual check on `docker compose -p kitsmoke` ports 14050/17890).
16. (amendment 2e) With no `.env`, `docker compose up -d --build` starts both services and the UI shows «Импорт ссылок» instead of the NL settings.
    Pasting owner-made links and pressing «Установить» installs with no SSH and no NL settings (unit-tested with ssh stubs that raise; manual check
    on project `kitsmoke`). `/api/state` stays secret-free. Discovery still works when `KIT_SSH_KEY` is set.

## Rollback considerations

- Code: `git revert` of this change's commit(s). With open question 2 at its default, the commit before this change holds the
  complete host installer (including the superseded USA2/macOS work).
- Runtime: `docker compose down` (keeps the data volumes), or `down -v` (removes them). Re-enable the old host services:
  - Linux: `systemctl --user enable --now mihomo.service xray-mihomo.service`
  - macOS: `launchctl enable gui/$(id -u)/com.mihomo.proxy; launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.mihomo.proxy.plist`
    (the same for `com.mihomo.xray`)

  This works only if the user did not delete the old files.
- A failed install inside the kit rolls back automatically to the previous generation.
- Amendment 2d: `git revert` of the 2d commit restores `kit-run`. Then `docker compose down` (without `-v`), `docker compose up -d --build`,
  re-install from the UI (the recreated `kit-run` is empty), and optionally
  `docker volume rm mihomo-proxy-kit_kit-gen mihomo-proxy-kit_kit-state`. The CSP part reverts with the same commit and needs no runtime step.

## Explicit list of files allowed to be modified

New: `Dockerfile`, `.dockerignore`, `compose.yaml`, `docker/env.example`, `ui/kit_nl.py`, `ui/kit_render.py`,
`ui/kit_apply.py`, `ui/kit_proxy.py`, `ui/kit_priv.py`, `ui/kit_cli.py`, `ui/server.py`,
`web/package.json`, `web/package-lock.json` (generated by the command in L), `web/vite.config.js`, `web/index.html`,
`web/src/main.jsx`, `web/src/App.jsx`, `web/src/api.js`, `web/src/app.css`, `web/src/components/*.jsx` (the 10 files in L),
`tests/test_kit_*.py` (10 files), `tests/test_web_contract.py`, `tests/test_docker_files.py`, `tests/docker_smoke.sh`.
Must not exist after the change: `ui/static/` (if an earlier run created it, delete it).

Changed: `ui/kit_db.py`, `ui/kit_guard.py`, `ui/kit_discovery.py`, `ui/kit_jobs.py`, `README.md`, `.gitignore`,
`tools/proxy_cli.py` (`check` only), `proxy.env.example` (rewrite), the one status line in
`openspec/changes/nl-usa2-ports-macos-xray-chain/proposal.md`, and this change's openspec files (notes/checkboxes).

Deleted (step 14 only, after the user's yes): exactly the REMOVE list.

Amendment 2d (step 17) may change only: `compose.yaml`, `Dockerfile`, `ui/kit_apply.py`, `ui/kit_proxy.py`, `ui/kit_priv.py`,
`ui/server.py`, `ui/kit_guard.py`, `tests/test_kit_apply.py`, `tests/test_kit_proxy.py`, `tests/test_kit_server.py`,
`tests/test_kit_guard.py`, `tests/test_kit_render.py`, `tests/test_kit_priv.py` (only if it references `KIT_RUN_DIR`),
`tests/test_docker_files.py`, `tests/docker_smoke.sh` and `README.md`. `ui/kit_render.py`, `web/**` and `tests/test_web_contract.py` are NOT changed by 2d.

Amendment 2e (step 18) may change only: new `ui/kit_import.py`, `tests/test_kit_import.py`, `docker/no-key` (empty),
`web/src/components/ImportLinks.jsx`; changed `ui/kit_db.py`, `ui/kit_discovery.py`, `ui/kit_jobs.py`, `ui/kit_apply.py`, `ui/kit_render.py`,
`ui/kit_priv.py`, `ui/server.py`, `web/src/api.js`, `web/src/App.jsx`, `web/src/components/ServerView.jsx`, `compose.yaml`, `docker/env.example`,
`README.md`, `tests/test_kit_db.py`, `tests/test_kit_server.py`, `tests/test_kit_discovery.py`, `tests/test_kit_priv.py`, `tests/test_kit_render.py`,
`tests/test_kit_apply.py` (only the `install(job, nl_host, row)` signature), `tests/test_kit_jobs.py` (only if it calls `check_job`/`install_job`),
`tests/test_docker_files.py`, `tests/test_web_contract.py`. No new npm dependency and no lockfile change.

Forbidden: `proxy.env`, `.env` (never read; the smoke test does not create it), `servers/*`, `server/*`, `tools/proxy_update.py`,
`proxy`, `setup-ai-cli-proxy.sh`, `docs/*`, `AGENTS.md`, `tests/fixtures/ui/xui_config.json` (read-only), anything
not listed. Never mount the Docker socket. Never stop host services. Never bind 4050 or 7890 in tests.

## Ordered implementation steps for the Implementer

0. Read this spec and the 4 partial `ui/*.py` files plus `tools/export-vless.py`. Do not touch any REMOVE file until step 14.
1. Create `ui/kit_nl.py` (B) by moving the code from `tools/export-vless.py`. Create `tests/test_kit_nl.py`. Run
   `python3 -m unittest tests.test_kit_nl -v`.
2. Create `ui/kit_render.py` (G) + `tests/test_kit_render.py`. Run them.
3. Change `ui/kit_db.py` (C) + `tests/test_kit_db.py`. Run them.
4. Change `ui/kit_guard.py` (F) + `tests/test_kit_guard.py`. Run them.
5. Change `ui/kit_discovery.py` (D) + `tests/test_kit_discovery.py`. Run them.
6. Create `ui/kit_apply.py` (H) + `tests/test_kit_apply.py`, change `ui/kit_jobs.py` (E) + `tests/test_kit_jobs.py`. Run them.
7. Create `ui/kit_proxy.py` (I) + `tests/test_kit_proxy.py`, `ui/kit_priv.py` (J0) + `tests/test_kit_priv.py`. Run them.
8. Create `ui/server.py` (J1), `ui/kit_cli.py` (J2) + `tests/test_kit_server.py`. Run them.
9. Frontend (L, amendment 2a):
   1. Create `web/package.json`, `web/vite.config.js`, `web/index.html` and `web/src/**` exactly as in L.
   2. Generate `web/package-lock.json` with the docker command in L.
   3. Build with the containerised `npm ci && npm run build` command from Test strategy.
   4. Create `tests/test_web_contract.py` and run `WEB_DIST=web/dist python3 -m unittest tests.test_web_contract -v`.
   5. Do not install Node on the host and do not commit `web/node_modules` or `web/dist`.
10. Create `Dockerfile`, `.dockerignore`, `compose.yaml`, `docker/env.example` + `tests/test_docker_files.py`. Run
    `docker compose config -q`.
11. Create `tests/docker_smoke.sh` (chmod 755) and run `bash tests/docker_smoke.sh` → `SMOKE OK`. It must use project
    `kitsmoke` and ports 14050/17890 only. Do not run `docker compose up` without `-p kitsmoke` and those ports.
12. `tools/proxy_cli.py` `check` change (K); rewrite `proxy.env.example` (K); add the status line to the superseded spec;
    append `.gitignore` (I2, first part); rewrite `README.md` (J).
13. Run the full Test strategy commands. Report results.
14. **Only if the orchestrator confirms the user's yes for the REMOVE list (and open question 2 is settled):**
    `git rm` exactly the REMOVE paths (and `rm -rf` the two untracked `__pycache__` dirs). Remove the obsolete
    `.gitignore` lines (I2, second part). Run the step-13 commands again plus the reference `grep` and the README/KEEP checks from acceptance criterion 11.
15. Report the changed, new and deleted paths for the memory sync. Do not run the manual E2E unless the orchestrator says the user
    approved it.
16. **Amendment 2c (Opus escalation after correction cycle 2).** Only these files change: `ui/kit_apply.py`, `ui/server.py`,
    `ui/kit_proxy.py`, `tests/test_kit_apply.py`, `tests/test_kit_proxy.py`, `tests/test_kit_server.py`, `.gitignore`, `README.md`.
    Follow the "Amendment 2c" block at the top and the escalation correction plan delivered with it; run
    `python3 -m unittest discover -s tests -v` and `python3 -m py_compile ui/*.py tools/proxy_cli.py` after each file.
17. **Amendment 2d (owner decisions A and B).** Only the files listed under "Amendment 2d" in the allowed-files section change. Follow the 2d block at the
    top. After each sub-step run `python3 -m py_compile ui/*.py tools/proxy_cli.py` and the named test module
    (`python3 -m unittest tests.<module> -v`).
    1. `ui/kit_guard.py`: set `SECURITY_HEADERS['Content-Security-Policy']` to the exact 2d-B string (keep the two-literal concatenation
       style; the joined value must equal the string byte for byte). Update `tests/test_kit_guard.py` (`test_csp_exact`,
       `test_csp_inline_only_for_styles`). Run `tests.test_kit_guard`.
    2. `ui/kit_apply.py`: remove `run_dir()`, add `gen_dir()`, `state_dir()`, `open_state_dir(sub=None)`, and the `dir_fd=None` keyword on
       `read_regular_bytes` and `read_regular_tail`. Point `_xray_path`, `_mihomo_path`, `_gen_path`, `_prev_dir`, `write_bundle` and
       `restore_prev` at `gen_dir()`, and `read_status` at `open_state_dir()`. Update the module docstring (kit-gen written by kit and read-only for
       proxy; kit-state read-only for kit). Update `tests/test_kit_apply.py` (env + the six new cases). Run `tests.test_kit_apply`.
    3. `ui/server.py` `Api.proxy_logs`: `fd = kit_apply.open_state_dir('logs')`. `None` → no tail. Otherwise
       `kit_apply.read_regular_tail(f'{name}.log', dir_fd=fd)` in `try/finally: os.close(fd)`. `RunFileError` from either call → no tail.
       The truncation, last-200-lines and redaction logic is unchanged. No other `KIT_RUN_DIR` use may remain in `server.py`. Update `tests/test_kit_server.py`
       (env, logs under `state/logs`, exact CSP, symlinked-logs-dir case). Run `tests.test_kit_server`.
    4. `ui/kit_proxy.py`: `gen_dir`/`state_dir` attributes, `start()` on `state_dir`, `status_path`, `_log_file`, `_config_path`, `_check_generation`
       paths, and the mihomo command `[mihomo_bin, '-d', str(self.state_dir / 'mihomo'), '-f', str(self._config_path('mihomo'))]`.
       Error text `Каталог /kit-state повреждён`. Update the module docstring. Update `tests/test_kit_proxy.py` (env + the three new cases). Run `tests.test_kit_proxy`.
    5. `ui/kit_priv.py`: `_own_top(os.environ.get('KIT_GEN_DIR', '/kit-gen'), uid, gid, 0o700)` replaces the `KIT_RUN_DIR` line. There is no line
       for `KIT_STATE_DIR`. Update `tests/test_kit_priv.py` only if it references `KIT_RUN_DIR`. Run `tests.test_kit_priv`.
    6. `tests/test_kit_render.py`: add the two 2d assertions (no change to `ui/kit_render.py`; if they fail, STOP and report). Run `tests.test_kit_render`.
    7. `Dockerfile`: the `mkdir`/`chown`/`chmod` line and the `ENV` line exactly as in the Dockerfile block above. `compose.yaml`: exactly the
       "Compose diff for amendment 2d". Update `tests/test_docker_files.py`. Run `tests.test_docker_files` and `docker compose config -q`.
    8. `tests/docker_smoke.sh`: append the 2d lines exactly as in the smoke block (before `echo "SMOKE OK"`). Run `bash tests/docker_smoke.sh` → `SMOKE OK`.
       If `proxy` cannot write `/kit-state` (volume ownership), STOP and report; do not add `user: 0`, caps or chmod workarounds.
    9. `README.md`:
       - Replace every `kit-run` / `/run-kit` mention with the 2d volume names.
       - Add a new subsection «Обновление: разделение тома kit-run» directly after section 8 "Переход с установки на хосте", with the 4 migration
         steps from 2d-A in Russian and the exact commands.
       - In the security notes, state that `kit` and `proxy` each have a read-only view of the other's volume.
    10. Final: `python3 -m unittest discover -s tests -v`, `python3 -m py_compile ui/*.py tools/proxy_cli.py`, `docker compose config -q`,
        `bash tests/docker_smoke.sh`, and `git grep -nE 'kit-run|/run-kit|KIT_RUN_DIR' -- ui compose.yaml Dockerfile` must print nothing.
        In `tests/` the only hits allowed are the negative assertions named in acceptance criterion 14, and `README.md` may mention `kit-run`
        only in the migration subsection. Report changed paths for the memory sync.
18. **Amendment 2e (import-only mode).** Start only after the orchestrator says "2e is ready". The 2d step (17) may be done before or after
    this one; they touch `compose.yaml` in different lines. Only the files listed under "Amendment 2e" change. Follow the 2e block at the top.
    After each sub-step run `python3 -m py_compile ui/*.py tools/proxy_cli.py` and the named test module.
    1. `ui/kit_render.py`: add `UUID_RE`, `HOST_IPV4_RE`, `PBK_RE`, `SID_RE`, `XHTTP_PATH_RE`, `XHTTP_MODES`, `GRPC_SERVICE_RE` and `FINGERPRINTS`
       exactly as in 2e-2, plus the re-validation in `xray_client_config` (2e-3). Tests: `tests/test_kit_render.py` (2e row). Run `tests.test_kit_render`.
       If a golden case fails, STOP and report; do not loosen a regex.
    2. `ui/kit_import.py` (new): `MAX_IMPORT_LINKS = 40`, `MAX_LINK_LEN = 1024`, `LABEL_RE`, `parse_link(text)` and `parse_links(links)`, exactly per
       2e-2. Tests: `tests/test_kit_import.py` (new). Run `tests.test_kit_import`.
    3. `ui/kit_db.py`: `SCHEMA_VERSION = 2`, `V2_SQL`, `MIGRATIONS`, `ImportConflict`, `replace_imported`, the `upsert_inbounds` change, and
       `source` in `PUBLIC_INBOUND_KEYS`/`public_inbound`. Tests: `tests/test_kit_db.py`. Run `tests.test_kit_db`.
    4. `ui/kit_discovery.py`: `key_available`, `row_nl_host`, and `links_for_exit(conn, nl, exit_ip)`. `ui/kit_priv.py`: `should_copy_key(mount)`,
       used by `prepare_and_drop`. Tests: `tests/test_kit_discovery.py`, `tests/test_kit_priv.py`. Run both.
    5. `ui/kit_apply.py`: `install(job, nl_host, row)`. `ui/kit_jobs.py`: `install_job(job, nl_host, row)` and per-row host in `check_job`.
       Update the callers in tests (`tests/test_kit_apply.py`, `tests/test_kit_jobs.py` if needed). Run both.
    6. `ui/server.py`:
       - `ApiError(..., extra=None)` and the dispatcher merge.
       - `import_links` and its route.
       - The `install`, `check_one`, `check_all`, `put_rules`, `exit_links` and `discover` changes (2e-1, 2e-3).
       - `nl_key_mounted` via `key_available`.
       Tests: `tests/test_kit_server.py` (2e row). Existing discover tests that expect 202 or the NL-settings 400 must first write a 1-byte file at
       `KIT_SSH_KEY_FILE`, because the key check now runs first. Do not weaken any other assertion. Run `tests.test_kit_server`.
    7. `docker/no-key` (empty, `chmod 0600`). In `compose.yaml`, change only the key `source:` line. `docker/env.example`: document
       `KIT_SSH_KEY` as optional ("нужен только для обнаружения входов на NL; без него доступен импорт ссылок"). Tests:
       `tests/test_docker_files.py` (2e row). Run `tests.test_docker_files` and `docker compose config -q` (with and without `KIT_SSH_KEY` exported).
    8. Frontend: `web/src/api.js` (`ApiError.data`), `web/src/components/ImportLinks.jsx` (new), `web/src/App.jsx`, and the `ServerView.jsx` badge, per 2e-4.
       Build with the containerised `npm ci && npm run build` command, then
       `WEB_DIST=web/dist python3 -m unittest tests.test_web_contract -v` (2e row added).
    9. `README.md`: a new subsection «Режим без доступа к NL (импорт ссылок)» in Russian: the friend's steps (`git clone`, `docker compose up -d --build`,
       `docker compose exec kit kit token`, paste links, «Установить»), the security note from 2e-5, and the owner note that `KIT_SSH_KEY` must now be set in
       `.env` for discovery (2e-Q1).
    10. Final: `python3 -m unittest discover -s tests -v`, `python3 -m py_compile ui/*.py tools/proxy_cli.py`, `docker compose config -q`,
        `bash tests/docker_smoke.sh` → `SMOKE OK`. Report changed and new paths for the memory sync.
