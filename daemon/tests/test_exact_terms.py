"""#93: terms aggregations count exactly across daily indices."""

from unittest.mock import patch

from opensearchpy import OpenSearch

from storage.exact_terms import EXACT_SHARD_SIZE, ExactTermsOpenSearch, exact_body, with_exact_terms
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
    assert out["set_already"]["terms"]["shard_size"] == 7
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
