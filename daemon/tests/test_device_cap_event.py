"""NET-182: reaching the device cap writes one Changelog event that says why, not one per read."""

from unittest.mock import MagicMock, patch

import pytest

from api import devices
from api.devices import _lan_device_buckets
from services.excluded_ips import build_lan_filter
from storage.snapshot_search import QueryFailed
from tests.fake_drill_opensearch import FROM, TO, DrillOpenSearch, conn

LAN = build_lan_filter([(192, 168, 1)])
# three LAN sources with 3 connections each: three devices, one more than a cap of 2
DOCS = [
    conn(f"192.168.1.{10 + n}", "93.184.216.34", f"2026-11-05T10:0{i}:00.000Z")
    for n in range(3)
    for i in range(3)
]


@pytest.fixture
def clock():
    """time.monotonic() as api.devices sees it, starting with no event written."""
    now = {"t": 1_000_000.0}
    with (
        patch.object(devices, "_DEVICE_CAP", 2),
        patch.object(devices, "_cap_event_next_at", 0.0),
        patch.object(devices.time, "monotonic", lambda: now["t"]),
    ):
        yield now


def _read(changelog, what="device list"):
    app = {"lan_filter": LAN, "excluded_ips": [], "changelog_service": changelog}
    with pytest.raises(QueryFailed, match="stopped at"):
        _lan_device_buckets(
            DrillOpenSearch(DOCS), app, FROM, TO, page_size=1, what=what
        )


def _written(changelog) -> list[tuple]:
    return [c.args for c in changelog.log_event.call_args_list]


def test_a_capped_read_writes_one_event_and_still_fails(clock):
    changelog = MagicMock()
    changelog.log_event.return_value = {"_id": "a"}
    _read(changelog)
    [(event_type, title, description, metadata)] = _written(changelog)
    assert event_type == "device_cap_reached"
    assert title == "More than 2 LAN addresses in one window"
    assert "device list, the device count and the risk scores" in description
    assert metadata == {"limit": 2, "search": "device list"}


def test_reads_within_a_day_write_nothing_more_and_the_next_day_writes_again(clock):
    changelog = MagicMock()
    changelog.log_event.return_value = {"_id": "a"}
    _read(changelog)
    clock["t"] += 23 * 3600
    _read(changelog, "device registry refresh")
    assert len(_written(changelog)) == 1
    clock["t"] += 3600
    _read(changelog, "risk scores")
    assert len(_written(changelog)) == 2


def test_a_failed_write_is_tried_again_after_five_minutes_not_a_day(clock):
    changelog = MagicMock()
    changelog.log_event.return_value = {
        "_id": ""
    }  # ChangelogService when indexing fails
    _read(changelog)
    clock["t"] += 4 * 60
    _read(changelog)
    assert len(_written(changelog)) == 1
    changelog.log_event.return_value = {"_id": "b"}
    clock["t"] += 60
    _read(changelog)
    assert len(_written(changelog)) == 2
    clock["t"] += 3600
    _read(changelog)
    assert len(_written(changelog)) == 2  # written, so the day is used


def test_no_changelog_service_still_fails_the_read(clock):
    _read(None)


def test_a_read_under_the_cap_writes_nothing(clock):
    changelog = MagicMock()
    app = {"lan_filter": LAN, "excluded_ips": [], "changelog_service": changelog}
    with patch.object(devices, "_DEVICE_CAP", 4):  # a full last page reads as capped
        buckets = _lan_device_buckets(
            DrillOpenSearch(DOCS), app, FROM, TO, page_size=1, what="device list"
        )
    assert len(buckets) == 3
    changelog.log_event.assert_not_called()
