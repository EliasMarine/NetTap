"""F2: health is a problem when the sensors stop or no new data arrives (release audit 2026-11)."""

import asyncio
import json
import threading
import time
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from api.server import handle_system_health
from services import pipeline_health
from services.pipeline_health import SENSORS, PipelineHealth, parse_inspect

DAY = 86400
ALL_RUNNING = "".join(f"/{name} running\n" for name in SENSORS)


def _ms(seconds_ago: float) -> float:
    return (time.time() - seconds_ago) * 1000


def zeek(ingested_ago: float, started_ago: float | None = None) -> dict:
    started = ingested_ago if started_ago is None else started_ago
    return {
        "event.provider": "zeek",
        "event.ingested": _ms(ingested_ago),
        "@timestamp": _ms(started),
    }


class FakeSearch:
    """Answers the freshness search over `docs` as OpenSearch would: the range filter and the max
    aggregation read whichever fields the query names, so a query on the wrong field gets the
    wrong answer."""

    def __init__(
        self,
        docs=(),
        error: Exception | None = None,
        gate: threading.Event | None = None,
    ):
        self.docs, self.error, self.gate, self.calls = list(docs), error, gate, 0

    def search(self, index, body):
        self.calls += 1
        if self.gate:
            self.gate.wait(10)
        if self.error:
            raise self.error
        filters = body["query"]["bool"]["filter"]
        provider = next(f["term"]["event.provider"] for f in filters if "term" in f)
        ((field, rng),) = next(f["range"] for f in filters if "range" in f).items()
        assert rng == {"gte": "now-7d"}
        agg = body["aggs"]["newest"]["max"]["field"]
        hits = [
            d
            for d in self.docs
            if d["event.provider"] == provider and d[field] >= _ms(7 * DAY)
        ]
        return {
            "aggregations": {
                "newest": {"value": max((d[agg] for d in hits), default=None)}
            }
        }


@pytest.fixture
def inspect_prints(monkeypatch):
    """Make the docker inspect a real child that prints `stdout`/`stderr` and exits `rc`."""

    def set_output(stdout: str = ALL_RUNNING, stderr: str = "", rc: int = 0):
        script = 'printf "%s" "$1"; printf "%s" "$2" >&2; exit "$3"'
        monkeypatch.setattr(
            pipeline_health,
            "INSPECT_CMD",
            ["sh", "-c", script, "_", stdout, stderr, str(rc)],
        )

    set_output()
    return set_output


@pytest.fixture
def children(monkeypatch):
    """Every child process the probe starts."""
    procs = []
    real = asyncio.create_subprocess_exec

    async def spy(*args, **kwargs):
        proc = await real(*args, **kwargs)
        procs.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    return procs


def probe(client, up: float = 3600) -> dict:
    return asyncio.run(PipelineHealth(client, time.monotonic() - up).get())


def _app(client, up: float = 3600) -> web.Application:
    app = web.Application()
    app["start_time"] = 0.0
    app["storage"] = MagicMock()
    app["storage"].get_status.return_value = {"disk_usage_percent": 10.0}
    app["smart"] = MagicMock()
    app["smart"].get_status.return_value = {"healthy": True}
    app["pipeline_health"] = PipelineHealth(client, time.monotonic() - up)
    return app


async def _call(app) -> dict:
    resp = await handle_system_health(
        make_mocked_request("GET", "/api/system/health", app=app)
    )
    return json.loads(resp.body)


def health(client, up: float = 3600) -> dict:
    return asyncio.run(_call(_app(client, up)))


# --- the overall health -------------------------------------------------------------------


def test_stale_data_makes_health_a_problem(inspect_prints):
    """Fails before F2: storage, SMART and OpenSearch fine read "healthy" with nothing new for 47 min."""
    body = health(FakeSearch([zeek(47 * 60)]))
    assert body["status"] == "problem"
    assert body["pipeline"]["state"] == "stale"
    assert 47 * 60 - 5 <= body["pipeline"]["age_seconds"] <= 47 * 60 + 5


def test_fresh_data_keeps_health_healthy(inspect_prints):
    body = health(FakeSearch([zeek(40)]))
    assert body["status"] == "healthy"
    p = body["pipeline"]
    assert p["state"] == "fresh"
    assert 38 <= p["age_seconds"] <= 45
    assert p["threshold_seconds"] == 900
    assert p["sensors"] == dict.fromkeys(SENSORS, "running")
    assert p["newest_record_at"] and p["checked_at"]


@pytest.mark.parametrize(
    ("docs", "up", "state", "status"),
    [
        ([], 3600, "no_data", "problem"),  # empty after the startup grace
        ([], 60, "starting", "incomplete"),  # empty during the grace
    ],
)
def test_no_records(inspect_prints, docs, up, state, status):
    body = health(FakeSearch(docs), up=up)
    assert (body["pipeline"]["state"], body["status"]) == (state, status)
    assert body["pipeline"]["age_seconds"] is None


def test_a_stopped_sensor_is_a_problem(inspect_prints):
    inspect_prints(
        ALL_RUNNING.replace(
            "nettap-suricata-live running", "nettap-suricata-live exited"
        )
    )
    body = health(FakeSearch([zeek(40)]))
    assert (body["pipeline"]["state"], body["status"]) == ("sensor_stopped", "problem")
    assert body["pipeline"]["sensors"]["nettap-suricata-live"] == "exited"


