# Updating NetTap

NetTap includes a built-in software update system that tracks component versions, checks for updates, and applies them from the dashboard.

---

## Update System Overview

The update system manages three categories of components:

| Category | Components |
|---|---|
| **Core** | NetTap daemon, web dashboard |
| **Docker Images** | Malcolm containers (Zeek, Suricata, Arkime, OpenSearch, etc.), Grafana |
| **System** | Docker Engine, Docker Compose, OS packages |

---

## Checking for Updates

### Via Dashboard

1. Navigate to **System > Software Updates** (`/system/updates`)
2. The version inventory shows all tracked components with their current versions and status
3. Click **Check for Updates** to scan for available updates

Components are grouped by category (Core, Docker Images, System) for easy review.

### Via API

```bash
# Get current component versions
curl http://localhost:8880/api/updates/versions

# Check for available updates
curl -X POST http://localhost:8880/api/updates/check

# Get available updates
curl http://localhost:8880/api/updates/available
```

### Via Command Line

```bash
# Pull latest repository changes
cd /opt/nettap
git pull origin develop

# Pull updated Docker images
docker compose -f docker/docker-compose.yml pull

# Restart services
sudo systemctl restart nettap
```

---

## Applying Updates

### Via Dashboard

1. After checking for updates, available updates appear in the update panel
2. Select which components to update (or select all)
3. Click **Apply Updates**
4. The system creates a backup, pulls new images, and restarts affected containers
5. Progress and status are shown in real-time

### Via Command Line

```bash
cd /opt/nettap

# Pull latest code
git pull origin develop

# Pull updated container images
docker compose -f docker/docker-compose.yml pull

# Restart with new images
sudo systemctl restart nettap
```

---

## Rollback

If an update causes issues, you can roll back individual components:

### Via Dashboard

On the Software Updates page, each component shows a **Rollback** option if a previous version is available. Click it to revert to the prior version.

### Via Command Line

```bash
# Roll back to a specific Malcolm version
# Edit docker-compose.yml and change the tag
# x-malcolm-tag: &malcolm-tag "26.01.0"  # previous version

# Then restart
sudo systemctl restart nettap
```

---

## Update Schedule

NetTap does not auto-update. You control when updates are applied. We recommend:

- **Check weekly** for security updates
- **Review release notes** before applying updates
- **Back up** before major version upgrades (see [Backup & Restore](backup-restore.md))
- **Test in off-hours** when brief service interruptions are acceptable

---

## Malcolm Version Pinning

NetTap pins Malcolm container images to a specific tested release tag (currently `26.02.0`). This prevents upstream breaking changes from affecting your installation.

The tag is configured in `docker/docker-compose.yml`:

```yaml
x-malcolm-tag: &malcolm-tag "26.02.0"
```

When a new Malcolm release is tested and validated with NetTap, the pinned version is updated in the repository.

!!! warning "Do not change the Malcolm tag manually"
    Changing the Malcolm image tag to an untested version may cause compatibility issues with NetTap's configuration and dashboard integrations.

---

## Update History

The Software Updates page maintains a history of applied updates, showing:

- Component name
- Previous version
- New version
- Timestamp
- Success or failure status
