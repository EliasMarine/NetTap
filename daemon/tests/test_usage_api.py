"""The usage ledger's API (NET-329, roadmap F4 §4.5) and the owner's time zone (§4.1)."""

import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from api.bandwidth import register_bandwidth_routes
from api.usage import register_usage_routes
from services import owner_tz
from services.bandwidth_tracker import BandwidthTracker
from services.device_accounting import lan_cidrs
from services.usage_days import rules_hash
from services.usage_ledger import UsageLedger

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
RULES = rules_hash([], lan_cidrs(None))


def _day(total: int, **extra) -> dict:
    return {
        "total": total,
        "download": total - 10,
        "upload": 10,
        "local": 3,
        "rules": RULES,
        "counted_at": "2026-11-18T11:30:00Z",
        "cutoff": "2026-11-18T00:00:00Z",
        **extra,
    }


def _ledger_file(**changes) -> dict:
    days = {f"2026-11-{n:02d}": _day(100) for n in (3, 4, 12, 13, 14, 15, 16, 17)}
    return {
        "version": 1,
        "generation": 1,
        "tz": "UTC",
        "since": "2026-11-03",
        "rules": RULES,
        "updated_at": "2026-11-18T11:30:00Z",
        "sweep": {
            "id": 4,
            "cursor": None,
            "started_at": "2026-11-18T03:00:00Z",
            "finished_at": "2026-11-18T03:05:00Z",
            "chunks_done": 3,
            "chunks_failed": 0,
            "retries": 0,
        },
        "inventory_ok": True,
        "indices": {},
        "gaps": ["2026-11-05"],
        "days": {
            **days,
            "2026-11-06": _day(100, failed_at="2026-11-18T03:01:00Z", error="X"),
            "2026-11-08": _day(100, rules="old"),
            "2026-11-09": _day(
                100, rules="old", coverage_lost_at="2026-11-12T00:00:00Z"
            ),
            "2026-11-10": _day(100, coverage_lost_at="2026-11-12T00:00:00Z"),
            "2026-11-11": _day(
                100,
                settled_at="2026-11-15T00:00:00Z",
                coverage_lost_at="2026-11-16T00:00:00Z",
            ),
            "2026-11-18": _day(
                50, counted_at="2026-11-18T11:30:00Z", cutoff="2026-11-18T11:30:00Z"
            ),
        },
        **changes,
    }


class Scheduler:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def request_run(self, name: str) -> str:
        self.requested.append(name)
        return "accepted"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OWNER_TZ_FILE", str(tmp_path / "owner-timezone.json"))
    path = tmp_path / "usage-ledger.json"
    clock = SimpleNamespace(now=NOW)

    def build(ledger: dict | None = None) -> tuple[web.Application, Scheduler]:
        if ledger is not None:
            path.write_text(json.dumps(ledger))
        usage = UsageLedger(
            None,
            None,
            excluded_ips=lambda: [],
            lan_filter=lambda: None,
            path=str(path),
            now=lambda: clock.now,
        )
        cap_file = tmp_path / "cap.json"
        cap_file.write_text(json.dumps({"monthly_cap_bytes": 10_000}))
        with patch("services.bandwidth_tracker._CAP_FILE", str(cap_file)):
            tracker = BandwidthTracker()
        app = web.Application()
        scheduler = Scheduler()
        app["scheduler"] = scheduler
        register_usage_routes(app, usage)
        register_bandwidth_routes(app, tracker)
        return app, scheduler

    return SimpleNamespace(build=build, clock=clock)


def _calls(app: web.Application, *requests: tuple) -> list[tuple[int, dict]]:
    """(status, body) of each (method, path[, json]) request, in order, on one server."""

    async def go():
        out = []
        async with TestClient(TestServer(app)) as client:
            for method, path, *body in requests:
                kw = {"json": body[0]} if body else {}
                resp = await client.request(method, path, **kw)
                out.append((resp.status, await resp.json()))
        return out

    return asyncio.run(go())


def _call(app: web.Application, method: str, path: str) -> tuple[int, dict]:
    return _calls(app, (method, path))[0]


