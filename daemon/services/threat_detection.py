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

# OLD CODE: from services.excluded_ips import CONN_ACCOUNTING (NET-240: lateral movement reads interim records too)
from services.excluded_ips import CONN_ACCOUNTING, CONN_RECORDS
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

# Protocols that repeat on a timer by design: their regularity says nothing about malware
PERIODIC_BY_DESIGN_PORTS = {
    53: "DNS",
    67: "DHCP",
    68: "DHCP",
    123: "NTP",
    137: "NetBIOS",
    138: "NetBIOS",
    1900: "SSDP",
    5353: "mDNS",
    5355: "LLMNR",
}
# Destinations that aren't internet hosts; a call home goes out to the internet
# (internal pairs are lateral movement's job)
NOT_INTERNET_CIDRS = [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "224.0.0.0/4",
    "255.255.255.255/32",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
    "ff00::/8",
]
# One device on regular schedules with this many internet hosts is not calling one server: on
# the G11 a BitTorrent client gave 283 of 366 "beacons" (DHT peers every ~37 min)
MANY_HOSTS_MIN = 10
# Candidate pairs in one list (under search.max_buckets); more are paged with a composite
CANDIDATE_LIST_SIZE = 50_000
_PAIR_FIELDS = [
    {"field": "source.ip"},
    {"field": "destination.ip"},
    {"field": "destination.port"},
]

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


def _histogram_batches(
    pairs: list[dict], slots: int | None
) -> tuple[list[list[dict]], list[dict]]:
    """(batches that each stay under the bucket budget, pairs too busy to share a request)."""
    costs = [(p, _histogram_cost(p["doc_count"], slots)) for p in pairs]
    too_big = [p for p, cost in costs if cost > HISTOGRAM_BUCKETS_PER_REQUEST]
    batches: list[list[dict]] = []
    batch: list[dict] = []
    used = 0
    for pair, cost in costs:
        if cost > HISTOGRAM_BUCKETS_PER_REQUEST:
            continue
        if batch and (
            used + cost > HISTOGRAM_BUCKETS_PER_REQUEST
            or len(batch) == PAIRS_PER_REQUEST
        ):
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


def _batch_slots(
    client, filters: list[dict], batch: list[dict]
) -> dict[str, list[dict]]:
    """Non-empty 10 s slots of every pair in `batch`, in one request.

    The query keeps only the batch's pairs and a multi_terms splits them in one pass: on the
    G11 the same slots in 6.4 s instead of 45 s for a `filters` aggregation of 500 pairs.
    """
    # a date_histogram under multi_terms (and the composite one in _paged_slots) is exact on
    # OpenSearch 3.5: the skip-list collector that misplaces records (#120) is top-level only;
    # 0 of 10,966 slots differed from date_range slots on the G11
    histogram = {
        "field": "@timestamp",
        "fixed_interval": f"{BEACON_SLOT_SECONDS}s",
        "min_doc_count": 1,
    }
    pair_clauses = [{"bool": {"filter": _pair_filter(p["key"])}} for p in batch]
    body = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    *filters,
                    {"bool": {"should": pair_clauses, "minimum_should_match": 1}},
                ]
            }
        },
        "aggs": {
            "pairs": {
                "multi_terms": {"terms": _PAIR_FIELDS, "size": len(batch)},
                "aggs": {"timestamps": {"date_histogram": histogram}},
            }
        },
    }
    reply = client.search(index=NETWORK_INDEX, body=body)
    buckets = ((reply.get("aggregations") or {}).get("pairs") or {}).get(
        "buckets"
    ) or []
    return {
        _pair_name(
            {"src": b["key"][0], "dst": b["key"][1], "port": int(b["key"][2])}
        ): b.get("timestamps", {}).get("buckets", [])
        for b in buckets
    }


