"""Watched devices' offline and online events in the dispatcher (F5, NET-331).

plans/2026-11-20-f5-watched-devices.md §2.3 (the shared journal fix), §2.5 and §5. Drives
AlertDispatcher.poll_once through the event tests' harness, with a watched_device rule on the
"all" channel (a custom channel, so every delivery here goes through a custom channel's rule)."""

import re
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from services import notification_dispatcher as nd
from services import watch_events as we
from services.notification_dispatcher import QUIET_PREAMBLE
from services.notification_hub import body_limit
from tests.test_dispatcher_events import CREDENTIALS, EventHarness
from tests.test_dispatcher_quiet import QuietHarness, m
from tests.test_notification_dispatcher import group

SEEN = "2026-11-09T11:40:00+00:00"
BACK = "2026-11-09T12:41:00+00:00"
T_FLAP = datetime(2026, 11, 1, tzinfo=timezone.utc)
# not the new-device harness's AA:BB:CC:00:… MACs
_WATCH_MAC = re.compile(r"02:00:00:00:00:[0-9A-F]{2}")


def mac(n: int) -> str:
    return f"02:00:00:00:00:{n:02X}"


def offline_data(n: int, seen_at: str = SEEN, **change) -> dict:
    """As the watched-devices job journals it: the upper-case canonical MAC."""
    return {
        "mac": mac(n),
        "name": None,
        "after_min": 15,
        "seen_at": seen_at,
        **change,
    }


def online_data(n: int, seen_at: str = SEEN, back_at: str = BACK, **change) -> dict:
    return {
        **offline_data(n, seen_at),
        "back_at": back_at,
        "away_min": 61,
        **change,
    }


def offline(journal, n: int, seen_at: str = SEEN, **change) -> None:
    journal.append(
        we.OFFLINE,
        mac(n),
        seen_at,
        offline_data(n, seen_at, **change),
        instance=f"down|{seen_at}",
    )


def online(journal, n: int, seen_at: str = SEEN, back_at: str = BACK, **change) -> None:
    journal.append(
        we.ONLINE,
        mac(n),
        back_at,
        online_data(n, seen_at, back_at, **change),
        instance=f"up|{seen_at}",
    )


def entry(kind: str, data) -> dict:
    return {
        "id": "e1",
        "seq": 7,
        "type": kind,
        "key": "02:00:00:00:00:01",
        "data": data,
    }


def watched(text: str) -> list[str]:
    return _WATCH_MAC.findall(text)


@pytest.fixture
def h(tmp_path):
    harness = EventHarness(tmp_path)
    harness.hub.add_rule(we.EVENT, [harness.all], 4)
    return harness


@pytest.fixture
def q(tmp_path):
    """Quiet hours 22:00 to 07:00 UTC (the quiet tests' harness)."""
    harness = QuietHarness(tmp_path)
    harness.hub.add_rule(we.EVENT, [harness.all], 4)
    return harness


# --- the item: severity, title and line ------------------------------------------------------


def test_an_offline_entry_is_a_high_item_with_its_time_and_limit():
    item = nd.event_item(entry(we.OFFLINE, offline_data(1, name="Kitchen display")))
    label = "Kitchen display (02:00:00:00:00:01)"
    assert item == {
        "sig": "event:e1",
        "event": "watched_device",
        "severity": 2,
        "title": f"Offline: {label}",
        "line": f"{label}: no sighting since 2026-11-09 11:40 UTC, longer than its 15-minute limit",
        "count": 1,
        "attempts": 0,
        "watch_mac": "02:00:00:00:00:01",
    }


def test_an_online_entry_is_a_low_item_with_its_time_and_time_away():
    item = nd.event_item(entry(we.ONLINE, online_data(1, after_min=60)))
    assert (item["severity"], item["title"]) == (4, "Back online: 02:00:00:00:00:01")
    assert item["line"] == (
        "02:00:00:00:00:01: seen again at 2026-11-09 12:41 UTC, "
        "61 minutes after the last confirmed sighting"
    )


@pytest.mark.parametrize(
    "after_min, words", [(30, "30-minute"), (60, "1-hour"), (1440, "24-hour")]
)
def test_the_limit_reads_as_the_owner_picked_it(after_min, words):
    item = nd.event_item(entry(we.OFFLINE, offline_data(1, after_min=after_min)))
    assert item["line"].endswith(f"longer than its {words} limit")


