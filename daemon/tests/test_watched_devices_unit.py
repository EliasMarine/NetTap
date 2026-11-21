"""The watched-devices pieces on their own (NET-331): step rows, readiness, query bodies, the
state file and DeviceDetailsStore.watch_is."""

import os
import stat
import threading
from datetime import timedelta

import pytest

from services import watched_rules as wr
from services.device_details import DeviceDetailsStore
from tests.watched_rig import GATEWAY, MAC_D, MIRROR, Rig, at, iso

COVER = at("11:00")
CAPTURE = at("12:30")
NOW = at("12:31")


def _dev(state="up", **fields) -> dict:
    return {
        "enrolled_at": iso(at("11:00")),
        "after_min": 15,
        "state": state,
        "since": iso(at("11:05")),
        "seen_at": iso(at("12:00")),
        "silent_from": None,
        "incident": None,
        "pending": None,
        **fields,
    }


def _step(dev, seen=None, started=None, capture=CAPTURE, cover=COVER):
    return wr.step(dev, seen, started, capture, cover, NOW)


# --- §2.4, one row each --------------------------------------------------------


def test_unknown_with_a_connection_started_at_enrollment_goes_up():
    dev = _dev("unknown", since=None, seen_at=None, enrolled_at=iso(at("12:10")))
    new, event = _step(dev, seen=at("12:20"), started=at("12:10"))
    assert event is None
    assert (new["state"], new["seen_at"], new["since"]) == (
        "up",
        iso(at("12:20")),
        iso(NOW),
    )


def test_unknown_with_an_earlier_start_stays_unknown():
    dev = _dev("unknown", since=None, seen_at=None, enrolled_at=iso(at("12:10")))
    assert _step(dev, seen=at("12:20"), started=at("12:09", 59)) == (dev, None)
    assert _step(dev) == (dev, None)


def test_unknown_with_a_carried_incident_journals_its_recovery():
    incident = {"seen_at": iso(at("11:30")), "declared_at": iso(at("12:00"))}
    dev = _dev("unknown", enrolled_at=iso(at("12:10")), incident=incident)
    new, event = _step(dev, seen=at("12:21"), started=at("12:20"))
    assert new["state"] == "up" and new["incident"] is None
    assert event == {
        "type": "device_online",
        "instance": "up|" + iso(at("11:30")),
        "data": {
            "after_min": 15,
            "seen_at": iso(at("11:30")),
            "back_at": iso(at("12:20")),
            "away_min": 50,
        },
    }


def test_up_within_the_threshold_clears_the_streak():
    # 15 minutes plus the 10-minute writing allowance
    dev = _dev(silent_from=iso(at("12:20")), seen_at=iso(at("12:05")))
    new, event = _step(dev)
    assert event is None and new["silent_from"] is None


def test_up_over_the_threshold_starts_a_streak():
    dev = _dev(seen_at=iso(at("12:04", 59)))
    new, event = _step(dev)
    assert event is None and new["silent_from"] == iso(CAPTURE)


def test_up_over_the_threshold_for_240_s_goes_down():
    dev = _dev(silent_from=iso(at("12:26")))
    new, event = _step(dev)
    incident = {"seen_at": iso(at("12:00")), "declared_at": iso(NOW)}
    assert (new["state"], new["since"], new["incident"]) == ("down", iso(NOW), incident)
    assert event == {
        "type": "device_offline",
        "instance": "down|" + iso(at("12:00")),
        "data": {"after_min": 15, "seen_at": iso(at("12:00"))},
    }


def test_up_with_capture_advanced_under_240_s_is_unchanged():
    dev = _dev(silent_from=iso(at("12:26", 1)))
    assert _step(dev) == (dev, None)


def test_a_streak_from_before_the_coverage_start_counts_as_none():
    dev = _dev(silent_from=iso(at("12:00")))
    new, event = _step(dev, cover=at("12:01"))
    assert event is None and new["silent_from"] == iso(CAPTURE)


def test_silence_starts_at_the_coverage_start():
    dev = _dev(seen_at=iso(at("10:00")))
    new, event = _step(dev, cover=at("12:06"))
    assert event is None and new["silent_from"] is None


def test_up_takes_the_newer_sighting():
    new, _ = _step(_dev(), seen=at("12:29"), started=at("12:00"))
    assert new["seen_at"] == iso(at("12:29"))
    new, _ = _step(_dev(), seen=at("11:00"), started=at("11:00"))
    assert new["seen_at"] == iso(at("12:00"))


