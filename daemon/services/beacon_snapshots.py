"""Beaconing results for the Threats page's 24h, 7d and 30d pills, kept fresh in the background.

NET-192 PR 3: the full scan (a 10 s date_histogram per candidate pair) took ~65 s at 7 days on
the G11, past what a page load can wait. A task started with the daemon rescans each window on
its own schedule, one scan at a time, and the page reads the last result. Only a complete scan
is published: a scan the bucket cap stopped part way changes classifications (many_hosts needs
all of a source's destinations), so it counts as a failed refresh.

State is read and written on the request loop only (each scan runs in a worker thread, and its
result is stored after the await), so it needs no lock.
"""

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable

from api.offload import run_blocking

logger = logging.getLogger("nettap.beacon_snapshots")

WINDOWS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
# 30 d scans the most data, so it refreshes hourly
INTERVALS_S = {"24h": 15 * 60, "7d": 15 * 60, "30d": 60 * 60}
CAP_HIT = "scan hit the bucket cap"
QUERY_FAILED = "the beaconing query failed"
# After a reboot the daemon often starts before OpenSearch (or its auth bootstrap) is up, so a
# failed query is retried after a minute, then 2, 4, 8… minutes, never later than the interval.
# A scan the bucket cap stopped will stop there again, so it waits the normal interval.
RETRY_S = 60


def _retry_delay(previous: float | None, interval: float) -> float:
    """The wait after a failed query: RETRY_S, then double the previous wait, up to `interval`."""
    return min(RETRY_S if previous is None else 2 * previous, interval)


def _iso(when: datetime | None) -> str | None:
    return when.isoformat() if when else None


@dataclass(frozen=True)
class _Window:
    beacons: tuple = ()  # the last complete scan's rows
    scanned_from: str | None = None
    scanned_to: str | None = None
    last_success_at: datetime | None = None
    computed_at: datetime | None = None  # when the latest run ended, success or not
    last_error: str | None = None  # the latest run's error; None once a run succeeds


class BeaconSnapshots:
    """The last complete beaconing scan per window, and the task that refreshes them."""

    def __init__(
        self,
        scan: Callable[[str, str], tuple[list[dict], bool]],
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._scan = scan  # blocking: (from, to) -> (beacons, complete)
        self._now = now
        self._windows = {w: _Window() for w in WINDOWS}
        self._task: asyncio.Task | None = None

    def beacons(self, window: str) -> list[dict]:
        return list(self._windows[window].beacons)

    def snapshot(self, window: str) -> dict:
        """The state contract both /api/threats routes return with `snapshot=`."""
        w = self._windows[window]
        if w.last_success_at is None:
            state = "pending" if w.computed_at is None else "failed"
        elif w.last_error is None and self._now() - w.last_success_at <= timedelta(
            seconds=2 * INTERVALS_S[window]
        ):
            state = "ready"
        else:
            state = (
                "stale"  # the latest refresh failed, or none has finished for too long
            )
        return {
            "window": window,
            "state": state,
            "computed_at": _iso(w.computed_at),
            "last_success_at": _iso(w.last_success_at),
            "last_error": w.last_error,
            "from": w.scanned_from,
            "to": w.scanned_to,
        }

    async def refresh(self, window: str) -> None:
        """Scan one window (one worker-thread call) and keep the result if the scan was complete."""
        to = self._now()
        from_ts, to_ts = _iso(to - WINDOWS[window]), _iso(to)
        started = time.monotonic()
        try:
            beacons, complete = await run_blocking(self._scan, from_ts, to_ts)
            error = None if complete else CAP_HIT
        except Exception:
            logger.exception("beacon-snapshot window=%s: the scan failed", window)
            beacons, error = [], QUERY_FAILED
        finished = self._now()
        old = self._windows[window]
        new = (
            replace(old, computed_at=finished, last_error=error)
            if error
            else _Window(tuple(beacons), from_ts, to_ts, finished, finished, None)
        )
        self._windows = {**self._windows, window: new}
        logger.info(
            "beacon-snapshot window=%s duration_s=%.1f beacons=%d outcome=%s",
            window,
            time.monotonic() - started,
            len(beacons),
            "published" if error is None else f"kept previous ({error})",
        )

    async def run_forever(self) -> None:
        """Refresh whichever window is due next, one at a time, forever (24h first at start).

        A window whose query failed is retried sooner (RETRY_S, doubling, up to its interval).
        """
        loop = asyncio.get_running_loop()
        due = {w: loop.time() for w in WINDOWS}
        # window -> its last retry wait, while its query keeps failing
        retry: dict[str, float] = {}
        while True:
            window = min(due, key=due.__getitem__)  # ties go to the first: 24h, then 7d
            wait = due[window] - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
            started = loop.time()
            await self.refresh(window)
            if self._windows[window].last_error == QUERY_FAILED:
                delay = _retry_delay(retry.get(window), INTERVALS_S[window])
                retry = {**retry, window: delay}
            else:
                delay = INTERVALS_S[window]
                retry = {w: d for w, d in retry.items() if w != window}
            due = {**due, window: started + delay}

    def start(self) -> None:
        self._task = asyncio.create_task(self.run_forever(), name="beacon-snapshots")

    async def stop(self) -> None:
        """Stop scheduling. A scan already in a worker thread is read-only and ends by itself."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
