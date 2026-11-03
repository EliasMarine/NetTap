# Backup & Restore

NetTap keeps network telemetry in OpenSearch, its own settings and records in Docker volumes, and its configuration and secrets in files next to the code. This page covers how to back up and restore all three.

Every command runs on the NetTap box. Set `NETTAP_DIR` to wherever you cloned NetTap first. The examples use `/opt/nettap`; some installs use `/home/nettap/NetTap`:

```bash
NETTAP_DIR=/opt/nettap
```

---

## What to Back Up

| Data | Where it lives | Importance |
|---|---|---|
| **Configuration and secrets** | `$NETTAP_DIR/.env`, `$NETTAP_DIR/docker/.env`, and the `docker/auth/`, `docker/curlrc/`, `docker/certs/` and `docker/ssl/` folders | Critical. `docker/.env` is the file Docker Compose reads, and the folders hold the OpenSearch logins and TLS keys |
| **OpenSearch data** | `docker_opensearch-data` Docker volume | High. All Zeek and Suricata records and the device registry |
| **NetTap records** | `docker_nettap-appdata` volume (`/opt/nettap/data` inside `nettap-storage-daemon`) | Medium. Investigations, device baseline, detection packs, retention settings and excluded IPs |
| **Dashboard logins** | `docker_web-data` volume (`/var/lib/nettap-web` inside `nettap-web`) | Medium. The web UI's user accounts and session key |
| **Grafana dashboards** | `docker_grafana-data` volume | Low. Grafana is off by default |
| **Raw PCAP** | `docker_pcap-data` volume | Usually skipped. It's large and rotates on its own |

!!! note "Volume names start with `docker_`"
    Docker Compose names volumes after the folder that holds `docker-compose.yml`, which is `docker/`. Check the real names with `sudo docker volume ls`. A command that names a volume that doesn't exist (for example `opensearch-data` without the prefix) silently creates a new, empty one.

Store backups somewhere other than the NetTap disk. The commands below write to `/var/backups/nettap`; copy that folder off the box afterwards.

---

## Backing Up Configuration and Secrets

```bash
sudo mkdir -p /var/backups/nettap
sudo tar czf /var/backups/nettap/config-$(date +%Y%m%d).tar.gz -C "$NETTAP_DIR" \
  .env docker/.env docker/auth docker/curlrc docker/certs docker/ssl
sudo chmod 600 /var/backups/nettap/config-*.tar.gz
```

The archive holds passwords and private keys, so keep it private.

## Backing Up NetTap Records and Logins

These volumes are read through the running containers, so nothing needs to stop:

```bash
sudo sh -c 'docker exec nettap-storage-daemon tar czf - -C /opt/nettap/data . > /var/backups/nettap/appdata-$(date +%Y%m%d).tar.gz'
sudo sh -c 'docker exec nettap-web tar czf - -C /var/lib/nettap-web . > /var/backups/nettap/webdata-$(date +%Y%m%d).tar.gz'
sudo chmod 600 /var/backups/nettap/webdata-*.tar.gz

# Check what went in
sudo tar tzf /var/backups/nettap/appdata-$(date +%Y%m%d).tar.gz
```

To restore one, copy it back in and restart the container:

```bash
sudo sh -c 'docker exec -i nettap-storage-daemon tar xzf - -C /opt/nettap/data < /var/backups/nettap/appdata-20261102.tar.gz'
sudo docker restart nettap-storage-daemon
```

---

## OpenSearch Snapshots

OpenSearch snapshots capture indices while NetTap keeps running. OpenSearch only answers with a login. The `osapi` helper below runs each call inside the OpenSearch container with the login NetTap already stores there, so you never type the password:

```bash
osapi() { sudo docker exec nettap-opensearch curl -sk --config /var/local/curlrc/.opensearch.primary.curlrc "$@"; }
```

A plain `curl -sk https://localhost:9200/...` from the host answers `401 Unauthorized`.

### Setting Up a Snapshot Repository

Register a filesystem repository once:

```bash
osapi -X PUT "https://localhost:9200/_snapshot/nettap_backup" \
  -H "Content-Type: application/json" \
  -d '{"type": "fs", "settings": {"location": "/opt/opensearch/backup/nettap", "compress": true}}'
```

It answers `{"acknowledged":true}`. `/opt/opensearch/backup` is the `docker_opensearch-backup` volume, already allowed as `path.repo` in the compose file. On the host, the files live in `/var/lib/docker/volumes/docker_opensearch-backup/_data/nettap`.

### Creating a Snapshot

```bash
osapi -X PUT "https://localhost:9200/_snapshot/nettap_backup/snapshot_$(date +%Y%m%d)?wait_for_completion=true" \
  -H "Content-Type: application/json" \
  -d '{"indices": "arkime_sessions3-*,malcolm_beats_*,nettap-*", "ignore_unavailable": true, "include_global_state": false}'
```

The reply ends with `"state":"SUCCESS"` and `"failed":0`. Zeek logs and Suricata alerts are both in the daily `arkime_sessions3-*` indices; `nettap-*` holds the device registry and change log.

To take the snapshots off the box:

```bash
sudo tar czf /var/backups/nettap/snapshots-$(date +%Y%m%d).tar.gz \
  -C /var/lib/docker/volumes/docker_opensearch-backup/_data nettap
```

### Checking Snapshots

