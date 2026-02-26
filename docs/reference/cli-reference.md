# CLI Reference

Complete reference for all NetTap shell scripts and their options.

---

## Installation Scripts

### `scripts/install/install.sh`

Main installation script. Orchestrates the full deployment: pre-flight checks, system dependencies, network bridge, Malcolm stack, systemd services, mDNS, and verification.

```bash
sudo scripts/install/install.sh [OPTIONS]
```

| Option | Description |
|---|---|
| `--skip-bridge` | Skip bridge configuration (if already done) |
| `--skip-pull` | Skip Docker image pull (use cached images) |
| `--skip-malcolm` | Skip Malcolm deployment entirely (bridge + deps only) |
| `--no-persist-bridge` | Don't write persistent netplan config (runtime-only bridge) |
| `--dry-run` | Log all actions without executing them |
| `-v, --verbose` | Enable debug output |
| `-h, --help` | Show help |

**Steps executed:**

1. Pre-flight checks (root, OS, architecture, hardware validation)
2. System dependencies (Docker, bridge-utils, net-tools, Python, Avahi)
3. Kernel tuning (vm.max_map_count, network buffers, conntrack)
4. Network bridge (br0 with WAN + LAN NICs)
5. Malcolm deployment (container images, TLS certs, auth)
6. Systemd services (nettap.service)
7. mDNS configuration (Avahi)
8. Firewall rules (UFW, if active)
9. Post-install verification

---

### `scripts/install/validate-hardware.sh`

Hardware validation. Checks CPU, RAM, disk, and NIC count against minimum requirements.

Can be sourced (provides `validate_hardware` function) or run standalone:

```bash
sudo scripts/install/validate-hardware.sh
```

**Exit codes:**

| Code | Meaning |
|---|---|
| `0` | All checks passed |
| `1` | Warnings (e.g., below recommended but above minimum) |
| `2` | Hard failure (does not meet minimum requirements) |

**Thresholds:**

| Check | Minimum | Recommended |
|---|---|---|
| CPU cores | 2 | 4 |
| RAM | 8 GB (~7500 MB) | 16 GB (~15000 MB) |
| Disk | 512 GB (~400 GB formatted) | 1 TB |
| NICs | 2 physical | 3 (including management) |

---

### `scripts/install/deploy-malcolm.sh`

Deploy the Malcolm container stack. Pulls images, generates TLS certificates, and configures authentication.

```bash
sudo scripts/install/deploy-malcolm.sh [OPTIONS]
```

| Option | Description |
|---|---|
| `--skip-pull` | Skip Docker image pull |
| `--dry-run` | Log without executing |
| `-v, --verbose` | Debug output |

---

### `scripts/install/malcolm-config.sh`

Generate Malcolm configuration files and environment settings.

---

### `scripts/install/setup-watchdog.sh`

Install and configure the hardware watchdog timer.

```bash
sudo scripts/install/setup-watchdog.sh
```

Deploys `config/watchdog/watchdog.conf` to `/etc/watchdog.conf` and enables the watchdog service.

---

### `scripts/install/setup-firewall.sh`

Configure UFW firewall rules for NetTap.

```bash
sudo scripts/install/setup-firewall.sh
```

---

## Bridge Scripts

### `scripts/bridge/setup-bridge.sh`

Create, validate, or tear down the transparent network bridge.

```bash
sudo scripts/bridge/setup-bridge.sh [OPTIONS]
```

| Option | Description |
|---|---|
| `--wan <iface>` | WAN-side interface (default: `$WAN_INTERFACE` or `eth0`) |
| `--lan <iface>` | LAN-side interface (default: `$LAN_INTERFACE` or `eth1`) |
| `--mgmt <iface>` | Management interface for dashboard access |
| `--persist` | Write netplan config and systemd units for boot persistence |
| `--no-persist` | Skip persistence (runtime only, for testing) |
| `--validate-only` | Check existing bridge config without making changes |
| `--teardown` | Remove bridge and restore interfaces to original state |
| `--detect` | Auto-detect NICs and suggest WAN/LAN assignment |
| `--dry-run` | Log commands without executing |
| `-v, --verbose` | Debug output |
| `-h, --help` | Show help |

