# Troubleshooting

Common issues and their solutions.

---

## Dashboard Not Loading

### Symptoms

- Browser shows "connection refused" or timeout
- `https://nettap.local` does not resolve

### Diagnosis

```bash
# Check if the service is running
systemctl status nettap

# Check if containers are running
docker compose -f /opt/nettap/docker/docker-compose.yml ps

# Check the nginx proxy specifically
docker logs nettap-nginx --tail 20

# Check if port 443 is listening
ss -tlnp | grep 443
```

### Solutions

| Cause | Solution |
|---|---|
| Service not started | `sudo systemctl start nettap` |
| Nginx container not running | `docker compose -f docker/docker-compose.yml up -d nettap-nginx` |
| Port conflict on 443 | Check for other services using port 443: `ss -tlnp \| grep 443` |
| mDNS not working | Try the IP address directly: `https://192.168.1.100` |
| Avahi not running | `sudo systemctl restart avahi-daemon` |

---

## OpenSearch Issues

### "OpenSearch not responding"

OpenSearch takes 2--5 minutes to start, especially on first boot when it initializes security indices.

```bash
# Check OpenSearch health
curl -sk https://localhost:9200/_cluster/health | python3 -m json.tool

# Check OpenSearch logs
docker logs nettap-opensearch --tail 50

# Check JVM memory
docker stats nettap-opensearch --no-stream
```

### "Cluster health: yellow"

Yellow cluster health is **normal and expected** for a single-node deployment. It means all primary shards are assigned, but replicas cannot be allocated (because there is only one node). This does not affect functionality.

### OpenSearch Out of Memory (OOM)

If OpenSearch is killed by the OOM killer:

```bash
# Check if OOM occurred
dmesg | grep -i "oom\|killed"
journalctl -k | grep -i "oom\|killed"
```

**Solution:** Reduce the JVM heap size or add more RAM:

```ini title=".env"
# Reduce to 3 GB on a 16 GB system
OPENSEARCH_JAVA_OPTS="-Xms3g -Xmx3g"
```

Then restart: `sudo systemctl restart nettap`

### vm.max_map_count Error

OpenSearch requires `vm.max_map_count >= 262144`. If you see:

```
max virtual memory areas vm.max_map_count [65530] is too low
```

**Solution:**

```bash
sudo sysctl -w vm.max_map_count=262144
echo "vm.max_map_count = 262144" | sudo tee /etc/sysctl.d/99-nettap.conf
```

---

## Bridge Issues

### Traffic Not Passing Through

```bash
# Validate the bridge
sudo scripts/bridge/setup-bridge.sh --validate-only

# Check bridge status
ip link show br0
bridge link show

# Check that interfaces are attached
ip link show eth0 | grep master
ip link show eth1 | grep master
```

### Bridge Validation Failures

| Issue | Cause | Solution |
|---|---|---|
| Bridge not found | Bridge was not created | Re-run: `sudo scripts/bridge/setup-bridge.sh --wan eth0 --lan eth1` |
| Interface not attached | NIC removed from bridge | Re-run bridge setup |
| STP enabled | STP should be off for inline tap | `ip link set br0 type bridge stp_state 0` |
| Forward delay non-zero | Should be 0 for inline tap | `ip link set br0 type bridge forward_delay 0` |
| Promiscuous mode off | Required for packet capture | `ip link set eth0 promisc on; ip link set eth1 promisc on` |

### Bridge Lost After Reboot

If the bridge does not persist across reboots, the netplan configuration may be missing:

```bash
# Check for netplan config
cat /etc/netplan/10-nettap-bridge.yaml

# If missing, re-run with persistence
sudo scripts/bridge/setup-bridge.sh --wan eth0 --lan eth1 --persist
```

### Tearing Down the Bridge

If you need to remove the bridge and restore normal networking:

```bash
sudo scripts/bridge/setup-bridge.sh --teardown
```

This removes the bridge, restores interfaces, and cleans up persistence files.

---

## Container Issues

### Containers Failing to Start

