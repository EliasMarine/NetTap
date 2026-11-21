"""
NetTap watched devices (NET-331, roadmap #5): one message when a watched device has been silent
longer than the owner's chosen time, and one when it is heard again.

Plan: plans/2026-11-20-f5-watched-devices.md, §2.2-§2.4 and §2.6. Passive only: every decision
uses conn records' last-packet time (event.end). The rule above all others (D4): a failure, gap
or doubt may delay or miss a message, never invent one.

    watched-devices.json  {"version": 1, "check": {...}, "devices": {MAC: {...}}}

A missing file starts empty; an unreadable one is reported and never overwritten. A transition
is saved as `pending` under the details store's lock (so a watch edit can't race it), then
appended to the event journal, then cleared. A crash anywhere repeats nothing: the next run
appends the pending, and the journal ignores an id it already holds. The pure rules (step,
readiness, the query bodies, the file's shape) are in services/watched_rules.py.
"""

import json
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from opensearchpy import ConnectionTimeout, OpenSearchException

from services.capture_config import write_file_atomic
from services.device_custom import StoreUnavailable
from services.usage_days import parse_iso
from services.watched_rules import (
    EMPTY_CHECK,
    capture_body,
    capture_scope,
    empty_state,
    enrolled,
    floor_ms,
    from_ms,
    iso,
    presence_body,
    sightings,
    state_ok,
    step,
    with_device,
    without_streaks,
)
from storage.snapshot_search import Budget, QueryFailed, TooSlow, checked

logger = logging.getLogger("nettap.services.watched_devices")

DEFAULT_PATH = os.environ.get(
    "WATCHED_DEVICES_FILE", "/opt/nettap/data/watched-devices.json"
)
FRESH = timedelta(seconds=600)  # capture_at older than this: the pipeline is behind
GAP = timedelta(seconds=900)  # successful checks further apart: coverage restarts
PENDING_MAX_AGE = timedelta(hours=24)
STATE_MAX_BYTES = 256 * 1024
MIN_TIMEOUT_S = 1.0

# check.error: fixed text, never an exception's (the card shows it)
UNREADABLE = "The watched-devices state file is unreadable."
ERR_JOURNAL = "The event journal couldn't be written."
ERR_SEARCH = "The traffic search failed."
ERR_SLOW = "The traffic search took too long."
ERR_SAVE = "The watched-devices state couldn't be saved."
ERR_OTHER = "The check failed. The daemon log has the details."

# check.reason when capture health can't be read
NO_HEALTH = "capture health didn't answer"


class StateUnreadable(Exception):
    """The state file exists but can't be trusted; it is never overwritten."""


class JournalFailed(OSError):
    """An event journal append failed."""


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, JournalFailed):
        return ERR_JOURNAL
    if isinstance(exc, TooSlow):
        return ERR_SLOW
    if isinstance(exc, QueryFailed):
        return ERR_SEARCH
    if isinstance(exc, OSError):
        return ERR_SAVE
    return ERR_OTHER


# ---------------------------------------------------------------------------
# The job
# ---------------------------------------------------------------------------


