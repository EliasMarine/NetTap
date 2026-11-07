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
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from aiohttp import web
from opensearchpy import OpenSearchException

from api.time_range import parse_time_range
from services.alert_enrichment import AlertEnrichment
from services.excluded_ips import parse_single_ip

# OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
# from services.excluded_ips import build_excluded_ips_filter
# OLD CODE END
from storage.all_buckets import all_buckets
from storage.manager import StorageManager
from storage.snapshot_search import QueryFailed, checked, total_hits
from storage.time_slots import histogram_buckets, time_slots

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
# Shared with the per-device alert counts (Devices, Risk) so every page counts alerts the
# same way (dashboard data accuracy #60)
SURICATA_NOISE_EXCLUSION = _SURICATA_NOISE_EXCLUSION

# Path for storing acknowledgement data (local JSON file)
_ACK_FILE = os.environ.get("ALERT_ACK_FILE", "/opt/nettap/data/alert_acks.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_time_range(request: web.Request) -> tuple[str, str]:
    """'from'/'to' as ISO timestamps, defaulting to the last 24 hours; unreadable is a 400."""
    # OLD CODE START — 2026-11-02: an unreadable from/to (e.g. now-5m) silently became the
    # default window, so the Infrastructure page divided 24 h of events by 5 min
    # """Extract 'from' and 'to' query parameters as ISO timestamps.
    #
    # Defaults to the last 24 hours if not provided or unparseable.
    # """
    # now = datetime.now(timezone.utc)
    # default_from = (now - timedelta(hours=_DEFAULT_RANGE_HOURS)).isoformat()
    # default_to = now.isoformat()
    #
    # raw_from = request.query.get("from", "")
    # raw_to = request.query.get("to", "")
    #
    # if raw_from:
    #     try:
    #         datetime.fromisoformat(raw_from.replace("Z", "+00:00"))
    #     except (ValueError, TypeError):
    #         raw_from = ""
    # if raw_to:
    #     try:
    #         datetime.fromisoformat(raw_to.replace("Z", "+00:00"))
    #     except (ValueError, TypeError):
    #         raw_to = ""
    #
    # return (raw_from or default_from, raw_to or default_to)
    # OLD CODE END
    return parse_time_range(request, timedelta(hours=_DEFAULT_RANGE_HOURS))


# OpenSearch's default index.max_result_window: from + size past it returns nothing.
# shortcut: only the newest 10,000 records can be paged to; use search_after if older pages are needed
_RESULT_WINDOW = 10_000


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


def alert_query(
    from_ts: str,
    to_ts: str,
    narrow: list[dict] | tuple = (),
    exclude: list[dict] | tuple = (),
) -> dict:
    """The alert list's query: Suricata alerts in the window without engine noise, plus `narrow`
    filters and `exclude` must_nots. A drill-down counting with it equals the list it links to."""
    return {
        "bool": {
            "filter": [
                _time_range_filter(from_ts, to_ts),
                *_SURICATA_ALERT_FILTERS,
                *narrow,
            ],
            "must_not": [*_SURICATA_NOISE_EXCLUSION, *exclude],
        }
    }


def severity_clauses(raw: str) -> tuple[list[dict], list[dict]]:
    """(filters, must_nots) for the list's severity=: 1, 2 or 3 is that Suricata severity, "info"
    is what the Info tile counts (no 1, 2 or 3), anything else narrows nothing."""
    if raw == "info":
        return [], [{"terms": {"suricata.alert.severity": [1, 2, 3]}}]
    try:
        severity = int(raw)
    except (ValueError, TypeError):
        return [], []
    if severity in (1, 2, 3):
        return [{"term": {"suricata.alert.severity": severity}}], []
    return [], []


# rule.category's ignore_above on the G11: a longer value is never indexed, so never matched
_SURICATA_CATEGORY_MAX = 1_024


def valid_suricata_category(raw: object) -> str | None:
    """A raw Suricata category (rule.category) exactly as given, or None: 1–1,024 characters,
    not only whitespace. A term on the keyword matches the stored value, which links send."""
    if isinstance(raw, str) and 0 < len(raw) <= _SURICATA_CATEGORY_MAX and raw.strip():
        return raw
    return None


def suricata_category_clause(name: str) -> dict:
    """Alerts carrying `name` among their rule.category values (NET-160 slice 2b-2)."""
    return {"term": {"rule.category": name}}


def rule_categories(rule: object) -> list[str]:
    """The stored rule.category values of a `rule` object a category page exists for: a scalar
    is one, a list each of its own, missing none."""
    raw = rule.get("category") if isinstance(rule, dict) else None
    found = raw if isinstance(raw, list) else [raw]
    return [v for v in found if valid_suricata_category(v) is not None]


def _get_client(request: web.Request):
    """Retrieve the OpenSearch client from the StorageManager on the app."""
    storage: StorageManager = request.app["storage"]
    return storage._client


def _sparkline_interval(from_ts: str, to_ts: str) -> str:
    """Choose a date_histogram interval for sparkline data based on the
    time range span. Returns an OpenSearch fixed_interval string."""
    try:
        ft = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
        tt = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
        span_hours = (tt - ft).total_seconds() / 3600
    except (ValueError, TypeError):
        span_hours = 24

    if span_hours <= 6:
        return "10m"
    elif span_hours <= 24:
        return "1h"
    elif span_hours <= 168:  # 7 days
        return "6h"
    else:
        return "1d"


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

    # OLD CODE START — NET-160 slice 2b-2: no stored rule.category values to link a category by
    # source["alert"] = {
    #     "signature": signature,
    #     "signature_id": signature_id,
    #     "severity": severity,
    #     "category": str(category),
    # }
    # OLD CODE END
    source["alert"] = {
        "signature": signature,
        "signature_id": signature_id,
        "severity": severity,
        "category": str(category),
        # The shown category links to its page only when it is one of these (it can come from
        # alert.category, which the page's term on rule.category never matches)
        "rule_category": rule_categories(rule),
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


# The alert tables' columns and the field behind each (#146): the pages sorted one page of rows.
_ALERT_SORT_FIELDS = {
    "time": "@timestamp",
    "severity": "suricata.alert.severity",
    "signature": "rule.name",
    "source": "source.ip",
    "destination": "destination.ip",
    "dest_port": "destination.port",
    "proto": "network.transport",
    "category": "rule.category",
}


def _alert_sort(sort_key: str, order: str) -> list[dict]:
    """The OpenSearch sort for a column; newest first breaks ties so pages don't overlap.

    Severity "desc" puts the most severe first, and Suricata's 1 is the most severe.
    """
    if sort_key == "time":
        return [{"@timestamp": {"order": order}}]
    if sort_key == "severity":
        order = "asc" if order == "desc" else "desc"
    return [
        {_ALERT_SORT_FIELDS[sort_key]: {"order": order, "missing": "_last"}},
        {"@timestamp": {"order": "desc"}},
    ]


async def handle_alerts_list(request: web.Request) -> web.Response:
    """GET /api/alerts?from=&to=&severity=&page=1&size=50&sort=time&order=desc&category=&sub=&signature=&ip=&src=&dst=&suricata_category=

    Returns a paginated list of Suricata alerts with optional severity filter,
    sorted by any of the alert tables' columns across every page (#146).
    Severity: 1=high, 2=medium, 3=low.
    """
    from_ts, to_ts = _parse_time_range(request)
    page = _parse_int_param(request, "page", 1)
    size = min(_parse_int_param(request, "size", 50), 200)
    severity_raw = request.query.get("severity", "")
    sort_key = request.query.get("sort", "time")
    order = request.query.get("order", "desc")
    if sort_key not in _ALERT_SORT_FIELDS or order not in ("asc", "desc"):
        return web.json_response(
            {
                "error": "sort must be one of "
                + ", ".join(_ALERT_SORT_FIELDS)
                + " and order asc or desc"
            },
            status=400,
        )
    # One canonical address each (NET-160 slice 2b-1). A bad one is a 400: a dropped filter would
    # list more alerts than the link promised, and OpenSearch's own rejection read as a 502.
    addresses: dict[str, str] = {}
    for name in ("ip", "src", "dst"):
        raw = request.query.get(name, "")
        if not raw:
            continue
        parsed = parse_single_ip(raw)
        if parsed is None:
            logger.debug("Alerts list: invalid %s parameter", name)
            return web.json_response(
                {"error": "ip, src and dst must each be one IPv4 or IPv6 address"},
                status=400,
            )
        addresses[name] = parsed
    # A raw Suricata category (NET-160 slice 2b-2); a dropped one would list every category
    suricata_category = None
    if "suricata_category" in request.query:
        suricata_category = valid_suricata_category(request.query["suricata_category"])
        if suricata_category is None:
            logger.debug("Alerts list: invalid suricata_category parameter")
            return web.json_response(
                {"error": "suricata_category must be 1–1024 characters"}, status=400
            )
    client = _get_client(request)

    offset = (page - 1) * size

    # OLD CODE START — NET-160 slice 2b-2: alert_query() adds the window and the alert filters, so
    # the Suricata category page counts with the very query this list runs
    # filter_clauses: list[dict] = [
    #     _time_range_filter(from_ts, to_ts),
    #     *_SURICATA_ALERT_FILTERS,
    # ]
    # OLD CODE END
    filter_clauses: list[dict] = []

    # Optional severity filter
    # OLD CODE START — Zeek-native field: "alert.severity"
    # filter_clauses.append({"term": {"alert.severity": severity}})
    # OLD CODE END
    # "info" is what the Info tile counts: total minus 1, 2 and 3 (it was ignored, so Info listed every alert)
    # OLD CODE START — NET-160 slice 2b-2: moved to severity_clauses(), shared with the category page
    # severity_must_not: list[dict] = []
    # if severity_raw == "info":
    #     severity_must_not.append({"terms": {"suricata.alert.severity": [1, 2, 3]}})
    # elif severity_raw:
    #     try:
    #         severity = int(severity_raw)
    #         if severity in (1, 2, 3):
    #             filter_clauses.append({"term": {"suricata.alert.severity": severity}})
    #     except (ValueError, TypeError):
    #         pass
    # OLD CODE END
    severity_filters, severity_must_not = severity_clauses(severity_raw)
    filter_clauses.extend(severity_filters)

    # Optional signature filter (exact match on rule.name)
    sig_filter = request.query.get("signature", "")
    # OLD CODE START — slice 2b-1: match_phrase; on the keyword rule.name it matches the same alerts,
    # but term states the exact match a smart alert's count relies on
    # if sig_filter:
    #     filter_clauses.append({"match_phrase": {"rule.name": sig_filter}})
    # OLD CODE END
    if sig_filter:
        filter_clauses.append({"term": {"rule.name": sig_filter}})

    # Optional IP filter (matches source OR destination)
    # OLD CODE: ip_filter = request.query.get("ip", "") (slice 2b-1: validated above)
    ip_filter = addresses.get("ip")
    if ip_filter:
        filter_clauses.append(
            {
                "bool": {
                    "should": [
                        {"term": {"source.ip": ip_filter}},
                        {"term": {"destination.ip": ip_filter}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )

    # Optional source and destination (a smart alert's pair, slice 2b-1)
    if "src" in addresses:
        filter_clauses.append({"term": {"source.ip": addresses["src"]}})
    if "dst" in addresses:
        filter_clauses.append({"term": {"destination.ip": addresses["dst"]}})
    if suricata_category is not None:
        filter_clauses.append(suricata_category_clause(suricata_category))

    # OLD CODE START — #147: any of the category's patterns, while the category's own totals give each
    # signature its first matching category (informational when none): Exploit listed 99 alerts
    # under a 6-alert header, Informational 83,490 of 120,066
    # # Optional category filter — match signatures belonging to a threat category
    # category_filter = request.query.get("category", "")
    # if category_filter:
    #     from services.alert_intelligence import THREAT_CATEGORIES

    #     cat_info = THREAT_CATEGORIES.get(category_filter)
    #     if cat_info:
    #         # Build a bool/should with wildcard matches on rule.name for each
    #         # pattern in the category.  Case-insensitive wildcard on .keyword.
    #         should_clauses = []
    #         for pattern in cat_info["patterns"]:
    #             # OLD CODE START — analyzed rule.name holds single tokens, so
    #             # multi-word patterns never matched; wildcard needs the keyword
    #             # should_clauses.append(
    #             #     {
    #             #         "wildcard": {
    #             #             "rule.name": {
    #             #                 "value": f"*{pattern}*",
    #             #                 "case_insensitive": True,
    #             #             }
    #             #         }
    #             #     }
    #             # )
    #             # OLD CODE END
    #             should_clauses.append(
    #                 {
    #                     "wildcard": {
    #                         "rule.name": {
    #                             "value": f"*{pattern}*",
    #                             "case_insensitive": True,
    #                         }
    #                     }
    #                 }
    #             )
    #         if should_clauses:
    #             filter_clauses.append(
    #                 {
    #                     "bool": {
    #                         "should": should_clauses,
    #                         "minimum_should_match": 1,
    #                     }
    #                 }
    #             )
    # OLD CODE END
    # Optional category (and sub-category) filter: the signatures the category page counts (#147)
    category_filter = request.query.get("category", "")
    sub_filter = request.query.get("sub", "")
    if category_filter or sub_filter:
        from services.alert_intelligence import (
            SUB_CATEGORIES,
            THREAT_CATEGORIES,
            categorize_alert,
            categorize_sub_category,
        )

        subs = [s["id"] for s in SUB_CATEGORIES.get(category_filter, [])]
        if category_filter not in THREAT_CATEGORIES or (
            sub_filter and sub_filter not in subs
        ):
            return web.json_response(
                {"error": "unknown category, or a sub-category not in that category"},
                status=400,
            )
        base = {
            "bool": {
                "filter": [
                    _time_range_filter(from_ts, to_ts),
                    *_SURICATA_ALERT_FILTERS,
                ],
                "must_not": _SURICATA_NOISE_EXCLUSION,
            }
        }
        try:
            names = [
                b["key"]
                for b in _every_signature(client, base)
                if categorize_alert(b["key"]) == category_filter
                and (
                    not sub_filter
                    or categorize_sub_category(b["key"], category_filter) == sub_filter
                )
            ]
        except OpenSearchException as exc:
            logger.error("OpenSearch error in alerts list (category): %s", exc)
            return web.json_response(
                {"error": f"OpenSearch query failed: {exc}"}, status=502
            )
        filter_clauses.append(_signature_filter(names))

    # OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
    # excluded = build_excluded_ips_filter(request.app.get("excluded_ips", []))
    # OLD CODE END

    query = {
        "size": size,
        "from": offset,
        # The UI shows this total; without it OpenSearch stops counting at 10,000
        "track_total_hits": True,
        # OLD CODE START — NET-160 slice 2b-2: built by alert_query(), shared with the category page
        # "query": {
        #     "bool": {
        #         "filter": filter_clauses,
        #         # OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
        #         # "must_not": _SURICATA_NOISE_EXCLUSION + excluded,
        #         # OLD CODE END
        #         "must_not": _SURICATA_NOISE_EXCLUSION + severity_must_not,
        #     }
        # },
        # OLD CODE END
        "query": alert_query(from_ts, to_ts, filter_clauses, severity_must_not),
        # OLD CODE START — Zeek-native sort field: "timestamp"
        # "sort": [{"timestamp": {"order": "desc"}}],
        # OLD CODE END
        # OLD CODE START — #146: always newest first; the pages sorted only the rows they had
        # "sort": [{"@timestamp": {"order": "desc"}}],
        # OLD CODE END
        "sort": _alert_sort(sort_key, order),
    }

    # OLD CODE START — NET-160 slice 2b-2: a timed-out or partly failed search, or a missing total,
    # showed a smaller list (or 0) as if complete
    # try:
    #     result = client.search(index=NETWORK_INDEX, body=query)
    # except OpenSearchException as exc:
    #     logger.error("OpenSearch error in alerts list: %s", exc)
    #     return web.json_response(
    #         {"error": f"OpenSearch query failed: {exc}"}, status=502
    #     )
    #
    # hits = result.get("hits", {})
    # total_raw = hits.get("total", {})
    # total = total_raw.get("value", 0) if isinstance(total_raw, dict) else total_raw
    # OLD CODE END
    try:
        result = checked(client.search(index=NETWORK_INDEX, body=query), "alert list")
        total = total_hits(result, "alert list")
    except OpenSearchException as exc:
        logger.error("OpenSearch error in alerts list: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )
    except QueryFailed as exc:
        logger.warning("Alerts list: %s", exc)
        return web.json_response(
            {"error": "The alert search was incomplete"}, status=502
        )

    hits = result.get("hits", {})

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
            # OLD CODE START — #85: pages past OpenSearch's 10,000-result window came back empty
            # "total_pages": (total + size - 1) // size if size > 0 else 0,
            # OLD CODE END
            "total_pages": min(-(-total // size), _RESULT_WINDOW // size)
            if size > 0
            else 0,
            "alerts": alerts,
        }
    )


async def handle_alerts_count(request: web.Request) -> web.Response:
    """GET /api/alerts/count?from=&to=

    Returns alert counts grouped by severity level.
    """
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)
    # OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
    # excluded = build_excluded_ips_filter(request.app.get("excluded_ips", []))
    # OLD CODE END

    query = {
        "size": 0,
        "track_total_hits": True,
        "query": {
            "bool": {
                "filter": [
                    _time_range_filter(from_ts, to_ts),
                    *_SURICATA_ALERT_FILTERS,
                ],
                # OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
                # "must_not": _SURICATA_NOISE_EXCLUSION + excluded,
                # OLD CODE END
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
    # OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
    # excluded = build_excluded_ips_filter(request.app.get("excluded_ips", []))
    # OLD CODE END

    query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    _time_range_filter(from_ts, to_ts),
                    *_SURICATA_ALERT_FILTERS,
                ],
                # OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
                # "must_not": excluded,
                # OLD CODE END
                # Same engine-event rule as the alert count, so the panels add up to the total
                "must_not": _SURICATA_NOISE_EXCLUSION,
            }
        },
        # OLD CODE START — #120: OpenSearch 3.5's skip-list date_histogram misplaces records
        # "aggs": {
        #     "over_time": {
        #         "date_histogram": {
        #             "field": "@timestamp",
        #             "fixed_interval": interval,
        #             "min_doc_count": 0,
        #             "extended_bounds": {"min": from_ts, "max": to_ts},
        #         },
        #         "aggs": {"by_severity": {"terms": {"field": "suricata.alert.severity", "size": 5}}},
        #     }
        # },
        # OLD CODE END
    }
    try:
        query["aggs"] = {
            "over_time": time_slots(
                from_ts,
                to_ts,
                interval,
                aggs={
                    "by_severity": {
                        "terms": {"field": "suricata.alert.severity", "size": 5}
                    }
                },
            )
        }
    except ValueError:
        return web.json_response(
            {
                "error": f"{interval} is too fine for this time range; choose a larger interval"
            },
            status=400,
        )

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in alerts/timeline: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    buckets = []
    # OLD CODE START — #120: date_histogram buckets
    # for bucket in (
    #     result.get("aggregations", {}).get("over_time", {}).get("buckets", [])
    # ):
    # OLD CODE END
    for bucket in histogram_buckets(result.get("aggregations", {}).get("over_time")):
        entry = {
            "timestamp": bucket.get("key_as_string", ""),
            "high": 0,
            "medium": 0,
            "low": 0,
        }
        for sev_bucket in bucket.get("by_severity", {}).get("buckets", []):
            key = sev_bucket.get("key")
            try:
                int_key = int(key)
            except (ValueError, TypeError):
                continue
            label = _SEVERITY_MAP.get(int_key)
            if label:
                entry[label] = sev_bucket.get("doc_count", 0)
        # Info is the rest of the slot, as on the tiles, so the slots sum to the alert count
        entry["info"] = max(
            0,
            bucket.get("doc_count", 0) - entry["high"] - entry["medium"] - entry["low"],
        )
        buckets.append(entry)

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "interval": interval,
            "buckets": buckets,
        }
    )


# Keys per composite page, and in all: past the cap a top list is the busiest among those read
_TOP_PAGE = 5_000
_TOP_CAP = 50_000


def _every_key(
    client,
    from_ts: str,
    to_ts: str,
    terms: dict,
    aggs: dict | None,
    what: str,
) -> tuple[list[dict], bool]:
    """Every value of one field among the list's alerts with its exact count ("key"), checked;
    False if the cap stopped the paging. A terms aggregation's counts are per-shard estimates."""
    buckets, complete = all_buckets(
        client,
        NETWORK_INDEX,
        alert_query(from_ts, to_ts),
        [{"key": {"terms": terms}}],
        aggs,
        page_size=_TOP_PAGE,
        max_buckets=_TOP_CAP,
        what=what,
    )
    if not complete:
        logger.warning("%s stopped at %d keys", what, len(buckets))
    return buckets, complete


def _primary_severity(bucket: dict) -> int:
    """The severity most of a row's alerts carry; 3 (low) when none or unreadable."""
    sev_buckets = (bucket.get("severity") or {}).get("buckets") or []
    try:
        return int(sev_buckets[0].get("key", 3)) if sev_buckets else 3
    except (ValueError, TypeError):
        return 3


async def handle_alerts_top_signatures(request: web.Request) -> web.Response:
    """GET /api/alerts/top-signatures?from=&to=&limit=

    Returns the most frequently triggered alert signatures with their
    primary severity level.
    """
    from_ts, to_ts = _parse_time_range(request)
    limit = min(_parse_int_param(request, "limit", 20), 100)
    client = _get_client(request)
    # OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
    # excluded = build_excluded_ips_filter(request.app.get("excluded_ips", []))
    # OLD CODE END

    # OLD CODE START — NET-160 slice 2b-2: a terms aggregation across shards miscounted some rows
    # (doc_count_error_upper_bound > 0 on the G11), and `missing` merged unnamed alerts with a rule
    # named "Unknown", so a row and the signature= list it opens could disagree
    # query = {
    #     "size": 0,
    #     "query": {
    #         "bool": {
    #             "filter": [
    #                 _time_range_filter(from_ts, to_ts),
    #                 *_SURICATA_ALERT_FILTERS,
    #             ],
    #             # OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
    #             # "must_not": excluded,
    #             # OLD CODE END
    #             # Same engine-event rule as the alert count, so the panels add up to the total
    #             "must_not": _SURICATA_NOISE_EXCLUSION,
    #         }
    #     },
    #     "aggs": {
    #         "top_sigs": {
    #             "terms": {
    #                 "field": "rule.name",
    #                 "size": limit,
    #                 "missing": "Unknown",
    #             },
    #             "aggs": {
    #                 "severity": {
    #                     "terms": {"field": "suricata.alert.severity", "size": 3}
    #                 }
    #             },
    #         }
    #     },
    # }
    #
    # try:
    #     result = client.search(index=NETWORK_INDEX, body=query)
    # except OpenSearchException as exc:
    #     logger.error("OpenSearch error in alerts/top-signatures: %s", exc)
    #     return web.json_response(
    #         {"error": f"OpenSearch query failed: {exc}"}, status=502
    #     )
    #
    # signatures = []
    # for bucket in result.get("aggregations", {}).get("top_sigs", {}).get("buckets", []):
    #     sev_buckets = bucket.get("severity", {}).get("buckets", [])
    #     primary_severity = 3  # default: low
    #     if sev_buckets:
    #         try:
    #             primary_severity = int(sev_buckets[0].get("key", 3))
    #         except (ValueError, TypeError):
    #             primary_severity = 3
    #     signatures.append(
    #         {
    #             "signature": bucket.get("key", "Unknown"),
    #             "count": bucket.get("doc_count", 0),
    #             "severity": primary_severity,
    #         }
    #     )
    #
    # return web.json_response(
    #     {
    #         "from": from_ts,
    #         "to": to_ts,
    #         "signatures": signatures,
    #     }
    # )
    # OLD CODE END
    severity = {"severity": {"terms": {"field": "suricata.alert.severity", "size": 3}}}
    try:
        # missing_bucket: an unnamed alert is its own row (null), apart from "" and "Unknown"
        buckets, complete = _every_key(
            client,
            from_ts,
            to_ts,
            {"field": "rule.name", "missing_bucket": True},
            severity,
            "alert top signatures",
        )
    except OpenSearchException as exc:
        logger.error("OpenSearch error in alerts/top-signatures: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )
    except QueryFailed as exc:
        logger.warning("Alert top signatures: %s", exc)
        return web.json_response(
            {"error": "The alert search was incomplete"}, status=502
        )
    signatures = [
        {
            "signature": b["key"]["key"],
            "count": b["doc_count"],
            "severity": _primary_severity(b),
        }
        for b in buckets
    ]
    signatures.sort(
        key=lambda s: (-s["count"], s["signature"] is None, s["signature"] or "")
    )
    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "signatures": signatures[:limit],
            # False: the rows are the busiest among the signatures read before the cap
            "complete": complete,
            "examined": len(buckets),  # keys read, the null name included
        }
    )


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

    # OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
    # excluded = build_excluded_ips_filter(request.app.get("excluded_ips", []))
    # OLD CODE END
    field = "source.ip" if direction == "src" else "destination.ip"

    # OLD CODE START — NET-160 slice 2b-2: a terms aggregation across shards could miscount a row,
    # so its number and the src=/dst= list could disagree
    # query = {
    #     "size": 0,
    #     "query": {
    #         "bool": {
    #             "filter": [
    #                 _time_range_filter(from_ts, to_ts),
    #                 *_SURICATA_ALERT_FILTERS,
    #             ],
    #             # OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
    #             # "must_not": excluded,
    #             # OLD CODE END
    #             # Same engine-event rule as the alert count, so the panels add up to the total
    #             "must_not": _SURICATA_NOISE_EXCLUSION,
    #         }
    #     },
    #     "aggs": {"top_ips": {"terms": {"field": field, "size": limit}}},
    # }
    #
    # try:
    #     result = client.search(index=NETWORK_INDEX, body=query)
    # except OpenSearchException as exc:
    #     logger.error("OpenSearch error in alerts/top-ips: %s", exc)
    #     return web.json_response(
    #         {"error": f"OpenSearch query failed: {exc}"}, status=502
    #     )
    #
    # ips = []
    # for bucket in result.get("aggregations", {}).get("top_ips", {}).get("buckets", []):
    #     ips.append(
    #         {
    #             "ip": bucket.get("key", ""),
    #             "count": bucket.get("doc_count", 0),
    #         }
    #     )
    #
    # return web.json_response(
    #     {
    #         "from": from_ts,
    #         "to": to_ts,
    #         "direction": direction,
    #         "ips": ips,
    #     }
    # )
    # OLD CODE END
    try:
        # A row counts alerts with the address on this side only: the src= or dst= list
        buckets, complete = _every_key(
            client, from_ts, to_ts, {"field": field}, None, "alert top IPs"
        )
    except OpenSearchException as exc:
        logger.error("OpenSearch error in alerts/top-ips: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )
    except QueryFailed as exc:
        logger.warning("Alert top IPs: %s", exc)
        return web.json_response(
            {"error": "The alert search was incomplete"}, status=502
        )
    ips = sorted(
        ({"ip": b["key"]["key"], "count": b["doc_count"]} for b in buckets),
        key=lambda r: (-r["count"], r["ip"]),
    )
    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "direction": direction,
            "ips": ips[:limit],
            # False: the rows are the busiest among the addresses read before the cap
            "complete": complete,
            "examined": len(buckets),  # addresses read
        }
    )


# Docs without a rule.name group under this name, as the old `missing: "Unknown"` did
_UNKNOWN_SIGNATURE = "Unknown"
# Signatures per page when each carries a sparkline: 100 x (~186 daily buckets over 180 days
# of alerts + 5 severities) stays under search.max_buckets (65,535)
_SPARKLINE_SIGNATURE_PAGE = 100


def _every_signature(
    client, query: dict, aggs: dict | None = None, page_size: int = 1_000
) -> list[dict]:
    """Every rule.name bucket matching `query`, "key" = the name (#96).

    A category is a pattern match on the name, so its totals need every signature, not a top list.
    """
    sources = [{"sig": {"terms": {"field": "rule.name", "missing_bucket": True}}}]
    buckets, complete = all_buckets(
        client, NETWORK_INDEX, query, sources, aggs, page_size=page_size
    )
    if not complete:
        logger.warning("Alert signatures stopped at %d", len(buckets))
    return [
        {
            **b,
            "key": _UNKNOWN_SIGNATURE if b["key"]["sig"] is None else b["key"]["sig"],
        }
        for b in buckets
    ]


def _signature_filter(names) -> dict:
    """Alerts whose rule.name is in `names` ("Unknown" also matches alerts without one)."""
    should: list[dict] = [{"terms": {"rule.name": sorted(names)}}]
    if _UNKNOWN_SIGNATURE in names:
        should.append({"bool": {"must_not": {"exists": {"field": "rule.name"}}}})
    return {"bool": {"should": should, "minimum_should_match": 1}}


# OLD CODE START — I4: an address took the worst NetTap-regraded severity of every signature it
# appeared in, so one high alert elsewhere made every address of that signature high
# def _alerts_by_ip(
#     client, query: dict, field: str, sig_severity: dict[str, int]
# ) -> dict[str, tuple[int, int]]:
#     """{ip: (alerts, worst severity)} for every `field` value among these signatures (#96).
#
#     The severity is the worst of the signatures the IP appears in, never above 4 (as before).
#     """
#     if not sig_severity:
#         return {}
#     by_sev: dict[int, list[str]] = defaultdict(list)
#     for name, sev in sig_severity.items():
#         by_sev[sev].append(name)
#     scoped = {"bool": {"filter": [query, _signature_filter(sig_severity)]}}
#     per_sev = {str(s): _signature_filter(names) for s, names in by_sev.items()}
#     buckets, complete = all_buckets(
#         client,
#         NETWORK_INDEX,
#         scoped,
#         [{"ip": {"terms": {"field": field}}}],
#         {"sev": {"filters": {"filters": per_sev}}},
#     )
#     if not complete:
#         logger.warning("Alert %s values stopped at %d", field, len(buckets))
#     return {
#         b["key"]["ip"]: (
#             b.get("doc_count", 0),
#             min(
#                 [4, *(int(s) for s, f in b["sev"]["buckets"].items() if f["doc_count"])]
#             ),
#         )
#         for b in buckets
#     }
# OLD CODE END
def _alerts_by_ip(
    client, query: dict, field: str, signatures
) -> dict[str, tuple[int, int]]:
    """{ip: (alerts, worst Suricata severity)} for every `field` value among these signatures (#96).

    The severity comes from that address's own alerts (I4): 1, 2 or 3, or 4 when none of
    them carries one of those.
    """
    if not signatures:
        return {}
    scoped = {"bool": {"filter": [query, _signature_filter(signatures)]}}
    buckets, complete = all_buckets(
        client,
        NETWORK_INDEX,
        scoped,
        [{"ip": {"terms": {"field": field}}}],
        {"sev": {"terms": {"field": "suricata.alert.severity", "size": 10}}},
    )
    if not complete:
        logger.warning("Alert %s values stopped at %d", field, len(buckets))
    return {
        b["key"]["ip"]: (
            b.get("doc_count", 0),
            min([4, *(k for k in map(_suricata_level, b["sev"]["buckets"]) if k)]),
        )
        for b in buckets
    }


def _suricata_level(sev_bucket: dict) -> int | None:
    """A severity bucket's key as Suricata's 1, 2 or 3 (numeric or keyword field); None otherwise."""
    try:
        key = int(sev_bucket.get("key"))
    except (TypeError, ValueError):
        return None
    return key if key in _SEVERITY_MAP and sev_bucket.get("doc_count", 0) else None


def _raw_severity_breakdown(bucket: dict) -> dict[str, int]:
    """Alerts by Suricata severity, as the alert list's tiles count them (I4): high = 1,
    medium = 2, low = 3, and info = the rest (other values or no severity)."""
    counts = {"high": 0, "medium": 0, "low": 0}
    for sev_bucket in bucket.get("by_severity", {}).get("buckets", []):
        level = _suricata_level(sev_bucket)
        if level:
            counts[_SEVERITY_MAP[level]] += sev_bucket["doc_count"]
    return {**counts, "info": max(0, bucket.get("doc_count", 0) - sum(counts.values()))}


async def handle_alerts_categories(request: web.Request) -> web.Response:
    """GET /api/alerts/categories?from=&to=

    Returns enriched alert categories with counts, severity breakdown,
    sparkline trend data, and sub-category grouping. Each alert is
    classified into one of 13 NetTap threat categories via pattern
    matching on the signature.
    """
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)
    interval = _sparkline_interval(from_ts, to_ts)
    # OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
    # excluded = build_excluded_ips_filter(request.app.get("excluded_ips", []))
    # OLD CODE END

    from services.alert_intelligence import (
        THREAT_CATEGORIES,
        SUB_CATEGORIES,
        MITRE_TECHNIQUES,
        categorize_alert,
        categorize_sub_category,
        # OLD CODE START — I4: the category pages show Suricata's severity now
        # reclassify_severity,
        # OLD CODE END
    )

    query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    _time_range_filter(from_ts, to_ts),
                    *_SURICATA_ALERT_FILTERS,
                ],
                # OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
                # "must_not": _SURICATA_NOISE_EXCLUSION + excluded,
                # OLD CODE END
                "must_not": _SURICATA_NOISE_EXCLUSION,
            }
        },
        # OLD CODE START — #96: the top 500 signatures only; the rest fell out of every category
        # "aggs": {
        #     "by_signature": {
        #         "terms": {
        #             "field": "rule.name",
        #             "size": 500,
        #             "missing": "Unknown",
        #         },
        #         "aggs": {
        #             "by_severity": {
        #                 "terms": {"field": "suricata.alert.severity", "size": 5}
        #             },
        #             "over_time": {
        #                 "date_histogram": {
        #                     "field": "@timestamp",
        #                     "fixed_interval": interval,
        #                     "min_doc_count": 0,
        #                 }
        #             },
        #         },
        #     }
        # },
        # OLD CODE END
    }
    per_signature = {
        "by_severity": {"terms": {"field": "suricata.alert.severity", "size": 5}},
        # OLD CODE START — #120: OpenSearch 3.5's skip-list date_histogram misplaces records
        # "over_time": {
        #     "date_histogram": {
        #         "field": "@timestamp",
        #         "fixed_interval": interval,
        #         "min_doc_count": 0,
        #     }
        # },
        # OLD CODE END
        "over_time": time_slots(
            from_ts, to_ts, interval
        ),  # the sparkline interval fits any range
    }

    try:
        # OLD CODE START — #96: the top 500 signatures only; the rest fell out of every category
        # result = client.search(index=NETWORK_INDEX, body=query)
        # OLD CODE END
        signatures = _every_signature(
            client, query["query"], per_signature, _SPARKLINE_SIGNATURE_PAGE
        )
    except OpenSearchException as exc:
        logger.error("OpenSearch error in alerts/categories: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    # Accumulate per-category data in Python
    cat_data: dict[str, dict] = {}
    for cat_id, cat_info in THREAT_CATEGORIES.items():
        cat_data[cat_id] = {
            "id": cat_id,
            "label": cat_info["label"],
            "icon": cat_info["icon"],
            "color": cat_info["color"],
            "description": cat_info["description"],
            "count": 0,
            # OLD CODE START — I4: NetTap's regraded scale; every other page shows Suricata's 1/2/3
            # "severity_breakdown": {
            #     "critical": 0,
            #     "high": 0,
            #     "medium": 0,
            #     "low": 0,
            #     "info": 0,
            # },
            # OLD CODE END
            "severity_breakdown": {"high": 0, "medium": 0, "low": 0, "info": 0},
            "sparkline": {},  # timestamp -> count
            "sub_categories": {},  # sub_id -> {label, count}
        }

    # OLD CODE START — I4: NetTap's regraded scale; the category pages show Suricata's 1/2/3
    # sev_name_map = {1: "critical", 2: "high", 3: "medium", 4: "low", 5: "info"}
    # OLD CODE END

    # OLD CODE START — #96: the top 500 signatures only; the rest fell out of every category
    # for bucket in (
    #     result.get("aggregations", {}).get("by_signature", {}).get("buckets", [])
    # ):
    # OLD CODE END
    for bucket in signatures:
        sig_name = bucket.get("key", "Unknown")
        doc_count = bucket.get("doc_count", 0)

        category = categorize_alert(sig_name)
        entry = cat_data.get(category)
        if not entry:
            entry = cat_data["informational"]

        entry["count"] += doc_count

        # OLD CODE START — I4: NetTap's regraded scale; every other page shows Suricata's 1/2/3
        # # Severity sub-agg (I6 fix: int() conversion on bucket key)
        # for sev_bucket in bucket.get("by_severity", {}).get("buckets", []):
        #     raw_sev = sev_bucket.get("key", 4)
        #     new_sev = reclassify_severity(sig_name, int(raw_sev))
        #     sev_label = sev_name_map.get(new_sev, "info")
        #     entry["severity_breakdown"][sev_label] += sev_bucket.get("doc_count", 0)
        # OLD CODE END
        for level, n in _raw_severity_breakdown(bucket).items():
            entry["severity_breakdown"][level] += n

        # Sparkline sub-agg
        # was bucket.get("over_time", {}).get("buckets", []) (date_histogram, #120)
        for time_bucket in histogram_buckets(bucket.get("over_time")):
            ts_key = time_bucket.get("key_as_string", "")
            ts_count = time_bucket.get("doc_count", 0)
            if ts_key:
                entry["sparkline"][ts_key] = (
                    entry["sparkline"].get(ts_key, 0) + ts_count
                )

        # Sub-category classification
        sub_id = categorize_sub_category(sig_name, category)
        if sub_id:
            subs = entry["sub_categories"]
            if sub_id not in subs:
                # Find the sub-category label
                sub_label = sub_id
                for sub_def in SUB_CATEGORIES.get(category, []):
                    if sub_def["id"] == sub_id:
                        sub_label = sub_def["label"]
                        break
                subs[sub_id] = {"id": sub_id, "label": sub_label, "count": 0}
            subs[sub_id]["count"] += doc_count

    # Compute trend from sparkline data
    def _compute_trend_from_sparkline(sparkline: dict) -> str:
        vals = list(sparkline.values())
        if len(vals) < 4:
            return "stable"
        mid = len(vals) // 2
        first_half = sum(vals[:mid])
        second_half = sum(vals[mid:])
        if second_half > first_half * 1.5:
            return "increasing"
        elif first_half > second_half * 1.5:
            return "decreasing"
        return "stable"

    # Build final response
    categories = []
    for cat_id, entry in cat_data.items():
        if entry["count"] == 0:
            continue
        trend = _compute_trend_from_sparkline(entry["sparkline"])
        categories.append(
            {
                "id": entry["id"],
                "label": entry["label"],
                "icon": entry["icon"],
                "color": entry["color"],
                "description": entry["description"],
                "count": entry["count"],
                "severity_breakdown": entry["severity_breakdown"],
                "trend": trend,
                "sparkline": [
                    {"timestamp": ts, "count": c}
                    for ts, c in sorted(entry["sparkline"].items())
                ],
                "sub_categories": sorted(
                    entry["sub_categories"].values(),
                    key=lambda s: s["count"],
                    reverse=True,
                ),
                "mitre_techniques": MITRE_TECHNIQUES.get(cat_id, []),
            }
        )

    categories.sort(key=lambda c: c["count"], reverse=True)

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "interval": interval,
            "categories": categories,
        }
    )


