## Context

`install.sh` currently starts Mihomo with `nohup … &` and records `~/.config/mihomo/mihomo.pid`; the binary lives at `~/.local/bin/mihomo` and the config in `~/.config/mihomo`. The project supports Linux (including WSL2) and macOS. See `proposal.md` for motivation.

Two constraints shape the approach:

- The client is often WSL2. Modern WSL2 ships systemd, but not every install has it enabled, and there is no single cross-platform supervision primitive available everywhere.
- The installer must stay idempotent and must never leave two processes bound to `127.0.0.1:7890` (the port conflict the existing install lock already guards against).

## Goals / Non-Goals

**Goals:**

- Self-healing proxy: start on boot/login and restart after a crash, on Linux/WSL and macOS.
- Pick the best native supervisor per platform automatically, with a working fallback.
- Keep the immediate start + exit-IP verification behaviour of `install.sh` intact.
- Keep the existing log and pid paths documented in `README.md`.

**Non-Goals:**

- Windows-host (WSL) autostart via Task Scheduler; server-side (Xray) supervision; binary auto-update; log rotation; system-wide VPN routing.

## Decisions

### 1. Platform-native supervisor, systemd user service preferred on Linux

systemd user unit with `Restart=always`, `RestartSec=3`, `StartLimitIntervalSec=0` (never give up), `default.target` target and `loginctl enable-linger`. Rationale: true event-driven restart (no polling delay), boot-time start without login, per-user files (no root). Alternative considered: cron-only watchdog (the original request) — universal and simple but 1-minute granularity and needs the cron daemon; kept as the fallback, not the primary.

### 2. systemd **user** unit, not a system unit

No `sudo`, files under `~/.config/systemd/user/`, works in WSL. Proxy env vars are neutralised with `UnsetEnvironment=…` to mirror the current `env -u` behaviour (otherwise the user-manager environment can leak `http_proxy` and Mihomo would connect to itself). Logs stay at the documented path via `StandardOutput=append:%h/.config/mihomo/mihomo.log` (same for stderr).

### 3. Cron fallback with an idempotent keepalive script

When the systemd user manager is unreachable, register crontab entries `@reboot` and `*/1 * * * *` that call a new `mihomo-keepalive.sh`. The script is `flock`-serialised, checks the pid and the port, and only starts Mihomo when it is actually down. Entries are wrapped in `# mihomo local proxy begin/end` markers so unrelated cron lines survive, matching the existing rc-file approach.

### 4. macOS LaunchAgent

`~/Library/LaunchAgents/com.mihomo.proxy.plist` with `RunAtLoad` and `KeepAlive`, `StandardOutPath`/`StandardErrorPath` pointing at the same log. Loaded with `launchctl bootstrap gui/$UID` and a `launchctl load -w` fallback for older macOS.

### 5. Ownership handover on (re)install

Detection order: `Darwin` → launchd; else `systemctl --user show-environment` succeeds → systemd; else `crontab` present → cron; else plain `nohup` plus a warning. On start, `install.sh` first stops the previous instance (via `systemctl --user stop` when a unit exists, then the pid file and `pgrep`), waits for the port, then starts through the selected supervisor so exactly one process owns the port.

### 6. Supervisor migration

When one supervisor is chosen, the installer removes the other's registration (cron block removed when systemd is used, and vice versa) so stale supervisors cannot fight over the port.

## Risks / Trade-offs

- [systemd user manager unreachable from a non-login shell] → detection falls back to cron.
- [WSL without systemd] → neither systemd nor cron autostarts; document enabling systemd in `/etc/wsl.conf` and warn during install.
- [launchd `load`/`unload` deprecation] → prefer `bootstrap`/`bootout`, fall back to `load -w`/`unload`.
- [Mihomo log grows without rotation] → out of scope; noted in README.
- [Restart storm on a broken config] → bounded by `RestartSec=3`; the installer still validates the config before enabling the unit.

## Migration Plan

- Run `install.sh`: it writes and enables the unit, stops the old `nohup` instance, starts via the supervisor, and runs the existing exit-IP check.
- Rollback: `systemctl --user disable --now mihomo.service` (optionally `loginctl disable-linger`), remove the cron marker block, or `launchctl bootout gui/$UID ~/Library/LaunchAgents/com.mihomo.proxy.plist`; then run the previous installer.

## Open Questions

- None blocking. Windows-host autostart and log rotation are candidate follow-ups.
