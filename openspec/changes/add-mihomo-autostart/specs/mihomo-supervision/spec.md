## Purpose

Keeps the local Mihomo proxy continuously available on the client: it starts automatically after a machine/WSL boot or user login and is restarted automatically after the process fails, so the NL→USA tunnel stays up without a manual `install.sh` run.

## ADDED Requirements

### Requirement: Automatic start after boot or login

The installer SHALL register a supervisor so the Mihomo proxy starts without manual intervention after the operating system or WSL distro starts, on every supported client platform.

#### Scenario: Linux with a systemd user manager

- **WHEN** the installer runs on Linux where the systemd user manager is reachable
- **THEN** it enables a `mihomo.service` user unit on `default.target` and enables lingering for the user, so the proxy starts after boot even without an interactive login

#### Scenario: Linux without a systemd user manager

- **WHEN** the installer runs on Linux where the systemd user manager is not reachable
- **THEN** it installs a crontab `@reboot` entry that starts the proxy when cron starts

#### Scenario: macOS

- **WHEN** the installer runs on macOS
- **THEN** it installs a LaunchAgent with `RunAtLoad` enabled, so the proxy starts when the user logs in

### Requirement: Automatic restart after failure

The active supervisor SHALL restart the Mihomo process after it exits unexpectedly, without user action.

#### Scenario: Proxy process crashes

- **WHEN** the Mihomo process terminates unexpectedly
- **THEN** the supervisor restarts it automatically within a bounded delay and the proxy port is listening again

#### Scenario: Repeated start failures

- **WHEN** Mihomo repeatedly fails to start
- **THEN** the supervisor keeps retrying instead of entering a terminal failed state that requires manual intervention

### Requirement: Single managed instance

The installer and every supervisor SHALL keep at most one Mihomo process bound to the proxy port, and re-running the installer SHALL be idempotent.

#### Scenario: Repeated install

- **WHEN** the installer is run again while the proxy is already supervised and running
- **THEN** no duplicate Mihomo process is left running and the proxy port stays served

#### Scenario: Watchdog overlap

- **WHEN** the cron keepalive watchdog runs while a Mihomo instance is already serving the port
- **THEN** the watchdog detects the running instance and does not start a second one

### Requirement: Supervisor visibility and removal

The installer SHALL report which supervisor keeps the proxy running, and the project SHALL document how to inspect, restart, and remove that supervision.

#### Scenario: Installer reports the supervisor

- **WHEN** the installer finishes successfully
- **THEN** it prints which supervisor (systemd user service, cron watchdog, or LaunchAgent) will start and restart the proxy

#### Scenario: Manual removal is possible

- **WHEN** a user applies the documented disable commands
- **THEN** the proxy no longer starts or restarts automatically
