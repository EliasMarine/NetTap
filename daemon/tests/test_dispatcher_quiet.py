"""Quiet hours in the dispatcher (NET-330, plans/2026-11-20-f8-quiet-hours.md §4.3, §6).

Drives AlertDispatcher.poll_once through the event tests' harness, with quiet hours from
22:00 to 07:00 (UTC unless a test changes the zone) and a clock the test moves.
T0 is 2026-11-09 12:00 UTC, so 22:00 that day is minute 600 and 07:00 the next is minute 1140."""

import asyncio
import json
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from services import notification_dispatcher as nd
from services import quiet_hours as qh
from services.notification_dispatcher import QUIET_FULL, QUIET_PREAMBLE, AlertDispatcher
from services.notification_hub import body_limit
from tests.test_dispatcher_events import GB, EventHarness
from tests.test_notification_dispatcher import at, group

QUIET = {"enabled": True, "start": "22:00", "end": "07:00", "critical_through": True}


def m(day: int, hhmm: str, seconds: float = 0) -> float:
    """Minutes from T0 (12:00 UTC on day 0) to hh:mm UTC on `day`."""
    hours, minutes = map(int, hhmm.split(":"))
    return day * 1440 + hours * 60 + minutes - 720 + seconds / 60


class QuietHarness(EventHarness):
    def __init__(self, tmp_path):
        self.quiet = dict(QUIET)
        self.tz = "UTC"
        self.now = at(0)
        self.clock_shift = timedelta(0)
        self.quiet_error: Exception | None = None
        self.range_aware = False
        super().__init__(tmp_path)

    def window(self, now: datetime) -> qh.Hold | None:
        if self.quiet_error:
            raise self.quiet_error
        return qh.hold(now, self.quiet, self.tz)

    def new_dispatcher(self):
        return AlertDispatcher(
            self.hub,
            client=object(),
            lan_cidrs=lambda: [],
            state_path=str(self.tmp / "dispatch.json"),
            journal=self.journal,
            data_cap_now=self.data_cap_now,
            quiet=self.window,
            clock=lambda: self.now + self.clock_shift,
        )

    def poll(self, minutes):
        self.now = at(minutes)

        def fake_alerts(_client, from_ts, to_ts, *_args, **_kwargs):
            self.queries.append((from_ts, to_ts))
            if not self.range_aware:
                return list(self.groups)
            low, high = datetime.fromisoformat(from_ts), datetime.fromisoformat(to_ts)
            return [
                g
                for g in self.groups
                if low <= datetime.fromisoformat(g["last_seen"]) <= high
            ]

        async def fake_deliver(cid, title, body, severity):
            self.sent.append((cid, title, body, severity))
            if cid in self.refuse:
                return "refused"
            return "failed" if cid in self.fail else "sent"

        with (
            patch(
                "services.alert_intelligence.get_smart_alerts", side_effect=fake_alerts
            ),
            patch.object(self.hub, "deliver", side_effect=fake_deliver),
        ):
            asyncio.run(self.dispatcher.poll_once(self.now))

    def state(self, cid: str) -> dict:
        return json.loads((self.tmp / "dispatch.json").read_text())["channels"].get(
            cid, {}
        )

    def held_events(self, cid: str) -> list[dict]:
        return self.events_state()["channels"].get(cid, {}).get("events", [])


@pytest.fixture
def h(tmp_path):
    return QuietHarness(tmp_path)


def bodies(h, cid) -> list[str]:
    return [s[2] for s in h.sent_to(cid)]


# 1 ---------------------------------------------------------------------------


def test_an_alert_and_a_device_inside_the_window_are_held(h):
    h.groups = [group(1, 3, m(0, "23:00"))]
    h.device(1)
    h.poll(m(0, "23:00"))
    assert h.sent_to(h.all) == []
    assert h.state(h.all)["pending"][0]["held"] is True
    assert h.held_events(h.all)[0]["held"] is True


def test_outside_the_window_nothing_is_held(h):
    h.groups = [group(1, 3, m(0, "21:00"))]
    h.poll(m(0, "21:00"))
    assert len(h.sent_to(h.all)) == 1
    assert QUIET_PREAMBLE not in bodies(h, h.all)[0]


# 2 ---------------------------------------------------------------------------


