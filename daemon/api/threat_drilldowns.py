"""The Threats page's drill-downs: one beaconing pair, and one device's failed DNS lookups.

GET /api/threats/beaconing/pair?device=&server=&port=  — the conn records the beaconing scan
    reads for one device -> server:port pair, timed with the scan's own rule
    (threat_detection._assess_beacon), with what the device called the server.
GET /api/threats/failed-lookups/{ip}  — the lookups behind an NXDOMAIN spike.

Both read the records their detector reads, so devices excluded in Settings are counted (the
detectors ignore exclusions), and each reply says whether its device is excluded. One snapshot
per request inside run_drilldown's budget and slots; never a partial reply.
"""

import logging
import re
import statistics
from collections import Counter
from datetime import timedelta
from typing import Any

from aiohttp import web

from api.addresses import _listed_by_alerts, threat_intel
from api.alerts import _time_range_filter
from api.domains import _every_value
from api.drilldown_runner import (
    LAST_SEEN,
    LIST_CAP,
    chart_interval,
    chart_slots,
    install,
    ip_param,
    iso_ms,
    json_error,
    run_drilldown,
    timeline,
    zeek,
)
from api.time_range import parse_time_range
from services.dns_analytics import DNS_LOOKUP_EXCLUSION
from services.excluded_ips import valid_excluded_ips
from services.hostnames import canonical_name
from services.threat_detection import (
    BEACON_SLOT_SECONDS,
    BEACONING_MIN_CONNECTIONS,
    NO_EVIDENCE,
    _assess_beacon,
    dns_name_evidence,
)
from storage.snapshot_search import (
    NETWORK_INDEX,
    Budget,
    SnapshotSearch,
    doc_count,
    metric,
    total_hits,
)
from storage.time_slots import histogram_buckets

logger = logging.getLogger("nettap.api.threat_drilldowns")

_DEFAULT_RANGE = timedelta(hours=24)
TIMING_CAP = (
    50_000  # 10 s slots read for one pair: a call a minute for 30 days is 43,200
)
GAPS_SHOWN = 8
FAILED_NAMES_SHOWN = 100
_PORT = re.compile(r"\d{1,5}")
_NXDOMAIN = {"term": {"zeek.dns.rcode_name": "NXDOMAIN"}}
_NOT_AN_IP = "That is not an IP address."
_BAD_PORT = "Port must be a number from 0 to 65535."
_TOO_LONG = "This time range is too long; choose a shorter one."
# Names that never exist in public DNS: a lookup for one fails by design
_LOCAL_SUFFIXES = (
    ".local",
    ".lan",
    ".home",
    ".localdomain",
    ".internal",
    ".home.arpa",
    ".test",
    ".invalid",
    ".example",
    ".localhost",
)


def _port_param(raw: str | None) -> int | None:
    """A destination port, 0-65535, written as digits; None for anything else."""
    if raw is None or not _PORT.fullmatch(raw):
        return None
    port = int(raw)
    return port if port <= 65535 else None


def _excluded(app: web.Application, ip: str) -> bool:
    """Whether Settings excludes the address (most pages leave it out; the detectors don't)."""
    return ip in valid_excluded_ips(app.get("excluded_ips", []))


def _window(request: web.Request) -> tuple[str, str, str, dict | None]:
    """(from, to, the chart's bucket, its slots or None when the window holds too many)."""
    from_ts, to_ts = parse_time_range(request, _DEFAULT_RANGE)
    interval = chart_interval(request, from_ts, to_ts)
    return from_ts, to_ts, interval, chart_slots(from_ts, to_ts, interval)


# ---------------------------------------------------------------------------
# One beaconing pair
# ---------------------------------------------------------------------------


def _top(aggs: dict, name: str, what: str) -> list[dict]:
    """A small terms aggregation as [{name, connections}], most first."""
    return [
        {"name": b["key"], "connections": doc_count(b, what)}
        for b in aggs[name].get("buckets") or []
    ]