async def handle_alert_category_detail(request: web.Request) -> web.Response:
    """GET /api/alerts/categories/{category}?from=&to=

    Returns detailed stats for a single threat category: total count,
    unique sources/targets/devices, severity breakdown, sub-categories,
    affected devices, top signatures, and MITRE techniques.
    """
    category = request.match_info.get("category", "")
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)
    # OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
    # excluded = build_excluded_ips_filter(request.app.get("excluded_ips", []))
    # OLD CODE END

    from services.alert_intelligence import (
        THREAT_CATEGORIES,
        SUB_CATEGORIES,
        MITRE_TECHNIQUES,
        categorize_alert,
        categorize_sub_category,
        # OLD CODE START — I4: the category pages show Suricata's severity now
        # reclassify_severity,
        # OLD CODE END
    )

    if category not in THREAT_CATEGORIES:
        return web.json_response({"error": f"Unknown category: {category}"}, status=404)

    cat_info = THREAT_CATEGORIES[category]

    query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    _time_range_filter(from_ts, to_ts),
                    *_SURICATA_ALERT_FILTERS,
                ],
                # OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
                # "must_not": _SURICATA_NOISE_EXCLUSION + excluded,
                # OLD CODE END
                "must_not": _SURICATA_NOISE_EXCLUSION,
            }
        },
        # OLD CODE START — #96: the top 500 signatures only; the rest fell out of the category
        # "aggs": {
        #     "by_signature": {
        #         "terms": {
        #             "field": "rule.name",
        #             "size": 500,
        #             "missing": "Unknown",
        #         },
        #         "aggs": {
        #             "by_severity": {
        #                 "terms": {"field": "suricata.alert.severity", "size": 5}
        #             },
        #             "by_src_ip": {"terms": {"field": "source.ip", "size": 50}},
        #             "by_dst_ip": {"terms": {"field": "destination.ip", "size": 50}},
        #             "latest": {"max": {"field": "@timestamp"}},
        #         },
        #     }
        # },
        # OLD CODE END
    }
    per_signature = {
        "by_severity": {"terms": {"field": "suricata.alert.severity", "size": 5}},
        # OLD CODE START — #96: 50 IPs per signature; 400 scanners read as 50 sources
        # "by_src_ip": {"terms": {"field": "source.ip", "size": 50}},
        # "by_dst_ip": {"terms": {"field": "destination.ip", "size": 50}},
        # OLD CODE END
        "latest": {"max": {"field": "@timestamp"}},
    }

    try:
        # OLD CODE START — #96: the top 500 signatures only; the rest fell out of the category
        # result = client.search(index=NETWORK_INDEX, body=query)
        # OLD CODE END
        # OLD CODE START — #96: 50 IPs per signature; 400 scanners read as 50 sources
        # # 500 x (5 + 50 + 50) sub-buckets stays under search.max_buckets (65,535)
        # signatures = _every_signature(client, query["query"], per_signature, 500)
        # OLD CODE END
        signatures = _every_signature(client, query["query"], per_signature)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in alert category detail: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    # OLD CODE START — I4: NetTap's regraded scale; the category pages show Suricata's 1/2/3
    # sev_name_map = {1: "critical", 2: "high", 3: "medium", 4: "low", 5: "info"}
    # OLD CODE END

    total_count = 0
    # OLD CODE START — I4: NetTap's regraded scale; every other page shows Suricata's 1/2/3
    # severity_breakdown = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    # OLD CODE END
    severity_breakdown = {"high": 0, "medium": 0, "low": 0, "info": 0}
    sub_cat_counts: dict[str, int] = {}
    # OLD CODE START — #96: 50 IPs per signature; 400 scanners read as 50 sources
    # all_sources: set[str] = set()
    # all_targets: set[str] = set()
    # device_counts: dict[str, int] = {}  # ip → total alert count
    # device_severity: dict[str, int] = {}  # ip → worst severity (lowest = worst)
    # OLD CODE END
    sig_severity: dict[
        str, int
    ] = {}  # signature → primary severity, for the IP queries
    top_signatures: list[dict] = []

    # OLD CODE START — #96: the top 500 signatures only; the rest fell out of the category
    # for bucket in (
    #     result.get("aggregations", {}).get("by_signature", {}).get("buckets", [])
    # ):
    # OLD CODE END
    for bucket in signatures:
        sig_name = bucket.get("key", "Unknown")
        doc_count = bucket.get("doc_count", 0)

        sig_category = categorize_alert(sig_name)
        if sig_category != category:
            continue

        total_count += doc_count

        # OLD CODE START — I4: NetTap's regraded scale; every other page shows Suricata's 1/2/3
        # # Severity
        # primary_sev = 4
        # for sev_bucket in bucket.get("by_severity", {}).get("buckets", []):
        #     raw_sev = sev_bucket.get("key", 4)
        #     new_sev = reclassify_severity(sig_name, int(raw_sev))
        #     sev_label = sev_name_map.get(new_sev, "info")
        #     severity_breakdown[sev_label] += sev_bucket.get("doc_count", 0)
        #
        # sev_buckets = bucket.get("by_severity", {}).get("buckets", [])
        # if sev_buckets:
        #     primary_sev = reclassify_severity(
        #         sig_name, int(sev_buckets[0].get("key", 4))
        #     )
        # OLD CODE END
        for level, n in _raw_severity_breakdown(bucket).items():
            severity_breakdown[level] += n
        # The signature's most common Suricata severity, as the top-signatures list shows it
        sev_buckets = bucket.get("by_severity", {}).get("buckets", [])
        primary_sev = (_suricata_level(sev_buckets[0]) if sev_buckets else None) or 4

        # OLD CODE START — #96: 50 IPs per signature; 400 scanners read as 50 sources
        # # Source IPs — track per-device counts
        # for src_b in bucket.get("by_src_ip", {}).get("buckets", []):
        #     ip = src_b.get("key", "")
        #     if ip:
        #         all_sources.add(ip)
        #         device_counts[ip] = device_counts.get(ip, 0) + src_b.get("doc_count", 0)
        #         device_severity[ip] = min(device_severity.get(ip, 4), primary_sev)
        #
        # # Destination IPs — track per-device counts
        # for dst_b in bucket.get("by_dst_ip", {}).get("buckets", []):
        #     ip = dst_b.get("key", "")
        #     if ip:
        #         all_targets.add(ip)
        #         device_counts[ip] = device_counts.get(ip, 0) + dst_b.get("doc_count", 0)
        #         device_severity[ip] = min(device_severity.get(ip, 4), primary_sev)
        # OLD CODE END
        sig_severity[sig_name] = primary_sev

        # Sub-category
        sub_id = categorize_sub_category(sig_name, category)
        if sub_id:
            sub_cat_counts[sub_id] = sub_cat_counts.get(sub_id, 0) + doc_count

        # Top signatures
        last_seen = bucket.get("latest", {}).get("value_as_string", "")
        top_signatures.append(
            {
                "signature": sig_name,
                "count": doc_count,
                # OLD CODE START — I4: NetTap's regraded scale
                # "severity": primary_sev,
                # "severity_label": sev_name_map.get(primary_sev, "info"),
                # OLD CODE END
                "severity": primary_sev,
                "severity_label": _SEVERITY_MAP.get(primary_sev, "info"),
                "last_seen": last_seen,
            }
        )

    top_signatures.sort(key=lambda s: s["count"], reverse=True)

    # Every source and target IP of the category's signatures, with its alert count
    try:
        # was _alerts_by_ip(..., sig_severity): a signature-wide severity for every address (I4)
        sources = _alerts_by_ip(client, query["query"], "source.ip", list(sig_severity))
        targets = _alerts_by_ip(
            client, query["query"], "destination.ip", list(sig_severity)
        )
    except OpenSearchException as exc:
        logger.error("OpenSearch error in alert category IPs: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )
    all_sources = set(sources)
    all_targets = set(targets)
    unseen = (0, 4)  # (no alerts, low)
    device_counts = {
        ip: sources.get(ip, unseen)[0] + targets.get(ip, unseen)[0]
        for ip in all_sources | all_targets
    }
    device_severity = {
        ip: min(sources.get(ip, unseen)[1], targets.get(ip, unseen)[1])
        for ip in device_counts
    }

    # Build sub-categories response
    sub_categories = []
    for sub_def in SUB_CATEGORIES.get(category, []):
        sub_count = sub_cat_counts.get(sub_def["id"], 0)
        if sub_count > 0:
            sub_categories.append(
                {
                    "id": sub_def["id"],
                    "label": sub_def["label"],
                    "count": sub_count,
                }
            )
    sub_categories.sort(key=lambda s: s["count"], reverse=True)

    # Build affected devices list (top 20 by alert count, as objects)
    affected_devices = []
    for ip in sorted(device_counts, key=lambda x: device_counts[x], reverse=True)[:20]:
        sev = device_severity.get(ip, 4)
        affected_devices.append(
            {
                "ip": ip,
                "count": device_counts[ip],
                # OLD CODE START — I4: NetTap's regraded scale
                # "severity": sev_name_map.get(sev, "info"),
                # OLD CODE END
                "severity": _SEVERITY_MAP.get(sev, "info"),
            }
        )

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "category": {
                "id": category,
                "label": cat_info["label"],
                "icon": cat_info["icon"],
                "color": cat_info["color"],
                "description": cat_info["description"],
            },
            "stats": {
                "total": total_count,
                "unique_sources": len(all_sources),
                "unique_targets": len(all_targets),
                "affected_devices": len(device_counts),
            },
            "severity_breakdown": severity_breakdown,
            "sub_categories": sub_categories,
            "affected_devices": affected_devices,
            "top_signatures": top_signatures[:20],
            "mitre_techniques": MITRE_TECHNIQUES.get(category, []),
        }
    )