def test_a_retry_falling_inside_the_window_is_held_with_its_attempts(h):
    h.groups = [group(1, 3, m(0, "21:59"))]
    h.fail.add(h.all)
    h.poll(m(0, "21:59"))
    assert len(h.take()) == 1  # failed; retries at 22:00
    h.fail.clear()
    h.poll(m(0, "22:00"))
    assert h.sent_to(h.all) == []
    [item] = h.state(h.all)["pending"]
    assert item["attempts"] == 1 and item["held"] is True


# 3 ---------------------------------------------------------------------------


def test_the_hourly_slot_inside_the_window_holds_and_a_held_critical_stays_held(
    h, monkeypatch
):
    monkeypatch.setattr(nd, "DAILY_BUDGET", 1)
    h.groups = [group(1, 3, m(0, "21:30"))]
    h.poll(m(0, "21:30"))  # the day's one message; next slot 22:30
    h.take()
    h.groups = [group(2, 3, m(0, "22:30"))]
    h.poll(m(0, "22:30"))
    assert h.sent_to(h.all) == []
    h.quiet["critical_through"] = False
    h.groups = [group(3, 1, m(0, "23:30"))]
    h.poll(m(0, "23:30"))
    assert h.sent_to(h.all) == []
    held = {i["sig"] for i in h.state(h.all)["pending"] if i.get("held")}
    assert {"2", "3"} <= held


# 4 ---------------------------------------------------------------------------


def test_a_critical_during_a_hold_goes_alone_and_a_waiting_alert_stays(h):
    h.groups = [group(1, 3, m(0, "21:58"))]
    h.fail.add(h.all)
    h.poll(m(0, "21:58"))  # fails: A waits on its retry
    h.fail.clear()
    h.take()
    h.device(1)
    h.poll(m(0, "22:05"))  # A and the device held
    assert h.take() == []
    h.groups = [group(1, 3, m(0, "21:58")), group(9, 1, m(0, "23:00"))]
    h.poll(m(0, "23:00"))
    [(_, title, body, severity)] = h.sent_to(h.all)
    assert severity == 1 and "signature 9" in title
    assert "signature 1" not in body and QUIET_PREAMBLE not in body
    assert [i["sig"] for i in h.state(h.all)["pending"]] == ["1"]
    h.take()
    h.restart()
    h.groups = []
    h.poll(m(1, "07:00", 30))
    [body] = bodies(h, h.all)
    assert body.startswith(QUIET_PREAMBLE)
    assert "signature 1" in body and "New device" in body


def test_never_holds_nothing(h):
    h.quiet["enabled"] = False
    h.groups = [group(1, 3, m(0, "23:00"))]
    h.device(1)
    h.poll(m(0, "23:00"))
    [body] = bodies(h, h.all)
    assert "signature 1" in body and "New device" in body
    assert QUIET_PREAMBLE not in body


# 5 ---------------------------------------------------------------------------


def test_a_held_only_poll_keeps_a_refusal_throttle_for_a_later_critical(h, monkeypatch):
    monkeypatch.setattr(nd, "RETRY_AFTER", (timedelta(minutes=30),))
    h.device(1)
    h.refuse.add(h.all)
    h.poll(m(0, "21:55"))  # refused: retries at 22:25
    h.refuse.clear()
    h.take()
    h.poll(m(0, "22:00"))  # held only
    h.restart()
    h.groups = [group(9, 1, m(0, "22:01"))]
    h.poll(m(0, "22:01"))
    assert h.sent_to(h.all) == []  # waits for the throttle
    assert h.state(h.all)["retry_at"]
    h.poll(m(0, "22:25"))
    [(_, title, _, _)] = h.sent_to(h.all)
    assert "signature 9" in title


# 6 ---------------------------------------------------------------------------


def test_the_release_is_one_message_with_the_heading_and_cap_lines_first(h):
    h.groups = [group(1, 3, m(0, "23:00")), group(2, 4, m(0, "23:10"))]
    h.device(1)
    h.cap_warning("80")
    h.cap_warning("100", used=101 * GB)
    h.poll(m(0, "23:00"))
    assert h.take() == []
    h.groups = []
    h.poll(m(1, "07:00", 30))
    [body] = bodies(h, h.all)
    assert body.startswith(QUIET_PREAMBLE)
    lines = body[len(QUIET_PREAMBLE) :].split("\n")
    assert "cap used" in lines[0] and "cap used" in lines[1]
    assert "signature 1" in body and "signature 2" in body and "New device" in body
    h.take()
    h.poll(m(1, "07:01", 30))
    assert h.sent_to(h.all) == []
    assert h.held_events(h.all) == []