# OLD CODE START — #96: a `filters` aggregation tested every record against 500 pair filters
def _batch_slots_filters_agg(
    client, filters: list[dict], batch: list[dict]
) -> dict[str, list[dict]]:
    """Non-empty 10 s slots of every pair in `batch`, in one request."""
    narrowed = [
        *filters,
        {"terms": {"source.ip": sorted({p["key"]["src"] for p in batch})}},
        {"terms": {"destination.ip": sorted({p["key"]["dst"] for p in batch})}},
    ]
    histogram = {
        "field": "@timestamp",
        "fixed_interval": f"{BEACON_SLOT_SECONDS}s",
        "min_doc_count": 1,
    }
    body = {
        "size": 0,
        "query": {"bool": {"filter": narrowed}},
        "aggs": {
            "pairs": {
                "filters": {
                    "filters": {
                        _pair_name(p["key"]): {
                            "bool": {"filter": _pair_filter(p["key"])}
                        }
                        for p in batch
                    }
                },
                "aggs": {"timestamps": {"date_histogram": histogram}},
            }
        },
    }
    reply = client.search(index=NETWORK_INDEX, body=body)
    buckets = ((reply.get("aggregations") or {}).get("pairs") or {}).get(
        "buckets"
    ) or {}
    return {
        name: b.get("timestamps", {}).get("buckets", []) for name, b in buckets.items()
    }


# OLD CODE END


def _paged_slots(client, filters: list[dict], key: dict) -> tuple[list[dict], bool]:
    """Non-empty 10 s slots of one pair too busy to share a request, paged (False if capped)."""
    slots, complete = all_buckets(
        client,
        NETWORK_INDEX,
        {"bool": {"filter": [*filters, *_pair_filter(key)]}},
        [
            {
                "t": {
                    "date_histogram": {
                        "field": "@timestamp",
                        "fixed_interval": f"{BEACON_SLOT_SECONDS}s",
                    }
                }
            }
        ],
    )
    return [{"key": s["key"]["t"]} for s in slots], complete


def _assess_beacon(key: dict, conn_count: int, ts_buckets: list[dict]) -> dict | None:
    """The beacon finding for one pair, or None if its connections aren't periodic."""
    if (
        conn_count < BEACONING_MIN_CONNECTIONS
        or len(ts_buckets) < BEACONING_MIN_CONNECTIONS
    ):
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
        # OLD CODE START — #96: every regular schedule was called C2, NTP and BitTorrent included
        # "assessment": (
        #     f"Periodic callbacks every ~{round(interval_sec)}s with "
        #     f"{round(cv * 100, 1)}% jitter over {conn_count} connections. "
        #     f"Consistent with C2 beaconing."
        # ),
        # OLD CODE END
        "pattern": "beacon",
        "assessment": (
            f"Connects to {key['dst']}:{key['port']} every ~{round(interval_sec)}s "
            f"({round(cv * 100, 1)}% jitter, {conn_count} connections). Malware that calls home "
            f"looks like this; so do update checks and cloud-connected devices."
        ),
    }


def _candidate_pairs(client, filters: list[dict]) -> tuple[list[dict], bool]:
    """Every pair with enough connections to be a beacon (False if a bucket cap stopped it).

    One multi_terms list with min_doc_count (1.4 s on the G11 instead of 5.6 s paging all
    33,645 pairs); a network with more candidates than one list holds is paged instead.
    """
    body = {
        "size": 0,
        "query": {"bool": {"filter": filters}},
        "aggs": {
            "pairs": {
                "multi_terms": {
                    "terms": _PAIR_FIELDS,
                    "size": CANDIDATE_LIST_SIZE,
                    "min_doc_count": BEACONING_MIN_CONNECTIONS,
                }
            }
        },
    }
    reply = client.search(index=NETWORK_INDEX, body=body)
    listed = (reply.get("aggregations") or {}).get("pairs") or {}
    if not listed.get("sum_other_doc_count"):
        return [
            {
                "key": {
                    "src": b["key"][0],
                    "dst": b["key"][1],
                    "port": int(b["key"][2]),
                },
                "doc_count": b["doc_count"],
            }
            for b in listed.get("buckets", [])
        ], True
    pairs, complete = all_buckets(
        client, NETWORK_INDEX, {"bool": {"filter": filters}}, _PAIR_SOURCES
    )
    return [p for p in pairs if p["doc_count"] >= BEACONING_MIN_CONNECTIONS], complete