class WatchedDevices:
    """The watched-devices job (`run`) and the card's data (`view`).

    The Scheduler never overlaps runs, so one pass's working state lives on the instance;
    `view` reads only the file, which every save replaces whole.
    """

    def __init__(
        self,
        *,
        details: Any,
        journal: Any,
        name_for: Callable[[str], str | None],
        client: Any,
        index: str,
        capture_health: Callable[[], dict],
        path: str = DEFAULT_PATH,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._details = details
        self._journal = journal
        self._name_for = name_for
        self._client = client  # built with max_retries=0, retry_on_timeout=False
        self._index = index
        self._capture_health = capture_health
        self._path = path
        self._now = now
        self._monotonic = monotonic
        self._state = empty_state()
        self._last_skip: tuple[str, str | None] | None = None

    # --- the file ----------------------------------------------------------

    def _read(self) -> dict:
        try:
            with open(self._path, "rb") as fh:
                data = fh.read(STATE_MAX_BYTES + 1)
        except FileNotFoundError:
            return empty_state()
        except OSError as exc:
            raise StateUnreadable(UNREADABLE) from exc
        try:
            if len(data) > STATE_MAX_BYTES:
                raise ValueError(f"larger than {STATE_MAX_BYTES} bytes")
            raw = json.loads(data.decode("utf-8"))
        # JSONDecodeError and UnicodeDecodeError are ValueErrors; deep nesting is RecursionError
        except (ValueError, RecursionError) as exc:
            raise StateUnreadable(UNREADABLE) from exc
        if not state_ok(raw):
            raise StateUnreadable(UNREADABLE)
        return {**raw, "check": {**EMPTY_CHECK, **raw["check"]}}

    def _save(self, state: dict) -> None:
        """Atomic replace, then fsync the directory so the rename itself is durable."""
        folder = os.path.dirname(self._path) or "."
        os.makedirs(folder, exist_ok=True)
        text = json.dumps(state, sort_keys=True, separators=(",", ":"))
        # pending events carry the owner's own device names: 0600
        write_file_atomic(self._path, text, mode=0o600, encoding="utf-8")
        fd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _commit_state(self, state: dict) -> None:
        self._save(state)
        self._state = state

    def _end_check(self, check: dict, broken: bool) -> None:
        """Save the run's check; a broken coverage also clears every streak (§2.3 step 5)."""
        devices = self._state["devices"]
        if broken:
            check = {**check, "coverage_since": None}
            devices = without_streaks(devices)
        self._commit_state({**self._state, "check": check, "devices": devices})

    # --- the job -----------------------------------------------------------

    def run(self, deadline: float) -> None:
        """One check (F1 job). Always saves `check` unless the file is unreadable; re-raises."""
        now = floor_ms(self._now())
        try:
            self._state = self._read()
        except StateUnreadable as exc:
            # logged here, not in _read: the card's polling would repeat it
            logger.error(
                # %s, not %r: a UnicodeDecodeError's repr carries the whole file
                "Watched devices state %s is unreadable (%s); left as it is. Delete it "
                "to start again.",
                self._path,
                exc.__cause__ or "wrong version or shape",
            )
            raise
        attempt = {**self._state["check"], "attempt_at": iso(now)}
        try:
            self._pass(
                now, attempt, Budget(deadline - self._monotonic(), self._monotonic)
            )
        except Exception as exc:
            logger.warning("Watched devices check failed: %s", exc)
            failed = {
                **attempt,
                "skipped": None,
                "reason": None,
                "error": _error_text(exc),
            }
            try:
                self._end_check(failed, broken=True)
            except OSError as save_exc:
                logger.warning("Couldn't save the watched devices check: %s", save_exc)
            raise

    def _pass(self, now: datetime, attempt: dict, budget: Budget) -> None:
        self._replay_pending(now)
        watched = self._reconcile(now)
        if watched is None:
            return self._skip(attempt, "store", None)
        if not watched:
            return self._succeed(attempt, now)
        scope, reason = self._readiness()
        if scope is None:
            return self._skip(attempt, "mode", reason)
        capture_at = self._capture_at(now, budget)
        if capture_at is None or now - capture_at > FRESH:
            return self._skip(attempt, "pipeline", None)
        # both searches before any re-baseline, so a refused reply changes no device
        found = self._sightings(now, budget)
        coverage_since = self._cover(scope, capture_at, now)
        transitions = self._step_all(found, capture_at, coverage_since, now)
        if transitions and self._readiness()[0] != scope:
            logger.info(
                "Watched devices: capture changed during the check; transitions dropped"
            )
            transitions = []
        self._commit_transitions(transitions)
        self._succeed(
            attempt,
            now,
            capture_at=iso(capture_at),
            coverage_since=iso(coverage_since),
            scope=scope,
        )

    def _succeed(self, attempt: dict, now: datetime, **covered: str) -> None:
        """Save a successful check; `covered` (capture_at, coverage_since, scope) when the
        searches ran. With no watches the previous ones are kept."""
        ok = {
            **attempt,
            **covered,
            "success_at": iso(now),
            "skipped": None,
            "reason": None,
            "error": None,
        }
        self._end_check(ok, broken=False)
        self._last_skip = None

    def _skip(self, attempt: dict, skipped: str, reason: str | None) -> None:
        if self._last_skip != (skipped, reason):
            logger.info(
                "Watched devices paused: %s%s",
                skipped,
                f" ({reason})" if reason else "",
            )
            self._last_skip = (skipped, reason)
        self._end_check(
            {**attempt, "skipped": skipped, "reason": reason, "error": None},
            broken=True,
        )

    # --- step 1: finish pending transitions --------------------------------

    def _append(self, pending: dict) -> None:
        try:
            self._journal.append(
                pending["type"],
                pending["key"],
                pending["observed_at"],
                pending["data"],
                instance=pending["instance"],
            )
        except OSError as exc:
            raise JournalFailed(str(exc)) from exc

    def _replay_pending(self, now: datetime) -> None:
        """Append what each pending holds (a duplicate is a no-op), then clear it. Raises on a
        failed append, so nothing new is evaluated while one is unfinished."""
        for mac, dev in sorted(self._state["devices"].items()):
            pending = dev["pending"]
            if pending is None:
                continue
            if now - parse_iso(pending["observed_at"]) > PENDING_MAX_AGE:
                logger.warning(
                    "Watched device %s: %s not journalled within 24 hours, dropped",
                    mac,
                    pending["type"],
                )
            else:
                self._append(pending)
            self._commit_state(with_device(self._state, mac, {**dev, "pending": None}))

    # --- step 2: reconcile the watch list ----------------------------------

    def _reconcile(self, now: datetime) -> dict[str, int] | None:
        """{MAC: after_min} now watched, the state pruned and enrolled to match; None when the
        details store is unreadable."""
        try:
            exported = self._details.export()
        except StoreUnavailable:
            return None
        watched = {
            mac: entry["watch_after_min"]
            for mac, entry in exported.items()
            if entry.get("watch_after_min") is not None
        }
        old = self._state["devices"]
        devices = {}
        for mac, after_min in watched.items():
            dev = old.get(mac)
            if dev is None:
                devices[mac] = enrolled(after_min, now)
            elif dev["after_min"] != after_min:
                devices[mac] = {**dev, "after_min": after_min, "silent_from": None}
            else:
                devices[mac] = dev
        self._state = {**self._state, "devices": devices}
        return watched

    # --- step 3: capture readiness ------------------------------------------

    def _readiness(self) -> tuple[str | None, str | None]:
        try:
            health = self._capture_health()
        except Exception as exc:  # a timeout, the loop gone, a manager that raised
            logger.debug("Watched devices: capture health failed: %s", exc)
            return None, NO_HEALTH
        if not isinstance(health, dict):
            return None, NO_HEALTH
        return capture_scope(health)

    # --- steps 4-5: freshness, scope, coverage ------------------------------

    def _search(
        self, body: dict, budget: Budget, what: str, required: tuple[str, ...]
    ) -> dict:
        """One search with the deadline's remainder as its timeouts; refused unless whole."""
        budget.check(what)
        timeout = budget.remaining()
        if timeout < MIN_TIMEOUT_S:
            raise TooSlow(f"{what}: no time left")
        try:
            reply = self._client.search(
                index=self._index,
                body={**body, "timeout": f"{int(timeout * 1000)}ms"},
                request_timeout=timeout,
            )
        except ConnectionTimeout as exc:
            raise TooSlow(f"{what} took too long") from exc
        except OpenSearchException as exc:
            raise QueryFailed(f"{what} failed: {exc}") from exc
        reply = checked(reply, what, required)
        shards = reply.get("_shards")
        if not isinstance(shards, dict) or not shards.get("total"):
            raise QueryFailed(f"{what}: no shards searched")
        return reply

    def _capture_at(self, now: datetime, budget: Budget) -> datetime | None:
        reply = self._search(
            capture_body(now), budget, "the capture time", ("capture_at",)
        )
        try:
            return from_ms(reply["aggregations"]["capture_at"].get("value"))
        except (ValueError, OverflowError) as exc:
            raise QueryFailed(f"the capture time: malformed reply ({exc})") from exc

    def _cover(self, scope: str, capture_at: datetime, now: datetime) -> datetime:
        """The coverage start, after a scope change re-baselines every watch (§2.3 4a-5)."""
        check, devices = self._state["check"], self._state["devices"]
        prev = parse_iso(check["capture_at"])
        restart = (
            check["coverage_since"] is None or prev is None or capture_at - prev > GAP
        )
        if check["scope"] is not None and check["scope"] != scope:
            logger.info(
                "Watched devices: capture scope changed; every watch starts again"
            )
            # a down device keeps its incident, so its first sighting journals the recovery
            devices = {
                mac: {
                    **dev,
                    "state": "unknown",
                    "enrolled_at": iso(now),
                    "since": None,
                }
                for mac, dev in devices.items()
            }
            restart = True
        if restart:
            self._state = {**self._state, "devices": without_streaks(devices)}
            return capture_at
        return parse_iso(check["coverage_since"])

    # --- steps 6-7: presence and the state machine --------------------------

    def _sightings(
        self, now: datetime, budget: Budget
    ) -> dict[str, tuple[datetime, datetime]]:
        macs = sorted(mac.lower() for mac in self._state["devices"])
        reply = self._search(
            presence_body(macs, now),
            budget,
            "the presence search",
            ("sent", "answered"),
        )
        try:
            return sightings(reply)
        except (KeyError, TypeError, AttributeError, ValueError, OverflowError) as exc:
            raise QueryFailed(
                f"the presence search: malformed reply ({exc!r})"
            ) from exc

    def _step_all(
        self,
        found: dict[str, tuple[datetime, datetime]],
        capture_at: datetime,
        coverage_since: datetime,
        now: datetime,
    ) -> list[tuple[str, int, dict, dict]]:
        """Apply every step without an event; return the transitions (MAC, after_min used,
        the new device, the pending) still to commit."""
        devices, transitions = {}, []
        for mac, dev in self._state["devices"].items():
            seen_new, started_new = found.get(mac, (None, None))
            new_dev, event = step(
                dev, seen_new, started_new, capture_at, coverage_since, now
            )
            if event is None:
                devices[mac] = new_dev
                continue
            devices[mac] = dev  # until its commit
            pending = {
                "type": event["type"],
                "key": mac,
                "instance": event["instance"],
                "observed_at": iso(now),
                "data": {"mac": mac, "name": self._name_for(mac), **event["data"]},
            }
            transitions.append((mac, dev["after_min"], new_dev, pending))
        self._state = {**self._state, "devices": devices}
        return transitions

    # --- steps 8-9: the two-phase commit ------------------------------------

    def _commit_transitions(
        self, transitions: list[tuple[str, int, dict, dict]]
    ) -> None:
        """Save each transition with its pending while the watch is held unchanged, then
        journal it (outside the lock), then clear the pending."""
        for mac, after_min, new_dev, pending in transitions:
            with self._details.watch_is(mac, after_min) as still:
                if not still:
                    logger.info(
                        "Watched device %s changed during the check; transition dropped",
                        mac,
                    )
                    continue
                self._commit_state(
                    with_device(self._state, mac, {**new_dev, "pending": pending})
                )
            self._append(pending)
            self._commit_state(
                with_device(self._state, mac, {**new_dev, "pending": None})
            )
            logger.info("Watched device %s is %s", mac, new_dev["state"])

    # --- the API -----------------------------------------------------------

    def view(self) -> dict:
        """GET /api/devices/watched: {check, devices}. Raises StoreUnavailable (the API's 503).

        The list is the details store's watches; an unreadable state file gives check.error
        with every device unknown.
        """
        exported = self._details.export()
        try:
            state = self._read()
            check, devices = state["check"], state["devices"]
        except StateUnreadable:
            check, devices = {**EMPTY_CHECK, "error": UNREADABLE}, {}
        rows = []
        for mac in sorted(exported):
            after_min = exported[mac].get("watch_after_min")
            if after_min is None:
                continue
            dev = devices.get(mac)
            incident = dev["incident"] if dev else None
            rows.append(
                {
                    "mac": mac,
                    "name": self._name_for(mac),
                    "after_min": after_min,
                    "state": dev["state"] if dev else "unknown",
                    # the last confirmed sighting: the incident's while one is open
                    "seen_at": incident["seen_at"]
                    if incident
                    else (dev or {}).get("seen_at"),
                    "since": dev["since"] if dev else None,
                }
            )
        return {"check": check, "devices": rows}
