"""
The weekly report's five sections (NET-340, plans/2026-11-21-weekly-report.md §3.4): internet
use, alerts, new devices, offline incidents and the data cap, each stating its own coverage.

build_sections() never raises: a section that fails is `unavailable` with a note, and one whose
data is incomplete is `partial`. The ledger's snapshot, clock and rules and the owner's zone are
read once. Every OpenSearch request goes through one Budget from the absolute deadline, on the
caller's no-retry client, so nothing runs (or is retried) past it.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from datetime import time as clock_time
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

from opensearchpy import ConnectionTimeout, OpenSearchException

from api.alerts import alert_query
from services import owner_tz, usage_report
from services.rule_explainer import explain_name
from services.usage_days import (
    day_bounds,
    day_key,
    days_between,
    index_day,
    parse_iso,
    utc_iso,
)
from services.usage_ledger import network_inventory
from storage.all_buckets import all_buckets
from storage.exact_terms import SearchTimedOut
from storage.snapshot_search import (
    Budget,
    QueryFailed,
    TooSlow,
    checked,
    doc_count,
    total_hits,
)

logger = logging.getLogger("nettap.services.report_sections")

SECTIONS = ("traffic", "alerts", "new_devices", "offline", "data_cap")
ALERTS_WHAT = "weekly report alert totals"
RANK_WHAT = "weekly report rule ranking"
RANK_PAGE = 1_000
RANK_MAX = 5_000
WORST_SHOWN = 5
LISTED_MAX = 50
ENRICH_MIN_S = 5  # with less left, the new devices list shows MACs and vendors only
ENRICH_MAX_S = 10
STILL_OFFLINE_CHECK = timedelta(minutes=10)
UNNAMED = "Unnamed rule"
# what DeviceRegistry.get_name reads; the owner's own name comes from the custom store by MAC
NAME_FIELDS = [
    "mac",
    "manufacturer",
    "friendly_name",
    "hostnames",
    "enrichment_sources.unifi.unifi_alias",
    "enrichment_sources.dhcp.hostname",
    "enrichment_sources.mdns.hostname",
]
_TIMEOUTS = (TooSlow, TimeoutError, ConnectionTimeout, SearchTimedOut)
_JOURNAL_CUT = "Not every event journal entry could be read, so some may be missing."


@dataclass(frozen=True)
class Period:
    first: date  # local dates, inclusive
    last: date
    start: datetime  # aware UTC, = day_bounds(first)[0]
    end: datetime  # aware UTC, = day_bounds(last)[1] (exclusive)
    tz: str  # the ledger zone

    @classmethod
    def of(cls, first: date, last: date, tz: str) -> "Period":
        zone = ZoneInfo(tz)
        return cls(
            first, last, day_bounds(first, zone)[0], day_bounds(last, zone)[1], tz
        )


@dataclass(frozen=True)
class ReportDeps:
    ledger: Any  # UsageLedger
    journal: Any  # EventJournal
    registry: Any  # DeviceRegistry
    watched: Any  # WatchedDevices
    tracker: Any  # bandwidth tracker (get_cap)
    client: Any  # the no-retry OpenSearch client
    network_index: str


class _Pinned(NamedTuple):
    snapshot: dict | None
    now: datetime
    rules: str
    owner: dict


def build_sections(period: Period, deps: ReportDeps, deadline: float) -> dict:
    """The five sections, keyed by name. Never raises: a failing section is `unavailable`.
    `deadline` is an absolute time.monotonic() value; nothing runs past it."""
    budget = Budget(deadline - time.monotonic())
    pinned = _attempt(lambda: _pin(deps.ledger))
    scan = _attempt(lambda: deps.journal.scan(period.start, period.end, deadline))
    # the I/O-free sections first; the optional rule ranking last, as alerts' last step
    built = {
        "traffic": _section("traffic", lambda: traffic(period, _need(pinned))),
        "data_cap": _section(
            "data_cap", lambda: data_cap(period, _need(pinned), deps.tracker, scan)
        ),
        "offline": _section(
            "offline",
            lambda: offline(period, _need(scan), deps.watched, _need(pinned).now),
        ),
        "new_devices": _section(
            "new_devices",
            lambda: new_devices(
                period, _need(scan), deps.registry, deps.client, budget
            ),
        ),
        "alerts": _section(
            "alerts",
            lambda: alerts(period, deps.client, deps.network_index, budget),
        ),
    }
    if not isinstance(scan, Exception):
        logger.info(
            "Weekly report %s to %s: %s; journal from %s%s",
            period.first,
            period.last,
            ", ".join(f"{k} {built[k]['status']}" for k in SECTIONS),
            scan["examined_from"],
            " (truncated)" if scan["truncated"] else "",
        )
    return {k: built[k] for k in SECTIONS}


# --- plumbing -------------------------------------------------------------------


def _pin(ledger: Any) -> _Pinned:
    return _Pinned(
        ledger.snapshot(), ledger.now(), ledger.current_rules(), owner_tz.read()
    )


def _attempt(fn: Callable[[], Any]) -> Any:
    """fn()'s value, or the exception it raised (a section that needs it raises it again)."""
    try:
        return fn()
    except Exception as exc:  # each section that needs this turns it into its own note
        return exc