def _mark_many_hosts(beacons: list[dict]) -> list[dict]:
    """Findings of a device with MANY_HOSTS_MIN or more scheduled internet hosts, relabelled."""
    hosts: dict[str, set] = defaultdict(set)
    for b in beacons:
        hosts[b["source_ip"]].add(b["destination_ip"])
    marked = []
    for b in beacons:
        n = len(hosts[b["source_ip"]])
        if n < MANY_HOSTS_MIN:
            marked.append(b)
            continue
        marked.append(
            {
                **b,
                "pattern": "many_hosts",
                "host_count": n,
                "assessment": (
                    f"One of {n} internet hosts {b['source_ip']} contacts on regular schedules. Malware "
                    f"that calls home usually calls one or a few servers; this many usually means "
                    f"peer-to-peer software (such as BitTorrent) or a device syncing with many services."
                ),
            }
        )
    return marked


def _scan_beacons(
    client, filters: list[dict], slots: int | None
) -> tuple[list[dict], bool]:
    """(beacons among every pair, False if a bucket cap left some pairs unchecked)."""
    # OLD CODE START — #96: every pair was paged (34 searches on the G11) to keep ~7% of them
    # pairs, complete = all_buckets(client, NETWORK_INDEX, {"bool": {"filter": filters}}, _PAIR_SOURCES)
    # # timing is only read for pairs with enough connections to be a beacon
    # candidates = [p for p in pairs if p["doc_count"] >= BEACONING_MIN_CONNECTIONS]
    # OLD CODE END
    candidates, complete = _candidate_pairs(client, filters)
    batches, too_big = _histogram_batches(candidates, slots)
    timings = {
        name: ts
        for batch in batches
        for name, ts in _batch_slots(client, filters, batch).items()
    }
    paged = {
        _pair_name(p["key"]): _paged_slots(client, filters, p["key"]) for p in too_big
    }
    timings = {**timings, **{name: ts for name, (ts, _) in paged.items()}}
    complete = complete and all(done for _, done in paged.values())
    found = (
        _assess_beacon(p["key"], p["doc_count"], timings.get(_pair_name(p["key"]), []))
        for p in candidates
    )
    return _mark_many_hosts([b for b in found if b is not None]), complete


