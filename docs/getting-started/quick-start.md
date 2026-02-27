# Quick Start

Get NetTap running in about 10 minutes. This guide assumes you already have compatible hardware with Ubuntu Server installed.

---

## 1. Clone and Install

```bash
# Clone the repository
sudo git clone https://github.com/EliasMarine/NetTap.git /opt/nettap
cd /opt/nettap

# Generate secrets for OpenSearch, Redis, etc.
sudo scripts/generate-secrets.sh

# Run the installer (keep your internet connected!)
sudo scripts/install/install.sh
```

The installer will:

1. **Discover your NICs** — shows a table of all interfaces with speed, MAC, and link status
2. **Let you assign roles** — pick which NIC is WAN (modem side), LAN (router side), and Management (dashboard). You can blink LEDs to identify ports.
3. **Install everything** — system dependencies, Docker images (~5 GB), systemd services, mDNS
4. **Print a wiring diagram** — tells you exactly which cable goes where

!!! tip "Only have 2 wired NICs?"
    If your box has Wi-Fi, NetTap automatically uses it as the management interface. Both wired NICs go to the bridge — no third Ethernet port required.

## 2. Rewire Cables

Follow the wiring diagram printed by the installer:

```
[ISP Modem] --> [WAN NIC] ==BRIDGE== [LAN NIC] --> [Router]
                          NetTap
[MGMT NIC / Wi-Fi] --> dashboard at https://nettap.local
```

1. Plug your ISP modem into the **WAN** NIC
2. Plug the **LAN** NIC into your router's WAN port
3. Keep your **MGMT** NIC (or Wi-Fi) connected for dashboard access

## 3. Activate

```bash
sudo scripts/install/activate-bridge.sh
```

This validates your cables are plugged in, activates the bridge, and starts all services.

## 4. Access the Dashboard

Open your browser to:

```
https://nettap.local
```

Or use the management IP (e.g., `https://192.168.1.100`).

!!! note
    Accept the self-signed certificate warning in your browser. The [Setup Wizard](first-run-wizard.md) will guide you through any remaining configuration.

## 5. Wait for Data

Give the system 5--10 minutes to start collecting and indexing data. You should see:

- **Bandwidth and connection counts** in the stat cards
- **Protocol distribution** in the donut chart
- **Top talkers** showing your most active devices
- **Alerts** from Suricata IDS (if any suspicious traffic is detected)

---

## What Just Happened?

The installer and activation scripts:

1. Discovered your NICs and assigned roles (MGMT, WAN, LAN)
2. Installed Docker, bridge utilities, and Python dependencies
3. Tuned kernel parameters for OpenSearch and high-throughput packet capture
4. Pulled and deployed 15+ containers (Zeek, Suricata, Arkime, OpenSearch, and more)
5. Created a transparent Layer 2 bridge (`br0`) between your WAN and LAN NICs
6. Registered `nettap.service` in systemd for automatic startup on boot
7. Configured mDNS so you can reach the dashboard at `nettap.local`

---

## Common Next Steps

| Task | Where |
|---|---|
| Learn the dashboard panels | [Dashboard Overview](../user-guide/dashboard-overview.md) |
| Investigate an alert | [Alerts](../user-guide/alerts.md) |
| Set up email notifications | [Notifications](../user-guide/notifications.md) |
| Tune for your hardware | [Performance Tuning](../admin-guide/performance-tuning.md) |
| Forward logs to your SIEM | [SIEM Forwarding](../user-guide/siem-forwarding.md) |

---

## Troubleshooting

**Dashboard not loading?**

```bash
# Check if containers are running
docker compose -f /opt/nettap/docker/docker-compose.yml ps

# Check service status
systemctl status nettap

# View logs
journalctl -u nettap -f
```

**OpenSearch showing "yellow" health?**

This is normal for a single-node deployment. Yellow means all primary shards are assigned but replicas are not (since there is only one node). It does not affect functionality.

**Bridge not forwarding traffic?**

```bash
# Validate the bridge
sudo scripts/bridge/setup-bridge.sh --validate-only
```

See [Troubleshooting](../admin-guide/troubleshooting.md) for more.