def _gap_stats(epochs: list[int]) -> tuple[float | None, float | None]:
    """(mean gap in seconds, stdev / mean of the gaps): _assess_beacon's arithmetic, kept for
    pairs it doesn't list. None below 3 slots (one gap has no spread)."""
    deltas = [b - a for a, b in zip(epochs, epochs[1:])]
    if len(deltas) < 2:
        return None, None
    mean = statistics.mean(deltas)
    return round(mean / 1000, 1), round(statistics.stdev(deltas) / mean, 4)


def _timing(snap: SnapshotSearch, records: dict, key: dict, connections: int) -> dict:
    """The pair's 10 s slots, read as the scan reads them, and what the scan's rule makes of them.

    status: capped (too many slots to read whole: nothing is claimed), too_few (under
    BEACONING_MIN_CONNECTIONS calls or occupied slots, _assess_beacon's first test), periodic
    (_assess_beacon lists it) or irregular (enough calls, gaps too uneven).
    """
    found, complete = snap.groups(
        records,
        [
            {
                "t": {
                    "date_histogram": {
                        "field": "@timestamp",
                        "fixed_interval": f"{BEACON_SLOT_SECONDS}s",
                    }
                }
            }
        ],
        None,
        "beacon timing",
        max_buckets=TIMING_CAP,
    )
    if not complete:
        logger.info("Beacon pair %s: more than %d slots to time", key, TIMING_CAP)
        return {
            "status": "capped",
            "slots": len(found),
            "mean_gap_seconds": None,
            "jitter": None,
            "beacon": None,
            "gaps": [],
        }
    epochs = sorted(int(s["key"]["t"]) for s in found)
    beacon = _assess_beacon(key, connections, [{"key": t} for t in epochs])
    if (
        connections < BEACONING_MIN_CONNECTIONS
        or len(epochs) < BEACONING_MIN_CONNECTIONS
    ):
        status = "too_few"
    else:
        status = "periodic" if beacon else "irregular"
    mean, jitter = _gap_stats(epochs)
    gaps = Counter((b - a) // 1000 for a, b in zip(epochs, epochs[1:]))
    return {
        "status": status,
        "slots": len(epochs),
        "mean_gap_seconds": mean,
        "jitter": jitter,
        "beacon": (
            {
                k: beacon[k]
                for k in ("interval_seconds", "jitter_coefficient", "confidence")
            }
            if beacon
            else None
        ),
        "gaps": [
            {"seconds": s, "count": n}
            for s, n in sorted(gaps.items(), key=lambda g: (-g[1], g[0]))[:GAPS_SHOWN]
        ],
    }


def _names(
    snap: SnapshotSearch,
    query: dict,
    field: str,
    count_key: str,
    what: str,
    missing: bool = False,
) -> tuple[list[dict], bool]:
    """Every value of a name field with its record count, spellings of one host name merged
    (canonical form, as addresses._tls_names does), most first; False if capped."""
    terms: dict = {"field": field, **({"missing_bucket": True} if missing else {})}
    buckets, complete = snap.groups(
        query, [{"name": {"terms": terms}}], None, what, max_buckets=LIST_CAP
    )
    counts: Counter = Counter()
    for b in buckets:
        raw = b["key"]["name"]
        counts[None if raw is None else canonical_name(raw) or raw] += doc_count(
            b, what
        )
    rows = [{"name": name, count_key: n} for name, n in counts.items()]
    return sorted(rows, key=lambda r: (-r[count_key], r["name"] or "")), complete


def beacon_pair_figures(
    client: Any,
    device: str,
    server: str,
    port: int,
    from_ts: str,
    to_ts: str,
    slots: dict,
    budget: Budget,
) -> dict:
    """Everything the beaconing pair page shows, over one snapshot."""
    window = _time_range_filter(from_ts, to_ts)
    pair = [
        {"term": {"source.ip": device}},
        {"term": {"destination.ip": server}},
        {"term": {"destination.port": port}},
    ]
    # the scan's records (detect_beaconing): final conn records, no excluded-IP filter
    records = {"bool": {"filter": [window, *zeek("conn"), *pair]}}
    # names this device looked up that answered with the server: passive, no lookup is sent
    lookups = {
        "bool": {
            "filter": [
                window,
                *zeek("dns"),
                {"term": {"source.ip": device}},
                {"term": {"zeek.dns.answers": server}},
            ],
            "must_not": DNS_LOOKUP_EXCLUSION,
        }
    }
    what = "beacon totals"
    with SnapshotSearch(client, NETWORK_INDEX, budget) as snap:
        reply = snap.search(
            {
                "size": 0,
                "track_total_hits": True,
                "query": records,
                "aggs": {
                    "first": {"min": {"field": "@timestamp"}},
                    "last": {"max": {"field": "@timestamp"}},
                    "timeline": slots,
                    "transports": {"terms": {"field": "network.transport", "size": 3}},
                    "services": {"terms": {"field": "network.protocol", "size": 3}},
                },
            },
            what,
            ("first", "last", "timeline", "transports", "services"),
        )
        connections = total_hits(reply, what)
        timing = _timing(
            snap, records, {"src": device, "dst": server, "port": port}, connections
        )
        tls_names, tls_complete = _names(
            snap,
            {"bool": {"filter": [window, *zeek("ssl"), *pair]}},
            "zeek.ssl.server_name",
            "sessions",
            "beacon TLS names",
            missing=True,
        )
        dns_names, dns_complete = _names(
            snap, lookups, "zeek.dns.query", "lookups", "beacon DNS names"
        )
        by_alerts = _listed_by_alerts(snap, server, window)
    aggs = reply["aggregations"]
    return {
        "device": device,
        "server": server,
        "port": port,
        "from": from_ts,
        "to": to_ts,
        "connections": connections,
        "first_seen": iso_ms(metric(aggs, "first", what)),
        "last_seen": iso_ms(metric(aggs, "last", what)),
        "timeline": timeline(reply),
        "transports": _top(aggs, "transports", what),
        "services": _top(aggs, "services", what),
        "timing": timing,
        "tls_names": tls_names,
        "tls_complete": tls_complete,
        "dns_names": dns_names,
        "dns_complete": dns_complete,
        "threat_intel": threat_intel(server, by_alerts),
    }


async def handle_beacon_pair(request: web.Request) -> web.Response:
    """GET /api/threats/beaconing/pair?device=&server=&port=&from=&to=&interval="""
    query = request.query
    device, server = ip_param(query.get("device")), ip_param(query.get("server"))
    if device is None or server is None:
        return json_error(_NOT_AN_IP, 400)
    port = _port_param(query.get("port"))
    if port is None:
        return json_error(_BAD_PORT, 400)
    from_ts, to_ts, interval, slots = _window(request)
    if slots is None:
        return json_error(_TOO_LONG, 400)
    client, excluded = request.app["drill_client"], _excluded(request.app, device)
    return await run_drilldown(
        request,
        lambda budget: {
            **beacon_pair_figures(
                client, device, server, port, from_ts, to_ts, slots, budget
            ),
            "device_excluded": excluded,
            "interval": interval,
        },
        f"beaconing pair {device} -> {server}:{port}",
    )


# ---------------------------------------------------------------------------
# One device's failed lookups
# ---------------------------------------------------------------------------


def failed_name_kind(name: str) -> str:
    """What a failed lookup asked for, so the page can say what usually causes it.

    `generated` is the detector's own DGA rule on the name as stored (dns_name_evidence).
    """
    host = (name[:-1] if name.endswith(".") else name).lower()
    labels = host.split(".")
    if "_dns-sd" in labels:
        return "service_discovery"
    if host.endswith((".in-addr.arpa", ".ip6.arpa")):
        return "reverse"
    if labels[0] == "wpad":
        return "wpad"
    if len(labels) == 1:
        return "bare"
    if host.endswith(_LOCAL_SUFFIXES):
        return "local"
    if (dns_name_evidence(name) or NO_EVIDENCE)["dga"]:
        return "generated"
    return "other"


def failed_lookup_figures(
    client: Any, ip: str, from_ts: str, to_ts: str, slots: dict, budget: Budget
) -> dict:
    """Everything the failed lookups page shows, over one snapshot.

    The failed names are read in name order (a composite), so a capped read holds the first
    LIST_CAP names alphabetically, not the busiest; `kinds` covers every name read.
    """
    window = _time_range_filter(from_ts, to_ts)
    # the detector's records (analyze_dns_anomalies): no excluded-IP filter
    base = [window, *zeek("dns"), {"term": {"source.ip": ip}}]
    lookups = {"bool": {"filter": base, "must_not": DNS_LOOKUP_EXCLUSION}}
    failed = {"bool": {"filter": [*base, _NXDOMAIN], "must_not": DNS_LOOKUP_EXCLUSION}}
    what = "failed lookups"
    with SnapshotSearch(client, NETWORK_INDEX, budget) as snap:
        reply = snap.search(
            {
                "size": 0,
                "track_total_hits": True,
                "query": lookups,
                "aggs": {
                    "failed": {"filter": _NXDOMAIN},
                    "timeline": {**slots, "aggs": {"failed": {"filter": _NXDOMAIN}}},
                },
            },
            what,
            ("failed", "timeline"),
        )
        codes = _every_value(
            snap, lookups, "zeek.dns.rcode_name", "failed lookup response codes"
        )
        names, complete = snap.groups(
            failed,
            [{"name": {"terms": {"field": "zeek.dns.query"}}}],
            LAST_SEEN,
            "failed lookup names",
            max_buckets=LIST_CAP,
        )
    aggs = reply["aggregations"]
    rows = [
        {
            "name": b["key"]["name"],
            "lookups": doc_count(b, what),
            "last_seen": iso_ms(metric(b, "last", what)),
            "kind": failed_name_kind(b["key"]["name"]),
        }
        for b in names
    ]
    if not complete:
        logger.info("Failed lookups for %s: the names list stopped at its cap", ip)
    names_per_kind = Counter(r["kind"] for r in rows)
    lookups_per_kind: Counter = Counter()
    for r in rows:
        lookups_per_kind[r["kind"]] += r["lookups"]
    return {
        "ip": ip,
        "from": from_ts,
        "to": to_ts,
        "lookups": total_hits(reply, what),
        "failed": doc_count(aggs["failed"], what),
        "timeline": [
            {
                "t": b["key_as_string"],
                "n": doc_count(b, what),
                "failed": doc_count(b.get("failed"), what),
            }
            for b in histogram_buckets(aggs["timeline"])
        ],
        "rcodes": sorted(
            ({"rcode": code, "lookups": n} for code, n in codes),
            key=lambda r: -r["lookups"],
        ),
        "failed_names": sorted(rows, key=lambda r: (-r["lookups"], r["name"]))[
            :FAILED_NAMES_SHOWN
        ],
        "failed_names_read": len(rows),
        "failed_names_complete": complete,
        "kinds": sorted(
            (
                {"kind": k, "names": n, "lookups": lookups_per_kind[k]}
                for k, n in names_per_kind.items()
            ),
            key=lambda k: (-k["lookups"], k["kind"]),
        ),
        "generated_names": names_per_kind["generated"],
    }


async def handle_failed_lookups(request: web.Request) -> web.Response:
    """GET /api/threats/failed-lookups/{ip}?from=&to=&interval="""
    ip = ip_param(request.match_info["ip"])
    if ip is None:
        return json_error(_NOT_AN_IP, 400)
    from_ts, to_ts, interval, slots = _window(request)
    if slots is None:
        return json_error(_TOO_LONG, 400)
    client, excluded = request.app["drill_client"], _excluded(request.app, ip)
    return await run_drilldown(
        request,
        lambda budget: {
            **failed_lookup_figures(client, ip, from_ts, to_ts, slots, budget),
            "excluded": excluded,
            "interval": interval,
        },
        f"failed lookups {ip}",
    )


def register_threat_drilldown_routes(app: web.Application, client: Any) -> None:
    install(app, client)
    app.router.add_get("/api/threats/beaconing/pair", handle_beacon_pair)
    app.router.add_get("/api/threats/failed-lookups/{ip}", handle_failed_lookups)
    logger.info("Threat drill-down API routes registered (2 endpoints)")
