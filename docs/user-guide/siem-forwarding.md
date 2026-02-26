# SIEM Forwarding

NetTap can forward logs to an external SIEM (Security Information and Event Management) system for centralized security monitoring. This is useful if you already run a SIEM like Splunk, Elastic SIEM, Wazuh, or QRadar and want to include NetTap's network telemetry.

---

## Architecture

NetTap's log pipeline already includes Logstash as part of the Malcolm stack. Logstash can be configured to send copies of all logs to external destinations in addition to the local OpenSearch cluster.

```
Zeek / Suricata ──> Filebeat ──> Logstash ──┬──> OpenSearch (local)
                                             └──> External SIEM
```

---

## Forwarding Options

### Syslog Output

Forward logs via syslog (TCP or UDP) to any syslog-compatible receiver:

Add a Logstash output configuration:

```ruby title="config/logstash/siem-output.conf"
output {
  syslog {
    host => "siem.example.com"
    port => 514
    protocol => "tcp"
    facility => "local0"
    severity => "informational"
    sourcehost => "nettap"
    msgid => "%{[event][module]}"
  }
}
```

### Elasticsearch/OpenSearch Output

Forward to a remote Elasticsearch or OpenSearch cluster:

```ruby title="config/logstash/siem-output.conf"
output {
  elasticsearch {
    hosts => ["https://siem.example.com:9200"]
    index => "nettap-%{[event][module]}-%{+YYYY.MM.dd}"
    user => "logstash_writer"
    password => "your-password"
    ssl => true
    cacert => "/path/to/ca.crt"
  }
}
```

### HTTP Output

Forward to any HTTP endpoint (useful for cloud SIEMs):

```ruby title="config/logstash/siem-output.conf"
output {
  http {
    url => "https://siem.example.com/api/v1/logs"
    http_method => "post"
    format => "json"
    headers => {
      "Authorization" => "Bearer your-api-token"
      "Content-Type" => "application/json"
    }
  }
}
```

### Kafka Output

For high-volume environments, forward via Kafka:

```ruby title="config/logstash/siem-output.conf"
output {
  kafka {
    bootstrap_servers => "kafka.example.com:9092"
    topic_id => "nettap-logs"
    codec => json
  }
}
```

---

## Configuration Steps

### 1. Create the Output Configuration

Create a Logstash pipeline configuration file for your SIEM:

```bash
mkdir -p /opt/nettap/config/logstash
nano /opt/nettap/config/logstash/siem-output.conf
```

### 2. Mount the Configuration

Add the configuration file as a volume mount in `docker/docker-compose.yml` for the Logstash service:

```yaml
logstash:
  volumes:
    # ... existing volumes ...
    - ../config/logstash/siem-output.conf:/usr/share/logstash/pipeline/siem-output.conf:ro
```

### 3. Restart Logstash

```bash
docker compose -f /opt/nettap/docker/docker-compose.yml restart logstash
```

### 4. Verify

Check Logstash logs to confirm the output plugin loaded successfully:

```bash
docker logs nettap-logstash --tail 50
```

Look for messages indicating the new output pipeline is active.

---

## Data Format

Logs forwarded to your SIEM contain structured JSON with these common fields:

| Field | Description | Example |
|---|---|---|
| `event.module` | Source module | `zeek`, `suricata` |
| `event.dataset` | Log type | `conn`, `dns`, `alert` |
| `source.ip` | Source IP address | `192.168.1.42` |
| `destination.ip` | Destination IP address | `93.184.216.34` |
| `source.port` | Source port | `54321` |
| `destination.port` | Destination port | `443` |
| `network.protocol` | Protocol | `tcp`, `udp` |
| `@timestamp` | Event timestamp | `2026-02-26T10:30:00.000Z` |

Zeek and Suricata logs follow the Elastic Common Schema (ECS) field naming where possible, making integration with ECS-compatible SIEMs straightforward.

---

## Filtering

To forward only specific log types (e.g., only alerts, not all conn logs), add a conditional to the output:

```ruby title="config/logstash/siem-output.conf"
output {
  if [event][module] == "suricata" and [event][dataset] == "alert" {
    syslog {
      host => "siem.example.com"
      port => 514
      protocol => "tcp"
    }
  }
}
```

This forwards only Suricata alerts, significantly reducing the volume sent to your SIEM.

---

## Performance Considerations

- **Bandwidth:** Forwarding all Zeek metadata generates 300--800 MB/day of additional network traffic to your SIEM.
- **Logstash memory:** If the SIEM destination is slow or unreachable, Logstash will buffer events in its persistent queue. Ensure adequate disk space for the `logstash-persistent-queue` Docker volume.
- **Filtering recommended:** For most use cases, forwarding only Suricata alerts and DNS logs provides high security value at a fraction of the data volume.
