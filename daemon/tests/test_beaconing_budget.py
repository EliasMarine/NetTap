"""NET-187: the beaconing scan's faster batch query, its time budget, and the honest replies.

On the G11 a live scan took 15 s for 24 h and 63 s for 7 d, and had no limit: a 30 d window
ended in the web proxy's generic failure. Now the scan stops at its budget, the beaconing route
answers 503 with the reason, and the threat report goes out with beaconing "not checked in time".
"""

import asyncio
import math
import threading
import time
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from aiohttp.test_utils import TestClient, TestServer
from opensearchpy import ConnectionTimeout, OpenSearch

import api.threats as threats
import services.threat_detection as td
from api.drilldown_runner import _SLOW
from storage.all_buckets import all_buckets
from storage.exact_terms import (
    ExactTermsOpenSearch,
    PartialResultsError,
    SearchTimedOut,
)
from storage.snapshot_search import Budget, TooSlow
from tests.fake_opensearch import FakeOpenSearch
from tests.test_beacon_snapshots import _app, _get
from tests.test_threat_detection import _DAY, _T0, _beacon_docs, _conn

_LIVE = "from=2026-01-01T00:00:00Z&to=2026-01-02T00:00:00Z"
_WHOLE = {"_shards": {"total": 1, "successful": 1, "failed": 0}, "timed_out": False}


class _TenSecondSearches(FakeOpenSearch):
    """Each search takes 10 s on a fake clock, so a Budget on `now` runs out on schedule."""

    now = 0.0

    def search(self, *a, **kw):
        self.now += 10
        return super().search(*a, **kw)


def _budget_on(client: _TenSecondSearches, seconds: float) -> Budget:
    return Budget(seconds, clock=lambda: client.now)


# --- the batch query ------------------------------------------------------------------------


def test_one_clause_per_source_and_port_reads_only_the_batch_pairs():
    """A source-and-port clause with its destinations matches exactly the batch's pairs; a query
    on sources x destinations x ports would also match (A, Y, 80) and push a pair out of the list."""
    a, x, y, z = "192.168.1.50", "203.0.113.9", "198.51.100.7", "198.51.100.8"
    docs = (
        [_conn(a, x, 80, _T0 + k * 60_000) for k in range(12)]
        + [_conn(a, z, 80, _T0 + k * 62_000) for k in range(12)]
        + [_conn(a, y, 443, _T0 + k * 60_000) for k in range(12)]
        + [_conn(a, y, 80, _T0 + k * 61_000) for k in range(5)]  # not in the batch
    )
    client = FakeOpenSearch(docs)
    batch = [
        {"key": {"src": a, "dst": x, "port": 80}, "doc_count": 12},
        {"key": {"src": a, "dst": z, "port": 80}, "doc_count": 12},
        {"key": {"src": a, "dst": y, "port": 443}, "doc_count": 12},
    ]

    slots = td._batch_slots(client, [], batch, Budget(60))

    assert sorted(slots) == sorted([f"{a} {x} 80", f"{a} {z} 80", f"{a} {y} 443"])
    assert slots[f"{a} {x} 80"] == [{"key": _T0 + k * 60_000} for k in range(12)]
    clauses = client.bodies[-1]["query"]["bool"]["filter"][-1]["bool"]["should"]
    # (a, 80) with x and z, and (a, 443): one clause per source and port, not one per pair
    assert len(clauses) == 2


def test_slot_keys_come_back_as_whole_milliseconds():
    """OpenSearch answers a numeric histogram's keys as doubles; the gaps are worked out in ints."""
    client = FakeOpenSearch(_beacon_docs("192.168.1.50", 60, 12))
    batch = [
        {
            "key": {"src": "192.168.1.50", "dst": "203.0.113.9", "port": 443},
            "doc_count": 12,
        }
    ]

    (slots,) = td._batch_slots(client, [], batch, Budget(60)).values()

    assert [s["key"] for s in slots] == [_T0 + k * 60_000 for k in range(12)]
    assert all(type(s["key"]) is int for s in slots)


