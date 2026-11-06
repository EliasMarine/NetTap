"""services/hostnames.py require_keyword (NET-160): name matching only on keyword fields;
keyword_paths (NET-178): which optional name fields can be matched, and how."""

from unittest.mock import MagicMock

import pytest
from opensearchpy import ConnectionTimeout, OpenSearchException

from services.hostnames import keyword_paths, require_keyword
from storage.snapshot_search import Budget, QueryFailed, TooSlow

FIELDS = ["zeek.dns.query", "url.domain"]


def mapped(kind):
    return {"mapping": {"query": {"type": kind}}}


def stub(reply=None, error=None):
    client = MagicMock()
    client.indices.get_field_mapping.side_effect = error
    client.indices.get_field_mapping.return_value = reply
    return client


def test_keyword_everywhere_or_absent_from_an_index_passes():
    reply = {
        "arkime_sessions3-261104": {"mappings": {"zeek.dns.query": mapped("keyword")}},
        "arkime_sessions3-261105": {"mappings": {}},  # no such records that day
    }
    require_keyword(stub(reply), FIELDS, Budget(10))


def test_types_that_differ_across_indices_fail_naming_the_index():
    reply = {
        "arkime_sessions3-261104": {"mappings": {"zeek.dns.query": mapped("keyword")}},
        "arkime_sessions3-261105": {"mappings": {"zeek.dns.query": mapped("text")}},
    }
    with pytest.raises(QueryFailed, match="text in arkime_sessions3-261105"):
        require_keyword(stub(reply), FIELDS, Budget(10))


def test_a_field_listed_without_a_type_fails_as_unmapped():
    reply = {"arkime_sessions3-261105": {"mappings": {"url.domain": {"mapping": {}}}}}
    with pytest.raises(QueryFailed, match="url.domain is unmapped"):
        require_keyword(stub(reply), FIELDS, Budget(10))


def test_an_unreadable_mapping_fails_and_a_slow_one_is_too_slow():
    with pytest.raises(QueryFailed, match="mappings unreadable"):
        require_keyword(stub(error=OpenSearchException("boom")), FIELDS, Budget(10))
    with pytest.raises(TooSlow):
        require_keyword(
            stub(error=ConnectionTimeout("TIMEOUT", "slow", None)), FIELDS, Budget(10)
        )
    with pytest.raises(QueryFailed, match="malformed"):
        require_keyword(stub(["not", "a", "dict"]), FIELDS, Budget(10))


# ---------------------------------------------------------------------------
# NET-178: keyword_paths, for the optional alert host fields
# ---------------------------------------------------------------------------

DAY1, DAY2 = "arkime_sessions3-261104", "arkime_sessions3-261105"
HOSTS = ["related.hosts", "dns.question.name", "tls.client.server_name", "url.domain"]


def entry(path, kind, ignore_above=None):
    """One field of a get_field_mapping reply; a multi-field f.keyword has leaf "keyword"."""
    params = {"type": kind}
    if ignore_above is not None:
        params["ignore_above"] = ignore_above
    return {path: {"full_name": path, "mapping": {path.rsplit(".", 1)[-1]: params}}}


def day(*entries):
    return {"mappings": {k: v for e in entries for k, v in e.items()}}


def test_keyword_that_keeps_a_whole_name_is_matched_as_it_is_in_one_call():
    reply = {
        DAY1: day(
            entry("related.hosts", "keyword"), entry("url.domain", "keyword", 256)
        ),
        DAY2: day(entry("url.domain", "keyword", 254)),  # no related.hosts that day
    }
    client = stub(reply)
    got = keyword_paths(client, ["related.hosts", "url.domain"], Budget(10))
    assert got == (["related.hosts", "url.domain"], [])
    asked = client.indices.get_field_mapping.call_args.kwargs["fields"].split(",")
    assert asked == [
        "related.hosts",
        "url.domain",
        "related.hosts.keyword",
        "url.domain.keyword",
    ]


def test_text_or_a_short_ignore_above_falls_back_to_a_keyword_subfield():
    reply = {
        DAY1: day(
            entry("tls.client.server_name", "text"),
            entry("tls.client.server_name.keyword", "keyword", 256),
            entry("url.domain", "keyword", 253),  # 253 + the trailing dot doesn't fit
            entry("url.domain.keyword", "keyword"),
        ),
        DAY2: day(
            entry("tls.client.server_name", "text"),
            entry("tls.client.server_name.keyword", "keyword", 300),
        ),
    }
    got = keyword_paths(
        stub(reply), ["tls.client.server_name", "url.domain"], Budget(10)
    )
    assert got == (["tls.client.server_name.keyword", "url.domain.keyword"], [])


def test_fields_with_no_exact_path_are_unmatched_and_named_in_a_warning(caplog):
    reply = {
        DAY1: day(
            entry("tls.client.server_name", "text"),  # no subfield
            entry("related.hosts", "keyword"),
            entry("url.domain", "text"),
            entry("url.domain.keyword", "keyword", 256),
            entry("dns.question.name", "text"),
            entry("dns.question.name.keyword", "keyword", 8),
        ),
        DAY2: day(
            entry("related.hosts", "text"),  # keyword one day, text the next
            entry("related.hosts.keyword", "keyword", 256),
            entry("url.domain", "text"),  # its subfield is missing this day
        ),
    }
    with caplog.at_level("WARNING", logger="nettap.services.hostnames"):
        got = keyword_paths(stub(reply), HOSTS, Budget(10))
    assert got == (
        [],
        ["related.hosts", "dns.question.name", "tls.client.server_name", "url.domain"],
    )
    for field in HOSTS:
        assert field in caplog.text
    assert "'type': 'text'" in caplog.text


def test_a_field_no_index_maps_is_in_neither_list():
    reply = {DAY1: day(entry("related.hosts", "keyword")), DAY2: {"mappings": {}}}
    got = keyword_paths(stub(reply), HOSTS, Budget(10))
    assert got == (["related.hosts"], [])
    assert keyword_paths(stub({}), HOSTS, Budget(10)) == ([], [])


def test_keyword_paths_fails_like_require_keyword_when_the_mapping_cant_be_read():
    with pytest.raises(QueryFailed, match="mappings unreadable"):
        keyword_paths(stub(error=OpenSearchException("boom")), HOSTS, Budget(10))
    with pytest.raises(TooSlow):
        keyword_paths(
            stub(error=ConnectionTimeout("TIMEOUT", "slow", None)), HOSTS, Budget(10)
        )
    with pytest.raises(QueryFailed, match="malformed"):
        keyword_paths(stub(["not", "a", "dict"]), HOSTS, Budget(10))
