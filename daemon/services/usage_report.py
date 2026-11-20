"""
What the usage API answers from a ledger snapshot (NET-329, roadmap F4 §4.5): each local day
with its status, the sums, and a month's projection. Pure: the snapshot, the clock, the current
rules hash and the owner's time zone setting are passed in.
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from services.usage_days import (
    FIGURES,
    day_bounds,
    day_key,
    days_between,
    local_today,
    parse_day,
    parse_iso,
    utc_iso,
)

STALE_TODAY = timedelta(minutes=45)
MIN_ELAPSED_S = 3600  # under an hour in, a rate says nothing
_NO_FIGURES = ("future", "not_counted", "pending")
_NO_SWEEP = {
    "id": 0,
    "cursor": None,
    "chunks_done": 0,
    "chunks_failed": 0,
    "finished_at": None,
}


def ledger_tz(snapshot: dict | None, owner: dict) -> str:
    """The zone days are counted in: the ledger's own, or the owner's before the first pass."""
    return snapshot["tz"] if snapshot else owner["tz"]


def pending_tz(snapshot: dict | None, owner: dict) -> str | None:
    """The owner's new zone while the ledger still counts in its old one."""
    if snapshot and owner["ok"] and owner["set"] and owner["tz"] != snapshot["tz"]:
        return owner["tz"]
    return None


def _today_stale(entry: dict, day_start: datetime, now: datetime) -> bool:
    """No successful recount of today in the last 45 min (a day younger than that can't be)."""
    last = parse_iso(entry.get("counted_at")) or day_start
    return now - last > STALE_TODAY


def day_status(
    d: date,
    entry: dict,
    snapshot: dict | None,
    today: date,
    now: datetime,
    rules: str,
) -> str:
    """The first status that applies, in the plan's order (§4.5)."""
    if d > today:
        return "future"
    if snapshot is None:
        return "pending"
    if d < parse_day(snapshot["since"]) or day_key(d) in snapshot["gaps"]:
        return "not_counted"
    start = day_bounds(d, ZoneInfo(snapshot["tz"]))[0]
    if entry.get("failed_at") or (d == today and _today_stale(entry, start, now)):
        return "stale"
    if "total" not in entry:
        return "pending"
    lost = "coverage_lost_at" in entry
    if entry.get("rules") != rules:
        return "old_rules" if lost else "recount_pending"
    if lost and "settled_at" not in entry:
        return "approximate"
    return "counted"


def _row(d: date, tz: ZoneInfo, entry: dict, status: str) -> dict:
    start, end = day_bounds(d, tz)
    shown = status not in _NO_FIGURES and "total" in entry
    return {
        "date": day_key(d),
        "start": utc_iso(start),
        "end": utc_iso(end),
        "cutoff": entry.get("cutoff") if shown else None,
        **{k: entry[k] if shown else None for k in FIGURES},
        "status": status,
        "counted_at": entry.get("counted_at"),
    }


def daily(
    snapshot: dict | None,
    first: date,
    last: date,
    now: datetime,
    rules: str,
    owner: dict,
) -> dict:
    """GET /api/usage/daily for local dates first..last."""
    tz_name = ledger_tz(snapshot, owner)
    tz = ZoneInfo(tz_name)
    today = local_today(now, tz)
    days = (snapshot or {}).get("days", {})

    def row(d: date) -> dict:
        entry = days.get(day_key(d), {})
        return _row(d, tz, entry, day_status(d, entry, snapshot, today, now, rules))

    rows = [row(d) for d in days_between(first, last)]
    gaps = [
        {"date": r["date"], "reason": r["status"]}
        for r in rows
        if r["status"] not in ("future", "counted")
    ]
    return {
        "tz": tz_name,
        "pending_tz": pending_tz(snapshot, owner),
        "since": (snapshot or {}).get("since"),
        "generation": (snapshot or {}).get("generation", 0),
        "updated_at": (snapshot or {}).get("updated_at"),
        "days": rows,
        "bytes": {
            k: sum(r[k] for r in rows if r[k] is not None)
            for k in ("download", "upload", "local", "total")
        },
        "complete": not gaps,
        "gaps": gaps,
    }


def current_month(snapshot: dict | None, now: datetime, owner: dict) -> tuple[int, int]:
    """(year, month) of the owner's local month now."""
    today = local_today(now, ZoneInfo(ledger_tz(snapshot, owner)))
    return today.year, today.month


def _projection(
    rows: list[dict], total: int, start: datetime, end: datetime, today: date
) -> dict:
    """daily_rate, projected and days_remaining from today's cutoff, in real seconds; all null
    for another month, under an hour in, or when an elapsed day isn't counted (Codex r2 #8)."""
    none = {"projected": None, "daily_rate": None, "days_remaining": None}
    now_row = next((r for r in rows if r["date"] == day_key(today)), None)
    if now_row is None or any(r["status"] not in ("future", "counted") for r in rows):
        return none
    cutoff = parse_iso(now_row["cutoff"])
    elapsed = (cutoff - start).total_seconds() if cutoff else 0
    if elapsed < MIN_ELAPSED_S:
        return none
    return {
        "projected": int(total / elapsed * (end - start).total_seconds()),
        "daily_rate": int(total / elapsed * 86400),
        "days_remaining": round((end - cutoff).total_seconds() / 86400, 2),
    }


def _lower_bound(rows: list[dict], snapshot: dict | None, rules: str) -> int:
    """NET-339: the days' totals counted under the current rules only (counted, approximate and
    stale days whose rules match), so the sum is never too high after an exclusions change."""
    days = (snapshot or {}).get("days", {})
    return sum(
        r["total"]
        for r in rows
        if r["total"] is not None
        and r["status"] in ("counted", "approximate", "stale")
        and days.get(r["date"], {}).get("rules") == rules
    )


def month(
    snapshot: dict | None,
    year: int,
    month_no: int,
    now: datetime,
    rules: str,
    owner: dict,
) -> dict:
    """GET /api/usage/month: the local month's days, its bounds, projection and sweep."""
    tz = ZoneInfo(ledger_tz(snapshot, owner))
    first = date(year, month_no, 1)
    after = (first + timedelta(days=31)).replace(day=1)
    start = datetime.combine(first, time(0), tzinfo=tz)
    end = datetime.combine(after, time(0), tzinfo=tz)
    report = daily(snapshot, first, after - timedelta(days=1), now, rules, owner)
    sweep = (snapshot or {}).get("sweep") or _NO_SWEEP
    return {
        **report,
        # NET-339: from the same snapshot and rules as the projection (Codex r2 #5)
        "bytes": {
            **report["bytes"],
            "lower_bound": _lower_bound(report["days"], snapshot, rules),
        },
        "year": year,
        "month": month_no,
        "month_start": start.isoformat(),
        "month_end": end.isoformat(),
        # in UTC: two datetimes sharing one ZoneInfo subtract as wall clocks (720 h, not 721)
        **_projection(
            report["days"],
            report["bytes"]["total"],
            start.astimezone(timezone.utc),
            end.astimezone(timezone.utc),
            local_today(now, tz),
        ),
        "sweep": {k: sweep.get(k, _NO_SWEEP[k]) for k in _NO_SWEEP},
    }