async def handle_alert_category_timeline(request: web.Request) -> web.Response:
    """GET /api/alerts/categories/{category}/timeline?from=&to=&interval=

    Returns time-series data for a single category, bucketed by interval,
    with per-signature breakdown within each time bucket.
    """
    category = request.match_info.get("category", "")
    from_ts, to_ts = _parse_time_range(request)
    interval = request.query.get("interval", "")
    if interval not in _ALLOWED_INTERVALS:
        interval = _sparkline_interval(from_ts, to_ts)
    client = _get_client(request)
    # OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
    # excluded = build_excluded_ips_filter(request.app.get("excluded_ips", []))
    # OLD CODE END

    from services.alert_intelligence import (
        THREAT_CATEGORIES,
        categorize_alert,
        categorize_sub_category,
    )

    if category not in THREAT_CATEGORIES:
        return web.json_response({"error": f"Unknown category: {category}"}, status=404)

    query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    _time_range_filter(from_ts, to_ts),
                    *_SURICATA_ALERT_FILTERS,
                ],
                # OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
                # "must_not": _SURICATA_NOISE_EXCLUSION + excluded,
                # OLD CODE END
                "must_not": _SURICATA_NOISE_EXCLUSION,
            }
        },
        # OLD CODE START — #96: 50 signatures per time bucket; a busier hour's total lost the rest
        # "aggs": {
        #     "over_time": {
        #         "date_histogram": {
        #             "field": "@timestamp",
        #             "fixed_interval": interval,
        #             "min_doc_count": 0,
        #             "extended_bounds": {"min": from_ts, "max": to_ts},
        #         },
        #         "aggs": {"by_signature": {"terms": {"field": "rule.name", "size": 50}}},
        #     }
        # },
        # OLD CODE END
    }

    try:
        # OLD CODE START — #96: 50 signatures per time bucket; a busier hour's total lost the rest
        # result = client.search(index=NETWORK_INDEX, body=query)
        # OLD CODE END
        # Count only this category's signatures, so each time bucket's doc_count is its total
        names = [
            b["key"]
            for b in _every_signature(client, query["query"])
            if categorize_alert(b["key"]) == category
        ]
        by_sub: dict[str, list[str]] = defaultdict(list)
        for name in names:
            sub_id = categorize_sub_category(name, category)
            if sub_id:
                by_sub[sub_id].append(name)
        # OLD CODE START — #120: OpenSearch 3.5's skip-list date_histogram misplaces records
        # over_time: dict = {
        #     "date_histogram": {
        #         "field": "@timestamp",
        #         "fixed_interval": interval,
        #         "min_doc_count": 0,
        #         "extended_bounds": {"min": from_ts, "max": to_ts},
        #     }
        # }
        # OLD CODE END
        over_time: dict = time_slots(from_ts, to_ts, interval)
        if by_sub:
            per_sub = {sub: _signature_filter(n) for sub, n in by_sub.items()}
            over_time["aggs"] = {"by_sub": {"filters": {"filters": per_sub}}}
        body = {
            "size": 0,
            "query": {"bool": {"filter": [query["query"], _signature_filter(names)]}},
            "aggs": {"over_time": over_time},
        }
        result = client.search(index=NETWORK_INDEX, body=body)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in category timeline: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )
    except ValueError:  # more slots than time_slots allows
        return web.json_response(
            {
                "error": f"{interval} is too fine for this time range; choose a larger interval"
            },
            status=400,
        )

    series = []
    # was result["aggregations"]["over_time"]["buckets"] (date_histogram, #120)
    for time_bucket in histogram_buckets(
        result.get("aggregations", {}).get("over_time")
    ):
        ts = time_bucket.get("key_as_string", "")
        # OLD CODE START — #96: 50 signatures per time bucket; a busier hour's total lost the rest
        # category_count = 0
        # sub_cat_breakdown: dict[str, int] = {}
        #
        # for sig_bucket in time_bucket.get("by_signature", {}).get("buckets", []):
        #     sig_name = sig_bucket.get("key", "Unknown")
        #     sig_count = sig_bucket.get("doc_count", 0)
        #
        #     if categorize_alert(sig_name) == category:
        #         category_count += sig_count
        #         sub_id = categorize_sub_category(sig_name, category)
        #         if sub_id:
        #             sub_cat_breakdown[sub_id] = (
        #                 sub_cat_breakdown.get(sub_id, 0) + sig_count
        #             )
        # OLD CODE END
        category_count = time_bucket.get("doc_count", 0)
        sub_cat_breakdown = {
            sub: f.get("doc_count", 0)
            for sub, f in time_bucket.get("by_sub", {}).get("buckets", {}).items()
            if f.get("doc_count", 0)
        }

        series.append(
            {
                "timestamp": ts,
                "total": category_count,
                "sub_categories": sub_cat_breakdown,
            }
        )

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "category": category,
            "interval": interval,
            "series": series,
        }
    )


