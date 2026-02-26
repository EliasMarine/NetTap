# Configuration

NetTap is configured primarily through environment variables in the `.env` file. This page provides an overview of the configuration system.

---

## Configuration File

The main configuration file is `.env` in the project root (typically `/opt/nettap/.env`). This file is loaded by:

- The install scripts (via `scripts/common.sh`)
- Docker Compose (for container environment variables)
- The storage daemon

```bash
# Edit configuration
sudo nano /opt/nettap/.env

# After changes, restart to apply
sudo systemctl restart nettap
```

!!! warning "Secrets in .env"
    The `.env` file contains passwords and secrets. Ensure it has restrictive permissions:
    ```bash
    sudo chmod 600 /opt/nettap/.env
    sudo chown root:root /opt/nettap/.env
    ```

---

## Configuration Categories

### Network Interfaces

```ini title=".env"
WAN_INTERFACE=eth0          # NIC connected to ISP modem
LAN_INTERFACE=eth1          # NIC connected to router
MGMT_INTERFACE=eth2         # Management NIC (optional)
MGMT_IP=192.168.1.100      # Static IP for management NIC
MGMT_NETMASK=255.255.255.0 # Netmask for management NIC
```

### Dashboard

```ini title=".env"
NETTAP_HOSTNAME=nettap.local    # mDNS hostname
DASHBOARD_PORT=443              # HTTPS port for the dashboard
```

### OpenSearch

```ini title=".env"
OPENSEARCH_JAVA_OPTS="-Xms4g -Xmx4g"              # JVM heap size
OPENSEARCH_ADMIN_PASSWORD=N3tT@p_0p3n               # Admin password (auto-generated)
```

### Storage Retention

```ini title=".env"
RETENTION_HOT=90                    # Zeek metadata retention (days)
RETENTION_WARM=180                  # Suricata alert retention (days)
RETENTION_COLD=30                   # PCAP retention (days)
DISK_THRESHOLD_PERCENT=80           # Start pruning at this disk usage %
EMERGENCY_THRESHOLD_PERCENT=90      # Aggressive pruning threshold
```

### Alerting

```ini title=".env"
SMTP_HOST=                  # SMTP server for email notifications
SMTP_PORT=587               # SMTP port
SMTP_USER=                  # SMTP username
SMTP_PASS=                  # SMTP password
ALERT_EMAIL=                # Notification recipient email
WEBHOOK_URL=                # Webhook URL for alert notifications
```

### Container Images

```ini title=".env"
MALCOLM_IMAGE_REGISTRY=ghcr.io/idaholab/malcolm    # Malcolm container registry
MALCOLM_IMAGE_TAG=26.02.0                           # Malcolm version tag
```

### Daemon

```ini title=".env"
API_PORT=8880                       # Daemon API port
STORAGE_CHECK_INTERVAL=300          # Storage check frequency (seconds)
SMART_CHECK_INTERVAL=3600           # SMART check frequency (seconds)
SMART_DEVICE=/dev/nvme0n1           # Storage device to monitor
LOG_LEVEL=INFO                      # Daemon log level (DEBUG, INFO, WARNING, ERROR)
```

For the complete reference of all environment variables, see [Environment Reference](../reference/env-reference.md).

---

## Applying Configuration Changes

Most configuration changes require a service restart:

```bash
sudo systemctl restart nettap
```

Some changes may require reapplying specific configurations:

| Change | Action Required |
|---|---|
| Interface names | Restart + re-run bridge setup |
| Retention periods | Restart + reapply ILM policies |
| OpenSearch heap | Restart (containers recreated) |
| Dashboard hostname | Restart + Avahi restart |
| SMTP / webhook settings | Restart daemon only |
| Log level | Restart daemon only |

---

## Firewall Configuration

If UFW is active, the installer adds rules automatically. To manage manually:

```bash
# View current rules
sudo ufw status verbose

# Add dashboard access
sudo ufw allow 443/tcp comment "NetTap dashboard"

# Add Malcolm dashboards
sudo ufw allow 9443/tcp comment "Malcolm dashboards"

# Add mDNS
sudo ufw allow 5353/udp comment "mDNS (avahi)"

# Restrict dashboard to specific subnet
sudo ufw allow from 192.168.1.0/24 to any port 443 proto tcp comment "NetTap dashboard (LAN only)"
```

The dedicated firewall setup script provides additional hardening:

```bash
sudo scripts/install/setup-firewall.sh
```

---

## Docker Compose Overrides

For advanced configuration, you can create a `docker-compose.override.yml` file alongside the main compose file:

```yaml title="docker/docker-compose.override.yml"
services:
  opensearch:
    environment:
      OPENSEARCH_JAVA_OPTS: "-Xms8g -Xmx8g"  # Override heap size

  zeek-live:
    environment:
      ZEEK_LOCAL_NETS: "10.0.0.0/8"  # Override local network definition
```

Docker Compose automatically merges override files with the main configuration.

---

## Settings via Dashboard

Some settings can also be changed through the web dashboard:

- **Settings** (`/settings`) --- general configuration
- **Notifications** (`/settings/notifications`) --- email, webhook, and in-app notification setup
- **System** (`/system`) --- view system health and storage status

Dashboard settings changes are persisted and take effect immediately without requiring a service restart.