@pytest.mark.parametrize(
    "away_min, words",
    [
        (1, "1 minute"),
        (61, "61 minutes"),
        (119, "119 minutes"),
        (120, "2 hours"),
        (121, "2 hours 1 minute"),
        (185, "3 hours 5 minutes"),
        (2879, "47 hours 59 minutes"),
        (2880, "2 days"),
        (2941, "2 days 1 hour"),
        (4320, "3 days"),
        (4380, "3 days 1 hour"),  # minutes past the hour aren't shown
        (1_500_000, "1,041 days 16 hours"),
    ],
)
def test_the_time_away_reads_as_a_person_says_it(away_min, words):
    item = nd.event_item(entry(we.ONLINE, online_data(1, away_min=away_min)))
    assert item["line"].endswith(f", {words} after the last confirmed sighting")


@pytest.mark.parametrize(
    "name",
    [
        None,
        "",
        "   ",
        "Kitchen\ndisplay",  # two lines
        "Kitchen display",  # a line separator
        "Kitchen ‮display",  # a bidi override that spoofs text
        "Kitchen\x07display",  # a control character
    ],
)
def test_a_missing_or_unsafe_name_falls_back_to_the_mac_alone(name):
    item = nd.event_item(entry(we.OFFLINE, offline_data(1, name=name)))
    assert item["title"] == "Offline: 02:00:00:00:00:01"
    assert item["line"].startswith("02:00:00:00:00:01: no sighting")


def test_a_long_name_is_clipped_to_64():
    item = nd.event_item(entry(we.OFFLINE, offline_data(1, name="N" * 100)))
    assert item["title"] == f"Offline: {'N' * 63}… (02:00:00:00:00:01)"


@pytest.mark.parametrize(
    "kind, data",
    [
        (we.OFFLINE, ["not", "a", "dict"]),
        (we.OFFLINE, None),
        (we.OFFLINE, offline_data(1, mac="02:00:00:00:00")),  # five octets
        (we.OFFLINE, offline_data(1, mac=None)),
        (we.OFFLINE, offline_data(1, after_min=0)),
        (we.OFFLINE, offline_data(1, after_min=True)),  # a bool is an int to Python
        (we.OFFLINE, offline_data(1, after_min="15")),
        (we.OFFLINE, offline_data(1, seen_at="yesterday")),
        (we.OFFLINE, offline_data(1, seen_at=None)),
        (we.OFFLINE, offline_data(1, name=42)),
        (we.ONLINE, offline_data(1)),  # no back_at or away_min
        (we.ONLINE, online_data(1, back_at="soon")),
        (we.ONLINE, online_data(1, away_min=0)),
        (we.ONLINE, online_data(1, away_min=-5)),
    ],
)
def test_wrong_shaped_data_gives_nothing(kind, data):
    assert nd.event_item(entry(kind, data)) is None


def test_an_offline_reaches_the_channel_its_custom_rule_names(h):
    offline(h.journal, 1, name="Kitchen display")
    h.poll(1)
    [msg] = h.sent_to(h.all)
    assert (msg[1], msg[3]) == ("Offline: Kitchen display (02:00:00:00:00:01)", 2)
    assert "- [high] Kitchen display (02:00:00:00:00:01): no sighting since" in msg[2]
    assert h.sent_to(h.high) == []  # no watched-device rule there
    assert h.events_state()["channels"] == {}


# --- quiet hours, and one queued item per device ----------------------------------------------


def test_quiet_hours_hold_an_offline_until_the_window_ends(q):
    offline(q.journal, 1, seen_at="2026-11-09T22:40:00+00:00")
    q.poll(m(0, "23:00"))
    assert q.sent_to(q.all) == []
    [held] = q.held_events(q.all)
    assert held["held"] is True
    q.poll(m(1, "07:00"))
    [msg] = q.sent_to(q.all)
    assert msg[2].startswith(QUIET_PREAMBLE)
    assert "no sighting since 2026-11-09 22:40 UTC" in msg[2]