# --- the scan stops at its budget, with nothing partial ---------------------------------------


def test_a_spent_budget_sends_no_search():
    client = _TenSecondSearches(_beacon_docs("192.168.1.50", 60, 20))
    with pytest.raises(TooSlow):
        td.detect_beaconing(client, *_DAY, budget=Budget(0))
    assert client.bodies == []


def test_running_out_after_the_candidate_read_sends_no_batch():
    client = _TenSecondSearches(_beacon_docs("192.168.1.50", 60, 20))
    with pytest.raises(TooSlow):
        td.detect_beaconing(client, *_DAY, budget=_budget_on(client, 5))
    assert len(client.bodies) == 1  # the candidate list only


def test_running_out_while_paging_the_candidates_stops_the_paging(monkeypatch):
    real = td.all_buckets
    monkeypatch.setattr(td, "CANDIDATE_LIST_SIZE", 1)
    monkeypatch.setattr(
        td, "all_buckets", lambda *a, **kw: real(*a, **{**kw, "page_size": 1})
    )
    docs = [d for i in range(5) for d in _beacon_docs(f"192.168.1.{50 + i}", 60, 20)]
    client = _TenSecondSearches(docs)

    with pytest.raises(TooSlow):
        td.detect_beaconing(client, *_DAY, budget=_budget_on(client, 25))

    # the candidate list, then two of the five pages: no search after the deadline
    assert len(client.bodies) == 3
    assert all("composite" in str(b["aggs"]) for b in client.bodies[1:])


def test_running_out_while_paging_a_busy_pair_stops_the_paging(monkeypatch):
    real = td.all_buckets
    monkeypatch.setattr(td, "HISTOGRAM_BUCKETS_PER_REQUEST", 20)
    monkeypatch.setattr(
        td, "all_buckets", lambda *a, **kw: real(*a, **{**kw, "page_size": 1})
    )
    client = _TenSecondSearches(_beacon_docs("192.168.1.50", 60, 30))

    with pytest.raises(TooSlow):
        td.detect_beaconing(client, *_DAY, budget=_budget_on(client, 25))

    assert len(client.bodies) == 3  # the candidate list, then two of 30 pages
    assert "date_histogram" in str(client.bodies[-1]["aggs"])


def test_without_a_budget_the_scan_has_no_time_limit(monkeypatch):
    """The background store passes none: nobody waits for it, and its 30 d scan must finish."""
    real, given = td._scan_beacons, []

    def scan(client, filters, slots, budget):
        given.append(budget)
        return real(client, filters, slots, budget)

    monkeypatch.setattr(td, "_scan_beacons", scan)
    beacons, complete = td.detect_beaconing(
        FakeOpenSearch(_beacon_docs("192.168.1.50", 60, 20)), *_DAY
    )

    assert [b["source_ip"] for b in beacons] == ["192.168.1.50"] and complete
    assert math.isinf(given[0].remaining())


def test_all_buckets_checks_its_budget_before_every_page():
    client = MagicMock()
    page = {
        "aggregations": {
            "all": {"buckets": [{"key": {"ip": "a"}}], "after_key": {"ip": "a"}}
        }
    }
    now = [0.0]

    def search(**_):
        now[0] += 10
        return page

    client.search.side_effect = search
    with pytest.raises(TooSlow):
        all_buckets(
            client,
            "x-*",
            {"match_all": {}},
            [{"ip": {"terms": {"field": "source.ip"}}}],
            page_size=1,
            budget=Budget(25, clock=lambda: now[0]),
        )
    assert client.search.call_count == 3
    # the daemon's client caps each page's wait at what is left
    assert all(
        isinstance(c.kwargs["budget"], Budget) for c in client.search.call_args_list
    )


# --- a search that took too long reads as "took too long" -------------------------------------