def test_a_clipped_pushover_release_is_one_post_with_both_cap_warnings(h):
    po = h.channel("pushover")
    h.groups = [group(100 + n, 2, m(0, "23:00")) for n in range(15)]
    h.cap_warning("80")
    h.cap_warning("100", used=101 * GB)
    h.poll(m(0, "23:00"))
    h.groups = []
    h.poll(m(1, "07:00", 30))
    h.poll(m(1, "07:01", 30))
    [body] = bodies(h, po)
    assert len(body) <= body_limit("pushover")
    assert body.count("cap used") == 2


@pytest.mark.parametrize("held", ["device", "cap"])
def test_a_held_item_ranked_eleventh_still_makes_a_release(h, held):
    if held == "device":
        h.device(1)
    else:
        h.cap_warning("80")
    h.poll(m(0, "23:00"))
    h.groups = [group(200 + n, 2, m(1, "07:00")) for n in range(10)]
    h.poll(m(1, "07:00", 30))
    [body] = bodies(h, h.all)
    assert body.startswith(QUIET_PREAMBLE)
    if held == "cap":
        assert "cap used" in body


# 7 ---------------------------------------------------------------------------


def test_turning_quiet_hours_off_mid_window_releases_at_the_next_poll(h):
    h.groups = [group(1, 3, m(0, "23:00"))]
    h.poll(m(0, "23:00"))
    h.quiet["enabled"] = False
    h.poll(m(0, "23:01"))
    [body] = bodies(h, h.all)
    assert body.startswith(QUIET_PREAMBLE) and "signature 1" in body


def test_an_earlier_end_releases_at_the_new_end(h):
    h.groups = [group(1, 3, m(0, "23:00"))]
    h.poll(m(0, "23:00"))
    h.quiet["end"] = "05:00"
    h.poll(m(1, "04:59"))
    assert h.sent_to(h.all) == []
    h.poll(m(1, "05:00", 30))
    assert len(h.sent_to(h.all)) == 1


def test_an_owner_zone_change_moves_the_window(h):
    h.tz = "America/New_York"  # 22:00 in New York is 03:00 UTC (EST)
    h.groups = [group(1, 3, m(0, "23:00"))]
    h.poll(m(0, "23:00"))  # 18:00 in New York: not quiet
    assert len(h.take()) == 1
    h.groups = [group(2, 3, m(1, "04:00"))]
    h.poll(m(1, "04:00"))  # 23:00 in New York: quiet
    assert h.sent_to(h.all) == []


# 8 ---------------------------------------------------------------------------


def test_a_restart_mid_window_keeps_holding_and_releases_once(h):
    h.groups = [group(1, 3, m(0, "23:00"))]
    h.device(1)
    h.poll(m(0, "23:00"))
    h.restart()
    h.poll(m(1, "03:00"))
    assert h.sent_to(h.all) == []
    h.groups = []
    h.poll(m(1, "07:00", 30))
    h.restart()
    h.poll(m(1, "07:01", 30))
    assert len(h.sent_to(h.all)) == 1


def test_stopped_before_the_end_and_restarted_at_night_holds_until_morning(h):
    h.groups = [group(1, 3, m(0, "23:00"))]
    h.poll(m(0, "23:00"))
    h.restart()  # stopped at 06:55, back at 23:00 the next night
    h.groups = []
    h.poll(m(1, "23:00"))
    assert h.sent_to(h.all) == []
    h.poll(m(2, "07:00", 30))
    [body] = bodies(h, h.all)
    assert body.startswith(QUIET_PREAMBLE) and "signature 1" in body


def test_a_morning_release_failing_until_night_is_held_again(h):
    h.device(1)
    h.poll(m(0, "23:00"))
    h.fail.add(h.all)
    h.poll(m(1, "07:00", 30))
    assert len(h.take()) == 1  # failed
    h.fail.clear()
    h.poll(m(1, "23:00"))  # the channel is back, but it is night again
    assert h.sent_to(h.all) == []
    h.poll(m(2, "07:00", 30))
    [body] = bodies(h, h.all)
    assert body.startswith(QUIET_PREAMBLE) and "New device" in body


# 9 ---------------------------------------------------------------------------


def test_a_held_device_survives_a_critical_send_that_did_not_carry_it(h):
    h.device(1)
    h.poll(m(0, "23:00"))
    h.groups = [group(9, 1, m(0, "23:30"))]
    h.poll(m(0, "23:30"))
    assert len(h.sent_to(h.all)) == 1
    h.take()
    assert len(h.held_events(h.all)) == 1


