"""
NetTap Device Inventory API Routes

Registers device discovery and detail endpoints with the aiohttp application.
These endpoints query OpenSearch zeek-* and suricata-* indices to provide
a network device inventory with passive fingerprinting enrichment (MAC,
hostname, manufacturer, OS hint).
"""

import ipaddress
import logging
import os
import time
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from aiohttp import web
from opensearchpy import OpenSearchException

from api.drilldown_runner import lan_check
from api.offload import in_thread, run_blocking
from api.time_range import _utc, iso_param, parse_time_range
from storage.all_buckets import PAGE_SIZE, all_buckets
from storage.manager import StorageManager
from storage.snapshot_search import QueryFailed, checked
from storage.time_slots import histogram_buckets, time_slots
from api.alerts import SURICATA_NOISE_EXCLUSION
from services.device_fingerprint import DeviceFingerprint
from services.device_registry import DeviceRegistry
from services.dns_analytics import DNS_LOOKUP_EXCLUSION
from services.excluded_ips import (
    CONN_ACCOUNTING,
    build_excluded_ips_filter,
    RFC1918_SOURCE_FILTER,
)
from services.device_accounting import (
    BYTE_SUMS as _BYTE_SUMS,
    IPV4_ALL,
    STARTED,
    add,
    answered_by_ip,
    bucket_bytes as _bucket_bytes,
    side_bytes as _device_side_bytes,
    side_sums as _side_sums,
    fold_ipv6,
    forwarded_macs,
    gateway_macs,
    ipv6_by_mac,
    ipv6_clause,
    totals,
)
from services.traffic_classifier import classify_asn, CATEGORIES
from api.alerts import _normalize_alert_source

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

# Fewest conn records an IP needs to be a device; 3 keeps quiet phones/IoT but drops stray packets
_MIN_CONNECTIONS = 3

# A listed device whose newest record is this recent is Online (the Devices table's rule)
_ONLINE_MS = 5 * 60 * 1000

# shortcut: the checked device reads (the list and the count) stop at 20,000 IPs and answer 502,
# far above a household; a site with more needs a paged list instead of every device per request
_DEVICE_CAP = 20_000


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
    # Returns (from_iso, to_iso) strings suitable for OpenSearch range queries.
    # """
    # now = datetime.now(timezone.utc)
    # default_from = (now - timedelta(hours=_DEFAULT_RANGE_HOURS)).isoformat()
    # default_to = now.isoformat()
    #
    # raw_from = request.query.get("from", "")
    # raw_to = request.query.get("to", "")
    #
    # # Validate from
    # if raw_from:
    #     try:
    #         datetime.fromisoformat(raw_from.replace("Z", "+00:00"))
    #     except (ValueError, TypeError):
    #         raw_from = ""
    # # Validate to
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

# #90: one device's terms lists are short, so asking each shard for all of them (instead of
# OpenSearch's size * 1.5 + 10) makes the counts exact once a window spans several daily indices
_ALL_TERMS = 10_000
# Device IPs per alert-count search: under index.max_terms_count (65,536) and search.max_buckets
_ALERT_IP_CHUNK = 10_000


def _parse_int_param(request: web.Request, name: str, default: int) -> int:
    """Parse an integer query parameter with a fallback default."""
    raw = request.query.get(name, "")
    if raw:
        try:
            return max(1, int(raw))
        except (ValueError, TypeError):
            pass
    return default


def _bandwidth_interval(from_ts: str, to_ts: str) -> str:
    """Bucket size for the device bandwidth chart: about 170-290 points for any range.

    5 minutes up to a day (as before), 1 hour up to 7 days, 3 hours beyond (#87: with
    min_doc_count 0 and extended bounds, 30 days at 5 minutes was 8,640 buckets).
    """
    try:
        t0 = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
        span = (t1 - t0).total_seconds()
    except (ValueError, TypeError):
        return "5m"
    if span <= 86400:
        return "5m"
    if span <= 7 * 86400:
        return "1h"
    return "3h"


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


def _lan_device_bool_query(app: Mapping[str, Any], from_ts: str, to_ts: str) -> dict:
    """Bool query for LAN-source Zeek conn records, minus excluded IPs.

    Shared by the device list, the device count and the device registry
    refresh so they always agree.
    """
    bool_query: dict = {
        "filter": [
            _time_range_filter(from_ts, to_ts),
            {"term": {"event.provider": "zeek"}},
            # OLD CODE START — F1: also counted conn_long.log interim records
            # {"term": {"event.dataset": "conn"}},
            # OLD CODE END
            CONN_ACCOUNTING,
            app.get("lan_filter", RFC1918_SOURCE_FILTER),
        ],
    }
    excluded = build_excluded_ips_filter(app.get("excluded_ips", []))
    if excluded:
        bool_query["must_not"] = excluded
    return bool_query


def _device_bool_query(request: web.Request, from_ts: str, to_ts: str) -> dict:
    """_lan_device_bool_query for the request's app."""
    # OLD CODE START — 2026-11-01: body moved to _lan_device_bool_query(app); the registry refresh has the app but no request
    # bool_query: dict = {
    #     "filter": [
    #         _time_range_filter(from_ts, to_ts),
    #         {"term": {"event.provider": "zeek"}},
    #         {"term": {"event.dataset": "conn"}},
    #         request.app.get("lan_filter", RFC1918_SOURCE_FILTER),
    #     ],
    # }
    # excluded = build_excluded_ips_filter(request.app.get("excluded_ips", []))
    # if excluded:
    #     bool_query["must_not"] = excluded
    # return bool_query
    # OLD CODE END
    return _lan_device_bool_query(request.app, from_ts, to_ts)


def _is_skipped_device_ip(ip: str) -> bool:
    """True for broadcast, network-address and multicast IPs, which are not devices."""
    return ip.endswith(".255") or ip.endswith(".0") or ip.startswith("224.")


def _now_ms() -> int:
    """The daemon's clock in whole epoch milliseconds, so JavaScript reads the same instant."""
    return time.time_ns() // 1_000_000


