"""GET /api/local-services: the mDNS and SSDP announcements the capture saw, per sender (NET-264).

A row is an observed announcement: a service instance seen from one sender, as the frames show
the sender (IP, MAC, VLAN). It never says the sender owns the service: a reflector (the router)
re-sends other devices' announcements, and gets its own row per VLAN.

mDNS: Zeek dns records with answers sent to the mDNS groups. In a multicast-destination
connection only the originator sends, so source.ip is the sender. Unicast exchanges are left
out: their originator can be the querier. dns records carry no MAC or VLAN; the conn record with
the same zeek.uid has both. Joining every uid does not fit the budget (the G11 had ~27,000 mDNS
uids a day: 26 s of searches at 24 h, 39 s at 7 d even in one composite), so uids are joined one
by one only where that changes the answer:
1. who each address was: every (IP, MAC, VLAN) of the mDNS conn records
2. flows still open: uids announced lately that have no conn record yet
3. an address seen as one (MAC, VLAN) only: its closed flows' names, aggregated per IP, are that
   sender's (every one of its conn records names it)
4. the rest (an address seen with several MACs or VLANs, or with no conn record, and the open
   flows) uid by uid; a uid with no conn record keeps a row of its own, never merged
SSDP: conn records from port 1900 to port 1900 (NOTIFY, not M-SEARCH), by (IP, MAC, VLAN).
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from aiohttp import web
from opensearchpy import ConnectionTimeout, OpenSearchException

from api.devices import _mac_key, _registry_names, _with_owner
from api.drilldown_runner import (
    DRILL_SLOTS,
    LIST_CAP,
    iso_ms,
    json_error,
    run_drilldown,
    zeek,
)
from api.time_range import _utc, parse_time_range
from api.traffic import NETWORK_INDEX, _time_range_filter
from services.excluded_ips import CONN_RECORDS
from storage.all_buckets import PAGE_SIZE, all_buckets
from storage.exact_terms import PartialResultsError
from storage.snapshot_search import Budget, QueryFailed, TooSlow

logger = logging.getLogger("nettap.api.local_services")

MAX_SPAN = timedelta(days=7)
MDNS_GROUPS = ["224.0.0.251", "ff02::fb"]
# Zeek writes a UDP conn record once a flow is idle a minute; the longest mDNS flow on the G11
# ran 395 s in a day. shortcut: a conn record Zeek lost reads as its address's one sender;
# join every uid if Zeek ever loses records here
OPEN_FLOWS = timedelta(minutes=15)
# A conn record is stamped when its flow starts, before the flow's announcements.
# shortcut: a flow open longer than this reads as its address's one sender; widen it if needed
FLOW_START_PAD = timedelta(days=1)
# shortcut: the uid-by-uid read stops here (7 d on the G11: 6,065) and says truncated
UID_CAP = 20_000
# A reply holds at most search.max_buckets (65,535): a page of buckets with two name lists each is
# sized under this, as snapshot_search.py sizes its pages
PAGE_BUCKETS = 60_000
# Names one bucket may list (a full list says truncated). On the G11 at 7 d: 54 per sender (the
# router repeats everyone's), 15 per flow
NAMES_PER_SENDER = 1_000
NAMES_PER_FLOW = 50
# (name, bucket) pairs the two names reads may hold in all (the G11 at 7 d: ~18,500), so spoofed
# announcements can't fill the daemon's memory; past it the reads stop and say truncated
NAMES_READ = 100_000
# A DNS-SD instance. Zeek lowercases names, so capitals start only its own rdata strings
# ("NSEC a._x._tcp.local …", "TXT …")
_INSTANCE_RX = r"[^_].*\._[a-z0-9-]+\._(tcp|udp)\.local"
_RDATA_RX = r"[A-Z][A-Z0-9]* .*"
_INSTANCE = re.compile(r"([^_].*)\.(_[a-z0-9-]+\._(?:tcp|udp))\.local")
_RDATA = re.compile(_RDATA_RX)
_NOT_SERVICES = {"_dns-sd._udp"}  # browse domains (lb._dns-sd._udp.local), not services

_CONN = [{"term": {"event.provider": "zeek"}}, CONN_RECORDS]
_IP = {"ip": {"terms": {"field": "source.ip"}}}
_UID = {"uid": {"terms": {"field": "zeek.uid"}}}
_WHO = [
    {"mac": {"terms": {"field": "source.mac", "missing_bucket": True}}},
    {"vlan": {"terms": {"field": "network.vlan.id", "missing_bucket": True}}},
]


# OLD CODE START — NET-264 review: one list size (1,000) for every read, so a page of 1,000
# flows could ask for 2M buckets, past search.max_buckets
# def _names(field: str) -> dict:
#     return {
#         "terms": {
#             "field": field,
#             "include": _INSTANCE_RX,
#             "exclude": _RDATA_RX,
#             "size": NAMES_PER_SENDER,
#         },
#         "aggs": {"last": {"max": {"field": "@timestamp"}}},
#     }
#
#
# _NAME_AGGS = {"q": _names("zeek.dns.query"), "a": _names("zeek.dns.answers")}
# OLD CODE END
def _names(field: str, size: int) -> dict:
    return {
        "terms": {
            "field": field,
            "include": _INSTANCE_RX,
            "exclude": _RDATA_RX,
            "size": size,
        },
        "aggs": {"last": {"max": {"field": "@timestamp"}}},
    }


def _name_aggs(size: int) -> dict:
    """The names a bucket's records announced, from both fields, up to `size` each."""
    return {"q": _names("zeek.dns.query", size), "a": _names("zeek.dns.answers", size)}


