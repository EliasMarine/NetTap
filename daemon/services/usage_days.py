"""
The usage ledger's pure rules (NET-329, roadmap F4 §4.3–4.4): local days, the rules hash, the
merge of a recount, coverage evidence, the bootstrap and the sweep's walk.

No I/O here: usage_ledger.py reads OpenSearch and saves, this decides. A ledger state is the
file's JSON as a dict and is never changed in place: every function returns a new one.
"""

import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from services.device_accounting import LOCAL_DESTINATIONS
from storage.manager import StorageManager

VERSION = 1
MAX_DAYS = 400  # the ledger keeps the newest 400 local days
CHUNK_DAYS = 7  # one sweep query
SETTLE_AFTER = timedelta(hours=72)
SWEEP_EVERY = timedelta(hours=24)
FIGURES = ("total", "download", "upload", "local")
_ERROR_CHARS = 120


# --- days and times -------------------------------------------------------


def day_key(d: date) -> str:
    return d.isoformat()


def parse_day(key: str) -> date:
    return date.fromisoformat(key)


def utc_iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: object) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """The local day's [start, end) in UTC: 23 or 25 hours on a daylight-saving day."""
    start = datetime.combine(day, time(0), tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def local_today(now: datetime, tz: ZoneInfo) -> date:
    return now.astimezone(tz).date()


def days_between(first: date, last: date) -> list[date]:
    """Every date from `first` to `last`, both included (none when last is before first)."""
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def utc_dates(start: datetime, end: datetime) -> set[date]:
    """The UTC dates overlapping [start, end)."""
    if end <= start:
        return set()
    last = end.astimezone(timezone.utc) - timedelta(microseconds=1)
    return set(days_between(start.astimezone(timezone.utc).date(), last.date()))


# --- rules and indices ------------------------------------------------------


def rules_hash(excluded_ips: list[str], lan_cidrs: list[str]) -> str:
    """What decides a day's figures besides its records: excluded IPs, LAN ranges, local destinations."""
    raw = json.dumps(
        [sorted(set(excluded_ips)), sorted(set(lan_cidrs)), LOCAL_DESTINATIONS]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def index_day(name: str) -> date | None:
    """The UTC date in a daily index's name (Malcolm writes arkime_sessions3-YYMMDD)."""
    parsed = StorageManager._parse_index_date(name)
    return parsed.date() if parsed else None


def index_entry(name: str, bounds: tuple[str | None, str | None] | None) -> dict:
    """{name, min_ts, max_ts}: an index holds one UTC day of @timestamp, so a dated name gives
    its bounds; another name takes the bounds searched for it (None, None when it is empty)."""
    day = index_day(name)
    if day is None:
        low, high = bounds or (None, None)
        return {"name": name, "min_ts": low, "max_ts": high}
    start = datetime.combine(day, time(0), tzinfo=timezone.utc)
    return {
        "name": name,
        "min_ts": utc_iso(start),
        "max_ts": utc_iso(start + timedelta(days=1, seconds=-1)),
    }


def _index_span(entry: dict) -> tuple[datetime, datetime] | None:
    low, high = parse_iso(entry.get("min_ts")), parse_iso(entry.get("max_ts"))
    return (low, high) if low and high and low <= high else None


def covered_utc_dates(indices: dict) -> set[date]:
    """The UTC dates the present indices hold."""
    out: set[date] = set()
    for entry in indices.values():
        span = _index_span(entry)
        if span:
            out |= set(days_between(span[0].date(), span[1].date()))
    return out


def index_local_days(entry: dict, tz: ZoneInfo) -> list[date]:
    """The local days overlapping an index's [min_ts, max_ts]."""
    span = _index_span(entry)
    if span is None:
        return []
    return days_between(span[0].astimezone(tz).date(), span[1].astimezone(tz).date())


# --- bootstrap ----------------------------------------------------------------


# OLD CODE: def bootstrap(indices: dict, tz: ZoneInfo, now: datetime) -> dict: (review: + floor)
def bootstrap(
    indices: dict, tz: ZoneInfo, now: datetime, floor: date | None = None
) -> dict:
    """{since, gaps, today_lost} from the index set (Codex r2 #5, r3 #1, r4 #1).

    A past local day is covered when every UTC date it overlaps has an index; `since` is the
    first covered one (today when none is), and each uncovered past day after it is a gap.
    Today is never a gap: only its elapsed UTC dates are checked, and a missing one marks it lost.
    `floor` is the first UTC date a ledger counted before (a time-zone change): an elapsed date
    before it was never captured, so it isn't loss (a day-one Berlin switch from UTC).
    """
    today = local_today(now, tz)
    covered = covered_utc_dates(indices)
    if not covered:  # an empty store: nothing was captured, so nothing was lost
        return {"since": day_key(today), "gaps": [], "today_lost": False}
    oldest_start = datetime.combine(min(covered), time(0), tzinfo=timezone.utc)
    first = max(local_today(oldest_start, tz), today - timedelta(days=MAX_DAYS - 1))
    past = days_between(first, today - timedelta(days=1))
    whole = {d for d in past if utc_dates(*day_bounds(d, tz)) <= covered}
    since = min(whole, default=today)
    # The current UTC date is never pruned (it is being written): no index yet only means no
    # record yet, so it isn't evidence of loss
    elapsed = {
        d
        for d in utc_dates(day_bounds(today, tz)[0], now)
        if d != now.astimezone(timezone.utc).date() and (floor is None or d >= floor)
    }
    return {
        "since": day_key(since),
        "gaps": [day_key(d) for d in past if d >= since and d not in whole],
        "today_lost": not elapsed <= covered,
    }


def new_state(
    *,
    tz_name: str,
    indices: dict,
    rules: str,
    now: datetime,
    generation: int,
    sweep_id: int,
    floor: date | None = None,
) -> dict:
    """A ledger with no figures yet, its coverage from the index set; its first sweep is due."""
    # OLD CODE: boot = bootstrap(indices, ZoneInfo(tz_name), now) (review: + floor)
    boot = bootstrap(indices, ZoneInfo(tz_name), now, floor)
    today = day_key(local_today(now, ZoneInfo(tz_name)))
    days = {today: {"coverage_lost_at": utc_iso(now)}} if boot["today_lost"] else {}
    return {
        "version": VERSION,
        "generation": generation,
        "tz": tz_name,
        "since": boot["since"],
        "rules": rules,
        "sweep": {
            "id": sweep_id,
            "cursor": None,
            "started_at": None,
            "finished_at": None,  # none yet, so a sweep is due at once
            "chunks_done": 0,
            "chunks_failed": 0,
            "retries": 0,
        },
        "inventory_ok": True,
        "indices": indices,
        "gaps": boot["gaps"],
        "days": days,
    }


# --- which days count -----------------------------------------------------------


def countable(state: dict, d: date, today: date) -> bool:
    """A day the ledger counts: from `since` to today, within the newest 400, not a gap."""
    return (
        parse_day(state["since"]) <= d <= today
        and d > today - timedelta(days=MAX_DAYS)
        and day_key(d) not in state["gaps"]
    )


def trimmed(state: dict, today: date) -> dict:
    """The newest 400 days only; `since` moves up with them so older days read not counted."""
    oldest = today - timedelta(days=MAX_DAYS - 1)
    since = max(parse_day(state["since"]), oldest)
    return {
        **state,
        "since": day_key(since),
        "gaps": [g for g in state["gaps"] if parse_day(g) >= since],
        "days": {k: v for k, v in state["days"].items() if parse_day(k) >= oldest},
    }


# --- coverage evidence ------------------------------------------------------------


def mark_lost(days: dict, keys: list[str], stamp: str) -> dict:
    """`days` with coverage_lost_at on each of `keys`: set at the first evidence, never changed."""
    fresh = {
        k: {**days.get(k, {}), "coverage_lost_at": stamp}
        for k in keys
        if "coverage_lost_at" not in days.get(k, {})
    }
    return {**days, **fresh}


def observe(state: dict, listing: dict, now: datetime) -> dict:
    """The state with `listing` ({uuid: entry}) as its inventory. A UUID that is gone (deleted,
    or recreated under its name with a new UUID) marks every countable day it held as lost."""
    tz = ZoneInfo(state["tz"])
    today = local_today(now, tz)
    gone = [e for uuid, e in state["indices"].items() if uuid not in listing]
    lost = sorted(
        {
            day_key(d)
            for entry in gone
            for d in index_local_days(entry, tz)
            if countable(state, d, today)
        }
    )
    return {
        **state,
        "indices": listing,
        "days": mark_lost(state["days"], lost, utc_iso(now)),
    }


def mark_all_lost(state: dict, now: datetime) -> dict:
    """Inventory unknown (evidence 4): every existing day, settled ones too, may have lost data."""
    days = mark_lost(state["days"], list(state["days"]), utc_iso(now))
    return {**state, "days": days, "indices": {}, "inventory_ok": False}


# --- merge ----------------------------------------------------------------------------


def merge_day(entry: dict, recount: dict, rules: str, stamp: str, cutoff: str) -> dict:
    """One day after a successful recount under `rules` (§4.3 merge).

    Same rules: the total only rises, and the split comes from the same recount as the total;
    a lower recount keeps the figures and is itself evidence of loss. Other rules replace the
    figures only on a day that never lost coverage.
    """
    base = {k: v for k, v in entry.items() if k not in ("failed_at", "error")}
    base = {**base, "counted_at": stamp, "cutoff": cutoff}
    fresh = {**base, **{k: int(recount[k]) for k in FIGURES}, "rules": rules}
    if "total" not in entry:
        return fresh
    if entry.get("rules") == rules:
        if recount["total"] >= entry["total"]:
            return fresh
        return {"coverage_lost_at": stamp, **base}  # an earlier loss keeps its time
    return fresh if "coverage_lost_at" not in entry else base


def settled(
    entry: dict, stamp: str, day_end: datetime, query_start: datetime, stable: bool
) -> dict:
    """The entry, settled when its recount ran 72 h past the day's end with an unchanged index
    listing around it, and the day never lost coverage."""
    if (
        stable
        and "total" in entry
        and "coverage_lost_at" not in entry
        and "settled_at" not in entry
        and query_start >= day_end + SETTLE_AFTER
    ):
        return {**entry, "settled_at": stamp}
    return entry


def failed(state: dict, keys: list[str], exc: BaseException, stamp: str) -> dict:
    """Each day of a failed recount gets failed_at and the error; its figures stay."""
    error = f"{type(exc).__name__}: {str(exc)[:_ERROR_CHARS]}"
    days = state["days"]
    marked = {k: {**days.get(k, {}), "failed_at": stamp, "error": error} for k in keys}
    return {**state, "days": {**days, **marked}}


# --- the sweep ---------------------------------------------------------------------------


def sweep_days(state: dict, today: date) -> list[date]:
    """Every day the sweep recounts, oldest first: since to today, gaps skipped."""
    first = max(parse_day(state["since"]), today - timedelta(days=MAX_DAYS - 1))
    return [d for d in days_between(first, today) if countable(state, d, today)]


def sweep_due(state: dict, rules: str, now: datetime, requested: bool) -> bool:
    """A new sweep starts on request, after a rules change, or a day after the last one ended."""
    sweep = state["sweep"]
    if requested or state.get("rules") != rules:
        return True
    if sweep.get("cursor"):
        return False  # one is under way
    finished = parse_iso(sweep.get("finished_at"))
    return finished is None or now - finished >= SWEEP_EVERY


def start_sweep(state: dict, rules: str, now: datetime, today: date) -> dict:
    days = sweep_days(state, today)
    stamp = utc_iso(now)
    sweep = {
        "id": state["sweep"]["id"] + 1,
        "cursor": day_key(days[0]) if days else None,
        "started_at": stamp,
        "finished_at": None if days else stamp,
        "chunks_done": 0,
        "chunks_failed": 0,
        "retries": 0,
    }
    return {**state, "rules": rules, "sweep": sweep}


def next_chunk(state: dict, today: date) -> tuple[list[date], str | None]:
    """The chunk at the cursor and the cursor after it (None: it is the last)."""
    cursor = parse_day(state["sweep"]["cursor"])
    ahead = [d for d in sweep_days(state, today) if d >= cursor]
    after = day_key(ahead[CHUNK_DAYS]) if len(ahead) > CHUNK_DAYS else None
    return ahead[:CHUNK_DAYS], after


def advance(state: dict, cursor: str | None, ok: bool, now: datetime) -> dict:
    """The sweep past one chunk, done or failed; a null cursor ends it."""
    sweep = state["sweep"]
    moved = {
        **sweep,
        "cursor": cursor,
        "retries": 0,
        "chunks_done": sweep["chunks_done"] + (1 if ok else 0),
        "chunks_failed": sweep.get("chunks_failed", 0) + (0 if ok else 1),
    }
    if cursor is None:
        moved = {**moved, "finished_at": utc_iso(now)}
    return {**state, "sweep": moved}