def _iso_ms(ms: int) -> str:
    """Whole epoch milliseconds as ISO UTC with exactly three fractional digits."""
    when = datetime.fromtimestamp(ms // 1000, tz=timezone.utc)
    return f"{when:%Y-%m-%dT%H:%M:%S}.{ms % 1000:03d}Z"


# The list's sorts, read from each device bucket (alerts are counted separately)
# OLD CODE START — NET-226: bytes and connections were the started side's, from the bucket
#     "bytes": lambda b: b.get("total_bytes", {}).get("value") or 0,
#     "connections": lambda b: b.get("doc_count", 0),
# OLD CODE END
_SORT_VALUE = {
    # both sides and IPv6, from _accounted_devices
    "bytes": lambda b: b.get("total_bytes") or 0,
    "connections": lambda b: b.get("connection_count", 0),
    "last_seen": lambda b: b.get("last_seen", {}).get("value") or 0,
    "first_seen": lambda b: b.get("first_seen", {}).get("value") or 0,
}


def _ip_order(ip: str) -> tuple:
    """IPv4 before IPv6, each in numeric order; anything unparsable last, by text."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return (99, 0, ip)
    return (addr.version, int(addr), "")


def _ranked(buckets: list[dict], key: Any, descending: bool) -> list[dict]:
    """Buckets by `key`; ties by bytes (largest first), then IP, so the order is stable."""
    by_ip = sorted(buckets, key=lambda b: _ip_order(b["key"]))
    by_bytes = sorted(by_ip, key=_SORT_VALUE["bytes"], reverse=True)
    return sorted(by_bytes, key=key, reverse=descending)


def _alert_sides(reply: Any) -> list[list[dict]]:
    """Both sides' per-IP buckets from an alert-count reply; QueryFailed if it is incomplete."""
    aggs = checked(reply, "device alert counts", ("by_ip", "by_dst"))["aggregations"]
    sides = [
        (aggs[side].get("ips") or {}).get("buckets") for side in ("by_ip", "by_dst")
    ]
    if any(not isinstance(side, list) for side in sides):
        raise QueryFailed("device alert counts: missing aggregation")
    return sides


def _incomplete(where: str, exc: QueryFailed) -> web.Response:
    """The 502 for a search that answered only in part, never a smaller figure."""
    logger.error("Incomplete search in %s: %s", where, exc)
    return web.json_response({"error": "The device search was incomplete"}, status=502)


# A record its responder answered: a probe of an empty address is no device (NET-226 follow-up)
_RESPONDED = {"range": {"destination.packets": {"gt": 0}}}
# Answer-only devices per search of their other aggregations
_ANSWER_CHUNK = 1_000
_OTHER_SIDE = {"source": "destination", "destination": "source"}


def _swapped(body: Any) -> Any:
    """`body` with every source.* and destination.* field name swapped: the answering side's view."""
    if isinstance(body, dict):
        return {_swapped(k): _swapped(v) for k, v in body.items()}
    if isinstance(body, list):
        return [_swapped(v) for v in body]
    if not isinstance(body, str):
        return body
    side, dot, rest = body.partition(".")
    return f"{_OTHER_SIDE[side]}.{rest}" if dot and side in _OTHER_SIDE else body


def _lan_answer_bool_query(app: Mapping[str, Any], from_ts: str, to_ts: str) -> dict:
    """_lan_device_bool_query seen from the answering side: records a LAN address answered.

    The LAN rule comes from the subnets that start internet connections, so a VLAN whose hosts
    only answer is in it only when LAN_SUBNETS lists it.
    """
    query = _swapped(_lan_device_bool_query(app, from_ts, to_ts))
    return {**query, "filter": [*query["filter"], _RESPONDED]}


def _ip_buckets(
    client: Any, query: dict, field: str, aggs, page_size: int, what: str | None
) -> dict[str, dict]:
    """{ip: composite bucket} of `field` over `query`, checked and capped as the device reads are."""
    buckets, complete = all_buckets(
        client,
        NETWORK_INDEX,
        {"bool": query},
        [{"ip": {"terms": {"field": field}}}],
        aggs=aggs,
        page_size=page_size,
        **({"max_buckets": _DEVICE_CAP} if what else {}),
        what=what,
    )
    # PR #191 review: a capped read is not every device, so a checked one fails instead
    if not complete and what:
        raise QueryFailed(f"{what}: stopped at {len(buckets)} IPs")
    if not complete:
        logger.warning(
            "Device buckets stopped at %d IPs; figures cover those only", len(buckets)
        )
    return {b["key"]["ip"]: {**b, "key": b["key"]["ip"]} for b in buckets}


def _time_bounds(aggs: dict | None) -> dict[str, str]:
    """{name: "min" or "max"} for the aggregations that are a bound of @timestamp."""
    return {
        name: kind
        for name, agg in (aggs or {}).items()
        for kind in ("min", "max")
        if (agg.get(kind) or {}).get("field") == "@timestamp"
    }


def _merged_bounds(bucket: dict, answered: dict | None, bounds: dict[str, str]) -> dict:
    """`bucket` with each time bound the earlier (min) or later (max) of its own and `answered`'s."""
    pick = {"min": min, "max": max}
    merged = {}
    for name, kind in bounds.items():
        seen = [
            b
            for b in (bucket.get(name), (answered or {}).get(name))
            if b and b.get("value") is not None
        ]
        if seen:
            merged[name] = pick[kind](seen, key=lambda b: b["value"])
    return {**bucket, **merged}


def _answered_aggs(
    client: Any, query: dict, ips: list[str], aggs: dict, what: str
) -> dict[str, dict]:
    """{ip: `aggs` over the records each IP answered, read from its side}; every IP must come back."""
    out: dict[str, dict] = {}
    for start in range(0, len(ips), _ANSWER_CHUNK):
        chunk = ips[start : start + _ANSWER_CHUNK]
        filters = [*query["filter"], {"terms": {"destination.ip": chunk}}]
        body = {
            "size": 0,
            "query": {"bool": {**query, "filter": filters}},
            "aggs": {
                "ips": {
                    "terms": {"field": "destination.ip", "size": len(chunk)},
                    "aggs": _swapped(aggs),
                }
            },
        }
        reply = checked(client.search(index=NETWORK_INDEX, body=body), what, ("ips",))
        got = {b["key"]: b for b in reply["aggregations"]["ips"].get("buckets") or []}
        if set(chunk) - set(got):
            raise QueryFailed(f"{what}: {len(set(chunk) - set(got))} IPs missing")
        out = {**out, **got}
    return out


def _lan_device_buckets(
    client: Any,
    app: Mapping[str, Any],
    from_ts: str,
    to_ts: str,
    aggs: dict | None = None,
    page_size: int = PAGE_SIZE,
    what: str | None = None,
) -> list[dict]:
    """Every device GET /api/devices can list, however many there are (#96).

    Same filters, _MIN_CONNECTIONS threshold and skip rules as the list. Each bucket is
    shaped like a terms bucket ("key" is the IP), with `aggs` per device. With `what`, an
    incomplete page raises QueryFailed instead of reading as fewer devices.

    NET-226 follow-up: a LAN address that answered _MIN_CONNECTIONS connections is a device
    too (a NAS, a media server). A time bound in `aggs` (a min or max of @timestamp) covers
    the records it started and the ones it answered. A device that started none is
    {"answer_only": True, "doc_count": 0}, with the other aggs except sums read from its side
    of the records it answered.
    """
    # OLD CODE START — NET-226 follow-up: only the IPs that started connections were devices
    # buckets, complete = all_buckets(
    #     client,
    #     NETWORK_INDEX,
    #     {"bool": _lan_device_bool_query(app, from_ts, to_ts)},
    #     [{"ip": {"terms": {"field": "source.ip"}}}],
    #     aggs=aggs,
    #     page_size=page_size,
    #     **({"max_buckets": _DEVICE_CAP} if what else {}),
    #     what=what,
    # )
    # # PR #191 review: a capped read is not every device, so a checked one fails instead
    # if not complete and what:
    #     raise QueryFailed(f"{what}: stopped at {len(buckets)} IPs")
    # if not complete:
    #     logger.warning(
    #         "Device buckets stopped at %d IPs; figures cover those only", len(buckets)
    #     )
    # return [
    #     {**b, "key": b["key"]["ip"]}
    #     for b in buckets
    #     if b.get("doc_count", 0) >= _MIN_CONNECTIONS
    #     and not _is_skipped_device_ip(b["key"]["ip"])
    # ]
    # OLD CODE END
    bounds = _time_bounds(aggs)
    started = _ip_buckets(
        client,
        _lan_device_bool_query(app, from_ts, to_ts),
        "source.ip",
        aggs,
        page_size,
        what,
    )
    answer_query = _lan_answer_bool_query(app, from_ts, to_ts)
    answered = _ip_buckets(
        client,
        answer_query,
        "destination.ip",
        {name: aggs[name] for name in bounds} or None,
        page_size,
        what,
    )
    members = [
        ip
        for ip in {**started, **answered}
        if not _is_skipped_device_ip(ip)
        and max(
            (started.get(ip) or {}).get("doc_count", 0),
            (answered.get(ip) or {}).get("doc_count", 0),
        )
        >= _MIN_CONNECTIONS
    ]
    only_answered = [ip for ip in members if ip not in started]
    others = {
        n: a for n, a in (aggs or {}).items() if n not in bounds and "sum" not in a
    }
    extra = (
        _answered_aggs(
            client, answer_query, only_answered, others, what or "answer-only devices"
        )
        if others and only_answered
        else {}
    )
    return [
        _merged_bounds(started[ip], answered.get(ip), bounds)
        if ip in started
        else {
            **answered[ip],
            **extra.get(ip, {}),
            "key": ip,
            "doc_count": 0,
            "answer_only": True,
        }
        for ip in members
    ]


# ---------------------------------------------------------------------------
# NET-226: a device's traffic is both sides of its connections, plus its IPv6 by MAC
# ---------------------------------------------------------------------------

# Per device, from the connections it started: sums, bounds and its most common MAC. The
# Painless total_bytes sum is gone: the list ranks in Python, and it was half the search's time.
_DEVICE_AGGS = {
    **STARTED,
    "protocols": {"terms": {"field": "network.transport", "size": 10}},
    "first_seen": {"min": {"field": "@timestamp"}},
    "last_seen": {"max": {"field": "@timestamp"}},
    "with_mac": {"terms": {"field": "source.mac", "size": 1}},
}


def _conn_filters(from_ts: str, to_ts: str) -> list[dict]:
    """Every final conn record in the window, whoever took part (the answered and IPv6 reads)."""
    return [
        _time_range_filter(from_ts, to_ts),
        {"term": {"event.provider": "zeek"}},
        CONN_ACCOUNTING,
    ]


def _bucket_mac(bucket: dict) -> str | None:
    """The MAC most of a device bucket's started connections carry (its with_mac terms)."""
    macs = (bucket.get("with_mac") or {}).get("buckets") or []
    return macs[0]["key"] if macs else None


def _ipv6_owners(rows: list[tuple[str, str | None, int]]) -> dict[str, str]:
    """{mac: ip} from (ip, mac, started connections) rows of listed devices.

    A MAC's IPv6 goes to one row only: the one with most started connections, ties to the
    lowest address. The list and the device page both decide through this.
    """
    owners: dict[str, str] = {}
    for ip, mac, _ in sorted(rows, key=lambda r: (-r[2], _ip_order(r[0]))):
        if mac:
            owners.setdefault(mac, ip)
    return owners


def _ipv6_shares(
    client: Any, app: Mapping[str, Any], filters: list[dict], macs: list[str], what: str
) -> dict[str, dict]:
    """fold_ipv6() for `macs`; gateways are only asked about MACs whose IPv6 could be forwarded."""
    per_mac = ipv6_by_mac(client, filters, macs, f"{what} (IPv6)")
    gateways = gateway_macs(
        client,
        filters,
        app.get("lan_filter"),
        forwarded_macs(per_mac),
        f"{what} (gateways)",
    )
    return fold_ipv6(per_mac, gateways)


def _accounted_devices(
    client: Any, app: Mapping[str, Any], from_ts: str, to_ts: str, what: str
) -> list[dict]:
    """Every listed device with its traffic from both sides and its IPv6 (NET-226).

    Membership and first/last seen come from _lan_device_buckets, so the count, the registry
    and risk still agree with the list. Each bucket gains connection_count, upload_bytes,
    download_bytes, total_bytes, ipv6_connections, ipv6_left_out(_reason) and mac.
    QueryFailed if any read is incomplete.
    """
    buckets = _lan_device_buckets(
        client, app, from_ts, to_ts, aggs=_DEVICE_AGGS, what=what
    )
    filters = _conn_filters(from_ts, to_ts)
    answered = answered_by_ip(
        client, filters, [b["key"] for b in buckets], f"{what} (answered)"
    )
    # OLD CODE START — NET-226 follow-up: every row could own IPv6; the device page's
    # _ipv6_mac_of only lets one that started _MIN_CONNECTIONS
    # owners = _ipv6_owners(
    #     [(b["key"], _bucket_mac(b), b.get("doc_count", 0)) for b in buckets]
    # )
    # OLD CODE END
    owners = _ipv6_owners(
        [
            (b["key"], _bucket_mac(b), b.get("doc_count", 0))
            for b in buckets
            if b.get("doc_count", 0) >= _MIN_CONNECTIONS
        ]
    )
    shares = _ipv6_shares(client, app, filters, sorted(owners), what)
    by_ip = {owners[mac]: share for mac, share in shares.items()}
    rows = []
    for b in buckets:
        v6 = by_ip.get(b["key"]) or {}
        both = add(totals(b), answered.get(b["key"]), v6.get("totals"))
        rows.append(
            {
                **b,
                "mac": _bucket_mac(b),
                "connection_count": both["connections"],
                "upload_bytes": both["upload"],
                "download_bytes": both["download"],
                "total_bytes": both["upload"] + both["download"],
                "ipv6_connections": (v6.get("totals") or {}).get("connections", 0),
                "ipv6_left_out": v6.get("left_out", 0),
                "ipv6_left_out_reason": v6.get("reason"),
            }
        )
    return rows


def _ipv6_mac_of(
    client: Any, app: Mapping[str, Any], ip: str, from_ts: str, to_ts: str
) -> str | None:
    """The MAC whose IPv6 the device list folds into this IP's row, or None (NET-226).

    The list's rule on the list's records: the IP must be a listed device, the MAC its most
    common, and _ipv6_owners must pick it over every other device with that MAC.
    """
    base = _lan_device_bool_query(app, from_ts, to_ts)

    def rows(clause: dict) -> list[tuple[str, str | None, int]]:
        body = {
            "size": 0,
            "query": {"bool": {**base, "filter": [*base["filter"], clause]}},
            "aggs": {
                "ips": {
                    "terms": {"field": "source.ip", "size": _ALL_TERMS},
                    "aggs": {"with_mac": _DEVICE_AGGS["with_mac"]},
                }
            },
        }
        reply = checked(
            client.search(index=NETWORK_INDEX, body=body), "device IPv6 owner", ("ips",)
        )
        return [
            (b["key"], _bucket_mac(b), b.get("doc_count", 0))
            for b in reply["aggregations"]["ips"].get("buckets") or []
            if b.get("doc_count", 0) >= _MIN_CONNECTIONS
            and not _is_skipped_device_ip(b["key"])
        ]

    own = rows({"term": {"source.ip": ip}})
    mac = own[0][1] if own else None
    if mac is None:
        return None
    # Other devices whose records carry this MAC; only those whose most common MAC it is count
    others = [r[0] for r in rows({"term": {"source.mac": mac}}) if r[0] != own[0][0]]
    rivals = rows({"terms": {"source.ip": others}}) if others else []
    return mac if _ipv6_owners([*own, *rivals]).get(mac) == own[0][0] else None


def _get_client(request: web.Request):
    """Retrieve the OpenSearch client from the StorageManager on the app."""
    storage: StorageManager = request.app["storage"]
    return storage._client


def _mac_key(mac: str | None) -> str:
    """A MAC the way the registry keys it (DeviceRegistry._normalize_mac)."""
    return DeviceRegistry._normalize_mac(mac) if mac else ""


def _registry_names(request: web.Request, macs: list[str]) -> dict[str, str]:
    """{normalized MAC: the name Home shows} for the MACs the device registry knows (#130).

    The registry names a device by its MAC (UniFi alias, the owner's name, then the name it
    gave DHCP), which DNS records can't do reliably; Devices and Home now agree.
    """
    registry = request.app.get("device_registry")
    if registry is None or not macs:
        return {}
    try:
        known = registry.get_devices(macs)
    except Exception as exc:
        logger.warning(
            "Device names from the registry unavailable, using DNS names: %s", exc
        )
        return {}
    # OLD CODE START — NET-200: the owner's name would reach _device_category; it is applied after
    # return {
    #     mac: name
    #     for mac, device in known.items()
    #     if (name := registry.get_name(device))
    # }
    # OLD CODE END
    return {
        mac: name
        for mac, device in known.items()
        if (name := registry.get_name(device, own=False))
    }


def _with_owner(request: web.Request, device: dict) -> dict:
    """NET-200: a copy with the owner's name, icon and picture, for presentation only.

    Applied after classification, so a cosmetic rename never moves a device between categories.
    """
    custom = request.app.get("device_custom")
    return custom.present(device) if custom is not None else device


def _get_fingerprint(request: web.Request) -> DeviceFingerprint:
    """Retrieve the DeviceFingerprint service from the app."""
    return request.app["device_fingerprint"]


# ---------------------------------------------------------------------------
# Helpers — device classification
# ---------------------------------------------------------------------------


# Vendors that make one kind of device, as lowercase substrings of the IEEE vendor name.
# Mixed vendors (Apple, Google, Samsung, Amazon, TP-Link) are left out on purpose.
_VENDOR_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("philips lighting", "iot"),
    ("signify", "iot"),
    ("tuya", "iot"),
    ("espressif", "iot"),
    ("shelly", "iot"),
    ("lifx", "iot"),
    ("ecobee", "iot"),
    ("wyze", "iot"),
    ("itead", "iot"),
    ("nest labs", "iot"),
    ("ring llc", "iot"),
    ("belkin", "iot"),
    ("sonos", "media"),
    ("roku", "media"),
    ("ubiquiti", "infrastructure"),
    ("cisco", "infrastructure"),
    ("netgear", "infrastructure"),
    ("aruba", "infrastructure"),
    ("juniper", "infrastructure"),
    ("mikrotik", "infrastructure"),
    # Arcadyan left out: it makes ISP routers but also the Wi-Fi modules in LG TVs ("LGwebOSTV")
    ("routerboard", "infrastructure"),
    ("synology", "infrastructure"),
    ("qnap", "infrastructure"),
    ("western digital", "infrastructure"),
    ("raspberry pi", "computer"),
    ("proxmox", "computer"),
    ("micro-star", "computer"),
    ("jwipc", "computer"),
    ("dell", "computer"),
    ("lenovo", "computer"),
)
_PHONE_HOSTNAME_HINTS = ("iphone", "ipad", "android", "galaxy", "pixel")
_COMPUTER_HOSTNAME_HINTS = (
    "macbook",
    "imac",
    "mac-studio",
    "mac-mini",
    "desktop",
    "laptop",
)
# Checked first: "nintendo-switch" must not match the IoT hint "switch", and a
# Chromecast's UA says "Linux"
_MEDIA_HOSTNAME_HINTS = (
    "xbox",
    "playstation",
    "ps4",
    "ps5",
    "nintendo",
    "roku",
    "appletv",
    "apple-tv",
    "chromecast",
    "firetv",
    "fire-tv",
    "webostv",
)


