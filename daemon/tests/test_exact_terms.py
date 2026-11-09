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
        "in_window": {
            "filter": {"term": {"a": 1}},
            "aggs": {"top": {"terms": {"field": "b"}}},
        },
        "big": {"terms": {"field": "c", "size": 20_000}},
        "set_already": {"terms": {"field": "d", "size": 5, "shard_size": 7}},
    }
    out = with_exact_terms(aggs)
    assert out["by_src"]["terms"]["shard_size"] == EXACT_SHARD_SIZE
    assert out["by_src"]["aggs"]["ports"]["terms"]["shard_size"] == EXACT_SHARD_SIZE
    assert out["by_src"]["aggs"]["bytes"] == {"sum": {"field": "source.bytes"}}
    assert out["in_window"]["aggs"]["top"]["terms"]["shard_size"] == EXACT_SHARD_SIZE
    assert out["big"]["terms"]["shard_size"] == 20_000  # never below size
    assert (
        out["set_already"]["terms"]["shard_size"] == EXACT_SHARD_SIZE
    )  # never lowered by a caller
    assert (
        "shard_size" not in aggs["by_src"]["terms"]
    )  # the caller's body is not changed


def test_bodies_without_aggregations_pass_through():
    body = {"query": {"match_all": {}}, "size": 5}
    assert exact_body(body) is body
    assert exact_body(None) is None


def test_the_client_sends_exact_bodies():
    client = ExactTermsOpenSearch(hosts=[{"host": "localhost", "port": 9200}])
    with patch.object(OpenSearch, "search", return_value={}) as search:
        client.search(
            index="x-*", body={"size": 0, "aggs": {"t": {"terms": {"field": "f"}}}}
        )
    assert (
        search.call_args.kwargs["body"]["aggs"]["t"]["terms"]["shard_size"]
        == EXACT_SHARD_SIZE
    )
    assert search.call_args.kwargs["index"] == "x-*"
    with patch.object(OpenSearch, "msearch", return_value={}) as msearch:
        client.msearch(
            body=[
                {"index": "x-*"},
                {"size": 0, "aggs": {"t": {"terms": {"field": "f", "size": 1}}}},
            ]
        )
    sent = msearch.call_args.kwargs["body"]
    assert sent[0] == {"index": "x-*"}
    assert sent[1]["aggs"]["t"]["terms"]["shard_size"] == EXACT_SHARD_SIZE


def test_the_daemon_uses_the_exact_client():
    assert isinstance(
        StorageManager._create_client("https://opensearch:9200"), ExactTermsOpenSearch
    )


def _reply(err):
    return {"aggregations": {"t": {"doc_count_error_upper_bound": err, "buckets": []}}}


def test_truncated_reads_every_level():
    assert not truncated(
        {"t": {"doc_count_error_upper_bound": 0, "buckets": [{"key": "a"}]}}
    )
    assert truncated(
        {"t": {"doc_count_error_upper_bound": 12, "buckets": []}}
    )  # by count
    assert truncated(
        {"t": {"doc_count_error_upper_bound": -1, "buckets": []}}
    )  # by a metric
    nested = {
        "t": {
            "doc_count_error_upper_bound": 0,
            "buckets": [
                {"key": "a", "inner": {"doc_count_error_upper_bound": 3, "buckets": []}}
            ],
        }
    }
    assert truncated(nested)
    assert not truncated(None)


def test_a_cut_short_list_is_counted_again_with_longer_lists():
    """#94: a network busier than a home one still gets exact counts."""
    client = ExactTermsOpenSearch(hosts=[{"host": "localhost", "port": 9200}])
    with patch.object(
        OpenSearch, "search", side_effect=[_reply(-1), _reply(0)]
    ) as search:
        reply = client.search(
            index="x-*", body={"size": 0, "aggs": {"t": {"terms": {"field": "f"}}}}
        )
    sizes = [
        c.kwargs["body"]["aggs"]["t"]["terms"]["shard_size"]
        for c in search.call_args_list
    ]
    assert sizes == [EXACT_SHARD_SIZE, EXACT_SHARD_SIZE * 10]
    assert reply == _reply(0)


def test_past_the_cap_the_estimate_is_returned_with_a_warning(caplog):
    client = ExactTermsOpenSearch(hosts=[{"host": "localhost", "port": 9200}])
    with patch.object(OpenSearch, "search", return_value=_reply(5)) as search:
        reply = client.search(
            index="x-*", body={"size": 0, "aggs": {"t": {"terms": {"field": "f"}}}}
        )
    assert (
        search.call_args.kwargs["body"]["aggs"]["t"]["terms"]["shard_size"]
        == MAX_SHARD_SIZE
    )
    assert reply == _reply(5)
    assert "estimates" in caplog.text


def test_msearch_is_counted_again_too():
    client = ExactTermsOpenSearch(hosts=[{"host": "localhost", "port": 9200}])
    first = {"responses": [_reply(0), _reply(4)]}
    second = {"responses": [_reply(0), _reply(0)]}
    with patch.object(OpenSearch, "msearch", side_effect=[first, second]) as msearch:
        reply = client.msearch(
            body=[
                {"index": "x-*"},
                {"size": 0, "aggs": {"t": {"terms": {"field": "f"}}}},
            ]
        )
    assert msearch.call_count == 2
    assert reply == second