def test_a_cap_warning_held_for_another_cap_survives_a_critical_and_is_released(h):
    h.cap_warning("80")
    h.cap_now = ("2026-11", 200 * GB)  # the owner changed the cap
    h.poll(m(0, "23:00"))
    h.groups = [group(9, 1, m(0, "23:30"))]
    h.poll(m(0, "23:30"))
    assert len(h.sent_to(h.all)) == 1
    h.take()
    h.cap_now = ("2026-11", 100 * GB)  # and changed it back
    h.groups = []
    h.poll(m(1, "07:00", 30))
    [body] = bodies(h, h.all)
    assert body.startswith(QUIET_PREAMBLE) and "cap used" in body


def test_a_held_queue_s_overflow_count_waits_for_the_release(h):
    for n in range(600):
        h.device(n)
    for minute in ("23:00", "23:01", "23:02"):  # 200 journal entries a poll
        h.poll(m(0, minute))
    q = h.dispatcher._events["channels"][h.all]
    assert (len(q["events"]), q["overflow"]) == (500, 100)
    h.groups = [group(9, 1, m(0, "23:30"))]
    h.poll(m(0, "23:30"))
    [critical] = bodies(h, h.all)
    assert "more events not listed" not in critical
    h.take()
    h.groups = []
    h.poll(m(1, "07:00", 30))
    [body] = bodies(h, h.all)
    assert body.startswith(QUIET_PREAMBLE)
    assert "and 100 more events not listed; see NetTap" in body
    assert h.dispatcher._events["channels"] == {}


# 10 --------------------------------------------------------------------------


def test_sixty_held_alerts_keep_the_worst_fifty(h):
    h.groups = [group(300 + n, 2 if n < 30 else 4, m(0, "23:00")) for n in range(60)]
    h.poll(m(0, "23:00"))
    pending = h.state(h.all)["pending"]
    assert len(pending) == nd.MAX_PENDING
    assert sum(1 for i in pending if i["severity"] == 2) == 30


@pytest.mark.parametrize(("seen", "returns"), [("22:59", True), ("22:10", False)])
def test_the_fifty_first_critical_comes_back_only_inside_the_overlap(h, seen, returns):
    h.range_aware = True
    h.poll(m(0, "22:00"))  # the cursor
    h.groups = [
        group(400 + n, 1, m(0, seen), count=100 - n) for n in range(nd.MAX_PENDING + 1)
    ]
    h.poll(m(0, "23:00"))
    [first] = bodies(h, h.all)
    assert "signature 450" not in first
    h.take()
    h.restart()
    h.poll(m(0, "23:01"))
    sent = bodies(h, h.all)
    assert bool(sent) is returns
    if returns:
        assert "signature 450" in sent[0]


def test_a_held_critical_keeps_its_own_observation_when_a_milder_one_follows(h):
    h.quiet["critical_through"] = False
    h.groups = [group(7, 1, m(0, "23:00"), src="192.0.2.1", dst="192.0.2.2", count=1)]
    h.poll(m(0, "23:00"))
    h.groups = [
        group(7, 3, m(1, "04:00"), src="198.51.100.3", dst="198.51.100.4", count=800)
    ]
    h.poll(m(1, "04:00"))
    h.restart()
    h.groups = []
    h.poll(m(1, "07:00", 30))
    [body] = bodies(h, h.all)
    assert "- [critical] ET TEST signature 7: 1 event, 192.0.2.1 → 192.0.2.2" in body
    assert "800" not in body


def test_held_items_are_kept_ahead_of_fresh_ones_at_the_release(h):
    h.groups = [group(1, 3, m(0, "23:00"))]
    h.poll(m(0, "23:00"))
    h.groups = [
        group(500 + n, 2, m(1, "07:00"), count=100 - n) for n in range(nd.MAX_PENDING)
    ]
    h.poll(m(1, "07:00", 30))
    [body] = bodies(h, h.all)
    assert body.startswith(QUIET_PREAMBLE)
    h.take()
    h.poll(m(1, "07:01", 30))  # the one fresh alert cut goes now
    [body] = bodies(h, h.all)
    assert "signature 549" in body


