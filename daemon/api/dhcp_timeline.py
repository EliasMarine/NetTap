"""GET /api/dhcp/timeline: one device's DHCP transactions over a window (NET-263).

Zeek's dhcp.log holds one record per transaction (grouped by xid). Its message types are a
multiset with no recorded order, and Zeek keeps no server per message. The servers come from
the transaction's connections (its zeek.uid list): the side of each conn record on port 67.
That is connection-level evidence only, since one UDP connection can carry several
transactions, so the web names a server for a message only when a transaction has exactly one
server endpoint and every one of its connections has a record (`endpoints_complete`).

Two reads in a drill-down slot, on the no-retry exact-terms client, inside the request's
budget (api/drilldown_runner.py), so a slow read answers "took too long" and frees its slot.
"""

import asyncio
import ipaddress
import logging
import re
import time
from collections import Counter
from typing import Any

from aiohttp import web
from opensearchpy import ConnectionTimeout, OpenSearchException

from api.devices import _RESULT_WINDOW, _parse_time_range
from api.drilldown_runner import DRILL_SLOTS, json_error, run_drilldown, zeek
from api.traffic import NETWORK_INDEX, _time_range_filter
from storage.exact_terms import PartialResultsError, SearchTimedOut
from storage.snapshot_search import Budget, QueryFailed, TooSlow, checked, total_hits

logger = logging.getLogger("nettap.api.dhcp_timeline")

TRANSACTION_CAP = 200
SERVER_PORT = 67
_NOT_AN_ADDRESS = {"0.0.0.0", "255.255.255.255"}
# OLD CODE START — PR #263 review: macOS arp prints octets with one digit (0:1b:63:84:45:e6)
# # aa:bb:cc:dd:ee:ff, aa-bb-…, aabb.ccdd.eeff or aabbccddeeff (any case); extended addresses are out of scope
# _MAC = re.compile(
#     r"[0-9a-f]{2}([:-])(?:[0-9a-f]{2}\1){4}[0-9a-f]{2}|(?:[0-9a-f]{4}\.){2}[0-9a-f]{4}|[0-9a-f]{12}"
# )
# OLD CODE END
# Six octets of one or two digits split by ":" or "-", or aabb.ccdd.eeff, or aabbccddeeff (any
# case); extended (non-Ethernet) addresses are out of scope
_OCTETS = re.compile(r"[0-9a-f]{1,2}([:-])(?:[0-9a-f]{1,2}\1){4}[0-9a-f]{1,2}")
_GROUPED = re.compile(r"(?:[0-9a-f]{4}\.){2}[0-9a-f]{4}|[0-9a-f]{12}")
BAD_MAC = "Enter a six-byte MAC address, such as aa:bb:cc:dd:ee:ff."

# The plan's outcome table: the first test the message types pass names the transaction
_OUTCOMES = (
    ("mixed", lambda seen: {"ACK", "NAK"} <= seen),
    ("ack", lambda seen: "ACK" in seen),
    ("nak", lambda seen: "NAK" in seen),
    ("offer_no_reply", lambda seen: "OFFER" in seen),
    (
        "discover_no_offer",
        lambda seen: "DISCOVER" in seen and seen <= {"DISCOVER", "DECLINE"},
    ),
    ("request_no_reply", lambda seen: "REQUEST" in seen),
    ("release", lambda seen: "RELEASE" in seen),
    ("decline", lambda seen: "DECLINE" in seen),
    ("inform", lambda seen: "INFORM" in seen),
)


def canonical_mac(raw: Any) -> str | None:
    """Six lowercase colon-separated two-digit octets (the stored form), or None."""
    # OLD CODE START — PR #263 review: one-digit octets
    # if not isinstance(raw, str) or not _MAC.fullmatch(text := raw.strip().lower()):
    #     return None
    # digits = re.sub(r"[:.-]", "", text)
    # return ":".join(digits[i : i + 2] for i in range(0, 12, 2))
    # OLD CODE END
    if not isinstance(raw, str):
        return None
    text = raw.strip().lower()
    if found := _OCTETS.fullmatch(text):
        return ":".join(o.zfill(2) for o in text.split(found.group(1)))
    if _GROUPED.fullmatch(text):
        digits = text.replace(".", "")
        return ":".join(digits[i : i + 2] for i in range(0, 12, 2))
    return None