def _vendor_category(manufacturer: str | None) -> str:
    """Category implied by a single-purpose vendor, else "unknown" (#26)."""
    vendor = (manufacturer or "").lower()
    return next((cat for key, cat in _VENDOR_CATEGORIES if key in vendor), "unknown")


def _device_category(
    os_hint: str | None, hostname: str | None, manufacturer: str | None = None
) -> str:
    """Classify a device into a broad category based on OS hint, hostname and vendor."""
    # A console or streamer name beats a generic OS label (a Chromecast reports "Linux")
    if hostname and any(x in hostname.lower() for x in _MEDIA_HOSTNAME_HINTS):
        return "media"
    if not os_hint:
        # Fall back to hostname-based heuristics
        if hostname:
            hn = hostname.lower()
            if any(
                x in hn
                for x in [
                    "ring",
                    "nest",
                    "hue",
                    "smart",
                    "cam",
                    "thermostat",
                    "switch",
                    "plug",
                    "sensor",
                ]
            ):
                return "iot"
            if any(x in hn for x in ["printer", "brother", "hp-", "epson", "canon"]):
                return "infrastructure"
            if any(
                x in hn
                for x in ["router", "gateway", "switch", "ap-", "access-point", "unifi"]
            ):
                return "infrastructure"
            if any(x in hn for x in _PHONE_HOSTNAME_HINTS):
                return "phone"
            if any(x in hn for x in _COMPUTER_HOSTNAME_HINTS):
                return "computer"
        # OLD CODE START — the vendor was ignored, so Hue bulbs and UniFi gear read "unknown" (#26)
        # return "unknown"
        # OLD CODE END
        return _vendor_category(manufacturer)
    os_lower = os_hint.lower()
    if os_lower in ("ios", "android"):
        return "phone"
    # OLD CODE START — the OS hints are "Windows 10/11", "Windows 8.1"..., never plain
    # "windows", so Windows PCs fell through; consoles matched nothing
    # if os_lower in ("windows", "macos", "linux", "chromeos"):
    #     return "computer"
    # if os_lower in ("smart tv", "roku", "fire tv"):
    #     return "media"
    # OLD CODE END
    if os_lower.startswith("windows") or os_lower in ("macos", "linux", "chromeos"):
        return "computer"
    if os_lower in ("smart tv", "roku", "fire tv", "xbox", "playstation", "nintendo"):
        return "media"
    # Check hostname for IoT indicators
    if hostname:
        hn = hostname.lower()
        if any(
            x in hn
            for x in [
                "ring",
                "nest",
                "hue",
                "smart",
                "cam",
                "thermostat",
                "switch",
                "plug",
                "sensor",
            ]
        ):
            return "iot"
        if any(x in hn for x in ["printer", "brother", "hp-", "epson", "canon"]):
            return "infrastructure"
        if any(
            x in hn
            for x in ["router", "gateway", "switch", "ap-", "access-point", "unifi"]
        ):
            return "infrastructure"
    # OLD CODE START — see above (#26)
    # return "unknown"
    # OLD CODE END
    return _vendor_category(manufacturer)


def _category_basis(
    os_hint: str | None, hostname: str | None, manufacturer: str | None
) -> str | None:
    """What _device_category's guess rests on: "name", "os", "vendor", or None when unknown.

    Follows its order: a console or streamer name, then a recognised OS, then other name hints,
    then the vendor.
    """
    if _device_category(os_hint, hostname, manufacturer) == "unknown":
        return None
    if hostname and any(x in hostname.lower() for x in _MEDIA_HOSTNAME_HINTS):
        return "name"
    if os_hint and _device_category(os_hint, None, None) != "unknown":
        return "os"
    if _device_category(os_hint, hostname, None) != "unknown":
        return "name"
    return "vendor"


def _guesses(
    os_hint: str | None, hostname: str | None, manufacturer: str | None
) -> dict:
    """B-h: the type and OS guesses with what each rests on, so the page can say so."""
    return {
        "category": _device_category(os_hint, hostname, manufacturer),
        "category_basis": _category_basis(os_hint, hostname, manufacturer),
        # the OS hint only ever comes from plaintext HTTP user agents (fingerprint)
        "os_basis": "web traffic" if os_hint else None,
    }


def _device_sides(ip: str, mac: str | None, link_local_only: bool) -> tuple[dict, dict]:
    """(started, answered) clauses for one device: its address, and its IPv6 by MAC."""

    def side(field: str) -> dict:
        own = [{"term": {f"{field}.ip": ip}}]
        if mac:
            own = [*own, ipv6_clause(field, mac, link_local_only)]
        return {"bool": {"should": own, "minimum_should_match": 1}}

    return side("source"), side("destination")


# The traffic figures _accounted_devices adds to each device bucket
_TRAFFIC_FIELDS = (
    "connection_count",
    "upload_bytes",
    "download_bytes",
    "total_bytes",
    "ipv6_connections",
    "ipv6_left_out",
    "ipv6_left_out_reason",
)