def test_down_recovers_only_on_a_connection_started_after_the_declaration():
    incident = {"seen_at": iso(at("11:00")), "declared_at": iso(at("12:00"))}
    dev = _dev("down", incident=incident)
    assert _step(dev, seen=at("12:29"), started=at("12:00")) == (dev, None)
    new, event = _step(dev, seen=at("12:29"), started=at("12:00", 1))
    assert new["state"] == "up" and new["seen_at"] == iso(at("12:29"))
    assert event["type"] == "device_online" and event["data"]["away_min"] == 60


def test_down_otherwise_keeps_its_incident_frozen():
    incident = {"seen_at": iso(at("11:00")), "declared_at": iso(at("12:00"))}
    dev = _dev("down", incident=incident)
    assert _step(dev) == (dev, None)


# --- readiness -----------------------------------------------------------------


def test_capture_scope_per_mode():
    assert wr.capture_scope(MIRROR) == ("mirror|enp1s0", None)
    assert wr.capture_scope({**MIRROR, "status": "degraded"}) == ("mirror|enp1s0", None)
    assert wr.capture_scope(GATEWAY) == ("dhcp_gateway|enp2s0|10.77.0.0/24", None)
    assert wr.capture_scope({**MIRROR, "status": "down"}) == (None, "capture is down")
    assert wr.capture_scope({**MIRROR, "link_up": False}) == (
        None,
        "the capture link is down",
    )
    assert wr.capture_scope({**GATEWAY, "status": "not_configured"}) == (
        None,
        "capture isn't set up",
    )
    assert wr.capture_scope({"mode": "tap"})[0] is None


# --- the query bodies ------------------------------------------------------------


def test_the_presence_body_asks_both_sides_lower_case_with_size_and_include():
    macs = ["aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02"]
    body = wr.presence_body(macs, NOW)
    for side, field in (("sent", "source.mac"), ("answered", "destination.mac")):
        terms = body["aggs"][side]["aggs"]["macs"]["terms"]
        assert terms == {"field": field, "size": 2, "include": macs}
    window = body["query"]["bool"]["filter"][1]["range"]["event.end"]
    assert window["lte"] == iso(NOW) and window["gte"] == iso(NOW - timedelta(hours=48))
    assert body["query"]["bool"]["filter"][0] == wr.CONN_RECORDS


def test_the_capture_body_reads_final_conn_records_up_to_now():
    body = wr.capture_body(NOW)
    first, window = body["query"]["bool"]["filter"]
    assert first == wr.CONN_ACCOUNTING
    assert window["range"]["event.end"]["lte"] == iso(NOW)
    assert window["range"]["event.end"]["gte"] == iso(NOW - timedelta(hours=1))


# --- the state file ------------------------------------------------------------


def test_the_state_file_is_private(tmp_path):
    rig = Rig(tmp_path)
    rig.watch()
    rig.check(at("12:00"))
    assert stat.S_IMODE(os.stat(rig.path).st_mode) == 0o600


def test_a_missing_file_starts_empty(tmp_path):
    rig = Rig(tmp_path)
    assert rig.watcher._read() == wr.empty_state()


# --- watch_is ------------------------------------------------------------------


def test_watch_is_yields_whether_the_watch_still_has_that_value(tmp_path):
    store = DeviceDetailsStore(str(tmp_path))
    store.update(MAC_D, {"watch_after_min": 15})
    with store.watch_is(MAC_D, 15) as still:
        assert still is True
    with store.watch_is(MAC_D, 30) as still:
        assert still is False
    with store.watch_is("AA:BB:CC:00:00:77", 15) as still:
        assert still is False


def test_watch_is_holds_the_store_lock(tmp_path):
    store = DeviceDetailsStore(str(tmp_path))
    store.update(MAC_D, {"watch_after_min": 15})
    editor = threading.Thread(
        target=store.update, args=(MAC_D, {"watch_after_min": 30})
    )
    with store.watch_is(MAC_D, 15) as still:
        got = store._lock.acquire(blocking=False)
        if got:
            store._lock.release()
        editor.start()  # its update can only land once the lock is released
    editor.join(5)
    assert still is True and not got  # the lock was held inside
    assert store.get(MAC_D)["watch_after_min"] == 30


def test_watch_is_on_a_damaged_store_yields_false(tmp_path):
    (tmp_path / "device_details.json").write_text("{broken")
    store = DeviceDetailsStore(str(tmp_path))
    with store.watch_is(MAC_D, 15) as still:
        assert still is False


@pytest.mark.parametrize("bad", ["nope", "AA:BB:CC:00:00:01:02"])
def test_watch_is_refuses_a_bad_mac(tmp_path, bad):
    store = DeviceDetailsStore(str(tmp_path))
    with pytest.raises(ValueError), store.watch_is(bad, 15):
        pass
