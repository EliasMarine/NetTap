# Installation

This guide walks through the full NetTap installation process using the automated install script.

NetTap uses a two-phase workflow: **Install** (with internet, bridge activates automatically) → **Rewire** (physical cables, traffic flows immediately). The bridge activates during install with no cables — it sits idle until you plug in. This means you never lose your management connection.

---

## Prerequisites

Before starting, ensure you have:

- Ubuntu Server 22.04 or 24.04 LTS installed
- Root or sudo access
- At least two physical Ethernet NICs (three recommended for a dedicated management interface)
- Internet access (to pull Docker images)
- At least 20 GB of free disk space for Docker images

See [Requirements](requirements.md) for full details.

---

## Phase 1: Install (with internet)

### Step 1: Clone the Repository

```bash
git clone https://github.com/EliasMarine/NetTap.git /opt/nettap
cd /opt/nettap
```

### Step 2: Generate Secrets

Generate cryptographically random passwords for all services:

```bash
sudo scripts/generate-secrets.sh
```

This writes secrets to your `.env` file for OpenSearch, Redis, Arkime, and Grafana. You can preview what would be generated without writing:

```bash
scripts/generate-secrets.sh --stdout
```

### Step 3: Run the Installer

```bash
sudo scripts/install/install.sh
```

The installer will first run **NIC discovery**, which detects your physical network interfaces and lets you assign them to roles:

```
==========================================
  NetTap Pre-Install NIC Discovery
==========================================

Detected 3 physical network interface(s):

  #     Interface       Driver       Speed        MAC                  Link
  ---   -----------     ---------    ----------   ------------------   --------
  1     enp1s0          igc          2500Mb/s     aa:bb:cc:dd:ee:01    link up  <-- current internet
  2     enp2s0          igc          2500Mb/s     aa:bb:cc:dd:ee:02    no link
  3     enp3s0          igc          2500Mb/s     aa:bb:cc:dd:ee:03    no link

Blink a NIC's LEDs to identify its port? (y/n): y
Enter NIC number (1-3): 1
Blinking enp1s0 for 10 seconds... look for the flashing port.

Select MANAGEMENT NIC (dashboard access): 1  [enp1s0]
Select WAN NIC (ISP modem side): 2  [enp2s0]
Select LAN NIC (router side): 3  [enp3s0]

Written to .env: MGMT=enp1s0, WAN=enp2s0, LAN=enp3s0
```

Then the installer runs through its steps automatically:

| Step | What It Does |
|---|---|
| **NIC preflight** | Discovers NICs, assigns MGMT/WAN/LAN roles, writes to `.env` |
| **0. Pre-flight** | Validates root access, OS version, architecture, and hardware (CPU, RAM, disk, NICs) |
| **1. Dependencies** | Installs Docker, bridge-utils, net-tools, ethtool, smartmontools, Python 3, Avahi |
| **2. Kernel tuning** | Sets `vm.max_map_count=262144` (required by OpenSearch), increases network buffer sizes |
| **3. Bridge setup** | Creates the transparent `br0` bridge between WAN and LAN NICs (no cables needed yet) |
| **4. Malcolm deploy** | Pulls Malcolm container images, generates TLS certificates, and starts services |
| **5. Systemd** | Installs and enables `nettap.service` for automatic start on boot |
| **6. mDNS** | Configures Avahi so the dashboard is accessible at `nettap.local` |
| **7. Firewall** | Adds UFW rules for the dashboard port, Malcolm port, and mDNS (if UFW is active) |
| **8. Verification** | Checks Docker, systemd, mDNS, kernel tuning, and prints rewiring instructions |

At the end, the installer prints rewiring instructions:

```
==========================================
  INSTALL COMPLETE — Now Rewire Cables
==========================================

The bridge is active and services are running.
Plug in your cables — traffic will flow immediately.

1. Plug ISP modem  --> enp2s0 (WAN)
2. Plug enp3s0 (LAN) --> Router WAN port
3. Keep enp1s0 (MGMT) connected for dashboard access

   [ISP Modem] --> [enp2s0] ==BRIDGE== [enp3s0] --> [Router]
                            NetTap
   [enp1s0 MGMT] --> dashboard at https://nettap.local
```

No additional commands are needed — just plug in the cables and traffic flows.

### Installer Options

```bash
sudo scripts/install/install.sh [OPTIONS]
```

| Option | Description |
|---|---|
| `--defer-bridge` | Defer bridge activation until after cable rewiring (requires `activate-bridge.sh`) |
| `--non-interactive` | Auto-assign NICs without prompts |
| `--reconfigure-nics` | Force NIC re-discovery even if `.env` has values |
| `--skip-bridge` | Skip bridge configuration entirely |
| `--skip-pull` | Skip Docker image pull (use cached images) |
| `--skip-malcolm` | Skip Malcolm deployment entirely (deps only) |
| `--no-persist-bridge` | Don't write persistent netplan config (runtime-only bridge) |
| `--dry-run` | Log all actions without executing them |
| `-v, --verbose` | Enable debug output |

---

## Phase 2: Rewire (physical cables)

After the installer completes, physically rewire your cables according to the diagram printed at the end of installation. The bridge is already active, so traffic flows immediately when both cables are connected:

1. **ISP modem** → plug into the **WAN** NIC
2. **LAN** NIC → plug into the **router's WAN** port
3. Keep the **MGMT** NIC (or Wi-Fi) connected for dashboard access

Wi-Fi downtime is only the ~30 seconds it takes to physically swap two cables.

!!! tip "Identifying ports"
    During NIC discovery, you can blink a NIC's LEDs to identify which physical port it corresponds to. If you missed this step, run:
    ```bash
    sudo ethtool -p enp1s0 10
    ```
    This blinks the LEDs on `enp1s0` for 10 seconds.

---

## Verify Installation

After rewiring, you should see all services running:

```bash
docker compose -f docker/docker-compose.yml ps
```

!!! warning "OpenSearch startup time"
    OpenSearch may take 2--5 minutes to fully start and become healthy. If the verification shows "OpenSearch not responding yet," wait a few minutes and check again with:
    ```bash
    curl -sk https://localhost:9200/_cluster/health | python3 -m json.tool
    ```

---

## Access the Dashboard

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

## Re-running NIC Discovery

If you need to change NIC assignments after installation:

```bash
sudo scripts/install/preflight.sh --reconfigure-nics
```

Or during a full re-install:

```bash
sudo scripts/install/install.sh --reconfigure-nics
```

---

## Deferred Bridge Mode (Advanced)

If you prefer the old three-phase workflow (install → rewire → activate), use `--defer-bridge`:

```bash
sudo scripts/install/install.sh --defer-bridge
```

This defers bridge activation and service startup until you explicitly run:

```bash
sudo scripts/install/activate-bridge.sh
```

The activation script validates cable carrier status, creates the bridge, and starts all services. Options:

| Option | Description |
|---|---|
| `--force` | Skip cable carrier validation |
| `--skip-services` | Activate bridge only, don't start Docker services |
| `--dry-run` | Log actions without executing |
| `-v, --verbose` | Enable debug output |

`activate-bridge.sh` is also useful for troubleshooting — if you need to re-create the bridge or restart services after the initial install.

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
