# API Reference

The NetTap daemon exposes a REST API on port 8880 for the web dashboard and external integrations. All endpoints return JSON.

---

## Base URL

```
http://localhost:8880
```

The API is intended for LAN-only access. CORS is configured to allow all origins (since the appliance runs on a private network).

---

## Health & System

### `GET /api/health`

Simple liveness check.

**Response:**

```json
{
  "status": "ok",
  "uptime": 3642.15
}
```

### `GET /api/system/health`

Combined system health check aggregating daemon uptime, storage status, SMART health, and OpenSearch reachability.

**Response:**

```json
{
  "uptime": 3642.15,
  "timestamp": "2026-02-26T10:30:00.000000+00:00",
  "storage": { ... },
  "smart": { ... },
  "opensearch_reachable": true,
  "healthy": true
}
```

---

## Storage

### `GET /api/storage/status`

Full storage status from the StorageManager.

**Response:**

```json
{
  "disk": {
    "total": 1000204886016,
    "used": 450000000000,
    "free": 550204886016,
    "percent": 45.0
  },
  "retention": {
    "hot_days": 90,
    "warm_days": 180,
    "cold_days": 30,
    "disk_threshold": 0.80
  },
  "indices": {
    "zeek": 42,
    "suricata": 85,
    "arkime": 15
  }
}
```

### `GET /api/storage/retention`

Retention configuration only (subset of storage status).

### `POST /api/storage/prune`

Trigger a manual prune/maintenance cycle. Returns the storage status after pruning.

**Response:**

```json
{
  "result": "prune_cycle_complete",
  "storage_status": { ... }
}
```

### `GET /api/indices`

List all tracked OpenSearch indices with metadata.

**Response:**

```json
{
  "indices": [
    {
      "index": "zeek-2026.02.26",
      "health": "green",
      "store_size": "245mb",
      "docs_count": "1500000",
      "parsed_date": "2026-02-26T00:00:00"
    }
  ],
  "count": 42
}
```

---

## SMART Health

### `GET /api/smart/health`

SSD SMART health status.

**Response:**

```json
{
  "healthy": true,
  "device": "/dev/nvme0n1",
  "temperature": 38,
  "percentage_used": 2,
  "power_on_hours": 1500,
  "unsafe_shutdowns": 3,
  "media_errors": 0
}
```

---

## ILM Policies

### `POST /api/ilm/apply`

Apply ILM (Index State Management) policies to OpenSearch.

**Response:**

```json
{
  "result": "ilm_policies_applied",
  "policies": {
    "nettap-hot-policy": "applied",
    "nettap-warm-policy": "applied",
    "nettap-cold-policy": "applied"
  }
}
```

---

## Traffic Analysis

### `GET /api/traffic/summary`

Traffic summary statistics.

**Query Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `from` | string | Start time (ISO 8601) |
| `to` | string | End time (ISO 8601) |

### `GET /api/traffic/bandwidth`

Bandwidth time series data.

**Query Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `from` | string | 24h ago | Start time |
| `to` | string | now | End time |
| `interval` | string | `1h` | Bucket interval |

### `GET /api/traffic/protocols`

Protocol distribution.

### `GET /api/traffic/top-talkers`

Top talkers (source IPs by bandwidth).

**Query Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 10 | Number of results |

### `GET /api/traffic/categories`

Traffic categorization by bandwidth.

---

## Alerts

### `GET /api/alerts`

List Suricata IDS alerts.

**Query Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `from` | string | Start time |
| `to` | string | End time |
| `severity` | int | Filter by severity (1=HIGH, 2=MEDIUM, 3=LOW) |
| `size` | int | Number of results (default 50) |
| `offset` | int | Pagination offset |

### `GET /api/alerts/count`

Alert counts by severity.

**Response:**

```json
{
  "counts": {
    "total": 150,
    "high": 5,
    "medium": 45,
    "low": 100
  }
}
```

---

## Devices

### `GET /api/devices`

List all discovered network devices.

**Query Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `sort` | string | Sort column (ip, hostname, last_seen, etc.) |
| `order` | string | Sort direction (asc, desc) |
| `limit` | int | Number of results |

### `GET /api/devices/{ip}`

Detailed information about a specific device.

---

## GeoIP

### `GET /api/geoip/{ip}`

GeoIP lookup for an IP address.

**Response:**

```json
{
  "ip": "93.184.216.34",
  "country": "United States",
  "city": "Norwell",
  "latitude": 42.1596,
  "longitude": -70.8217,
  "asn": 15133,
  "org": "Edgecast Inc."
}
```

---

## Risk Scoring

### `GET /api/risk/scores`

Risk scores for all devices.

### `GET /api/risk/scores/{ip}`

Risk score for a specific device (0--100).

---

## Device Baseline

### `GET /api/baseline`

List all known (baselined) devices.

### `POST /api/baseline`

Add a device to the known-device baseline.

---

## Investigations

### `GET /api/investigations`

List all investigation bookmarks.

### `POST /api/investigations`

Create a new investigation.

### `PUT /api/investigations/{id}`

Update an investigation.

### `DELETE /api/investigations/{id}`

Delete an investigation.

---

## Search

### `POST /api/search`

Natural language search. Parses a plain-English query into an OpenSearch query and returns results.

**Request Body:**

```json
{
  "query": "DNS queries to suspicious domains in the last 24 hours"
}
```

---

## Bridge Health

### `GET /api/bridge/health`

Bridge interface status and health.

---

## Software Updates

### `GET /api/updates/versions`

Current component version inventory.

### `POST /api/updates/check`

Check for available updates.

### `GET /api/updates/available`

List available updates.

### `POST /api/updates/apply`

Apply selected updates.

### `GET /api/updates/status`

Current update operation status.

### `GET /api/updates/history`

History of applied updates.

### `POST /api/updates/rollback/{component}`

Roll back a component to its previous version.

---

## NIC Identification

### `POST /api/setup/nics/identify`

Blink the LED on a network interface for physical identification.

**Request Body:**

```json
{
  "interface": "enp1s0",
  "duration": 15
}
```

---

## TShark Packet Analysis

### `POST /api/tshark/analyze`

Analyze a PCAP file with TShark.

---

## CyberChef

### `GET /api/cyberchef/status`

CyberChef service status.

### `POST /api/cyberchef/bake`

Run a CyberChef recipe on input data.

---

## Detection Packs

### `GET /api/detection-packs`

List installed detection packs.

### `POST /api/detection-packs/install`

Install a community detection pack.

---

## Reports

### `GET /api/reports`

List generated reports.

### `POST /api/reports/generate`

Generate a new report.

### `GET /api/reports/schedules`

List report schedules.

---

## Settings

### `GET /api/settings`

Get current settings.

### `POST /api/settings`

Update settings.

---

## Error Responses

All endpoints return errors in a consistent format:

```json
{
  "error": "Description of what went wrong"
}
```

HTTP status codes:

| Code | Meaning |
|---|---|
| `200` | Success |
| `400` | Bad request (invalid parameters) |
| `404` | Resource not found |
| `500` | Internal server error |
