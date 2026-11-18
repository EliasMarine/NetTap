"""Journal events reach the channels with the alerts' limits, and are never lost (NET-319).

Drives AlertDispatcher.poll_once through the alert tests' Harness, with an event journal and a
new-device rule on the "all" channel."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from services import notification_dispatcher as nd
from services.event_journal import EventJournal
from services.notification_dispatcher import AlertDispatcher
from tests.test_notification_dispatcher import Harness, group


class EventHarness(Harness):
    def __init__(self, tmp_path):
        self.journal = EventJournal(str(tmp_path / "events.jsonl"))
        super().__init__(tmp_path)
        self.hub.add_rule("new_device", [self.all], 4)

    def new_dispatcher(self):
        return AlertDispatcher(
            self.hub,
            client=object(),
            lan_cidrs=lambda: [],
            state_path=str(self.tmp / "dispatch.json"),
            journal=self.journal,
        )

    def device(self, n: int, vendor: str | None = "Acme") -> None:
        mac = f"AA:BB:CC:00:{n // 256:02X}:{n % 256:02X}"
        self.journal.append(
            "new_device",
            mac,
            "2026-11-09T11:58:00+00:00",
            {"ip": f"192.0.2.{n % 250}", "vendor": vendor, "source": "conn"},
            instance="",
        )

    def restart(self) -> None:
        self.journal = EventJournal(str(self.tmp / "events.jsonl"))
        self.dispatcher = self.new_dispatcher()

    def events_state(self) -> dict:
        return json.loads((self.tmp / "notification-events.json").read_text())


@pytest.fixture
def h(tmp_path):
    return EventHarness(tmp_path)


def test_a_new_device_reaches_the_channels_its_rule_names(h):
    h.device(1)
    h.poll(1)
    [msg] = h.sent_to(h.all)
    assert msg[1] == "New device: Acme"
    assert (
        "- [medium] New device AA:BB:CC:00:00:01 (Acme) at 192.0.2.1, first seen 2026-11-09 11:58 UTC"
        in msg[2]
    )
    assert msg[2].endswith("Open NetTap for details.")
    assert h.sent_to(h.high) == []  # no new-device rule there
    h.take()
    h.poll(2)
    assert h.take() == []  # sent once
    assert h.events_state() == {"journal_seq": 1, "channels": {}}
    assert h.dispatcher.committed_seq == 1


def test_first_start_delivers_an_event_journaled_before_the_first_poll(h):
    assert not h.journal.existed_at_start
    h.device(1)  # the registry ran before the dispatcher's first minute
    h.poll(1)
    assert len(h.sent_to(h.all)) == 1


def test_alerts_and_events_share_one_message(h):
    h.groups = [group(1, 2, 0)]
    h.device(1)
    h.poll(1)
    [msg] = h.sent_to(h.all)
    assert msg[1] == "2 new notifications (worst: high)"
    assert "- [high] ET TEST signature 1" in msg[2]
    assert "- [medium] New device" in msg[2]
    assert (
        h.dispatcher._state["channels"][h.all]["sent"] == 1
    )  # one message of the budget
    # the alert-only channel keeps its alert wording
    assert h.sent_to(h.high)[0][1] == "High alert: ET TEST signature 1"


def test_a_backlog_is_read_over_several_polls_and_nothing_is_lost(h):
    for n in range(1000):
        h.device(n)
    for minute in range(1, 7):
        h.poll(minute)
    titles = [s[1] for s in h.sent_to(h.all)]
    assert titles == ["200 new notifications (worst: medium)"] * 5
    assert h.events_state()["journal_seq"] == 1000


def test_recovery_without_the_event_state_rereads_one_day(tmp_path):
    path = tmp_path / "events.jsonl"
    now = datetime.now(timezone.utc)
    lines = []
    for seq, age_h in ((1, 30), (2, 2)):
        lines.append(
            json.dumps(
                {
                    "seq": seq,
                    "id": f"id{seq}",
                    "type": "new_device",
                    "key": f"AA:00:00:00:00:0{seq}",
                    "observed_at": now.isoformat(),
                    "recorded_at": (now - timedelta(hours=age_h)).isoformat(),
                    "data": {"vendor": f"V{seq}"},
                }
            )
        )
    path.write_text("\n".join(lines) + "\n")
    h = EventHarness(tmp_path)
    assert h.journal.existed_at_start
    h.poll(1)
    [msg] = h.sent_to(h.all)
    assert msg[1] == "New device: V2"  # the 30-hour-old one stays in the journal only


def test_a_failing_channel_keeps_its_events_and_never_gives_up(h):
    h.fail = {h.all}
    h.groups = [group(1, 3, 0)]
    h.device(1)
    minute = 1
    for _ in range(8):  # well past the alerts' 3 retries
        h.poll(minute)
        minute += 16
    queued = h.dispatcher._events["channels"][h.all]["events"]
    assert [e["event"] for e in queued] == ["new_device"]
    assert h.dispatcher._state["channels"][h.all]["pending"] == []  # the alert gave up
    h.take()
    h.fail = set()
    h.groups = []
    h.poll(minute)
    [msg] = h.sent_to(h.all)
    assert msg[1] == "New device: Acme"


def test_a_refused_event_past_the_back_off_retries_hourly_not_every_15_minutes(h):
    h.refuse = {h.all}  # a wrong password: each try counts against the account
    h.device(1)
    minute = 1
    for _ in range(4):  # the alerts' back-off: 1, 5, 15 minutes
        h.poll(minute)
        minute += 16
    tries = len(h.sent_to(h.all))
    h.poll(minute + 16)  # past 15 minutes, before the hour
    assert len(h.sent_to(h.all)) == tries
    h.poll(minute + 61)
    assert len(h.sent_to(h.all)) == tries + 1
    assert h.dispatcher._events["channels"][h.all]["events"]  # still queued, not lost


def test_a_journal_that_restarts_its_numbering_is_read_again(h):
    for n in range(3):
        h.device(n)
    h.poll(1)
    assert h.events_state()["journal_seq"] == 3
    (h.tmp / "events.jsonl").unlink()  # deleted by hand: numbering restarts at 1
    h.restart()
    h.take()
    h.device(9)
    h.poll(2)
    assert [s[1] for s in h.sent_to(h.all)] == ["New device: Acme"]
    assert h.events_state()["journal_seq"] == 1


def test_past_the_daily_budget_events_wait_for_the_hourly_digest(h):
    with patch.object(nd, "DAILY_BUDGET", 1):
        h.device(1)
        h.poll(1)  # the day's one message
        h.device(2)
        h.poll(2)
        h.poll(30)
        assert len(h.sent_to(h.all)) == 1
        assert "and 1 other event waiting" in h.hub.last_delivery(h.all)["error"]
        h.poll(61)  # an hour after the last message
    sends = h.sent_to(h.all)
    assert len(sends) == 2
    assert "AA:BB:CC:00:00:02" in sends[-1][2]


def test_queued_events_never_push_alerts_out_of_the_pending_cap(h):
    h.fail = {h.all}
    for n in range(20):
        h.device(n)
    h.groups = [group(1000 + n, 4, 0.5) for n in range(nd.MAX_PENDING)]
    h.poll(1)
    assert len(h.dispatcher._state["channels"][h.all]["pending"]) == nd.MAX_PENDING
    assert len(h.dispatcher._events["channels"][h.all]["events"]) == 20


def test_the_compact_job_keeps_what_the_dispatcher_has_not_saved_as_taken(h):
    path = h.tmp / "events.jsonl"
    h.journal = EventJournal(
        str(path), keep_days=0
    )  # every line is past its keep period
    h.dispatcher = h.new_dispatcher()
    h.device(1)
    h.poll(1)  # taken and saved
    h.device(2)
    h.device(3)  # not taken yet
    assert h.dispatcher.compact_journal(0.0) == {"dropped": 1}
    assert [json.loads(line)["seq"] for line in path.read_text().splitlines()] == [2, 3]


def test_overflow_past_the_queue_cap_is_counted_and_reported(h):
    h.fail = {h.all}
    for n in range(600):
        h.device(n)
    for minute in (1, 3, 9):  # each past the previous retry
        h.poll(minute)
    q = h.dispatcher._events["channels"][h.all]
    assert (len(q["events"]), q["overflow"]) == (500, 100)
    h.take()
    h.fail = set()
    h.poll(30)
    [msg] = h.sent_to(h.all)
    assert msg[1] == "600 new notifications (worst: medium)"
    assert "and 490 more" in msg[2]
    assert "and 100 more events not listed; see NetTap" in msg[2]
    assert h.dispatcher._events["channels"] == {}


def test_a_crash_between_send_and_save_repeats_never_loses(h):
    h.device(1)
    for crash in range(3):
        with (
            patch.object(AlertDispatcher, "_save"),
            patch.object(AlertDispatcher, "_save_events", return_value=False),
        ):
            h.poll(1 + crash)
        h.restart()
    h.poll(10)
    h.poll(11)
    assert [s[1] for s in h.sent_to(h.all)] == [
        "New device: Acme"
    ] * 4  # one repeat a crash


def test_a_rollback_rewriting_the_alert_state_keeps_queued_events(h):
    h.fail = {h.all}
    h.device(1)
    h.poll(1)
    # the pre-NET-319 dispatcher runs and rewrites its own file only
    (h.tmp / "dispatch.json").write_text(json.dumps({"cursor": None, "channels": {}}))
    h.restart()
    h.fail = set()
    h.take()
    h.poll(5)
    assert [s[1] for s in h.sent_to(h.all)] == ["New device: Acme"]


def test_a_failed_event_state_save_keeps_the_committed_seq(h):
    h.device(1)
    h.poll(1)
    assert h.dispatcher.committed_seq == 1
    h.device(2)
    real = nd.write_file_atomic

    def fail_events(path, text, mode=0o644):
        if path.endswith("notification-events.json"):
            raise OSError(28, "No space left")
        return real(path, text, mode=mode)

    with patch(
        "services.notification_dispatcher.write_file_atomic", side_effect=fail_events
    ):
        h.poll(2)
    assert h.dispatcher.committed_seq == 1  # compaction keeps seq 2
    h.journal.compact(
        datetime.now(timezone.utc) + timedelta(days=365), h.dispatcher.committed_seq
    )
    h.restart()
    h.take()
    h.poll(3)
    assert [s[1] for s in h.sent_to(h.all)] == [
        "New device: Acme"
    ]  # seq 2 again: a repeat, not a loss


def test_turning_the_rule_off_drops_queued_events(h):
    h.fail = {h.all}
    h.device(1)
    h.poll(1)
    for rule in h.hub.get_rules():
        if rule["event_type"] == "new_device":
            h.hub.delete_rule(rule["id"])
    h.fail = set()
    h.take()
    h.poll(5)
    assert h.sent_to(h.all) == []


def test_without_a_journal_nothing_changes(tmp_path):
    h = Harness(tmp_path)
    h.groups = [group(1, 2, 0)]
    h.poll(1)
    assert not (tmp_path / "notification-events.json").exists()
    assert len(h.sent_to(h.high)) == 1