def _names_budget() -> Callable[[list[dict]], bool]:
    """A `stop` for the names reads: True once they hold more than NAMES_READ pairs."""
    held = 0

    def over(page: list[dict]) -> bool:
        nonlocal held
        held += sum(len(b["q"]["buckets"]) + len(b["a"]["buckets"]) for b in page)
        return held > NAMES_READ

    return over


def _mdns(filters: list[dict], *more: dict) -> dict:
    return {
        "bool": {
            "filter": [
                *filters,
                {"term": {"destination.port": 5353}},
                {"terms": {"destination.ip": MDNS_GROUPS}},
                *more,
            ]
        }
    }


def _announcements(*more: dict) -> dict:
    return _mdns(zeek("dns"), {"exists": {"field": "zeek.dns.answers"}}, *more)


def _read(
    client: Any,
    budget: Budget,
    query: dict,
    sources: list[dict],
    what: str,
    aggs: dict | None = None,
    cap: int | None = None,
    names: int = 0,
    stop: Callable[[list[dict]], bool] | None = None,
) -> tuple[list[dict], bool]:
    """Every bucket, up to `cap`; with `names`, each lists up to that many names per field, and a
    page holds at most PAGE_BUCKETS buckets in all."""
    cap = cap or LIST_CAP
    per_bucket = 1 + 2 * names
    return all_buckets(
        client,
        NETWORK_INDEX,
        query,
        sources,
        aggs=_name_aggs(names) if names else aggs,
        page_size=max(1, min(PAGE_SIZE, cap, PAGE_BUCKETS // per_bucket)),
        max_buckets=cap,
        what=what,
        budget=budget,
        stop=stop,
    )


def _joined(
    client: Any, budget: Budget, uids: list[str]
) -> tuple[dict[str, list[tuple]], bool]:
    """({uid: [(mac, vlan), …]} from each uid's conn record, complete?).

    A uid with no conn record is absent; a frame with two VLAN tags gives two pairs."""
    if not uids:
        return {}, True
    found, done = _read(
        client,
        budget,
        {"bool": {"filter": [*_CONN, {"terms": {"zeek.uid": uids}}]}},
        [_UID, *_WHO],
        "the mDNS connections",
        cap=UID_CAP,
    )
    out: dict[str, list[tuple]] = {}
    for b in found:
        out.setdefault(b["key"]["uid"], []).append((b["key"]["mac"], b["key"]["vlan"]))
    return out, done


def _instances(bucket: dict) -> tuple[dict[tuple[str, str], str], bool]:
    """({(service type, instance): last seen} of a bucket's names, complete?)."""
    out: dict[tuple[str, str], str] = {}
    for b in [*bucket["q"]["buckets"], *bucket["a"]["buckets"]]:
        found = _INSTANCE.fullmatch(b["key"])
        if not found or _RDATA.fullmatch(b["key"]) or found[2] in _NOT_SERVICES:
            continue
        key, seen = (found[2], found[1]), iso_ms(b["last"]["value"])
        out[key] = max(out.get(key, seen), seen)
    complete = not (
        bucket["q"]["sum_other_doc_count"] or bucket["a"]["sum_other_doc_count"]
    )
    return out, complete


def _sender(ip: str, mac: str | None, vlan: str | None, joined: bool) -> dict:
    state = ("tagged" if vlan is not None else "untagged") if joined else "unknown"
    return {"ip": ip, "mac": mac, "name": None, "vlan": vlan, "vlan_state": state}


def _row(protocol: str, service: tuple | None, sender: dict, last_seen: str) -> dict:
    service_type, instance = service or (None, None)
    return {
        "protocol": protocol,
        "service_type": service_type,
        "instance": instance,
        "sender": sender,
        "last_seen": last_seen,
    }


def _row_id(key: tuple) -> str:
    """A stable id for a row's merge key: two unresolved flows can read the same on screen."""
    return hashlib.blake2b(json.dumps(key).encode(), digest_size=8).hexdigest()


def _newest(keyed: list[tuple[tuple, dict]]) -> list[dict]:
    """One row per key: the one last seen, with that announcement's IP."""
    best: dict[tuple, dict] = {}
    for key, row in keyed:
        if key not in best or row["last_seen"] > best[key]["last_seen"]:
            best[key] = row
    # OLD CODE: return list(best.values()) (NET-264 review: rows carry their key's id)
    return [{"id": _row_id(key), **row} for key, row in best.items()]


def _mdns_rows(
    client: Any, from_ts: str, to_ts: str, now: datetime, budget: Budget
) -> tuple[list[dict], bool, int]:
    """(rows, complete?, uids joined one by one)."""
    window = _time_range_filter(from_ts, to_ts)
    padded = _time_range_filter((_utc(from_ts) - FLOW_START_PAD).isoformat(), to_ts)
    who, done = _read(
        client, budget, _mdns(_CONN, padded), [_IP, *_WHO], "the mDNS senders"
    )
    seen_as: dict[str, set] = {}
    for b in who:
        seen_as.setdefault(b["key"]["ip"], set()).add(
            (b["key"]["mac"], b["key"]["vlan"])
        )

    lately = _time_range_filter((now - OPEN_FLOWS).isoformat(), now.isoformat())
    recent, recent_done = _read(
        client, budget, _announcements(lately), [_UID], "the open mDNS flows"
    )
    recent_uids = [b["key"]["uid"] for b in recent]
    closed, closed_done = _joined(client, budget, recent_uids)
    open_uids = [u for u in recent_uids if u not in closed]
    held_names = _names_budget()  # shared: both names reads count against one budget
    # a capped read could hide an address's second sender or an open flow: then every uid is joined
    one = (
        {ip: next(iter(pairs)) for ip, pairs in seen_as.items() if len(pairs) == 1}
        if done and recent_done
        else {}
    )

    singles, singles_done = _read(
        client,
        budget,
        {
            "bool": {
                "filter": [_announcements(window), {"terms": {"source.ip": list(one)}}],
                "must_not": [{"terms": {"zeek.uid": open_uids}}],
            }
        },
        [_IP],
        "the mDNS names per sender",
        names=NAMES_PER_SENDER,
        stop=held_names,
    )
    rest = {
        "bool": {
            "filter": [_announcements(window)],
            "should": [
                {"bool": {"must_not": [{"terms": {"source.ip": list(one)}}]}},
                {"terms": {"zeek.uid": open_uids}},
            ],
            "minimum_should_match": 1,
        }
    }
    by_uid, by_uid_done = _read(
        client,
        budget,
        rest,
        [_UID, _IP],
        "the mDNS names per flow",
        cap=UID_CAP,
        names=NAMES_PER_FLOW,
        stop=held_names,
    )
    joined, joined_done = _joined(client, budget, [b["key"]["uid"] for b in by_uid])

    keyed: list[tuple[tuple, dict]] = []
    complete = all(
        (done, recent_done, closed_done, singles_done, by_uid_done, joined_done)
    )
    for b in singles:
        ip = b["key"]["ip"]
        mac, vlan = one[ip]
        names, names_done = _instances(b)
        complete = complete and names_done
        for svc, last in names.items():
            row = _row("mdns", svc, _sender(ip, mac, vlan, True), last)
            keyed.append((("mdns", *svc, mac, vlan), row))
    for b in by_uid:
        uid, ip = b["key"]["uid"], b["key"]["ip"]
        names, names_done = _instances(b)
        complete = complete and names_done
        for svc, last in names.items():
            for mac, vlan in joined.get(uid, []):
                row = _row("mdns", svc, _sender(ip, mac, vlan, True), last)
                keyed.append((("mdns", *svc, mac, vlan), row))
            if (
                uid not in joined
            ):  # identity not known yet: never merged with another uid
                row = _row("mdns", svc, _sender(ip, None, None, False), last)
                keyed.append((("mdns", *svc, "uid", uid), row))
    return _newest(keyed), complete, len(by_uid)


def _ssdp_rows(
    client: Any, from_ts: str, to_ts: str, budget: Budget
) -> tuple[list[dict], bool]:
    found, done = _read(
        client,
        budget,
        {
            "bool": {
                "filter": [
                    *_CONN,
                    _time_range_filter(from_ts, to_ts),
                    {"term": {"source.port": 1900}},
                    {"term": {"destination.port": 1900}},
                ]
            }
        },
        [_IP, *_WHO],
        "the SSDP senders",
        aggs={"last": {"max": {"field": "@timestamp"}}},
    )
    rows = [
        {
            "id": _row_id(("ssdp", ip, mac, vlan)),
            **_row(
                "ssdp", None, _sender(ip, mac, vlan, True), iso_ms(b["last"]["value"])
            ),
        }
        for b in found
        for ip, mac, vlan in [(b["key"]["ip"], b["key"]["mac"], b["key"]["vlan"])]
    ]
    return rows, done


def _named(request: web.Request, rows: list[dict]) -> list[dict]:
    """Rows with the sender's name: the owner's, else the registry's, by MAC only (an IP is
    reused, and link-local addresses repeat across VLANs)."""
    macs = list({r["sender"]["mac"] for r in rows if r["sender"]["mac"]})
    registry = _registry_names(request, macs)

    def name(mac: str | None) -> str | None:
        if not mac:
            return None
        found = {"mac": mac, "hostname": registry.get(_mac_key(mac))}
        return _with_owner(request, found).get("hostname")

    return [
        {**r, "sender": {**r["sender"], "name": name(r["sender"]["mac"])}} for r in rows
    ]


def local_services(
    request: web.Request,
    client: Any,
    from_ts: str,
    to_ts: str,
    now: datetime,
    budget: Budget,
) -> dict:
    """The reply; QueryFailed (a 502) for a failed or partial read, TooSlow once out of budget."""
    began = time.monotonic()
    try:
        mdns, mdns_done, per_uid = _mdns_rows(client, from_ts, to_ts, now, budget)
        ssdp, ssdp_done = _ssdp_rows(client, from_ts, to_ts, budget)
    except TooSlow:
        raise
    except ConnectionTimeout as exc:  # a read waited all the budget had left
        logger.warning("Local services search ran out of time: %s", exc)
        raise TooSlow("the local service search took too long") from exc
    except (QueryFailed, PartialResultsError) as exc:
        logger.warning("Local services search was incomplete: %s", exc)
        raise QueryFailed("the local service search was incomplete") from exc
    except OpenSearchException as exc:
        logger.warning("Local services search failed: %s", exc)
        raise QueryFailed("the local service search failed") from exc
    budget.check("the sender names")
    # OLD CODE START — NET-264 review: every row was named before the cut
    # rows = sorted(
    #     _named(request, [*mdns, *ssdp]), key=lambda r: r["last_seen"], reverse=True
    # )
    # OLD CODE END
    rows = sorted([*mdns, *ssdp], key=lambda r: r["last_seen"], reverse=True)
    truncated = not (mdns_done and ssdp_done) or len(rows) > LIST_CAP
    logger.info(
        "Local services %s to %s: %d rows (%d flows joined one by one), truncated=%s, in %.2f s",
        from_ts,
        to_ts,
        len(rows),
        per_uid,
        truncated,
        time.monotonic() - began,
    )
    return {
        "from": from_ts,
        "to": to_ts,
        "truncated": truncated,
        # OLD CODE: "rows": rows[:LIST_CAP], (NET-264 review: named after the cut)
        "rows": _named(request, rows[:LIST_CAP]),
    }


async def handle_local_services(request: web.Request) -> web.Response:
    """GET /api/local-services?from=&to= (default the last 24 hours, at most 7 days)."""
    from_ts, to_ts = parse_time_range(request, timedelta(hours=24))
    if _utc(to_ts) - _utc(from_ts) > MAX_SPAN:
        return json_error("The window can be at most 7 days.", 400)
    client = request.app["local_services_client"]
    now = datetime.now(timezone.utc)
    return await run_drilldown(
        request,
        lambda budget: local_services(request, client, from_ts, to_ts, now, budget),
        "local services",
    )


def register_local_service_routes(app: web.Application, client: Any) -> None:
    """`client`: the daemon's exact-terms client without retries (the moment page's)."""
    app["local_services_client"] = client
    app.setdefault("drill_slots", asyncio.Semaphore(DRILL_SLOTS))
    app.router.add_get("/api/local-services", handle_local_services)
    logger.info("Local services API routes registered (1 endpoint)")
