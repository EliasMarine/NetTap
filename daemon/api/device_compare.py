"""GET /api/moment/device-compare: what one device started in two periods, side by side (NET-265).

The Moment breakdown is a top 5, so this reads every destination instead: one msearch, one
body per period, with the breakdown's "started" predicate on the device's IP over a
half-open window [from, to), so a record on the boundary counts in one period only. Each
body sums its bytes on its own, so the totals never depend on a list being complete.

The destination lists are terms in doc-count order (the error bound is only meaningful
there) on the exact-terms client, ranked by bytes here. Two signals per period decide what
the reply can say: list_complete (no destination left out of the list) and buckets_exact
(no shard cut its list short, so the counts are not estimates). New and gone need both in
both periods; changes need exact buckets; without them only the totals are sent.

shortcut: it compares the connections the device started from this IP, so after an IP
change the earlier traffic is under the old address; upgrade when compare keys on MAC.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from aiohttp import web
from opensearchpy import ConnectionTimeout, OpenSearchException

from api.drilldown_runner import ip_param, json_error, run_drilldown
from api.time_range import _bad_request, _utc, iso_param
from api.traffic import _CONN_BYTES_SUM, _ZEEK_CONN_FILTERS, NETWORK_INDEX
from services.excluded_ips import build_excluded_ips_filter, valid_excluded_ips
from storage.exact_terms import PartialResultsError, truncated
from storage.snapshot_search import Budget, QueryFailed, TooSlow, checked

logger = logging.getLogger("nettap.api.device_compare")

_TERMS_SIZE = 10_000  # destinations per period; past it the list is incomplete
_LIST_CAP = 50  # rows per reply list, with its full count
_MAX_SPAN = timedelta(days=7)
_SAME_LENGTH = timedelta(seconds=1)
_FUTURE_SLACK = timedelta(seconds=60)  # the browser's clock may run a little ahead
_PARAMS = ("a_from", "a_to", "b_from", "b_to")

Window = tuple[str, str]


def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def parse_windows(request: web.Request) -> tuple[Window, Window]:
    """((a_from, a_to), (b_from, b_to)) as UTC ISO times; a 400 with a plain sentence if not."""
    raw = [iso_param(request, name) for name in _PARAMS]  # 400 when one is unreadable
    if not all(raw):
        raise _bad_request("a_from, a_to, b_from and b_to are all required.")
    a_from, a_to, b_from, b_to = (_utc(r) for r in raw)
    if a_from >= a_to or b_from >= b_to:
        raise _bad_request("Each period must end after it starts.")
    if abs((a_to - a_from) - (b_to - b_from)) > _SAME_LENGTH:
        raise _bad_request("Both periods must be the same length.")
    if a_to - a_from > _MAX_SPAN:
        raise _bad_request("A period can be at most 7 days long.")
    if a_from < b_to and b_from < a_to:
        raise _bad_request("The two periods must not overlap.")
    if max(a_to, b_to) > datetime.now(timezone.utc) + _FUTURE_SLACK:
        raise _bad_request("A period can't end in the future.")
    return (_iso(a_from), _iso(a_to)), (_iso(b_from), _iso(b_to))


def _period_body(ip: str, window: Window, excluded: list[str]) -> dict:
    """The connections `ip` started in [from, to), every destination with its bytes."""
    from_ts, to_ts = window
    return {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    # half-open, unlike the shared lte filter: periods meet without overlapping
                    {
                        "range": {
                            "@timestamp": {
                                "gte": from_ts,
                                "lt": to_ts,
                                "format": "strict_date_optional_time",
                            }
                        }
                    },
                    *_ZEEK_CONN_FILTERS,
                    {"term": {"source.ip": ip}},
                ],
                "must_not": build_excluded_ips_filter(excluded),
            }
        },
        "aggs": {
            "total": _CONN_BYTES_SUM,
            "destinations": {
                "terms": {"field": "destination.ip", "size": _TERMS_SIZE},
                "aggs": {
                    "bytes": _CONN_BYTES_SUM,
                    "org": {"terms": {"field": "destination.as.full", "size": 1}},
                },
            },
        },
    }


def _by_ip(agg: dict) -> dict[str, tuple[int, str | None]]:
    """{destination: (bytes, organisation)} from a destinations aggregation."""
    return {
        b["key"]: (
            round(b["bytes"]["value"] or 0),
            b["org"]["buckets"][0]["key"] if b["org"]["buckets"] else None,
        )
        for b in agg["buckets"]
    }


def _capped(rows: list[dict]) -> dict:
    return {"total": len(rows), "items": rows[:_LIST_CAP]}


def _only_in(
    here: dict[str, tuple[int, str | None]], there: dict[str, tuple[int, str | None]]
) -> list[dict]:
    """The destinations in `here` and not in `there`, largest first."""
    rows = [
        {"ip": ip, "org": org, "bytes": n}
        for ip, (n, org) in here.items()
        if ip not in there
    ]
    return sorted(rows, key=lambda r: (-r["bytes"], r["ip"]))


def _changes(
    a: dict[str, tuple[int, str | None]], b: dict[str, tuple[int, str | None]]
) -> list[dict]:
    """The destinations in both whose bytes changed, by the size of the change."""
    rows = [
        {
            "ip": ip,
            "org": b[ip][1] or a[ip][1],
            "a_bytes": a[ip][0],
            "b_bytes": b[ip][0],
            "delta": b[ip][0] - a[ip][0],
        }
        for ip in a.keys() & b.keys()
        if a[ip][0] != b[ip][0]
    ]
    return sorted(rows, key=lambda r: (-abs(r["delta"]), r["ip"]))


def _period(window: Window, reply: dict) -> dict:
    aggs = reply["aggregations"]
    listed = aggs["destinations"]
    exact = not truncated(listed)
    return {
        "from": window[0],
        "to": window[1],
        "total_bytes": round(aggs["total"]["value"] or 0),
        # a count from estimated buckets is no count at all
        "destinations": len(listed["buckets"]) if exact else None,
        "list_complete": listed.get("sum_other_doc_count") == 0,
        "buckets_exact": exact,
    }


def compare(a: Window, b: Window, a_reply: dict, b_reply: dict) -> dict:
    """The reply's figures from the two checked period replies."""
    periods = {"a": _period(a, a_reply), "b": _period(b, b_reply)}
    exact = all(p["buckets_exact"] for p in periods.values())
    complete = exact and all(p["list_complete"] for p in periods.values())
    out = {**periods, "exact": exact, "complete": complete}
    if not exact:
        return {**out, "new": None, "gone": None, "changed": None}
    a_ips, b_ips = (
        _by_ip(r["aggregations"]["destinations"]) for r in (a_reply, b_reply)
    )
    return {
        **out,
        # a destination left off a list can't be called new or gone
        "new": _capped(_only_in(b_ips, a_ips)) if complete else None,
        "gone": _capped(_only_in(a_ips, b_ips)) if complete else None,
        "changed": {**_capped(_changes(a_ips, b_ips)), "partial": not complete},
    }


