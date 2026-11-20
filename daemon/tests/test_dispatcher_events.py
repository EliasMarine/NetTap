"""Journal events reach the channels with the alerts' limits, and are never lost (NET-319).

Drives AlertDispatcher.poll_once through the alert tests' Harness, with an event journal and a
new-device rule on the "all" channel."""

import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from services import notification_dispatcher as nd
from services.event_journal import EventJournal
from services.notification_dispatcher import AlertDispatcher
from services.notification_hub import body_limit
from tests.test_notification_dispatcher import Harness, group

GB = 10**9
# NET-339: dummy credentials for the services whose senders clip
CREDENTIALS = {
    "pushover": {"user_key": "u", "api_token": "t"},
    "telegram": {"bot_token": "b", "chat_id": "1"},
    "discord": {"webhook_url": "https://discord.example.net/hook"},
}


def cap_data(month: str = "2026-11", **change) -> dict:
    """A data cap warning's data, as data_cap.DataCapWatch writes it."""
    return {
        "month": month,
        "month_label": date.fromisoformat(f"{month}-01").strftime("%B"),
        "used": 82_400_000_000,
        "cap": 100 * GB,
        "projected": 131 * GB,
        "tz": "Europe/London",
        "since": "2026-10-01",
        "complete": True,
        **change,
    }


def macs(text: str) -> set[str]:
    return set(re.findall(r"AA:BB:CC:00:[0-9A-F]{2}:[0-9A-F]{2}", text))


class EventHarness(Harness):
    def __init__(self, tmp_path):
        self.journal = EventJournal(str(tmp_path / "events.jsonl"))
        # NET-339: what data_cap_now answers; an exception is raised instead
        self.cap_now: tuple[str, int] | Exception = ("2026-11", 100 * GB)
        super().__init__(tmp_path)
        self.hub.add_rule("new_device", [self.all], 4)
        self.hub.add_rule("data_cap", [self.all], 4)

    # OLD CODE START — NET-339: the dispatcher also gets data_cap_now
    # def new_dispatcher(self):
    #     return AlertDispatcher(
    #         self.hub,
    #         client=object(),
    #         lan_cidrs=lambda: [],
    #         state_path=str(self.tmp / "dispatch.json"),
    #         journal=self.journal,
    #     )
    # OLD CODE END
    def new_dispatcher(self):
        return AlertDispatcher(
            self.hub,
            client=object(),
            lan_cidrs=lambda: [],
            state_path=str(self.tmp / "dispatch.json"),
            journal=self.journal,
            data_cap_now=self.data_cap_now,
        )

    def data_cap_now(self) -> tuple[str, int]:
        if isinstance(self.cap_now, Exception):
            raise self.cap_now
        return self.cap_now

    def cap_warning(self, key: str = "80", month: str = "2026-11", **change) -> None:
        data = cap_data(month, **change)
        self.journal.append(
            "data_cap",
            key,
            "2026-11-09T11:58:00+00:00",
            {**data, "threshold": key},
            instance=f"{month}|{data['cap']}",
        )

    def channel(self, kind: str) -> str:
        """A channel of a clipping service, routed like "all"."""
        cid = self.hub.configure(kind, CREDENTIALS[kind])["id"]
        for event in ("alert", "new_device", "data_cap"):
            self.hub.add_rule(event, [cid], 4)
        return cid

    def queued(self, cid: str) -> list[dict]:
        return self.dispatcher._events["channels"].get(cid, {}).get("events", [])

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
    # OLD CODE START — NET-339 security review: unshown devices went in the next message, so a
    # burst became one message a minute; they're counted in "and N more" again, as in F1
    # sends = h.sent_to(h.all)
    # assert len(sends) == 6  # one message a poll
    # assert h.events_state()["journal_seq"] == 1000
    # # each device is shown, counted as "not listed", or still queued for the next message
    # shown = sum(s[2].count("- [medium] New device") for s in sends)
    # counted = sum(
    #     int(line.split()[1])
    #     for s in sends
    #     for line in s[2].splitlines()
    #     if line.endswith("more events not listed; see NetTap")
    # )
    # queued = len(h.events_state()["channels"][h.all]["events"])
    # assert shown == 60 and shown + counted + queued == 1000
    # OLD CODE END
    titles = [s[1] for s in h.sent_to(h.all)]
    assert titles == ["200 new notifications (worst: medium)"] * 5
    assert h.events_state() == {"journal_seq": 1000, "channels": {}}


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
    # OLD CODE START — NET-339 security review: the 490 not shown are in "and 490 more" again
    # q = h.dispatcher._events["channels"][h.all]
    # assert (len(q["events"]), q["overflow"]) == (490, 0)
    # OLD CODE END
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


