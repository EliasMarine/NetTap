# Installation

This guide walks through the full NetTap installation process using the automated install script.

---

## Prerequisites

Before starting, ensure you have:

- Ubuntu Server 22.04 or 24.04 LTS installed
- Root or sudo access
- At least two physical Ethernet NICs
- Internet access (to pull Docker images)
- At least 20 GB of free disk space for Docker images

See [Requirements](requirements.md) for full details.

---

## Step 1: Clone the Repository

```bash
git clone https://github.com/EliasMarine/NetTap.git /opt/nettap
cd /opt/nettap
```

---

## Step 2: Configure Environment

Copy the example environment file and edit it:

```bash
cp .env.example .env
nano .env
```

At minimum, set your network interfaces:

```ini title=".env"
# Bridge interfaces (required)
WAN_INTERFACE=eth0      # NIC connected to ISP modem
LAN_INTERFACE=eth1      # NIC connected to router

# Management interface (recommended)
MGMT_INTERFACE=eth2     # NIC for dashboard access
MGMT_IP=192.168.1.100
MGMT_NETMASK=255.255.255.0

# Dashboard
NETTAP_HOSTNAME=nettap.local
DASHBOARD_PORT=443

# OpenSearch JVM heap (adjust for your RAM)
OPENSEARCH_JAVA_OPTS="-Xms4g -Xmx4g"

# Storage retention (days)
RETENTION_HOT=90
RETENTION_WARM=180
RETENTION_COLD=30
DISK_THRESHOLD_PERCENT=80
```

!!! tip "Finding your NIC names"
    Run `ip link show` to list all interfaces. Physical NICs are typically named `eth0`, `eth1`, `enp1s0`, `enp2s0`, etc. Look for interfaces with MAC addresses and a `device` symlink in `/sys/class/net/<name>/device`.

See the [Environment Reference](../reference/env-reference.md) for all available options.

---

## Step 3: Generate Secrets

Generate cryptographically random passwords for all services:

```bash
sudo scripts/generate-secrets.sh
```

This writes secrets to your `.env` file for OpenSearch, Redis, Arkime, and Grafana. You can preview what would be generated without writing:

```bash
scripts/generate-secrets.sh --stdout
```

---

## Step 4: Run the Installer

```bash
sudo scripts/install/install.sh
```

The installer runs through eight steps automatically:

| Step | What It Does |
|---|---|
| **0. Pre-flight** | Validates root access, OS version, architecture, and hardware (CPU, RAM, disk, NICs) |
| **1. Dependencies** | Installs Docker, bridge-utils, net-tools, ethtool, smartmontools, Python 3, Avahi |
| **2. Kernel tuning** | Sets `vm.max_map_count=262144` (required by OpenSearch), increases network buffer sizes |
| **3. Bridge setup** | Creates the `br0` transparent bridge between WAN and LAN NICs with performance tuning |
| **4. Malcolm deploy** | Pulls Malcolm container images and generates TLS certificates and auth credentials |
| **5. Systemd** | Installs and enables `nettap.service` for automatic start on boot |
| **6. mDNS** | Configures Avahi so the dashboard is accessible at `nettap.local` |
| **7. Firewall** | Adds UFW rules for the dashboard port, Malcolm port, and mDNS (if UFW is active) |
| **8. Verification** | Checks bridge, Docker, containers, OpenSearch, systemd, mDNS, and kernel tuning |

### Installer Options

```bash
sudo scripts/install/install.sh [OPTIONS]
```

| Option | Description |
|---|---|
| `--skip-bridge` | Skip bridge configuration (if already set up) |
| `--skip-pull` | Skip Docker image pull (use cached images) |
| `--skip-malcolm` | Skip Malcolm deployment entirely (bridge + deps only) |
| `--no-persist-bridge` | Don't write persistent netplan config (runtime-only bridge) |
| `--dry-run` | Log all actions without executing them |
| `-v, --verbose` | Enable debug output |

---

## Step 5: Verify Installation

After the installer completes, you should see a summary like:

```
==========================================
  Installation Summary
==========================================
  Passed:   7
  Warnings: 0
  Failed:   0
  Time:     4m 32s

  NetTap installation complete!

  Malcolm Dashboards:  https://localhost:9443
  NetTap Dashboard:    https://nettap.local:443

  Manage services:     systemctl {start|stop|restart} nettap
  View logs:           journalctl -u nettap -f
  Container status:    docker compose -f docker/docker-compose.yml ps
==========================================
```

!!! warning "OpenSearch startup time"
    OpenSearch may take 2--5 minutes to fully start and become healthy. If the verification shows "OpenSearch not responding yet," wait a few minutes and check again with:
    ```bash
    curl -sk https://localhost:9200/_cluster/health | python3 -m json.tool
    ```

---

## Step 6: Access the Dashboard

Open a browser and navigate to:

```
https://nettap.local
```

Or use the management IP directly:

```
https://192.168.1.100
```

!!! note "Self-signed certificate"
    The first time you access the dashboard, your browser will warn about a self-signed TLS certificate. This is expected --- accept the warning to proceed. See [TLS Certificates](../admin-guide/tls-certificates.md) to configure a custom certificate.

If this is a fresh installation, you will be redirected to the [Setup Wizard](first-run-wizard.md) to complete initial configuration.

---

## Managing the Service

After installation, NetTap runs as a systemd service:

```bash
# Start all NetTap containers
sudo systemctl start nettap

# Stop all containers gracefully
sudo systemctl stop nettap

# Restart
sudo systemctl restart nettap

# Check status
systemctl status nettap

# View logs
journalctl -u nettap -f
```

NetTap starts automatically on boot. To disable auto-start:

```bash
sudo systemctl disable nettap
```

---

## Uninstallation

To remove NetTap:

```bash
# Stop services
sudo systemctl stop nettap

# Remove systemd service
sudo systemctl disable nettap
sudo rm /etc/systemd/system/nettap.service
sudo systemctl daemon-reload

# Tear down the bridge
sudo scripts/bridge/setup-bridge.sh --teardown

# Remove Docker containers and volumes (WARNING: deletes all data)
docker compose -f docker/docker-compose.yml down -v

# Remove kernel tuning
sudo rm /etc/sysctl.d/99-nettap.conf
sudo sysctl --system

# Remove the installation directory
sudo rm -rf /opt/nettap
```

!!! danger "Data loss"
    The `docker compose down -v` command deletes all Docker volumes, including OpenSearch data, PCAP captures, and Grafana dashboards. Back up any data you need before running this.
