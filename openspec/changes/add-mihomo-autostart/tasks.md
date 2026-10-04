## 1. Keepalive helper

- [x] 1.1 Add `mihomo-keepalive.sh`: a `flock`-serialised, idempotent restart helper that checks the pid file and the proxy port and only starts Mihomo when it is actually down; verify with `bash -n` and by running it while the proxy is up (no second process is started).
- [x] 1.2 Make the helper honour `MIHOMO_CONFIG_DIR`, `MIHOMO_BIN`, `PROXY_PORT`, and `LOG_FILE` overrides so cron and manual use work from any cwd; verify by running it against a temporary config dir/port and confirming the real instance is untouched.

## 2. install.sh supervision

- [x] 2.1 Add supervisor detection (`launchd` on Darwin, else `systemd` when `systemctl --user show-environment` succeeds, else `cron` when `crontab` exists, else none) and print the selected supervisor; verify detection resolves to `systemd` on this machine.
- [x] 2.2 Generate the systemd user unit (`Restart=always`, `RestartSec=3`, `StartLimitIntervalSec=0`, `UnsetEnvironment` for proxy vars, `append:` log, `WantedBy=default.target`); verify it with `systemd-analyze --user verify`.
- [x] 2.3 Hand process ownership to the supervisor on start (stop via `systemctl --user stop` when a unit exists, then pid file + `pgrep`; start via the supervisor) and keep the existing exit-IP verification; verify `systemctl --user is-active mihomo.service` is `active` and `127.0.0.1:7890` is listening.
- [x] 2.4 Add the cron fallback: install/replace a `# mihomo local proxy begin/end` block with `@reboot` and per-minute keepalive entries, preserving unrelated cron lines; verify `crontab -l` shows exactly one block after repeated installs.
- [x] 2.5 Add the macOS LaunchAgent path (`com.mihomo.proxy.plist`, `RunAtLoad`/`KeepAlive`) loaded via `launchctl bootstrap` with a `load -w` fallback; verify the plist is well-formed (documented as `plutil -lint`).
- [x] 2.6 Implement supervisor migration: remove the cron block when systemd is selected and the systemd unit when cron is selected, so the two cannot fight over the port.

## 3. Documentation

- [x] 3.1 Document the always-on behaviour in `README.md`: which supervisor is used per platform, how to check it, how to restart it, and how to disable it (replacing the "does not survive reboot" wording).
- [x] 3.2 Document the WSL-without-systemd caveat and the manual removal/rollback commands.

## 4. Validation

- [x] 4.1 Run `openspec validate add-mihomo-autostart --strict` and confirm the change passes.
- [x] 4.2 End-to-end on this machine: install, confirm autostart registration, kill the Mihomo process and confirm the supervisor restarts it, and re-run the installer to confirm a single surviving instance on port 7890.