def test_a_search_error_is_incomplete(inspect_prints):
    body = health(FakeSearch(error=ConnectionError("refused")))
    assert (body["pipeline"]["state"], body["status"]) == ("unknown", "incomplete")


def test_a_slow_search_answers_within_the_budget(inspect_prints, monkeypatch):
    monkeypatch.setattr(pipeline_health, "BUDGET_S", 0.5)
    gate = threading.Event()
    try:
        started = time.monotonic()
        body = health(FakeSearch([zeek(40)], gate=gate))
        assert time.monotonic() - started < 2
    finally:
        gate.set()
    assert (body["pipeline"]["state"], body["status"]) == ("unknown", "incomplete")
    assert body["pipeline"]["sensors"] == dict.fromkeys(SENSORS, "running")


def test_twenty_concurrent_calls_share_one_probe(inspect_prints, children):
    client = FakeSearch([zeek(40)])
    app = _app(client)

    async def main():
        bodies = await asyncio.gather(*(_call(app) for _ in range(20)))
        again = await _call(app)  # within 30 s: the cached answer
        return bodies, again

    bodies, again = asyncio.run(main())
    assert {b["pipeline"]["state"] for b in bodies} == {"fresh"}
    assert again["pipeline"] == bodies[0]["pipeline"]
    assert (client.calls, len(children)) == (1, 1)


def test_a_busy_route_pool_does_not_make_it_unknown(inspect_prints, monkeypatch):
    # Review: on the shared route pool the search queued behind a cold page load ate the budget
    from api import offload

    monkeypatch.setattr(pipeline_health, "BUDGET_S", 0.5)
    hold = threading.Event()
    busy = [offload._POOL.submit(hold.wait, 10) for _ in range(offload._POOL._max_workers)]
    try:
        result = probe(FakeSearch([zeek(40)]))
    finally:
        hold.set()
        for job in busy:
            job.result(10)
    assert result["state"] == "fresh"


def test_unknown_is_checked_again_sooner_than_a_real_answer(inspect_prints, monkeypatch):
    client = FakeSearch(error=ConnectionError("refused"))
    probe = PipelineHealth(client, time.monotonic() - 3600)
    monkeypatch.setattr(pipeline_health, "UNKNOWN_CACHE_S", 0.0)

    async def twice():
        first = await probe.get()
        client.error = None
        client.docs = [zeek(40)]
        return first, await probe.get()

    first, second = asyncio.run(twice())
    assert (first["state"], second["state"], client.calls) == ("unknown", "fresh", 2)


# --- the probe ----------------------------------------------------------------------------


def test_freshness_reads_when_a_record_was_indexed_not_when_it_started(inspect_prints):
    # A long connection: started 8 days ago, indexed now. Measured on @timestamp it would be
    # outside the 7-day window and read "no data".
    assert probe(FakeSearch([zeek(30, started_ago=8 * DAY)]))["state"] == "fresh"


def test_stale_reports_the_age_past_a_day(inspect_prints):
    result = probe(FakeSearch([zeek(3 * DAY)]))
    assert result["state"] == "stale"
    assert abs(result["age_seconds"] - 3 * DAY) <= 5


def test_a_missing_container_is_a_stopped_sensor(inspect_prints):
    inspect_prints(
        ALL_RUNNING.replace("/nettap-filebeat running\n", ""),
        "error: no such object: nettap-filebeat\n",
        rc=1,
    )
    result = probe(FakeSearch([zeek(40)]))
    assert result["state"] == "sensor_stopped"
    assert result["sensors"]["nettap-filebeat"] == "missing"
    assert result["sensors"]["nettap-zeek-live"] == "running"


def test_docker_unreachable_is_unknown(inspect_prints):
    inspect_prints(
        "",
        "Cannot connect to the Docker daemon at unix:///var/run/docker.sock.\n",
        rc=1,
    )
    result = probe(FakeSearch([zeek(40)]))
    assert result["state"] == "unknown"
    assert result["sensors"] == dict.fromkeys(SENSORS, "unknown")


def test_a_stalled_docker_inspect_is_killed_at_the_deadline(monkeypatch, children):
    monkeypatch.setattr(pipeline_health, "BUDGET_S", 0.5)
    monkeypatch.setattr(pipeline_health, "INSPECT_CMD", ["sleep", "30"])
    started = time.monotonic()
    result = probe(FakeSearch([zeek(40)]))
    assert time.monotonic() - started < 2
    assert result["state"] == "unknown"
    assert result["sensors"] == dict.fromkeys(SENSORS, "unknown")
    assert len(children) == 1 and children[0].returncode == -9  # killed and reaped


def test_parse_inspect_reads_partial_output():
    out = "/nettap-zeek-live running\n/nettap-suricata-live restarting\n"
    err = "Error: No such object: nettap-logstash\n"  # the older CLI's wording
    assert parse_inspect(out, err) == {
        "nettap-zeek-live": "running",
        "nettap-suricata-live": "restarting",
        "nettap-logstash": "missing",
        "nettap-filebeat": "unknown",
    }