def detect_beaconing(
    client, from_ts: str, to_ts: str, excluded_ips: list[str] | None = None
) -> tuple[list[dict], bool]:
    """Detect periodic callback patterns indicative of C2 beaconing.

    Returns (beacons, complete): complete is False if the bucket cap stopped the scan. A failed
    query raises, so callers can't mistake it for "no beacons" (#96).

    ``excluded_ips`` is ignored (kept for callers): excluded IPs stay visible here.
    """
    # OLD CODE START — excluded IPs stay visible in threat detections
    # excluded = build_excluded_ips_filter(excluded_ips or [])
    # OLD CODE END
    bool_clause: dict = {
        "filter": [
            {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
            {"term": {"event.provider": "zeek"}},
            # OLD CODE START — F1: also counted conn_long.log interim records
            # {"term": {"event.dataset": "conn"}},
            # OLD CODE END
            CONN_ACCOUNTING,
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
    # OLD CODE START — #96: a failed query read as "No beaconing patterns detected"
    # try:
    #     beacons, complete = _scan_beacons(client, bool_clause["filter"], _max_slots(from_ts, to_ts))
    # except Exception:
    #     logger.error("Beaconing detection query failed", exc_info=True)
    #     return []
    # OLD CODE END
    # #96: calls home go to internet hosts; DNS, NTP, mDNS... repeat by design
    scope = {
        "bool": {
            "must_not": [
                {"terms": {"destination.ip": NOT_INTERNET_CIDRS}},
                {"terms": {"destination.port": sorted(PERIODIC_BY_DESIGN_PORTS)}},
            ]
        }
    }
    beacons, complete = _scan_beacons(
        client, [*bool_clause["filter"], scope], _max_slots(from_ts, to_ts)
    )
    if not complete:
        logger.warning(
            "Beaconing: the scan hit its bucket cap; pairs past it were not checked"
        )

    beacons.sort(key=lambda b: b["confidence"], reverse=True)
    return beacons, complete


# ---------------------------------------------------------------------------
# Lateral Movement Detection
# ---------------------------------------------------------------------------


def detect_lateral_movement(
    client, from_ts: str, to_ts: str, excluded_ips: list[str] | None = None
) -> tuple[list[dict], bool]:
    """Find internal hosts connecting to other internal hosts on admin ports.

    Returns (movements, complete): complete is False if the bucket cap stopped the scan. A
    failed query raises, so callers can't mistake it for "no lateral movement" (#96).

    NET-240: a connection counts when it was active in the window, read from its final and its
    interim (conn_long.log) records, so a session still open shows as of its latest interim
    record (Zeek's long-connection schedule, about 30 min on the G11 for the first one).
    `connection_count` is OpenSearch's approximate distinct count of `zeek.uid`, plus one per
    record without a uid (`records_without_uid`, 0 on Zeek data). Beaconing keeps final records
    only: one open connection is one connection, and its interim records would look periodic.

    ``excluded_ips`` is ignored (kept for callers): excluded IPs stay visible here.
    """
    port_filters = [{"term": {"destination.port": p}} for p in LATERAL_MOVEMENT_PORTS]
    # OLD CODE START — excluded IPs stay visible in threat detections
    # excluded = build_excluded_ips_filter(excluded_ips or [])
    # OLD CODE END

    bool_clause: dict = {
        "filter": [
            # OLD CODE START — NET-240: @timestamp is the connection's start, so a session begun
            # before the window was unseen however recent its interim records
            # {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
            # OLD CODE END
            # active in the window: started by its end, and seen (lastPacket) or started after its start
            {"range": {"@timestamp": {"lte": to_ts}}},
            {
                "bool": {
                    "should": [
                        {"range": {"lastPacket": {"gte": from_ts}}},
                        {"range": {"@timestamp": {"gte": from_ts}}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            {"term": {"event.provider": "zeek"}},
            # OLD CODE START — F1: also counted conn_long.log interim records
            # {"term": {"event.dataset": "conn"}},
            # OLD CODE END
            # OLD CODE: CONN_ACCOUNTING, (NET-240: interim records too; connections are counted by uid below)
            CONN_RECORDS,
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
    # OLD CODE START — #96: a failed query read as "No lateral movement detected"
    # try:
    #     pairs, complete = all_buckets(...)
    # except Exception:
    #     logger.error("Lateral movement detection query failed", exc_info=True)
    #     return []
    # OLD CODE END
    pairs, complete = all_buckets(
        client,
        NETWORK_INDEX,
        {"bool": bool_clause},
        _PAIR_SOURCES,
        aggs={
            "first_seen": {"min": {"field": "@timestamp"}},
            "last_seen": {"max": {"field": "@timestamp"}},
            # NET-240: interim and final records of one connection share its uid
            "last_packet": {"max": {"field": "lastPacket"}},
            "uids": {"cardinality": {"field": "zeek.uid", "precision_threshold": 1000}},
            "with_uid": {"value_count": {"field": "zeek.uid"}},
        },
    )
    if not complete:
        logger.warning(
            "Lateral movement: the scan hit its bucket cap; pairs past it were not checked"
        )

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
        # OLD CODE START — NET-240: one record per finished connection; interim records now count
        # count = bucket["doc_count"]
        # OLD CODE END
        without_uid = bucket["doc_count"] - bucket.get("with_uid", {}).get("value", 0)
        count = bucket.get("uids", {}).get("value", 0) + without_uid
        # OLD CODE START — NET-240: the start of the newest connection, not when it was last seen
        # "last_seen": bucket.get("last_seen", {}).get("value_as_string"),
        # OLD CODE END
        last_seen = max(
            (bucket.get(k) or {} for k in ("last_seen", "last_packet")),
            key=lambda m: m.get("value") or 0,
        ).get("value_as_string")
        # OLD CODE START — NET-240: an approximate distinct count, so not "N times"
        # f"Internal host {src} connected to {dst} via {service} "
        # f"({count} times). Verify this is authorized administrative access."
        # OLD CODE END
        no_uid_note = (
            f" {without_uid} records had no connection ID and are counted one each."
            if without_uid
            else ""
        )

        suspicious.append(
            {
                "source_ip": src,
                "destination_ip": dst,
                "port": port,
                "service": service,
                "connection_count": count,
                "records_without_uid": without_uid,
                "first_seen": bucket.get("first_seen", {}).get("value_as_string"),
                "last_seen": last_seen,
                "assessment": (
                    f"Internal host {src} connected to {dst} via {service} "
                    f"(about {count} connections). Verify this is authorized administrative "
                    f"access.{no_uid_note}"
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
    return suspicious, complete


# ---------------------------------------------------------------------------
# DNS Anomaly Detection
# ---------------------------------------------------------------------------


def analyze_dns_anomalies(
    client, from_ts: str, to_ts: str, excluded_ips: list[str] | None = None
) -> dict:
    """Detect DNS-based threats: DGA, tunneling, NXDOMAIN spikes.

    A failed query raises, so callers can't mistake it for "no DNS anomalies" (#96).
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

    # OLD CODE START — #96: only the top 500 names and top 100 sources were checked; DGA and
    # tunnel names are each queried about once (the tail the list cut), and a source ranked
    # 101st by volume could send any share of NXDOMAINs unseen
    # query = {
    #     "size": 0,
    #     "query": {"bool": bool_clause},
    #     "aggs": {
    #         "domains": {
    #             "terms": {"field": "zeek.dns.query", "size": 500},
    #         },
    #         "by_source": {
    #             "terms": {"field": "source.ip", "size": 100},
    #             "aggs": {
    #                 "unique_domains": {"cardinality": {"field": "zeek.dns.query"}},
    #                 "nxdomain_count": {
    #                     "filter": {"term": {"zeek.dns.rcode_name": "NXDOMAIN"}}
    #                 },
    #             },
    #         },
    #     },
    # }
    #
    # try:
    #     result = client.search(index=NETWORK_INDEX, body=query)
    # except Exception:
    #     logger.error("DNS anomaly analysis failed", exc_info=True)
    #     return {
    #         "dga_suspects": [],
    #         "tunnel_suspects": [],
    #         "nxdomain_spikes": [],
    #         "suspicious_tlds": [],
    #     }
    # OLD CODE END
    query = {"bool": bool_clause}
    # OLD CODE START — #96: a failed query returned empty lists, read as "No DNS anomalies detected"
    # try:
    #     names, names_complete = all_buckets(...)
    #     sources, sources_complete = all_buckets(...)
    # except Exception:
    #     logger.error("DNS anomaly analysis failed", exc_info=True)
    #     return {"dga_suspects": [], "tunnel_suspects": [], "nxdomain_spikes": [],
    #             "suspicious_tlds": [], "complete": False}
    # OLD CODE END
    names, names_complete = all_buckets(
        client, NETWORK_INDEX, query, [{"name": {"terms": {"field": "zeek.dns.query"}}}]
    )
    sources, sources_complete = all_buckets(
        client,
        NETWORK_INDEX,
        query,
        [{"src": {"terms": {"field": "source.ip"}}}],
        aggs={
            "unique_domains": {"cardinality": {"field": "zeek.dns.query"}},
            "nxdomain_count": {"filter": {"term": {"zeek.dns.rcode_name": "NXDOMAIN"}}},
        },
    )
    complete = names_complete and sources_complete
    if not complete:
        logger.warning(
            "DNS anomalies: the scan hit its bucket cap; names or sources past it were not checked"
        )

    findings: dict[str, list] = {
        "dga_suspects": [],
        "tunnel_suspects": [],
        "nxdomain_spikes": [],
        "suspicious_tlds": [],
    }

    # OLD CODE START — #96: iterated the top-500 terms list
    # for bucket in result.get("aggregations", {}).get("domains", {}).get("buckets", []):
    #     domain = bucket["key"]
    # OLD CODE END
    # most-queried first, the order the top list gave, so each list's first rows mean the same
    for bucket in sorted(names, key=lambda b: -b["doc_count"]):
        domain = bucket["key"]["name"]
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
        registrable = (
            parts[-3] if len(parts) >= 3 and len(parts[-2]) <= 3 else parts[-2]
        )
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
    # OLD CODE START — #96: iterated the top-100 sources list
    # for bucket in (
    #     result.get("aggregations", {}).get("by_source", {}).get("buckets", [])
    # ):
    #     src_ip = bucket["key"]
    # OLD CODE END
    for bucket in sorted(sources, key=lambda b: -b["doc_count"]):
        src_ip = bucket["key"]["src"]
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
    # OLD CODE START — #96: no way to tell a full scan from one a bucket cap stopped
    # return findings
    # OLD CODE END
    return {**findings, "complete": complete}
