"""#96: all_buckets pages a composite aggregation to the end."""

from unittest.mock import MagicMock

from storage.all_buckets import all_buckets


def _page(keys, after):
    return {"aggregations": {"all": {"buckets": [{"key": {"ip": k}, "doc_count": 1} for k in keys], **({"after_key": after} if after else {})}}}


def test_pages_until_the_last_bucket():
    client = MagicMock()
    client.search.side_effect = [_page(["a", "b"], {"ip": "b"}), _page(["c"], {"ip": "c"})]
    buckets, complete = all_buckets(client, "x-*", {"match_all": {}}, [{"ip": {"terms": {"field": "source.ip"}}}],
                                    aggs={"bytes": {"sum": {"field": "source.bytes"}}}, page_size=2)
    assert [b["key"]["ip"] for b in buckets] == ["a", "b", "c"]
    assert complete is True
    bodies = [c.kwargs["body"] for c in client.search.call_args_list]
    assert "after" not in bodies[0]["aggs"]["all"]["composite"]
    assert bodies[1]["aggs"]["all"]["composite"]["after"] == {"ip": "b"}
    assert bodies[0]["aggs"]["all"]["aggs"] == {"bytes": {"sum": {"field": "source.bytes"}}}
    # the short page [c] was the last: no extra empty search
    assert client.search.call_count == 2


def test_reports_incomplete_at_the_cap():
    client = MagicMock()
    client.search.side_effect = [_page(["a", "b"], {"ip": "b"}), _page(["c", "d"], {"ip": "d"})]
    buckets, complete = all_buckets(client, "x-*", {}, [{"ip": {"terms": {"field": "f"}}}], page_size=2, max_buckets=3)
    assert len(buckets) == 4
    assert complete is False


def test_a_full_last_page_ends_on_the_empty_page():
    client = MagicMock()
    client.search.side_effect = [_page(["a", "b"], {"ip": "b"}), _page([], {"ip": "b"})]
    buckets, complete = all_buckets(client, "x-*", {}, [{"ip": {"terms": {"field": "f"}}}], page_size=2)
    assert [b["key"]["ip"] for b in buckets] == ["a", "b"]
    assert complete is True


def test_a_reply_without_a_bucket_list_stops():
    """A bare MagicMock reply has a truthy after_key and no list: it used to page forever."""
    buckets, complete = all_buckets(MagicMock(), "x-*", {}, [{"ip": {"terms": {"field": "f"}}}])
    assert buckets == []
    assert complete is True