```bash
# List all snapshots
osapi "https://localhost:9200/_cat/snapshots/nettap_backup?v"

# Which indices one snapshot holds
osapi "https://localhost:9200/_snapshot/nettap_backup/snapshot_20261102" | python3 -m json.tool
```

### Restoring from a Snapshot

Try a restore under a new name first. It leaves the live data alone:

```bash
osapi -X POST "https://localhost:9200/_snapshot/nettap_backup/snapshot_20261102/_restore?wait_for_completion=true" \
  -H "Content-Type: application/json" \
  -d '{"indices": "nettap-devices", "rename_pattern": "(.+)", "rename_replacement": "restored-$1", "include_global_state": false}'

osapi "https://localhost:9200/_cat/indices/nettap-devices,restored-nettap-devices?v&h=index,docs.count"
osapi -X DELETE "https://localhost:9200/restored-nettap-devices"
```

!!! danger "A full restore overwrites existing data"
    Restoring into the original names replaces what is in those indices now.

An open index can't be restored over, so close the ones you restore first:

```bash
osapi -X POST "https://localhost:9200/arkime_sessions3-*,nettap-*/_close"

osapi -X POST "https://localhost:9200/_snapshot/nettap_backup/snapshot_20261102/_restore?wait_for_completion=true" \
  -H "Content-Type: application/json" \
  -d '{"indices": "arkime_sessions3-*,malcolm_beats_*,nettap-*", "ignore_unavailable": true, "include_global_state": false}'
```

Restored indices open on their own once the restore finishes.

---

## Docker Volume Backup

A copy of the whole OpenSearch volume needs NetTap stopped. Snapshots (above) are the tested path and need no downtime.

```bash
# Stop services first
sudo systemctl stop nettap

# Back up the OpenSearch data volume
sudo docker run --rm \
  -v docker_opensearch-data:/data:ro \
  -v /var/backups/nettap:/backup \
  alpine tar czf /backup/opensearch-data-$(date +%Y%m%d).tar.gz -C /data .

# Restart services
sudo systemctl start nettap
```

### Restoring Docker Volumes

```bash
sudo systemctl stop nettap

sudo docker run --rm \
  -v docker_opensearch-data:/data \
  -v /var/backups/nettap:/backup \
  alpine sh -c "rm -rf /data/* && tar xzf /backup/opensearch-data-20261102.tar.gz -C /data"

sudo systemctl start nettap
```

After a volume restore, run the OpenSearch security bootstrap from the project README. Recreating the OpenSearch container resets its role mapping.

---

## Automated Backups

Create a cron job for daily backups:

```bash
sudo crontab -e
```

Add (change the path to your `NETTAP_DIR`):

```cron
# Daily NetTap backup at 2 AM
0 2 * * * /opt/nettap/scripts/backup.sh >> /var/log/nettap-backup.log 2>&1
```

Example backup script. Save it as `$NETTAP_DIR/scripts/backup.sh` and `chmod 700` it. Cron runs it as root, so it needs no `sudo`:

```bash title="/opt/nettap/scripts/backup.sh"
#!/bin/bash
set -uo pipefail

NETTAP_DIR=/opt/nettap
BACKUP_DIR=/var/backups/nettap
DATE=$(date +%Y%m%d)
KEEP_DAYS=7

osapi() { docker exec nettap-opensearch curl -sk --config /var/local/curlrc/.opensearch.primary.curlrc "$@"; }

mkdir -p "$BACKUP_DIR"

# Configuration and secrets
tar czf "$BACKUP_DIR/config-$DATE.tar.gz" -C "$NETTAP_DIR" \
  .env docker/.env docker/auth docker/curlrc docker/certs docker/ssl

# NetTap records and dashboard logins
docker exec nettap-storage-daemon tar czf - -C /opt/nettap/data . > "$BACKUP_DIR/appdata-$DATE.tar.gz"
docker exec nettap-web tar czf - -C /var/lib/nettap-web . > "$BACKUP_DIR/webdata-$DATE.tar.gz"
chmod 600 "$BACKUP_DIR"/*.tar.gz

# OpenSearch snapshot (the nettap_backup repository must be registered once, see above)
osapi -X PUT "https://localhost:9200/_snapshot/nettap_backup/snapshot_$DATE?wait_for_completion=true" \
  -H "Content-Type: application/json" \
  -d '{"indices":"arkime_sessions3-*,malcolm_beats_*,nettap-*","ignore_unavailable":true,"include_global_state":false}' \
  | grep -q '"state":"SUCCESS"' || echo "Snapshot $DATE did not succeed"

# Drop the snapshot and archives from KEEP_DAYS ago
osapi -X DELETE "https://localhost:9200/_snapshot/nettap_backup/snapshot_$(date -d "$KEEP_DAYS days ago" +%Y%m%d)" >/dev/null
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +$KEEP_DAYS -delete

echo "Backup completed: $DATE"
```

---

## Disaster Recovery

If the system needs a complete rebuild:

1. Install a fresh Ubuntu Server.
2. Clone NetTap to the same path and unpack the config archive into it: `sudo tar xzf config-YYYYMMDD.tar.gz -C "$NETTAP_DIR"`.
3. Run `sudo scripts/install/install.sh`. It keeps the restored `docker/.env` and secrets.
4. Restore OpenSearch from a snapshot (register the repository, then restore) or from a volume backup.
5. Restore the NetTap records and dashboard logins archives.
6. Verify the data on the dashboard.
