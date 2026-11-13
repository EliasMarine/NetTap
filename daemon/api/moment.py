"""GET /api/moment/devices: the busiest LAN devices in a window and what each talked to (NET-249).

The moment page's top devices card. The ranking is /api/devices' own (_accounted_devices,
ranked as sort=bytes), so a device's figures equal its row there. The breakdown is one
msearch over the ranked IPs: the connections each started, by destination and by app, with
the traffic summary's predicate, and the names it looked up, with the DNS device page's. It
joins onto the ranking, so a device that only answered connections keeps its row and gets
empty lists.

Two reads and no snapshot: in a live window the breakdown can hold a few records newer than
the ranking, so the totals always come from the ranking and the lists are rankings, not parts
of a total. The work runs in a drill-down slot (api/drilldown_runner.py), off the route pool;
the budget is checked between the reads and can't stop one that is running. The breakdown
covers a device's IPv4 address; IPv6 credited to it by MAC is in its totals only.
"""

import asyncio
import logging
import time
from typing import Any

from aiohttp import web
from opensearchpy import OpenSearchException

from api.devices import (
    _SORT_VALUE,
    _accounted_devices,
    _get_client,
    _mac_key,
    _parse_time_range,
    _ranked,
    _registry_names,
    _with_owner,
)
from api.drilldown_runner import DRILL_SLOTS, json_error, run_drilldown
from api.traffic import (
    _CONN_BYTES_SUM,
    _ZEEK_CONN_FILTERS,
    NETWORK_INDEX,
    _time_range_filter,
)
from services.device_fingerprint import _NOT_HOSTNAMES
from services.excluded_ips import build_excluded_ips_filter, valid_excluded_ips
from storage.exact_terms import PartialResultsError
from storage.snapshot_search import Budget, QueryFailed, checked

logger = logging.getLogger("nettap.api.moment")

_LIMIT_DEFAULT = 10
_LIMIT_MAX = 25
_TOP = 5  # destinations, domains and apps per device
# The fields each device keeps from _accounted_devices, as the reply names them
_TOTALS = (
    "total_bytes",
    "upload_bytes",
    "download_bytes",
    "connection_count",
    "ipv6_left_out",
    "ipv6_left_out_reason",
)


def _limit(raw: str | None) -> int | None:
    """The limit query parameter, default _LIMIT_DEFAULT; None unless a whole number in range."""
    if not raw:
        return _LIMIT_DEFAULT
    try:
        limit = int(raw)
    except ValueError:
        return None
    return limit if 1 <= limit <= _LIMIT_MAX else None


def _names(
    request: web.Request, client: Any, top: list[dict], from_ts: str, to_ts: str
) -> dict[str, str | None]:
    """{ip: the name its /api/devices row shows}: the owner's, then UniFi's, then the hostname.

    handle_device_list's lookups in its order, so a device reads the same on both pages.
    """
    lookups = request.app["device_fingerprint"].lookup_many(
        client, [b["key"] for b in top], from_ts, to_ts
    )
    registry = _registry_names(request, [mac for mac, _, _ in lookups.values() if mac])
    unifi = request.app.get("unifi_integration")
    names: dict[str, str | None] = {}
    for b in top:
        ip = b["key"]
        mac, hostname, _ = lookups.get(ip, (None, None, None))
        mac = mac or b["mac"]
        hostname = registry.get(_mac_key(mac)) or hostname
        if hostname and any(x in hostname for x in _NOT_HOSTNAMES):
            hostname = None
        alias = None
        if unifi and unifi.is_configured:
            alias = (unifi.get_device_alias(mac) if mac else None) or (
                unifi.get_client_name_by_ip(ip)
            )
        own = _with_owner(request, {"mac": mac, "hostname": hostname}).get(
            "custom_name"
        )
        names[ip] = own or alias or hostname
    return names


def _top_by_bytes(field: str, **terms: Any) -> dict:
    return {
        "terms": {"field": field, "size": _TOP, "order": {"bytes": "desc"}, **terms},
        "aggs": {"bytes": _CONN_BYTES_SUM},
    }


