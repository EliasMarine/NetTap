"""
NetTap Traffic API Routes

Registers traffic analysis endpoints with the aiohttp application.
These endpoints query OpenSearch arkime_sessions3-* indices to provide
network traffic summaries, top talkers, protocol distributions,
bandwidth time-series, and paginated connection listings.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from aiohttp import web
from opensearchpy import OpenSearchException

from services.excluded_ips import build_excluded_ips_filter
from services import traffic_classifier
from services.traffic_classifier import get_category_stats
from storage.manager import StorageManager

logger = logging.getLogger("nettap.api.traffic")

# Default time range: last 24 hours
_DEFAULT_RANGE_HOURS = 24

# OLD CODE START — replaced Zeek-native index with Malcolm unified index
# ZEEK_INDEX = "zeek-*"
# OLD CODE END
NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# Zeek conn event filters — Malcolm routes all data into arkime_sessions3-*;
# these term filters select only Zeek connection logs from the unified index.
_ZEEK_CONN_FILTERS = [
    {"term": {"event.provider": "zeek"}},
    {"term": {"event.dataset": "conn"}},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_time_range(request: web.Request) -> tuple[str, str]:
    """Extract 'from' and 'to' query parameters as ISO timestamps.

    Defaults to the last 24 hours if not provided or unparseable.
    Returns (from_iso, to_iso) strings suitable for OpenSearch range queries.
    """
    now = datetime.now(timezone.utc)
    default_from = (now - timedelta(hours=_DEFAULT_RANGE_HOURS)).isoformat()
    default_to = now.isoformat()

    raw_from = request.query.get("from", "")
    raw_to = request.query.get("to", "")

    # Validate from
    if raw_from:
        try:
            datetime.fromisoformat(raw_from.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raw_from = ""
    # Validate to
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


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_traffic_summary(request: web.Request) -> web.Response:
    """GET /api/traffic/summary?from=&to=

    Returns total bytes, packet count, connection count, and top protocol
    for the given time range from arkime_sessions3-* indices.
    """
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)

    query = {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": {"filter": [
            _time_range_filter(from_ts, to_ts),
            *_ZEEK_CONN_FILTERS,
        ]}},
        "aggs": {
            # OLD CODE START — Arkime session fields (client.bytes/server.bytes) include
            # protocol overhead and inflate values ~25x vs actual network bytes.
            # "total_orig_bytes": {"sum": {"field": "client.bytes", "missing": 0}},
            # "total_resp_bytes": {"sum": {"field": "server.bytes", "missing": 0}},
            # OLD CODE END
            "total_orig_bytes": {"sum": {"field": "source.bytes", "missing": 0}},
            "total_resp_bytes": {"sum": {"field": "destination.bytes", "missing": 0}},
            "total_orig_pkts": {"sum": {"field": "source.packets", "missing": 0}},
            "total_resp_pkts": {"sum": {"field": "destination.packets", "missing": 0}},
            "top_protocol": {"terms": {"field": "network.transport.keyword", "size": 1}},
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in traffic/summary: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    aggs = result.get("aggregations", {})
    hits_total = result.get("hits", {}).get("total", {})
    connection_count = (
        hits_total.get("value", 0) if isinstance(hits_total, dict) else hits_total
    )

    orig_bytes = aggs.get("total_orig_bytes", {}).get("value", 0) or 0
    resp_bytes = aggs.get("total_resp_bytes", {}).get("value", 0) or 0
    orig_pkts = aggs.get("total_orig_pkts", {}).get("value", 0) or 0
    resp_pkts = aggs.get("total_resp_pkts", {}).get("value", 0) or 0

    top_protocol_buckets = aggs.get("top_protocol", {}).get("buckets", [])
    top_protocol = top_protocol_buckets[0]["key"] if top_protocol_buckets else "unknown"

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "total_bytes": orig_bytes + resp_bytes,
            "orig_bytes": orig_bytes,
            "resp_bytes": resp_bytes,
            "packet_count": orig_pkts + resp_pkts,
            "connection_count": connection_count,
            "top_protocol": top_protocol,
        }
    )


async def handle_top_talkers(request: web.Request) -> web.Response:
    """GET /api/traffic/top-talkers?from=&to=&limit=20

    Returns top source IPs by total bytes (client.bytes + server.bytes).
    """
    from_ts, to_ts = _parse_time_range(request)
    limit = _parse_int_param(request, "limit", 20)
    client = _get_client(request)

    excluded = build_excluded_ips_filter(request.app.get("excluded_ips", []))
    bool_query: dict = {
        "filter": [
            _time_range_filter(from_ts, to_ts),
            *_ZEEK_CONN_FILTERS,
        ],
    }
    if excluded:
        bool_query["must_not"] = excluded

    query = {
        "size": 0,
        "query": {"bool": bool_query},
        "aggs": {
            "top_sources": {
                "terms": {"field": "source.ip.keyword", "size": limit},
                "aggs": {
                    "total_bytes": {
                        "sum": {
                            "script": {
                                "source": "(doc['client.bytes'].size() > 0 ? doc['client.bytes'].value : 0) + (doc['server.bytes'].size() > 0 ? doc['server.bytes'].value : 0)",
                                "lang": "painless",
                            }
                        }
                    },
                    "bucket_sort": {
                        "bucket_sort": {"sort": [{"total_bytes": {"order": "desc"}}]}
                    },
                },
            }
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in traffic/top-talkers: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    buckets = result.get("aggregations", {}).get("top_sources", {}).get("buckets", [])
    talkers = [
        {
            "ip": b["key"],
            "total_bytes": b.get("total_bytes", {}).get("value", 0),
            "connection_count": b.get("doc_count", 0),
        }
        for b in buckets
    ]

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "limit": limit,
            "top_talkers": talkers,
        }
    )


async def handle_top_destinations(request: web.Request) -> web.Response:
    """GET /api/traffic/top-destinations?from=&to=&limit=20

    Returns top destination IPs by total bytes.
    """
    from_ts, to_ts = _parse_time_range(request)
    limit = _parse_int_param(request, "limit", 20)
    client = _get_client(request)

    excluded_ips = request.app.get("excluded_ips", [])
    must_not: list[dict] = []
    if excluded_ips:
        # Exclude from both source and destination for top-destinations
        must_not.append({"terms": {"destination.ip": excluded_ips}})

    bool_query: dict = {
        "filter": [
            _time_range_filter(from_ts, to_ts),
            *_ZEEK_CONN_FILTERS,
        ],
    }
    if must_not:
        bool_query["must_not"] = must_not

    query = {
        "size": 0,
        "query": {"bool": bool_query},
        "aggs": {
            "top_destinations": {
                "terms": {"field": "destination.ip.keyword", "size": limit},
                "aggs": {
                    "total_bytes": {
                        "sum": {
                            "script": {
                                "source": "(doc['client.bytes'].size() > 0 ? doc['client.bytes'].value : 0) + (doc['server.bytes'].size() > 0 ? doc['server.bytes'].value : 0)",
                                "lang": "painless",
                            }
                        }
                    },
                    "bucket_sort": {
                        "bucket_sort": {"sort": [{"total_bytes": {"order": "desc"}}]}
                    },
                },
            }
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in traffic/top-destinations: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    buckets = (
        result.get("aggregations", {}).get("top_destinations", {}).get("buckets", [])
    )
    destinations = [
        {
            "ip": b["key"],
            "total_bytes": b.get("total_bytes", {}).get("value", 0),
            "connection_count": b.get("doc_count", 0),
        }
        for b in buckets
    ]

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "limit": limit,
            "top_destinations": destinations,
        }
    )


async def handle_protocols(request: web.Request) -> web.Response:
    """GET /api/traffic/protocols?from=&to=

    Returns protocol distribution via terms aggregation on the
    'network.transport' and 'network.protocol' fields from Zeek
    connection logs in arkime_sessions3-*.
    """
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)

    query = {
        "size": 0,
        "query": {"bool": {"filter": [
            _time_range_filter(from_ts, to_ts),
            *_ZEEK_CONN_FILTERS,
        ]}},
        "aggs": {
            "by_proto": {"terms": {"field": "network.transport.keyword", "size": 50}},
            "by_service": {
                "terms": {"field": "network.protocol.keyword", "size": 50, "missing": "unknown"}
            },
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in traffic/protocols: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    aggs = result.get("aggregations", {})

    proto_buckets = aggs.get("by_proto", {}).get("buckets", [])
    service_buckets = aggs.get("by_service", {}).get("buckets", [])

    protocols = [{"name": b["key"], "count": b["doc_count"]} for b in proto_buckets]
    services = [{"name": b["key"], "count": b["doc_count"]} for b in service_buckets]

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "protocols": protocols,
            "services": services,
        }
    )


async def handle_bandwidth(request: web.Request) -> web.Response:
    """GET /api/traffic/bandwidth?from=&to=&interval=5m

    Returns time-series bandwidth data using a date_histogram on '@timestamp'
    with sum of client.bytes + server.bytes per bucket.
    """
    from_ts, to_ts = _parse_time_range(request)
    interval = request.query.get("interval", "5m")
    client = _get_client(request)

    # Validate interval format (e.g., 1m, 5m, 1h, 1d)
    valid_intervals = {"1m", "5m", "10m", "15m", "30m", "1h", "3h", "6h", "12h", "1d"}
    if interval not in valid_intervals:
        interval = "5m"

    query = {
        "size": 0,
        "query": {"bool": {"filter": [
            _time_range_filter(from_ts, to_ts),
            *_ZEEK_CONN_FILTERS,
        ]}},
        "aggs": {
            "bandwidth_over_time": {
                "date_histogram": {
                    "field": "@timestamp",
                    "fixed_interval": interval,
                    "min_doc_count": 0,
                    "extended_bounds": {
                        "min": from_ts,
                        "max": to_ts,
                    },
                },
                "aggs": {
                    "orig_bytes": {"sum": {"field": "client.bytes", "missing": 0}},
                    "resp_bytes": {"sum": {"field": "server.bytes", "missing": 0}},
                },
            }
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in traffic/bandwidth: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    buckets = (
        result.get("aggregations", {}).get("bandwidth_over_time", {}).get("buckets", [])
    )

    series = [
        {
            "timestamp": b.get("key_as_string", b.get("key")),
            "orig_bytes": b.get("orig_bytes", {}).get("value", 0) or 0,
            "resp_bytes": b.get("resp_bytes", {}).get("value", 0) or 0,
            "total_bytes": (b.get("orig_bytes", {}).get("value", 0) or 0)
            + (b.get("resp_bytes", {}).get("value", 0) or 0),
            "connections": b.get("doc_count", 0),
        }
        for b in buckets
    ]

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "interval": interval,
            "series": series,
        }
    )


async def handle_connections(request: web.Request) -> web.Response:
    """GET /api/traffic/connections?from=&to=&page=1&size=50&q=

    Returns a paginated list of Zeek connection log entries with optional
    full-text search.
    """
    from_ts, to_ts = _parse_time_range(request)
    page = _parse_int_param(request, "page", 1)
    size = min(_parse_int_param(request, "size", 50), 200)  # Cap at 200
    search_query = request.query.get("q", "").strip()
    client = _get_client(request)

    offset = (page - 1) * size

    # Build query
    must_clauses: list[dict] = []
    filter_clauses: list[dict] = [
        _time_range_filter(from_ts, to_ts),
        *_ZEEK_CONN_FILTERS,
    ]

    if search_query:
        must_clauses.append(
            {
                "query_string": {
                    "query": search_query,
                    "default_operator": "AND",
                    "analyze_wildcard": True,
                }
            }
        )

    query = {
        "size": size,
        "from": offset,
        "query": {
            "bool": {
                "must": must_clauses if must_clauses else [{"match_all": {}}],
                "filter": filter_clauses,
            }
        },
        "sort": [{"@timestamp": {"order": "desc"}}],
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in traffic/connections: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    hits = result.get("hits", {})
    total_raw = hits.get("total", {})
    total = total_raw.get("value", 0) if isinstance(total_raw, dict) else total_raw

    connections = []
    for hit in hits.get("hits", []):
        source = hit.get("_source", {})
        source["_id"] = hit.get("_id", "")
        source["_index"] = hit.get("_index", "")
        connections.append(source)

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "page": page,
            "size": size,
            "total": total,
            "total_pages": (total + size - 1) // size if size > 0 else 0,
            "connections": connections,
        }
    )


async def handle_traffic_categories(request: web.Request) -> web.Response:
    """GET /api/traffic/categories?from=&to=

    Returns traffic data grouped by human-readable categories (Streaming,
    Gaming, Social Media, etc.) using the TrafficClassifier service.
    """
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)

    try:
        categories = await get_category_stats(client, from_ts, to_ts)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in traffic/categories: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )
    except Exception as exc:
        logger.error("Error in traffic/categories: %s", exc)
        return web.json_response(
            {"error": f"Category classification failed: {exc}"}, status=500
        )

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "categories": categories,
        }
    )


async def handle_category_detail(request: web.Request) -> web.Response:
    """GET /api/traffic/categories/{category} -- per-device breakdown."""
    category = request.match_info["category"]

    if category not in traffic_classifier.CATEGORIES:
        return web.json_response({"error": f"Unknown category: {category}"}, status=404)

    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)

    fingerprint = request.app.get("device_fingerprint")

    try:
        devices, services = await asyncio.gather(
            traffic_classifier.get_category_devices(client, category, from_ts, to_ts, fingerprint=fingerprint),
            traffic_classifier.get_category_services(client, category, from_ts, to_ts),
        )
    except Exception as exc:
        logger.error("Error in category detail for %s: %s", category, exc)
        return web.json_response(
            {"error": f"Category detail query failed: {exc}"}, status=500
        )

    grand_total = sum(d["total_bytes"] for d in devices)
    for d in devices:
        d["percent"] = round((d["total_bytes"] / grand_total * 100), 1) if grand_total > 0 else 0

    return web.json_response({
        "category": category,
        "label": traffic_classifier.CATEGORIES[category],
        "device_count": len(devices),
        "total_bytes": grand_total,
        "connection_count": sum(d["connections"] for d in devices),
        "devices": devices,
        "services": services,
    })


async def handle_category_bandwidth(request: web.Request) -> web.Response:
    """GET /api/traffic/categories/{category}/bandwidth?from=&to=&interval="""
    category = request.match_info["category"]

    if category not in traffic_classifier.CATEGORIES:
        return web.json_response({"error": f"Unknown category: {category}"}, status=404)

    from_ts, to_ts = _parse_time_range(request)
    interval = request.query.get("interval", "15m")

    # Validate interval
    valid_intervals = {"1m", "5m", "10m", "15m", "30m", "1h", "3h", "6h", "12h", "1d"}
    if interval not in valid_intervals:
        interval = "15m"

    client = _get_client(request)

    try:
        series = await traffic_classifier.get_category_bandwidth(
            client, category, from_ts, to_ts, interval
        )
    except Exception as exc:
        logger.error("Error in category bandwidth for %s: %s", category, exc)
        return web.json_response(
            {"error": f"Category bandwidth query failed: {exc}"}, status=500
        )

    return web.json_response({
        "category": category,
        "from": from_ts,
        "to": to_ts,
        "interval": interval,
        "series": series,
    })


# ---------------------------------------------------------------------------
# Suricata alert filters (for cross-referencing alert sessions)
# ---------------------------------------------------------------------------

_SURICATA_ALERT_FILTERS: list[dict] = [
    {"term": {"event.provider": "suricata"}},
    {"term": {"event.dataset": "alert"}},
]

_SURICATA_NOISE_EXCLUSION: list[dict] = [
    {"prefix": {"rule.name": "SURICATA "}},
]


# ---------------------------------------------------------------------------
# Connection stats / sankey / timeline / related endpoints
# ---------------------------------------------------------------------------


def _sparkline_interval(from_ts: str, to_ts: str) -> str:
    """Pick a reasonable date_histogram interval based on the time span."""
    try:
        t0 = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
        span = (t1 - t0).total_seconds()
    except Exception:
        span = 3600
    if span <= 3600:       # ≤1h
        return "1m"
    if span <= 14400:      # ≤4h
        return "5m"
    if span <= 86400:      # ≤24h
        return "15m"
    if span <= 604800:     # ≤7d
        return "1h"
    return "6h"


async def handle_connection_stats(request: web.Request) -> web.Response:
    """GET /api/traffic/connections/stats?from=&to=

    Single multi-agg query returning: total sessions, bytes in/out,
    protocol distribution, top 10 sources, top 10 destinations (with ASN/geo),
    and alert session count.
    """
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)

    # Two parallel queries: Zeek conn stats + Suricata alert count
    conn_query = {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": {"filter": [
            _time_range_filter(from_ts, to_ts),
            *_ZEEK_CONN_FILTERS,
        ]}},
        "aggs": {
            "bytes_in": {"sum": {"field": "source.bytes", "missing": 0}},
            "bytes_out": {"sum": {"field": "destination.bytes", "missing": 0}},
            "protocols": {"terms": {"field": "network.transport.keyword", "size": 20}},
            "top_sources": {
                "terms": {"field": "source.ip.keyword", "size": 10},
                "aggs": {
                    "total_bytes": {"sum": {"script": {
                        "source": "(doc.containsKey('source.bytes') && doc['source.bytes'].size()>0 ? doc['source.bytes'].value : 0) + (doc.containsKey('destination.bytes') && doc['destination.bytes'].size()>0 ? doc['destination.bytes'].value : 0)",
                        "lang": "painless",
                    }}},
                    "bucket_sort": {"bucket_sort": {"sort": [{"total_bytes": {"order": "desc"}}]}},
                },
            },
            "top_destinations": {
                "terms": {"field": "destination.ip.keyword", "size": 10},
                "aggs": {
                    "total_bytes": {"sum": {"script": {
                        "source": "(doc.containsKey('source.bytes') && doc['source.bytes'].size()>0 ? doc['source.bytes'].value : 0) + (doc.containsKey('destination.bytes') && doc['destination.bytes'].size()>0 ? doc['destination.bytes'].value : 0)",
                        "lang": "painless",
                    }}},
                    "asn": {"terms": {"field": "destination.as.full.keyword", "size": 1}},
                    "geo": {"terms": {"field": "destination.geo.country_iso_code.keyword", "size": 1}},
                    "bucket_sort": {"bucket_sort": {"sort": [{"total_bytes": {"order": "desc"}}]}},
                },
            },
        },
    }

    alert_query = {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": {
            "filter": [
                _time_range_filter(from_ts, to_ts),
                *_SURICATA_ALERT_FILTERS,
            ],
            "must_not": _SURICATA_NOISE_EXCLUSION,
        }},
    }

    try:
        conn_result, alert_result = await asyncio.gather(
            asyncio.get_event_loop().run_in_executor(
                None, lambda: client.search(index=NETWORK_INDEX, body=conn_query)
            ),
            asyncio.get_event_loop().run_in_executor(
                None, lambda: client.search(index=NETWORK_INDEX, body=alert_query)
            ),
        )
    except OpenSearchException as exc:
        logger.error("OpenSearch error in connections/stats: %s", exc)
        return web.json_response({"error": str(exc)}, status=502)

    aggs = conn_result.get("aggregations", {})
    hits_total = conn_result.get("hits", {}).get("total", {})
    total_sessions = hits_total.get("value", 0) if isinstance(hits_total, dict) else hits_total

    bytes_in = aggs.get("bytes_in", {}).get("value", 0) or 0
    bytes_out = aggs.get("bytes_out", {}).get("value", 0) or 0

    protocols = [
        {"name": b["key"], "count": b["doc_count"]}
        for b in aggs.get("protocols", {}).get("buckets", [])
    ]

    top_sources = [
        {
            "ip": b["key"],
            "total_bytes": b.get("total_bytes", {}).get("value", 0),
            "connections": b.get("doc_count", 0),
        }
        for b in aggs.get("top_sources", {}).get("buckets", [])
    ]

    top_destinations = []
    for b in aggs.get("top_destinations", {}).get("buckets", []):
        asn_buckets = b.get("asn", {}).get("buckets", [])
        geo_buckets = b.get("geo", {}).get("buckets", [])
        top_destinations.append({
            "ip": b["key"],
            "total_bytes": b.get("total_bytes", {}).get("value", 0),
            "connections": b.get("doc_count", 0),
            "asn": asn_buckets[0]["key"] if asn_buckets else "",
            "country": geo_buckets[0]["key"] if geo_buckets else "",
        })

    alert_total = alert_result.get("hits", {}).get("total", {})
    alert_sessions = alert_total.get("value", 0) if isinstance(alert_total, dict) else alert_total

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "total_sessions": total_sessions,
        "bytes_in": bytes_in,
        "bytes_out": bytes_out,
        "alert_sessions": alert_sessions,
        "protocols": protocols,
        "top_sources": top_sources,
        "top_destinations": top_destinations,
    })


async def handle_connection_sankey(request: web.Request) -> web.Response:
    """GET /api/traffic/connections/sankey?from=&to=&limit=10

    Nested terms aggregation: source.ip → network.transport → destination.as.full.
    Flattened into {nodes, links} for Sankey visualization.
    """
    from_ts, to_ts = _parse_time_range(request)
    limit = _parse_int_param(request, "limit", 10)
    client = _get_client(request)

    query = {
        "size": 0,
        "query": {"bool": {"filter": [
            _time_range_filter(from_ts, to_ts),
            *_ZEEK_CONN_FILTERS,
        ]}},
        "aggs": {
            "by_source": {
                "terms": {"field": "source.ip.keyword", "size": limit},
                "aggs": {
                    "total_bytes": {"sum": {"script": {
                        "source": "(doc.containsKey('source.bytes') && doc['source.bytes'].size()>0 ? doc['source.bytes'].value : 0) + (doc.containsKey('destination.bytes') && doc['destination.bytes'].size()>0 ? doc['destination.bytes'].value : 0)",
                        "lang": "painless",
                    }}},
                    "by_proto": {
                        "terms": {"field": "network.transport.keyword", "size": 10},
                        "aggs": {
                            "proto_bytes": {"sum": {"script": {
                                "source": "(doc.containsKey('source.bytes') && doc['source.bytes'].size()>0 ? doc['source.bytes'].value : 0) + (doc.containsKey('destination.bytes') && doc['destination.bytes'].size()>0 ? doc['destination.bytes'].value : 0)",
                                "lang": "painless",
                            }}},
                            "by_dest": {
                                "terms": {"field": "destination.as.full.keyword", "size": limit, "missing": "Unknown"},
                                "aggs": {
                                    "dest_bytes": {"sum": {"script": {
                                        "source": "(doc.containsKey('source.bytes') && doc['source.bytes'].size()>0 ? doc['source.bytes'].value : 0) + (doc.containsKey('destination.bytes') && doc['destination.bytes'].size()>0 ? doc['destination.bytes'].value : 0)",
                                        "lang": "painless",
                                    }}},
                                    "geo": {"terms": {"field": "destination.geo.country_iso_code.keyword", "size": 1}},
                                },
                            },
                        },
                    },
                    "bucket_sort": {"bucket_sort": {"sort": [{"total_bytes": {"order": "desc"}}]}},
                },
            },
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in connections/sankey: %s", exc)
        return web.json_response({"error": str(exc)}, status=502)

    # Flatten into nodes + links
    source_nodes: list[dict] = []
    proto_set: dict[str, int] = {}  # proto → total bytes
    dest_set: dict[str, dict] = {}  # asn → {bytes, country}
    links: list[dict] = []

    for src_bucket in result.get("aggregations", {}).get("by_source", {}).get("buckets", []):
        src_ip = src_bucket["key"]
        src_bytes = src_bucket.get("total_bytes", {}).get("value", 0)
        source_nodes.append({"id": src_ip, "label": src_ip, "value": src_bytes})

        for proto_bucket in src_bucket.get("by_proto", {}).get("buckets", []):
            proto_name = proto_bucket["key"]
            proto_bytes = proto_bucket.get("proto_bytes", {}).get("value", 0)
            proto_set[proto_name] = proto_set.get(proto_name, 0) + proto_bytes

            # Link: source → protocol
            links.append({
                "source": src_ip,
                "target": proto_name,
                "value": proto_bytes,
            })

            for dest_bucket in proto_bucket.get("by_dest", {}).get("buckets", []):
                dest_name = dest_bucket["key"]
                dest_bytes = dest_bucket.get("dest_bytes", {}).get("value", 0)
                geo_buckets = dest_bucket.get("geo", {}).get("buckets", [])
                country = geo_buckets[0]["key"] if geo_buckets else ""

                if dest_name not in dest_set:
                    dest_set[dest_name] = {"bytes": 0, "country": country}
                dest_set[dest_name]["bytes"] += dest_bytes

                # Link: protocol → destination
                links.append({
                    "source": proto_name,
                    "target": dest_name,
                    "value": dest_bytes,
                })

    # Aggregate duplicate links (same source→target)
    link_map: dict[str, dict] = {}
    for link in links:
        key = f"{link['source']}→{link['target']}"
        if key in link_map:
            link_map[key]["value"] += link["value"]
        else:
            link_map[key] = dict(link)
    aggregated_links = list(link_map.values())

    protocol_nodes = [
        {"id": name, "label": name.upper(), "value": total}
        for name, total in sorted(proto_set.items(), key=lambda x: -x[1])
    ]

    destination_nodes = [
        {"id": name, "label": name, "value": info["bytes"], "country": info["country"]}
        for name, info in sorted(dest_set.items(), key=lambda x: -x[1]["bytes"])
    ][:limit]

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "nodes": {
            "sources": source_nodes,
            "protocols": protocol_nodes,
            "destinations": destination_nodes,
        },
        "links": aggregated_links,
    })


async def handle_connection_timeline(request: web.Request) -> web.Response:
    """GET /api/traffic/connections/timeline?from=&to=&interval=

    Date histogram with sub-agg on network.transport.keyword.
    Returns buckets with per-protocol session counts.
    """
    from_ts, to_ts = _parse_time_range(request)
    interval = request.query.get("interval", "")
    if not interval:
        interval = _sparkline_interval(from_ts, to_ts)
    client = _get_client(request)

    valid_intervals = {"1m", "5m", "10m", "15m", "30m", "1h", "3h", "6h", "12h", "1d"}
    if interval not in valid_intervals:
        interval = "15m"

    query = {
        "size": 0,
        "query": {"bool": {"filter": [
            _time_range_filter(from_ts, to_ts),
            *_ZEEK_CONN_FILTERS,
        ]}},
        "aggs": {
            "over_time": {
                "date_histogram": {
                    "field": "@timestamp",
                    "fixed_interval": interval,
                    "min_doc_count": 0,
                    "extended_bounds": {"min": from_ts, "max": to_ts},
                },
                "aggs": {
                    "by_proto": {"terms": {"field": "network.transport.keyword", "size": 10}},
                },
            },
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in connections/timeline: %s", exc)
        return web.json_response({"error": str(exc)}, status=502)

    buckets = result.get("aggregations", {}).get("over_time", {}).get("buckets", [])
    timeline = []
    for b in buckets:
        proto_counts: dict[str, int] = {}
        for pb in b.get("by_proto", {}).get("buckets", []):
            proto_counts[pb["key"]] = pb["doc_count"]
        timeline.append({
            "timestamp": b.get("key_as_string", b.get("key")),
            "total": b.get("doc_count", 0),
            "protocols": proto_counts,
        })

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "interval": interval,
        "buckets": timeline,
    })


async def handle_connection_related(request: web.Request) -> web.Response:
    """GET /api/traffic/connections/related?src_ip=&dst_ip=&from=&to=

    All connections between a specific src-dst pair (up to 200),
    sorted by timestamp. Includes summary stats.
    """
    from_ts, to_ts = _parse_time_range(request)
    src_ip = request.query.get("src_ip", "").strip()
    dst_ip = request.query.get("dst_ip", "").strip()
    client = _get_client(request)

    if not src_ip or not dst_ip:
        return web.json_response(
            {"error": "Both src_ip and dst_ip are required"}, status=400
        )

    # Match connections in either direction
    query = {
        "size": 200,
        "query": {"bool": {
            "filter": [
                _time_range_filter(from_ts, to_ts),
                *_ZEEK_CONN_FILTERS,
                {"bool": {"should": [
                    {"bool": {"must": [
                        {"term": {"source.ip.keyword": src_ip}},
                        {"term": {"destination.ip.keyword": dst_ip}},
                    ]}},
                    {"bool": {"must": [
                        {"term": {"source.ip.keyword": dst_ip}},
                        {"term": {"destination.ip.keyword": src_ip}},
                    ]}},
                ], "minimum_should_match": 1}},
            ],
        }},
        "sort": [{"@timestamp": {"order": "asc"}}],
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in connections/related: %s", exc)
        return web.json_response({"error": str(exc)}, status=502)

    hits = result.get("hits", {}).get("hits", [])
    connections = []
    total_bytes = 0
    protocols_seen: set[str] = set()
    first_seen = None
    last_seen = None

    for hit in hits:
        src = hit.get("_source", {})
        src["_id"] = hit.get("_id", "")
        connections.append(src)

        # Accumulate stats
        sb = src.get("source", {}).get("bytes", 0) or 0
        db = src.get("destination", {}).get("bytes", 0) or 0
        total_bytes += sb + db

        proto = src.get("network", {}).get("transport", "")
        if proto:
            protocols_seen.add(proto)

        ts = src.get("@timestamp", "")
        if ts:
            if first_seen is None or ts < first_seen:
                first_seen = ts
            if last_seen is None or ts > last_seen:
                last_seen = ts

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "total_connections": len(connections),
        "total_bytes": total_bytes,
        "protocols": sorted(protocols_seen),
        "first_seen": first_seen,
        "last_seen": last_seen,
        "connections": connections,
    })


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_traffic_routes(
    app: web.Application, storage_manager: StorageManager
) -> None:
    """Register all traffic API routes on the given aiohttp application.

    The StorageManager is expected to already be stored in app['storage']
    by create_app(). This function registers the route handlers.
    """
    app.router.add_get("/api/traffic/summary", handle_traffic_summary)
    app.router.add_get("/api/traffic/top-talkers", handle_top_talkers)
    app.router.add_get("/api/traffic/top-destinations", handle_top_destinations)
    app.router.add_get("/api/traffic/protocols", handle_protocols)
    app.router.add_get("/api/traffic/bandwidth", handle_bandwidth)
    app.router.add_get("/api/traffic/connections", handle_connections)
    app.router.add_get("/api/traffic/connections/stats", handle_connection_stats)
    app.router.add_get("/api/traffic/connections/sankey", handle_connection_sankey)
    app.router.add_get("/api/traffic/connections/timeline", handle_connection_timeline)
    app.router.add_get("/api/traffic/connections/related", handle_connection_related)
    app.router.add_get("/api/traffic/categories", handle_traffic_categories)
    app.router.add_get("/api/traffic/categories/{category}", handle_category_detail)
    app.router.add_get("/api/traffic/categories/{category}/bandwidth", handle_category_bandwidth)
    logger.info("Traffic API routes registered (13 endpoints)")
