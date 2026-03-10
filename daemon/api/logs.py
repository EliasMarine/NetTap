"""
NetTap Log Search API Routes

Generic log browser for Zeek and Suricata logs stored in OpenSearch.
Supports filtering by log type, full-text search, time range,
field projection, sorting, and cursor-based pagination.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from aiohttp import web
from opensearchpy import OpenSearchException

from storage.manager import StorageManager

logger = logging.getLogger("nettap.api.logs")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# Log type -> OpenSearch filter mapping
LOG_TYPE_FILTERS = {
    "zeek.conn": [{"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "conn"}}],
    "zeek.dns": [{"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "dns"}}],
    "zeek.http": [{"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "http"}}],
    "zeek.tls": [{"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "ssl"}}],
    "zeek.files": [{"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "files"}}],
    "zeek.dhcp": [{"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "dhcp"}}],
    "zeek.smtp": [{"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "smtp"}}],
    "suricata": [{"term": {"event.provider": "suricata"}}, {"term": {"event.dataset": "alert"}}],
}

# Field definitions per log type (name, type, description, example)
FIELD_DEFINITIONS = {
    "zeek.conn": [
        {"name": "@timestamp", "type": "date", "description": "When the connection was observed", "example": "2026-03-05T12:34:56Z"},
        {"name": "source.ip", "type": "ip", "description": "IP address that initiated the connection", "example": "192.168.1.100"},
        {"name": "source.port", "type": "integer", "description": "Port used by the source", "example": "52341"},
        {"name": "destination.ip", "type": "ip", "description": "IP address that received the connection", "example": "8.8.8.8"},
        {"name": "destination.port", "type": "integer", "description": "Port on the destination (e.g. 443 = HTTPS)", "example": "443"},
        {"name": "network.transport", "type": "keyword", "description": "Transport protocol (tcp, udp, icmp)", "example": "tcp"},
        {"name": "network.protocol", "type": "keyword", "description": "Application protocol detected by Zeek", "example": "ssl"},
        {"name": "event.duration", "type": "float", "description": "How long the connection lasted (seconds)", "example": "1.234"},
        {"name": "source.bytes", "type": "long", "description": "Bytes sent by the source", "example": "1024"},
        {"name": "destination.bytes", "type": "long", "description": "Bytes sent by the destination", "example": "2048"},
        {"name": "zeek.conn.state", "type": "keyword", "description": "Connection state (S1=established, SF=finished, REJ=rejected)", "example": "SF"},
        {"name": "zeek.conn.history", "type": "keyword", "description": "Connection history string (ShADFf = SYN/ACK/DATA/FIN)", "example": "ShADFf"},
    ],
    "zeek.dns": [
        {"name": "@timestamp", "type": "date", "description": "When the DNS query was observed", "example": "2026-03-05T12:34:56Z"},
        {"name": "source.ip", "type": "ip", "description": "Device that made the DNS query", "example": "192.168.1.100"},
        {"name": "destination.ip", "type": "ip", "description": "DNS server that answered", "example": "8.8.8.8"},
        {"name": "zeek.dns.query", "type": "keyword", "description": "Domain name that was looked up", "example": "www.google.com"},
        {"name": "zeek.dns.qtype_name", "type": "keyword", "description": "DNS record type (A=IPv4, AAAA=IPv6, CNAME=alias)", "example": "A"},
        {"name": "zeek.dns.rcode_name", "type": "keyword", "description": "Response code (NOERROR=success, NXDOMAIN=not found)", "example": "NOERROR"},
        {"name": "zeek.dns.answers", "type": "keyword", "description": "IP addresses returned in the DNS response", "example": "142.250.80.46"},
        {"name": "zeek.dns.rejected", "type": "boolean", "description": "Whether the query was rejected", "example": "false"},
    ],
    "zeek.http": [
        {"name": "@timestamp", "type": "date", "description": "When the HTTP request was observed", "example": "2026-03-05T12:34:56Z"},
        {"name": "source.ip", "type": "ip", "description": "Device that made the HTTP request", "example": "192.168.1.100"},
        {"name": "destination.ip", "type": "ip", "description": "Web server that responded", "example": "93.184.216.34"},
        {"name": "zeek.http.method", "type": "keyword", "description": "HTTP method (GET, POST, PUT, etc.)", "example": "GET"},
        {"name": "zeek.http.host", "type": "keyword", "description": "Website hostname from the Host header", "example": "www.example.com"},
        {"name": "zeek.http.uri", "type": "keyword", "description": "URL path requested", "example": "/api/data"},
        {"name": "zeek.http.status_code", "type": "integer", "description": "HTTP response code (200=OK, 404=not found, 500=error)", "example": "200"},
        {"name": "zeek.http.user_agent", "type": "keyword", "description": "Browser or app that made the request", "example": "Mozilla/5.0..."},
        {"name": "zeek.http.resp_mime_types", "type": "keyword", "description": "Content type of the response", "example": "text/html"},
    ],
    "zeek.tls": [
        {"name": "@timestamp", "type": "date", "description": "When the TLS handshake was observed", "example": "2026-03-05T12:34:56Z"},
        {"name": "source.ip", "type": "ip", "description": "Device that initiated the TLS connection", "example": "192.168.1.100"},
        {"name": "destination.ip", "type": "ip", "description": "Server that accepted the TLS connection", "example": "93.184.216.34"},
        {"name": "zeek.tls.version", "type": "keyword", "description": "TLS version used (TLSv1.3 is current best)", "example": "TLSv13"},
        {"name": "zeek.tls.server_name", "type": "keyword", "description": "Server Name Indication — the domain being connected to", "example": "www.google.com"},
        {"name": "zeek.tls.cipher", "type": "keyword", "description": "Encryption cipher suite negotiated", "example": "TLS_AES_256_GCM_SHA384"},
        {"name": "zeek.tls.established", "type": "boolean", "description": "Whether the TLS handshake completed successfully", "example": "true"},
        {"name": "zeek.tls.subject", "type": "keyword", "description": "Certificate subject (who the cert was issued to)", "example": "CN=www.google.com"},
        {"name": "zeek.tls.issuer", "type": "keyword", "description": "Certificate Authority that issued the cert", "example": "CN=GTS CA 1C3,O=Google Trust Services LLC"},
    ],
    "zeek.files": [
        {"name": "@timestamp", "type": "date", "description": "When the file transfer was observed", "example": "2026-03-05T12:34:56Z"},
        {"name": "source.ip", "type": "ip", "description": "Device that sent the file", "example": "93.184.216.34"},
        {"name": "destination.ip", "type": "ip", "description": "Device that received the file", "example": "192.168.1.100"},
        {"name": "zeek.files.filename", "type": "keyword", "description": "Name of the file transferred", "example": "document.pdf"},
        {"name": "zeek.files.mime_type", "type": "keyword", "description": "File content type", "example": "application/pdf"},
        {"name": "zeek.files.total_bytes", "type": "long", "description": "Size of the file in bytes", "example": "102400"},
        {"name": "zeek.files.md5", "type": "keyword", "description": "MD5 hash of the file (for identification)", "example": "d41d8cd98f00b204e9800998ecf8427e"},
        {"name": "zeek.files.sha1", "type": "keyword", "description": "SHA1 hash of the file", "example": "da39a3ee5e6b4b0d3255bfef95601890afd80709"},
    ],
    "zeek.dhcp": [
        {"name": "@timestamp", "type": "date", "description": "When the DHCP transaction was observed", "example": "2026-03-05T12:34:56Z"},
        {"name": "source.ip", "type": "ip", "description": "Device requesting an IP address", "example": "0.0.0.0"},
        {"name": "zeek.dhcp.client_addr", "type": "ip", "description": "IP address assigned to the device", "example": "192.168.1.100"},
        {"name": "zeek.dhcp.mac", "type": "keyword", "description": "MAC address of the requesting device", "example": "aa:bb:cc:dd:ee:ff"},
        {"name": "zeek.dhcp.hostname", "type": "keyword", "description": "Hostname the device reported", "example": "johns-iphone"},
        {"name": "zeek.dhcp.msg_types", "type": "keyword", "description": "DHCP message type (DISCOVER, OFFER, REQUEST, ACK)", "example": "ACK"},
        {"name": "zeek.dhcp.lease_time", "type": "long", "description": "Lease duration in seconds", "example": "86400"},
    ],
    "zeek.smtp": [
        {"name": "@timestamp", "type": "date", "description": "When the email transaction was observed", "example": "2026-03-05T12:34:56Z"},
        {"name": "source.ip", "type": "ip", "description": "Device sending the email", "example": "192.168.1.100"},
        {"name": "destination.ip", "type": "ip", "description": "Mail server receiving the email", "example": "74.125.133.26"},
        {"name": "zeek.smtp.mailfrom", "type": "keyword", "description": "Sender email address", "example": "user@example.com"},
        {"name": "zeek.smtp.rcptto", "type": "keyword", "description": "Recipient email address(es)", "example": "recipient@example.com"},
        {"name": "zeek.smtp.subject", "type": "keyword", "description": "Email subject line", "example": "Meeting tomorrow"},
        {"name": "zeek.smtp.tls", "type": "boolean", "description": "Whether TLS encryption was used", "example": "true"},
    ],
    "suricata": [
        {"name": "@timestamp", "type": "date", "description": "When the alert was triggered", "example": "2026-03-05T12:34:56Z"},
        {"name": "source.ip", "type": "ip", "description": "Source IP that triggered the alert", "example": "192.168.1.100"},
        {"name": "destination.ip", "type": "ip", "description": "Destination IP involved in the alert", "example": "45.33.32.156"},
        {"name": "suricata.alert.signature", "type": "keyword", "description": "Name of the IDS rule that matched", "example": "ET SCAN Potential SSH Scan"},
        {"name": "suricata.alert.signature_id", "type": "integer", "description": "Unique rule ID (SID) from the Suricata ruleset", "example": "2001219"},
        {"name": "suricata.alert.severity", "type": "integer", "description": "Severity level (1=high, 2=medium, 3=low)", "example": "2"},
        {"name": "suricata.alert.category", "type": "keyword", "description": "Alert category grouping", "example": "Attempted Information Leak"},
        {"name": "network.transport", "type": "keyword", "description": "Transport protocol (tcp, udp, icmp)", "example": "tcp"},
    ],
}

_DEFAULT_RANGE_HOURS = 24
_MAX_SIZE = 500
_DEFAULT_SIZE = 50

_ALLOWED_INTERVALS = {"1m", "5m", "10m", "15m", "30m", "1h", "6h", "12h", "1d"}

_LOG_TYPE_LABELS = {
    "conn": "Connections", "dns": "DNS", "http": "HTTP", "ssl": "TLS",
    "files": "Files", "dhcp": "DHCP", "smtp": "SMTP", "alert": "Suricata",
}


def _parse_time_range(request: web.Request) -> tuple[str, str]:
    """Parse and validate from/to time range from query params."""
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


async def handle_log_search(request: web.Request) -> web.Response:
    """GET /api/logs/search — Generic log search across Zeek/Suricata indices."""
    storage: StorageManager = request.app["storage"]
    from_ts, to_ts = _parse_time_range(request)

    log_type = request.query.get("log_type", "")
    query_str = request.query.get("query", "")
    fields = request.query.get("fields", "")
    size = min(int(request.query.get("size", str(_DEFAULT_SIZE))), _MAX_SIZE)
    sort_param = request.query.get("sort", "@timestamp:desc")
    search_after = request.query.get("search_after", "")

    # Build query
    filters = [{"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}}]

    if log_type and log_type in LOG_TYPE_FILTERS:
        filters.extend(LOG_TYPE_FILTERS[log_type])

    must = []
    if query_str:
        must.append({"query_string": {"query": query_str, "default_operator": "AND"}})

    body: dict = {
        "query": {"bool": {"must": must if must else [{"match_all": {}}], "filter": filters}},
        "size": size,
        "sort": [],
    }

    # Sort — auto-add .keyword suffix for text fields that need it.
    # Fields like @timestamp, _id, and numeric fields don't need it.
    _NO_KEYWORD_PREFIXES = ("@", "_", "event.", "client.", "server.", "network.")
    for part in sort_param.split(","):
        if ":" in part:
            field, order = part.split(":", 1)
        else:
            field, order = part, "desc"
        # Add .keyword for text fields (zeek.*, suricata.*, source.*, destination.*)
        # unless they already have .keyword or are known non-text fields
        if (
            not field.startswith(_NO_KEYWORD_PREFIXES)
            and not field.endswith(".keyword")
            and "." in field
            and field not in ("source.port", "destination.port")
        ):
            field = f"{field}.keyword"
        body["sort"].append({field: {"order": order}})
    # Always add _id tiebreaker for cursor pagination
    if not any("_id" in s for s in body["sort"]):
        body["sort"].append({"_id": {"order": "desc"}})

    # Cursor pagination
    if search_after:
        try:
            body["search_after"] = json.loads(search_after)
        except (json.JSONDecodeError, ValueError):
            pass

    # Field projection
    if fields:
        body["_source"] = [f.strip() for f in fields.split(",")]

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: storage._client.search(index=NETWORK_INDEX, body=body)
        )

        hits = result.get("hits", {})
        documents = []
        last_sort = None
        for hit in hits.get("hits", []):
            documents.append({
                "_id": hit.get("_id"),
                "_index": hit.get("_index"),
                "_source": hit.get("_source", {}),
            })
            last_sort = hit.get("sort")

        return web.json_response({
            "hits": documents,
            "total": hits.get("total", {}).get("value", 0),
            "search_after": last_sort,
            "size": size,
            "log_type": log_type or "all",
        })
    except OpenSearchException as exc:
        logger.exception("Log search failed")
        return web.json_response({"error": f"Search failed: {exc}"}, status=500)


async def handle_log_fields(request: web.Request) -> web.Response:
    """GET /api/logs/fields/{log_type} — Return field definitions for a log type."""
    log_type = request.match_info.get("log_type", "")

    if log_type not in FIELD_DEFINITIONS:
        return web.json_response(
            {"error": f"Unknown log type: {log_type}", "available": list(FIELD_DEFINITIONS.keys())},
            status=400,
        )

    return web.json_response({"log_type": log_type, "fields": FIELD_DEFINITIONS[log_type]})


async def handle_log_stats(request: web.Request) -> web.Response:
    """GET /api/logs/stats — Aggregate statistics for the log explorer."""
    storage: StorageManager = request.app["storage"]
    from_ts, to_ts = _parse_time_range(request)

    body: dict = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [{"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}}]
            }
        },
        "aggs": {
            "unique_sources": {"cardinality": {"field": "source.ip"}},
            "protocol_count": {"cardinality": {"field": "event.dataset"}},
            "src_bytes": {"sum": {"field": "source.bytes"}},
            "dst_bytes": {"sum": {"field": "destination.bytes"}},
        },
    }

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: storage._client.search(index=NETWORK_INDEX, body=body)
        )

        aggs = result.get("aggregations", {})
        total_events = result.get("hits", {}).get("total", {}).get("value", 0)
        total_bytes = (
            aggs.get("src_bytes", {}).get("value", 0)
            + aggs.get("dst_bytes", {}).get("value", 0)
        )

        return web.json_response({
            "from": from_ts,
            "to": to_ts,
            "total_events": total_events,
            "unique_sources": aggs.get("unique_sources", {}).get("value", 0),
            "protocol_count": aggs.get("protocol_count", {}).get("value", 0),
            "total_bytes": total_bytes,
        })
    except OpenSearchException as exc:
        logger.exception("Log stats query failed")
        return web.json_response({"error": f"Stats query failed: {exc}"}, status=502)


async def handle_log_timeline(request: web.Request) -> web.Response:
    """GET /api/logs/timeline — Time-series event counts by log type."""
    storage: StorageManager = request.app["storage"]
    from_ts, to_ts = _parse_time_range(request)

    interval = request.query.get("interval", "1h")
    if interval not in _ALLOWED_INTERVALS:
        interval = "1h"

    body: dict = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [{"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}}]
            }
        },
        "aggs": {
            "timeline": {
                "date_histogram": {
                    "field": "@timestamp",
                    "fixed_interval": interval,
                },
                "aggs": {
                    "by_type": {"terms": {"field": "event.dataset", "size": 20}},
                },
            }
        },
    }

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: storage._client.search(index=NETWORK_INDEX, body=body)
        )

        raw_buckets = result.get("aggregations", {}).get("timeline", {}).get("buckets", [])
        buckets = []
        for b in raw_buckets:
            entry: dict = {
                "timestamp": b.get("key_as_string", b.get("key")),
                "total": b.get("doc_count", 0),
            }
            type_buckets = {tb["key"]: tb["doc_count"] for tb in b.get("by_type", {}).get("buckets", [])}
            for key in _LOG_TYPE_LABELS:
                entry[key] = type_buckets.get(key, 0)
            buckets.append(entry)

        return web.json_response({
            "from": from_ts,
            "to": to_ts,
            "interval": interval,
            "buckets": buckets,
        })
    except OpenSearchException as exc:
        logger.exception("Log timeline query failed")
        return web.json_response({"error": f"Timeline query failed: {exc}"}, status=502)


async def handle_log_top_talkers(request: web.Request) -> web.Response:
    """GET /api/logs/top-talkers — Top source IPs by event count."""
    storage: StorageManager = request.app["storage"]
    from_ts, to_ts = _parse_time_range(request)

    limit = min(int(request.query.get("limit", "10")), 50)

    body: dict = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [{"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}}]
            }
        },
        "aggs": {
            "top_sources": {"terms": {"field": "source.ip", "size": limit}},
        },
    }

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: storage._client.search(index=NETWORK_INDEX, body=body)
        )

        raw = result.get("aggregations", {}).get("top_sources", {}).get("buckets", [])
        talkers = [{"ip": b["key"], "count": b["doc_count"]} for b in raw]

        return web.json_response({
            "from": from_ts,
            "to": to_ts,
            "talkers": talkers,
        })
    except OpenSearchException as exc:
        logger.exception("Top talkers query failed")
        return web.json_response({"error": f"Top talkers query failed: {exc}"}, status=502)


async def handle_log_protocol_breakdown(request: web.Request) -> web.Response:
    """GET /api/logs/protocol-breakdown — Event counts by protocol/dataset."""
    storage: StorageManager = request.app["storage"]
    from_ts, to_ts = _parse_time_range(request)

    body: dict = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [{"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}}]
            }
        },
        "aggs": {
            "protocols": {"terms": {"field": "event.dataset", "size": 20}},
        },
    }

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: storage._client.search(index=NETWORK_INDEX, body=body)
        )

        raw = result.get("aggregations", {}).get("protocols", {}).get("buckets", [])
        protocols = [
            {
                "protocol": b["key"],
                "label": _LOG_TYPE_LABELS.get(b["key"], b["key"]),
                "count": b["doc_count"],
            }
            for b in raw
        ]

        return web.json_response({
            "from": from_ts,
            "to": to_ts,
            "protocols": protocols,
        })
    except OpenSearchException as exc:
        logger.exception("Protocol breakdown query failed")
        return web.json_response({"error": f"Protocol breakdown query failed: {exc}"}, status=502)


async def handle_log_top_destinations(request: web.Request) -> web.Response:
    """GET /api/logs/top-destinations — Top destination IPs by event count."""
    storage: StorageManager = request.app["storage"]
    from_ts, to_ts = _parse_time_range(request)

    limit = min(int(request.query.get("limit", "10")), 50)

    body: dict = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [{"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}}]
            }
        },
        "aggs": {
            "top_destinations": {"terms": {"field": "destination.ip", "size": limit}},
        },
    }

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: storage._client.search(index=NETWORK_INDEX, body=body)
        )

        raw = result.get("aggregations", {}).get("top_destinations", {}).get("buckets", [])
        destinations = [{"ip": b["key"], "count": b["doc_count"]} for b in raw]

        return web.json_response({
            "from": from_ts,
            "to": to_ts,
            "destinations": destinations,
        })
    except OpenSearchException as exc:
        logger.exception("Top destinations query failed")
        return web.json_response({"error": f"Top destinations query failed: {exc}"}, status=502)


async def handle_log_top_dns(request: web.Request) -> web.Response:
    """GET /api/logs/top-dns — Top DNS queries by frequency."""
    storage: StorageManager = request.app["storage"]
    from_ts, to_ts = _parse_time_range(request)

    limit = min(int(request.query.get("limit", "10")), 50)

    body: dict = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
                    {"term": {"event.provider": "zeek"}},
                    {"term": {"event.dataset": "dns"}},
                ],
            }
        },
        "aggs": {
            "top_queries": {"terms": {"field": "zeek.dns.query.keyword", "size": limit}},
        },
    }

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: storage._client.search(index=NETWORK_INDEX, body=body)
        )

        raw = result.get("aggregations", {}).get("top_queries", {}).get("buckets", [])
        queries = [{"domain": b["key"], "count": b["doc_count"]} for b in raw]

        return web.json_response({
            "from": from_ts,
            "to": to_ts,
            "queries": queries,
        })
    except OpenSearchException as exc:
        logger.exception("Top DNS query failed")
        return web.json_response({"error": f"Top DNS query failed: {exc}"}, status=502)


def register_log_routes(app: web.Application, storage: StorageManager) -> None:
    app["storage"] = storage
    app.router.add_get("/api/logs/search", handle_log_search)
    app.router.add_get("/api/logs/stats", handle_log_stats)
    app.router.add_get("/api/logs/timeline", handle_log_timeline)
    app.router.add_get("/api/logs/top-talkers", handle_log_top_talkers)
    app.router.add_get("/api/logs/protocol-breakdown", handle_log_protocol_breakdown)
    app.router.add_get("/api/logs/top-destinations", handle_log_top_destinations)
    app.router.add_get("/api/logs/top-dns", handle_log_top_dns)
    app.router.add_get("/api/logs/fields/{log_type}", handle_log_fields)
    logger.info("Log search API routes registered (8 endpoints)")