def _need(value: Any) -> Any:
    if isinstance(value, Exception):
        raise value
    return value


def _why(exc: BaseException) -> str:
    if isinstance(
        exc, _TIMEOUTS
    ):  # before OSError and OpenSearchException: both hold some
        return "It ran out of time."
    if isinstance(exc, (QueryFailed, OpenSearchException)):
        return "OpenSearch didn't give a complete answer."
    if isinstance(exc, OSError):
        return "A file it needs couldn't be read."
    return "Something went wrong; the daemon log has the details."


def _section(name: str, build: Callable[[], dict]) -> dict:
    try:
        return build()
    except Exception as exc:  # a failing section never fails the report
        known = isinstance(exc, (QueryFailed, OpenSearchException, OSError))
        log = logger.warning if known else logger.exception
        log("Weekly report: the %s section is unavailable: %r", name, exc)
        return {
            "status": "unavailable",
            "coverage": "Not available this time",
            "note": _why(exc),
        }


def _head(notes: list[str], coverage: str) -> dict:
    return {
        "status": "partial" if notes else "ok",
        "coverage": coverage,
        "note": " ".join(notes) or None,
    }


def _ms(t: datetime) -> str:
    """UTC with milliseconds, the precision of @timestamp."""
    return (
        f"{t.astimezone(timezone.utc):%Y-%m-%dT%H:%M:%S}.{t.microsecond // 1000:03d}Z"
    )


def _local(t: datetime, tz: str) -> str:
    t = t.astimezone(ZoneInfo(tz))
    return f"{t.day} {t:%b %H:%M}"


def _inside(period: Period, t: datetime | None) -> bool:
    return t is not None and period.start <= t < period.end


def _text(raw: Any) -> str | None:
    return raw if isinstance(raw, str) and raw else None


def _journal_notes(period: Period, scan: dict) -> list[str]:
    notes = [_JOURNAL_CUT] if scan["truncated"] else []
    since = scan["examined_from"]
    if since is None:
        notes.append("The event journal holds no entries yet.")
    elif since > period.start:
        notes.append(f"The event journal only goes back to {_local(since, period.tz)}.")
    return notes


# --- 1. internet use -----------------------------------------------------------


def _covered(row: dict) -> bool:
    """Counted under the current rules, up to the day's end."""
    cutoff, end = parse_iso(row["cutoff"]), parse_iso(row["end"])
    return row["status"] == "counted" and cutoff is not None and cutoff >= end


