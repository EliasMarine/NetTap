# Storage Management

NetTap uses a three-tier storage architecture to balance retention needs with disk space. This page explains how storage works and how to manage it.

---

## Three-Tier Storage Architecture

| Tier | Data | Default Retention | Daily Size | Compression |
|---|---|---|---|---|
| **Hot** | Zeek metadata logs | 90 days | 300--800 MB | ~8:1 (zstd) |
| **Warm** | Suricata IDS alerts | 180 days | 10--50 MB | ~6:1 (zstd) |
| **Cold** | PCAP captures (alert-triggered) | 30 days | Variable | ~3:1 (zstd) |

### Hot Tier (Zeek Metadata)

Zeek generates structured JSON logs for every network connection: conn, DNS, HTTP, TLS, DHCP, SMTP, and file metadata. These logs are the richest source of network visibility data.

- **Index pattern:** `zeek-*`
- **Rollover:** At 10 GB or 1 day (whichever comes first)
- **Retention:** 90 days by default (configurable via `RETENTION_HOT`)
- **Action at expiry:** Automatic deletion

### Warm Tier (Suricata Alerts)

Suricata alert and protocol logs are kept longer because alert data is typically smaller and more valuable for historical investigation.

- **Index pattern:** `suricata-*`
- **Rollover:** At 5 GB or 1 day
- **Optimization:** After 7 days, indices are force-merged to 1 segment and set to read-only (reduces resource usage)
- **Retention:** 180 days by default (configurable via `RETENTION_WARM`)
- **Action at expiry:** Automatic deletion

### Cold Tier (PCAP Captures)

Raw packet captures are stored for forensic analysis but consume significant disk space.

- **Index pattern:** `arkime-*`, `pcap-*`
- **Rollover:** At 20 GB or 1 day
- **Retention:** 30 days by default (configurable via `RETENTION_COLD`)
- **Action at expiry:** Automatic deletion

---

## Index Lifecycle Management (ILM)

OpenSearch ISM (Index State Management) policies automatically manage the lifecycle of each index tier. The policies are defined in `config/opensearch/ilm-policy.json` and applied automatically during installation.

### Policy Flow

```
Hot state                   Warm state (alerts only)         Delete state
  ├─ Rollover on size/age     ├─ Force merge to 1 segment     └─ Delete index
  └─ Transition to next       ├─ Set read-only
     state after N days        └─ Transition to delete
                                  after N days
```

All policy actions include retry logic (3 attempts with exponential backoff) to handle transient OpenSearch errors.

### Reapplying Policies

If you change retention settings, reapply ILM policies:

=== "Via Dashboard"

    Go to **System** and use the storage management panel.

=== "Via API"

    ```bash
    curl -X POST http://localhost:8880/api/ilm/apply
    ```

---

## Disk Monitoring

The NetTap storage daemon monitors disk usage continuously and takes action to prevent the disk from filling up.

### Thresholds

| Threshold | Default | Action |
|---|---|---|
| **Warning** | 80% | Begins pruning oldest data from each tier |
| **Emergency** | 90% | Aggressive pruning of all tiers |

When disk usage exceeds the warning threshold:

1. The daemon identifies the oldest indices in each tier
2. Deletes indices beyond their retention period first
3. If still above threshold, deletes the oldest indices regardless of retention

### Monitoring Interval

The storage daemon runs a maintenance cycle every 5 minutes (configurable via `STORAGE_CHECK_INTERVAL`).

### Viewing Disk Status

=== "Via Dashboard"

    Go to **System** to see:

    - Disk usage (total, used, available)
    - Disk usage percentage with color-coded bar
    - Per-tier index counts and sizes

=== "Via API"

    ```bash
    # Full storage status
    curl http://localhost:8880/api/storage/status

    # List all indices
    curl http://localhost:8880/api/indices
    ```

=== "Via Command Line"

    ```bash
    # Check disk usage
    df -h /

    # Check OpenSearch index sizes
    curl -sk https://localhost:9200/_cat/indices?v&s=store.size:desc
    ```

---

## SMART Health Monitoring

NetTap monitors the SSD's SMART (Self-Monitoring, Analysis and Reporting Technology) attributes to detect drive health issues before they cause failures.

### Monitored Attributes

- **Overall health status** (PASSED / FAILED)
- **Temperature** (current, with warning thresholds)
- **Percentage used** (NVMe wear indicator)
- **Power-on hours**
- **Unsafe shutdowns**
- **Media errors**

### Viewing SMART Status

Go to **System** in the dashboard, or query the API:

```bash
curl http://localhost:8880/api/smart/health
```

### SSD Write Protection

NetTap includes several measures to extend SSD lifespan:

- **30-second log flush intervals** --- Zeek batches log writes instead of writing per-event
- **Write coalescing** --- logs are compressed (zstd) before being written to OpenSearch
- **Docker log rotation** --- container logs are capped at 10 MB with 3 rotations maximum

---

## Changing Retention Settings

### Via Environment Variables

Edit `.env` and restart:

```ini title=".env"
RETENTION_HOT=90              # Zeek metadata (days)
RETENTION_WARM=180            # Suricata alerts (days)
RETENTION_COLD=30             # PCAP captures (days)
DISK_THRESHOLD_PERCENT=80     # Start pruning at this disk usage
```

```bash
sudo systemctl restart nettap
```

### Storage Sizing Guide

| Network Size | Daily Data | 1 TB Drive Lasts |
|---|---|---|
| Small home (5--10 devices) | ~400 MB/day | 3+ years |
| Medium home (15--25 devices) | ~800 MB/day | 2+ years |
| Small office (25--50 devices) | ~1.5 GB/day | 1+ year |
| Heavy use / large office | ~3+ GB/day | Adjust retention or add storage |

---

## Manual Maintenance

### Trigger a Manual Prune Cycle

```bash
curl -X POST http://localhost:8880/api/storage/prune
```

This runs the same maintenance cycle that normally executes every 5 minutes, but immediately.

### Delete Specific Indices

If you need to free space urgently, delete specific OpenSearch indices:

```bash
# List indices sorted by size
curl -sk https://localhost:9200/_cat/indices?v&s=store.size:desc

# Delete a specific index
curl -sk -X DELETE https://localhost:9200/zeek-2024.01.15
```

!!! danger "Data loss"
    Deleting indices permanently removes that data. There is no undo unless you have a backup.
