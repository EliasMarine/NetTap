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
from datetime import datetime

from services.dns_analytics import DNS_LOOKUP_EXCLUSION
from storage.all_buckets import all_buckets

# OLD CODE START — excluded IPs stay visible in threat detections
# from services.excluded_ips import build_excluded_ips_filter
# OLD CODE END

logger = logging.getLogger("nettap.services.threat_detection")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BEACONING_JITTER_THRESHOLD = 0.15  # 15% coefficient of variation
BEACONING_MIN_CONNECTIONS = 10
COMMON_BEACON_INTERVALS = [30, 60, 120, 300, 600, 900, 1800, 3600]
# Regularity is read from a 10 s histogram per pair. OpenSearch refuses a response with more
# than search.max_buckets (65,535) buckets, so pairs are sent in batches that stay under this.
BEACON_SLOT_SECONDS = 10
HISTOGRAM_BUCKETS_PER_REQUEST = 50_000
PAIRS_PER_REQUEST = 500

# Every (source, destination, port) pair, paged to the end (#96)
_PAIR_SOURCES = [
    {"src": {"terms": {"field": "source.ip"}}},
    {"dst": {"terms": {"field": "destination.ip"}}},
    {"port": {"terms": {"field": "destination.port"}}},
]

LATERAL_MOVEMENT_PORTS = {
    22: "SSH",
    23: "Telnet",
    445: "SMB",
    3389: "RDP",
    5985: "WinRM",
    5986: "WinRM-HTTPS",
    135: "RPC",
    139: "NetBIOS",
    1433: "MSSQL",
    3306: "MySQL",
    5432: "PostgreSQL",
    6379: "Redis",
    27017: "MongoDB",
}

DGA_ENTROPY_THRESHOLD = 3.8
DNS_TUNNEL_LENGTH_THRESHOLD = 50
SUSPICIOUS_TLDS = {".tk", ".ml", ".ga", ".cf", ".gq", ".xyz", ".top", ".buzz", ".rest"}

INTERNAL_PREFIXES = (
    "10.",
    "192.168.",
    "172.16.",
    "172.17.",
    "172.18.",
    "172.19.",
    "172.20.",
    "172.21.",
    "172.22.",
    "172.23.",
    "172.24.",
    "172.25.",
    "172.26.",
    "172.27.",
    "172.28.",
    "172.29.",
    "172.30.",
    "172.31.",
)


# INTERNAL_PREFIXES as ranges, for OpenSearch ip-field queries
INTERNAL_CIDRS = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]


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