def _traffic_fields(bucket: dict) -> dict:
    return {k: bucket[k] for k in _TRAFFIC_FIELDS}


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@in_thread
def handle_device_list(request: web.Request) -> web.Response:
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

    # OLD CODE START — replaced 2026-11-01: 20 hid quiet phones/IoT; now module-level _MIN_CONNECTIONS = 3, shared with the count
    # # Minimum connection threshold — IPs with fewer connections are noise
    # # (ARP probes, broadcast replies, one-off scans)
    # _MIN_CONNECTIONS = 20
    # OLD CODE END

    # OLD CODE START — slice 2b-3: the terms list's order; every sort is ranked in Python now
    # # Map user-facing sort names to aggregation sort keys
    # sort_map = {
    #     "bytes": "total_bytes",
    #     "connections": "_count",
    #     "last_seen": "last_seen",
    #     "first_seen": "first_seen",
    #     "alerts": "total_bytes",  # Alert sort handled post-query
    # }
    # agg_sort_key = sort_map.get(sort_field, "total_bytes")
    # OLD CODE END

    # OLD CODE START — #96: the alert sort only saw the top 2 x limit devices by bytes, so a
    # quieter device with more alerts was never listed
    # # Fetch more than needed if sorting by alerts (post-query sort)
    # fetch_size = limit * 2 if sort_field == "alerts" else limit
    # OLD CODE END
    # OLD CODE START — slice 2b-3: the terms list's size; every device is read now
    # fetch_size = limit
    # OLD CODE END

    # OLD CODE START — replaced 2026-11-01: moved into _device_bool_query so the count uses the same filters
    # excluded = build_excluded_ips_filter(request.app.get("excluded_ips", []))
    # bool_query: dict = {
    #     "filter": [
    #         _time_range_filter(from_ts, to_ts),
    #         {"term": {"event.provider": "zeek"}},
    #         {"term": {"event.dataset": "conn"}},
    #         request.app.get("lan_filter", RFC1918_SOURCE_FILTER),
    #     ],
    # }
    # if excluded:
    #     bool_query["must_not"] = excluded
    # OLD CODE END
    # OLD CODE START — slice 2b-3 review: _lan_device_buckets builds this query itself now
    # bool_query = _device_bool_query(request, from_ts, to_ts)
    # OLD CODE END

    # No DHCP pre-filter — DHCP data may not be available (NetTap captures
    # between modem and router, DHCP happens on the LAN side). Instead, use
    # min_doc_count on the terms aggregation to filter noise IPs.

    # OLD CODE START — slice 2b-3: a terms list ordered by a sub-aggregation with size = the
    # limit is approximate across shards once a shard holds more IPs than its shard_size, and
    # skipped IPs came off after the cut, so the list could disagree with the count
    # query = {
    #     "size": 0,
    #     "query": {"bool": bool_query},
    #     "aggs": {
    #         "devices": {
    #             "terms": {
    #                 "field": "source.ip",
    #                 "size": fetch_size,
    #                 "min_doc_count": _MIN_CONNECTIONS,
    #                 "order": {agg_sort_key: sort_order},
    #             },
    #             "aggs": { ...the per-device aggregations below... },
    #         }
    #     },
    # }
    # OLD CODE END
    # OLD CODE START — NET-226: started-side sums only; _DEVICE_AGGS + _accounted_devices now
    # # Per device: the same sums and bounds the terms list carried
    # device_aggs = {
    #     "total_bytes": {"sum": {"script": {"source": "(doc['source.bytes']...) + (doc['destination.bytes']...)", "lang": "painless"}}},
    #     # Same split as handle_device_detail: sent (orig) vs received (resp)
    #     "orig_bytes": {"sum": {"field": "source.bytes"}},
    #     "resp_bytes": {"sum": {"field": "destination.bytes"}},
    #     "protocols": {"terms": {"field": "network.transport", "size": 10}},
    #     "first_seen": {"min": {"field": "@timestamp"}},
    #     "last_seen": {"max": {"field": "@timestamp"}},
    # }
    # OLD CODE END

    try:
        # OLD CODE START — #96: the alert sort read the same capped list
        # result = client.search(index=NETWORK_INDEX, body=query)
        # OLD CODE END
        # OLD CODE START — slice 2b-3: only the alert sort read every device
        # if sort_field == "alerts":
        #     # Every device: alert counts aren't in conn records, so the top `limit` is picked below
        #     buckets = _lan_device_buckets(
        #         client,
        #         request.app,
        #         from_ts,
        #         to_ts,
        #         aggs=query["aggs"]["devices"]["aggs"],
        #     )
        # else:
        #     result = client.search(index=NETWORK_INDEX, body=query)
        #     buckets = (
        #         result.get("aggregations", {}).get("devices", {}).get("buckets", [])
        #     )
        # OLD CODE END
        # Every device, through the count's own helper, so the list and the count agree.
        # OLD CODE START — PR 2 (reliability): only this read was off the loop; the alert
        # counts, fingerprint and registry lookups below still blocked it
        # # PR #191 review: off the event loop, so a long read never stalls /api/health
        # buckets = await asyncio.get_running_loop().run_in_executor(
        #     None,
        #     lambda: _lan_device_buckets(
        #         client,
        #         request.app,
        #         from_ts,
        #         to_ts,
        #         aggs=device_aggs,
        #         what="device list",
        #     ),
        # )
        # OLD CODE END
        # The whole handler runs in a worker thread, so /api/health never waits on it
        # OLD CODE START — NET-226: the started side only
        # buckets = _lan_device_buckets(
        #     client, request.app, from_ts, to_ts, aggs=device_aggs, what="device list"
        # )
        # OLD CODE END
        buckets = _accounted_devices(client, request.app, from_ts, to_ts, "device list")
    except QueryFailed as exc:
        return _incomplete("devices list", exc)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in devices list: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    # The page's device figures come from this one reading (slice 2b-3), not separate counts
    as_of_ms = _now_ms()
    online_since_ms = as_of_ms - _ONLINE_MS
    total = len(buckets)
    online_total = sum(
        1
        for b in buckets
        if (b.get("last_seen", {}).get("value") or 0) >= online_since_ms
    )
    if sort_field != "alerts":
        # Alert counts are asked below for the listed devices only
        buckets = _ranked(buckets, _SORT_VALUE[sort_field], sort_order == "desc")[
            :limit
        ]

    # OLD CODE START — #96: moved into the try above
    # buckets = result.get("aggregations", {}).get("devices", {}).get("buckets", [])
    # OLD CODE END

    # Collect all device IPs for batch alert count query
    device_ips = [b["key"] for b in buckets]

    # Batch query: alert counts per device IP from suricata-*
    # OLD CODE START — #96: one terms filter of every IP failed past 65,536 devices
    # (index.max_terms_count) on the alert sort, and any failure listed every device with 0 alerts
    # alert_counts: dict[str, int] = {}
    # if device_ips:
    #     alert_query = {... {"terms": {"source.ip": device_ips}} ... size len(device_ips)}
    #     try:
    #         alert_result = client.search(index=NETWORK_INDEX, body=alert_query)
    #         for ab in alert_result.get("aggregations", {}).get("by_ip", {}).get("buckets", []):
    #             alert_counts[ab["key"]] = ab["doc_count"]
    #     except OpenSearchException as exc:
    #         logger.warning("Alert count query failed: %s", exc)
    # OLD CODE END
    alert_counts: dict[str, int] = {}
    for start in range(0, len(device_ips), _ALERT_IP_CHUNK):
        chunk = device_ips[start : start + _ALERT_IP_CHUNK]
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
                        # OLD CODE START — PR #174 review: alerts the device sent only, while
                        # its detail page (NET-158, D4) counts alerts on its traffic both ways
                        # {"terms": {"source.ip": chunk}},
                        # OLD CODE END
                        {
                            "bool": {
                                "should": [
                                    {"terms": {"source.ip": chunk}},
                                    {"terms": {"destination.ip": chunk}},
                                ],
                                "minimum_should_match": 1,
                            }
                        },
                        {"term": {"event.provider": "suricata"}},
                        {"term": {"event.dataset": "alert"}},
                    ],
                    "must_not": SURICATA_NOISE_EXCLUSION,
                }
            },
            # OLD CODE START — PR #174 review: source side only
            # "aggs": {"by_ip": {"terms": {"field": "source.ip", "size": len(chunk)}}},
            # OLD CODE END
            # Each side's terms run inside a filter on this chunk, so every bucket is a device here.
            # shortcut: an alert whose source and destination are the same device counts twice;
            # the bridge never sees a device talk to itself, so this stays a sum
            "aggs": {
                side: {
                    "filter": {"terms": {field: chunk}},
                    "aggs": {"ips": {"terms": {"field": field, "size": len(chunk)}}},
                }
                for side, field in (
                    ("by_ip", "source.ip"),
                    ("by_dst", "destination.ip"),
                )
            },
        }

        try:
            alert_result = client.search(index=NETWORK_INDEX, body=alert_query)
            # slice 2b-3: a timed-out or partly failed reply read as 0 alerts
            sides = _alert_sides(alert_result)
        except QueryFailed as exc:
            return _incomplete("devices list alert counts", exc)
        except OpenSearchException as exc:
            logger.error("Alert count query failed in devices list: %s", exc)
            return web.json_response(
                {"error": f"OpenSearch query failed: {exc}"}, status=502
            )
        # OLD CODE START — PR #174 review: source side only
        # for ab in (
        #     alert_result.get("aggregations", {}).get("by_ip", {}).get("buckets", [])
        # ):
        #     alert_counts[ab["key"]] = ab["doc_count"]
        # OLD CODE END
        # OLD CODE START — slice 2b-3: read the reply unchecked; _alert_sides checks it above
        # aggs = alert_result.get("aggregations", {})
        # for side in ("by_ip", "by_dst"):
        #     for ab in aggs.get(side, {}).get("ips", {}).get("buckets", []):
        #         alert_counts[ab["key"]] = (
        #             alert_counts.get(ab["key"], 0) + ab["doc_count"]
        #         )
        # OLD CODE END
        for side in sides:
            for ab in side:
                alert_counts[ab["key"]] = (
                    alert_counts.get(ab["key"], 0) + ab["doc_count"]
                )

    if sort_field == "alerts":
        # OLD CODE START — slice 2b-3: the same rule, now shared with every sort (and IP last)
        # # Bytes (largest first) breaks ties, as the bytes-ordered list did before
        # by_bytes = sorted(
        #     buckets,
        #     key=lambda b: b.get("total_bytes", {}).get("value", 0) or 0,
        #     reverse=True,
        # )
        # buckets = sorted(
        #     by_bytes,
        #     key=lambda b: alert_counts.get(b["key"], 0),
        #     reverse=(sort_order == "desc"),
        # )[:limit]
        # OLD CODE END
        buckets = _ranked(
            buckets, lambda b: alert_counts.get(b["key"], 0), sort_order == "desc"
        )[:limit]

    # Build device list with enrichment — skip broadcast/gateway IPs
    # Fingerprint lookups for every device at once (#21: 4 round trips per device before)
    lookups = fingerprint.lookup_many(
        client,
        [b["key"] for b in buckets if not _is_skipped_device_ip(b["key"])],
        from_ts,
        to_ts,
    )
    names = _registry_names(request, [mac for mac, _, _ in lookups.values() if mac])
    devices = []
    for b in buckets:
        ip = b["key"]

        # Skip broadcast, multicast, and gateway-pattern IPs
        # OLD CODE START — replaced 2026-11-01: moved into _is_skipped_device_ip, shared with the count
        # if ip.endswith(".255") or ip.endswith(".0") or ip.startswith("224."):
        #     continue
        # OLD CODE END
        if _is_skipped_device_ip(ip):
            continue

        # OLD CODE START — NET-226: the started side's bytes and connections only
        # total_bytes = b.get("total_bytes", {}).get("value", 0) or 0
        # orig_bytes = int(b.get("orig_bytes", {}).get("value", 0) or 0)
        # resp_bytes = int(b.get("resp_bytes", {}).get("value", 0) or 0)
        # connection_count = b.get("doc_count", 0)
        # OLD CODE END
        proto_buckets = b.get("protocols", {}).get("buckets", [])
        protocols = [pb["key"] for pb in proto_buckets]
        first_seen = b.get("first_seen", {}).get("value_as_string", "")
        last_seen = b.get("last_seen", {}).get("value_as_string", "")
        alert_count = alert_counts.get(ip, 0)

        # Passive fingerprinting enrichment
        # OLD CODE START — one search per lookup per device (#21); now batched above
        # mac = fingerprint.get_mac_for_ip(client, ip, from_ts, to_ts)
        # hostname = fingerprint.get_hostname_for_ip(client, ip, from_ts, to_ts)
        # os_hint = fingerprint.get_os_hint(client, ip, from_ts, to_ts)
        # OLD CODE END
        mac, hostname, os_hint = lookups.get(ip, (None, None, None))
        # an answer-only device has no MAC of its own records; its answered ones carry it
        mac = mac or b.get("mac")
        hostname = names.get(_mac_key(mac)) or hostname
        manufacturer = fingerprint.get_manufacturer(mac) if mac else None

        # Clean up mDNS service names and reverse DNS that aren't real hostnames
        if hostname:
            if any(
                x in hostname
                for x in ["._tcp.", "._udp.", ".in-addr.arpa", ".ip6.arpa", "_asquic"]
            ):
                hostname = None

        device = {
            "ip": ip,
            "mac": mac,
            "hostname": hostname,
            "manufacturer": manufacturer,
            "os_hint": os_hint,
            # OLD CODE: "category": _device_category(os_hint, hostname, manufacturer), (B-h: with its basis)
            **_guesses(os_hint, hostname, manufacturer),
            "first_seen": first_seen,
            "last_seen": last_seen,
            # OLD CODE START — NET-226: the started side's figures, orig/resp named
            # "total_bytes": total_bytes,
            # "orig_bytes": orig_bytes,
            # "resp_bytes": resp_bytes,
            # "connection_count": connection_count,
            # OLD CODE END
            **_traffic_fields(b),
            "protocols": protocols,
            "alert_count": alert_count,
        }

        # UniFi alias enrichment — merge user-assigned names from controller
        unifi = request.app.get("unifi_integration")
        if unifi and unifi.is_configured:
            alias = None
            if mac:
                alias = unifi.get_device_alias(mac)
            if not alias:
                alias = unifi.get_client_name_by_ip(ip)
            if alias:
                device["unifi_name"] = alias

        # OLD CODE: devices.append(device) (NET-200: the owner's fields, after classification)
        devices.append(_with_owner(request, device))

    # OLD CODE START — #96: sorted the capped list; the buckets are sorted above now
    # # Post-query sort by alerts if requested
    # if sort_field == "alerts":
    #     devices.sort(
    #         key=lambda d: d["alert_count"],
    #         reverse=(sort_order == "desc"),
    #     )
    # OLD CODE END

    # Apply limit after post-sort
    devices = devices[:limit]

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "limit": limit,
            "devices": devices,
            # slice 2b-3: Total devices and Online now on the Devices page, from this reading
            "total": total,
            "online_total": online_total,
            "as_of": _iso_ms(as_of_ms),
            "online_since": _iso_ms(online_since_ms),
        }
    )