def outcome(messages: Counter) -> str:
    seen = set(messages)
    return next((name for name, test in _OUTCOMES if test(seen)), "other")


def _listed(value: Any) -> list:
    return value if isinstance(value, list) else [] if value is None else [value]


# OLD CODE START — PR #263 review: any string passed, so an odd record could fail the page
# def _address(value: Any) -> str | None:
#     return value if isinstance(value, str) and value not in _NOT_AN_ADDRESS else None
# OLD CODE END
def _address(value: Any) -> str | None:
    """A valid IP other than 0.0.0.0 and broadcast, or None."""
    try:
        # a str only: ip_address(7) would be 0.0.0.7
        ip = str(ipaddress.ip_address(value)) if isinstance(value, str) else None
    except ValueError:
        return None
    return None if ip is None or ip in _NOT_AN_ADDRESS else ip


def _uids(record: dict) -> list[str]:
    return [
        u for u in _listed((record.get("zeek") or {}).get("uid")) if isinstance(u, str)
    ]


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _number(value: Any) -> float | int | None:
    return (
        value
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else None
    )


def _ip_order(ip: str) -> tuple:
    address = ipaddress.ip_address(ip)
    return (address.version, address)


def _server_ends(conn: dict) -> list[str]:
    """The conn record's sides on port 67: the originator or the responder (both for a relay)."""
    sides = [conn.get("source") or {}, conn.get("destination") or {}]
    return [
        ip
        for s in sides
        if s.get("port") == SERVER_PORT and (ip := _address(s.get("ip")))
    ]


def _search(
    client: Any, body: dict, budget: Budget, what: str
) -> tuple[list[dict], int]:
    """The hits' `_source`s and the exact hit total; TooSlow once out of time, else QueryFailed."""
    try:
        reply = client.search(index=NETWORK_INDEX, body=body, budget=budget)
    except (ConnectionTimeout, SearchTimedOut) as exc:
        logger.warning("DHCP timeline: %s ran out of time: %s", what, exc)
        raise TooSlow(f"{what} took too long") from exc
    except PartialResultsError as exc:
        logger.warning("DHCP timeline: %s was incomplete: %s", what, exc)
        raise QueryFailed(f"{what} was incomplete") from exc
    except OpenSearchException as exc:
        logger.warning("DHCP timeline: %s failed: %s", what, exc)
        raise QueryFailed(f"{what} failed") from exc
    hits = (checked(reply, what).get("hits") or {}).get("hits")
    if not isinstance(hits, list):
        raise QueryFailed(f"{what}: malformed reply")
    return [h.get("_source") or {} for h in hits], total_hits(reply, what)


def _endpoints(client: Any, uids: list[str], budget: Budget) -> dict[str, list[str]]:
    """{uid: its server endpoints} for every uid that has a final conn record."""
    conns, _ = _search(
        client,
        {
            # OLD CODE: "size": len(uids), (PR #263 review: past the result window the read failed)
            # a uid left out past the window counts as not recorded, so its transaction is incomplete
            "size": min(len(uids), _RESULT_WINDOW),
            "track_total_hits": True,
            "_source": [
                "zeek.uid",
                "source.ip",
                "source.port",
                "destination.ip",
                "destination.port",
            ],
            # no time filter: a connection can start before the window its transaction is in
            "query": {
                "bool": {"filter": [*zeek("conn"), {"terms": {"zeek.uid": uids}}]}
            },
        },
        budget,
        "the DHCP connections search",
    )
    found: dict[str, list[str]] = {}
    for conn in conns:
        uid = (conn.get("zeek") or {}).get("uid")
        if isinstance(uid, str):
            found.setdefault(uid, []).extend(_server_ends(conn))
    return found


