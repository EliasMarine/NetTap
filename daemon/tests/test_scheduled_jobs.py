"""The background job runner's contract (NET-319)."""

import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from api.jobs import register_jobs_routes
from services.scheduled_jobs import Job, Scheduler

T0 = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self) -> None:
        self.wall = T0
        self.mono = 1000.0

    def now(self) -> datetime:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def advance(self, seconds: float) -> None:
        self.wall += timedelta(seconds=seconds)
        self.mono += seconds


def _blocking(release: threading.Event, started: threading.Event | None = None):
    def run(_deadline: float) -> None:
        if started:
            started.set()
        release.wait(5)

    return run


async def _settle(scheduler: Scheduler, name: str) -> None:
    for _ in range(200):
        if not any(r["running"] for r in scheduler.view() if r["name"] == name):
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"{name} never finished")


def _sched(tmp_path, jobs, clock, workers=2) -> Scheduler:
    return Scheduler(
        jobs,
        str(tmp_path / "jobs.json"),
        workers=workers,
        now=clock.now,
        monotonic=clock.monotonic,
    )


def test_a_running_job_is_skipped_and_counted_not_started_twice(tmp_path):
    async def go() -> None:
        clock, release, started = Clock(), threading.Event(), threading.Event()
        calls = []

        def run(deadline):
            calls.append(deadline)
            started.set()
            release.wait(5)

        s = _sched(tmp_path, [Job("a", "A", 60, 30, run)], clock)
        assert s.tick() == ["a"]
        await asyncio.to_thread(started.wait, 5)
        clock.advance(30)  # a tick inside the interval is not an overlap
        assert s.tick() == []
        clock.advance(90)  # due again while still running
        assert s.tick() == []
        assert s.tick() == []
        release.set()
        await _settle(s, "a")
        row = s.view()[0]
        assert len(calls) == 1
        assert row["skipped_overlaps"] == 2
        assert row["last_error"] is None

    asyncio.run(go())


def test_at_most_two_run_together_and_a_hung_job_keeps_its_slot(tmp_path):
    async def go() -> None:
        clock, release = Clock(), threading.Event()
        jobs = [Job(n, n, 60, 10, _blocking(release)) for n in "abc"]
        s = _sched(tmp_path, jobs, clock)
        assert s.tick() == ["a", "b"]
        clock.advance(30)  # past a's and b's 10 s deadline: still holding their slots
        assert s.tick() == []
        rows = {r["name"]: r for r in s.view()}
        assert rows["a"]["running"] and rows["a"]["overdue"]
        assert rows["a"]["running_for_s"] == 30
        assert not rows["c"]["running"]
        release.set()
        await _settle(s, "a")
        await _settle(s, "b")
        assert s.tick() == ["c"]
        await _settle(s, "c")

    asyncio.run(go())


def test_partial_and_errors_are_recorded(tmp_path):
    async def go() -> None:
        clock = Clock()

        def boom(_d):
            raise OSError("disk full")

        s = _sched(
            tmp_path,
            [
                Job("p", "P", 60, 10, lambda _d: {"partial": True}),
                Job("e", "E", 60, 10, boom),
            ],
            clock,
        )
        s.tick()
        await _settle(s, "p")
        await _settle(s, "e")
        rows = {r["name"]: r for r in s.view()}
        assert rows["p"]["partial"] is True and rows["p"]["last_error"] is None
        assert rows["e"]["last_error"] == "OSError: disk full"
        assert rows["e"]["last_run"] == T0.isoformat()

    asyncio.run(go())


def test_state_survives_a_restart_and_a_daily_job_waits(tmp_path):
    async def go() -> None:
        clock = Clock()
        ran = []
        job = Job("daily", "Daily", 86400, 60, lambda _d: ran.append(1))
        s = _sched(tmp_path, [job], clock)
        s.tick()
        await _settle(s, "daily")
        clock.advance(3600)
        again = _sched(tmp_path, [job], clock)  # a restart an hour later
        assert again.tick() == []
        assert again.view()[0]["last_run"] == T0.isoformat()
        clock.advance(86400)
        assert again.tick() == ["daily"]
        await _settle(again, "daily")
        assert len(ran) == 2
        saved = json.loads((tmp_path / "jobs.json").read_text())
        assert saved["daily"]["last_duration_ms"] >= 0

    asyncio.run(go())


def test_run_now_goes_through_admission(tmp_path):
    async def go() -> None:
        clock, release, started = Clock(), threading.Event(), threading.Event()
        job = Job("daily", "Daily", 86400, 60, _blocking(release, started))
        s = _sched(tmp_path, [job], clock)
        s.tick()
        await asyncio.to_thread(started.wait, 5)
        assert s.request_run("daily") == "running"
        assert s.request_run("nope") == "unknown"
        release.set()
        await _settle(s, "daily")
        assert s.tick() == []  # not due for a day
        assert s.request_run("daily") == "accepted"
        assert s.tick() == ["daily"]
        await _settle(s, "daily")
        assert s.tick() == []  # the request is used up

    asyncio.run(go())


def test_jobs_api(tmp_path):
    async def go() -> None:
        clock, release, started = Clock(), threading.Event(), threading.Event()
        s = _sched(
            tmp_path,
            [
                Job(
                    "journal-compact",
                    "Event journal clean-up",
                    86400,
                    60,
                    _blocking(release, started),
                )
            ],
            clock,
        )
        app = web.Application()
        register_jobs_routes(app, s)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/jobs")
            body = await resp.json()
            assert resp.status == 200
            assert body["jobs"][0]["name"] == "journal-compact"
            assert body["jobs"][0]["label"] == "Event journal clean-up"
            assert body["jobs"][0]["last_run"] is None
            resp = await client.post("/api/jobs/journal-compact/run")
            assert (resp.status, await resp.json()) == (
                202,
                {"accepted": True, "name": "journal-compact"},
            )
            s.tick()
            await asyncio.to_thread(started.wait, 5)
            resp = await client.post("/api/jobs/journal-compact/run")
            assert resp.status == 409
            resp = await client.post("/api/jobs/<script>/run")
            assert resp.status == 404
            assert "<script>" not in await resp.text()
            release.set()
            await _settle(s, "journal-compact")

    asyncio.run(go())