@in_thread
def handle_device_detail(request: web.Request) -> web.Response:
    """GET /api/devices/{ip}

    Returns detailed information for a single device, including top
    destinations, DNS queries, and bandwidth time-series.
    """
    ip = request.match_info["ip"]
    # NET-209: an internet address is never a device; checked before any search or fingerprint
    if not lan_check(request.app)(ip):
        return web.json_response({"error": f"{ip} is not on your network"}, status=404)
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)
    fingerprint = _get_fingerprint(request)

    # OLD CODE START — NET-226: only the connections the device started (source.ip), IPv4
    # only, with orig/resp as upload/download; replaced by the device-side query below
    # # Main device aggregation query
    # device_query = {
    #     "size": 0,
    #     "track_total_hits": True,  # #84: hits.total stops at 10,000 without it (the router read 10,000)
    #     "query": {
    #         "bool": {
    #             "filter": [
    #                 _time_range_filter(from_ts, to_ts),
    #                 {"term": {"source.ip": ip}},
    #                 {"term": {"event.provider": "zeek"}},
    #                 # OLD CODE START — F1: also counted conn_long.log interim records
    #                 # {"term": {"event.dataset": "conn"}},
    #                 # OLD CODE END
    #                 CONN_ACCOUNTING,
    #             ]
    #         }
    #     },
    #     "aggs": {
    #         "total_bytes": {
    #             "sum": {
    #                 "script": {
    #                     "source": "(doc['source.bytes'].size() > 0 ? doc['source.bytes'].value : 0) + (doc['destination.bytes'].size() > 0 ? doc['destination.bytes'].value : 0)",
    #                     "lang": "painless",
    #                 }
    #             }
    #         },
    #         "total_orig_bytes": {"sum": {"field": "source.bytes"}},
    #         "total_resp_bytes": {"sum": {"field": "destination.bytes"}},
    #         "unique_destinations": {"cardinality": {"field": "destination.ip"}},
    #         # OLD CODE START — #96: the 10 ASNs with the most connections, then shown in bytes
    #         # order, so a service with fewer but bigger flows was left out
    #         # "top_services": {
    #         #     "terms": {"field": "destination.as.full", "size": 10, "shard_size": _ALL_TERMS},
    #         # OLD CODE END
    #         # Every ASN (biggest first if a device has more), so the top 10 by bytes is exact
    #         # after ASNs of one organisation are merged
    #         "top_services": {
    #             "terms": {
    #                 "field": "destination.as.full",
    #                 "size": _ALL_TERMS,
    #                 "shard_size": _ALL_TERMS,
    #                 "order": {"bytes": "desc"},
    #             },
    #             "aggs": {
    #                 "bytes": {
    #                     "sum": {
    #                         "script": {
    #                             "source": "(doc['source.bytes'].size() > 0 ? doc['source.bytes'].value : 0) + (doc['destination.bytes'].size() > 0 ? doc['destination.bytes'].value : 0)",
    #                             "lang": "painless",
    #                         }
    #                     }
    #                 },
    #             },
    #         },
    #         "protocols": {"terms": {"field": "network.transport", "size": 10}},
    #         "first_seen": {"min": {"field": "@timestamp"}},
    #         "last_seen": {"max": {"field": "@timestamp"}},
    #         # OLD CODE START — #90: top 20 only; unique_destinations came from cardinality, an
    #         # estimate (2,390 for 2,391 on the G11)
    #         # "top_destinations": {
    #         #     "terms": {"field": "destination.ip", "size": 20},
    #         # OLD CODE END
    #         # Every destination, so the top 20 and the unique count are exact
    #         "top_destinations": {
    #             "terms": {"field": "destination.ip", "size": _ALL_TERMS},
    #             "aggs": {
    #                 "bytes": {
    #                     "sum": {
    #                         "script": {
    #                             "source": "(doc['source.bytes'].size() > 0 ? doc['source.bytes'].value : 0) + (doc['destination.bytes'].size() > 0 ? doc['destination.bytes'].value : 0)",
    #                             "lang": "painless",
    #                         }
    #                     }
    #                 },
    #             },
    #         },
    #         "bandwidth_series": {
    #             # OLD CODE START — #120: OpenSearch 3.5's skip-list date_histogram misplaces records
    #             # "date_histogram": {
    #             #     "field": "@timestamp",
    #             #     # OLD CODE START — #87: 5 minutes for every range
    #             #     # "fixed_interval": "5m",
    #             #     # OLD CODE END
    #             #     "fixed_interval": _bandwidth_interval(from_ts, to_ts),
    #             #     "min_doc_count": 0,
    #             #     "extended_bounds": {"min": from_ts, "max": to_ts},
    #             # },
    #             # OLD CODE END
    #             **time_slots(
    #                 from_ts, to_ts, _bandwidth_interval(from_ts, to_ts)
    #             ),  # at most ~720 slots
    #             "aggs": {
    #                 "bytes": {
    #                     "sum": {
    #                         "script": {
    #                             "source": "(doc['source.bytes'].size() > 0 ? doc['source.bytes'].value : 0) + (doc['destination.bytes'].size() > 0 ? doc['destination.bytes'].value : 0)",
    #                             "lang": "painless",
    #                         }
    #                     }
    #                 },
    #                 "download_bytes": {"sum": {"field": "destination.bytes"}},
    #                 "upload_bytes": {"sum": {"field": "source.bytes"}},
    #             },
    #         },
    #     },
    # }
    #
    # try:
    #     result = client.search(index=NETWORK_INDEX, body=device_query)
    # except OpenSearchException as exc:
    #     logger.error("OpenSearch error in device detail: %s", exc)
    #     return web.json_response(
    #         {"error": f"OpenSearch query failed: {exc}"}, status=502
    #     )
    #
    # aggs = result.get("aggregations", {})
    # hits_total = result.get("hits", {}).get("total", {})
    # connection_count = (
    #     hits_total.get("value", 0) if isinstance(hits_total, dict) else hits_total
    # )
    #
    # total_bytes = aggs.get("total_bytes", {}).get("value", 0) or 0
    # orig_bytes = int(aggs.get("total_orig_bytes", {}).get("value", 0) or 0)
    # resp_bytes = int(aggs.get("total_resp_bytes", {}).get("value", 0) or 0)
    # unique_dest_count = int(aggs.get("unique_destinations", {}).get("value", 0) or 0)
    # all_dests = aggs.get("top_destinations", {})
    # if all_dests.get("buckets") and not all_dests.get("sum_other_doc_count"):
    #     unique_dest_count = len(
    #         all_dests["buckets"]
    #     )  # #90: exact; the estimate stays past _ALL_TERMS
    #
    # # Top services: strip ASN prefix and merge duplicates
    # svc_merged: dict[str, dict] = {}
    # for sb in aggs.get("top_services", {}).get("buckets", []):
    #     asn_full = sb["key"]
    #     service_name = asn_full.split(" ", 1)[1] if " " in asn_full else asn_full
    #     if service_name not in svc_merged:
    #         svc_merged[service_name] = {"bytes": 0, "connections": 0}
    #     svc_merged[service_name]["bytes"] += int(
    #         sb.get("bytes", {}).get("value", 0) or 0
    #     )
    #     svc_merged[service_name]["connections"] += sb.get("doc_count", 0)
    # top_services_list = [
    #     {"name": name, "bytes": m["bytes"], "connections": m["connections"]}
    #     for name, m in svc_merged.items()
    # ]
    # # OLD CODE START — #96: sorted the 10 ASNs with the most connections
    # # top_services_list.sort(key=lambda s: s["bytes"], reverse=True)
    # # OLD CODE END
    # top_services_list = sorted(
    #     top_services_list, key=lambda s: s["bytes"], reverse=True
    # )[:10]
    #
    # first_seen = aggs.get("first_seen", {}).get("value_as_string", "")
    # last_seen = aggs.get("last_seen", {}).get("value_as_string", "")
    # proto_buckets = aggs.get("protocols", {}).get("buckets", [])
    # protocols = [pb["key"] for pb in proto_buckets]
    #
    # # Top destinations
    # # OLD CODE START — NET-158: the buckets come in connection-count order, so "By bytes"
    # # showed the 20 most frequent destinations, not the biggest transfers
    # # dest_buckets = aggs.get("top_destinations", {}).get("buckets", [])[:20]
    # # OLD CODE END
    # dest_buckets = sorted(
    #     aggs.get("top_destinations", {}).get("buckets", []),
    #     key=lambda b: b.get("bytes", {}).get("value", 0) or 0,
    #     reverse=True,
    # )[:20]
    # top_destinations = [
    #     {
    #         "ip": db["key"],
    #         "bytes": db.get("bytes", {}).get("value", 0) or 0,
    #         "connections": db.get("doc_count", 0),
    #     }
    #     for db in dest_buckets
    # ]
    #
    # # Bandwidth series
    # bw_buckets = histogram_buckets(
    #     aggs.get("bandwidth_series")
    # )  # date_histogram before #120
    # bandwidth_series = [
    #     {
    #         "timestamp": bwb.get("key_as_string", bwb.get("key")),
    #         "bytes": bwb.get("bytes", {}).get("value", 0) or 0,
    #         "download_bytes": int(bwb.get("download_bytes", {}).get("value", 0) or 0),
    #         "upload_bytes": int(bwb.get("upload_bytes", {}).get("value", 0) or 0),
    #     }
    #     for bwb in bw_buckets
    # ]
    #
    # OLD CODE END
    # NET-226: the device's side of every connection, and its IPv6 by MAC as the list folds it
    try:
        v6_mac = _ipv6_mac_of(client, request.app, ip, from_ts, to_ts)
        filters = _conn_filters(from_ts, to_ts)
        v6 = (
            _ipv6_shares(client, request.app, filters, [v6_mac], "device detail")
            if v6_mac
            else {}
        ).get(v6_mac, {})
    except QueryFailed as exc:
        return _incomplete("device detail", exc)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in device detail: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )
    # A reason means fold_ipv6 kept only the link-local part of this MAC's IPv6
    started, answered = _device_sides(ip, v6_mac, v6.get("reason") is not None)
    # The list's activity rule (_lan_device_buckets): its IPv4 records, started or answered
    responded = {"bool": {"filter": [{"term": {"destination.ip": ip}}, _RESPONDED]}}
    device_query = {
        "size": 0,
        "track_total_hits": True,  # #84: hits.total stops at 10,000 without it (the router read 10,000)
        "query": {
            "bool": {
                "filter": [
                    *filters,
                    {
                        "bool": {
                            "should": [started, answered],
                            "minimum_should_match": 1,
                        }
                    },
                ]
            }
        },
        "aggs": {
            **_side_sums(answered),
            "ipv6": {
                "filter": {"bool": {"must_not": [{"terms": {"source.ip": IPV4_ALL}}]}}
            },
            "bandwidth_series": {
                **time_slots(from_ts, to_ts, _bandwidth_interval(from_ts, to_ts)),
                "aggs": _side_sums(answered),
            },
            "activity": {
                "filter": {
                    "bool": {
                        "should": [{"term": {"source.ip": ip}}, responded],
                        "minimum_should_match": 1,
                    }
                },
                "aggs": {
                    "first_seen": {"min": {"field": "@timestamp"}},
                    "last_seen": {"max": {"field": "@timestamp"}},
                },
            },
            # what an answer-only device's row reads (its side of the records it answered)
            "responded": {
                "filter": responded,
                "aggs": _swapped(
                    {
                        "protocols": _DEVICE_AGGS["protocols"],
                        "with_mac": _DEVICE_AGGS["with_mac"],
                    }
                ),
            },
            # Where the device connected to: the started side, as before
            "started": {
                "filter": started,
                "aggs": {
                    "protocols": {"terms": {"field": "network.transport", "size": 10}},
                    # OLD CODE START — NET-226 follow-up: the bounds are "activity" now
                    # "first_seen": {"min": {"field": "@timestamp"}},
                    # "last_seen": {"max": {"field": "@timestamp"}},
                    # OLD CODE END
                    "unique_destinations": {"cardinality": {"field": "destination.ip"}},
                    # Every ASN (biggest first if a device has more), so the top 10 by bytes is
                    # exact after ASNs of one organisation are merged
                    "top_services": {
                        "terms": {
                            "field": "destination.as.full",
                            "size": _ALL_TERMS,
                            "shard_size": _ALL_TERMS,
                            "order": {"order_bytes": "desc"},
                        },
                        "aggs": {
                            **_BYTE_SUMS,
                            # Malcolm's sum of both IP byte counts, for the order only
                            "order_bytes": {"sum": {"field": "network.bytes"}},
                        },
                    },
                    # Every destination, so the top 20 and the unique count are exact
                    "top_destinations": {
                        "terms": {"field": "destination.ip", "size": _ALL_TERMS},
                        "aggs": _BYTE_SUMS,
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
    upload_bytes, download_bytes = _device_side_bytes(aggs)
    started_aggs = aggs.get("started", {})

    unique_dest_count = int(
        started_aggs.get("unique_destinations", {}).get("value", 0) or 0
    )
    all_dests = started_aggs.get("top_destinations", {})
    if all_dests.get("buckets") and not all_dests.get("sum_other_doc_count"):
        unique_dest_count = len(
            all_dests["buckets"]
        )  # #90: exact; the estimate stays past _ALL_TERMS

    # Top services: strip ASN prefix and merge duplicates
    svc_merged: dict[str, dict] = {}
    for sb in started_aggs.get("top_services", {}).get("buckets", []):
        asn_full = sb["key"]
        service_name = asn_full.split(" ", 1)[1] if " " in asn_full else asn_full
        seen = svc_merged.get(service_name, {"bytes": 0, "connections": 0})
        svc_merged = {
            **svc_merged,
            service_name: {
                "bytes": seen["bytes"] + _bucket_bytes(sb),
                "connections": seen["connections"] + sb.get("doc_count", 0),
            },
        }
    top_services_list = sorted(
        (
            {"name": name, "bytes": m["bytes"], "connections": m["connections"]}
            for name, m in svc_merged.items()
        ),
        key=lambda svc: svc["bytes"],
        reverse=True,
    )[:10]

    # OLD CODE START — NET-226 follow-up: the started side's bounds, its IPv6 included, where
    # the list reads its IPv4 records started and answered; and no protocols if it started none
    # first_seen = started_aggs.get("first_seen", {}).get("value_as_string", "")
    # last_seen = started_aggs.get("last_seen", {}).get("value_as_string", "")
    # protocols = [
    #     pb["key"] for pb in started_aggs.get("protocols", {}).get("buckets", [])
    # ]
    # OLD CODE END
    activity = aggs.get("activity", {})
    first_seen = activity.get("first_seen", {}).get("value_as_string", "")
    last_seen = activity.get("last_seen", {}).get("value_as_string", "")
    protocols = [
        pb["key"]
        for pb in (
            started_aggs.get("protocols", {}).get("buckets")
            or aggs.get("responded", {}).get("protocols", {}).get("buckets", [])
        )
    ]

    # Top destinations, by bytes (NET-158)
    top_destinations = [
        {
            "ip": db["key"],
            "bytes": _bucket_bytes(db),
            "connections": db.get("doc_count", 0),
        }
        for db in sorted(all_dests.get("buckets", []), key=_bucket_bytes, reverse=True)[
            :20
        ]
    ]

    # Bandwidth series, download and upload from the device's side
    bandwidth_series = []
    for bwb in histogram_buckets(aggs.get("bandwidth_series")):
        up, down = _device_side_bytes(bwb)
        bandwidth_series.append(
            {
                "timestamp": bwb.get("key_as_string", bwb.get("key")),
                "bytes": up + down,
                "download_bytes": down,
                "upload_bytes": up,
            }
        )

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
                ],
                "must_not": DNS_LOOKUP_EXCLUSION,
            }
        },
        "aggs": {
            "dns_queries": {
                "terms": {
                    "field": "zeek.dns.query",
                    "size": 50,
                    "shard_size": _ALL_TERMS,
                }
            }
        },
    }

    # OLD CODE START — #96: a failure showed the device as having made no DNS queries
    # dns_queries = []
    # try:
    #     ...
    # except OpenSearchException as exc:
    #     logger.warning("DNS query lookup failed for %s: %s", ip, exc)
    # OLD CODE END
    try:
        dns_result = client.search(index=NETWORK_INDEX, body=dns_query)
    except OpenSearchException as exc:
        logger.error("DNS query lookup failed for %s: %s", ip, exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )
    dns_buckets = (
        dns_result.get("aggregations", {}).get("dns_queries", {}).get("buckets", [])
    )
    dns_queries = [
        {"domain": db["key"], "count": db["doc_count"]} for db in dns_buckets
    ]

    # Alert count from unified index (suricata alert events)
    alert_query = {
        "size": 0,
        "track_total_hits": True,  # #84: same 10,000 cap on the alert count
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
                    # OLD CODE START — NET-158: alerts the device sent only, while the
                    # KPI says "on this device's traffic" and Smart alerts covers both ways
                    # {"term": {"source.ip": ip}},
                    # OLD CODE END
                    {
                        "bool": {
                            "should": [
                                {"term": {"source.ip": ip}},
                                {"term": {"destination.ip": ip}},
                            ],
                            "minimum_should_match": 1,
                        }
                    },
                    {"term": {"event.provider": "suricata"}},
                    {"term": {"event.dataset": "alert"}},
                ],
                "must_not": SURICATA_NOISE_EXCLUSION,
            }
        },
    }

    # OLD CODE START — #96: a failure showed the device with 0 alerts
    # alert_count = 0
    # try:
    #     ...
    # except OpenSearchException as exc:
    #     logger.warning("Alert count lookup failed for %s: %s", ip, exc)
    # OLD CODE END
    try:
        alert_result = client.search(index=NETWORK_INDEX, body=alert_query)
    except OpenSearchException as exc:
        logger.error("Alert count lookup failed for %s: %s", ip, exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )
    alert_total = alert_result.get("hits", {}).get("total", {})
    alert_count = (
        alert_total.get("value", 0) if isinstance(alert_total, dict) else alert_total
    )

    # Passive fingerprinting enrichment
    # OLD CODE: mac = fingerprint.get_mac_for_ip(client, ip, from_ts, to_ts) (an answer-only device had none)
    mac = fingerprint.get_mac_for_ip(client, ip, from_ts, to_ts) or _bucket_mac(
        aggs.get("responded", {})
    )
    hostname = fingerprint.get_hostname_for_ip(client, ip, from_ts, to_ts)
    hostname = (
        _registry_names(request, [mac] if mac else []).get(_mac_key(mac)) or hostname
    )
    manufacturer = fingerprint.get_manufacturer(mac) if mac else None
    os_hint = fingerprint.get_os_hint(client, ip, from_ts, to_ts)

    device = {
        "ip": ip,
        "mac": mac,
        "hostname": hostname,
        "manufacturer": manufacturer,
        "os_hint": os_hint,
        **_guesses(os_hint, hostname, manufacturer),
        "first_seen": first_seen,
        "last_seen": last_seen,
        # OLD CODE START — NET-226: started side only, orig/resp named
        # "total_bytes": total_bytes,
        # "orig_bytes": orig_bytes,
        # "resp_bytes": resp_bytes,
        # OLD CODE END
        "total_bytes": upload_bytes + download_bytes,
        "upload_bytes": upload_bytes,
        "download_bytes": download_bytes,
        "unique_destinations": unique_dest_count,
        "top_services": top_services_list,
        "connection_count": connection_count,
        "ipv6_connections": aggs.get("ipv6", {}).get("doc_count", 0),
        "ipv6_left_out": v6.get("left_out", 0),
        "ipv6_left_out_reason": v6.get("reason"),
        "protocols": protocols,
        "alert_count": alert_count,
        "top_destinations": top_destinations,
        "dns_queries": dns_queries,
        "bandwidth_series": bandwidth_series,
    }

    # UniFi alias enrichment — merge user-assigned name from controller
    unifi = request.app.get("unifi_integration")
    if unifi and unifi.is_configured:
        alias = None
        if mac:
            alias = unifi.get_device_alias(mac)
        if not alias:
            alias = unifi.get_client_name_by_ip(ip)
        if alias:
            device["unifi_name"] = alias

    # OLD CODE: return web.json_response({"device": device}) (NET-200: the owner's fields)
    return web.json_response({"device": _with_owner(request, device)})