def _transaction(record: dict, ends: dict[str, list[str]]) -> dict:
    dhcp = (record.get("zeek") or {}).get("dhcp") or {}
    uids = _uids(record)
    messages = Counter(m for m in _listed(dhcp.get("msg_types")) if isinstance(m, str))
    # OLD CODE START — PR #263 review: fields as stored, so one odd record failed the page's check;
    # endpoints sorted as text (192.168.1.10 before 192.168.1.5)
    # return {
    #     "ts": record.get("@timestamp"),
    #     "duration": dhcp.get("duration"),
    #     "messages": dict(sorted(messages.items())),
    #     "requested_ip": dhcp.get("requested_ip"),
    #     "assigned_ip": dhcp.get("assigned_ip"),
    #     "client_ip": _address((record.get("source") or {}).get("ip")),
    #     "lease_time": dhcp.get("lease_time"),
    #     "host_name": dhcp.get("host_name"),
    #     "client_software": dhcp.get("client_software"),
    #     "zeek_server": _address((record.get("destination") or {}).get("ip")),
    #     "server_endpoints": sorted({ip for u in uids for ip in ends.get(u, [])}),
    #     "endpoints_complete": all(u in ends for u in uids),
    #     "server_message": dhcp.get("server_message"),
    #     "outcome": outcome(messages),
    # }
    # OLD CODE END
    # every field is its type or None, so one odd record can't fail the page
    return {
        "ts": record.get("@timestamp"),
        "duration": _number(dhcp.get("duration")),
        # a multiset: Zeek records no order, so the keys are sorted to say so
        "messages": dict(sorted(messages.items())),
        "requested_ip": _address(dhcp.get("requested_ip")),
        "assigned_ip": _address(dhcp.get("assigned_ip")),
        # the address the client sent from (ciaddr when renewing), for a NAK or REQUEST sentence
        "client_ip": _address((record.get("source") or {}).get("ip")),
        "lease_time": _number(dhcp.get("lease_time")),
        "host_name": _text(dhcp.get("host_name")),
        "client_software": _text(dhcp.get("client_software")),
        "zeek_server": _address((record.get("destination") or {}).get("ip")),
        "server_endpoints": sorted(
            {ip for u in uids for ip in ends.get(u, [])}, key=_ip_order
        ),
        "endpoints_complete": all(u in ends for u in uids),
        "server_message": _text(dhcp.get("server_message")),
        "outcome": outcome(messages),
    }


def dhcp_timeline(
    client: Any, mac: str, from_ts: str, to_ts: str, budget: Budget
) -> dict:
    """The reply; QueryFailed (a 502) for a failed or partial read, TooSlow once out of budget."""
    began = time.monotonic()
    records, total = _search(
        client,
        {
            "size": TRANSACTION_CAP,
            "track_total_hits": True,
            "sort": [{"@timestamp": {"order": "desc"}}],
            "_source": [
                "@timestamp",
                "zeek.uid",
                "zeek.dhcp",
                "source.ip",
                "destination.ip",
            ],
            "query": {
                "bool": {
                    "filter": [
                        _time_range_filter(from_ts, to_ts),
                        *zeek("dhcp"),
                        {"term": {"zeek.dhcp.mac": mac}},
                    ]
                }
            },
        },
        budget,
        "the DHCP search",
    )
    uids = sorted({u for r in records for u in _uids(r)})
    ends = _endpoints(client, uids, budget) if uids else {}
    # %r: a newline in from or to gets past fromisoformat, so it can't start a fake log line
    logger.info(
        "DHCP timeline for %s, %r to %r: %d transactions in %.2f s",
        mac,
        from_ts,
        to_ts,
        len(records),
        time.monotonic() - began,
    )
    return {
        "mac": mac,
        "from": from_ts,
        "to": to_ts,
        "truncated": total > len(records),
        "transactions": [_transaction(r, ends) for r in records],
    }


async def handle_dhcp_timeline(request: web.Request) -> web.Response:
    """GET /api/dhcp/timeline?mac=&from=&to= (the last 24 hours by default)."""
    mac = canonical_mac(request.query.get("mac"))
    if mac is None:
        return json_error(BAD_MAC, 400)
    from_ts, to_ts = _parse_time_range(request)
    client = request.app["dhcp_client"]
    return await run_drilldown(
        request,
        lambda budget: dhcp_timeline(client, mac, from_ts, to_ts, budget),
        "the DHCP timeline",
    )


def register_dhcp_timeline_routes(app: web.Application, client: Any) -> None:
    """`client`: the daemon's exact-terms client without retries (the moment page's)."""
    app["dhcp_client"] = client
    # the drill-down pages' shared permits, whichever registers first
    app.setdefault("drill_slots", asyncio.Semaphore(DRILL_SLOTS))
    app.router.add_get("/api/dhcp/timeline", handle_dhcp_timeline)
    logger.info("DHCP timeline route registered (1 endpoint)")