def test_longer_lists_never_pass_the_cap(monkeypatch):
    from storage import exact_terms

    monkeypatch.setattr(exact_terms, "EXACT_SHARD_SIZE", 5)
    client = ExactTermsOpenSearch(hosts=[{"host": "localhost", "port": 9200}])
    with patch.object(OpenSearch, "search", return_value=_reply(-1)) as search:
        client.search(
            index="x-*", body={"size": 0, "aggs": {"t": {"terms": {"field": "f"}}}}
        )
    sizes = [
        c.kwargs["body"]["aggs"]["t"]["terms"]["shard_size"]
        for c in search.call_args_list
    ]
    assert sizes == [
        10,
        50,
        500,
        5000,
        50_000,
        MAX_SHARD_SIZE,
    ]  # size 10 floors the first


def test_a_reply_from_only_some_shards_is_an_error():
    """By default OpenSearch answers from the shards that worked, so a count read low silently."""
    import pytest

    from storage.exact_terms import PartialResultsError

    partial = {
        "_shards": {"total": 3, "successful": 2, "failed": 1},
        "hits": {"total": {"value": 7}},
    }
    whole = {
        "_shards": {"total": 3, "successful": 3, "failed": 0},
        "hits": {"total": {"value": 9}},
    }
    client = ExactTermsOpenSearch(hosts=[{"host": "localhost", "port": 9200}])
    with (
        patch.object(OpenSearch, "search", return_value=partial),
        pytest.raises(PartialResultsError),
    ):
        client.search(index="x-*", body={"size": 0})
    with (
        patch.object(
            OpenSearch, "msearch", return_value={"responses": [whole, partial]}
        ),
        pytest.raises(PartialResultsError),
    ):
        client.msearch(body=[{"index": "x-*"}, {"size": 0}])
    with patch.object(OpenSearch, "search", return_value=whole):
        assert client.search(index="x-*", body={"size": 0}) == whole


def test_multi_terms_lists_get_a_shard_size_too():
    """#96: a cut-short multi_terms list was re-run with the same shard size until the cap."""
    aggs = {
        "pairs": {
            "multi_terms": {"terms": [{"field": "a"}, {"field": "b"}], "size": 50_000}
        }
    }
    assert with_exact_terms(aggs)["pairs"]["multi_terms"]["shard_size"] == 50_000
    assert (
        with_exact_terms(aggs, 100_000)["pairs"]["multi_terms"]["shard_size"] == 100_000
    )


# ---------------------------------------------------------------------------
# NET-237 (TRF-3, ALR-11, DNS-4): every partial reply is an error, through the one shared client
# ---------------------------------------------------------------------------

_WHOLE = {
    "_shards": {"total": 3, "successful": 3, "failed": 0},
    "timed_out": False,
    "hits": {"total": {"value": 9}, "hits": []},
}
_TIMED_OUT = {**_WHOLE, "timed_out": True, "hits": {"total": {"value": 4}}}
_FAILED = {**_WHOLE, "_shards": {"total": 3, "successful": 2, "failed": 1}}


def _client() -> ExactTermsOpenSearch:
    return ExactTermsOpenSearch(hosts=[{"host": "localhost", "port": 9200}])


def test_a_timed_out_search_is_an_error_not_a_smaller_count():
    import pytest

    from storage.exact_terms import PartialResultsError

    with (
        patch.object(OpenSearch, "search", return_value=_TIMED_OUT),
        pytest.raises(PartialResultsError, match="timed out"),
    ):
        _client().search(index="x-*", body={"size": 0, "timeout": "1ms"})


def test_one_failed_search_in_an_msearch_is_an_error_not_no_hits():
    import pytest

    from storage.exact_terms import PartialResultsError

    failed = {"error": {"type": "search_phase_execution_exception"}, "status": 500}
    with (
        patch.object(
            OpenSearch, "msearch", return_value={"responses": [_WHOLE, failed]}
        ),
        pytest.raises(PartialResultsError, match="search in the batch failed"),
    ):
        _client().msearch(body=[{"index": "x-*"}, {"size": 0}] * 2)


def test_a_count_from_only_some_shards_is_an_error():
    import pytest

    from storage.exact_terms import PartialResultsError

    partial = {"count": 3, "_shards": {"total": 3, "successful": 2, "failed": 1}}
    whole = {"count": 5, "_shards": {"total": 3, "successful": 3, "failed": 0}}
    with (
        patch.object(OpenSearch, "count", return_value=partial),
        pytest.raises(PartialResultsError),
    ):
        _client().count(index="x-*", body={"query": {"match_all": {}}})
    with patch.object(OpenSearch, "count", return_value=whole):
        assert _client().count(index="x-*", body={"query": {"match_all": {}}}) == whole


def test_dns_analytics_paths_raise_on_a_partial_reply():
    """DNS-4: DNSAnalytics runs on the shared client, its all_buckets scans included."""
    import pytest

    from services.dns_analytics import DNSAnalytics
    from storage.exact_terms import PartialResultsError

    window = ("2026-11-09T00:00:00Z", "2026-11-09T01:00:00Z")
    for bad in (_TIMED_OUT, _FAILED):
        dns = DNSAnalytics(client=_client())
        with patch.object(OpenSearch, "search", return_value=bad):
            for call in (
                lambda: dns.get_top_domains(*window),  # a plain search
                lambda: dns.get_suspicious_dns(*window),  # all_buckets without what=
                lambda: dns.get_stats(*window),
            ):
                with pytest.raises(PartialResultsError):
                    call()