**Modes:**

=== "Create (default)"

    ```bash
    sudo scripts/bridge/setup-bridge.sh --wan eth0 --lan eth1 --persist
    ```

    Creates br0, adds NICs, tunes offloads, enables promiscuous mode, and optionally writes netplan config for persistence.

=== "Validate"

    ```bash
    sudo scripts/bridge/setup-bridge.sh --validate-only
    ```

    Checks bridge exists, is UP, STP disabled, interfaces attached, promiscuous mode on, forward delay 0.

=== "Teardown"

    ```bash
    sudo scripts/bridge/setup-bridge.sh --teardown
    ```

    Removes bridge, restores interfaces, cleans up netplan config, systemd units, and sysctl settings.

=== "Detect"

    ```bash
    scripts/bridge/setup-bridge.sh --detect
    ```

    Lists physical NICs with driver, speed, and carrier status. Does not require root.

---

### `scripts/bridge/bypass-mode.sh`

Enable or disable bridge bypass mode (for maintenance or troubleshooting).

---

### `scripts/bridge/harden-bridge.sh`

Apply additional bridge hardening settings.

---

## Utility Scripts

### `scripts/generate-secrets.sh`

Generate cryptographically random passwords and secrets for deployment.

```bash
sudo scripts/generate-secrets.sh [OPTIONS]
```

| Option | Description |
|---|---|
| `--stdout` | Print secrets to stdout instead of writing to `.env` |
| `--env-file PATH` | Write to a custom `.env` path (default: `/opt/nettap/.env`) |
| `--force` | Regenerate all secrets even if they already exist |
| `--dry-run` | Show what would be done without writing |
| `-v, --verbose` | Debug output |
| `-h, --help` | Show help |

Generates secrets for: OpenSearch admin password, Redis password, Arkime secret, Grafana admin password, and other service credentials.

---

### `scripts/generate-cert.sh`

Generate a self-signed TLS certificate for the NetTap dashboard.

```bash
sudo scripts/generate-cert.sh
```

Outputs `docker/ssl/nettap.crt` and `docker/ssl/nettap.key`.

---

### `scripts/common.sh`

Shared shell utilities sourced by all other scripts. Provides:

- **Logging:** `log`, `warn`, `error`, `debug` functions
- **Dry-run support:** `run` function wraps commands for `--dry-run` mode
- **Cleanup traps:** `push_cleanup`, `enable_cleanup_trap`, `disable_cleanup_trap`
- **Lock files:** `acquire_lock`, `release_lock` (prevents concurrent script execution)
- **Retry logic:** `retry <attempts> <delay> <command>` for transient failures
- **System checks:** `require_root`, `check_ubuntu`, `check_arch`, `check_interface_exists`, `check_command`
- **Environment loading:** `load_env` reads `.env` files
- **Network helpers:** `list_physical_nics`, `get_nic_driver`, `nic_has_carrier`, `get_nic_speed`, `get_nic_mac`

---

## Service Management

These are systemd commands, not NetTap scripts, but they are the primary way to manage the running system:

```bash
# Start NetTap
sudo systemctl start nettap

# Stop NetTap
sudo systemctl stop nettap

# Restart NetTap
sudo systemctl restart nettap

# Check status
systemctl status nettap

# View logs
journalctl -u nettap -f

# Enable/disable auto-start on boot
sudo systemctl enable nettap
sudo systemctl disable nettap
```

---

## Docker Compose Commands

```bash
# Check container status
docker compose -f /opt/nettap/docker/docker-compose.yml ps

# View logs for a specific container
docker compose -f /opt/nettap/docker/docker-compose.yml logs -f zeek-live

# Restart a specific container
docker compose -f /opt/nettap/docker/docker-compose.yml restart suricata-live

# Pull updated images
docker compose -f /opt/nettap/docker/docker-compose.yml pull

# Rebuild custom images
docker compose -f /opt/nettap/docker/docker-compose.yml build
```
