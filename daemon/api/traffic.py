"""
NetTap Traffic API Routes

Registers traffic analysis endpoints with the aiohttp application.
These endpoints query OpenSearch zeek-* indices to provide network traffic
summaries, top talkers, protocol distributions, bandwidth time-series,
and paginated connection listings.
"""

import logging
from datetime import datetime, timedelta, timezone

from aiohttp import web
from opensearchpy import OpenSearchException

from services.traffic_classifier import get_category_stats
from storage.manager import StorageManager

logger = logging.getLogger("nettap.api.traffic")

# Default time range: last 24 hours
_DEFAULT_RANGE_HOURS = 24

# Zeek connection indices
ZEEK_INDEX = "zeek-*"


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
    """Build an OpenSearch range filter on the 'ts' field (Zeek timestamp)."""
    return {
        "range": {
            "ts": {
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
    for the given time range from zeek-* indices.
    """
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)

    query = {
        "size": 0,
        "query": {"bool": {"filter": [_time_range_filter(from_ts, to_ts)]}},
        "aggs": {
            "total_orig_bytes": {"sum": {"field": "orig_bytes", "missing": 0}},
            "total_resp_bytes": {"sum": {"field": "resp_bytes", "missing": 0}},
            "total_orig_pkts": {"sum": {"field": "orig_pkts", "missing": 0}},
            "total_resp_pkts": {"sum": {"field": "resp_pkts", "missing": 0}},
            "top_protocol": {"terms": {"field": "proto", "size": 1}},
        },
    }

    try:
        result = client.search(index=ZEEK_INDEX, body=query)
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

    Returns top source IPs by total bytes (orig_bytes + resp_bytes).
    """
    from_ts, to_ts = _parse_time_range(request)
    limit = _parse_int_param(request, "limit", 20)
    client = _get_client(request)

    query = {
        "size": 0,
        "query": {"bool": {"filter": [_time_range_filter(from_ts, to_ts)]}},
        "aggs": {
            "top_sources": {
                "terms": {"field": "id.orig_h", "size": limit},
                "aggs": {
                    "total_bytes": {
                        "sum": {
                            "script": {
                                "source": "(doc['orig_bytes'].size() > 0 ? doc['orig_bytes'].value : 0) + (doc['resp_bytes'].size() > 0 ? doc['resp_bytes'].value : 0)",
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
        result = client.search(index=ZEEK_INDEX, body=query)
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

    query = {
        "size": 0,
        "query": {"bool": {"filter": [_time_range_filter(from_ts, to_ts)]}},
        "aggs": {
            "top_destinations": {
                "terms": {"field": "id.resp_h", "size": limit},
                "aggs": {
                    "total_bytes": {
                        "sum": {
                            "script": {
                                "source": "(doc['orig_bytes'].size() > 0 ? doc['orig_bytes'].value : 0) + (doc['resp_bytes'].size() > 0 ? doc['resp_bytes'].value : 0)",
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
        result = client.search(index=ZEEK_INDEX, body=query)
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

    Returns protocol distribution via terms aggregation on the 'proto'
    and 'service' fields from zeek connection logs.
    """
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)

    query = {
        "size": 0,
        "query": {"bool": {"filter": [_time_range_filter(from_ts, to_ts)]}},
        "aggs": {
            "by_proto": {"terms": {"field": "proto", "size": 50}},
            "by_service": {
                "terms": {"field": "service", "size": 50, "missing": "unknown"}
            },
        },
    }

    try:
        result = client.search(index=ZEEK_INDEX, body=query)
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

    Returns time-series bandwidth data using a date_histogram on 'ts'
    with sum of orig_bytes + resp_bytes per bucket.
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
        "query": {"bool": {"filter": [_time_range_filter(from_ts, to_ts)]}},
        "aggs": {
            "bandwidth_over_time": {
                "date_histogram": {
                    "field": "ts",
                    "fixed_interval": interval,
                    "min_doc_count": 0,
                    "extended_bounds": {
                        "min": from_ts,
                        "max": to_ts,
                    },
                },
                "aggs": {
                    "orig_bytes": {"sum": {"field": "orig_bytes", "missing": 0}},
                    "resp_bytes": {"sum": {"field": "resp_bytes", "missing": 0}},
                },
            }
        },
    }

    try:
        result = client.search(index=ZEEK_INDEX, body=query)
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
    filter_clauses: list[dict] = [_time_range_filter(from_ts, to_ts)]

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
        "sort": [{"ts": {"order": "desc"}}],
    }

    try:
        result = client.search(index=ZEEK_INDEX, body=query)
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
    app.router.add_get("/api/traffic/categories", handle_traffic_categories)
    logger.info("Traffic API routes registered (7 endpoints)")
