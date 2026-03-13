"""
NetTap Device Inventory API Routes

Registers device discovery and detail endpoints with the aiohttp application.
These endpoints query OpenSearch zeek-* and suricata-* indices to provide
a network device inventory with passive fingerprinting enrichment (MAC,
hostname, manufacturer, OS hint).
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from aiohttp import web
from opensearchpy import OpenSearchException

from storage.manager import StorageManager
from services.device_fingerprint import DeviceFingerprint
from services.excluded_ips import build_excluded_ips_filter, RFC1918_SOURCE_FILTER

logger = logging.getLogger("nettap.api.devices")

# Default time range: last 24 hours
_DEFAULT_RANGE_HOURS = 24

# OLD CODE START — separate per-log-type indices replaced by unified Malcolm index
# ZEEK_CONN_INDEX = "zeek-conn-*"
# ZEEK_DNS_INDEX = "zeek-dns-*"
# SURICATA_INDEX = "suricata-*"
# OLD CODE END
NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# Maximum devices per request
_MAX_DEVICE_LIMIT = 500

# Allowed sort fields for device listing
_ALLOWED_SORT_FIELDS = {"bytes", "connections", "alerts", "last_seen", "first_seen"}


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
    """Build an OpenSearch range filter on the '@timestamp' field (ECS timestamp)."""
    return {
        "range": {
            # OLD CODE START — was "ts" (Zeek-native), now "@timestamp" (ECS)
            # "ts": {
            # OLD CODE END
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


def _get_fingerprint(request: web.Request) -> DeviceFingerprint:
    """Retrieve the DeviceFingerprint service from the app."""
    return request.app["device_fingerprint"]


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_device_list(request: web.Request) -> web.Response:
    """GET /api/devices?from=&to=&sort=bytes&order=desc&limit=100

    Returns a list of discovered devices (unique source IPs) with
    aggregated traffic stats and passive fingerprinting enrichment.
    """
    from_ts, to_ts = _parse_time_range(request)
    limit = min(_parse_int_param(request, "limit", 100), _MAX_DEVICE_LIMIT)
    sort_field = request.query.get("sort", "bytes")
    sort_order = request.query.get("order", "desc")

    if sort_field not in _ALLOWED_SORT_FIELDS:
        sort_field = "bytes"
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"

    client = _get_client(request)
    fingerprint = _get_fingerprint(request)

    # Map user-facing sort names to aggregation sort keys
    sort_map = {
        "bytes": "total_bytes",
        "connections": "_count",
        "last_seen": "last_seen",
        "first_seen": "first_seen",
        "alerts": "total_bytes",  # Alert sort handled post-query
    }
    agg_sort_key = sort_map.get(sort_field, "total_bytes")

    # Fetch more than needed if sorting by alerts (post-query sort)
    fetch_size = limit * 2 if sort_field == "alerts" else limit

    excluded = build_excluded_ips_filter(request.app.get("excluded_ips", []))
    bool_query: dict = {
        "filter": [
            _time_range_filter(from_ts, to_ts),
            {"term": {"event.provider": "zeek"}},
            {"term": {"event.dataset": "conn"}},
            request.app.get("lan_filter", RFC1918_SOURCE_FILTER),
        ],
    }
    if excluded:
        bool_query["must_not"] = excluded

    query = {
        "size": 0,
        "query": {"bool": bool_query},
        "aggs": {
            "devices": {
                "terms": {
                    "field": "source.ip.keyword",
                    "size": fetch_size,
                    "order": {agg_sort_key: sort_order},
                },
                "aggs": {
                    "total_bytes": {
                        "sum": {
                            "script": {
                                "source": "(doc['client.bytes'].size() > 0 ? doc['client.bytes'].value : 0) + (doc['server.bytes'].size() > 0 ? doc['server.bytes'].value : 0)",
                                "lang": "painless",
                            }
                        }
                    },
                    "protocols": {"terms": {"field": "network.transport.keyword", "size": 10}},
                    "first_seen": {"min": {"field": "@timestamp"}},
                    "last_seen": {"max": {"field": "@timestamp"}},
                },
            }
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in devices list: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    buckets = result.get("aggregations", {}).get("devices", {}).get("buckets", [])

    # Collect all device IPs for batch alert count query
    device_ips = [b["key"] for b in buckets]

    # Batch query: alert counts per device IP from suricata-*
    alert_counts: dict[str, int] = {}
    if device_ips:
        alert_query = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "range": {
                                "@timestamp": {
                                    "gte": from_ts,
                                    "lte": to_ts,
                                    "format": "strict_date_optional_time",
                                }
                            }
                        },
                        {"terms": {"source.ip": device_ips}},
                        {"term": {"event.provider": "suricata"}},
                        {"term": {"event.dataset": "alert"}},
                    ]
                }
            },
            "aggs": {"by_ip": {"terms": {"field": "source.ip.keyword", "size": len(device_ips)}}},
        }

        try:
            alert_result = client.search(index=NETWORK_INDEX, body=alert_query)
            for ab in (
                alert_result.get("aggregations", {}).get("by_ip", {}).get("buckets", [])
            ):
                alert_counts[ab["key"]] = ab["doc_count"]
        except OpenSearchException as exc:
            logger.warning("Alert count query failed: %s", exc)

    # Build device list with enrichment
    devices = []
    for b in buckets:
        ip = b["key"]
        total_bytes = b.get("total_bytes", {}).get("value", 0) or 0
        connection_count = b.get("doc_count", 0)
        proto_buckets = b.get("protocols", {}).get("buckets", [])
        protocols = [pb["key"] for pb in proto_buckets]
        first_seen = b.get("first_seen", {}).get("value_as_string", "")
        last_seen = b.get("last_seen", {}).get("value_as_string", "")
        alert_count = alert_counts.get(ip, 0)

        # Passive fingerprinting enrichment
        mac = fingerprint.get_mac_for_ip(client, ip, from_ts, to_ts)
        hostname = fingerprint.get_hostname_for_ip(client, ip, from_ts, to_ts)
        manufacturer = fingerprint.get_manufacturer(mac) if mac else None
        os_hint = fingerprint.get_os_hint(client, ip, from_ts, to_ts)

        devices.append(
            {
                "ip": ip,
                "mac": mac,
                "hostname": hostname,
                "manufacturer": manufacturer,
                "os_hint": os_hint,
                "first_seen": first_seen,
                "last_seen": last_seen,
                "total_bytes": total_bytes,
                "connection_count": connection_count,
                "protocols": protocols,
                "alert_count": alert_count,
            }
        )

    # Post-query sort by alerts if requested
    if sort_field == "alerts":
        devices.sort(
            key=lambda d: d["alert_count"],
            reverse=(sort_order == "desc"),
        )

    # Apply limit after post-sort
    devices = devices[:limit]

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "limit": limit,
            "devices": devices,
        }
    )


async def handle_device_detail(request: web.Request) -> web.Response:
    """GET /api/devices/{ip}

    Returns detailed information for a single device, including top
    destinations, DNS queries, and bandwidth time-series.
    """
    ip = request.match_info["ip"]
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)
    fingerprint = _get_fingerprint(request)

    # Main device aggregation query
    device_query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    _time_range_filter(from_ts, to_ts),
                    {"term": {"source.ip": ip}},
                    {"term": {"event.provider": "zeek"}},
                    {"term": {"event.dataset": "conn"}},
                ]
            }
        },
        "aggs": {
            "total_bytes": {
                "sum": {
                    "script": {
                        "source": "(doc['client.bytes'].size() > 0 ? doc['client.bytes'].value : 0) + (doc['server.bytes'].size() > 0 ? doc['server.bytes'].value : 0)",
                        "lang": "painless",
                    }
                }
            },
            "protocols": {"terms": {"field": "network.transport.keyword", "size": 10}},
            "first_seen": {"min": {"field": "@timestamp"}},
            "last_seen": {"max": {"field": "@timestamp"}},
            "top_destinations": {
                "terms": {"field": "destination.ip.keyword", "size": 20},
                "aggs": {
                    "bytes": {
                        "sum": {
                            "script": {
                                "source": "(doc['client.bytes'].size() > 0 ? doc['client.bytes'].value : 0) + (doc['server.bytes'].size() > 0 ? doc['server.bytes'].value : 0)",
                                "lang": "painless",
                            }
                        }
                    },
                },
            },
            "bandwidth_series": {
                "date_histogram": {
                    "field": "@timestamp",
                    "fixed_interval": "5m",
                    "min_doc_count": 0,
                    "extended_bounds": {
                        "min": from_ts,
                        "max": to_ts,
                    },
                },
                "aggs": {
                    "bytes": {
                        "sum": {
                            "script": {
                                "source": "(doc['client.bytes'].size() > 0 ? doc['client.bytes'].value : 0) + (doc['server.bytes'].size() > 0 ? doc['server.bytes'].value : 0)",
                                "lang": "painless",
                            }
                        }
                    },
                },
            },
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=device_query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in device detail: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    aggs = result.get("aggregations", {})
    hits_total = result.get("hits", {}).get("total", {})
    connection_count = (
        hits_total.get("value", 0) if isinstance(hits_total, dict) else hits_total
    )

    total_bytes = aggs.get("total_bytes", {}).get("value", 0) or 0
    first_seen = aggs.get("first_seen", {}).get("value_as_string", "")
    last_seen = aggs.get("last_seen", {}).get("value_as_string", "")
    proto_buckets = aggs.get("protocols", {}).get("buckets", [])
    protocols = [pb["key"] for pb in proto_buckets]

    # Top destinations
    dest_buckets = aggs.get("top_destinations", {}).get("buckets", [])
    top_destinations = [
        {
            "ip": db["key"],
            "bytes": db.get("bytes", {}).get("value", 0) or 0,
            "connections": db.get("doc_count", 0),
        }
        for db in dest_buckets
    ]

    # Bandwidth series
    bw_buckets = aggs.get("bandwidth_series", {}).get("buckets", [])
    bandwidth_series = [
        {
            "timestamp": bwb.get("key_as_string", bwb.get("key")),
            "bytes": bwb.get("bytes", {}).get("value", 0) or 0,
        }
        for bwb in bw_buckets
    ]

    # DNS queries from unified index (zeek dns events)
    dns_query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    _time_range_filter(from_ts, to_ts),
                    {"term": {"source.ip": ip}},
                    {"term": {"event.provider": "zeek"}},
                    {"term": {"event.dataset": "dns"}},
                ]
            }
        },
        "aggs": {"dns_queries": {"terms": {"field": "zeek.dns.query.keyword", "size": 50}}},
    }

    dns_queries = []
    try:
        dns_result = client.search(index=NETWORK_INDEX, body=dns_query)
        dns_buckets = (
            dns_result.get("aggregations", {}).get("dns_queries", {}).get("buckets", [])
        )
        dns_queries = [
            {"domain": db["key"], "count": db["doc_count"]} for db in dns_buckets
        ]
    except OpenSearchException as exc:
        logger.warning("DNS query lookup failed for %s: %s", ip, exc)

    # Alert count from unified index (suricata alert events)
    alert_query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {
                        "range": {
                            "@timestamp": {
                                "gte": from_ts,
                                "lte": to_ts,
                                "format": "strict_date_optional_time",
                            }
                        }
                    },
                    {"term": {"source.ip": ip}},
                    {"term": {"event.provider": "suricata"}},
                    {"term": {"event.dataset": "alert"}},
                ]
            }
        },
    }

    alert_count = 0
    try:
        alert_result = client.search(index=NETWORK_INDEX, body=alert_query)
        alert_total = alert_result.get("hits", {}).get("total", {})
        alert_count = (
            alert_total.get("value", 0)
            if isinstance(alert_total, dict)
            else alert_total
        )
    except OpenSearchException as exc:
        logger.warning("Alert count lookup failed for %s: %s", ip, exc)

    # Passive fingerprinting enrichment
    mac = fingerprint.get_mac_for_ip(client, ip, from_ts, to_ts)
    hostname = fingerprint.get_hostname_for_ip(client, ip, from_ts, to_ts)
    manufacturer = fingerprint.get_manufacturer(mac) if mac else None
    os_hint = fingerprint.get_os_hint(client, ip, from_ts, to_ts)

    return web.json_response(
        {
            "device": {
                "ip": ip,
                "mac": mac,
                "hostname": hostname,
                "manufacturer": manufacturer,
                "os_hint": os_hint,
                "first_seen": first_seen,
                "last_seen": last_seen,
                "total_bytes": total_bytes,
                "connection_count": connection_count,
                "protocols": protocols,
                "alert_count": alert_count,
                "top_destinations": top_destinations,
                "dns_queries": dns_queries,
                "bandwidth_series": bandwidth_series,
            }
        }
    )


async def handle_device_connections(request: web.Request) -> web.Response:
    """GET /api/devices/{ip}/connections?page=1&size=50&from=&to=

    Returns paginated connection logs for a specific device IP, where the
    device appears as either source or destination.
    """
    ip = request.match_info["ip"]
    from_ts, to_ts = _parse_time_range(request)
    page = _parse_int_param(request, "page", 1)
    size = min(_parse_int_param(request, "size", 50), 200)  # Cap at 200
    client = _get_client(request)

    offset = (page - 1) * size

    query = {
        "size": size,
        "from": offset,
        "query": {
            "bool": {
                "filter": [
                    _time_range_filter(from_ts, to_ts),
                    {
                        "bool": {
                            "should": [
                                {"term": {"source.ip": ip}},
                                {"term": {"destination.ip": ip}},
                            ],
                            "minimum_should_match": 1,
                        }
                    },
                    {"term": {"event.provider": "zeek"}},
                    {"term": {"event.dataset": "conn"}},
                ]
            }
        },
        "sort": [{"@timestamp": {"order": "desc"}}],
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in device connections: %s", exc)
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
            "ip": ip,
            "page": page,
            "size": size,
            "total": total,
            "total_pages": (total + size - 1) // size if size > 0 else 0,
            "connections": connections,
        }
    )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


async def handle_device_count(request: web.Request) -> web.Response:
    """GET /api/devices/count?from=&to=

    Returns the count of unique DHCP-leased devices (unique client IPs
    seen in Zeek DHCP logs). This is more accurate than counting all
    unique source IPs from conn logs, which includes stale/unleased IPs.
    """
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)

    query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    _time_range_filter(from_ts, to_ts),
                    {"term": {"event.provider": "zeek"}},
                    {"term": {"event.dataset": "dhcp"}},
                ]
            }
        },
        "aggs": {
            "unique_devices": {
                "cardinality": {"field": "zeek.dhcp.assigned_ip"}
            }
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in devices/count: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    aggs = result.get("aggregations", {})
    count = aggs.get("unique_devices", {}).get("value", 0)

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "count": count,
    })


def register_device_routes(
    app: web.Application, storage_manager: StorageManager
) -> None:
    """Register all device inventory API routes on the given aiohttp application.

    Creates and stores a DeviceFingerprint instance on the app for use
    by the route handlers.
    """
    # Create fingerprint service and store on app
    app["device_fingerprint"] = DeviceFingerprint()

    app.router.add_get("/api/devices/count", handle_device_count)
    app.router.add_get("/api/devices", handle_device_list)
    app.router.add_get("/api/devices/{ip}", handle_device_detail)
    app.router.add_get("/api/devices/{ip}/connections", handle_device_connections)
    logger.info("Device API routes registered (4 endpoints)")