@pytest.mark.parametrize("poll_between", [True, False])
def test_down_up_down_while_held_leaves_one_item_the_newest(q, poll_between):
    first, second = "2026-11-09T22:30:00+00:00", "2026-11-10T02:00:00+00:00"
    offline(q.journal, 1, seen_at=first)
    if poll_between:
        q.poll(m(0, "23:00"))
    online(q.journal, 1, seen_at=first, back_at="2026-11-10T01:10:00+00:00")
    if poll_between:
        q.poll(m(1, "01:15"))
    offline(q.journal, 1, seen_at=second)
    q.poll(m(1, "03:00"))
    assert q.sent_to(q.all) == []
    [held] = q.held_events(q.all)
    assert held["title"] == "Offline: 02:00:00:00:00:01"
    assert "since 2026-11-10 02:00 UTC" in held["line"]
    q.poll(m(1, "07:00"))
    [msg] = q.sent_to(q.all)
    assert msg[1] == "Offline: 02:00:00:00:00:01"
    assert watched(msg[2]) == ["02:00:00:00:00:01"]  # one line for the device
    assert "since 2026-11-10 02:00 UTC" in msg[2] and "Back online" not in msg[2]


def test_a_high_only_channel_keeps_no_stale_offline(h):
    h.hub.add_rule(we.EVENT, [h.high], 2)  # high and above: offline, never online
    h.fail = {h.high, h.all}
    offline(h.journal, 1)
    h.poll(1)
    assert [e["title"] for e in h.queued(h.high)] == ["Offline: 02:00:00:00:00:01"]
    online(h.journal, 1)
    h.poll(3)
    assert h.queued(h.high) == []
    assert [e["title"] for e in h.queued(h.all)] == ["Back online: 02:00:00:00:00:01"]
    h.take()
    h.fail = set()
    h.poll(30)
    assert h.sent_to(h.high) == []
    [msg] = h.sent_to(h.all)
    assert msg[1] == "Back online: 02:00:00:00:00:01"


# --- the catch-up guard ------------------------------------------------------------------------


def _offline_then_online_at_a_page_boundary(h) -> None:
    for n in range(nd.INTAKE - 1):
        h.device(n)
    offline(h.journal, 1)  # seq 200, the last of the first page
    online(h.journal, 1)  # seq 201


def test_an_offline_ending_a_full_page_waits_for_the_next_read(h):
    _offline_then_online_at_a_page_boundary(h)
    h.poll(1)
    assert h.events_state()["journal_seq"] == nd.INTAKE
    assert len(h.sent_to(h.all)) == 1  # the new devices went
    assert [e["title"] for e in h.queued(h.all)] == ["Offline: 02:00:00:00:00:01"]
    h.poll(2)
    sends = h.sent_to(h.all)
    assert not any("no sighting" in s[2] or s[1].startswith("Offline") for s in sends)
    assert sends[-1][1] == "Back online: 02:00:00:00:00:01"
    assert h.queued(h.all) == []


def test_a_failed_second_read_holds_watch_items_while_alerts_go(h):
    _offline_then_online_at_a_page_boundary(h)
    h.poll(1)
    h.take()
    h.groups = [group(1, 2, 2)]
    with patch.object(h.journal, "after", side_effect=OSError(5, "I/O error")):
        h.poll(2)
    [alert] = h.sent_to(h.all)
    assert alert[1] == "High alert: ET TEST signature 1"
    assert "no sighting" not in alert[2]
    assert [e["title"] for e in h.queued(h.all)] == ["Offline: 02:00:00:00:00:01"]
    assert h.events_state()["journal_seq"] == nd.INTAKE  # the cursor stayed
    h.take()
    h.groups = []
    h.poll(3)
    [msg] = h.sent_to(h.all)
    assert msg[1] == "Back online: 02:00:00:00:00:01"


def test_a_journal_unreadable_at_start_up_moves_nothing_and_recovers_without_an_append(
    h,
):
    path = h.tmp / "events.jsonl"
    for n in range(3):
        h.device(n)
    h.poll(1)
    h.device(3)
    offline(h.journal, 1)  # seq 5: journalled, not yet taken
    path.rename(h.tmp / "events.bak")
    path.mkdir()  # reading it now fails with IsADirectoryError, not FileNotFoundError
    h.restart()
    h.take()
    assert not h.journal.available
    h.poll(2)
    assert h.sent_to(h.all) == []
    # not read as a reset: neither the cursor nor the replay floor moved
    assert h.events_state()["journal_seq"] == 3
    assert h.dispatcher.committed_seq == 3
    assert h.dispatcher._replay_floor is None
    path.rmdir()
    (h.tmp / "events.bak").rename(path)
    h.poll(3)  # no producer appended: this poll's reload finds it
    assert h.journal.available
    [msg] = h.sent_to(h.all)
    assert "New device AA:BB:CC:00:00:03" in msg[2]
    assert "02:00:00:00:00:01: no sighting since" in msg[2]
    assert h.events_state() == {"journal_seq": 5, "channels": {}}