# ---------------------------------------------------------------------------
# Smart Alert endpoints (alert intelligence layer)
# ---------------------------------------------------------------------------


async def handle_smart_alerts(request: web.Request) -> web.Response:
    """GET /api/alerts/smart?from=&to=&device_ip=&include_info=false&limit=50"""
    from_ts, to_ts = _parse_time_range(request)
    device_ip = request.query.get("device_ip", "").strip() or None
    include_info = request.query.get("include_info", "false").lower() == "true"
    limit = _parse_int_param(request, "limit", 50)
    client = _get_client(request)
    # OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
    # excluded = build_excluded_ips_filter(request.app.get("excluded_ips", []))
    # OLD CODE END

    from services.alert_intelligence import get_smart_alerts

    try:
        # OLD CODE START — NET-158: fetched `limit` groups, so "total" was the capped list's
        # length (the device page's "10 grouped" for a device with more)
        # alerts = await get_smart_alerts(
        #     client,
        #     from_ts,
        #     to_ts,
        #     device_ip,
        #     include_info,
        #     limit,
        # OLD CODE END
        every_group = await get_smart_alerts(
            client,
            from_ts,
            to_ts,
            device_ip,
            include_info,
            None,
            # OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
            # excluded_ips=excluded,
            # OLD CODE END
        )
    except Exception as exc:
        logger.error("Smart alerts query failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "device_ip": device_ip,
            # get_smart_alerts sorts worst first, so the first `limit` are the top groups
            "alerts": every_group[:limit],
            "total": len(every_group),
        }
    )