def test_a_critical_at_the_end_of_a_full_night_survives_a_failing_release(h):
    # ponytail review: a fresh critical ranked behind 50 held alerts was cut while the morning
    # send failed, until it left the query's overlap and was never sent
    h.range_aware = True
    h.poll(m(0, "22:00"))  # the cursor
    held = [group(600 + n, 4, m(0, "23:00")) for n in range(nd.MAX_PENDING)]
    h.groups = held
    h.poll(m(0, "23:00"))
    h.fail.add(h.all)
    h.groups = [*held, group(999, 1, m(1, "07:00"))]
    for minute in range(6):
        h.poll(m(1, f"07:{minute:02d}", 30))
    h.fail.clear()
    h.take()
    for minute in range(6, 12):
        h.poll(m(1, f"07:{minute:02d}", 30))
    assert any("signature 999" in body for body in bodies(h, h.all))


def test_criticals_ahead_of_a_full_held_queue_still_say_it_was_full(h):
    h.groups = [group(600 + n, 3, m(0, "23:00")) for n in range(nd.MAX_PENDING)]
    h.poll(m(0, "23:00"))
    h.groups = [group(900 + n, 1, m(1, "07:00")) for n in range(3)]
    h.poll(m(1, "07:00", 30))
    [body] = bodies(h, h.all)
    assert body.startswith(QUIET_PREAMBLE) and QUIET_FULL in body


def test_a_full_held_queue_says_so_and_fits_pushover(h):
    po = h.channel("pushover")
    h.groups = [group(600 + n, 3, m(0, "23:00")) for n in range(nd.MAX_PENDING + 5)]
    h.poll(m(0, "23:00"))
    h.groups = []
    h.poll(m(1, "07:00", 30))
    [body] = bodies(h, po)
    assert QUIET_FULL in body
    assert len(body) <= body_limit("pushover")


# 11 --------------------------------------------------------------------------


def test_state_from_before_quiet_hours_follows_the_rule(h):
    h.groups = [group(1, 3, m(0, "21:00"))]
    h.device(1)
    h.fail.add(h.all)
    h.poll(m(0, "21:00"))  # queued, without any flag
    h.fail.clear()
    h.take()
    for path in ("dispatch.json", "notification-events.json"):
        assert '"held"' not in (h.tmp / path).read_text()
    h.restart()
    h.groups = []
    h.poll(m(0, "23:00"))
    assert h.sent_to(h.all) == []
    h.poll(m(1, "07:00", 30))
    [body] = bodies(h, h.all)
    assert body.startswith(QUIET_PREAMBLE)


# 12 --------------------------------------------------------------------------


def test_a_window_that_cannot_be_read_sends_as_usual(h, caplog):
    h.quiet_error = ValueError("bad zone")
    h.groups = [group(1, 3, m(0, "23:00"))]
    h.poll(m(0, "23:00"))
    assert len(h.sent_to(h.all)) == 1
    assert "Quiet hours can't be read" in caplog.text


def test_the_decision_uses_the_clock_at_send_time(h):
    h.groups = [group(1, 3, m(0, "21:59"))]
    h.clock_shift = timedelta(seconds=10)  # the query took until 22:00:05
    h.poll(m(0, "21:59", 55))
    assert h.sent_to(h.all) == []


# 13 --------------------------------------------------------------------------


def test_create_app_wires_quiet_hours_in_the_owner_zone(tmp_path):
    from api.server import create_app
    from storage.manager import RetentionConfig, StorageManager

    config = tmp_path / "notifications.json"
    config.write_text(json.dumps({"channels": {}, "rules": {}, "quiet": QUIET}))
    tz_file = tmp_path / "owner-timezone.json"
    tz_file.write_text(json.dumps({"tz": "America/New_York"}))
    client = MagicMock(**{"search.return_value": {}})
    with patch.object(StorageManager, "_create_client", return_value=client):
        storage = StorageManager(RetentionConfig(), "http://localhost:9200")
    env = {
        "DAEMON_TOKEN_FILE": str(tmp_path / "auth" / "token"),
        "EXCLUDED_IPS_FILE": str(tmp_path / "excluded_ips.json"),
        "NOTIFICATION_CONFIG": str(config),
        "OWNER_TZ_FILE": str(tz_file),
    }
    with patch.dict(os.environ, env):
        app = create_app(storage, MagicMock(), "http://localhost:9200")
        ask = app["alert_dispatcher"]._quiet
        # 23:00 in New York (04:00 UTC) is quiet; 23:00 UTC (18:00 there) isn't
        assert ask(at(m(1, "04:00"))) is not None
        assert ask(at(m(0, "23:00"))) is None