# Recent Connections columns the device page can sort on, and the field behind each (#140).
# `length` is the session's end minus start: the duration the page shows, on every record.
# The Connections page sorts through the same map (#145), so it carries its Source and State too.
_CONNECTION_SORT_FIELDS = {
    "time": "@timestamp",
    "source": "source.ip",
    "destination": "destination.ip",
    "proto": "network.transport",
    "service": "network.protocol",
    "duration": "length",
    "dl": "destination.bytes",
    "ul": "source.bytes",
    "state": "zeek.conn.conn_state",
}
# An address column sorts by IP, then port
_PORT_TIEBREAK = {"source": "source.port", "destination": "destination.port"}


def _connection_sort(sort_key: str, order: str) -> list[dict]:
    """The OpenSearch sort for a column; newest first breaks ties so pages don't overlap."""
    if sort_key == "time":
        return [{"@timestamp": {"order": order}}]
    clauses = [
        {_CONNECTION_SORT_FIELDS[sort_key]: {"order": order, "missing": "_last"}}
    ]
    # OLD CODE START — #145: destination only; the Connections page sorts Source the same way
    # if sort_key == "destination":
    #     clauses.append({"destination.port": {"order": order, "missing": "_last"}})
    # OLD CODE END
    if sort_key in _PORT_TIEBREAK:
        clauses.append({_PORT_TIEBREAK[sort_key]: {"order": order, "missing": "_last"}})
    return [*clauses, {"@timestamp": {"order": "desc"}}]