def test_a_search_the_client_gave_up_on_is_too_slow():
    client = MagicMock()
    client.search.side_effect = ConnectionTimeout("TIMEOUT", "read timed out", None)
    with pytest.raises(TooSlow):
        td.detect_beaconing(client, *_DAY, budget=Budget(60))


def _exact_client(reply: dict):
    """The daemon's real client class, its parent's search answering `reply`."""
    client = ExactTermsOpenSearch(hosts=[{"host": "localhost", "port": 9200}])
    return client, patch.object(OpenSearch, "search", return_value=reply)


def test_a_search_opensearch_timed_out_is_too_slow_through_the_real_client():
    client, answering = _exact_client({**_WHOLE, "timed_out": True})
    with answering, pytest.raises(TooSlow) as caught:
        td.detect_beaconing(client, *_DAY, budget=Budget(60))
    assert isinstance(caught.value.__cause__, SearchTimedOut)


def test_failed_shards_stay_a_failure_not_a_time_out():
    client, answering = _exact_client(
        {**_WHOLE, "_shards": {"total": 2, "successful": 1, "failed": 1}}
    )
    with answering, pytest.raises(PartialResultsError) as caught:
        td.detect_beaconing(client, *_DAY, budget=Budget(60))
    assert not isinstance(caught.value, SearchTimedOut)


# --- the threat report: beaconing "not checked in time", every other section kept -------------


def _report_with(**patches):
    from services.investigation import generate_threat_report

    defaults = {
        "services.alert_intelligence.get_smart_alert_summary": MagicMock(
            return_value={"threat_score": 7}
        ),
        "services.alert_intelligence.get_smart_alerts": MagicMock(return_value=[]),
        "services.threat_detection.detect_lateral_movement": MagicMock(
            return_value=([{"source_ip": "192.168.1.66"}], True)
        ),
        "services.threat_detection.analyze_dns_anomalies": MagicMock(
            return_value={"dga_suspects": [{"domain": "x"}], "complete": True}
        ),
        **patches,
    }
    with ExitStack() as stack:
        for target, value in defaults.items():
            stack.enter_context(patch(target, value))
        return asyncio.run(
            generate_threat_report(MagicMock(), "a", "b", budget=Budget(0.3))
        )


def test_the_report_marks_beaconing_not_checked_in_time_and_keeps_the_rest():
    report = _report_with(
        **{
            "services.threat_detection.detect_beaconing": MagicMock(
                side_effect=TooSlow("the beaconing scan took too long")
            )
        }
    )
    assert report["failed_checks"] == ["beaconing"]
    assert report["timed_out_checks"] == ["beaconing"]
    assert report["summary"] == {"threat_score": 7}
    assert report["lateral_movement"] == [{"source_ip": "192.168.1.66"}]
    assert report["dns_anomalies"]["dga_suspects"] == [{"domain": "x"}]


def test_another_failure_is_not_called_a_time_out():
    report = _report_with(
        **{
            "services.threat_detection.detect_beaconing": MagicMock(
                side_effect=ConnectionError("down")
            )
        }
    )
    assert report["failed_checks"] == ["beaconing"]
    assert report["timed_out_checks"] == []


def test_a_failed_alert_summary_does_not_wait_for_beaconing():
    """Review fix: the report waited up to the budget for a scan nobody would read."""
    from services.investigation import generate_threat_report

    release, calls = threading.Event(), []
    started = time.monotonic()
    try:
        with (
            patch(
                "services.alert_intelligence.get_smart_alert_summary",
                MagicMock(side_effect=ConnectionError("down")),
            ),
            patch(
                "services.threat_detection.detect_lateral_movement",
                MagicMock(return_value=([], True)),
            ),
            patch(
                "services.threat_detection.analyze_dns_anomalies",
                MagicMock(return_value={"complete": True}),
            ),
            patch(
                "services.threat_detection.detect_beaconing",
                _blocked_scan(release, calls),
            ),
            pytest.raises(ConnectionError),
        ):
            asyncio.run(
                generate_threat_report(MagicMock(), "a", "b", budget=Budget(60))
            )
    finally:
        release.set()
        _wait_for_free_beacon_threads()
    assert time.monotonic() - started < 3