# --- NET-339: data cap warnings and the channels' length limits ------------------------------


def cap_entry(key: str, **change) -> dict:
    return {"id": "e1", "type": "data_cap", "key": key, "data": cap_data(**change)}


USED = "82.4 GB of your 100 GB cap used in November (Europe/London)"


@pytest.mark.parametrize(
    "key, change, severity, title, line",
    [
        ("80", {}, 3, "Data cap: 80% used", USED),
        (
            "100",
            {"used": 100_300_000_000},
            2,
            "Data cap reached",
            "100.3 GB of your 100 GB cap used in November (Europe/London)",
        ),
        (
            "projected",
            {},
            3,
            "Data cap: on track to go over",
            "On track for 131.0 GB in November, over your 100 GB cap",
        ),
        # the ledger started inside the month
        (
            "80",
            {"complete": False, "since": "2026-11-13"},
            3,
            "Data cap: 80% used",
            f"{USED}, at least: counted since 13 Nov",
        ),
        # it started earlier, so the month has gaps: no "counted since"
        (
            "80",
            {"complete": False, "since": "2026-10-20"},
            3,
            "Data cap: 80% used",
            f"{USED}, at least",
        ),
        # "at least" floors: 82.46 GB counted so far never reads 82.5
        (
            "80",
            {"complete": False, "since": "2026-10-20", "used": 82_460_000_000},
            3,
            "Data cap: 80% used",
            f"{USED}, at least",
        ),
        # a complete month is the real figure, rounded as usual
        (
            "80",
            {"used": 82_460_000_000},
            3,
            "Data cap: 80% used",
            "82.5 GB of your 100 GB cap used in November (Europe/London)",
        ),
        # it started on the 1st: nothing before it is missing, so no "counted since 1 Nov"
        (
            "80",
            {"complete": False, "since": "2026-11-01"},
            3,
            "Data cap: 80% used",
            f"{USED}, at least",
        ),
    ],
)
def test_a_data_cap_entry_becomes_an_item_with_its_severity_title_and_line(
    key, change, severity, title, line
):
    item = nd.event_item(cap_entry(key, **change))
    assert (item["event"], item["severity"], item["title"], item["line"]) == (
        "data_cap",
        severity,
        title,
        line,
    )
    assert item["sig"] == "event:e1"


@pytest.mark.parametrize(
    "key, change",
    [
        ("80", {"cap": -1}),
        ("80", {"used": -5}),
        ("80", {"used": True}),  # a bool is an int to Python, not a byte count
        ("100", {"cap": False}),
        ("projected", {"projected": None}),
        ("80", {"complete": False, "since": "2026-11-99"}),  # an unreadable since
        ("90", {}),  # not a threshold
    ],
)
def test_a_malformed_data_cap_entry_gives_nothing(key, change):
    assert nd.event_item(cap_entry(key, **change)) is None


@pytest.mark.parametrize("data", [["cap", 100], "82.4 GB"])
def test_a_data_cap_entry_whose_data_is_not_a_dict_gives_nothing(data):
    assert nd.event_item({**cap_entry("80"), "data": data}) is None


