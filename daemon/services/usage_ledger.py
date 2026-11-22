"""
The durable usage ledger (NET-329, roadmap F4 §4.3–4.4): each local day's Internet total, kept
after its raw records are pruned, counted in the owner's time zone.

One background job ("usage-ledger", every 15 min) is the only writer. Each step builds a new
state from the published one, saves it, and only then publishes it, so the API never shows a
figure that isn't on disk. The rules themselves are pure and live in usage_days.py.
"""

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from opensearchpy import ConnectionTimeout, OpenSearchException

from services import owner_tz
from services.capture_config import write_file_atomic
from services.device_accounting import NETWORK_INDEX, lan_cidrs
from services.usage_days import (
    VERSION,
    advance,
    countable,
    day_bounds,
    day_key,
    failed,
    index_day,
    index_entry,
    local_today,
    mark_all_lost,
    merge_day,
    new_state,
    next_chunk,
    observe,
    parse_day,
    parse_iso,
    rules_hash,
    settled,
    start_sweep,
    sweep_due,
    trimmed,
    utc_iso,
)
from storage.exact_terms import SearchTimedOut
from storage.snapshot_search import Budget, QueryFailed, TooSlow, checked

logger = logging.getLogger("nettap.services.usage_ledger")

DEFAULT_FILE = "/opt/nettap/data/usage-ledger.json"
RECENT_DAYS = 3
MAX_CONTINUATIONS = 3  # the third timeout in a row of one chunk counts it as failed
BUDGET_MARGIN_S = 5
LISTING_TIMEOUT_S = 10
# a chunk started with less would time out and spend one of its three tries for nothing
MIN_CHUNK_BUDGET_S = 30

# Every failure a recount can raise; the timeouts among them continue a sweep chunk later
# OLD CODE START — review: SerializationError (a bad reply body) is an OpenSearchException but not
# a TransportError, so it escaped the chunk and the cursor never moved
# LEDGER_QUERY_ERRORS = (
#     QueryFailed,
#     PartialResultsError,
#     TransportError,
#     TransportConnectionError,
# )
# OLD CODE END
# OpenSearchException covers PartialResultsError, TransportError, ConnectionError and
# SerializationError; malformed buckets are raised as QueryFailed where they are read
LEDGER_QUERY_ERRORS = (QueryFailed, OpenSearchException)
TIMEOUTS = (TooSlow, ConnectionTimeout, SearchTimedOut)


class UsageLedgerIncomplete(Exception):
    """A pass saved what succeeded, but a day group or a save failed (F1 shows it as last_error)."""


class _SaveFailed(Exception):
    pass


@dataclass(frozen=True)
class _Pass:
    budget: Budget
    rules: str
    excluded: list[str]
    lan: dict | None


def _short(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:120]}"


def _listing(rows: Any) -> dict[str, str]:
    """{uuid: name} from a _cat/indices reply; QueryFailed if it is malformed."""
    if not isinstance(rows, list):
        raise QueryFailed("the index listing: malformed reply")
    out: dict[str, str] = {}
    for row in rows:
        name = row.get("index") if isinstance(row, dict) else None
        uuid = row.get("uuid") if isinstance(row, dict) else None
        if not isinstance(name, str) or not isinstance(uuid, str) or not uuid:
            raise QueryFailed("the index listing: an index without a name or UUID")
        out = {**out, uuid: name}
    return out


def _ms_iso(value: Any) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    return utc_iso(datetime.fromtimestamp(value / 1000, tz=timezone.utc))


def network_inventory(
    client: Any, budget: Budget, index: str = NETWORK_INDEX
) -> dict[str, dict]:
    """{uuid: {name, min_ts, max_ts}} of the network indices, inside the budget (moved out of
    UsageLedger._inventory for the weekly report's storage coverage, NET-340; unchanged)."""
    budget.check("the index listing")
    rows = client.cat.indices(
        index=index,
        format="json",
        h="index,uuid",
        request_timeout=min(LISTING_TIMEOUT_S, budget.remaining()),
    )
    names = _listing(rows)
    undated = sorted({n for n in names.values() if index_day(n) is None})
    bounds = _index_bounds(client, undated, budget) if undated else {}
    return {u: index_entry(n, bounds.get(n)) for u, n in names.items()}