# NET-158: the device page's DL/UL are the device's own download and upload, so on a session
# the device answered (it is the destination) they are the other way round. These keys sort
# on the device's side of each session; for this endpoint only (the Connections page keeps
# its source/destination columns). params.ip is the canonical form ip doc values use.
_DEVICE_STARTED = "doc['source.ip'].size() > 0 && doc['source.ip'].value == params.ip"
_DEVICE_SIDE_SORT = {
    # 1 when the device started the session (out), 0 when it answered (in)
    "direction": f"{_DEVICE_STARTED} ? 1 : 0",
    "dl": f"String f = {_DEVICE_STARTED} ? 'destination.bytes' : 'source.bytes';"
    " return doc[f].size() > 0 ? doc[f].value : 0;",
    "ul": f"String f = {_DEVICE_STARTED} ? 'source.bytes' : 'destination.bytes';"
    " return doc[f].size() > 0 ? doc[f].value : 0;",
}
# The Recent connections protocol filter (NET-158: it filtered only the rows on screen)
_DEVICE_CONNECTION_PROTOS = {"tcp", "udp", "icmp"}


def _canonical_ip(ip: str) -> str:
    """The address as OpenSearch prints an ip field (compressed IPv6); unparsable as is."""
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        return ip


def _device_connection_sort(sort_key: str, order: str, ip: str) -> list[dict]:
    """_connection_sort, with direction, DL and UL taken from the device's side."""
    if sort_key not in _DEVICE_SIDE_SORT:
        return _connection_sort(sort_key, order)
    script = {
        "lang": "painless",
        "source": _DEVICE_SIDE_SORT[sort_key],
        "params": {"ip": _canonical_ip(ip)},
    }
    return [
        {"_script": {"type": "number", "script": script, "order": order}},
        {"@timestamp": {"order": "desc"}},
    ]


@in_thread
def handle_device_connections(request: web.Request) -> web.Response:
    """GET /api/devices/{ip}/connections?page=1&size=50&from=&to=&sort=time&order=desc&proto=

    Returns paginated connection logs for a specific device IP, where the
    device appears as either source or destination. Each row carries its
    `direction` from the device's side: "out" if the device started it, else "in".
    `proto` (tcp, udp or icmp) filters on the daemon, so the total and pages match.
    """
    ip = request.match_info["ip"]
    from_ts, to_ts = _parse_time_range(request)
    page = _parse_int_param(request, "page", 1)
    size = min(_parse_int_param(request, "size", 50), 200)  # Cap at 200
    sort_key = request.query.get("sort", "time")
    order = request.query.get("order", "desc")
    proto = request.query.get("proto", "")
    # OLD CODE START — NET-158: no direction sort for the device page
    # if sort_key not in _CONNECTION_SORT_FIELDS or order not in ("asc", "desc"):
    # OLD CODE END
    sort_keys = [*_CONNECTION_SORT_FIELDS, "direction"]
    if sort_key not in sort_keys or order not in ("asc", "desc"):
        return web.json_response(
            {
                "error": "sort must be one of "
                + ", ".join(sort_keys)
                + " and order asc or desc"
            },
            status=400,
        )
    if proto and proto not in _DEVICE_CONNECTION_PROTOS:
        return web.json_response(
            {
                "error": "proto must be one of "
                + ", ".join(sorted(_DEVICE_CONNECTION_PROTOS))
            },
            status=400,
        )
    client = _get_client(request)

    offset = (page - 1) * size

    query = {
        "size": size,
        "track_total_hits": True,  # #84: the list total stopped at 10,000
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
                    # OLD CODE START — F1: also counted conn_long.log interim records
                    # {"term": {"event.dataset": "conn"}},
                    # OLD CODE END
                    CONN_ACCOUNTING,
                    *([{"term": {"network.transport": proto}}] if proto else []),
                ]
            }
        },
        # OLD CODE START — #140: always newest first, so the page's columns couldn't sort
        # "sort": [{"@timestamp": {"order": "desc"}}],
        # OLD CODE END
        # OLD CODE START — NET-158: DL/UL sorted on destination/source bytes, the device's
        # upload on the sessions it answered
        # "sort": _connection_sort(sort_key, order),
        # OLD CODE END
        "sort": _device_connection_sort(sort_key, order, ip),
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

    device_ip = _canonical_ip(ip)
    connections = []
    for hit in hits.get("hits", []):
        source = hit.get("_source", {})
        source["_id"] = hit.get("_id", "")
        source["_index"] = hit.get("_index", "")
        started_by = (source.get("source") or {}).get("ip") or ""
        source["direction"] = "out" if _canonical_ip(started_by) == device_ip else "in"
        connections.append(source)

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "ip": ip,
            "page": page,
            "size": size,
            "total": total,
            # OLD CODE START — #85: pages past OpenSearch's 10,000-result window came back empty
            # "total_pages": (total + size - 1) // size if size > 0 else 0,
            # OLD CODE END
            "total_pages": min(-(-total // size), _RESULT_WINDOW // size)
            if size > 0
            else 0,
            "connections": connections,
        }
    )