def _breakdown(
    request: web.Request, client: Any, from_ts: str, to_ts: str, ips: list[str]
) -> list[dict[str, dict]]:
    """[{ip: started bucket}, {ip: DNS bucket}] for `ips`, from one msearch.

    A device with no bucket started no connections (or looked nothing up) in the window.
    """
    if not ips:
        return [{}, {}]
    excluded = valid_excluded_ips(request.app.get("excluded_ips", []))
    per_ip = {"terms": {"field": "source.ip", "include": ips, "size": len(ips)}}
    started = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [_time_range_filter(from_ts, to_ts), *_ZEEK_CONN_FILTERS],
                "must_not": build_excluded_ips_filter(excluded),
            }
        },
        "aggs": {
            "ips": {
                **per_ip,
                "aggs": {
                    "destinations": _top_by_bytes("destination.ip"),
                    # Unlabelled connections as "unknown", as /api/traffic/protocols counts them:
                    # on the G11 a device's biggest flows were often unlabelled
                    "apps": _top_by_bytes("network.protocol", missing="unknown"),
                },
            }
        },
    }
    looked_up = {
        "size": 0,
        "query": {
            "bool": request.app["dns_analytics"]._bool_clause(from_ts, to_ts, excluded)
        },
        "aggs": {
            "ips": {
                **per_ip,
                "aggs": {
                    "domains": {"terms": {"field": "zeek.dns.query", "size": _TOP}}
                },
            }
        },
    }
    replies = client.msearch(
        body=[{"index": NETWORK_INDEX}, started, {"index": NETWORK_INDEX}, looked_up]
    ).get("responses")
    if not isinstance(replies, list) or len(replies) != 2:
        raise QueryFailed("the device breakdown reply was malformed")
    return [
        {
            b["key"]: b
            for b in checked(r, "the device breakdown", ("ips",))["aggregations"][
                "ips"
            ]["buckets"]
        }
        for r in replies
    ]


def _listed(bucket: dict | None, name: str) -> list[dict]:
    return bucket[name]["buckets"] if bucket else []


def _device(
    row: dict, name: str | None, started: dict | None, looked_up: dict | None
) -> dict:
    return {
        "ip": row["key"],
        "name": name,
        "mac": row["mac"],
        **{k: row[k] for k in _TOTALS},
        "destinations": [
            {
                "ip": d["key"],
                "bytes": round(d["bytes"]["value"] or 0),
                "connections": d["doc_count"],
            }
            for d in _listed(started, "destinations")
        ],
        "domains": [
            {"domain": d["key"], "count": d["doc_count"]}
            for d in _listed(looked_up, "domains")
        ],
        "apps": [
            {
                "protocol": d["key"],
                "bytes": round(d["bytes"]["value"] or 0),
                "connections": d["doc_count"],
            }
            for d in _listed(started, "apps")
        ],
    }


def moment_devices(
    request: web.Request,
    client: Any,
    from_ts: str,
    to_ts: str,
    limit: int,
    budget: Budget,
) -> dict:
    """The reply; QueryFailed (a 502) for a failed or partial read, TooSlow once out of budget."""
    began = time.monotonic()
    try:
        rows = _accounted_devices(client, request.app, from_ts, to_ts, "moment devices")
        top = _ranked(rows, _SORT_VALUE["bytes"], True)[:limit]
        budget.check("the device names")
        names = _names(request, client, top, from_ts, to_ts)
        budget.check("the device breakdown")
        started, looked_up = _breakdown(
            request, client, from_ts, to_ts, [b["key"] for b in top]
        )
    # the daemon's client raises PartialResultsError for a part reply or a time-out
    except OpenSearchException as exc:
        logger.warning("Moment devices search failed: %s", exc)
        why = "was incomplete" if isinstance(exc, PartialResultsError) else "failed"
        raise QueryFailed(f"the device search {why}") from exc
    logger.info(
        "Moment devices %s to %s: %d of %d in %.2f s",
        from_ts,
        to_ts,
        len(top),
        len(rows),
        time.monotonic() - began,
    )
    return {
        "from": from_ts,
        "to": to_ts,
        "total_devices": len(rows),
        "devices": [
            _device(
                b, names.get(b["key"]), started.get(b["key"]), looked_up.get(b["key"])
            )
            for b in top
        ],
    }


async def handle_moment_devices(request: web.Request) -> web.Response:
    """GET /api/moment/devices?from=&to=&limit=10 (limit 1-25)."""
    from_ts, to_ts = _parse_time_range(request)
    limit = _limit(request.query.get("limit"))
    if limit is None:
        return json_error(f"limit must be a whole number from 1 to {_LIMIT_MAX}.", 400)
    client = _get_client(request)
    return await run_drilldown(
        request,
        lambda budget: moment_devices(request, client, from_ts, to_ts, limit, budget),
        "moment devices",
    )


def register_moment_routes(app: web.Application) -> None:
    """Needs the device and DNS routes too: it reads their device_fingerprint and dns_analytics."""
    # the drill-down pages' shared permits (drilldown_runner.install), whichever registers first
    app.setdefault("drill_slots", asyncio.Semaphore(DRILL_SLOTS))
    app.router.add_get("/api/moment/devices", handle_moment_devices)
    logger.info("Moment API routes registered (1 endpoint)")
