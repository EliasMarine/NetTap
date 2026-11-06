"""storage/snapshot_search.py (NET-160): one checked snapshot per request, complete or flagged."""

import pytest
from opensearchpy import OpenSearchException

from storage import snapshot_search
from storage.snapshot_search import Budget, QueryFailed, SnapshotSearch, TooSlow
from tests.fake_drill_opensearch import DrillOpenSearch, conn

ALL = {"match_all": {}}
BY_SOURCE = [{"ip": {"terms": {"field": "source.ip"}}}]


def snapshot(client, seconds=25):
    return SnapshotSearch(client, "arkime_sessions3-*", Budget(seconds))


def peers(n):
    return [conn(f"10.0.0.{i}", "93.184.216.34") for i in range(n)]


@pytest.mark.parametrize(
    "change, words",
    [
        (lambda r: None, "malformed"),
        (lambda r: {**r, "timed_out": True}, "timed out"),
        (lambda r: {**r, "_shards": {"failed": 2}}, "shard"),
        (lambda r: {**r, "aggregations": {}}, "missing aggregation"),
    ],
)
def test_every_incomplete_reply_is_a_failure_never_a_smaller_figure(change, words):
    client = DrillOpenSearch(peers(3), tamper=lambda body, reply: change(reply))
    with pytest.raises(QueryFailed, match=words), snapshot(client) as snap:
        snap.groups(ALL, BY_SOURCE, None, "peers")


def test_an_inexact_total_is_a_failure():
    client = DrillOpenSearch(
        peers(1),
        tamper=lambda b, r: {**r, "hits": {"total": {"value": 1, "relation": "gte"}}},
    )
    with pytest.raises(QueryFailed, match="no exact total"), snapshot(client) as snap:
        snap.count(ALL, "count")


def test_groups_page_every_bucket_over_one_snapshot(monkeypatch):
    monkeypatch.setattr(snapshot_search, "GROUP_PAGE", 2)
    client = DrillOpenSearch(peers(5))
    with snapshot(client) as snap:
        buckets, complete = snap.groups(ALL, BY_SOURCE, None, "peers")
    assert complete and len(buckets) == 5
    assert {b["key"]["ip"] for b in buckets} == {f"10.0.0.{i}" for i in range(5)}
    assert len(client.bodies) == 3  # two full pages and a short one
    assert {b["pit"]["id"] for b in client.bodies} == {"pit-0"}
    assert client.bodies[1]["aggs"]["groups"]["composite"]["after"] == {
        "ip": "10.0.0.1"
    }


def test_groups_stopped_by_the_cap_say_so(monkeypatch):
    monkeypatch.setattr(snapshot_search, "GROUP_PAGE", 2)
    with snapshot(DrillOpenSearch(peers(5))) as snap:
        buckets, complete = snap.groups(ALL, BY_SOURCE, None, "peers", max_buckets=4)
    assert (len(buckets), complete) == (4, False)


def test_groups_take_per_bucket_metrics_only():
    with snapshot(DrillOpenSearch(peers(1))) as snap, pytest.raises(ValueError):
        snap.groups(ALL, BY_SOURCE, {"x": {"terms": {"field": "y"}}}, "peers")


def test_the_snapshot_holds_when_documents_change_between_searches():
    client = DrillOpenSearch(peers(2))
    with snapshot(client) as snap:
        before = snap.count(ALL, "count")
        client.docs.extend(peers(3))  # new records arrive mid-request
        buckets, _ = snap.groups(ALL, BY_SOURCE, None, "peers")
    assert before == 2 and sum(b["doc_count"] for b in buckets) == 2
    with snapshot(client) as snap:
        assert snap.count(ALL, "count") == 5


def test_the_snapshot_refuses_partial_shards_and_is_closed_on_error():
    def fail(body, reply):
        raise OpenSearchException("boom")

    client = DrillOpenSearch(peers(1), tamper=fail)
    with pytest.raises(QueryFailed, match="query failed"), snapshot(client) as snap:
        snap.count(ALL, "count")
    assert client.pit_params["allow_partial_pit_creation"] == "false"
    assert client.pits == {} and client.closed == ["pit-0"]


def test_every_search_gets_the_remaining_budget_and_runs_out_as_too_slow():
    now = [0.0]
    client = DrillOpenSearch(peers(1))
    budget = Budget(25, clock=lambda: now[0])
    with SnapshotSearch(client, "i", budget) as snap:
        now[0] = 10.0
        snap.count(ALL, "first")
        now[0] = 26.0
        with pytest.raises(TooSlow):
            snap.count(ALL, "second")
    assert client.bodies[0]["timeout"] == "15000ms"
    assert client.pits == {}