def _index_bounds(client: Any, names: list[str], budget: Budget) -> dict[str, tuple]:
    """{name: (min_ts, max_ts)} for indices whose name has no date (was UsageLedger._bounds)."""
    body = {
        "size": 0,
        "aggs": {
            "idx": {
                "terms": {"field": "_index", "size": len(names)},
                "aggs": {
                    "lo": {"min": {"field": "@timestamp"}},
                    "hi": {"max": {"field": "@timestamp"}},
                },
            }
        },
    }
    reply = client.search(index=",".join(names), body=body, budget=budget)
    buckets = checked(reply, "the index bounds", ("idx",))["aggregations"]["idx"]
    try:
        return {
            b["key"]: (_ms_iso(b["lo"].get("value")), _ms_iso(b["hi"].get("value")))
            for b in buckets.get("buckets") or []
        }
    # review: a bad bucket (OverflowError: a time past year 9999)
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError) as exc:
        raise QueryFailed(f"the index bounds: malformed reply ({exc!r})") from exc


def _usable(data: Any) -> bool:
    """A ledger file this version can read; its inventory is checked separately."""
    try:
        return (
            isinstance(data, dict)
            and data.get("version") == VERSION
            and isinstance(data.get("generation"), int)
            and owner_tz.known(data.get("tz"))
            and isinstance(parse_day(data["since"]), date)
            and all(isinstance(parse_day(g), date) for g in data["gaps"])
            and all(
                isinstance(parse_day(k), date) and isinstance(v, dict)
                for k, v in data["days"].items()
            )
            and isinstance(data["sweep"].get("id"), int)
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def _with_inventory_checked(data: dict) -> dict:
    """Evidence 4: missing or unreadable indices make the inventory unknown."""
    indices = data.get("indices")
    ok = (
        data.get("inventory_ok") is True
        and isinstance(indices, dict)
        and all(isinstance(e, dict) and "name" in e for e in indices.values())
    )
    return data if ok else {**data, "indices": {}, "inventory_ok": False}


class UsageLedger:
    """The ledger file, its published snapshot, and the job that keeps it."""

    def __init__(
        self,
        client: Any,
        tracker: Any,
        excluded_ips: Callable[[], list[str]],
        lan_filter: Callable[[], dict | None],
        path: str | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._tracker = tracker
        self._excluded_ips = excluded_ips
        self._lan_filter = lan_filter
        self._path = Path(path or os.environ.get("USAGE_LEDGER_FILE", DEFAULT_FILE))
        self._now = now
        self._monotonic = monotonic
        self._lock = threading.Lock()  # held for the swap only, never during a query
        self._sweep_requested = False
        self._published: dict | None = self._load()

    # --- reading ------------------------------------------------------------

    def snapshot(self) -> dict | None:
        """The published state (never changed after publishing); None before the first pass."""
        with self._lock:
            return self._published

    def now(self) -> datetime:
        return self._now()

    def current_rules(self) -> str:
        return rules_hash(
            list(self._excluded_ips() or []), lan_cidrs(self._lan_filter())
        )

    def request_sweep(self) -> int:
        """Ask the next pass for a new sweep (no total is reset); the current sweep id."""
        with self._lock:
            self._sweep_requested = True
            snap = self._published
        return snap["sweep"]["id"] if snap else 0

    # --- file ---------------------------------------------------------------

    def _load(self) -> dict | None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            return self._set_aside(f"unreadable ({exc})")
        if not _usable(data):
            return self._set_aside("not a ledger this version reads")
        return _with_inventory_checked(data)

    def _kept_as(self, kind: str, when: datetime) -> Path:
        """usage-ledger.<kind>.<UTC time>.json beside the ledger: each kept copy its own file."""
        return self._path.with_suffix(f".{kind}.{when:%Y%m%dT%H%M%SZ}.json")

    def _set_aside(self, why: str) -> None:
        """A broken file is kept beside a new ledger, never overwritten."""
        # OLD CODE: aside = self._path.with_suffix(".corrupt.json") (review: a 2nd one replaced the 1st)
        aside = self._kept_as("corrupt", self._now().astimezone(timezone.utc))
        logger.error("The usage ledger %s is %s; kept as %s", self._path, why, aside)
        try:
            os.replace(self._path, aside)
        except OSError as exc:
            logger.error("Couldn't move the usage ledger aside: %s", exc)
        return None

    def _save(self, path: Path, state: dict) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_file_atomic(
                str(path), json.dumps(state, separators=(",", ":")), mode=0o644
            )
        except OSError as exc:
            raise _SaveFailed(str(exc)) from exc

    def _commit(self, state: dict, counted: bool = False) -> dict:
        """Save, then publish: a failed save leaves the published state and cursor as they were.
        `counted`: it holds a successful recount, the only thing updated_at dates."""
        # OLD CODE: state = {**state, "updated_at": utc_iso(self._now())} (review: failure-only
        # saves moved it too, so "Not updated since" never showed during an outage)
        if counted:
            state = {**state, "updated_at": utc_iso(self._now())}
        self._save(self._path, state)
        with self._lock:
            self._published = state
        return state

    # --- OpenSearch -------------------------------------------------------------

    # OLD CODE START — NET-340: moved to the module (network_inventory, _index_bounds) so the
    # weekly report reads the same inventory
    # def _inventory(self, budget: Budget) -> dict[str, dict]:
    #     """{uuid: {name, min_ts, max_ts}} of the network indices, inside the budget."""
    #     budget.check("the index listing")
    #     rows = self._client.cat.indices(
    #         index=NETWORK_INDEX,
    #         format="json",
    #         h="index,uuid",
    #         request_timeout=min(LISTING_TIMEOUT_S, budget.remaining()),
    #     )
    #     names = _listing(rows)
    #     undated = sorted({n for n in names.values() if index_day(n) is None})
    #     bounds = self._bounds(undated, budget) if undated else {}
    #     return {u: index_entry(n, bounds.get(n)) for u, n in names.items()}
    #
    # def _bounds(self, names: list[str], budget: Budget) -> dict[str, tuple]:
    #     """{name: (min_ts, max_ts)} for indices whose name has no date."""
    #     body = {
    #         "size": 0,
    #         "aggs": {
    #             "idx": {
    #                 "terms": {"field": "_index", "size": len(names)},
    #                 "aggs": {
    #                     "lo": {"min": {"field": "@timestamp"}},
    #                     "hi": {"max": {"field": "@timestamp"}},
    #                 },
    #             }
    #         },
    #     }
    #     reply = self._client.search(index=",".join(names), body=body, budget=budget)
    #     buckets = checked(reply, "the index bounds", ("idx",))["aggregations"]["idx"]
    #     try:
    #         return {
    #             b["key"]: (_ms_iso(b["lo"].get("value")), _ms_iso(b["hi"].get("value")))
    #             for b in buckets.get("buckets") or []
    #         }
    #     # review: a bad bucket (OverflowError: a time past year 9999)
    #     except (KeyError, TypeError, AttributeError, ValueError, OverflowError) as exc:
    #         raise QueryFailed(f"the index bounds: malformed reply ({exc!r})") from exc
    # OLD CODE END
    def _inventory(self, budget: Budget) -> dict[str, dict]:
        """{uuid: {name, min_ts, max_ts}} of the network indices, inside the budget."""
        return network_inventory(self._client, budget)

    def _recount(self, p: _Pass, state: dict, days: list[date]) -> dict:
        """The state after one recount of `days`, the index listing read around its query."""
        tz = ZoneInfo(state["tz"])
        before = self._inventory(p.budget)
        state = observe(state, before, self._now())
        query_start = self._now()
        bounds = {d: day_bounds(d, tz) for d in days}
        ranges = [
            (day_key(d), utc_iso(start), utc_iso(min(end, query_start)))
            for d, (start, end) in bounds.items()
        ]
        counts = self._tracker.usage_for_ranges(
            self._client, ranges, p.excluded, p.lan, p.budget
        )
        after = self._inventory(p.budget)
        # an added index only defers settling; a missing one is loss, which observe() records
        stable = after.keys() == before.keys()
        state = observe(state, after, self._now())
        stamp = utc_iso(self._now())
        merged = {
            key: settled(
                merge_day(state["days"].get(key, {}), counts[key], p.rules, stamp, cut),
                stamp,
                bounds[parse_day(key)][1],
                query_start,
                stable,
            )
            for key, _start, cut in ranges
        }
        return {**state, "days": {**state["days"], **merged}}

    # --- the job --------------------------------------------------------------------

    def run(self, deadline: float) -> dict | None:
        """One pass (F1 job): time zone, inventory, the recent days, then the sweep."""
        excluded = list(self._excluded_ips() or [])
        lan = self._lan_filter()
        p = _Pass(
            Budget(deadline - self._monotonic() - BUDGET_MARGIN_S, self._monotonic),
            rules_hash(excluded, lan_cidrs(lan)),
            excluded,
            lan,
        )
        try:
            state, tried, failures = self._prepare(p)
            # OLD CODE: if state is not None: (review: with OpenSearch down, e.g. a 401 after every
            # recreate until its security bootstrap, every chunk failed in one pass and every
            # older day read stale for a day; a failed listing now ends the pass here)
            if state is not None and not failures:
                for step in (self._recent, self._sweep):
                    state, more, fails = step(p, state)
                    tried, failures = tried + more, [*failures, *fails]
        except _SaveFailed as exc:
            raise UsageLedgerIncomplete(
                f"couldn't save the usage ledger: {exc}"
            ) from exc
        if failures:
            raise UsageLedgerIncomplete(
                f"{len(failures)} of {tried} day groups failed: {failures[0]}"
            )
        return {"partial": True} if state["sweep"]["cursor"] else None

    def _prepare(self, p: _Pass) -> tuple[dict | None, int, list[str]]:
        """Steps 1–2: a new ledger, a time-zone transition, or the inventory's evidence."""
        state = self.snapshot()
        owner = owner_tz.read()
        try:
            if state is None:
                return self._commit(self._fresh(p, owner["tz"], 1, 0)), 1, []
            if owner["ok"] and owner["set"] and owner["tz"] != state["tz"]:
                return self._transition(p, state, owner["tz"]), 1, []
            if not owner["ok"]:
                logger.warning(
                    "Time zone setting unreadable; counting in %s", state["tz"]
                )
            return self._take_inventory(p, state), 1, []
        except LEDGER_QUERY_ERRORS as exc:
            logger.warning("Usage ledger: the index listing failed: %s", exc)
            # OLD CODE START — review: an unknown inventory stopped the pass, a known one didn't, so
            # an outage failed every chunk in one pass; run() now stops at any failure here
            # known = state if state is not None and state.get("inventory_ok") else None
            # return known, 1, [f"the index listing: {_short(exc)}"]
            # OLD CODE END
            return state, 1, [f"the index listing: {_short(exc)}"]

    # OLD CODE: def _fresh(self, p, tz_name, generation, sweep_id) -> dict: (review: + floor)
    def _fresh(
        self,
        p: _Pass,
        tz_name: str,
        generation: int,
        sweep_id: int,
        floor: date | None = None,
    ) -> dict:
        return new_state(
            tz_name=tz_name,
            indices=self._inventory(p.budget),
            rules=p.rules,
            now=self._now(),
            generation=generation,
            sweep_id=sweep_id,
            floor=floor,
        )

    def _transition(self, p: _Pass, state: dict, tz_name: str) -> dict:
        """Old ledger kept, a new one bootstrapped in the new zone, saved, then published.
        A crash between the steps leaves the old ledger, so the next pass starts over."""
        # OLD CODE: self._save(self._path.with_suffix(".prev.json"), state)
        # (review: a second zone change replaced the only copy of the first ledger.) Named by its
        # generation and last save, so a repeated transition rewrites the same file and a ledger
        # started again after a lost file (generation 1 again) gets its own
        saved = parse_iso(state.get("updated_at")) or self._now()
        kept = self._kept_as(
            f"gen{state['generation']}", saved.astimezone(timezone.utc)
        )
        self._save(kept, state)
        logger.info("Usage ledger: counting days in %s from now on", tz_name)
        # the first UTC date the old ledger counted: nothing before it was ever captured
        floor = day_bounds(parse_day(state["since"]), ZoneInfo(state["tz"]))[0].date()
        # OLD CODE: fresh = self._fresh(p, tz_name, state["generation"] + 1, state["sweep"]["id"])
        fresh = self._fresh(
            p, tz_name, state["generation"] + 1, state["sweep"]["id"], floor
        )
        return self._commit(fresh)

    def _take_inventory(self, p: _Pass, state: dict) -> dict:
        now = self._now()
        state = trimmed(state, local_today(now, ZoneInfo(state["tz"])))
        if not state.get("inventory_ok"):
            logger.warning("Usage ledger: index inventory unknown; every day marked")
            state = mark_all_lost(state, now)
        listing = self._inventory(p.budget)
        updated = {**observe(state, listing, now), "inventory_ok": True}
        return self._commit(updated) if updated != self.snapshot() else updated

    def _recent(self, p: _Pass, state: dict) -> tuple[dict, int, list[str]]:
        """Step 3: today, yesterday and the day before, in one query."""
        today = local_today(self._now(), ZoneInfo(state["tz"]))
        days = [
            d
            for d in (today - timedelta(days=n) for n in range(RECENT_DAYS - 1, -1, -1))
            if countable(state, d, today)
        ]
        if not days:
            return state, 0, []
        try:
            return self._commit(self._recount(p, state, days), counted=True), 1, []
        except LEDGER_QUERY_ERRORS as exc:
            logger.warning("Usage ledger: recounting the recent days failed: %s", exc)
            keys = [day_key(d) for d in days]
            marked = failed(state, keys, exc, utc_iso(self._now()))
            return self._commit(marked), 1, [f"recent days: {_short(exc)}"]

    def _take_sweep_request(self) -> bool:
        with self._lock:
            return self._sweep_requested

    def _clear_sweep_request(self) -> None:
        with self._lock:
            self._sweep_requested = False

    def _sweep(self, p: _Pass, state: dict) -> tuple[dict, int, list[str]]:
        """Step 4: older days, a 7-day chunk at a time from the saved cursor."""
        now = self._now()
        today = local_today(now, ZoneInfo(state["tz"]))
        requested = self._take_sweep_request()
        if sweep_due(state, p.rules, now, requested):
            state = self._commit(start_sweep(state, p.rules, now, today))
        # OLD CODE: cleared only when it started a sweep (review: a running one now answers it)
        if requested:
            self._clear_sweep_request()
        tried, failures = 0, []
        # OLD CODE: while state["sweep"]["cursor"] and p.budget.remaining() > 0: (review: a chunk
        # started with under a second left timed out and spent a retry); past this the run stops
        # as a continuation, no retry counted
        while state["sweep"]["cursor"] and p.budget.remaining() >= MIN_CHUNK_BUDGET_S:
            chunk, cursor = next_chunk(state, today)
            if not chunk:
                state = self._commit(advance(state, None, True, self._now()))
                break
            tried += 1
            state, why, stop = self._sweep_chunk(p, state, chunk, cursor)
            failures = [*failures, *([why] if why else [])]
            if stop:
                break
        return state, tried, failures

    def _sweep_chunk(
        self, p: _Pass, state: dict, chunk: list[date], cursor: str | None
    ) -> tuple[dict, str | None, bool]:
        """(state, failure or None, stop the sweep for this run) for one chunk."""
        try:
            counted = self._recount(p, state, chunk)
        except TIMEOUTS as exc:
            retries = state["sweep"].get("retries", 0) + 1
            if retries < MAX_CONTINUATIONS:
                # a continuation: results dropped, cursor and counters kept, next run redoes it
                logger.info("Usage ledger: sweep chunk %s ran out of time", chunk[0])
                kept = {**state, "sweep": {**state["sweep"], "retries": retries}}
                return self._commit(kept), None, True
            return self._chunk_failed(state, chunk, cursor, exc)
        except LEDGER_QUERY_ERRORS as exc:
            return self._chunk_failed(state, chunk, cursor, exc)
        done = advance(counted, cursor, True, self._now())
        return self._commit(done, counted=True), None, False

    def _chunk_failed(
        self, state: dict, chunk: list[date], cursor: str | None, exc: Exception
    ) -> tuple[dict, str, bool]:
        """Its days go stale and the cursor moves on, so one bad chunk can't stall the sweep;
        the run stops there, so an outage costs one chunk a run, not the whole sweep."""
        logger.warning("Usage ledger: sweep chunk %s failed: %s", chunk[0], exc)
        now = self._now()
        marked = failed(state, [day_key(d) for d in chunk], exc, utc_iso(now))
        why = f"days {day_key(chunk[0])} to {day_key(chunk[-1])}: {_short(exc)}"
        # OLD CODE: return self._commit(advance(marked, cursor, False, now)), why, False (review)
        return self._commit(advance(marked, cursor, False, now)), why, True