def traffic(period: Period, p: _Pinned) -> dict:
    report = usage_report.daily(
        p.snapshot, period.first, period.last, p.now, p.rules, p.owner
    )
    rows = report["days"]
    days = [
        {
            "date": r["date"],
            "download": r["download"],
            "upload": r["upload"],
            "total": r["total"],
            "covered": _covered(r),
        }
        for r in rows
    ]
    covered = sum(d["covered"] for d in days)
    busiest = max(
        (d for d in days if d["total"] is not None),
        key=lambda d: d["total"],
        default=None,
    )
    provisional = covered < len(days)
    notes = (
        ["Not every day is fully counted, so the total is provisional."]
        if provisional
        else []
    )
    return {
        **_head(notes, f"{covered} of {len(days)} {_days(len(days))} counted"),
        **report["bytes"],  # download, upload, local and total: /api/usage/daily's sums
        "counted_total": usage_report.lower_bound(rows, p.snapshot, p.rules),
        "provisional": provisional,
        "days_covered": covered,
        "days_total": len(days),
        "busiest": {"date": busiest["date"], "total": busiest["total"]}
        if busiest
        else None,
        "days": days,
    }


def _days(n: int) -> str:
    return "day" if n == 1 else "days"


# --- 2. alerts --------------------------------------------------------------------


def alerts(period: Period, client: Any, index: str, budget: Budget) -> dict:
    """Exact totals and days from one search; storage coverage; the optional worst five."""
    zone = ZoneInfo(period.tz)
    bounds = {
        day_key(d): day_bounds(d, zone) for d in days_between(period.first, period.last)
    }
    # the Alerts page's counted query, [start, end): its range is inclusive
    query = alert_query(_ms(period.start), _ms(period.end - timedelta(milliseconds=1)))
    body = {
        "size": 0,
        "track_total_hits": True,
        "query": query,
        "aggs": {
            # /api/alerts/count's own: alerts without a severity still count in the total
            "by_severity": {"terms": {"field": "suricata.alert.severity", "size": 10}},
            # date_range, not date_histogram (storage/time_slots.py: exact on OpenSearch 3.5)
            "per_day": {
                "date_range": {
                    "field": "@timestamp",
                    "format": "strict_date_optional_time",
                    "ranges": [
                        {"key": k, "from": _ms(s), "to": _ms(e)}
                        for k, (s, e) in bounds.items()
                    ],
                }
            },
        },
    }
    reply = checked(
        client.search(index=index, body=body, budget=budget),
        ALERTS_WHAT,
        ("by_severity", "per_day"),
    )
    total = total_hits(reply, ALERTS_WHAT)
    aggs = reply["aggregations"]
    counts = {b["key"]: doc_count(b, ALERTS_WHAT) for b in aggs["per_day"]["buckets"]}
    if counts.keys() != bounds.keys():
        raise QueryFailed(f"{ALERTS_WHAT}: the days don't match")
    stored, stored_note = _storage(client, index, budget, bounds)
    worst, worst_note = _worst(client, index, query, budget)
    notes = [stored_note] if stored_note else []
    if any(s in ("partial", "absent") for s in stored.values()):
        notes.append("Some days are only partly stored, or not stored at all.")
    if worst is None:
        notes.append("The worst rules aren't included this time.")
    full = sum(s == "full" for s in stored.values())
    coverage = (
        "Storage coverage unknown"
        if stored_note
        else f"{full} of {len(bounds)} {_days(len(bounds))} fully stored"
    )
    return {
        **_head(notes, coverage),
        "total": total,
        "by_severity": _severities(aggs["by_severity"], total),
        "days": [{"date": k, "count": counts[k], "stored": stored[k]} for k in bounds],
        "worst": worst,
        "worst_note": worst_note,
    }


def _severities(agg: dict, total: int) -> dict:
    named = {"1": 0, "2": 0, "3": 0}
    for b in agg.get("buckets") or []:
        try:
            key = str(int(b.get("key")))
        except (TypeError, ValueError):
            continue  # counted in "other"
        if key in named:
            named = {**named, key: doc_count(b, ALERTS_WHAT)}
    return {**named, "other": max(0, total - sum(named.values()))}