def test_each_day_gets_the_first_status_that_applies(env):
    app, _ = env.build(_ledger_file())
    status, body = _call(app, "GET", "/api/usage/daily?from=2026-11-01&to=2026-11-20")
    assert status == 200, body
    got = {d["date"][-2:]: d["status"] for d in body["days"]}
    assert got == {
        "01": "not_counted",  # before since
        "02": "not_counted",
        "03": "counted",
        "04": "counted",
        "05": "not_counted",  # a gap
        "06": "stale",  # its last recount failed
        "07": "pending",
        "08": "recount_pending",  # older rules, nothing lost
        "09": "old_rules",  # older rules and lost coverage: can't be recounted
        "10": "approximate",
        "11": "counted",  # it settled before the loss
        "12": "counted",
        "13": "counted",
        "14": "counted",
        "15": "counted",
        "16": "counted",
        "17": "counted",
        "18": "counted",
        "19": "future",
        "20": "future",
    }
    days = {d["date"][-2:]: d for d in body["days"]}
    assert days["19"]["total"] is None and days["07"]["total"] is None
    assert days["03"] == {
        "date": "2026-11-03",
        "start": "2026-11-03T00:00:00Z",
        "end": "2026-11-04T00:00:00Z",
        "cutoff": "2026-11-18T00:00:00Z",
        "total": 100,
        "download": 90,
        "upload": 10,
        "local": 3,
        "status": "counted",
        "counted_at": "2026-11-18T11:30:00Z",
    }
    # every day with figures: 03, 04, 06 and 08–17 (13 days at 100), and today's 50
    assert body["bytes"]["total"] == 13 * 100 + 50
    assert body["bytes"]["local"] == 14 * 3  # beside the total, never in it
    assert not body["complete"]
    assert {g["date"][-2:] for g in body["gaps"]} == {
        "01",
        "02",
        "05",
        "06",
        "07",
        "08",
        "09",
        "10",
    }
    assert (body["tz"], body["pending_tz"], body["since"], body["generation"]) == (
        "UTC",
        None,
        "2026-11-03",
        1,
    )


def test_today_without_a_recount_in_45_minutes_is_stale(env):
    app, _ = env.build(_ledger_file())
    env.clock.now = NOW + timedelta(minutes=16)  # 46 min after its last recount
    _, body = _call(app, "GET", "/api/usage/daily?from=2026-11-18&to=2026-11-18")
    assert body["days"][0]["status"] == "stale"


def test_the_month_has_its_bounds_projection_and_sweep(env):
    days = {f"2026-11-{n:02d}": _day(100) for n in range(1, 18)}
    today = _day(50, cutoff="2026-11-18T12:00:00Z")
    app, _ = env.build(
        _ledger_file(since="2026-11-01", gaps=[], days={**days, "2026-11-18": today})
    )
    status, body = _call(app, "GET", "/api/usage/month")
    assert status == 200, body
    assert (body["year"], body["month"]) == (2026, 11)
    assert body["month_start"] == "2026-11-01T00:00:00+00:00"
    assert body["month_end"] == "2026-12-01T00:00:00+00:00"
    assert len(body["days"]) == 30 and body["complete"]
    total = 17 * 100 + 50
    elapsed = 17.5 * 86400
    assert body["bytes"]["total"] == total
    assert body["daily_rate"] == int(total / elapsed * 86400)
    assert body["projected"] == int(total / elapsed * 30 * 86400)
    assert body["days_remaining"] == 12.5
    assert body["sweep"] == {
        "id": 4,
        "cursor": None,
        "chunks_done": 3,
        "chunks_failed": 0,
        "finished_at": "2026-11-18T03:05:00Z",
    }


def test_a_month_with_an_old_rules_day_or_a_past_month_has_no_projection(env):
    app, _ = env.build(_ledger_file())
    (_, body), (_, past) = _calls(
        app, ("GET", "/api/usage/month"), ("GET", "/api/usage/month?year=2026&month=10")
    )
    assert (body["projected"], body["daily_rate"], body["days_remaining"]) == (
        None,
        None,
        None,
    )
    body = past
    assert body["projected"] is None and body["month"] == 10
    assert {d["status"] for d in body["days"]} == {"not_counted"}


def test_the_month_is_in_the_ledgers_zone_and_says_when_a_new_one_is_pending(env):
    app, _ = env.build(_ledger_file(tz="America/Los_Angeles", days={}))
    owner_tz.write("Europe/Berlin")
    env.clock.now = datetime(
        2026, 12, 1, 1, 0, tzinfo=timezone.utc
    )  # Nov 30, 17:00 in LA
    _, body = _call(app, "GET", "/api/usage/month")
    assert (body["year"], body["month"]) == (2026, 11)
    assert body["month_start"] == "2026-11-01T00:00:00-07:00"
    assert body["month_end"] == "2026-12-01T00:00:00-08:00"
    assert (body["tz"], body["pending_tz"]) == ("America/Los_Angeles", "Europe/Berlin")