# --- carry-over, severity order and the queue bound ---------------------------------------------


def test_eleven_outages_at_pushover_s_limit_all_go_over_the_next_messages(h):
    po = h.hub.configure("pushover", CREDENTIALS["pushover"])["id"]
    h.hub.add_rule(we.EVENT, [po], 4)
    for n in range(11):
        offline(h.journal, n, name=f"{n:02d} " + "N" * 60)
    for minute in range(1, 6):
        h.poll(minute)
    bodies = [s[2] for s in h.sent_to(po)]
    assert all(len(b) <= body_limit("pushover") for b in bodies)
    # the length limit, not the 10-line cap, split them
    assert len(watched(bodies[0])) < nd.DIGEST_LINES
    shown = [found for b in bodies for found in watched(b)]
    assert sorted(shown) == sorted(mac(n) for n in range(11))  # each once, none lost
    assert h.queued(po) == []


def test_ten_recoveries_never_push_out_a_medium_alert(h):
    h.groups = [group(1, 3, 0)]
    for n in range(10):
        online(h.journal, n)
    h.poll(1)
    [first] = h.sent_to(h.all)
    assert first[2].startswith("- [medium] ET TEST signature 1")
    assert len(watched(first[2])) == nd.DIGEST_LINES - 1
    h.poll(2)
    second = h.sent_to(h.all)[1]
    assert len(watched(second[2])) == 1
    assert not set(watched(first[2])) & set(watched(second[2]))
    assert h.queued(h.all) == []


def test_a_flapping_device_leaves_one_queued_item_that_no_flood_trims(h):
    h.fail = {h.all}
    for k in range(300):  # 600 entries, three full pages
        seen = (T_FLAP + timedelta(minutes=k)).isoformat()
        offline(h.journal, 1, seen_at=seen)
        online(h.journal, 1, seen_at=seen, back_at=BACK)
    for n in range(nd.MAX_EVENTS + 100):  # then a new-device flood past the queue's cap
        h.device(n)
    for minute in (1, 3, 9, 25, 60, 120, 240):
        h.poll(minute)
    q = h.dispatcher._events["channels"][h.all]
    [item] = [e for e in q["events"] if e["event"] == we.EVENT]
    assert item["title"] == "Back online: 02:00:00:00:00:01"
    assert (len(q["events"]), q["overflow"]) == (nd.MAX_EVENTS, 101)  # devices went
    h.take()
    h.fail = set()
    h.poll(480)  # the devices fill the message; the low "Back online" is carried over
    assert [e["event"] for e in h.queued(h.all)] == [we.EVENT]
    h.poll(481)
    first, second = h.sent_to(h.all)
    assert "seen again" not in first[2]
    assert second[1] == "Back online: 02:00:00:00:00:01"


def test_trim_keeps_a_watch_item_past_the_queue_cap():
    watch = nd.event_item(entry(we.OFFLINE, offline_data(1)))
    devices = [
        {"sig": f"d{n}", "event": "new_device", "severity": 3} for n in range(500)
    ]
    kept, gone = nd._trim([watch, *devices])
    assert gone == 1
    assert kept[0] is watch and kept[1:] == devices[1:]


def test_a_poll_with_only_deferred_watch_items_keeps_a_refusal_back_off(h):
    w = h.hub.configure("webhook", {"url": "https://hooks.example.net/w"})["id"]
    h.hub.add_rule(
        we.EVENT, [w], 4
    )  # watched devices only, so nothing else is due there
    h.refuse = {w}  # a wrong password: each try counts against the account
    offline(h.journal, 1)
    h.poll(1)  # refused: the next try waits a minute
    for n in range(nd.INTAKE):
        h.device(n)  # a full page for "all", so the watch item is deferred
    h.poll(1.5)
    h.poll(1.75)  # caught up, still inside the back-off
    assert len(h.sent_to(w)) == 1
    h.poll(2.5)
    assert len(h.sent_to(w)) == 2
