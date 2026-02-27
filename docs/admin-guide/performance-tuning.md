# Performance Tuning

NetTap is pre-configured for the reference Intel N100 hardware (4 cores, 16 GB RAM, 1 TB NVMe). This page covers tuning options for different hardware or workloads.

---

## OpenSearch JVM Heap

OpenSearch is the largest memory consumer. The JVM heap size controls how much RAM OpenSearch uses for indexing and search operations.

**Default:** 4 GB (suitable for 16 GB RAM systems)

```ini title=".env"
OPENSEARCH_JAVA_OPTS="-Xms4g -Xmx4g"
```

### Sizing Guidelines

| System RAM | Recommended Heap | Notes |
|---|---|---|
| 8 GB | 2--3 GB | Tight --- may struggle under heavy load |
| 16 GB | 4 GB | Default. Good balance for most home networks |
| 32 GB | 8 GB | Faster queries, larger working set in memory |
| 64 GB+ | 16 GB max | OpenSearch does not benefit from heaps > 32 GB |

!!! warning "Heap must not exceed 50% of system RAM"
    Other services (Zeek, Suricata, the OS) also need memory. As a rule, set OpenSearch heap to no more than 50% of total RAM, and never more than 32 GB.

After changing, restart services:

```bash
sudo systemctl restart nettap
```

---

## Logstash JVM Heap

Logstash processes and enriches logs before they reach OpenSearch.

**Default:** 2 GB

```ini title=".env"
LS_JAVA_OPTS="-Xmx2g -Xms2g"
```

| System RAM | Recommended |
|---|---|
| 8 GB | 1 GB |
| 16 GB | 2 GB |
| 32 GB | 2--4 GB |

---

## Kernel Parameters

The installer applies these kernel tuning parameters in `/etc/sysctl.d/99-nettap.conf`:

```ini title="/etc/sysctl.d/99-nettap.conf"
# Required by OpenSearch
vm.max_map_count = 262144

# Increase network buffer sizes for high-throughput capture
net.core.rmem_max = 134217728
net.core.wmem_max = 134217728
net.core.rmem_default = 16777216
net.core.netdev_max_backlog = 5000

# Increase conntrack table for busy networks
net.netfilter.nf_conntrack_max = 1048576
```

### Bridge-Specific Tuning

The bridge setup script applies these in `/etc/sysctl.d/99-nettap-bridge.conf`:

```ini title="/etc/sysctl.d/99-nettap-bridge.conf"
# Disable bridge netfilter — avoid iptables overhead on bridged traffic
net.bridge.bridge-nf-call-iptables = 0
net.bridge.bridge-nf-call-ip6tables = 0
net.bridge.bridge-nf-call-arptables = 0

# Disable IPv6 on bridge to stay invisible
net.ipv6.conf.br0.disable_ipv6 = 1
```

To verify current values:

```bash
sysctl vm.max_map_count
sysctl net.core.rmem_max
sysctl net.bridge.bridge-nf-call-iptables
```

---

## NIC Offload Settings

The bridge setup script disables hardware offloads that interfere with accurate packet capture:

```bash
# Applied automatically during bridge setup
ethtool -K eth0 tso off gso off gro off lro off
ethtool -K eth1 tso off gso off gro off lro off

# Increase RX ring buffer for better capture under burst
ethtool -G eth0 rx 4096
ethtool -G eth1 rx 4096
```

These settings reduce CPU-assisted packet assembly, ensuring Zeek and Suricata see packets as they appear on the wire.

### Verifying Offload Settings

```bash
ethtool -k eth0 | grep -E "tcp-segmentation|generic-segmentation|generic-receive|large-receive"
ethtool -g eth0
```

---

## Zeek Threads

Zeek's thread count affects how many packets it can process simultaneously. For the default configuration:

```yaml title="docker-compose.yml (zeek-live environment)"
ZEEK_LIVE_CAPTURE: "true"
PCAP_IFACE: "br0"
```

On a 4-core system, Zeek typically uses 1--2 cores for capture and analysis. For higher-throughput networks, you can enable Zeek's cluster mode with worker processes.

---

## Suricata Threads

Suricata's runmode and thread settings control parallelism:

```yaml title="docker-compose.yml (suricata-live environment)"
SURICATA_RUNMODE: "workers"   # Each thread handles capture + detection
```

The `workers` runmode is the most efficient for multi-core systems. Each worker handles its own traffic via kernel-level flow balancing (AF_PACKET cluster).

---

## Arkime Packet Threads

Arkime's packet processing threads:

```ini title=".env"
ARKIME_PACKET_THREADS=2    # Default: 2 threads
```

| CPU Cores | Recommended Threads |
|---|---|
| 2 | 1 |
| 4 | 2 |
| 8+ | 4 |

---

## SSD Write Endurance

NetTap includes several measures to protect SSD lifespan:

### Write Coalescing

- **Zeek log rotation:** Logs are flushed every 30 seconds (not per-event). Configured in `config/zeek/nettap.zeek`:
  ```
  redef Log::default_rotation_interval = 30sec;
  ```

- **Docker log rotation:** Container logs are capped at 10 MB with 3 rotations:
  ```json title="/etc/docker/daemon.json"
  {
    "log-driver": "json-file",
    "log-opts": {
      "max-size": "10m",
      "max-file": "3"
    }
  }
  ```

### SMART Monitoring

The daemon checks SMART health every hour (configurable):

```ini title=".env"
SMART_CHECK_INTERVAL=3600       # Seconds between SMART checks
SMART_DEVICE=/dev/nvme0n1       # Device to monitor
```

View current SMART status:

```bash
curl http://localhost:8880/api/smart/health
```

Or from the command line:

```bash
sudo smartctl -a /dev/nvme0n1
```

---

## PCAP Capture Settings

Control how raw packet capture operates:

```ini title=".env"
PCAP_ROTATE_MB=4096     # Rotate PCAP files at this size (MB)
PCAP_ROTATE_MIN=10      # Rotate PCAP files at this interval (minutes)
```

Larger rotation sizes reduce file overhead but increase recovery time if a write is interrupted.

---

## Hardware Watchdog

NetTap configures a hardware watchdog timer as a last-resort failsafe. If the system hangs, the watchdog triggers a hard reboot to restore network traffic flow.

Configuration is in `config/watchdog/watchdog.conf`:

| Setting | Default | Description |
|---|---|---|
| `interval` | 10s | How often the daemon "pets" the watchdog |
| `watchdog-timeout` | 60s | Time without a pet before hardware reboot |
| `max-load-1` | 24 | Reboot if 1-minute load average exceeds this |
| `ping` | 127.0.0.1 | Test kernel network stack is alive |

The watchdog runs with realtime scheduling priority to ensure it functions even under extreme system load.

---

## Resource Monitoring

Check system resource usage:

```bash
# Overall system status
htop

# Docker container resource usage
docker stats --no-stream

# OpenSearch cluster health
curl -sk https://localhost:9200/_cluster/health | python3 -m json.tool

# OpenSearch node stats
curl -sk https://localhost:9200/_nodes/stats/jvm | python3 -m json.tool
```