def _spans(inventory: dict) -> list[tuple[datetime, datetime]]:
    """[start, end) each network index holds: a dated one its whole UTC day (not the ledger's
    23:59:59 upper bound), an undated one its observed min to max."""
    out = []
    for entry in inventory.values():
        day = index_day(entry["name"])
        if day is not None:
            start = datetime.combine(day, clock_time(0), tzinfo=timezone.utc)
            out.append((start, start + timedelta(days=1)))
            continue
        low, high = parse_iso(entry.get("min_ts")), parse_iso(entry.get("max_ts"))
        if low and high and low <= high:
            out.append((low, high))
    return out


def _stored(start: datetime, end: datetime, spans: list) -> str:
    covered, reach = timedelta(0), start
    for low, high in sorted(spans):
        low, high = max(low, reach), min(high, end)
        if high > low:
            covered, reach = covered + (high - low), high
    if covered >= end - start:
        return "full"
    return "partial" if covered else "absent"


def _storage(
    client: Any, index: str, budget: Budget, bounds: dict
) -> tuple[dict, str | None]:
    try:
        spans = _spans(network_inventory(client, budget, index))
    except Exception as exc:  # coverage then reads unknown; the counts stand
        logger.warning("Weekly report: the index inventory failed: %r", exc)
        return dict.fromkeys(bounds, "unknown"), (
            "Which days are stored couldn't be checked this time."
        )
    return {k: _stored(s, e, spans) for k, (s, e) in bounds.items()}, None


def _worst(
    client: Any, index: str, query: dict, budget: Budget
) -> tuple[list | None, str | None]:
    """The five rules with the highest observed severity (Suricata 1 is the highest), then the
    most alerts, from exact composite paging; (None, why) unless it completed in the budget."""
    try:
        buckets, complete = all_buckets(
            client,
            index,
            query,
            [{"key": {"terms": {"field": "rule.name", "missing_bucket": True}}}],
            {"worst": {"min": {"field": "suricata.alert.severity"}}},
            page_size=RANK_PAGE,
            max_buckets=RANK_MAX,
            budget=budget,
            what=RANK_WHAT,
        )
        if not complete:
            return None, f"Not included this time: more than {RANK_MAX:,} rules fired."
        rows = [_rule_row(b) for b in buckets]
    except Exception as exc:  # optional: the exact totals and days don't depend on it
        logger.warning("Weekly report: the rule ranking failed: %r", exc)
        return None, f"Not included this time. {_why(exc)}"
    rows.sort(
        key=lambda r: (
            r["severity"] if r["severity"] is not None else float("inf"),
            -r["count"],
            r["rule"],
        )
    )
    return [
        {**r, **explain_name(r["rule"], r["severity"] or 3)} for r in rows[:WORST_SHOWN]
    ], None


def _rule_row(bucket: dict) -> dict:
    name = bucket["key"]["key"]
    worst = bucket["worst"]["value"]
    if not (name is None or isinstance(name, str)) or not (
        worst is None or isinstance(worst, (int, float))
    ):
        raise QueryFailed(f"{RANK_WHAT}: malformed bucket")
    return {
        "rule": name or UNNAMED,
        "severity": None if worst is None else int(worst),
        "count": doc_count(bucket, RANK_WHAT),
    }


# --- 3. new devices ----------------------------------------------------------------


def new_devices(
    period: Period, scan: dict, registry: Any, client: Any, budget: Budget
) -> dict:
    """First sightings from the journal (one entry per MAC); names for the listed few."""
    found = sorted(
        (
            e
            for e in scan["entries"]
            if e.get("type") == "new_device"
            and isinstance(e.get("key"), str)
            and _inside(period, parse_iso(e.get("observed_at")))
        ),
        key=lambda e: parse_iso(e["observed_at"]),
    )
    listed = found[:LISTED_MAX]
    names, name_note = _names(registry, client, [e["key"] for e in listed], budget)
    since = scan["examined_from"]
    since = max(since, period.start) if since else period.start
    coverage = (
        f"First sightings recorded between {_local(since, period.tz)} and "
        f"{_local(period.end, period.tz)}. Devices seen only while NetTap was offline "
        "aren't listed"
    )
    notes = [*_journal_notes(period, scan), *([name_note] if name_note else [])]
    return {
        **_head(notes, coverage),
        "count": len(found),
        "listed": [_device_row(e, names) for e in listed],
        "examined_from": utc_iso(scan["examined_from"])
        if scan["examined_from"]
        else None,
        "truncated": scan["truncated"],
    }


