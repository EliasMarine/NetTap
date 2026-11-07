"""NET-192 PR 3: beaconing for the Threats page's 24h/7d/30d pills, refreshed in the background."""

import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from api.threats import register_threat_routes
from services import beacon_snapshots
from services.beacon_snapshots import CAP_HIT, QUERY_FAILED, BeaconSnapshots
from storage.manager import RetentionConfig, StorageManager

T0 = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
ROW = {
    "source_ip": "192.168.1.188",
    "destination_ip": "188.166.201.72",
    "confidence": 100,
}
OLD_ROW = {**ROW, "confidence": 70}


class Clock:
    def __init__(self) -> None:
        self.at = T0

    def __call__(self) -> datetime:
        return self.at


def _store(*replies):
    """A store whose scan answers `replies` in turn; an Exception instance is raised."""
    clock = Clock()
    calls = []

    def scan(from_ts, to_ts):
        calls.append((from_ts, to_ts))
        reply = replies[min(len(calls), len(replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply

    return BeaconSnapshots(scan, now=clock), clock, calls


def _refresh(store, window="7d"):
    asyncio.run(store.refresh(window))


# --- the state contract -------------------------------------------------------------------


def test_pending_until_the_first_run_ends():
    store, _, _ = _store(([ROW], True))
    snap = store.snapshot("7d")
    assert snap == {
        "window": "7d",
        "state": "pending",
        "computed_at": None,
        "last_success_at": None,
        "last_error": None,
        "from": None,
        "to": None,
    }
    assert store.beacons("7d") == []


def test_ready_after_a_complete_scan_then_stale_when_old():
    store, clock, calls = _store(([ROW], True))
    _refresh(store, "7d")
    snap = store.snapshot("7d")
    assert snap["state"] == "ready"
    assert store.beacons("7d") == [ROW]
    # the window scanned is the last 7 days up to the run
    assert calls == [((T0 - timedelta(days=7)).isoformat(), T0.isoformat())]
    assert (snap["from"], snap["to"]) == calls[0]
    assert snap["computed_at"] == snap["last_success_at"] == T0.isoformat()
    assert snap["last_error"] is None

    clock.at = T0 + timedelta(minutes=30)  # 2 x 15 min: still ready
    assert store.snapshot("7d")["state"] == "ready"
    clock.at = T0 + timedelta(minutes=31)
    assert store.snapshot("7d")["state"] == "stale"
    assert store.beacons("7d") == [ROW]


def test_thirty_days_is_ready_for_two_hours():
    store, clock, _ = _store(([], True))
    _refresh(store, "30d")
    clock.at = T0 + timedelta(minutes=120)
    assert store.snapshot("30d")["state"] == "ready"
    clock.at = T0 + timedelta(minutes=121)
    assert store.snapshot("30d")["state"] == "stale"


def test_failed_when_the_first_run_fails():
    store, _, _ = _store(RuntimeError("OpenSearch down"))
    _refresh(store)
    snap = store.snapshot("7d")
    assert snap["state"] == "failed"
    assert snap["last_error"] == QUERY_FAILED
    assert snap["computed_at"] == T0.isoformat() and snap["last_success_at"] is None
    assert store.beacons("7d") == []


def test_a_failed_refresh_keeps_the_last_good_rows_as_stale():
    store, clock, _ = _store(([OLD_ROW], True), RuntimeError("timeout"))
    _refresh(store)
    clock.at = T0 + timedelta(minutes=15)
    _refresh(store)
    snap = store.snapshot("7d")
    assert snap["state"] == "stale"
    assert snap["last_error"] == QUERY_FAILED
    assert snap["last_success_at"] == T0.isoformat()
    assert snap["computed_at"] == clock.at.isoformat()
    assert store.beacons("7d") == [OLD_ROW]


def test_a_later_success_is_ready_again():
    store, clock, _ = _store(RuntimeError("timeout"), ([ROW], True))
    _refresh(store)
    clock.at = T0 + timedelta(minutes=15)
    _refresh(store)
    assert store.snapshot("7d")["state"] == "ready"
    assert store.snapshot("7d")["last_error"] is None


# --- a partial scan is never published ------------------------------------------------------


def test_a_partial_scan_after_a_good_one_keeps_the_old_rows():
    store, clock, _ = _store(([OLD_ROW], True), ([ROW], False))
    _refresh(store)
    clock.at = T0 + timedelta(minutes=15)
    _refresh(store)
    snap = store.snapshot("7d")
    assert snap["state"] == "stale"
    assert snap["last_error"] == CAP_HIT
    assert store.beacons("7d") == [OLD_ROW]


def test_a_partial_first_scan_is_failed_not_ready():
    store, _, _ = _store(([ROW], False))
    _refresh(store)
    assert store.snapshot("7d")["state"] == "failed"
    assert store.snapshot("7d")["last_error"] == CAP_HIT
    assert store.beacons("7d") == []


def test_a_partial_scan_with_no_findings_is_not_a_clean_empty_result():
    store, _, _ = _store(([], False))
    _refresh(store)
    assert store.snapshot("7d")["state"] == "failed"


# --- the task --------------------------------------------------------------------------------


def test_runs_one_scan_at_a_time_24h_first(monkeypatch):
    monkeypatch.setattr(
        beacon_snapshots, "INTERVALS_S", {"24h": 0.02, "7d": 0.02, "30d": 0.05}
    )
    lock = threading.Lock()
    running, most, order = [0], [0], []

    def scan(from_ts, to_ts):
        with lock:
            running[0] += 1
            most[0] = max(most[0], running[0])
            span = datetime.fromisoformat(to_ts) - datetime.fromisoformat(from_ts)
            order.append(span.days)
        time.sleep(0.01)
        with lock:
            running[0] -= 1
        return [], True

    async def run():
        store = BeaconSnapshots(scan)
        store.start()
        await asyncio.sleep(0.3)
        await store.stop()

    asyncio.run(run())
    assert most[0] == 1
    assert order[:3] == [1, 7, 30]
    assert len(order) > 6  # it kept refreshing


def _app(client, background: str, monkeypatch, run_task=False) -> web.Application:
    """The threat routes on `client`; route tests keep the background task from scanning."""
    monkeypatch.setenv("NETTAP_BEACON_BACKGROUND", background)
    if not run_task:
        monkeypatch.setattr(BeaconSnapshots, "start", lambda self: None)
    with patch.object(StorageManager, "_create_client", return_value=client):
        storage = StorageManager(RetentionConfig(), "http://os:9200")
    app = web.Application()
    app["storage"] = storage
    register_threat_routes(app, storage)
    return app


def test_the_task_starts_with_the_app_and_stops_on_cleanup(monkeypatch):
    scans = []

    def detect(client, from_ts, to_ts, excluded_ips=None):
        scans.append(from_ts)
        return [ROW], True

    monkeypatch.setattr("services.threat_detection.detect_beaconing", detect)

    async def run():
        client = TestClient(
            TestServer(_app(MagicMock(), "1", monkeypatch, run_task=True))
        )
        await client.start_server()
        try:
            for _ in range(100):  # the three windows' first runs
                if len(scans) >= 3:
                    break
                await asyncio.sleep(0.01)
            task = next(
                t for t in asyncio.all_tasks() if t.get_name() == "beacon-snapshots"
            )
            resp = await client.get("/api/threats/beaconing?snapshot=24h")
            body = await resp.json()
        finally:
            await client.close()
        return body, task.done()

    body, stopped = asyncio.run(run())
    assert stopped
    assert body["beaconing_snapshot"]["state"] == "ready"
    assert body["beacons"] == [ROW] and body["complete"] is True
    assert len(scans) == 3


# --- the routes ------------------------------------------------------------------------------


def _get(app, path):
    async def run():
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(path)
            return resp.status, await resp.json()

    return asyncio.run(run())


@pytest.mark.parametrize("route", ["/api/threats/report", "/api/threats/beaconing"])
@pytest.mark.parametrize("value", ["1h", "6h", "90d", "7D", "all"])
def test_an_unknown_snapshot_is_a_400(monkeypatch, route, value):
    app = _app(MagicMock(), "0", monkeypatch)
    status, body = _get(app, f"{route}?snapshot={value}")
    assert status == 400
    assert "snapshot must be one of 24h, 7d, 30d" in body["error"]


@pytest.mark.parametrize("window", ["24h", "7d", "30d"])
def test_each_snapshot_window_reads_its_own_snapshot(monkeypatch, window):
    app = _app(MagicMock(), "1", monkeypatch)
    status, body = _get(app, f"/api/threats/beaconing?snapshot={window}")
    assert status == 200
    assert body["beaconing_snapshot"]["window"] == window
    assert body["beaconing_snapshot"]["state"] == "pending"
    assert body["beacons"] == [] and body["complete"] is False


def _with_rows(app, window="7d"):
    """The app's store, with one complete scan published for `window`."""
    store = app["beacon_snapshots"]
    store._scan = lambda f, t: ([ROW], True)
    asyncio.run(store.refresh(window))
    return store


def test_the_report_takes_beaconing_from_the_snapshot(monkeypatch):
    app = _app(MagicMock(), "1", monkeypatch)
    _with_rows(app)
    seen = {}

    async def report(client, from_ts, to_ts, excluded_ips=None, beaconing=None):
        seen.update(beaconing=beaconing, span=_span(from_ts, to_ts))
        return {"beaconing": beaconing}

    with patch("services.investigation.generate_threat_report", report):
        status, body = _get(app, "/api/threats/report?snapshot=7d")
    assert status == 200
    assert seen["beaconing"] == [ROW]
    assert seen["span"] == pytest.approx(
        7 * 86400, abs=5
    )  # the other checks: the last 7 days
    assert body["beaconing_snapshot"]["state"] == "ready"


@pytest.mark.parametrize("route", ["/api/threats/report", "/api/threats/beaconing"])
def test_an_explicit_window_is_always_live(monkeypatch, route):
    app = _app(MagicMock(), "1", monkeypatch)
    _with_rows(app)
    seen = {}

    async def report(client, from_ts, to_ts, excluded_ips=None, beaconing=None):
        seen.update(beaconing=beaconing, live=True)
        return {"beaconing": []}

    def detect(client, from_ts, to_ts, excluded_ips=None):
        seen.update(live=True)
        return [], True

    window = "from=2026-11-01T00:00:00Z&to=2026-11-02T00:00:00Z"
    with (
        patch("services.investigation.generate_threat_report", report),
        patch("services.threat_detection.detect_beaconing", detect),
    ):
        status, body = _get(app, f"{route}?snapshot=7d&{window}")
    assert status == 200
    assert seen["live"] and seen.get("beaconing") is None
    assert "beaconing_snapshot" not in body
    assert body["from"] == "2026-11-01T00:00:00Z"


def test_with_the_background_off_a_snapshot_request_runs_live(monkeypatch):
    app = _app(MagicMock(), "0", monkeypatch)
    assert "beacon_snapshots" not in app
    seen = {}

    async def report(client, from_ts, to_ts, excluded_ips=None, beaconing=None):
        seen.update(beaconing=beaconing, span=_span(from_ts, to_ts))
        return {"beaconing": []}

    with patch("services.investigation.generate_threat_report", report):
        status, body = _get(app, "/api/threats/report?snapshot=30d")
    assert status == 200
    assert seen["beaconing"] is None  # the check runs live, as before
    assert seen["span"] == pytest.approx(30 * 86400, abs=5)
    assert "beaconing_snapshot" not in body


def test_the_report_skips_the_live_check_when_given_snapshot_rows():
    from services.investigation import generate_threat_report

    def must_not_run(*_a, **_k):
        raise AssertionError("the live beaconing check ran")

    with (
        patch("services.threat_detection.detect_beaconing", must_not_run),
        patch(
            "services.threat_detection.detect_lateral_movement", return_value=([], True)
        ),
        patch(
            "services.threat_detection.analyze_dns_anomalies",
            return_value={"complete": True},
        ),
        patch("services.alert_intelligence.get_smart_alert_summary", return_value={}),
        patch("services.alert_intelligence.get_smart_alerts", return_value=[]),
    ):
        report = asyncio.run(
            generate_threat_report(MagicMock(), "a", "b", beaconing=[ROW])
        )
    assert report["beaconing"] == [ROW]
    assert report["failed_checks"] == [] and report["incomplete_checks"] == []


def _span(from_ts: str, to_ts: str) -> float:
    parse = lambda ts: datetime.fromisoformat(ts.replace("Z", "+00:00"))  # noqa: E731
    return (parse(to_ts) - parse(from_ts)).total_seconds()
