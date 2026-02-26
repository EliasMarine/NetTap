# Configuration Files Reference

NetTap uses several configuration files to customize the behavior of Zeek, Suricata, OpenSearch ILM, Grafana, and the hardware watchdog. This page documents each file.

---

## Zeek Configuration

### `config/zeek/nettap.zeek`

Zeek script overrides loaded at startup. Mounted into the Zeek container at `/opt/zeek/share/zeek/site/local.zeek`.

```zeek title="config/zeek/nettap.zeek"
# Capture interface — full packet snaplen
redef Pcap::snaplen = 65535;

# Log rotation — batch writes every 30s to reduce SSD wear
redef Log::default_rotation_interval = 30sec;

# Enable JSON output for OpenSearch ingestion
@load policy/tuning/json-logs

# Disable gzip (using zstd in the log pipeline instead)
redef LogAscii::gzip_level = 0;
redef LogAscii::enable_utf_8 = T;

# Load standard protocol analyzers
@load base/protocols/conn
@load base/protocols/dns
@load base/protocols/http
@load base/protocols/ssl
@load base/protocols/dhcp
@load base/protocols/smtp
@load base/files/extract-all-files

# File analysis
@load frameworks/files/hash-all-files
```

**Key settings:**

| Setting | Value | Purpose |
|---|---|---|
| `Pcap::snaplen` | 65535 | Capture full packets (not truncated) |
| `Log::default_rotation_interval` | 30sec | Batch log writes to reduce SSD wear |
| `LogAscii::gzip_level` | 0 | Disable gzip; zstd is used in the log pipeline instead |
| Protocol analyzers | conn, dns, http, ssl, dhcp, smtp, files | Generate logs for these protocols |

**Compression strategy:** Zeek writes uncompressed JSON logs. The log pipeline (Filebeat -> Logstash) applies zstd compression (~8:1 ratio) before shipping to OpenSearch. This trades temporary disk space for better compression ratios and lower CPU on the capture path.

---

## Suricata Configuration

### `config/suricata/nettap.yaml`

Suricata configuration overrides merged with Malcolm's defaults. Mounted at `/etc/suricata/nettap.yaml`.

```yaml title="config/suricata/nettap.yaml"
# Capture interface — the bridge
af-packet:
  - interface: br0
    cluster-id: 99
    cluster-type: cluster_flow
    defrag: yes
    use-mmap: yes
    ring-size: 200000

# Emerging Threats Open ruleset
default-rule-path: /var/lib/suricata/rules
rule-files:
  - suricata.rules

# Output — Eve JSON for OpenSearch ingestion
outputs:
  - eve-log:
      enabled: yes
      filetype: regular
      filename: eve.json
      rotate-interval: day
      types:
        - alert
        - dns
        - tls
        - http
        - files
        - flow
```

**Key settings:**

| Setting | Value | Purpose |
|---|---|---|
| `af-packet.interface` | `br0` | Capture from the bridge interface |
| `cluster-type` | `cluster_flow` | Flow-based load balancing across workers |
| `use-mmap` | yes | Memory-mapped I/O for higher capture throughput |
| `ring-size` | 200000 | Large ring buffer to prevent drops under burst |
| Eve log types | alert, dns, tls, http, files, flow | Which event types to log |
| `rotate-interval` | day | Daily log file rotation |

**Compression strategy:** Like Zeek, Suricata writes uncompressed eve.json. The Filebeat/Logstash pipeline handles zstd compression (~6:1) asynchronously.

---

## OpenSearch ILM Policies

### `config/opensearch/ilm-policy.json`

OpenSearch Index State Management (ISM) policies for three-tier data retention. Applied automatically during installation.

The file contains three policies:

### `nettap-hot-policy`

- **Applied to:** `zeek-*` indices (priority 100)
- **Hot state:** Rollover at 10 GB primary shard size or 1 day
- **Delete state:** Delete indices older than 90 days
- **Retry:** 3 attempts with exponential backoff (10 minute delay)

### `nettap-warm-policy`

- **Applied to:** `suricata-*` indices (priority 100)
- **Hot state:** Rollover at 5 GB or 1 day
- **Warm state (after 7 days):** Force merge to 1 segment, set read-only
- **Delete state:** Delete indices older than 180 days

### `nettap-cold-policy`

- **Applied to:** `arkime-*` and `pcap-*` indices (priority 100)
- **Hot state:** Rollover at 20 GB or 1 day
- **Delete state:** Delete indices older than 30 days

---

## Grafana Configuration

