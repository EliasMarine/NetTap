# Storage Management

NetTap uses a three-tier storage architecture to balance retention needs with disk space. This page explains how storage works and how to manage it.

---

## Three-Tier Storage Architecture

| Tier | Data | Default Retention | Where it lives |
|---|---|---|---|
| **Hot** | Zeek logs **and** Suricata alerts | 90 days (`RETENTION_HOT`) | One daily OpenSearch index, `arkime_sessions3-YYMMDD` |
| **Warm** | Separate `suricata-*` indices only | 180 days (`RETENTION_WARM`) | Not created by a Malcolm install, so this setting is normally unused |
| **Cold** | PCAP captures (all traffic) | 30 days (`RETENTION_COLD`) | Files under `/opt/nettap/pcap`, capped at `PCAP_MAX_DISK_PCT` of the disk |

### Hot Tier (Zeek logs and Suricata alerts)

Malcolm's Logstash writes every Zeek log (conn, DNS, HTTP, TLS, DHCP, SMTP, files) and every Suricata alert into the same daily index.

- **Index pattern:** `arkime_sessions3-*` (plus `malcolm_beats_*` host data, if present)
- **Retention:** 90 days by default (`RETENTION_HOT`). The whole daily index is deleted, so **alerts are kept exactly as long as Zeek logs**.
- **Action at expiry:** automatic deletion by the `nettap-hot-policy` ISM policy.

### Warm Tier (separate Suricata indices)

The daemon keeps a warm retention setting for `suricata-*` indices, but a standard install never creates them: alerts go into the hot index above. To keep alerts longer, raise the hot retention.

### Cold Tier (PCAP Captures)

netsniff-ng records all traffic to rotating PCAP files. They are files, not OpenSearch indices.

- **Location:** `/opt/nettap/pcap` (rotated by `PCAP_ROTATE_MB` or every `PCAP_ROTATE_MIN` minutes)
- **Retention:** 30 days by default (`RETENTION_COLD`)
- **Disk cap:** PCAP files are capped at `PCAP_MAX_DISK_PCT` percent of the disk (default 25; 0 disables the cap). The storage daemon deletes the oldest files first.
- **Action at expiry:** the storage daemon deletes the file.

---

## Index Lifecycle Management (ILM)

OpenSearch ISM (Index State Management) manages the hot indices. The daemon builds the policy from your retention settings (`daemon/storage/ilm_generator.py`) and applies it at startup and whenever retention is saved; `config/opensearch/ilm-policy.json` is the fallback.

### Policy Flow

```
nettap-hot-policy  (arkime_sessions3-*, malcolm_beats_*, zeek-*)
  hot ── after RETENTION_HOT days ──> delete
```

There is no rollover or force-merge: Malcolm already starts a new index each day.

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
