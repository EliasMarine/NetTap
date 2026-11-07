"""NET-192 PR 3: NETTAP_QUERY_TIMING=1 logs one line per OpenSearch request."""

import json
import logging

import pytest
from opensearchpy import Connection, TransportError

from storage import query_timing
from storage.exact_terms import ExactTermsOpenSearch
from storage.manager import StorageManager


class FakeConnection(Connection):
    """Answers every request from `reply` (or fails with a 500) without a network."""

    reply: dict = {"took": 7, "_shards": {"failed": 0}, "hits": {"hits": []}}
    fail = False

    def perform_request(self, method, url, *args, **kwargs):
        if self.fail:
            raise TransportError(500, "boom", {})
        return 200, {}, json.dumps(self.reply)


def _client(monkeypatch, value: str | None) -> ExactTermsOpenSearch:
    if value is None:
        monkeypatch.delenv("NETTAP_QUERY_TIMING", raising=False)
    else:
        monkeypatch.setenv("NETTAP_QUERY_TIMING", value)
    kwargs = StorageManager._client_kwargs("http://os:9200")
    return ExactTermsOpenSearch(
        **{**kwargs, "max_retries": 0}, connection_class=FakeConnection
    )


def _timing_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "nettap.query_timing"]


@pytest.mark.parametrize("value", [None, "0", ""])
def test_off_by_default(monkeypatch, caplog, value):
    client = _client(monkeypatch, value)
    assert "transport_class" not in StorageManager._client_kwargs("http://os:9200")
    with caplog.at_level(logging.INFO):
        client.search(index="arkime_sessions3-*", body={"size": 0})
    assert _timing_lines(caplog) == []


def test_logs_caller_took_and_wall_time(monkeypatch, caplog):
    client = _client(monkeypatch, "1")
    with caplog.at_level(logging.INFO):
        client.search(index="arkime_sessions3-*", body={"size": 0})
    (line,) = _timing_lines(caplog)
    assert line.startswith(f"{query_timing.PREFIX} caller=test_query_timing.")
    assert "test_logs_caller_took_and_wall_time:" in line
    assert " POST _search index=arkime_sessions3-* took_ms=7 " in line
    assert "wall_ms=" in line and line.endswith("outcome=ok")


def test_never_logs_a_document_id(monkeypatch, caplog):
    client = _client(monkeypatch, "1")
    mac = "aa:bb:cc:dd:ee:ff"
    with caplog.at_level(logging.INFO):
        client.get(index="nettap-devices", id=mac)
    (line,) = _timing_lines(caplog)
    assert mac not in line and "aa%3A" not in line
    assert " GET _doc index=nettap-devices " in line


def test_a_failed_request_is_logged_and_still_raises(monkeypatch, caplog):
    client = _client(monkeypatch, "1")
    monkeypatch.setattr(FakeConnection, "fail", True)
    with caplog.at_level(logging.INFO), pytest.raises(TransportError):
        client.count(index="arkime_sessions3-*")
    (line,) = _timing_lines(caplog)
    assert " _count index=arkime_sessions3-* took_ms=- " in line
    assert line.endswith("outcome=error")
