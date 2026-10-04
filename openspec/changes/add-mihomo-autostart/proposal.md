## Why

`install.sh` starts Mihomo as a bare `nohup` background process with no supervisor, so after a WSL/machine reboot, a crash, or a dropped connection the tunnel stays down until someone re-runs the installer. This silently breaks the AI CLIs (Claude Code, Codex, Junie) that rely on `127.0.0.1:7890`. The installer must make the tunnel self-healing: started on boot/login and restarted automatically after any failure.

## What Changes

- `install.sh` registers a platform-appropriate supervisor at install time, in addition to bringing Mihomo up immediately:
  - Linux with a reachable systemd user manager: a `mihomo.service` **user** unit with `Restart=always`, enabled on `default.target`, plus `loginctl enable-linger` so it starts without an interactive login.
  - Linux without a systemd user manager: a crontab watchdog (`@reboot` plus a per-minute keepalive job).
  - macOS: a `LaunchAgent` with `RunAtLoad` and `KeepAlive`.
- Add a small keepalive script that is idempotent and lock-protected; the cron fallback and manual recovery use it.
- `install.sh` hands process ownership to the selected supervisor (instead of only `nohup`) and reports which supervisor is active.
- Document the autostart behavior and how to inspect, restart and remove it in `README.md`.

## Capabilities

### New Capabilities

- `mihomo-supervision`: guarantees the local Mihomo proxy process is running after boot/login and is restarted after a crash, on every supported client platform (WSL/Linux, macOS).

### Modified Capabilities

<!-- No existing specs in this project yet. -->

## Impact

- `install.sh` — supervision setup and startup handover (new helper functions).
- New file `mihomo-keepalive.sh` — idempotent restart helper for the cron path.
- `README.md` — new "always-on" section and diagnostics.
- Touches systemd user units / `crontab` / `launchd`; no server-side (Xray) changes and no new runtime dependencies.