def device_compare(
    request: web.Request, client: Any, ip: str, a: Window, b: Window, budget: Budget
) -> dict:
    """The reply; QueryFailed (a 502) for a failed or partial read, TooSlow once out of budget."""
    began = time.monotonic()
    excluded = valid_excluded_ips(request.app.get("excluded_ips", []))
    body = []
    for window in (a, b):
        body += [{"index": NETWORK_INDEX}, _period_body(ip, window, excluded)]
    try:
        replies = client.msearch(body=body, budget=budget).get("responses")
        if not isinstance(replies, list) or len(replies) != 2:
            raise QueryFailed("the device compare reply was malformed")
        a_reply, b_reply = (
            checked(r, "the device compare", ("total", "destinations"))
            for r in replies
        )
    except TooSlow:
        raise
    except ConnectionTimeout as exc:  # the read waited all the budget had left
        logger.warning("Device compare for %s ran out of time: %s", ip, exc)
        raise TooSlow("the device compare took too long") from exc
    except (QueryFailed, PartialResultsError) as exc:
        logger.warning("Device compare for %s was incomplete: %s", ip, exc)
        raise QueryFailed("the device compare was incomplete") from exc
    except OpenSearchException as exc:
        logger.warning("Device compare for %s failed: %s", ip, exc)
        raise QueryFailed("the device compare failed") from exc
    reply = {"ip": ip, **compare(a, b, a_reply, b_reply)}
    logger.info(
        "Device compare %s, %s to %s vs %s to %s: %s destinations, exact=%s complete=%s in %.2f s",
        ip,
        *a,
        *b,
        (reply["a"]["destinations"], reply["b"]["destinations"]),
        reply["exact"],
        reply["complete"],
        time.monotonic() - began,
    )
    return reply


async def handle_device_compare(request: web.Request) -> web.Response:
    """GET /api/moment/device-compare?ip=&a_from=&a_to=&b_from=&b_to="""
    ip = ip_param(request.query.get("ip"))
    if ip is None:
        return json_error("ip must be an IP address.", 400)
    a, b = parse_windows(request)
    client = request.app["moment_client"]  # exact terms, no retries (api/moment.py)
    return await run_drilldown(
        request,
        lambda budget: device_compare(request, client, ip, a, b, budget),
        "device compare",
    )


def register_device_compare_routes(app: web.Application) -> None:
    """After register_moment_routes: it uses that client and the drill-down permits."""
    app.router.add_get("/api/moment/device-compare", handle_device_compare)
    logger.info("Device compare API routes registered (1 endpoint)")