@in_thread
def handle_device_categories(request: web.Request) -> web.Response:
    """GET /api/devices/{ip}/categories?from=&to=

    Returns traffic category breakdown for this device (what percentage
    is streaming, cloud, social, etc.) based on destination ASN mapping.
    """
    ip = request.match_info["ip"]
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)

    # Query destination ASN breakdown for this device
    query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    _time_range_filter(from_ts, to_ts),
                    {"term": {"source.ip": ip}},
                    {"term": {"event.provider": "zeek"}},
                    # OLD CODE START — F1: also counted conn_long.log interim records
                    # {"term": {"event.dataset": "conn"}},
                    # OLD CODE END
                    CONN_ACCOUNTING,
                ]
            }
        },
        "aggs": {
            "asn_breakdown": {
                # OLD CODE START — #90: 200 ASNs; a device with 395 lost 679 connections from its categories
                # "terms": {"field": "destination.as.full", "size": 200},
                # OLD CODE END
                "terms": {"field": "destination.as.full", "size": _ALL_TERMS},
                "aggs": {
                    "total_bytes": {
                        "sum": {
                            "script": {
                                "source": "(doc['source.bytes'].size() > 0 ? doc['source.bytes'].value : 0) + (doc['destination.bytes'].size() > 0 ? doc['destination.bytes'].value : 0)",
                                "lang": "painless",
                            }
                        }
                    },
                },
            }
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in device categories: %s", exc)
        return web.json_response({"error": str(exc)}, status=502)

    cat_data: dict[str, dict] = {}
    for bucket in (
        result.get("aggregations", {}).get("asn_breakdown", {}).get("buckets", [])
    ):
        asn_full = bucket["key"]
        cat_key = classify_asn(asn_full)
        total_bytes = int(bucket.get("total_bytes", {}).get("value", 0))

        if cat_key not in cat_data:
            cat_data[cat_key] = {
                "name": cat_key,
                "label": CATEGORIES.get(cat_key, cat_key.title()),
                "total_bytes": 0,
                "connection_count": 0,
            }

        cat_data[cat_key]["total_bytes"] += total_bytes
        cat_data[cat_key]["connection_count"] += bucket.get("doc_count", 0)

    categories = sorted(cat_data.values(), key=lambda c: c["total_bytes"], reverse=True)

    return web.json_response(
        {"ip": ip, "from": from_ts, "to": to_ts, "categories": categories}
    )


@in_thread
def handle_device_alerts(request: web.Request) -> web.Response:
    """GET /api/devices/{ip}/alerts?from=&to=&limit=20

    Returns recent Suricata alerts with details for a specific device,
    where the device appears as either source or destination.
    """
    ip = request.match_info["ip"]
    from_ts, to_ts = _parse_time_range(request)
    limit = _parse_int_param(request, "limit", 20)
    client = _get_client(request)

    query = {
        "size": limit,
        "track_total_hits": True,  # #84: the alert total stopped at 10,000
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
                    {"term": {"event.provider": "suricata"}},
                    {"term": {"event.dataset": "alert"}},
                ],
                "must_not": SURICATA_NOISE_EXCLUSION,
            }
        },
        "sort": [{"@timestamp": {"order": "desc"}}],
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in device alerts: %s", exc)
        return web.json_response({"error": str(exc)}, status=502)

    hits = result.get("hits", {})
    total_raw = hits.get("total", {})
    total = total_raw.get("value", 0) if isinstance(total_raw, dict) else total_raw

    alerts = []
    for hit in hits.get("hits", []):
        src = hit.get("_source", {})
        # OLD CODE START — extracted from wrong path (suricata.eve.alert)
        # alert_info = src.get("suricata", {}).get("eve", {}).get("alert", {}) or src.get("alert", {})
        # OLD CODE END
        _normalize_alert_source(
            src
        )  # Normalizes all ECS/Malcolm field paths into src["alert"]
        alert = src.get("alert", {})
        alerts.append(
            {
                "timestamp": src.get("@timestamp", ""),
                "severity": alert.get("severity", 3),
                "signature": alert.get("signature", "Unknown alert"),
                "category": alert.get("category", "Unknown"),
                "signature_id": alert.get("signature_id", 0),
                "source_ip": src.get("src_ip")
                or (src.get("source", {}) or {}).get("ip", ""),
                "destination_ip": src.get("dest_ip")
                or (src.get("destination", {}) or {}).get("ip", ""),
                "source_port": src.get("src_port")
                or (src.get("source", {}) or {}).get("port"),
                "destination_port": src.get("dest_port")
                or (src.get("destination", {}) or {}).get("port"),
            }
        )

    return web.json_response(
        {
            "ip": ip,
            "from": from_ts,
            "to": to_ts,
            "total": total,
            "alerts": alerts,
        }
    )


@in_thread
def handle_device_ports(request: web.Request) -> web.Response:
    """GET /api/devices/{ip}/ports?from=&to=

    Returns top destination ports used by this device with service
    name mapping and suspicious port flagging.
    """
    ip = request.match_info["ip"]
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)

    query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    _time_range_filter(from_ts, to_ts),
                    {"term": {"source.ip": ip}},
                    {"term": {"event.provider": "zeek"}},
                    # OLD CODE START — F1: also counted conn_long.log interim records
                    # {"term": {"event.dataset": "conn"}},
                    # OLD CODE END
                    CONN_ACCOUNTING,
                ]
            }
        },
        "aggs": {
            "top_ports": {
                "terms": {
                    "field": "destination.port",
                    "size": 20,
                    "shard_size": _ALL_TERMS,
                },
            }
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in device ports: %s", exc)
        return web.json_response({"error": str(exc)}, status=502)

    PORT_NAMES = {
        20: "FTP Data",
        21: "FTP",
        22: "SSH",
        23: "Telnet",
        25: "SMTP",
        53: "DNS",
        67: "DHCP",
        68: "DHCP",
        80: "HTTP",
        110: "POP3",
        123: "NTP",
        143: "IMAP",
        443: "HTTPS",
        465: "SMTPS",
        587: "SMTP",
        993: "IMAPS",
        995: "POP3S",
        3389: "RDP",
        5060: "SIP",
        5222: "XMPP",
        5353: "mDNS",
        5900: "VNC",
        8080: "HTTP-Alt",
        8443: "HTTPS-Alt",
        8888: "Unknown",
        9999: "Unknown",
    }

    SUSPICIOUS_PORTS = {4444, 5555, 6666, 8888, 9999, 31337, 12345, 65535}

    ports = []
    for bucket in (
        result.get("aggregations", {}).get("top_ports", {}).get("buckets", [])
    ):
        port_num = bucket["key"]
        ports.append(
            {
                "port": port_num,
                "service": PORT_NAMES.get(port_num, "Unknown"),
                "connections": bucket["doc_count"],
                "suspicious": port_num in SUSPICIOUS_PORTS,
            }
        )

    return web.json_response({"ip": ip, "from": from_ts, "to": to_ts, "ports": ports})


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


async def handle_device_count(request: web.Request) -> web.Response:
    """GET /api/devices/count?from=&to=&active_since=

    Returns how many devices GET /api/devices would list for the same range:
    same filters, same _MIN_CONNECTIONS threshold, same skip rules. With active_since,
    only those whose last_seen (the list's newest record) is at or after it.
    """
    from_ts, to_ts = _parse_time_range(request)
    # NET-158: "Online now" counted a 5-minute range, so it needed 3 records in those 5 minutes
    # while the table calls a listed device Online on its newest record alone
    active_since = iso_param(request, "active_since")
    client = _get_client(request)

    # OLD CODE START — replaced 2026-11-01: a mirror on the uplink sees almost no DHCP, so this said 3 while the list showed 27
    # query = {
    #     "size": 0,
    #     "query": {
    #         "bool": {
    #             "filter": [
    #                 _time_range_filter(from_ts, to_ts),
    #                 {"term": {"event.provider": "zeek"}},
    #                 {"term": {"event.dataset": "dhcp"}},
    #             ]
    #         }
    #     },
    #     "aggs": {"unique_devices": {"cardinality": {"field": "zeek.dhcp.assigned_ip"}}},
    # }
    # OLD CODE END
    # OLD CODE START — #96: a terms list stops at 500 IPs, so 30 days of DHCP churn on a
    # bigger network read 500 (the Home device stat)
    # query = {
    #     "size": 0,
    #     "query": {"bool": _device_bool_query(request, from_ts, to_ts)},
    #     "aggs": {
    #         "devices": {
    #             "terms": {
    #                 "field": "source.ip",
    #                 # shortcut: counts at most _MAX_DEVICE_LIMIT devices, the list's own cap; raise both if a site outgrows it
    #                 "size": _MAX_DEVICE_LIMIT,
    #                 "min_doc_count": _MIN_CONNECTIONS,
    #             }
    #         }
    #     },
    # }
    # OLD CODE END

    try:
        # OLD CODE START — #96: the capped terms search above
        # result = client.search(index=NETWORK_INDEX, body=query)
        # OLD CODE END
        # PR #191 review: off the event loop, as the list does
        # OLD CODE START — PR #200 review: asyncio's default pool, which must stay free for
        # the drill-downs and health checks
        # devices = await asyncio.get_running_loop().run_in_executor(
        #     None,
        #     lambda: _lan_device_buckets(
        # OLD CODE END
        devices = await run_blocking(
            lambda: _lan_device_buckets(
                client,
                request.app,
                from_ts,
                to_ts,
                aggs={"last_seen": {"max": {"field": "@timestamp"}}}
                if active_since
                else None,
                what="device count",
            ),
        )
    except QueryFailed as exc:
        return _incomplete("devices/count", exc)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in devices/count: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    # OLD CODE START — replaced 2026-11-01: DHCP cardinality, see the query above
    # aggs = result.get("aggregations", {})
    # count = aggs.get("unique_devices", {}).get("value", 0)
    # OLD CODE END
    # OLD CODE START — #96: counted the capped terms list
    # buckets = result.get("aggregations", {}).get("devices", {}).get("buckets", [])
    # count = sum(1 for b in buckets if not _is_skipped_device_ip(b["key"]))
    # OLD CODE END
    if active_since:
        cutoff_ms = _utc(active_since).timestamp() * 1000
        devices = [
            d
            for d in devices
            if (d.get("last_seen", {}).get("value") or 0) >= cutoff_ms
        ]
    count = len(devices)

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "count": count,
        }
    )


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
    app.router.add_get("/api/devices/{ip}/categories", handle_device_categories)
    app.router.add_get("/api/devices/{ip}/alerts", handle_device_alerts)
    app.router.add_get("/api/devices/{ip}/ports", handle_device_ports)
    logger.info("Device API routes registered (7 endpoints)")
