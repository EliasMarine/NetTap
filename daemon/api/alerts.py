"""
NetTap Alert API Routes

Registers Suricata alert endpoints with the aiohttp application.
These endpoints query OpenSearch suricata-* indices to provide paginated
alert listings, severity counts, individual alert details, and
acknowledgement tracking.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiohttp import web
from opensearchpy import OpenSearchException

from services.alert_enrichment import AlertEnrichment
from storage.manager import StorageManager

logger = logging.getLogger("nettap.api.alerts")

# Module-level enrichment instance (loaded once, reused across requests)
_alert_enrichment = AlertEnrichment()

# Default time range: last 24 hours
_DEFAULT_RANGE_HOURS = 24

# Suricata alert indices
SURICATA_INDEX = "suricata-*"

# Path for storing acknowledgement data (local JSON file)
_ACK_FILE = os.environ.get(
    "ALERT_ACK_FILE", "/opt/nettap/data/alert_acks.json"
)


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
    """Build an OpenSearch range filter on the 'timestamp' field (Suricata)."""
    return {
        "range": {
            "timestamp": {
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

    filter_clauses: list[dict] = [_time_range_filter(from_ts, to_ts)]

    # Optional severity filter
    if severity_raw:
        try:
            severity = int(severity_raw)
            if severity in (1, 2, 3):
                filter_clauses.append({"term": {"alert.severity": severity}})
        except (ValueError, TypeError):
            pass

    query = {
        "size": size,
        "from": offset,
        "query": {
            "bool": {
                "filter": filter_clauses,
            }
        },
        "sort": [{"timestamp": {"order": "desc"}}],
    }

    try:
        result = client.search(index=SURICATA_INDEX, body=query)
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
        # Enrich with plain English description, risk context, and recommendation
        _alert_enrichment.enrich_alert(source)
        alerts.append(source)

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "page": page,
        "size": size,
        "total": total,
        "total_pages": (total + size - 1) // size if size > 0 else 0,
        "alerts": alerts,
    })


async def handle_alerts_count(request: web.Request) -> web.Response:
    """GET /api/alerts/count?from=&to=

    Returns alert counts grouped by severity level.
    """
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)

    query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [_time_range_filter(from_ts, to_ts)]
            }
        },
        "aggs": {
            "by_severity": {
                "terms": {"field": "alert.severity", "size": 10}
            },
        },
    }

    try:
        result = client.search(index=SURICATA_INDEX, body=query)
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
        label = severity_map.get(key, f"severity_{key}")
        counts[label] = b.get("doc_count", 0)

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "counts": counts,
    })


async def handle_alert_detail(request: web.Request) -> web.Response:
    """GET /api/alerts/{id}

    Returns a single alert document by its OpenSearch _id.
    """
    alert_id = request.match_info.get("id", "")
    if not alert_id:
        return web.json_response({"error": "Alert ID is required"}, status=400)

    client = _get_client(request)

    # Search across all suricata indices for the document by _id
    query = {
        "size": 1,
        "query": {
            "ids": {"values": [alert_id]}
        },
    }

    try:
        result = client.search(index=SURICATA_INDEX, body=query)
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

    return web.json_response({
        "result": "acknowledged",
        "alert_id": alert_id,
        "acknowledged_at": acks[alert_id]["acknowledged_at"],
        "acknowledged_by": acknowledged_by,
    })


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_alert_routes(app: web.Application, storage_manager: StorageManager) -> None:
    """Register all alert API routes on the given aiohttp application.

    The StorageManager is expected to already be stored in app['storage']
    by create_app(). This function registers the route handlers.
    """
    app.router.add_get("/api/alerts", handle_alerts_list)
    app.router.add_get("/api/alerts/count", handle_alerts_count)
    app.router.add_get("/api/alerts/{id}", handle_alert_detail)
    app.router.add_post("/api/alerts/{id}/acknowledge", handle_alert_acknowledge)
    logger.info("Alert API routes registered (4 endpoints)")
