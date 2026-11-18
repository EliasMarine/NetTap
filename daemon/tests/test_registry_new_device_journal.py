"""A device's first registration is journaled before it is indexed (NET-319)."""

import json
from unittest.mock import MagicMock, patch

import pytest
from opensearchpy import NotFoundError, TransportError

from services.device_registry import DeviceRegistry
from services.event_journal import EventJournal


@pytest.fixture
def client():
    c = MagicMock()
    c.indices.exists.return_value = True
    c.get.side_effect = NotFoundError(404, "not found", {})
    return c


def _lines(path) -> list[dict]:
    return (
        [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []
    )


def test_a_new_mac_is_journaled_before_it_is_indexed(tmp_path, client):
    path = tmp_path / "events.jsonl"
    order = []
    journal = EventJournal(str(path))
    real_append = journal.append
    journal.append = lambda *a, **k: order.append("journal") or real_append(*a, **k)
    client.index.side_effect = lambda **_k: order.append("index")
    registry = DeviceRegistry(client=client, journal=journal)
    registry.register_device(
        "AA-BB-CC-00-11-22",
        ip="192.0.2.5",
        source="conn",
        metadata={"manufacturer": "Acme"},
        seen_at="2026-11-18T10:00:00+00:00",
    )
    assert order == ["journal", "index"]
    [entry] = _lines(path)
    assert entry["type"] == "new_device"
    assert entry["key"] == "AA:BB:CC:00:11:22"  # the registry's normalised form
    assert entry["observed_at"] == "2026-11-18T10:00:00+00:00"
    assert entry["data"] == {"ip": "192.0.2.5", "vendor": "Acme", "source": "conn"}


def test_a_known_mac_appends_nothing(tmp_path, client):
    path = tmp_path / "events.jsonl"
    client.get.side_effect = None
    client.get.return_value = {
        "_source": {
            "mac": "aa:bb:cc:00:11:22",
            "ips": [],
            "hostnames": [],
            "enrichment_sources": {},
        }
    }
    DeviceRegistry(client=client, journal=EventJournal(str(path))).register_device(
        "aa:bb:cc:00:11:22", ip="192.0.2.5"
    )
    assert _lines(path) == []


def test_a_journal_failure_skips_the_device_without_raising(tmp_path, client):
    path = tmp_path / "events.jsonl"
    journal = EventJournal(str(path))
    registry = DeviceRegistry(client=client, journal=journal)
    with patch.object(journal, "append", side_effect=OSError(28, "No space left")):
        registry.register_device(
            "aa:bb:cc:00:11:22", ip="192.0.2.5"
        )  # no raise: the pass goes on
    client.index.assert_not_called()  # never registered without its event
    # the next refresh registers it, with its event
    registry.register_device("aa:bb:cc:00:11:22", ip="192.0.2.5")
    assert client.index.call_count == 1
    assert len(_lines(path)) == 1


def test_an_index_failure_then_a_retry_gives_one_event(tmp_path, client):
    path = tmp_path / "events.jsonl"
    registry = DeviceRegistry(client=client, journal=EventJournal(str(path)))
    client.index.side_effect = TransportError(500, "boom", {})
    with pytest.raises(TransportError):
        registry.register_device(
            "aa:bb:cc:00:11:22", ip="192.0.2.5", seen_at="2026-11-18T10:00:00+00:00"
        )
    client.index.side_effect = None
    registry.register_device(
        "aa:bb:cc:00:11:22", ip="192.0.2.5", seen_at="2026-11-18T10:05:00+00:00"
    )
    assert len(_lines(path)) == 1
    assert client.index.call_count == 2


def test_without_a_journal_registration_is_unchanged(client):
    DeviceRegistry(client=client).register_device("aa:bb:cc:00:11:22", ip="192.0.2.5")
    client.index.assert_called_once()