def test_with_no_ledger_yet_every_day_so_far_is_pending(env):
    app, _ = env.build()
    (status, body), (_, month) = _calls(
        app,
        ("GET", "/api/usage/daily?from=2026-11-17&to=2026-11-19"),
        ("GET", "/api/usage/month"),
    )
    assert status == 200
    assert [d["status"] for d in body["days"]] == ["pending", "pending", "future"]
    assert (body["since"], body["generation"], body["bytes"]["total"]) == (None, 0, 0)
    body = month
    assert body["sweep"]["id"] == 0 and body["projected"] is None


@pytest.mark.parametrize(
    "query",
    [
        "from=2026-11-01",
        "from=2026-11-01&to=nope",
        "from=20261101&to=20261102",
        "from=2026-02-30&to=2026-03-01",
        "from=2026-11-10&to=2026-11-01",
        "from=2025-01-01&to=2026-11-01",
        "from=0001-01-01&to=0001-01-02",
    ],
)
def test_a_bad_inverted_or_too_long_range_is_a_400(env, query):
    app, _ = env.build(_ledger_file())
    status, body = _call(app, "GET", f"/api/usage/daily?{query}")
    assert status == 400 and body["error"]


@pytest.mark.parametrize("query", ["month=13", "month=0", "year=abc", "year=1969"])
def test_a_bad_month_is_a_400(env, query):
    app, _ = env.build(_ledger_file())
    status, _ = _call(app, "GET", f"/api/usage/month?{query}")
    assert status == 400


def test_recount_asks_for_a_new_sweep_and_a_run(env):
    app, scheduler = env.build(_ledger_file())
    status, body = _call(app, "POST", "/api/usage/recount")
    assert (status, body) == (202, {"sweep_requested": True, "sweep_id": 4})
    assert scheduler.requested == ["usage-ledger"]
    assert app["usage_ledger"]._take_sweep_request()


def test_the_time_zone_is_utc_until_set_and_a_put_runs_the_ledger(env):
    app, scheduler = env.build(_ledger_file())
    bad = [{"tz": "Mars/Olympus_Mons"}, {"tz": "../etc/passwd"}, {"tz": 5}, []]
    replies = _calls(
        app,
        ("GET", "/api/settings/timezone"),
        *(("PUT", "/api/settings/timezone", b) for b in bad),
        ("PUT", "/api/settings/timezone", {"tz": "America/Los_Angeles"}),
        ("GET", "/api/settings/timezone"),
    )
    assert replies[0] == (200, {"tz": "UTC", "set": False})
    for status, body in replies[1:5]:
        assert (status, body) == (400, {"error": "That isn't a time zone NetTap knows"})
    assert replies[5] == (200, {"tz": "America/Los_Angeles", "set": True})
    assert replies[6] == (200, {"tz": "America/Los_Angeles", "set": True})
    assert scheduler.requested == ["usage-ledger"]  # only the saved one ran the ledger


def test_the_cap_reads_the_ledgers_month(env):
    days = {f"2026-11-{n:02d}": _day(1000) for n in range(1, 18)}
    app, _ = env.build(_ledger_file(since="2026-11-01", gaps=[], days=days))
    status, body = _call(app, "GET", "/api/bandwidth/cap")
    assert status == 200, body
    assert body["current_usage_bytes"] == 17_000  # Internet bytes; local stays out
    assert body["usage_percent"] == 170.0
    assert (body["monthly_cap_bytes"], body["enabled"]) == (10_000, True)
    assert (body["tz"], body["since"], body["complete"]) == ("UTC", "2026-11-01", False)


def test_the_time_zone_put_saves_off_the_request_loop(env, monkeypatch):
    """Review: write_file_atomic's fsync ran on the loop, holding every other request."""
    app, _ = env.build(_ledger_file())
    threads = []
    write = owner_tz.write

    def recording(name):
        threads.append(threading.current_thread())
        return write(name)

    monkeypatch.setattr(owner_tz, "write", recording)
    status, _ = _calls(app, ("PUT", "/api/settings/timezone", {"tz": "Asia/Tokyo"}))[0]
    assert status == 200
    assert threads and threads[0] is not threading.main_thread()  # the loop's thread


def test_an_unreadable_time_zone_file_is_logged_once_per_error(env, tmp_path, caplog):
    """Review: every usage request reads it, so a bad file logged on every page load."""
    for text in ("{not json", '{"tz": "Mars/Olympus_Mons"}'):
        (tmp_path / "owner-timezone.json").write_text(text)
        for _ in range(3):
            assert owner_tz.read() == {"tz": "UTC", "set": False, "ok": False}
    warnings = [r for r in caplog.records if "Ignoring the time zone file" in r.message]
    assert len(warnings) == 2
