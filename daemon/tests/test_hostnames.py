"""services/hostnames.py require_keyword (NET-160): name matching only on keyword fields."""

from unittest.mock import MagicMock

import pytest
from opensearchpy import ConnectionTimeout, OpenSearchException

from services.hostnames import require_keyword
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
