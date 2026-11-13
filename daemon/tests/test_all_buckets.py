"""#96: all_buckets pages a composite aggregation to the end."""

from unittest.mock import MagicMock

from storage.all_buckets import all_buckets


def _page(keys, after):
    return {
        "aggregations": {
            "all": {
                "buckets": [{"key": {"ip": k}, "doc_count": 1} for k in keys],
                **({"after_key": after} if after else {}),
            }
        }
    }


def test_pages_until_the_last_bucket():
    client = MagicMock()
    client.search.side_effect = [
        _page(["a", "b"], {"ip": "b"}),
        _page(["c"], {"ip": "c"}),
    ]
    buckets, complete = all_buckets(
        client,
        "x-*",
        {"match_all": {}},
        [{"ip": {"terms": {"field": "source.ip"}}}],
        aggs={"bytes": {"sum": {"field": "source.bytes"}}},
        page_size=2,
    )
    assert [b["key"]["ip"] for b in buckets] == ["a", "b", "c"]
    assert complete is True
    bodies = [c.kwargs["body"] for c in client.search.call_args_list]
    assert "after" not in bodies[0]["aggs"]["all"]["composite"]
    assert bodies[1]["aggs"]["all"]["composite"]["after"] == {"ip": "b"}
    assert bodies[0]["aggs"]["all"]["aggs"] == {
        "bytes": {"sum": {"field": "source.bytes"}}
    }
    # the short page [c] was the last: no extra empty search
    assert client.search.call_count == 2


def test_reports_incomplete_at_the_cap():
    client = MagicMock()
    client.search.side_effect = [
        _page(["a", "b"], {"ip": "b"}),
        _page(["c", "d"], {"ip": "d"}),
    ]
    buckets, complete = all_buckets(
        client,
        "x-*",
        {},
        [{"ip": {"terms": {"field": "f"}}}],
        page_size=2,
        max_buckets=3,
    )
    assert len(buckets) == 4
    assert complete is False


def test_the_callers_stop_ends_the_scan_as_incomplete():
    """NET-264: `stop` sees every full page and can end the scan before the cap."""
    client = MagicMock()
    client.search.side_effect = [
        _page(["a", "b"], {"ip": "b"}),
        _page(["c", "d"], {"ip": "d"}),
        _page(["e"], {"ip": "e"}),
    ]
    seen = []

    def stop(page):
        seen.append([b["key"]["ip"] for b in page])
        return len(seen) == 2

    buckets, complete = all_buckets(
        client, "x-*", {}, [{"ip": {"terms": {"field": "f"}}}], page_size=2, stop=stop
    )
    assert [b["key"]["ip"] for b in buckets] == ["a", "b", "c", "d"]
    assert complete is False
    assert seen == [["a", "b"], ["c", "d"]]
    assert client.search.call_count == 2


def test_a_full_last_page_ends_on_the_empty_page():
    client = MagicMock()
    client.search.side_effect = [_page(["a", "b"], {"ip": "b"}), _page([], {"ip": "b"})]
    buckets, complete = all_buckets(
        client, "x-*", {}, [{"ip": {"terms": {"field": "f"}}}], page_size=2
    )
    assert [b["key"]["ip"] for b in buckets] == ["a", "b"]
    assert complete is True


def test_a_reply_without_a_bucket_list_stops():
    """A bare MagicMock reply has a truthy after_key and no list: it used to page forever."""
    buckets, complete = all_buckets(
        MagicMock(), "x-*", {}, [{"ip": {"terms": {"field": "f"}}}]
    )
    assert buckets == []
    assert complete is True


# Follow-up to PR #191: a checked read never takes a malformed page as the end of the list


def _checked(client, page_size=2):
    return all_buckets(
        client,
        "x-*",
        {},
        [{"ip": {"terms": {"field": "f"}}}],
        page_size=page_size,
        what="devices",
    )


def test_checked_read_fails_on_a_later_page_with_no_bucket_list():
    import pytest

    from storage.snapshot_search import QueryFailed

    client = MagicMock()
    client.search.side_effect = [
        _page(["a", "b"], {"ip": "b"}),
        {"aggregations": {"all": {"after_key": {"ip": "z"}}}},
    ]
    with pytest.raises(QueryFailed, match="devices: malformed page"):
        _checked(client)


def test_checked_read_fails_on_a_full_page_with_no_next_key():
    import pytest

    from storage.snapshot_search import QueryFailed

    client = MagicMock()
    client.search.side_effect = [_page(["a", "b"], None)]
    with pytest.raises(QueryFailed, match="malformed page"):
        _checked(client)


def test_unchecked_read_keeps_reading_a_malformed_page_as_the_end():
    client = MagicMock()
    client.search.side_effect = [
        _page(["a", "b"], {"ip": "b"}),
        {"aggregations": {"all": {"after_key": {"ip": "z"}}}},
    ]
    buckets, complete = all_buckets(
        client, "x-*", {}, [{"ip": {"terms": {"field": "f"}}}], page_size=2
    )
    assert [b["key"]["ip"] for b in buckets] == ["a", "b"]
    assert complete is True
