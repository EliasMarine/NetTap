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


# OLD CODE START — NET-160 review: terms sub-aggregations are allowed when they come back whole
# def test_groups_take_per_bucket_metrics_only():
#     with snapshot(DrillOpenSearch(peers(1))) as snap, pytest.raises(ValueError):
#         snap.groups(ALL, BY_SOURCE, {"x": {"terms": {"field": "y"}}}, "peers")
# OLD CODE END
def test_groups_take_per_bucket_metrics_or_whole_terms_only():
    with snapshot(DrillOpenSearch(peers(1))) as snap, pytest.raises(ValueError):
        snap.groups(ALL, BY_SOURCE, {"x": {"cardinality": {"field": "y"}}}, "peers")


def test_a_whole_terms_sub_aggregation_comes_back_and_a_cut_one_fails():
    docs = [conn("10.0.0.1", "1.1.1.1", network__protocol=p) for p in "abc"]

    def services(size):
        return {"svc": {"terms": {"field": "network.protocol", "size": size}}}

    with snapshot(DrillOpenSearch(docs)) as snap:
        (bucket,), _ = snap.groups(ALL, BY_SOURCE, services(3), "ports")
        assert [b["key"] for b in bucket["svc"]["buckets"]] == ["a", "b", "c"]
        with pytest.raises(QueryFailed, match="cut short"):
            snap.groups(ALL, BY_SOURCE, services(2), "ports")


@pytest.mark.parametrize("call", ["search", "create_pit"])
def test_a_client_side_timeout_is_too_slow_not_a_failure(call):
    from opensearchpy import ConnectionTimeout

    client = DrillOpenSearch(peers(1))

    def times_out(*args, **kw):
        raise ConnectionTimeout("TIMEOUT", "read timed out", None)

    setattr(client, call, times_out)
    with pytest.raises(TooSlow):
        with snapshot(client) as snap:
            snap.count(ALL, "count")


def test_opensearchs_own_timeout_is_too_slow():
    client = DrillOpenSearch(peers(1), tamper=lambda b, r: {**r, "timed_out": True})
    with pytest.raises(TooSlow, match="timed out"), snapshot(client) as snap:
        snap.count(ALL, "count")


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
