# Backup & Restore

NetTap stores network telemetry data in OpenSearch and configuration in files on disk. This page covers how to back up and restore both.

---

## What to Back Up

| Data | Location | Importance |
|---|---|---|
| **Configuration** | `/opt/nettap/.env` | Critical --- contains all settings and secrets |
| **OpenSearch data** | `opensearch-data` Docker volume | High --- all Zeek/Suricata logs and alert history |
| **Investigation notes** | `/opt/nettap/data/investigations.json` | Medium --- bookmarked investigations |
| **Device baseline** | `/opt/nettap/data/device_baseline.json` | Medium --- known device registry |
| **Detection packs** | `/opt/nettap/data/detection-packs/` | Low --- can be re-downloaded |
| **Grafana dashboards** | `grafana-data` Docker volume | Low --- can be reprovisioned from config |
| **TLS certificates** | `docker/ssl/` | Medium --- can be regenerated |

---

## Backing Up Configuration

The simplest and most important backup is the `.env` file and data directory:

```bash
# Create a backup directory
mkdir -p /opt/nettap/backups

# Back up configuration
cp /opt/nettap/.env /opt/nettap/backups/.env.$(date +%Y%m%d)

# Back up data files
tar czf /opt/nettap/backups/data-$(date +%Y%m%d).tar.gz \
  -C /opt/nettap data/ 2>/dev/null || true
```

---

## OpenSearch Snapshots

OpenSearch supports snapshot-based backups that capture the full state of all indices.

### Setting Up a Snapshot Repository

First, register a snapshot repository (filesystem-based):

```bash
curl -sk -X PUT "https://localhost:9200/_snapshot/nettap_backup" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "fs",
    "settings": {
      "location": "/opt/opensearch/backup",
      "compress": true
    }
  }'
```

The `opensearch-backup` Docker volume is already mounted at `/opt/opensearch/backup` in the OpenSearch container.

### Creating a Snapshot

```bash
# Create a named snapshot
curl -sk -X PUT "https://localhost:9200/_snapshot/nettap_backup/snapshot_$(date +%Y%m%d)" \
  -H "Content-Type: application/json" \
  -d '{
    "indices": "zeek-*,suricata-*,arkime-*",
    "ignore_unavailable": true,
    "include_global_state": false
  }'
```

### Checking Snapshot Status

```bash
# List all snapshots
curl -sk "https://localhost:9200/_snapshot/nettap_backup/_all" | python3 -m json.tool

# Check status of a specific snapshot
curl -sk "https://localhost:9200/_snapshot/nettap_backup/snapshot_20260226/_status"
```

### Restoring from a Snapshot

!!! danger "Restoration overwrites existing data"
    Restoring indices will replace any existing data in those indices.

```bash
# Close the indices first (if they exist)
curl -sk -X POST "https://localhost:9200/zeek-*/_close"
curl -sk -X POST "https://localhost:9200/suricata-*/_close"

# Restore from snapshot
curl -sk -X POST "https://localhost:9200/_snapshot/nettap_backup/snapshot_20260226/_restore" \
  -H "Content-Type: application/json" \
  -d '{
    "indices": "zeek-*,suricata-*",
    "ignore_unavailable": true,
    "include_global_state": false
  }'
```

---

## Docker Volume Backup

For a complete backup of all Docker volumes:

```bash
# Stop services first
sudo systemctl stop nettap

# Back up OpenSearch data volume
docker run --rm \
  -v opensearch-data:/data:ro \
  -v /opt/nettap/backups:/backup \
  alpine tar czf /backup/opensearch-data-$(date +%Y%m%d).tar.gz -C /data .

# Back up Grafana data volume
docker run --rm \
  -v grafana-data:/data:ro \
  -v /opt/nettap/backups:/backup \
  alpine tar czf /backup/grafana-data-$(date +%Y%m%d).tar.gz -C /data .

# Restart services
sudo systemctl start nettap
```

### Restoring Docker Volumes

```bash
# Stop services
sudo systemctl stop nettap

# Restore OpenSearch data
docker run --rm \
  -v opensearch-data:/data \
  -v /opt/nettap/backups:/backup \
  alpine sh -c "rm -rf /data/* && tar xzf /backup/opensearch-data-20260226.tar.gz -C /data"

# Restart services
sudo systemctl start nettap
```

---

## Automated Backups

Create a cron job for automated daily backups:

```bash
sudo crontab -e
```

Add:

```cron
# Daily NetTap backup at 2 AM
0 2 * * * /opt/nettap/scripts/backup.sh >> /var/log/nettap-backup.log 2>&1
```

Example backup script:

```bash title="/opt/nettap/scripts/backup.sh"
#!/bin/bash
set -euo pipefail

BACKUP_DIR="/opt/nettap/backups"
DATE=$(date +%Y%m%d)
KEEP_DAYS=7

mkdir -p "$BACKUP_DIR"

# Back up configuration
cp /opt/nettap/.env "$BACKUP_DIR/.env.$DATE"

# Back up data files
tar czf "$BACKUP_DIR/data-$DATE.tar.gz" -C /opt/nettap data/ 2>/dev/null || true

# Create OpenSearch snapshot
curl -sk -X PUT "https://localhost:9200/_snapshot/nettap_backup/snapshot_$DATE" \
  -H "Content-Type: application/json" \
  -d '{"indices":"zeek-*,suricata-*","ignore_unavailable":true,"include_global_state":false}'

# Clean up old backups
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +$KEEP_DAYS -delete
find "$BACKUP_DIR" -name ".env.*" -mtime +$KEEP_DAYS -delete

echo "Backup completed: $DATE"
```

---

## Disaster Recovery

If the system needs a complete rebuild:

1. Install a fresh Ubuntu Server
2. Clone NetTap and restore `.env` from backup
3. Run `scripts/install/install.sh`
4. Restore OpenSearch data from snapshot or Docker volume backup
5. Verify data integrity via the dashboard