def _device_row(entry: dict, names: dict) -> dict:
    data = entry.get("data") if isinstance(entry.get("data"), dict) else {}
    return {
        "mac": entry["key"],
        "name": names.get(entry["key"].upper()),
        "vendor": _text(data.get("vendor")),
        "ip": _text(data.get("ip")),
        "first_seen": utc_iso(parse_iso(entry["observed_at"])),
    }


def _names(
    registry: Any, client: Any, macs: list[str], budget: Budget
) -> tuple[dict, str | None]:
    """{MAC: name or None}; ({}, why) when the lookup fails or the deadline is near."""
    if not macs:
        return {}, None
    if budget.remaining() < ENRICH_MIN_S:
        return {}, "Device names weren't looked up: the report ran short of time."
    try:
        devices = registry.get_devices(
            macs,
            fields=NAME_FIELDS,
            timeout=min(ENRICH_MAX_S, budget.remaining()),
            client=client,
        )
        return {
            mac: registry.get_name({"mac": mac, **dev}) for mac, dev in devices.items()
        }, None
    except (
        Exception
    ) as exc:  # the list keeps its MACs and vendors, and the count stands
        logger.warning("Weekly report: device names failed: %r", exc)
        return {}, "Device names couldn't be looked up this time."


# --- 4. offline incidents (watched devices) -------------------------------------


def offline(period: Period, scan: dict, watched: Any, now: datetime) -> dict:
    """Outages keyed (MAC, seen_at), paired before any window filter, clipped to the period."""
    pairs = _outages(scan["entries"])
    seen_by_mac: dict[str, list[datetime]] = {}
    for mac, seen in pairs:
        seen_by_mac.setdefault(mac, []).append(seen)
    view, view_note = _view(watched)
    rows = {str(r.get("mac", "")).upper(): r for r in (view or {}).get("devices", [])}
    success = parse_iso(((view or {}).get("check") or {}).get("success_at"))
    fresh = success is not None and now - success <= STILL_OFFLINE_CHECK
    incidents = []
    for (mac, seen), pair in pairs.items():
        row = rows.get(mac) or {}
        still = (
            fresh
            and row.get("state") == "down"
            and parse_iso(row.get("seen_at")) == seen
        )
        later = min((s for s in seen_by_mac[mac] if s > seen), default=None)
        found = _incident(period, mac, seen, pair, later, still)
        if found:
            incidents.append(found)
    notes = [*_journal_notes(period, scan), *([view_note] if view_note else [])]
    return {
        **_head(notes, "Watched devices only"),
        "incidents": sorted(incidents, key=lambda i: (i["from"], i["mac"])),
        "watched_now": len(view["devices"]) if view else None,
    }


def _outages(entries: list[dict]) -> dict[tuple[str, datetime], dict]:
    pairs: dict[tuple[str, datetime], dict] = {}
    for e in entries:
        kind = {"device_offline": "down", "device_online": "up"}.get(e.get("type"))
        data = e.get("data")
        if kind is None or not isinstance(data, dict):
            continue
        mac, seen = data.get("mac") or e.get("key"), parse_iso(data.get("seen_at"))
        if isinstance(mac, str) and seen is not None:
            pairs.setdefault((mac.upper(), seen), {})[kind] = e
    return pairs


def _view(watched: Any) -> tuple[dict | None, str | None]:
    try:
        return watched.view(), None
    except Exception as exc:  # without it no outage reads "still offline"
        logger.warning("Weekly report: the watched devices list failed: %r", exc)
        return None, "The watched devices list couldn't be read this time."


def _entry_name(entry: dict | None) -> str | None:
    data = (entry or {}).get("data")
    return _text(data.get("name")) if isinstance(data, dict) else None


