"""GET /api/alerts/suricata/{name} — one raw Suricata category over a window (NET-160 slice 2b-2).

The name is a stored rule.category value: Suricata's own classification of the rule, plus the
MITRE ATT&CK tactic Malcolm adds as a second value on some alerts, so category totals overlap.
Every figure comes from one snapshot and counts with the alert list's own query for
suricata_category=name (alert_query), so each equals the list its link opens. A list whose
enumeration stopped at its cap says so: its rows are the busiest among those read, and it
gives no distinct count.
"""

import logging
from datetime import timedelta
from typing import Any, Callable

from aiohttp import web

from api.alerts import (
    alert_query,
    severity_clauses,
    suricata_category_clause,
    valid_suricata_category,
)
from api.drilldown_runner import (
    LAST_SEEN,
    LIST_CAP,
    chart_slots,
    install,
    iso_ms,
    json_error,
    run_drilldown,
    timeline,
)
from api.time_range import parse_time_range
from storage.snapshot_search import (
    NETWORK_INDEX,
    Budget,
    QueryFailed,
    SnapshotSearch,
    doc_count,
    metric,
    total_hits,
)

logger = logging.getLogger("nettap.api.suricata_categories")

_DEFAULT_RANGE = timedelta(hours=24)
_TOP_RULES = 50
_TOP_ADDRESSES = 20
# The page's tiles and the list's severity= value each one links to
_SEVERITIES = {"high": "1", "medium": "2", "low": "3", "info": "info"}


def _query(from_ts: str, to_ts: str, name: str, severity: str = "") -> dict:
    """The list's query for suricata_category=name (and severity=, when given)."""
    narrow, exclude = severity_clauses(severity)
    return alert_query(
        from_ts, to_ts, [suricata_category_clause(name), *narrow], exclude
    )


def _listing(
    rows: list[dict],
    order: Callable,
    top: int | None,
    complete: bool,
    examined: int | None = None,
) -> dict:
    """The busiest `top` rows; a distinct count only when every key was read. `examined` is the
    keys read, when rows leave one out (Also tagged drops the page's own name)."""
    return {
        "rows": sorted(rows, key=order)[:top],
        "distinct": len(rows) if complete else None,
        "examined": len(rows) if examined is None else examined,
        "complete": complete,
    }


def _groups(
    snap: SnapshotSearch,
    query: dict,
    terms: dict,
    what: str,
    metrics: dict | None = None,
) -> tuple[list[dict], bool]:
    buckets, complete = snap.groups(
        query, [{"key": {"terms": terms}}], metrics, what, max_buckets=LIST_CAP
    )
    if not complete:
        logger.info("Suricata category page: the %s stopped at its cap", what)
    return buckets, complete


def _rules(snap: SnapshotSearch, base: dict) -> dict:
    what = "category rules"
    # missing_bucket: an alert with no rule.name is its own row, apart from a rule named ""
    terms = {"field": "rule.name", "missing_bucket": True}
    buckets, complete = _groups(snap, base, terms, what, LAST_SEEN)
    rows = [
        {
            "rule_name": b["key"]["key"],
            "count": doc_count(b, what),
            "last_seen": iso_ms(metric(b, "last", what)),
        }
        for b in buckets
    ]
    return _listing(
        rows,
        lambda r: (-r["count"], r["rule_name"] is None, r["rule_name"] or ""),
        _TOP_RULES,
        complete,
    )


def _addresses(snap: SnapshotSearch, base: dict, field: str, what: str) -> dict:
    """Alerts per address on one side, as the list's src= or dst= counts them."""
    buckets, complete = _groups(snap, base, {"field": field}, what)
    rows = [{"ip": b["key"]["key"], "count": doc_count(b, what)} for b in buckets]
    listing = _listing(rows, lambda r: (-r["count"], r["ip"]), _TOP_ADDRESSES, complete)
    # Counted on its own, so it is exact even when the enumeration stopped
    without = {"bool": {"filter": [base], "must_not": [{"exists": {"field": field}}]}}
    return {**listing, "missing": snap.count(without, f"{what} missing")}


def _also_tagged(snap: SnapshotSearch, base: dict, name: str) -> dict:
    """Every other rule.category on these alerts, with how many of them carry it."""
    what = "category also tagged"
    buckets, complete = _groups(snap, base, {"field": "rule.category"}, what)
    rows = [
        {"category": b["key"]["key"], "count": doc_count(b, what)}
        for b in buckets
        if b["key"]["key"] != name
    ]
    # OLD CODE: return _listing(rows, lambda r: (-r["count"], r["category"]), None, complete) (PR #190 review: examined left out the page's own name, one short)
    return _listing(
        rows, lambda r: (-r["count"], r["category"]), None, complete, len(buckets)
    )


def suricata_category_figures(
    client: Any, name: str, from_ts: str, to_ts: str, slots: dict, budget: Budget
) -> dict:
    """Every figure the Suricata category page shows, over one snapshot."""
    base = _query(from_ts, to_ts, name)
    with SnapshotSearch(client, NETWORK_INDEX, budget) as snap:
        what = "category alerts"
        reply = snap.search(
            {
                "size": 0,
                "track_total_hits": True,
                "query": base,
                "aggs": {"timeline": slots},
            },
            what,
            ("timeline",),
        )
        total = total_hits(reply, what)
        severity = {
            tile: snap.count(_query(from_ts, to_ts, name, code), f"category {tile}")
            for tile, code in _SEVERITIES.items()
        }
        # Only a multi-valued severity could do this; four tiles that don't add up are wrong
        if sum(severity.values()) != total:
            raise QueryFailed("the severity counts don't add up to the total")
        figures = {
            "name": name,
            "from": from_ts,
            "to": to_ts,
            "total": total,
            "severity": severity,
            "timeline": timeline(reply),
            "rules": _rules(snap, base),
            "sources": _addresses(snap, base, "source.ip", "category sources"),
            "targets": _addresses(snap, base, "destination.ip", "category targets"),
            "also_tagged": _also_tagged(snap, base, name),
        }
    return figures


async def handle_suricata_category(request: web.Request) -> web.Response:
    """GET /api/alerts/suricata/{name}?from=&to= — the Suricata category page's figures."""
    name = valid_suricata_category(request.match_info["name"])
    if name is None:
        logger.debug("Suricata category page: invalid name")
        return json_error("That isn't a Suricata category name.", 400)
    from_ts, to_ts = parse_time_range(request, _DEFAULT_RANGE)
    slots = chart_slots(from_ts, to_ts)
    if slots is None:
        return json_error("This time range is too long; choose a shorter one.", 400)
    client = request.app["drill_client"]
    return await run_drilldown(
        request,
        lambda budget: suricata_category_figures(
            client, name, from_ts, to_ts, slots, budget
        ),
        "a Suricata category",
    )


def register_suricata_category_routes(app: web.Application, client: Any) -> None:
    install(app, client)
    # .+ keeps a name with a "/" (aiohttp decodes %2F before routing); no other route sits below
    app.router.add_get("/api/alerts/suricata/{name:.+}", handle_suricata_category)
    logger.info("Suricata category API routes registered (1 endpoint)")