# --- the routes -----------------------------------------------------------------------------


def _blocked_scan(release: threading.Event, calls: list):
    def scan(*_a, **_kw):
        calls.append(time.monotonic())
        release.wait(10)
        return [], True

    return scan


def _wait_for_free_beacon_threads():
    """A released scan ends a moment later; wait until every beacon thread and slot is free."""
    for _ in range(500):
        got = [
            threats._LIVE_SCANS.acquire(blocking=False)
            for _ in range(td.BEACON_THREADS)
        ]
        for held in got:
            if held:
                threats._LIVE_SCANS.release()
        idle = [td.BEACON_POOL.submit(time.sleep, 0) for _ in range(td.BEACON_THREADS)]
        if all(got) and all(f.result(5) is None for f in idle):
            return
        time.sleep(0.01)
    raise AssertionError("the beacon threads stayed busy")


def test_the_beaconing_route_answers_503_with_the_reason(monkeypatch):
    app = _app(MagicMock(), "0", monkeypatch)
    with patch(
        "services.threat_detection.detect_beaconing",
        side_effect=TooSlow("x took too long"),
    ):
        status, body = _get(app, f"/api/threats/beaconing?{_LIVE}")
    assert (status, body) == (503, {"error": _SLOW})


def test_the_beaconing_route_answers_at_its_deadline_while_the_scan_hangs(monkeypatch):
    monkeypatch.setattr("api.threats.BEACON_BUDGET_SECONDS", 0.2)
    app = _app(MagicMock(), "0", monkeypatch)
    release, calls = threading.Event(), []
    started = time.monotonic()
    try:
        with patch(
            "services.threat_detection.detect_beaconing", _blocked_scan(release, calls)
        ):
            status, body = _get(app, f"/api/threats/beaconing?{_LIVE}")
    finally:
        release.set()
        _wait_for_free_beacon_threads()
    assert (status, body) == (503, {"error": _SLOW})
    assert time.monotonic() - started < 2
    assert len(calls) == 1


def test_a_scan_still_queued_at_the_deadline_never_starts(monkeypatch):
    """The report's scans hold both beacon threads; the route's scan waits, and is dropped."""
    monkeypatch.setattr("api.threats.BEACON_BUDGET_SECONDS", 0.2)
    busy = threading.Event()
    for _ in range(td.BEACON_THREADS):
        td.BEACON_POOL.submit(busy.wait, 10)
    calls: list = []
    try:
        with patch(
            "services.threat_detection.detect_beaconing",
            lambda *a, **kw: calls.append(1),
        ):
            status, body = _get(
                _app(MagicMock(), "0", monkeypatch), f"/api/threats/beaconing?{_LIVE}"
            )
    finally:
        busy.set()
        _wait_for_free_beacon_threads()  # also proves the dropped scan gave its slot back
    assert (status, body) == (503, {"error": _SLOW})
    assert calls == []


def test_a_request_beyond_the_beacon_threads_is_turned_away_at_once(monkeypatch):
    """Review fix: on the shared route pool, eight 30-day scans left Home no thread."""
    release, calls = threading.Event(), []
    blocked = _blocked_scan(release, calls)

    async def run():
        client = TestClient(TestServer(_app(MagicMock(), "0", monkeypatch)))
        await client.start_server()
        try:
            running = [
                asyncio.ensure_future(client.get(f"/api/threats/beaconing?{_LIVE}"))
                for _ in range(td.BEACON_THREADS)
            ]
            for _ in range(500):  # both scans have started
                if len(calls) == td.BEACON_THREADS:
                    break
                await asyncio.sleep(0.01)
            started = time.monotonic()
            extra = await client.get(f"/api/threats/beaconing?{_LIVE}")
            turned_away = (extra.status, await extra.json(), time.monotonic() - started)
            release.set()
            finished = [(await r).status for r in running]
            return turned_away, finished
        finally:
            await client.close()

    try:
        with patch("services.threat_detection.detect_beaconing", blocked):
            (status, body, took), finished = asyncio.run(run())
    finally:
        release.set()
        _wait_for_free_beacon_threads()
    assert (status, body) == (503, {"error": threats._SCANS_BUSY})
    assert took < 1
    assert len(calls) == td.BEACON_THREADS  # the extra request started no scan
    assert finished == [200] * td.BEACON_THREADS


