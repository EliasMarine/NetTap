"""#93: terms aggregations count exactly across daily indices."""

from unittest.mock import patch

from opensearchpy import OpenSearch

from storage.exact_terms import (
    EXACT_SHARD_SIZE,
    MAX_SHARD_SIZE,
    ExactTermsOpenSearch,
    exact_body,
    truncated,
    with_exact_terms,
)
from storage.manager import StorageManager


def test_every_terms_aggregation_gets_a_shard_size_nested_ones_too():
    aggs = {
        "by_src": {
            "terms": {"field": "source.ip", "size": 10},
            "aggs": {
                "bytes": {"sum": {"field": "source.bytes"}},
                "ports": {"terms": {"field": "destination.port", "size": 50}},
            },
        },
        "in_window": {"filter": {"term": {"a": 1}}, "aggs": {"top": {"terms": {"field": "b"}}}},
        "big": {"terms": {"field": "c", "size": 20_000}},
        "set_already": {"terms": {"field": "d", "size": 5, "shard_size": 7}},
    }
    out = with_exact_terms(aggs)
    assert out["by_src"]["terms"]["shard_size"] == EXACT_SHARD_SIZE
    assert out["by_src"]["aggs"]["ports"]["terms"]["shard_size"] == EXACT_SHARD_SIZE
    assert out["by_src"]["aggs"]["bytes"] == {"sum": {"field": "source.bytes"}}
    assert out["in_window"]["aggs"]["top"]["terms"]["shard_size"] == EXACT_SHARD_SIZE
    assert out["big"]["terms"]["shard_size"] == 20_000  # never below size
    assert out["set_already"]["terms"]["shard_size"] == EXACT_SHARD_SIZE  # never lowered by a caller
    assert "shard_size" not in aggs["by_src"]["terms"]  # the caller's body is not changed


def test_bodies_without_aggregations_pass_through():
    body = {"query": {"match_all": {}}, "size": 5}
    assert exact_body(body) is body
    assert exact_body(None) is None


def test_the_client_sends_exact_bodies():
    client = ExactTermsOpenSearch(hosts=[{"host": "localhost", "port": 9200}])
    with patch.object(OpenSearch, "search", return_value={}) as search:
        client.search(index="x-*", body={"size": 0, "aggs": {"t": {"terms": {"field": "f"}}}})
    assert search.call_args.kwargs["body"]["aggs"]["t"]["terms"]["shard_size"] == EXACT_SHARD_SIZE
    assert search.call_args.kwargs["index"] == "x-*"
    with patch.object(OpenSearch, "msearch", return_value={}) as msearch:
        client.msearch(body=[{"index": "x-*"}, {"size": 0, "aggs": {"t": {"terms": {"field": "f", "size": 1}}}}])
    sent = msearch.call_args.kwargs["body"]
    assert sent[0] == {"index": "x-*"}
    assert sent[1]["aggs"]["t"]["terms"]["shard_size"] == EXACT_SHARD_SIZE


def test_the_daemon_uses_the_exact_client():
    assert isinstance(StorageManager._create_client("https://opensearch:9200"), ExactTermsOpenSearch)


def _reply(err):
    return {"aggregations": {"t": {"doc_count_error_upper_bound": err, "buckets": []}}}


def test_truncated_reads_every_level():
    assert not truncated({"t": {"doc_count_error_upper_bound": 0, "buckets": [{"key": "a"}]}})
    assert truncated({"t": {"doc_count_error_upper_bound": 12, "buckets": []}})  # by count
    assert truncated({"t": {"doc_count_error_upper_bound": -1, "buckets": []}})  # by a metric
    nested = {"t": {"doc_count_error_upper_bound": 0, "buckets": [{"key": "a", "inner": {"doc_count_error_upper_bound": 3, "buckets": []}}]}}
    assert truncated(nested)
    assert not truncated(None)


def test_a_cut_short_list_is_counted_again_with_longer_lists():
    """#94: a network busier than a home one still gets exact counts."""
    client = ExactTermsOpenSearch(hosts=[{"host": "localhost", "port": 9200}])
    with patch.object(OpenSearch, "search", side_effect=[_reply(-1), _reply(0)]) as search:
        reply = client.search(index="x-*", body={"size": 0, "aggs": {"t": {"terms": {"field": "f"}}}})
    sizes = [c.kwargs["body"]["aggs"]["t"]["terms"]["shard_size"] for c in search.call_args_list]
    assert sizes == [EXACT_SHARD_SIZE, EXACT_SHARD_SIZE * 10]
    assert reply == _reply(0)


def test_past_the_cap_the_estimate_is_returned_with_a_warning(caplog):
    client = ExactTermsOpenSearch(hosts=[{"host": "localhost", "port": 9200}])
    with patch.object(OpenSearch, "search", return_value=_reply(5)) as search:
        reply = client.search(index="x-*", body={"size": 0, "aggs": {"t": {"terms": {"field": "f"}}}})
    assert search.call_args.kwargs["body"]["aggs"]["t"]["terms"]["shard_size"] == MAX_SHARD_SIZE
    assert reply == _reply(5)
    assert "estimates" in caplog.text


def test_msearch_is_counted_again_too():
    client = ExactTermsOpenSearch(hosts=[{"host": "localhost", "port": 9200}])
    first = {"responses": [_reply(0), _reply(4)]}
    second = {"responses": [_reply(0), _reply(0)]}
    with patch.object(OpenSearch, "msearch", side_effect=[first, second]) as msearch:
        reply = client.msearch(body=[{"index": "x-*"}, {"size": 0, "aggs": {"t": {"terms": {"field": "f"}}}}])
    assert msearch.call_count == 2
    assert reply == second


def test_longer_lists_never_pass_the_cap(monkeypatch):
    from storage import exact_terms

    monkeypatch.setattr(exact_terms, "EXACT_SHARD_SIZE", 5)
    client = ExactTermsOpenSearch(hosts=[{"host": "localhost", "port": 9200}])
    with patch.object(OpenSearch, "search", return_value=_reply(-1)) as search:
        client.search(index="x-*", body={"size": 0, "aggs": {"t": {"terms": {"field": "f"}}}})
    sizes = [c.kwargs["body"]["aggs"]["t"]["terms"]["shard_size"] for c in search.call_args_list]
    assert sizes == [10, 50, 500, 5000, 50_000, MAX_SHARD_SIZE]  # size 10 floors the first
