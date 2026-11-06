"""GET /api/addresses/{ip} — what the network did with one address in a window (NET-160).

One snapshot per request (storage/snapshot_search.py) inside run_drilldown's bound. Every
list is complete or flagged, and every byte total says how many connections measured it.
No excluded-IP filter: exclusions act on the source side only, so they would bias one
direction and disagree with the connections table under this page (api/devices.py).

A connection is "to it" when the address is the destination, "from it" otherwise; a
connection from the address to itself is counted once, on the "to it" side.
"""

import logging
from collections import Counter
from datetime import timedelta
from typing import Any, Callable

from aiohttp import web

from api.alerts import _SURICATA_ALERT_FILTERS, SURICATA_NOISE_EXCLUSION
from api.drilldown_runner import (
    chart_slots,
    install,
    ip_param,
    iso_ms,
    json_error,
    lan_check,
    run_drilldown,
    timeline,
    window_filter,
)
from api.time_range import parse_time_range
from services.threat_intel import ThreatIntelService
from storage.snapshot_search import (
    NETWORK_INDEX,
    Budget,
    SnapshotSearch,
    doc_count,
    metric,
)

logger = logging.getLogger("nettap.api.addresses")

_DEFAULT_RANGE = timedelta(hours=24)
_CONN = [{"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "conn"}}]
_SSL = [{"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "ssl"}}]
# Each sum ships with how many records had the field: a missing value is not a 0
_BYTES = {
    "src": {"sum": {"field": "source.bytes"}},
    "src_n": {"value_count": {"field": "source.bytes"}},
    "dst": {"sum": {"field": "destination.bytes"}},
    "dst_n": {"value_count": {"field": "destination.bytes"}},
}
_LAST = {"last": {"max": {"field": "@timestamp"}}}


# ---------------------------------------------------------------------------
# Reading replies
# ---------------------------------------------------------------------------


def _directed(agg: dict, peer_opened: bool, what: str) -> tuple[int, int, int, int]:
    """(bytes to the address, records measuring it, bytes from it, records measuring it).

    source.bytes is what the side that opened the connection sent: the peer's when the
    address is the destination, the address's own otherwise.
    """
    src, dst = metric(agg, "src", what), metric(agg, "dst", what)
    src_n, dst_n = metric(agg, "src_n", what), metric(agg, "dst_n", what)
    sent = (round(src or 0), int(src_n or 0))
    answered = (round(dst or 0), int(dst_n or 0))
    return (*sent, *answered) if peer_opened else (*answered, *sent)


def _byte_total(total: int, measured: int, connections: int) -> dict:
    return {
        "total": total,
        "measured": measured,
        "connections": connections,
        "partial": measured < connections,
    }


# ---------------------------------------------------------------------------
# The figures
# ---------------------------------------------------------------------------


def _sides(ip: str) -> tuple[dict, dict]:
    """(the address is the destination, it is the source of a connection to anyone else)."""
    to_it = {"term": {"destination.ip": ip}}
    from_it = {
        "bool": {
            "filter": [{"term": {"source.ip": ip}}],
            "must_not": [{"term": {"destination.ip": ip}}],
        }
    }
    return to_it, from_it


def _totals(snap: SnapshotSearch, ip: str, window: dict, slots: dict) -> dict:
    to_it, from_it = _sides(ip)
    sides = [{"term": {"source.ip": ip}}, to_it]
    either = {"bool": {"should": sides, "minimum_should_match": 1}}
    what = "address totals"
    reply = snap.search(
        {
            "size": 0,
            "query": {"bool": {"filter": [window, *_CONN, either]}},
            "aggs": {
                "to_it": {"filter": to_it, "aggs": _BYTES},
                "from_it": {"filter": from_it, "aggs": _BYTES},
                "first": {"min": {"field": "@timestamp"}},
                "last": {"max": {"field": "@timestamp"}},
                "timeline": slots,
            },
        },
        what,
        ("to_it", "from_it", "first", "last", "timeline"),
    )
    aggs = reply["aggregations"]
    n_to, n_from = doc_count(aggs["to_it"], what), doc_count(aggs["from_it"], what)
    in_to, in_to_n, out_to, out_to_n = _directed(aggs["to_it"], True, what)
    in_from, in_from_n, out_from, out_from_n = _directed(aggs["from_it"], False, what)
    connections = n_to + n_from
    return {
        "connections": connections,
        "first_seen": iso_ms(metric(aggs, "first", what)),
        "last_seen": iso_ms(metric(aggs, "last", what)),
        "bytes_to": _byte_total(in_to + in_from, in_to_n + in_from_n, connections),
        "bytes_from": _byte_total(
            out_to + out_from, out_to_n + out_from_n, connections
        ),
        "timeline": timeline(reply),
    }


def _peer_row(ip: str, parts: list[tuple], is_lan: Callable[[str], bool]) -> dict:
    """One peer's two sides summed: parts are (connections, to, to_n, from, from_n, last)."""
    connections = sum(p[0] for p in parts)
    lasts = [p[5] for p in parts if p[5] is not None]
    to_n, from_n = sum(p[2] for p in parts), sum(p[4] for p in parts)
    return {
        "ip": ip,
        "lan": is_lan(ip),
        "connections": connections,
        # None when no session measured that direction: "Not measured", never "at least 0 B"
        "bytes_to": sum(p[1] for p in parts) if to_n else None,
        "bytes_from": sum(p[3] for p in parts) if from_n else None,
        "bytes_partial": to_n < connections or from_n < connections,
        "last_seen": iso_ms(max(lasts)) if lasts else None,
    }


def _peers(
    snap: SnapshotSearch, ip: str, window: dict, is_lan: Callable[[str], bool]
) -> tuple[list[dict], bool]:
    to_it, from_it = _sides(ip)
    what = "address peers"
    parts: dict[str, list[tuple]] = {}
    complete = True
    for side, peer_field, peer_opened in (
        (to_it, "source.ip", True),
        (from_it, "destination.ip", False),
    ):
        buckets, done = snap.groups(
            {"bool": {"filter": [window, *_CONN, side]}},
            [{"ip": {"terms": {"field": peer_field}}}],
            {**_BYTES, **_LAST},
            what,
        )
        complete = complete and done
        for b in buckets:
            row = (doc_count(b, what), *_directed(b, peer_opened, what))
            parts.setdefault(b["key"]["ip"], []).append((*row, metric(b, "last", what)))
    rows = [_peer_row(peer, p, is_lan) for peer, p in parts.items()]
    return sorted(rows, key=lambda r: (-r["connections"], r["ip"])), complete


def _ports(snap: SnapshotSearch, ip: str, window: dict) -> tuple[list[dict], bool]:
    """The ports on this address the network reached (it is the destination)."""
    buckets, complete = snap.groups(
        {"bool": {"filter": [window, *_CONN, {"term": {"destination.ip": ip}}]}},
        [
            {name: {"terms": {"field": field, "missing_bucket": True}}}
            for name, field in (
                ("port", "destination.port"),
                ("transport", "network.transport"),
                ("service", "network.protocol"),
            )
        ],
        None,
        "address ports",
    )
    rows = [{**b["key"], "connections": doc_count(b, "address ports")} for b in buckets]
    return sorted(rows, key=lambda r: -r["connections"]), complete


def _tls_names(snap: SnapshotSearch, ip: str, window: dict) -> tuple[list[dict], bool]:
    """The names TLS clients asked this address for, with how each session validated."""
    buckets, complete = snap.groups(
        {"bool": {"filter": [window, *_SSL, {"term": {"destination.ip": ip}}]}},
        [
            {
                "name": {
                    "terms": {"field": "zeek.ssl.server_name", "missing_bucket": True}
                }
            },
            {
                "status": {
                    "terms": {
                        "field": "zeek.ssl.validation_status",
                        "missing_bucket": True,
                    }
                }
            },
        ],
        None,
        "address TLS names",
    )
    names: dict[Any, Counter] = {}
    for b in buckets:
        status = b["key"]["status"] or "unchecked"
        names.setdefault(b["key"]["name"], Counter())[status] += doc_count(
            b, "TLS names"
        )
    rows = [
        {"name": name, "sessions": sum(st.values()), "statuses": dict(st)}
        for name, st in names.items()
    ]
    return sorted(rows, key=lambda r: -r["sessions"]), complete


def _alerts(snap: SnapshotSearch, ip: str, window: dict) -> int:
    """Suricata alerts with the address on either side, counted as /api/alerts?ip= lists them."""
    either = [{"term": {"source.ip": ip}}, {"term": {"destination.ip": ip}}]
    return snap.count(
        {
            "bool": {
                "filter": [
                    window,
                    *_SURICATA_ALERT_FILTERS,
                    {"bool": {"should": either, "minimum_should_match": 1}},
                ],
                "must_not": SURICATA_NOISE_EXCLUSION,
            }
        },
        "address alerts",
    )


def threat_intel(ip: str) -> dict | None:
    """None when no indicator is loaded yet; otherwise whether any feed lists the address."""
    ti = ThreatIntelService()
    ti.load_cache()
    if not ti.available:
        return None
    hits = ti.lookup_ip(ip)
    return {"matched": bool(hits), "feeds": hits, "indicators": ti.indicator_count}


def address_figures(
    client: Any,
    ip: str,
    from_ts: str,
    to_ts: str,
    slots: dict,
    is_lan: Callable[[str], bool],
    budget: Budget,
) -> dict:
    """Every figure the address page shows, over one snapshot."""
    window = window_filter(from_ts, to_ts)
    with SnapshotSearch(client, NETWORK_INDEX, budget) as snap:
        totals = _totals(snap, ip, window, slots)
        peers, peers_complete = _peers(snap, ip, window, is_lan)
        ports, ports_complete = _ports(snap, ip, window)
        tls_names, tls_complete = _tls_names(snap, ip, window)
        alerts = _alerts(snap, ip, window)
    for name, complete in (
        ("peers", peers_complete),
        ("ports", ports_complete),
        ("TLS names", tls_complete),
    ):
        if not complete:
            logger.info("Address %s: the %s list stopped at its cap", ip, name)
    return {
        "ip": ip,
        "from": from_ts,
        "to": to_ts,
        "lan": is_lan(ip),
        **{k: v for k, v in totals.items() if k != "timeline"},
        "peers": peers,
        "peers_complete": peers_complete,
        "ports": ports,
        "ports_complete": ports_complete,
        "timeline": totals["timeline"],
        "tls_names": tls_names,
        "tls_complete": tls_complete,
        "alerts": alerts,
        "threat_intel": threat_intel(ip),
    }


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


async def handle_address(request: web.Request) -> web.Response:
    """GET /api/addresses/{ip}?from=&to= — the address page's figures."""
    ip = ip_param(request.match_info["ip"])
    if ip is None:
        return json_error("That is not an IP address.", 400)
    from_ts, to_ts = parse_time_range(request, _DEFAULT_RANGE)
    slots = chart_slots(from_ts, to_ts)
    if slots is None:
        return json_error("This time range is too long; choose a shorter one.", 400)
    client, is_lan = request.app["drill_client"], lan_check(request.app)
    return await run_drilldown(
        request,
        lambda budget: address_figures(
            client, ip, from_ts, to_ts, slots, is_lan, budget
        ),
        f"address {ip}",
    )


def register_address_routes(app: web.Application, client: Any) -> None:
    install(app, client)
    app.router.add_get("/api/addresses/{ip}", handle_address)
    logger.info("Address API routes registered (1 endpoint)")
