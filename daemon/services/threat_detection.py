"""
NetTap Behavioral Threat Detection Engine

Detects threats through behavioral analysis of raw connection and DNS data:
1. C2 Beaconing — periodic callback patterns
2. Lateral Movement — internal-to-internal on admin ports
3. DNS Anomalies — DGA, tunneling, NXDOMAIN spikes
"""

import logging
import math
import os
import statistics
from collections import Counter, defaultdict

logger = logging.getLogger("nettap.services.threat_detection")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BEACONING_JITTER_THRESHOLD = 0.15  # 15% coefficient of variation
BEACONING_MIN_CONNECTIONS = 10
COMMON_BEACON_INTERVALS = [30, 60, 120, 300, 600, 900, 1800, 3600]

LATERAL_MOVEMENT_PORTS = {
    22: "SSH", 23: "Telnet", 445: "SMB", 3389: "RDP",
    5985: "WinRM", 5986: "WinRM-HTTPS", 135: "RPC",
    139: "NetBIOS", 1433: "MSSQL", 3306: "MySQL",
    5432: "PostgreSQL", 6379: "Redis", 27017: "MongoDB",
}

DGA_ENTROPY_THRESHOLD = 3.8
DNS_TUNNEL_LENGTH_THRESHOLD = 50
SUSPICIOUS_TLDS = {".tk", ".ml", ".ga", ".cf", ".gq", ".xyz", ".top", ".buzz", ".rest"}

INTERNAL_PREFIXES = ("10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.",
                     "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
                     "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.")


def _is_internal(ip: str) -> bool:
    return ip.startswith(INTERNAL_PREFIXES)


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq = Counter(s)
    length = len(s)
    return -sum((c / length) * math.log2(c / length) for c in freq.values())


def _beacon_confidence(cv: float, count: int, interval: float) -> float:
    score = 0.0
    if cv < 0.05:
        score += 50
    elif cv < 0.10:
        score += 35
    elif cv < 0.15:
        score += 20

    if count > 100:
        score += 30
    elif count > 50:
        score += 20
    elif count > 20:
        score += 10

    for ci in COMMON_BEACON_INTERVALS:
        if abs(interval - ci) < ci * 0.1:
            score += 20
            break

    return min(100.0, score)


# ---------------------------------------------------------------------------
# Beaconing Detection
# ---------------------------------------------------------------------------