def _incident(
    period: Period,
    mac: str,
    seen: datetime,
    pair: dict,
    later: datetime | None,
    still: bool,
) -> dict | None:
    up, down = pair.get("up"), pair.get("down")
    name = _entry_name(up) or _entry_name(down)
    if (
        up is not None
    ):  # an online entry is a whole interval, with or without its offline
        back = parse_iso(up["data"].get("back_at"))
        if back is None or back < seen:
            return None
        return _clipped(period, mac, name, seen, back, "returned", None)
    if later is not None:  # seen again later (an unwatch while down, a new outage)
        if later < period.start:
            return None
        when = _local(later, period.tz)
        return _clipped(
            period,
            mac,
            name,
            seen,
            None,
            "returned_unrecorded",
            f"Returned before {when}, time not recorded",
        )
    if still:
        return _clipped(
            period, mac, name, seen, period.end, "still_offline", "Still offline"
        )
    # no evidence it reached the period unless it was last seen or declared in it
    if _inside(period, seen) or _inside(period, parse_iso(down.get("observed_at"))):
        return _clipped(
            period,
            mac,
            name,
            seen,
            None,
            "return_unrecorded",
            "Return time not recorded",
        )
    return None


def _clipped(
    period: Period,
    mac: str,
    name: str | None,
    seen: datetime,
    back: datetime | None,
    state: str,
    detail: str | None,
) -> dict | None:
    """[seen, back) clipped to the period; None when they don't overlap."""
    if seen >= period.end or (back is not None and back <= period.start):
        return None
    start = max(seen, period.start)
    end = min(back, period.end) if back is not None else None
    return {
        "mac": mac,
        "name": name,
        "from": utc_iso(start),
        "to": utc_iso(end) if end else None,
        "minutes": int((end - start).total_seconds() // 60) if end else None,
        "state": state,
        "detail": detail,
    }


# --- 5. data cap ---------------------------------------------------------------------


def data_cap(period: Period, p: _Pinned, tracker: Any, scan: Any) -> dict:
    """The month to date as of the period's last day against the current cap (never counted
    past it, no projection); the percentage from the current-rules lower bound."""
    report = usage_report.daily(
        p.snapshot, period.last.replace(day=1), period.last, p.now, p.rules, p.owner
    )
    rows = report["days"]
    counted = sum(usage_report.counted_now(r, p.snapshot, p.rules) for r in rows)
    used = usage_report.lower_bound(rows, p.snapshot, p.rules)
    cap = tracker.get_cap()["monthly_cap_bytes"] or None
    scanned = not isinstance(scan, Exception)
    crossings = [c for e in scan["entries"] if (c := _crossing(e))] if scanned else None
    notes = []
    if counted < len(rows):
        notes.append(
            "Not every day this month is counted under the current rules, so usage is at "
            "least this much."
        )
    if not scanned:
        notes.append("Data cap warnings couldn't be read this time.")
    elif scan["truncated"]:
        notes.append(_JOURNAL_CUT)
    return {
        **_head(
            notes,
            f"{counted} of {len(rows)} {_days(len(rows))} this month counted under the "
            "current rules",
        ),
        "cap_bytes": cap,
        "month": f"{period.last:%Y-%m}",
        "used_counted": used,
        "used_provisional": report["bytes"]["total"],
        "percent": used * 1000 // cap / 10
        if cap
        else None,  # floored: never overstated
        "days_counted": counted,
        "days_so_far": len(rows),
        "crossings": crossings,
    }


def _crossing(entry: dict) -> dict | None:
    data, at = entry.get("data"), parse_iso(entry.get("observed_at"))
    if entry.get("type") != "data_cap" or not isinstance(data, dict) or at is None:
        return None
    threshold = data.get("threshold", entry.get("key"))
    return {
        "month": _text(data.get("month")),
        "threshold": int(threshold) if threshold in ("80", "100") else threshold,
        "cap": data.get("cap") if isinstance(data.get("cap"), int) else None,
        "at": utc_iso(at),
    }