def test_the_report_route_sends_the_other_sections_when_beaconing_runs_out(monkeypatch):
    monkeypatch.setattr("api.threats.BEACON_BUDGET_SECONDS", 0.3)
    app = _app(MagicMock(), "0", monkeypatch)
    release, calls = threading.Event(), []
    started = time.monotonic()
    try:
        with (
            patch(
                "services.alert_intelligence.get_smart_alert_summary",
                MagicMock(return_value={"threat_score": 7}),
            ),
            patch(
                "services.alert_intelligence.get_smart_alerts",
                MagicMock(return_value=[]),
            ),
            patch(
                "services.threat_detection.detect_lateral_movement",
                MagicMock(return_value=([{"source_ip": "192.168.1.66"}], True)),
            ),
            patch(
                "services.threat_detection.analyze_dns_anomalies",
                MagicMock(
                    return_value={"dga_suspects": [{"domain": "x"}], "complete": True}
                ),
            ),
            patch(
                "services.threat_detection.detect_beaconing",
                _blocked_scan(release, calls),
            ),
        ):
            status, body = _get(app, f"/api/threats/report?{_LIVE}")
    finally:
        release.set()
        _wait_for_free_beacon_threads()
    assert status == 200
    assert time.monotonic() - started < 3
    assert body["failed_checks"] == body["timed_out_checks"] == ["beaconing"]
    assert body["summary"] == {"threat_score": 7}
    assert body["lateral_movement"] == [{"source_ip": "192.168.1.66"}]
    assert body["dns_anomalies"]["dga_suspects"] == [{"domain": "x"}]


def test_the_report_route_has_a_backstop(monkeypatch):
    monkeypatch.setattr("api.threats.REPORT_WAIT_SECONDS", 0.2)
    app = _app(MagicMock(), "0", monkeypatch)
    release = threading.Event()

    async def hung(*_a, **_kw):
        release.wait(10)  # a section without a budget that hangs
        return {}

    try:
        with patch("services.investigation.generate_threat_report", hung):
            status, body = _get(app, f"/api/threats/report?{_LIVE}")
    finally:
        release.set()
    assert (status, body) == (503, {"error": _SLOW})


def test_a_search_opensearch_timed_out_gives_the_honest_replies(monkeypatch):
    client, answering = _exact_client({**_WHOLE, "timed_out": True})
    with (
        answering,
        patch(
            "services.alert_intelligence.get_smart_alert_summary",
            MagicMock(return_value={}),
        ),
        patch(
            "services.alert_intelligence.get_smart_alerts", MagicMock(return_value=[])
        ),
        patch(
            "services.threat_detection.detect_lateral_movement",
            MagicMock(return_value=([], True)),
        ),
        patch(
            "services.threat_detection.analyze_dns_anomalies",
            MagicMock(return_value={"complete": True}),
        ),
    ):
        beaconing = _get(
            _app(client, "0", monkeypatch), f"/api/threats/beaconing?{_LIVE}"
        )
        status, report = _get(
            _app(client, "0", monkeypatch), f"/api/threats/report?{_LIVE}"
        )
    assert beaconing == (503, {"error": _SLOW})
    assert status == 200
    assert report["timed_out_checks"] == ["beaconing"]