def detect_beaconing(client, from_ts: str, to_ts: str) -> list[dict]:
    """Detect periodic callback patterns indicative of C2 beaconing."""
    query = {
        "size": 0,
        "query": {"bool": {"filter": [
            {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
            {"term": {"event.provider": "zeek"}},
            {"term": {"event.dataset": "conn"}},
        ]}},
        "aggs": {
            "by_pair": {
                "composite": {
                    "size": 300,
                    "sources": [
                        {"src": {"terms": {"field": "source.ip.keyword"}}},
                        {"dst": {"terms": {"field": "destination.ip.keyword"}}},
                        {"port": {"terms": {"field": "destination.port"}}},
                    ],
                },
                "aggs": {
                    "timestamps": {
                        "date_histogram": {
                            "field": "@timestamp",
                            "fixed_interval": "10s",
                            "min_doc_count": 1,
                        }
                    },
                    "conn_count": {"value_count": {"field": "@timestamp"}},
                },
            }
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except Exception:
        logger.error("Beaconing detection query failed", exc_info=True)
        return []

    beacons = []
    for bucket in result.get("aggregations", {}).get("by_pair", {}).get("buckets", []):
        conn_count = bucket.get("conn_count", {}).get("value", 0)
        if conn_count < BEACONING_MIN_CONNECTIONS:
            continue

        ts_buckets = bucket.get("timestamps", {}).get("buckets", [])
        if len(ts_buckets) < BEACONING_MIN_CONNECTIONS:
            continue

        epochs = [b["key"] for b in ts_buckets]
        deltas = [epochs[i + 1] - epochs[i] for i in range(len(epochs) - 1)]
        if not deltas:
            continue

        mean_delta = statistics.mean(deltas)
        if mean_delta <= 5000:  # < 5s intervals = not beaconing, just chatty
            continue

        std_delta = statistics.stdev(deltas) if len(deltas) > 1 else 0
        cv = std_delta / mean_delta if mean_delta > 0 else 1.0

        if cv < BEACONING_JITTER_THRESHOLD:
            interval_sec = mean_delta / 1000
            confidence = _beacon_confidence(cv, conn_count, interval_sec)
            beacons.append({
                "source_ip": bucket["key"]["src"],
                "destination_ip": bucket["key"]["dst"],
                "destination_port": bucket["key"]["port"],
                "connection_count": conn_count,
                "interval_seconds": round(interval_sec, 1),
                "jitter_coefficient": round(cv, 4),
                "confidence": round(confidence, 1),
                "assessment": (
                    f"Periodic callbacks every ~{round(interval_sec)}s with "
                    f"{round(cv * 100, 1)}% jitter over {conn_count} connections. "
                    f"Consistent with C2 beaconing."
                ),
            })

    beacons.sort(key=lambda b: b["confidence"], reverse=True)
    return beacons


# ---------------------------------------------------------------------------
# Lateral Movement Detection
# ---------------------------------------------------------------------------


def detect_lateral_movement(client, from_ts: str, to_ts: str) -> list[dict]:
    """Find internal hosts connecting to other internal hosts on admin ports."""
    port_filters = [{"term": {"destination.port": p}} for p in LATERAL_MOVEMENT_PORTS]

    query = {
        "size": 0,
        "query": {"bool": {"filter": [
            {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
            {"term": {"event.provider": "zeek"}},
            {"term": {"event.dataset": "conn"}},
            {"bool": {"should": port_filters, "minimum_should_match": 1}},
        ]}},
        "aggs": {
            "by_pair": {
                "composite": {
                    "size": 300,
                    "sources": [
                        {"src": {"terms": {"field": "source.ip.keyword"}}},
                        {"dst": {"terms": {"field": "destination.ip.keyword"}}},
                        {"port": {"terms": {"field": "destination.port"}}},
                    ],
                },
                "aggs": {
                    "first_seen": {"min": {"field": "@timestamp"}},
                    "last_seen": {"max": {"field": "@timestamp"}},
                },
            }
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except Exception:
        logger.error("Lateral movement detection query failed", exc_info=True)
        return []

    suspicious = []
    for bucket in result.get("aggregations", {}).get("by_pair", {}).get("buckets", []):
        src = bucket["key"]["src"]
        dst = bucket["key"]["dst"]
        port = bucket["key"]["port"]

        if not (_is_internal(src) and _is_internal(dst)):
            continue
        if src == dst:
            continue

        service = LATERAL_MOVEMENT_PORTS.get(port, f"port {port}")
        count = bucket["doc_count"]

        suspicious.append({
            "source_ip": src,
            "destination_ip": dst,
            "port": port,
            "service": service,
            "connection_count": count,
            "first_seen": bucket.get("first_seen", {}).get("value_as_string"),
            "last_seen": bucket.get("last_seen", {}).get("value_as_string"),
            "assessment": (
                f"Internal host {src} connected to {dst} via {service} "
                f"({count} times). Verify this is authorized administrative access."
            ),
        })

    # Flag fan-out (one source hitting multiple internal targets)
    src_targets: dict[str, set] = defaultdict(set)
    for s in suspicious:
        src_targets[s["source_ip"]].add(s["destination_ip"])

    for entry in suspicious:
        targets = src_targets[entry["source_ip"]]
        if len(targets) > 2:
            entry["fan_out"] = len(targets)
            entry["assessment"] += (
                f" WARNING: This source is connecting to {len(targets)} "
                f"internal hosts — possible lateral movement."
            )

    suspicious.sort(key=lambda s: s.get("fan_out", 0), reverse=True)
    return suspicious


# ---------------------------------------------------------------------------
# DNS Anomaly Detection
# ---------------------------------------------------------------------------


def analyze_dns_anomalies(client, from_ts: str, to_ts: str) -> dict:
    """Detect DNS-based threats: DGA, tunneling, NXDOMAIN spikes."""
    query = {
        "size": 0,
        "query": {"bool": {"filter": [
            {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
            {"term": {"event.provider": "zeek"}},
            {"term": {"event.dataset": "dns"}},
        ]}},
        "aggs": {
            "domains": {
                "terms": {"field": "zeek.dns.query.keyword", "size": 500},
            },
            "by_source": {
                "terms": {"field": "source.ip.keyword", "size": 100},
                "aggs": {
                    "unique_domains": {"cardinality": {"field": "zeek.dns.query.keyword"}},
                    "nxdomain_count": {
                        "filter": {"term": {"zeek.dns.rcode_name.keyword": "NXDOMAIN"}}
                    },
                },
            },
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except Exception:
        logger.error("DNS anomaly analysis failed", exc_info=True)
        return {"dga_suspects": [], "tunnel_suspects": [], "nxdomain_spikes": [], "suspicious_tlds": []}

    findings: dict[str, list] = {
        "dga_suspects": [], "tunnel_suspects": [],
        "nxdomain_spikes": [], "suspicious_tlds": [],
    }

    for bucket in result.get("aggregations", {}).get("domains", {}).get("buckets", []):
        domain = bucket["key"]
        count = bucket["doc_count"]
        parts = domain.split(".")

        # Skip mDNS/local
        if domain.endswith(".local") or domain.endswith(".arpa"):
            continue

        # DGA detection
        registrable = parts[0] if len(parts) >= 2 else domain
        entropy = _shannon_entropy(registrable)
        if entropy > DGA_ENTROPY_THRESHOLD and len(registrable) > 8:
            findings["dga_suspects"].append({
                "domain": domain,
                "entropy": round(entropy, 3),
                "query_count": count,
                "assessment": f"Domain has entropy {entropy:.2f} — consistent with algorithmic generation.",
            })

        # DNS tunneling
        subdomain = ".".join(parts[:-2]) if len(parts) > 2 else ""
        if len(subdomain) > DNS_TUNNEL_LENGTH_THRESHOLD:
            findings["tunnel_suspects"].append({
                "domain": domain,
                "subdomain_length": len(subdomain),
                "query_count": count,
                "assessment": f"Subdomain length ({len(subdomain)} chars) suggests DNS tunneling.",
            })

        # Suspicious TLD
        tld = "." + parts[-1] if parts else ""
        if tld in SUSPICIOUS_TLDS and count > 10:
            findings["suspicious_tlds"].append({
                "domain": domain, "tld": tld, "query_count": count,
            })

    # NXDOMAIN spikes per source
    for bucket in result.get("aggregations", {}).get("by_source", {}).get("buckets", []):
        src_ip = bucket["key"]
        total = bucket["doc_count"]
        nxdomain = bucket.get("nxdomain_count", {}).get("doc_count", 0)

        if total > 50 and nxdomain / total > 0.4:
            findings["nxdomain_spikes"].append({
                "source_ip": src_ip,
                "total_queries": total,
                "unique_domains": bucket.get("unique_domains", {}).get("value", 0),
                "nxdomain_count": nxdomain,
                "nxdomain_ratio": round(nxdomain / total, 3),
                "assessment": (
                    f"{src_ip} generated {nxdomain} NXDOMAIN responses out of "
                    f"{total} queries ({round(nxdomain / total * 100)}%) — "
                    f"consistent with DGA domain bruteforcing."
                ),
            })

    findings["dga_suspects"].sort(key=lambda d: d["entropy"], reverse=True)
    return findings