```bash
# Check which containers are unhealthy or restarting
docker compose -f /opt/nettap/docker/docker-compose.yml ps

# Check logs for a specific container
docker logs nettap-opensearch --tail 50
docker logs nettap-zeek-live --tail 50
docker logs nettap-suricata-live --tail 50
```

### Zeek or Suricata Not Capturing

```bash
# Check if br0 exists and is up
ip link show br0

# Check if capture containers can see the interface
docker exec nettap-zeek-live ip link show

# Check Zeek logs
docker logs nettap-zeek-live --tail 30

# Check Suricata stats
docker logs nettap-suricata-live --tail 30
```

!!! tip
    Zeek and Suricata run with `network_mode: host` so they can access the bridge interface directly. If the bridge is not set up, they will fail to start capture.

### Restarting Individual Containers

```bash
# Restart a specific container
docker compose -f /opt/nettap/docker/docker-compose.yml restart zeek-live

# Restart the whole stack
sudo systemctl restart nettap
```

---

## No Data in Dashboard

### Symptoms

- Dashboard shows "--" for all values
- "No traffic data available" messages

### Diagnosis

1. **Check that containers are running:**
   ```bash
   docker compose -f /opt/nettap/docker/docker-compose.yml ps
   ```

2. **Check that OpenSearch has indices:**
   ```bash
   curl -sk https://localhost:9200/_cat/indices?v
   ```

3. **Check that the daemon API is reachable:**
   ```bash
   curl http://localhost:8880/api/health
   ```

4. **Check Zeek log output:**
   ```bash
   docker exec nettap-zeek-live ls -la /zeek/live/
   ```

### Common Causes

| Cause | Solution |
|---|---|
| Bridge not set up | Run bridge setup script |
| No traffic on bridge | Verify cables are connected to WAN and LAN ports |
| OpenSearch still starting | Wait 5 minutes for initial startup |
| Filebeat not shipping logs | Check `docker logs nettap-filebeat` |
| Logstash pipeline error | Check `docker logs nettap-logstash` |
| Daemon not running | Check `docker logs nettap-storage-daemon` |

---

## Daemon API Issues

### "Unable to reach the monitoring daemon"

This warning banner appears on the dashboard when the web UI cannot reach the storage daemon API.

```bash
# Check daemon container
docker logs nettap-storage-daemon --tail 30

# Test API directly
curl http://localhost:8880/api/health
```

### API Returns Errors

```bash
# Check daemon health
curl http://localhost:8880/api/system/health | python3 -m json.tool
```

---

## Performance Issues

### High CPU Usage

```bash
# Check which containers use the most CPU
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"
```

Common CPU hogs:

- **Suricata** under heavy traffic --- normal, scales with traffic volume
- **OpenSearch** during indexing --- normal, especially after startup
- **Logstash** during log enrichment --- reduce `pipeline.workers` if needed

### High Memory Usage

```bash
# Check memory per container
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}"
```

If memory is tight, reduce OpenSearch and Logstash heap sizes. See [Performance Tuning](performance-tuning.md).

### Disk Space Running Low

```bash
# Check disk usage
df -h /

# Check Docker disk usage
docker system df

# Clean up unused Docker resources
docker system prune --volumes
```

!!! warning
    `docker system prune --volumes` removes all unused volumes, including any data not associated with a running container. Make sure all your containers are running before pruning.

---

## Getting Help

If these troubleshooting steps do not resolve your issue:

1. Collect diagnostic information:
   ```bash
   systemctl status nettap
   docker compose -f /opt/nettap/docker/docker-compose.yml ps
   curl http://localhost:8880/api/system/health 2>/dev/null || echo "Daemon unreachable"
   sudo scripts/bridge/setup-bridge.sh --validate-only 2>/dev/null || echo "Bridge issues"
   ```

2. Open a [GitHub Issue](https://github.com/EliasMarine/NetTap/issues) with the diagnostic output.

3. Join the [Discord community](https://discord.gg/nettap) for real-time help.
