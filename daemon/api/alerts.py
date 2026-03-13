"""
NetTap Alert API Routes

Registers Suricata alert endpoints with the aiohttp application.
These endpoints query the unified arkime_sessions3-* index (Malcolm's
Logstash pipeline) filtered by event.provider=suricata and event.dataset=alert
to provide paginated alert listings, severity counts, individual alert
details, and acknowledgement tracking.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from aiohttp import web
from opensearchpy import OpenSearchException

from services.alert_enrichment import AlertEnrichment
from storage.manager import StorageManager

logger = logging.getLogger("nettap.api.alerts")

# Module-level enrichment instance (loaded once, reused across requests)
_alert_enrichment = AlertEnrichment()

# Default time range: last 24 hours
_DEFAULT_RANGE_HOURS = 24

# OLD CODE START — replaced by unified NETWORK_INDEX (Malcolm routes all data here)
# SURICATA_INDEX = "suricata-*"
# OLD CODE END
NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# Suricata alert filters — all queries must include these to select only
# Suricata alert documents from the unified index.
_SURICATA_ALERT_FILTERS: list[dict] = [
    {"term": {"event.provider": "suricata"}},
    {"term": {"event.dataset": "alert"}},
]

# Exclude Suricata internal decoder/stream errors from alert counts and
# listings.  These fire millions of times (e.g., "SURICATA AF-PACKET
# truncated packet", "SURICATA IPv4 truncated packet") and are not real
# security alerts — they indicate capture-layer issues, not threats.
_SURICATA_NOISE_EXCLUSION: list[dict] = [
    {"prefix": {"rule.name": "SURICATA "}},
]

# Path for storing acknowledgement data (local JSON file)
_ACK_FILE = os.environ.get("ALERT_ACK_FILE", "/opt/nettap/data/alert_acks.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_time_range(request: web.Request) -> tuple[str, str]:
    """Extract 'from' and 'to' query parameters as ISO timestamps.

    Defaults to the last 24 hours if not provided or unparseable.
    """
    now = datetime.now(timezone.utc)
    default_from = (now - timedelta(hours=_DEFAULT_RANGE_HOURS)).isoformat()
    default_to = now.isoformat()

    raw_from = request.query.get("from", "")
    raw_to = request.query.get("to", "")

    if raw_from:
        try:
            datetime.fromisoformat(raw_from.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raw_from = ""
    if raw_to:
        try:
            datetime.fromisoformat(raw_to.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raw_to = ""

    return (raw_from or default_from, raw_to or default_to)


def _parse_int_param(request: web.Request, name: str, default: int) -> int:
    """Parse an integer query parameter with a fallback default."""
    raw = request.query.get(name, "")
    if raw:
        try:
            return max(1, int(raw))
        except (ValueError, TypeError):
            pass
    return default


def _time_range_filter(from_ts: str, to_ts: str) -> dict:
    """Build an OpenSearch range filter on the '@timestamp' field (ECS)."""
    # OLD CODE START — Zeek-native field name
    # "timestamp": { ... }
    # OLD CODE END
    return {
        "range": {
            "@timestamp": {
                "gte": from_ts,
                "lte": to_ts,
                "format": "strict_date_optional_time",
            }
        }
    }


def _get_client(request: web.Request):
    """Retrieve the OpenSearch client from the StorageManager on the app."""
    storage: StorageManager = request.app["storage"]
    return storage._client


def _normalize_alert_source(source: dict) -> dict:
    """Normalize OpenSearch ECS/Malcolm field names into the structure the
    frontend expects.

    OpenSearch documents from Malcolm's Logstash pipeline can store Suricata
    alert fields under several paths depending on ECS normalization:

    - ``rule.name`` / ``rule.id`` / ``rule.category``  (ECS)
    - ``suricata.alert.signature`` / ``suricata.alert.severity``  (Malcolm)
    - ``alert.signature`` / ``alert.severity``  (raw Suricata EVE)
    - ``suricata.severity``  (Malcolm top-level duplicate)

    This function merges all paths into a single ``alert`` sub-dict and
    flattens network fields so the frontend can access them uniformly.
    """
    rule = source.get("rule", {}) or {}
    suricata = source.get("suricata", {}) or {}
    suricata_alert = suricata.get("alert", {}) if isinstance(suricata, dict) else {}
    suricata_alert = suricata_alert or {}
    existing_alert = source.get("alert", {}) or {}

    # --- alert sub-dict (signature, severity, category) ---
    signature = (
        existing_alert.get("signature")
        or rule.get("name")
        or suricata_alert.get("signature")
        or ""
    )
    signature_id = (
        existing_alert.get("signature_id")
        or rule.get("id")
        or suricata_alert.get("signature_id")
    )
    raw_category = (
        existing_alert.get("category")
        or rule.get("category")
        or suricata_alert.get("category")
        or ""
    )
    # Malcolm may store category as a list — flatten to first string
    if isinstance(raw_category, list):
        category = raw_category[0] if raw_category else ""
    else:
        category = raw_category
    severity = _extract_severity(existing_alert, suricata, suricata_alert)

    source["alert"] = {
        "signature": signature,
        "signature_id": signature_id,
        "severity": severity,
        "category": str(category),
    }

    # --- Flatten network endpoints ---
    src = source.get("source", {}) or {}
    dst = source.get("destination", {}) or {}
    net = source.get("network", {}) or {}

    def _first_ip(val):
        """Handle array-valued IP fields (ECS sometimes wraps in list)."""
        if isinstance(val, list):
            return val[0] if val else None
        return val

    if isinstance(src, dict):
        source.setdefault("src_ip", _first_ip(src.get("ip")))
        source.setdefault("src_port", src.get("port"))
    if isinstance(dst, dict):
        source.setdefault("dest_ip", _first_ip(dst.get("ip")))
        source.setdefault("dest_port", dst.get("port"))
    if isinstance(net, dict):
        source.setdefault("proto", net.get("transport"))

    # --- Normalize timestamp ---
    # Prefer @timestamp (ISO 8601) over raw timestamp (epoch millis from Malcolm)
    if "@timestamp" in source:
        source["timestamp"] = source["@timestamp"]
    elif "timestamp" not in source:
        source["timestamp"] = ""

    return source


def _extract_severity(alert_sub: dict, suricata: dict, suricata_alert: dict) -> int:
    """Extract severity from the first available field path.

    Returns 3 (low) as the default if no severity is found.
    """
    # 1. alert.severity  (raw Suricata EVE)
    sev = alert_sub.get("severity")
    if isinstance(sev, int):
        return sev

    # 2. suricata.severity  (Malcolm top-level)
    sev = suricata.get("severity") if isinstance(suricata, dict) else None
    if isinstance(sev, int):
        return sev
    # Could be stored as string "1" via keyword mapping
    if isinstance(sev, str):
        try:
            return int(sev)
        except ValueError:
            pass

    # 3. suricata.alert.severity  (Malcolm nested)
    sev = suricata_alert.get("severity")
    if isinstance(sev, int):
        return sev

    return 3  # default: low


def _load_acks(ack_file: str | None = None) -> dict:
    """Load the alert acknowledgement map from disk.

    Returns a dict of {alert_id: {acknowledged_at, acknowledged_by}}.
    """
    path = ack_file or _ACK_FILE
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load ack file %s: %s", path, exc)
    return {}


def _save_acks(acks: dict, ack_file: str | None = None) -> None:
    """Persist the alert acknowledgement map to disk."""
    path = ack_file or _ACK_FILE
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(acks, f, indent=2)
    except OSError as exc:
        logger.error("Failed to save ack file %s: %s", path, exc)
        raise


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_alerts_list(request: web.Request) -> web.Response:
    """GET /api/alerts?from=&to=&severity=&page=1&size=50

    Returns a paginated list of Suricata alerts with optional severity filter.
    Severity: 1=high, 2=medium, 3=low.
    """
    from_ts, to_ts = _parse_time_range(request)
    page = _parse_int_param(request, "page", 1)
    size = min(_parse_int_param(request, "size", 50), 200)
    severity_raw = request.query.get("severity", "")
    client = _get_client(request)

    offset = (page - 1) * size

    filter_clauses: list[dict] = [
        _time_range_filter(from_ts, to_ts),
        *_SURICATA_ALERT_FILTERS,
    ]

    # Optional severity filter
    # OLD CODE START — Zeek-native field: "alert.severity"
    # filter_clauses.append({"term": {"alert.severity": severity}})
    # OLD CODE END
    if severity_raw:
        try:
            severity = int(severity_raw)
            if severity in (1, 2, 3):
                filter_clauses.append({"term": {"suricata.alert.severity": severity}})
        except (ValueError, TypeError):
            pass

    # Optional signature filter (wildcard match on rule.name)
    sig_filter = request.query.get("signature", "")
    if sig_filter:
        filter_clauses.append({"match_phrase": {"rule.name": sig_filter}})

    # Optional IP filter (matches source OR destination)
    ip_filter = request.query.get("ip", "")
    if ip_filter:
        filter_clauses.append({
            "bool": {
                "should": [
                    {"term": {"source.ip.keyword": ip_filter}},
                    {"term": {"destination.ip.keyword": ip_filter}},
                ],
                "minimum_should_match": 1,
            }
        })

    query = {
        "size": size,
        "from": offset,
        "query": {
            "bool": {
                "filter": filter_clauses,
                "must_not": _SURICATA_NOISE_EXCLUSION,
            }
        },
        # OLD CODE START — Zeek-native sort field: "timestamp"
        # "sort": [{"timestamp": {"order": "desc"}}],
        # OLD CODE END
        "sort": [{"@timestamp": {"order": "desc"}}],
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in alerts list: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    hits = result.get("hits", {})
    total_raw = hits.get("total", {})
    total = total_raw.get("value", 0) if isinstance(total_raw, dict) else total_raw

    # Load acks to annotate results
    acks = _load_acks(request.app.get("alert_ack_file"))

    alerts = []
    for hit in hits.get("hits", []):
        source = hit.get("_source", {})
        alert_id = hit.get("_id", "")
        source["_id"] = alert_id
        source["_index"] = hit.get("_index", "")
        source["acknowledged"] = alert_id in acks
        if alert_id in acks:
            source["acknowledged_at"] = acks[alert_id].get("acknowledged_at")
        # Normalize ECS/Malcolm field names into frontend-expected structure
        _normalize_alert_source(source)
        # Enrich with plain English description, risk context, and recommendation
        _alert_enrichment.enrich_alert(source)
        alerts.append(source)

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "page": page,
            "size": size,
            "total": total,
            "total_pages": (total + size - 1) // size if size > 0 else 0,
            "alerts": alerts,
        }
    )


async def handle_alerts_count(request: web.Request) -> web.Response:
    """GET /api/alerts/count?from=&to=

    Returns alert counts grouped by severity level.
    """
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)

    query = {
        "size": 0,
        "track_total_hits": True,
        "query": {
            "bool": {
                "filter": [
                    _time_range_filter(from_ts, to_ts),
                    *_SURICATA_ALERT_FILTERS,
                ],
                "must_not": _SURICATA_NOISE_EXCLUSION,
            }
        },
        "aggs": {
            # OLD CODE START — Zeek-native: "alert.severity"
            # "by_severity": {"terms": {"field": "alert.severity", "size": 10}},
            # OLD CODE END
            "by_severity": {"terms": {"field": "suricata.alert.severity", "size": 10}},
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in alerts/count: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    aggs = result.get("aggregations", {})
    buckets = aggs.get("by_severity", {}).get("buckets", [])

    hits_total = result.get("hits", {}).get("total", {})
    total = hits_total.get("value", 0) if isinstance(hits_total, dict) else hits_total

    severity_map = {1: "high", 2: "medium", 3: "low"}
    counts = {
        "total": total,
        "high": 0,
        "medium": 0,
        "low": 0,
    }
    for b in buckets:
        key = b.get("key")
        # Handle both int keys (numeric field) and string keys (.keyword field)
        int_key = key
        if isinstance(key, str):
            try:
                int_key = int(key)
            except (ValueError, TypeError):
                int_key = None
        label = severity_map.get(int_key, f"severity_{key}")
        counts[label] = b.get("doc_count", 0)

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "counts": counts,
        }
    )


async def handle_alert_detail(request: web.Request) -> web.Response:
    """GET /api/alerts/{id}

    Returns a single alert document by its OpenSearch _id.
    """
    alert_id = request.match_info.get("id", "")
    if not alert_id:
        return web.json_response({"error": "Alert ID is required"}, status=400)

    client = _get_client(request)

    # Search across the unified index for the document by _id, filtered
    # to suricata alerts only so we don't return Zeek docs by accident.
    query = {
        "size": 1,
        "query": {
            "bool": {
                "must": [{"ids": {"values": [alert_id]}}],
                "filter": list(_SURICATA_ALERT_FILTERS),
            }
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in alert detail: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    hits = result.get("hits", {}).get("hits", [])
    if not hits:
        return web.json_response({"error": "Alert not found"}, status=404)

    hit = hits[0]
    source = hit.get("_source", {})
    source["_id"] = hit.get("_id", "")
    source["_index"] = hit.get("_index", "")

    # Annotate with acknowledgement status
    acks = _load_acks(request.app.get("alert_ack_file"))
    source["acknowledged"] = source["_id"] in acks
    if source["_id"] in acks:
        source["acknowledged_at"] = acks[source["_id"]].get("acknowledged_at")
        source["acknowledged_by"] = acks[source["_id"]].get("acknowledged_by")

    # Normalize ECS/Malcolm field names into frontend-expected structure
    _normalize_alert_source(source)
    # Enrich with plain English description, risk context, and recommendation
    _alert_enrichment.enrich_alert(source)

    return web.json_response({"alert": source})


async def handle_alert_acknowledge(request: web.Request) -> web.Response:
    """POST /api/alerts/{id}/acknowledge

    Mark an alert as acknowledged. Stores the ack in a local JSON file.
    Accepts optional JSON body with 'acknowledged_by' field.
    """
    alert_id = request.match_info.get("id", "")
    if not alert_id:
        return web.json_response({"error": "Alert ID is required"}, status=400)

    # Parse optional body
    acknowledged_by = "admin"
    try:
        body = await request.json()
        acknowledged_by = body.get("acknowledged_by", "admin")
    except Exception:
        pass  # No body or invalid JSON is fine, use default

    ack_file = request.app.get("alert_ack_file")
    acks = _load_acks(ack_file)

    acks[alert_id] = {
        "acknowledged_at": datetime.now(timezone.utc).isoformat(),
        "acknowledged_by": acknowledged_by,
    }

    try:
        _save_acks(acks, ack_file)
    except OSError as exc:
        return web.json_response(
            {"error": f"Failed to save acknowledgement: {exc}"}, status=500
        )

    return web.json_response(
        {
            "result": "acknowledged",
            "alert_id": alert_id,
            "acknowledged_at": acks[alert_id]["acknowledged_at"],
            "acknowledged_by": acknowledged_by,
        }
    )


# ---------------------------------------------------------------------------
# Aggregation endpoints (timeline, top signatures, top IPs, categories)
# ---------------------------------------------------------------------------

# Allowed intervals for the timeline endpoint (prevents injection).
_ALLOWED_INTERVALS = {"1m", "5m", "10m", "15m", "30m", "1h", "6h", "12h", "1d"}

# Severity number → label mapping (shared by timeline and top-signatures).
_SEVERITY_MAP = {1: "high", 2: "medium", 3: "low"}


async def handle_alerts_timeline(request: web.Request) -> web.Response:
    """GET /api/alerts/timeline?from=&to=&interval=

    Returns time-series alert counts bucketed by interval and severity.
    Uses a date_histogram aggregation with a severity sub-aggregation.
    """
    from_ts, to_ts = _parse_time_range(request)
    interval = request.query.get("interval", "1h")
    if interval not in _ALLOWED_INTERVALS:
        interval = "1h"
    client = _get_client(request)

    query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    _time_range_filter(from_ts, to_ts),
                    *_SURICATA_ALERT_FILTERS,
                ]
            }
        },
        "aggs": {
            "over_time": {
                "date_histogram": {
                    "field": "@timestamp",
                    "fixed_interval": interval,
                    "min_doc_count": 0,
                    "extended_bounds": {"min": from_ts, "max": to_ts},
                },
                "aggs": {
                    "by_severity": {
                        "terms": {"field": "suricata.alert.severity", "size": 5}
                    }
                },
            }
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in alerts/timeline: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    buckets = []
    for bucket in result.get("aggregations", {}).get("over_time", {}).get("buckets", []):
        entry = {"timestamp": bucket.get("key_as_string", ""), "high": 0, "medium": 0, "low": 0}
        for sev_bucket in bucket.get("by_severity", {}).get("buckets", []):
            key = sev_bucket.get("key")
            try:
                int_key = int(key)
            except (ValueError, TypeError):
                continue
            label = _SEVERITY_MAP.get(int_key)
            if label:
                entry[label] = sev_bucket.get("doc_count", 0)
        buckets.append(entry)

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "interval": interval,
        "buckets": buckets,
    })


async def handle_alerts_top_signatures(request: web.Request) -> web.Response:
    """GET /api/alerts/top-signatures?from=&to=&limit=

    Returns the most frequently triggered alert signatures with their
    primary severity level.
    """
    from_ts, to_ts = _parse_time_range(request)
    limit = min(_parse_int_param(request, "limit", 20), 100)
    client = _get_client(request)

    query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    _time_range_filter(from_ts, to_ts),
                    *_SURICATA_ALERT_FILTERS,
                ]
            }
        },
        "aggs": {
            "top_sigs": {
                "terms": {"field": "rule.name.keyword", "size": limit, "missing": "Unknown"},
                "aggs": {
                    "severity": {
                        "terms": {"field": "suricata.alert.severity", "size": 3}
                    }
                },
            }
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in alerts/top-signatures: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    signatures = []
    for bucket in result.get("aggregations", {}).get("top_sigs", {}).get("buckets", []):
        sev_buckets = bucket.get("severity", {}).get("buckets", [])
        primary_severity = 3  # default: low
        if sev_buckets:
            try:
                primary_severity = int(sev_buckets[0].get("key", 3))
            except (ValueError, TypeError):
                primary_severity = 3
        signatures.append({
            "signature": bucket.get("key", "Unknown"),
            "count": bucket.get("doc_count", 0),
            "severity": primary_severity,
        })

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "signatures": signatures,
    })


async def handle_alerts_top_ips(request: web.Request) -> web.Response:
    """GET /api/alerts/top-ips?from=&to=&limit=&direction=src|dest

    Returns the most frequently seen IPs in alerts, either as source
    (attacker) or destination (target) addresses.
    """
    from_ts, to_ts = _parse_time_range(request)
    limit = min(_parse_int_param(request, "limit", 10), 50)
    direction = request.query.get("direction", "dest")
    if direction not in ("src", "dest"):
        direction = "dest"
    client = _get_client(request)

    field = "source.ip.keyword" if direction == "src" else "destination.ip.keyword"

    query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    _time_range_filter(from_ts, to_ts),
                    *_SURICATA_ALERT_FILTERS,
                ]
            }
        },
        "aggs": {
            "top_ips": {
                "terms": {"field": field, "size": limit}
            }
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in alerts/top-ips: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    ips = []
    for bucket in result.get("aggregations", {}).get("top_ips", {}).get("buckets", []):
        ips.append({
            "ip": bucket.get("key", ""),
            "count": bucket.get("doc_count", 0),
        })

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "direction": direction,
        "ips": ips,
    })


async def handle_alerts_categories(request: web.Request) -> web.Response:
    """GET /api/alerts/categories?from=&to=

    Returns alert counts grouped by rule category.
    """
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)

    query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    _time_range_filter(from_ts, to_ts),
                    *_SURICATA_ALERT_FILTERS,
                ]
            }
        },
        "aggs": {
            "by_category": {
                "terms": {"field": "rule.category.keyword", "size": 20, "missing": "Uncategorized"}
            }
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in alerts/categories: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    categories = []
    for bucket in result.get("aggregations", {}).get("by_category", {}).get("buckets", []):
        categories.append({
            "category": bucket.get("key", "Uncategorized"),
            "count": bucket.get("doc_count", 0),
        })

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "categories": categories,
    })


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_alert_routes(
    app: web.Application, storage_manager: StorageManager
) -> None:
    """Register all alert API routes on the given aiohttp application.

    The StorageManager is expected to already be stored in app['storage']
    by create_app(). This function registers the route handlers.
    """
    # Static routes must be registered BEFORE {id} param route
    app.router.add_get("/api/alerts", handle_alerts_list)
    app.router.add_get("/api/alerts/count", handle_alerts_count)
    app.router.add_get("/api/alerts/timeline", handle_alerts_timeline)
    app.router.add_get("/api/alerts/top-signatures", handle_alerts_top_signatures)
    app.router.add_get("/api/alerts/top-ips", handle_alerts_top_ips)
    app.router.add_get("/api/alerts/categories", handle_alerts_categories)
    app.router.add_get("/api/alerts/{id}", handle_alert_detail)
    app.router.add_post("/api/alerts/{id}/acknowledge", handle_alert_acknowledge)
    logger.info("Alert API routes registered (8 endpoints)")