@pytest.mark.parametrize("field", ["cap", "used"])
def test_a_data_cap_entry_missing_a_figure_gives_nothing(field):
    entry = cap_entry("80")
    data = {k: v for k, v in entry["data"].items() if k != field}
    assert nd.event_item({**entry, "data": data}) is None


def test_a_data_cap_warning_reaches_the_channels_its_rule_names(h):
    h.cap_warning("80")
    h.poll(1)
    [msg] = h.sent_to(h.all)
    assert (msg[1], msg[3]) == ("Data cap: 80% used", 3)
    assert f"- [medium] {USED}" in msg[2]
    assert h.sent_to(h.high) == []  # no data cap rule there
    assert h.events_state()["channels"] == {}


# OLD CODE START — NET-339 security review: unshown devices no longer go in the next message
# def test_a_clipped_channel_sends_what_fits_and_the_rest_in_the_next_message(h):
#     po = h.channel("pushover")
#     every = {f"AA:BB:CC:00:00:{n:02X}" for n in range(12)}
#     h.groups = [group(1, 1, 0)]
#     for n in range(12):
#         h.device(n, vendor="V" * 40)
#     h.poll(1)
#     [first] = h.sent_to(po)
#     assert first[2].startswith("- [critical] ET TEST signature 1")
#     shown = macs(first[2])
#     # the clip, not the 10-line cap, stopped it (the critical alert is a line too)
#     assert 0 < len(shown) < nd.DIGEST_LINES - 1
#     assert f"and {12 - len(shown)} more" in first[2]
#     # nothing unshown was acknowledged
#     assert macs(" ".join(e["line"] for e in h.queued(po))) == every - shown
#     h.poll(2)
#     second = h.sent_to(po)[1]
#     assert macs(second[2]) == every - shown
#     assert h.queued(po) == []
#     assert all(len(s[2]) <= body_limit("pushover") for s in h.sent_to(po))
# OLD CODE END
def test_a_clipped_channel_counts_unshown_devices_and_sends_a_cap_warning_past_the_cut_next(
    h,
):
    po = h.channel("pushover")
    h.groups = [group(1, 1, 0)]
    for n in range(12):
        h.device(n, vendor="V" * 40)
    # medium like the devices; _worst_first ties keep queue order, so it sorts past the cut
    h.cap_warning("80")
    h.poll(1)
    [first] = h.sent_to(po)
    assert first[2].startswith("- [critical] ET TEST signature 1")
    shown = macs(first[2])
    # the clip, not the 10-line cap, stopped it (the critical alert is a line too)
    assert 0 < len(shown) < nd.DIGEST_LINES - 1
    assert USED not in first[2]
    # the devices left out and the warning
    assert f"and {13 - len(shown)} more" in first[2]
    assert [e["event"] for e in h.queued(po)] == ["data_cap"]
    h.poll(2)
    second = h.sent_to(po)[1]
    assert f"- [medium] {USED}" in second[2]
    assert macs(second[2]) == set()  # a device counted in "and N more" isn't sent again
    assert h.queued(po) == []
    assert all(len(s[2]) <= body_limit("pushover") for s in h.sent_to(po))