async def handle_smart_alert_summary(request: web.Request) -> web.Response:
    """GET /api/alerts/smart/summary?from=&to=&device_ip="""
    from_ts, to_ts = _parse_time_range(request)
    device_ip = request.query.get("device_ip", "").strip() or None
    client = _get_client(request)
    # OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
    # excluded = build_excluded_ips_filter(request.app.get("excluded_ips", []))
    # OLD CODE END

    from services.alert_intelligence import get_smart_alert_summary

    try:
        summary = await get_smart_alert_summary(
            # OLD CODE START — excluded IPs stay visible in alerts (Settings copy promises it)
            # client, from_ts, to_ts, device_ip, excluded_ips=excluded
            # OLD CODE END
            client,
            from_ts,
            to_ts,
            device_ip,
        )
    except Exception as exc:
        logger.error("Smart alert summary failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response(
        {"from": from_ts, "to": to_ts, "device_ip": device_ip, **summary}
    )


async def handle_suppress_alert(request: web.Request) -> web.Response:
    """POST /api/alerts/suppress — body: {signature_id, device_ip?, reason?}"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    sig_id = body.get("signature_id")
    if not sig_id:
        return web.json_response({"error": "signature_id is required"}, status=400)

    from services.alert_intelligence import suppress_rule

    suppress_rule(
        signature_id=int(sig_id),
        device_ip=body.get("device_ip"),
        reason=body.get("reason", ""),
    )
    return web.json_response({"status": "suppressed", "signature_id": sig_id})


async def handle_false_positive(request: web.Request) -> web.Response:
    """POST /api/alerts/false-positive — body: {signature_id, reason?}"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    sig_id = body.get("signature_id")
    if not sig_id:
        return web.json_response({"error": "signature_id is required"}, status=400)

    from services.alert_intelligence import mark_false_positive

    mark_false_positive(signature_id=int(sig_id), reason=body.get("reason", ""))
    return web.json_response(
        {"status": "marked_false_positive", "signature_id": sig_id}
    )


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
    # Category detail routes — BEFORE {id} catch-all (more specific path)
    app.router.add_get(
        "/api/alerts/categories/{category}/timeline", handle_alert_category_timeline
    )
    app.router.add_get(
        "/api/alerts/categories/{category}", handle_alert_category_detail
    )
    # Smart alert routes — /smart/summary BEFORE /smart (more specific first)
    app.router.add_get("/api/alerts/smart/summary", handle_smart_alert_summary)
    app.router.add_get("/api/alerts/smart", handle_smart_alerts)
    app.router.add_post("/api/alerts/suppress", handle_suppress_alert)
    app.router.add_post("/api/alerts/false-positive", handle_false_positive)
    # Parameterized routes LAST (catch-all pattern)
    app.router.add_get("/api/alerts/{id}", handle_alert_detail)
    app.router.add_post("/api/alerts/{id}/acknowledge", handle_alert_acknowledge)
    logger.info("Alert API routes registered (14 endpoints)")