def _max_slots(from_ts: str, to_ts: str) -> int | None:
    """10 s slots the range can touch, or None if the bounds aren't ISO times (e.g. "now-1h")."""
    try:
        start = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
        end = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
        return max(0, int((end - start).total_seconds() // BEACON_SLOT_SECONDS)) + 2
    except (ValueError, TypeError, AttributeError):
        return None


def _histogram_cost(doc_count: int, slots: int | None) -> int:
    """Most buckets one pair adds to a request: its own bucket plus one per non-empty slot."""
    return 1 + (doc_count if slots is None else min(doc_count, slots))


def _histogram_batches(pairs: list[dict], slots: int | None) -> tuple[list[list[dict]], list[dict]]:
    """(batches that each stay under the bucket budget, pairs too busy to share a request)."""
    costs = [(p, _histogram_cost(p["doc_count"], slots)) for p in pairs]
    too_big = [p for p, cost in costs if cost > HISTOGRAM_BUCKETS_PER_REQUEST]
    batches: list[list[dict]] = []
    batch: list[dict] = []
    used = 0
    for pair, cost in costs:
        if cost > HISTOGRAM_BUCKETS_PER_REQUEST:
            continue
        if batch and (used + cost > HISTOGRAM_BUCKETS_PER_REQUEST or len(batch) == PAIRS_PER_REQUEST):
            batches.append(batch)
            batch, used = [], 0
        batch.append(pair)
        used += cost
    return ([*batches, batch] if batch else batches), too_big


def _pair_name(key: dict) -> str:
    return f"{key['src']} {key['dst']} {key['port']}"


def _pair_filter(key: dict) -> list[dict]:
    return [
        {"term": {"source.ip": key["src"]}},
        {"term": {"destination.ip": key["dst"]}},
        {"term": {"destination.port": key["port"]}},
    ]


def _batch_slots(client, filters: list[dict], batch: list[dict]) -> dict[str, list[dict]]:
    """Non-empty 10 s slots of every pair in `batch`, in one request."""
    narrowed = [
        *filters,
        {"terms": {"source.ip": sorted({p["key"]["src"] for p in batch})}},
        {"terms": {"destination.ip": sorted({p["key"]["dst"] for p in batch})}},
    ]
    histogram = {"field": "@timestamp", "fixed_interval": f"{BEACON_SLOT_SECONDS}s", "min_doc_count": 1}
    body = {
        "size": 0,
        "query": {"bool": {"filter": narrowed}},
        "aggs": {
            "pairs": {
                "filters": {
                    "filters": {_pair_name(p["key"]): {"bool": {"filter": _pair_filter(p["key"])}} for p in batch}
                },
                "aggs": {"timestamps": {"date_histogram": histogram}},
            }
        },
    }
    reply = client.search(index=NETWORK_INDEX, body=body)
    buckets = ((reply.get("aggregations") or {}).get("pairs") or {}).get("buckets") or {}
    return {name: b.get("timestamps", {}).get("buckets", []) for name, b in buckets.items()}


def _paged_slots(client, filters: list[dict], key: dict) -> tuple[list[dict], bool]:
    """Non-empty 10 s slots of one pair too busy to share a request, paged (False if capped)."""
    slots, complete = all_buckets(
        client,
        NETWORK_INDEX,
        {"bool": {"filter": [*filters, *_pair_filter(key)]}},
        [{"t": {"date_histogram": {"field": "@timestamp", "fixed_interval": f"{BEACON_SLOT_SECONDS}s"}}}],
    )
    return [{"key": s["key"]["t"]} for s in slots], complete


def _assess_beacon(key: dict, conn_count: int, ts_buckets: list[dict]) -> dict | None:
    """The beacon finding for one pair, or None if its connections aren't periodic."""
    if conn_count < BEACONING_MIN_CONNECTIONS or len(ts_buckets) < BEACONING_MIN_CONNECTIONS:
        return None

    epochs = [b["key"] for b in ts_buckets]
    deltas = [epochs[i + 1] - epochs[i] for i in range(len(epochs) - 1)]
    mean_delta = statistics.mean(deltas)
    if mean_delta <= 5000:  # < 5s intervals = not beaconing, just chatty
        return None

    std_delta = statistics.stdev(deltas) if len(deltas) > 1 else 0
    cv = std_delta / mean_delta if mean_delta > 0 else 1.0
    if cv >= BEACONING_JITTER_THRESHOLD:
        return None

    interval_sec = mean_delta / 1000
    confidence = _beacon_confidence(cv, conn_count, interval_sec)
    return {
        "source_ip": key["src"],
        "destination_ip": key["dst"],
        "destination_port": key["port"],
        "connection_count": conn_count,
        "interval_seconds": round(interval_sec, 1),
        "jitter_coefficient": round(cv, 4),
        "confidence": round(confidence, 1),
        "assessment": (
            f"Periodic callbacks every ~{round(interval_sec)}s with "
            f"{round(cv * 100, 1)}% jitter over {conn_count} connections. "
            f"Consistent with C2 beaconing."
        ),
    }


def _scan_beacons(client, filters: list[dict], slots: int | None) -> tuple[list[dict], bool]:
    """(beacons among every pair, False if a bucket cap left some pairs unchecked)."""
    pairs, complete = all_buckets(client, NETWORK_INDEX, {"bool": {"filter": filters}}, _PAIR_SOURCES)
    # timing is only read for pairs with enough connections to be a beacon
    candidates = [p for p in pairs if p["doc_count"] >= BEACONING_MIN_CONNECTIONS]
    batches, too_big = _histogram_batches(candidates, slots)
    timings = {name: ts for batch in batches for name, ts in _batch_slots(client, filters, batch).items()}
    paged = {_pair_name(p["key"]): _paged_slots(client, filters, p["key"]) for p in too_big}
    timings = {**timings, **{name: ts for name, (ts, _) in paged.items()}}
    complete = complete and all(done for _, done in paged.values())
    found = (_assess_beacon(p["key"], p["doc_count"], timings.get(_pair_name(p["key"]), [])) for p in candidates)
    return [b for b in found if b is not None], complete


def detect_beaconing(
    client, from_ts: str, to_ts: str, excluded_ips: list[str] | None = None
) -> list[dict]:
    """Detect periodic callback patterns indicative of C2 beaconing.

    ``excluded_ips`` is ignored (kept for callers): excluded IPs stay visible here.
    """
    # OLD CODE START — excluded IPs stay visible in threat detections
    # excluded = build_excluded_ips_filter(excluded_ips or [])
    # OLD CODE END
    bool_clause: dict = {
        "filter": [
            {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
            {"term": {"event.provider": "zeek"}},
            {"term": {"event.dataset": "conn"}},
        ]
    }
    # OLD CODE START — excluded IPs stay visible in threat detections
    # if excluded:
    #     bool_clause["must_not"] = excluded
    # OLD CODE END

    # OLD CODE START — #96: one 300-pair page in key order, so a pair sorting after the first
    # 300 (192.168.1.50 on a busy hour) was never checked; 300 10 s histograms could also pass
    # search.max_buckets, and that error was caught and reported as "no beacons"
    # query = {
    #     "size": 0,
    #     "query": {"bool": bool_clause},
    #     "aggs": {
    #         "by_pair": {
    #             "composite": {
    #                 "size": 300,
    #                 "sources": [
    #                     {"src": {"terms": {"field": "source.ip"}}},
    #                     {"dst": {"terms": {"field": "destination.ip"}}},
    #                     {"port": {"terms": {"field": "destination.port"}}},
    #                 ],
    #             },
    #             "aggs": {
    #                 "timestamps": {
    #                     "date_histogram": {
    #                         "field": "@timestamp",
    #                         "fixed_interval": "10s",
    #                         "min_doc_count": 1,
    #                     }
    #                 },
    #                 "conn_count": {"value_count": {"field": "@timestamp"}},
    #             },
    #         }
    #     },
    # }
    #
    # try:
    #     result = client.search(index=NETWORK_INDEX, body=query)
    # except Exception:
    #     logger.error("Beaconing detection query failed", exc_info=True)
    #     return []
    #
    # beacons = []
    # for bucket in result.get("aggregations", {}).get("by_pair", {}).get("buckets", []):
    #     conn_count = bucket.get("conn_count", {}).get("value", 0)
    #     ... (the per-pair checks, unchanged, are now _assess_beacon)
    # OLD CODE END
    try:
        beacons, complete = _scan_beacons(client, bool_clause["filter"], _max_slots(from_ts, to_ts))
    except Exception:
        logger.error("Beaconing detection query failed", exc_info=True)
        return []
    if not complete:
        logger.warning("Beaconing: the scan hit its bucket cap; pairs past it were not checked")

    beacons.sort(key=lambda b: b["confidence"], reverse=True)
    return beacons


# ---------------------------------------------------------------------------
# Lateral Movement Detection
# ---------------------------------------------------------------------------


def detect_lateral_movement(
    client, from_ts: str, to_ts: str, excluded_ips: list[str] | None = None
) -> list[dict]:
    """Find internal hosts connecting to other internal hosts on admin ports.

    ``excluded_ips`` is ignored (kept for callers): excluded IPs stay visible here.
    """
    port_filters = [{"term": {"destination.port": p}} for p in LATERAL_MOVEMENT_PORTS]
    # OLD CODE START — excluded IPs stay visible in threat detections
    # excluded = build_excluded_ips_filter(excluded_ips or [])
    # OLD CODE END

    bool_clause: dict = {
        "filter": [
            {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
            {"term": {"event.provider": "zeek"}},
            {"term": {"event.dataset": "conn"}},
            {"bool": {"should": port_filters, "minimum_should_match": 1}},
            # only internal-to-internal pairs can be lateral movement; inbound scans aren't paged
            {"terms": {"source.ip": INTERNAL_CIDRS}},
            {"terms": {"destination.ip": INTERNAL_CIDRS}},
        ]
    }
    # OLD CODE START — excluded IPs stay visible in threat detections
    # if excluded:
    #     bool_clause["must_not"] = excluded
    # OLD CODE END

    # OLD CODE START — #96: one 300-pair page in key order; inbound scans from public IPs on
    # 22/445/3389 sort before 192.168.x and filled it, so internal pairs and fan-out went unseen
    # query = {
    #     "size": 0,
    #     "query": {"bool": bool_clause},
    #     "aggs": {
    #         "by_pair": {
    #             "composite": {
    #                 "size": 300,
    #                 "sources": [
    #                     {"src": {"terms": {"field": "source.ip"}}},
    #                     {"dst": {"terms": {"field": "destination.ip"}}},
    #                     {"port": {"terms": {"field": "destination.port"}}},
    #                 ],
    #             },
    #             "aggs": {
    #                 "first_seen": {"min": {"field": "@timestamp"}},
    #                 "last_seen": {"max": {"field": "@timestamp"}},
    #             },
    #         }
    #     },
    # }
    #
    # try:
    #     result = client.search(index=NETWORK_INDEX, body=query)
    # except Exception:
    #     logger.error("Lateral movement detection query failed", exc_info=True)
    #     return []
    #
    # suspicious = []
    # for bucket in result.get("aggregations", {}).get("by_pair", {}).get("buckets", []):
    # OLD CODE END
    try:
        pairs, complete = all_buckets(
            client,
            NETWORK_INDEX,
            {"bool": bool_clause},
            _PAIR_SOURCES,
            aggs={
                "first_seen": {"min": {"field": "@timestamp"}},
                "last_seen": {"max": {"field": "@timestamp"}},
            },
        )
    except Exception:
        logger.error("Lateral movement detection query failed", exc_info=True)
        return []
    if not complete:
        logger.warning("Lateral movement: the scan hit its bucket cap; pairs past it were not checked")

    suspicious = []
    for bucket in pairs:
        src = bucket["key"]["src"]
        dst = bucket["key"]["dst"]
        port = bucket["key"]["port"]

        if not (_is_internal(src) and _is_internal(dst)):
            continue
        if src == dst:
            continue

        service = LATERAL_MOVEMENT_PORTS.get(port, f"port {port}")
        count = bucket["doc_count"]

        suspicious.append(
            {
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
            }
        )

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


def analyze_dns_anomalies(
    client, from_ts: str, to_ts: str, excluded_ips: list[str] | None = None
) -> dict:
    """Detect DNS-based threats: DGA, tunneling, NXDOMAIN spikes.

    ``excluded_ips`` is ignored (kept for callers): excluded IPs stay visible here.
    """
    # OLD CODE START — excluded IPs stay visible in threat detections
    # excluded = build_excluded_ips_filter(excluded_ips or [])
    # OLD CODE END
    bool_clause: dict = {
        "filter": [
            {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
            {"term": {"event.provider": "zeek"}},
            {"term": {"event.dataset": "dns"}},
        ],
        # pcap-monitor would read as an NXDOMAIN spike; long mDNS service names would read as tunneling
        "must_not": DNS_LOOKUP_EXCLUSION,
    }
    # OLD CODE START — excluded IPs stay visible in threat detections
    # if excluded:
    #     bool_clause["must_not"] = excluded
    # OLD CODE END

    query = {
        "size": 0,
        "query": {"bool": bool_clause},
        "aggs": {
            "domains": {
                "terms": {"field": "zeek.dns.query", "size": 500},
            },
            "by_source": {
                "terms": {"field": "source.ip", "size": 100},
                "aggs": {
                    "unique_domains": {"cardinality": {"field": "zeek.dns.query"}},
                    "nxdomain_count": {
                        "filter": {"term": {"zeek.dns.rcode_name": "NXDOMAIN"}}
                    },
                },
            },
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except Exception:
        logger.error("DNS anomaly analysis failed", exc_info=True)
        return {
            "dga_suspects": [],
            "tunnel_suspects": [],
            "nxdomain_spikes": [],
            "suspicious_tlds": [],
        }

    findings: dict[str, list] = {
        "dga_suspects": [],
        "tunnel_suspects": [],
        "nxdomain_spikes": [],
        "suspicious_tlds": [],
    }

    for bucket in result.get("aggregations", {}).get("domains", {}).get("buckets", []):
        domain = bucket["key"]
        count = bucket["doc_count"]
        parts = domain.split(".")

        # Skip mDNS/local
        if domain.endswith(".local") or domain.endswith(".arpa"):
            continue

        # DGA detection
        # OLD CODE START — parts[0] is the leftmost hostname label (CDN/session IDs like
        # "7b18d6de...-7a0ef8ad28aa.cdn.forter.com"), not the registered name a DGA randomises,
        # and single-label LAN hostnames ("sarabouzeid-fgwk3p497k") were scored too (#35).
        # registrable = parts[0] if len(parts) >= 2 else domain
        # OLD CODE END
        if len(parts) < 2:
            continue  # single-label names are local hostnames, not registered domains
        # shortcut: no public-suffix list; a 2nd-level label of <=3 chars (co.uk, com.au) is
        # taken as part of the suffix. Use a PSL library if this misfires.
        registrable = parts[-3] if len(parts) >= 3 and len(parts[-2]) <= 3 else parts[-2]
        # DGA labels are one random run; score the longest hyphen-separated word so compound
        # names like "browser-intake-datadoghq" aren't read as random
        registrable = max(registrable.split("-"), key=len)
        entropy = _shannon_entropy(registrable)
        if entropy > DGA_ENTROPY_THRESHOLD and len(registrable) > 8:
            findings["dga_suspects"].append(
                {
                    "domain": domain,
                    "entropy": round(entropy, 3),
                    "query_count": count,
                    "assessment": f"Domain has entropy {entropy:.2f} — consistent with algorithmic generation.",
                }
            )

        # DNS tunneling
        subdomain = ".".join(parts[:-2]) if len(parts) > 2 else ""
        if len(subdomain) > DNS_TUNNEL_LENGTH_THRESHOLD:
            findings["tunnel_suspects"].append(
                {
                    "domain": domain,
                    "subdomain_length": len(subdomain),
                    "query_count": count,
                    "assessment": f"Subdomain length ({len(subdomain)} chars) suggests DNS tunneling.",
                }
            )

        # Suspicious TLD
        tld = "." + parts[-1] if parts else ""
        if tld in SUSPICIOUS_TLDS and count > 10:
            findings["suspicious_tlds"].append(
                {
                    "domain": domain,
                    "tld": tld,
                    "query_count": count,
                }
            )

    # NXDOMAIN spikes per source
    for bucket in (
        result.get("aggregations", {}).get("by_source", {}).get("buckets", [])
    ):
        src_ip = bucket["key"]
        total = bucket["doc_count"]
        nxdomain = bucket.get("nxdomain_count", {}).get("doc_count", 0)

        if total > 50 and nxdomain / total > 0.4:
            findings["nxdomain_spikes"].append(
                {
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
                }
            )

    findings["dga_suspects"].sort(key=lambda d: d["entropy"], reverse=True)
    return findings