# OLD CODE START — NET-339 security review: unshown devices are counted, not queued
# def test_pushover_s_body_fits_with_the_budget_notice_and_the_unshown_stay_queued(h):
#     po = h.channel("pushover")
#     for n in range(12):
#         h.device(n, vendor="V" * 200)
#     with patch.object(nd, "DAILY_BUDGET", 1):  # the first message is the day's last
#         h.poll(1)
#     [msg] = h.sent_to(po)
#     assert msg[2].startswith("This channel has reached its limit of 1 messages today")
#     assert len(msg[2]) <= body_limit("pushover")
#     shown = macs(msg[2])
#     left = macs(" ".join(e["line"] for e in h.queued(po)))
#     assert shown and not shown & left and len(shown | left) == 12
# OLD CODE END
def test_pushover_s_body_fits_with_the_budget_notice_and_only_cap_warnings_stay_queued(
    h,
):
    po = h.channel("pushover")
    # three of these lines fill all but 38 characters, too few for the cap warning's line
    for n in range(12):
        h.device(n, vendor="V" * 185)
    h.cap_warning("80")  # last in the queue, past the cut
    with patch.object(nd, "DAILY_BUDGET", 1):  # the first message is the day's last
        h.poll(1)
    [msg] = h.sent_to(po)
    assert msg[2].startswith("This channel has reached its limit of 1 messages today")
    assert len(msg[2]) <= body_limit("pushover")
    shown = macs(msg[2])
    assert shown and USED not in msg[2]
    assert f"and {13 - len(shown)} more" in msg[2]
    assert [e["event"] for e in h.queued(po)] == ["data_cap"]


def test_a_new_device_flood_never_trims_a_queued_data_cap_warning(h):
    h.fail = {h.all}
    h.cap_warning("80")  # the oldest in the queue, so the first a plain trim would drop
    for n in range(600):
        h.device(n)
    for minute in (1, 3, 9, 25):  # 601 entries at 200 a poll
        h.poll(minute)
    q = h.dispatcher._events["channels"][h.all]
    assert (len(q["events"]), q["overflow"]) == (nd.MAX_EVENTS, 101)
    assert [e["event"] for e in q["events"]].count("data_cap") == 1
    h.take()
    h.fail = set()
    h.poll(120)
    [msg] = h.sent_to(h.all)
    assert f"- [medium] {USED}" in msg[2]


def test_a_channel_down_across_months_keeps_only_the_current_month_s_warnings(
    h, caplog
):
    h.fail = {h.all}
    with caplog.at_level("WARNING"):
        h.cap_warning("80", month="2026-11")
        h.poll(1)
        h.cap_now = ("2026-12", 100 * GB)
        h.cap_warning("80", month="2026-12")
        h.poll(3)
        h.cap_now = ("2027-01", 100 * GB)
        h.cap_warning("100", month="2027-01", used=101 * GB)
        h.take()
        h.fail = set()
        h.poll(30)
    [msg] = h.sent_to(h.all)
    assert msg[1] == "Data cap reached"
    assert "used in January" in msg[2]
    assert "November" not in msg[2] and "December" not in msg[2]
    assert h.events_state()["channels"] == {}
    assert "dropped 1 for a month that is over" in caplog.text


@pytest.mark.parametrize("new_cap", [500 * GB, 0])
def test_a_warning_for_a_cap_since_raised_or_removed_is_held_and_the_rest_still_go(
    h, new_cap
):
    h.cap_warning("80")  # for the 100 GB cap
    h.cap_now = ("2026-11", new_cap)
    h.fail = {h.all}
    h.groups = [group(1, 3, 0)]
    h.device(1)
    h.poll(1)  # a failed send: only what was offered counts a try
    h.take()
    h.fail = set()
    h.poll(3)
    [msg] = h.sent_to(h.all)
    assert "ET TEST signature 1" in msg[2] and "New device" in msg[2]
    assert "of your 100 GB cap" not in msg[2]
    [held] = h.events_state()["channels"][h.all]["events"]
    assert (held["event"], held["cap"], held["attempts"]) == ("data_cap", 100 * GB, 0)


def test_a_to_b_to_a_during_an_outage_sends_a_s_warning_once_a_is_back(h):
    h.fail = {h.all}
    h.cap_warning("80")  # cap A, 100 GB
    h.poll(1)
    h.cap_now = ("2026-11", 200 * GB)  # B
    h.cap_warning("80", cap=200 * GB, used=165 * GB)
    h.poll(3)
    h.cap_now = ("2026-11", 100 * GB)  # back to A
    h.take()
    h.fail = set()
    for minute in (30, 31, 90):
        h.poll(minute)
    [msg] = h.sent_to(h.all)
    assert f"- [medium] {USED}" in msg[2] and "200 GB" not in msg[2]
    [held] = h.events_state()["channels"][h.all]["events"]
    assert held["cap"] == 200 * GB  # B's waits for B