### `config/grafana/provisioning/datasources/datasource.yaml`

Grafana datasource provisioning. Auto-configures OpenSearch connections on startup.

```yaml title="config/grafana/provisioning/datasources/datasource.yaml"
apiVersion: 1
datasources:
  - name: OpenSearch-Zeek
    type: grafana-opensearch-datasource
    access: proxy
    url: http://opensearch:9200
    database: "zeek-*"
    isDefault: true
    jsonData:
      timeField: "ts"
      version: "2.11.0"
      flavor: "opensearch"
    editable: false

  - name: OpenSearch-Suricata
    type: grafana-opensearch-datasource
    access: proxy
    url: http://opensearch:9200
    database: "suricata-*"
    jsonData:
      timeField: "timestamp"
      version: "2.11.0"
      flavor: "opensearch"
    editable: false
```

Two datasources are configured:

| Datasource | Index Pattern | Time Field | Purpose |
|---|---|---|---|
| OpenSearch-Zeek | `zeek-*` | `ts` | Zeek metadata queries |
| OpenSearch-Suricata | `suricata-*` | `timestamp` | Suricata alert queries |

### `config/grafana/provisioning/dashboards/dashboard.yaml`

Dashboard provisioning configuration. Points Grafana to the dashboard JSON files.

### `config/grafana/dashboards/`

Pre-built Grafana dashboard JSON files:

| Dashboard | File | Description |
|---|---|---|
| Network Overview | `network-overview.json` | High-level traffic summary |
| Bandwidth Trending | `bandwidth-trending.json` | Bandwidth over time with trending |
| GeoIP Map | `geoip-map.json` | World map of external connections |
| Security Alerts | `security-alerts.json` | Suricata alert dashboard |
| System Health | `system-health.json` | System resource monitoring |

---

## Watchdog Configuration

### `config/watchdog/watchdog.conf`

Hardware watchdog timer configuration. Deployed to `/etc/watchdog.conf` by `scripts/install/setup-watchdog.sh`.

```ini title="config/watchdog/watchdog.conf"
watchdog-device = /dev/watchdog
interval = 10
watchdog-timeout = 60
max-load-1 = 24
min-memory = 1
ping = 127.0.0.1
log-dir = /var/log/watchdog
realtime = yes
priority = 1
```

| Setting | Value | Purpose |
|---|---|---|
| `watchdog-device` | `/dev/watchdog` | Kernel watchdog device node |
| `interval` | 10s | Pet frequency (5 pets per timeout window) |
| `watchdog-timeout` | 60s | Hardware reboot trigger if no pet received |
| `max-load-1` | 24 | Reboot if 1-minute load average exceeds 24 (6x cores) |
| `min-memory` | 1 page | Extreme memory exhaustion failsafe |
| `ping` | 127.0.0.1 | Test kernel network stack is alive |
| `realtime` | yes | Run with realtime scheduling priority |

The watchdog is a last-resort failsafe. If the system hangs, the hardware watchdog triggers a reboot within ~90 seconds, restoring network traffic flow.

---

## Kernel Tuning

### `/etc/sysctl.d/99-nettap.conf`

Applied by the installer for OpenSearch and capture performance:

```ini
vm.max_map_count = 262144
net.core.rmem_max = 134217728
net.core.wmem_max = 134217728
net.core.rmem_default = 16777216
net.core.netdev_max_backlog = 5000
net.netfilter.nf_conntrack_max = 1048576
```

### `/etc/sysctl.d/99-nettap-bridge.conf`

Applied by the bridge setup script:

```ini
net.bridge.bridge-nf-call-iptables = 0
net.bridge.bridge-nf-call-ip6tables = 0
net.bridge.bridge-nf-call-arptables = 0
net.ipv6.conf.br0.disable_ipv6 = 1
```

---

## Netplan Bridge Configuration

### `/etc/netplan/10-nettap-bridge.yaml`

Generated by `setup-bridge.sh --persist`:

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    eth0:
      dhcp4: false
      dhcp6: false
      optional: true
    eth1:
      dhcp4: false
      dhcp6: false
      optional: true
  bridges:
    br0:
      interfaces:
        - eth0
        - eth1
      dhcp4: false
      dhcp6: false
      parameters:
        stp: false
        forward-delay: 0
```

---

## Docker Daemon Configuration

### `/etc/docker/daemon.json`

Applied by the installer:

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "storage-driver": "overlay2"
}
```

Ensures container log rotation (10 MB max, 3 files) and uses the overlay2 storage driver.
