# Quick Start

Get NetTap running in about 5 minutes. This guide assumes you already have compatible hardware with Ubuntu Server installed.

---

## 1. Clone and Configure

```bash
# Clone the repository
sudo git clone https://github.com/EliasMarine/NetTap.git /opt/nettap
cd /opt/nettap

# Copy the example config
sudo cp .env.example .env

# Edit your NIC names (run 'ip link show' to find them)
sudo nano .env
```

Set at minimum:

```ini
WAN_INTERFACE=enp1s0    # NIC connected to your modem
LAN_INTERFACE=enp2s0    # NIC connected to your router
```

## 2. Generate Secrets

```bash
sudo scripts/generate-secrets.sh
```

## 3. Install

```bash
sudo scripts/install/install.sh
```

This takes 3--10 minutes depending on your internet speed (Docker images are ~5 GB total).

## 4. Access the Dashboard

Open your browser to:

```
https://nettap.local
```

Or use the management IP you configured (e.g., `https://192.168.1.100`).

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

The installer:

1. Installed Docker, bridge utilities, and Python dependencies
2. Tuned kernel parameters for OpenSearch and high-throughput packet capture
3. Created a transparent Layer 2 bridge (`br0`) between your WAN and LAN NICs
4. Pulled and deployed 15+ containers (Zeek, Suricata, Arkime, OpenSearch, and more)
5. Registered `nettap.service` in systemd for automatic startup on boot
6. Configured mDNS so you can reach the dashboard at `nettap.local`

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