def test_past_twelve_held_warnings_the_oldest_held_ones_go(h, caplog):
    h.cap_now = ("2026-11", 500 * GB)  # every warning below is for a cap since replaced
    for gb in range(101, 115):
        h.cap_warning("80", cap=gb * GB)
    with caplog.at_level("WARNING"):
        h.poll(1)
    assert h.sent_to(h.all) == []
    queued = h.events_state()["channels"][h.all]["events"]
    assert [e["cap"] for e in queued] == [gb * GB for gb in range(103, 115)]
    assert "and 2 held for a cap no longer set" in caplog.text


def _payload_text(kind: str, posted: dict) -> str:
    if kind == "pushover":
        return posted["data"]["message"]
    if kind == "discord":
        return posted["json"]["embeds"][0]["description"]
    return posted["json"]["text"]


@pytest.mark.parametrize("kind", ["telegram", "pushover", "discord"])
def test_the_real_payload_carries_a_journal_event_at_the_limit_uncut(h, kind):
    cid = h.channel(kind)
    limit = body_limit(kind)
    # event lines stop at 300 characters, so a long alert takes the message near its limit
    alert = {**group(1, 2, 0), "signature": "S"}
    alert_extra = len(nd._digest_line(nd.merge_groups([alert])[0])) - 1
    h.device(10, vendor="V" * 60)
    [entry] = h.journal.after(0, 1)
    device_line = nd._digest_line(nd.event_item(entry))
    h.device(11)  # one more, which can't fit
    footer = "Open NetTap for details."
    room = limit - len("\n".join(["and 3 more", "", footer]))
    # the alert and the device lines (each with its break) fill the room to the last character
    signature = "S" * (room - len(device_line) - 2 - alert_extra)
    h.groups = [{**alert, "signature": signature}]
    h.poll(1)
    [send] = h.sent_to(cid)
    body = send[2]
    assert len(body) == limit
    assert body.splitlines()[1] == device_line and "and 1 more" in body
    posted = []

    async def fake_post(_url, **kwargs):
        posted.append(kwargs)

    with patch("services.notification_hub._post", side_effect=fake_post):
        assert asyncio.run(h.hub.deliver(*send)) == "sent"
    text = _payload_text(kind, posted[0])
    expected = body if kind != "telegram" else f"[HIGH] {send[1]}\n\n{body}"
    assert text == expected  # every rendered line whole, no service clip
    assert not text.endswith("…")


def test_a_huge_vendor_name_is_clipped_and_a_cap_warning_behind_it_still_goes(h):
    po = h.channel("pushover")
    h.device(1, vendor="V" * 2000)
    h.cap_warning("80")
    h.poll(1)
    [msg] = h.sent_to(po)
    [device] = [line for line in msg[2].splitlines() if "New device" in line]
    line = device.removeprefix("- [medium] ")
    assert len(line) == nd.EVENT_LINE_CHARS and line.endswith("…")
    assert f"- [medium] {USED}" in msg[2]
    assert h.queued(po) == []


def test_an_unreadable_cap_holds_cap_warnings_and_alerts_still_go(h, caplog):
    h.cap_now = OSError("the ledger can't be read")
    h.cap_warning("80")
    h.groups = [group(1, 2, 0)]
    with caplog.at_level("WARNING"):
        h.poll(1)
    [msg] = h.sent_to(h.all)
    assert msg[1] == "High alert: ET TEST signature 1"
    assert [e["event"] for e in h.queued(h.all)] == ["data_cap"]
    assert "Data cap warnings held: the current cap can't be read" in caplog.text
    h.cap_now = ("2026-11", 100 * GB)
    h.poll(2)
    assert f"- [medium] {USED}" in h.sent_to(h.all)[-1][2]
