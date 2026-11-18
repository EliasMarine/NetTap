"""
NetTap's background checks (NET-319, roadmap F1): one small runner every later check plugs into.

The contract every job gets:
- its own two worker threads, never the request pool, so a slow check can't starve the API;
- no overlap: a job still running is skipped (and counted), never started twice;
- a slot is held until the thread really returns, even past the job's deadline, so a hung job
  shows as overdue instead of quietly letting a third thread start;
- a deadline (time.monotonic()) the job passes on to OpenSearch as its own timeouts;
- its last run, error, duration and memory saved, so Settings can show it after a restart.
"""

import asyncio
import contextlib
import json
import logging
import os
import time
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.capture_config import write_file_atomic

logger = logging.getLogger("nettap.services.scheduled_jobs")

DEFAULT_STATE = os.environ.get(
    "SCHEDULED_JOBS_FILE", "/opt/nettap/data/scheduled-jobs.json"
)
TICK_S = 30
WORKERS = 2


@dataclass(frozen=True)
class Job:
    name: str
    label: str
    every_s: int
    deadline_s: int
    # run(deadline) -> {"partial": True} when it stopped at the deadline, else None
    run: Callable[[float], dict | None]


def _status_mb(field: str) -> float | None:
    """A memory figure of this process from /proc (VmRSS, VmHWM); None off Linux."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith(field + ":"):
                    return round(int(line.split()[1]) / 1024, 1)
    except (OSError, ValueError, IndexError):
        pass
    return None


def _when(raw: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


class Scheduler:
    """Runs registered jobs on their schedule, from one cleanup_ctx task."""

    def __init__(
        self,
        jobs: list[Job],
        state_path: str = DEFAULT_STATE,
        workers: int = WORKERS,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._jobs = {j.name: j for j in jobs}
        self._state_path = Path(state_path)
        self._workers = workers
        self._executor = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="nettap-job"
        )
        self._now = now
        self._monotonic = monotonic
        self._running: dict[str, float] = {}  # name -> monotonic start
        self._requested: frozenset[str] = frozenset()
        self._state: dict[str, dict] = self._load()
        self._wake: asyncio.Event | None = None

    # --- state -------------------------------------------------------------

    def _load(self) -> dict[str, dict]:
        try:
            data = json.loads(self._state_path.read_text())
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if isinstance(v, dict)}
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            logger.warning("Background job state unreadable, starting fresh (%s)", exc)
        return {}

    def _save(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            write_file_atomic(
                str(self._state_path), json.dumps(self._state), mode=0o600
            )
        except OSError as exc:
            logger.warning("Couldn't save the background job state: %s", exc)

    # --- scheduling --------------------------------------------------------

    def _due(self, job: Job, now: datetime) -> bool:
        if job.name in self._requested:
            return True
        last = _when(self._state.get(job.name, {}).get("last_run"))
        return last is None or (now - last).total_seconds() >= job.every_s

    def request_run(self, name: str) -> str:
        """ "accepted", "running" or "unknown": the next tick starts it, through the same
        admission as a scheduled run."""
        if name not in self._jobs:
            return "unknown"
        if name in self._running:
            return "running"
        self._requested = self._requested | {name}
        if self._wake is not None:
            self._wake.set()
        return "accepted"

    def tick(self) -> list[str]:
        """Start every due job a slot allows; must run on the event loop."""
        now = self._now()
        started = []
        for job in self._jobs.values():
            if not self._due(job, now):
                continue
            if job.name in self._running:
                # due is measured from the start of the last finished run: an overlap is only
                # once this run has gone a whole interval
                if self._monotonic() - self._running[job.name] < job.every_s:
                    continue
                entry = self._state.get(job.name, {})
                self._state = {
                    **self._state,
                    job.name: {
                        **entry,
                        "skipped_overlaps": entry.get("skipped_overlaps", 0) + 1,
                    },
                }
                continue
            if len(self._running) >= self._workers:
                break  # stays due: the next tick tries again
            self._start(job, now)
            started.append(job.name)
        return started

    def _start(self, job: Job, now: datetime) -> None:
        begun = self._monotonic()
        rss_before = _status_mb("VmRSS")
        # OLD CODE START — NET-319 review: a submit that raised (no thread to start) left the
        # slot taken for ever, so the job answered 409 until a restart
        # self._running = {**self._running, job.name: begun}
        # self._requested = self._requested - {job.name}
        # OLD CODE END
        future = asyncio.get_running_loop().run_in_executor(
            self._executor, job.run, begun + job.deadline_s
        )
        # the done-callback runs on a later loop turn, so the slot is taken before it frees it
        self._running = {**self._running, job.name: begun}
        self._requested = self._requested - {job.name}
        future.add_done_callback(lambda f: self._finish(job, f, now, begun, rss_before))

    def _finish(
        self,
        job: Job,
        future: asyncio.Future,
        started_at: datetime,
        begun: float,
        rss_before: float | None,
    ) -> None:
        """The thread has returned: free its slot and record the run."""
        self._running = {k: v for k, v in self._running.items() if k != job.name}
        error, partial = None, False
        if future.cancelled():
            error = "cancelled"
        elif (exc := future.exception()) is not None:
            error = f"{type(exc).__name__}: {exc}"[:300]
            logger.error("Background job %s failed: %s", job.name, error)
        else:
            result = future.result()
            partial = bool(isinstance(result, dict) and result.get("partial"))
        entry = self._state.get(job.name, {})
        self._state = {
            **self._state,
            job.name: {
                "last_run": started_at.isoformat(),
                "last_duration_ms": int((self._monotonic() - begun) * 1000),
                "last_error": error,
                "partial": partial,
                "skipped_overlaps": entry.get("skipped_overlaps", 0),
                "rss_mb_before": rss_before,
                "rss_mb_after": _status_mb("VmRSS"),
                "peak_rss_mb": _status_mb("VmHWM"),
            },
        }
        self._save()

    # --- reading -----------------------------------------------------------

    def view(self) -> list[dict]:
        """Each job's schedule and last run, as GET /api/jobs shows them."""
        now = self._monotonic()
        rows = []
        for job in self._jobs.values():
            entry = self._state.get(job.name, {})
            begun = self._running.get(job.name)
            running_for = int(now - begun) if begun is not None else None
            rows.append(
                {
                    "name": job.name,
                    "label": job.label,
                    "every_s": job.every_s,
                    "last_run": entry.get("last_run"),
                    "last_duration_ms": entry.get("last_duration_ms"),
                    "last_error": entry.get("last_error"),
                    "partial": bool(entry.get("partial")),
                    "running": begun is not None,
                    "running_for_s": running_for,
                    "overdue": running_for is not None and running_for > job.deadline_s,
                    "skipped_overlaps": entry.get("skipped_overlaps", 0),
                    "rss_mb_before": entry.get("rss_mb_before"),
                    "rss_mb_after": entry.get("rss_mb_after"),
                    "peak_rss_mb": entry.get("peak_rss_mb"),
                }
            )
        return rows

    # --- background task ---------------------------------------------------

    async def ctx(self, _app: Any) -> AsyncIterator[None]:
        """aiohttp cleanup_ctx: tick every TICK_S, or at once when a run is requested."""
        self._wake = asyncio.Event()

        async def run() -> None:
            while True:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), TICK_S)
                self._wake.clear()
                try:
                    self.tick()
                except Exception:
                    logger.exception("Background job tick failed")

        task = asyncio.create_task(run(), name="background-jobs")
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self._executor.shutdown(wait=False, cancel_futures=True)
