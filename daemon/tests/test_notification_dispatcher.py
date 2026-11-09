"""NET-224: alerts reach the channels from the daemon, with no browser open.

Each test drives AlertDispatcher.poll_once with a fake get_smart_alerts and a recording
hub.send, through the real NotificationHub routing rules."""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import notification_dispatcher as nd  # noqa: E402
from services.notification_dispatcher import AlertDispatcher  # noqa: E402
from services.notification_hub import NotificationHub  # noqa: E402

T0 = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def group(sig_id, severity, seen_min, src="192.0.2.10", dst="192.0.2.20", count=3):
    return {
        "signature_id": sig_id,
        "signature": f"ET TEST signature {sig_id}",
        "severity": severity,
        "source_ip": src,
        "destination_ip": dst,
        "count": count,
        "last_seen": at(seen_min).isoformat(),
    }


class Harness:
    """A hub with two webhook channels (high-only and all) and a dispatcher on a temp state file."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        env = tmp_path / ".env"
        env.write_text("")
        self.hub = NotificationHub(
            config_path=str(tmp_path / "n.json"), env_file=str(env)
        )
        self.high = self.hub.configure(
            "webhook", {"url": "https://hooks.example.net/high"}
        )["id"]
        self.all = self.hub.configure(
            "webhook", {"url": "https://hooks.example.net/all"}
        )["id"]
        self.hub.add_rule("alert", [self.high], 2)
        self.hub.add_rule("alert", [self.all], 4)
        self.groups: list[dict] = []
        self.query_fails = False
        self.queries: list[tuple[str, str]] = []
        self.sent: list[tuple[str, str, str, int]] = []
        self.fail: set[str] = set()
        self.refuse: set[str] = set()  # the service answers and turns the send down
        self.partly: set[str] = set()  # the mail went out; some recipients were refused
        self.dispatcher = self.new_dispatcher()

    def new_dispatcher(self):
        return AlertDispatcher(
            self.hub,
            client=object(),
            lan_cidrs=lambda: [],
            state_path=str(self.tmp / "dispatch.json"),
        )

    def poll(self, minutes):
        def fake_alerts(_client, from_ts, to_ts, *_args, **_kwargs):
            self.queries.append((from_ts, to_ts))
            if self.query_fails:
                raise ConnectionError("OpenSearch is down")
            return list(self.groups)

        # OLD CODE START — security delta: the dispatcher asks the hub how a send went, not only whether
        # async def fake_send(cid, title, body, severity):
        #     self.sent.append((cid, title, body, severity))
        #     return cid not in self.fail
        # OLD CODE END
        async def fake_deliver(cid, title, body, severity):
            self.sent.append((cid, title, body, severity))
            if cid in self.refuse:
                return "refused"
            if cid in self.partly:
                return "partly"
            return "failed" if cid in self.fail else "sent"

        with (
            patch(
                "services.alert_intelligence.get_smart_alerts", side_effect=fake_alerts
            ),
            # OLD CODE: patch.object(self.hub, "send", side_effect=fake_send),
            patch.object(self.hub, "deliver", side_effect=fake_deliver),
        ):
            asyncio.run(self.dispatcher.poll_once(at(minutes)))

    def sent_to(self, cid):
        return [s for s in self.sent if s[0] == cid]

    def take(self):
        sent, self.sent = self.sent, []
        return sent


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def test_each_channel_gets_one_digest_of_what_its_rules_route(h):
    h.groups = [
        group(1, 2, 0),
        group(1, 2, 0, src="192.0.2.11"),
        group(2, 3, 0),
        group(3, 4, 0),
    ]
    h.poll(1)

    high, every = h.sent_to(h.high), h.sent_to(h.all)
    assert len(high) == 1 and len(every) == 1
    assert high[0][1] == "High alert: ET TEST signature 1"
    assert "192.0.2.10 → 192.0.2.20 and 1 more" in high[0][2]
    assert every[0][1] == "3 new alerts (worst: high)" and every[0][3] == 2
    assert "ET TEST signature 3" in every[0][2]


def test_the_cooldown_is_per_channel_escalation_bypasses_it_and_unrouted_alerts_dont_use_it(
    h,
):
    h.groups = [group(1, 3, 0)]  # medium: only the "all" channel hears it
    h.poll(1)
    assert [s[0] for s in h.take()] == [h.all]

    h.groups = [group(1, 3, 2)]  # a newer occurrence inside the hour: nobody again
    h.poll(3)
    assert h.take() == []

    h.groups = [
        group(1, 2, 4)
    ]  # escalated to high: both, the high-only one for the first time
    h.poll(5)
    assert sorted(s[0] for s in h.take()) == sorted([h.high, h.all])

    h.groups = [group(1, 2, 70)]  # a newer occurrence after the hour
    h.poll(71)
    assert sorted(s[0] for s in h.take()) == sorted([h.high, h.all])


def test_a_failed_channel_retries_after_a_back_off_even_after_a_restart(h):
    h.fail = {h.high}
    h.groups = [group(1, 1, 0)]
    h.poll(1)
    assert len(h.sent_to(h.high)) == 1 and len(h.sent_to(h.all)) == 1
    h.take()

    h.groups = []
    h.poll(1.5)  # inside the 1 min back-off: no new attempt
    assert h.take() == []

    h.dispatcher = h.new_dispatcher()  # the daemon restarts
    h.fail = set()
    h.poll(2.5)
    assert [(s[0], s[1]) for s in h.take()] == [
        (h.high, "Critical alert: ET TEST signature 1")
    ]

    h.poll(4)  # delivered: never again
    assert h.take() == []


def test_a_new_alert_keeps_its_own_retries_when_an_older_batch_runs_out(h):
    h.fail = {h.high}
    h.groups = [group(1, 2, 0)]
    for minute in (1, 2, 7, 22):  # first try, then the +1, +5 and +15 min retries
        h.poll(minute)
        if minute == 7:
            h.groups = [
                group(1, 2, 0),
                group(9, 1, 21),
            ]  # a new critical before the last retry
    tries = [s for s in h.take() if s[0] == h.high]
    assert len(tries) == 4
    assert "ET TEST signature 9" in tries[-1][2]

    h.fail = set()
    h.groups = []
    h.poll(23.5)  # signature 1 was given up; 9 still has retries
    last = h.take()
    assert [(s[0], s[1]) for s in last] == [
        (h.high, "Critical alert: ET TEST signature 9")
    ]


def test_a_given_up_alert_is_not_restarted_when_the_same_alerts_are_read_again(h):
    """Codex round 3's timeline: quick retries, give up, OpenSearch down, the same occurrences re-read."""
    h.fail = {h.high, h.all}
    h.groups = [group(1, 1, 0)]
    h.poll(0.5)
    for minute, sig in ((1.5, 2), (2.5, 3)):  # new signatures keep the 1 min retry pace
        h.groups = [group(1, 1, 0), group(sig, 1, minute - 0.2)]
        h.poll(minute)
    h.groups = [group(1, 1, 0)]
    h.poll(3.5)  # signature 1's last try: given up, while 2 and 3 still have retries
    h.query_fails = True  # OpenSearch goes down: the cursor stays at 3.5 from here
    for minute in (
        9,
        25,
        26,
        40,
        60,
    ):  # the retries run out (2 at 9, 3 at 25) during the outage
        h.poll(minute)
    assert (
        json.loads((h.tmp / "dispatch.json").read_text())["cursor"]
        == at(3.5).isoformat()
    )
    assert all(
        not st["pending"]
        for st in json.loads((h.tmp / "dispatch.json").read_text())["channels"].values()
    )
    h.take()
    h.query_fails = False
    h.fail = set()
    h.groups = [
        group(1, 1, 0),
        group(2, 1, 1.3),
        group(3, 1, 2.3),
    ]  # the same occurrences
    h.poll(64)  # the window reaches back to minute -1: all three occurrences again

    assert h.queries[-1][0] == at(-1).isoformat()
    assert h.take() == []


def test_the_cursor_is_kept_while_the_query_fails_and_the_window_is_capped(h):
    h.poll(1)
    state = json.loads((h.tmp / "dispatch.json").read_text())
    assert state["cursor"] == at(1).isoformat()

    h.query_fails = True
    h.poll(2)
    assert (
        json.loads((h.tmp / "dispatch.json").read_text())["cursor"] == at(1).isoformat()
    )

    h.query_fails = False
    h.poll(300)  # four hours later: an hour back plus the overlap, not four hours
    start, end = h.queries[-1]
    assert (
        datetime.fromisoformat(end) - datetime.fromisoformat(start)
    ) == nd.MAX_CATCH_UP + nd.OVERLAP


def test_no_query_runs_when_no_channel_would_hear_it(tmp_path):
    env = tmp_path / ".env"
    env.write_text("")
    hub = NotificationHub(config_path=str(tmp_path / "n.json"), env_file=str(env))
    dispatcher = AlertDispatcher(
        hub, client=object(), lan_cidrs=lambda: [], state_path=str(tmp_path / "d.json")
    )
    with patch("services.alert_intelligence.get_smart_alerts") as query:
        asyncio.run(dispatcher.poll_once(T0))
    query.assert_not_called()


def test_a_slow_channel_does_not_hold_up_another(h):
    h.groups = [group(1, 1, 0)]
    gate = asyncio.Event()
    order = []

    async def send(cid, *_args):
        if cid == h.high:
            await gate.wait()
        order.append(cid)
        if cid == h.all:
            gate.set()
        # OLD CODE: return True (security delta: the dispatcher asks the hub how a send went)
        return "sent"

    with (
        patch("services.alert_intelligence.get_smart_alerts", return_value=h.groups),
        # OLD CODE: patch.object(h.hub, "send", side_effect=send),
        patch.object(h.hub, "deliver", side_effect=send),
    ):
        asyncio.run(asyncio.wait_for(h.dispatcher.poll_once(at(1)), 5))
    assert order == [h.all, h.high]


def test_a_corrupt_state_file_starts_fresh(h):
    (h.tmp / "dispatch.json").write_text("{not json")
    h.dispatcher = h.new_dispatcher()
    h.groups = [group(1, 2, 0)]
    h.poll(1)
    assert len(h.take()) == 2


# Security review M2: alerts an attacker can trip must not use up the owner's mail or Pushover quota
# OLD CODE START — security delta D3: past the budget nothing went out until midnight, so a
# flood an attacker trips held a critical alert back for the rest of the day
# def test_a_channel_gets_at_most_the_daily_budget_then_a_held_count_until_tomorrow(h):
#     with patch.object(nd, "DAILY_BUDGET", 3):
#         for minute in range(1, 6):  # a new critical signature every minute
#             h.groups = [group(100 + minute, 1, minute - 0.5)]
#             h.poll(minute)
#         sends = h.sent_to(h.high)
#         assert len(sends) == 3
#         # OLD CODE START — delta review: the notice now comes first, so a length clip keeps it
#         # assert "last notification today" in sends[-1][2]
#         # OLD CODE END
#         assert sends[-1][2].startswith("This is the last notification today")
#         assert "last notification today" not in sends[0][2]
#         status = h.hub.last_delivery(h.high)
#         assert status["ok"] is False
#         assert "Daily limit of 3 messages" in status["error"]
#         assert "2 alerts" in status["error"]
#
#         h.dispatcher = h.new_dispatcher()  # the count survives a restart
#         h.groups = [group(200, 1, 7)]
#         h.poll(8)
#         assert len(h.sent_to(h.high)) == 3
#         assert "3 alerts" in h.hub.last_delivery(h.high)["error"]
#
#         h.groups = [group(300, 1, 24 * 60 + 1)]  # the next UTC day
#         h.poll(24 * 60 + 2)
#         assert len(h.sent_to(h.high)) == 4
#         # the held ones were handled: tomorrow doesn't bring them back
#         assert "ET TEST signature 105" not in h.sent_to(h.high)[-1][2]
# OLD CODE END
def test_past_the_daily_budget_a_channel_gets_one_digest_an_hour(h):
    with patch.object(nd, "DAILY_BUDGET", 3):
        for minute in range(1, 4):  # a new critical signature every minute
            h.groups = [group(100 + minute, 1, minute - 0.5)]
            h.poll(minute)
        sends = h.sent_to(h.high)
        assert len(sends) == 3
        assert sends[-1][2].startswith(
            "This channel has reached its limit of 3 messages today"
        )
        assert "limit of 3" not in sends[0][2]

        h.groups = []
        h.poll(4)  # a quiet minute doesn't reopen the channel
        for minute in (5, 6):
            h.groups = [group(100 + minute, 1, minute - 0.5)]
            h.poll(minute)
        assert len(h.sent_to(h.high)) == 3
        status = h.hub.last_delivery(h.high)
        assert status["ok"] is False
        assert "Daily limit of 3 messages" in status["error"]
        assert "2 alerts" in status["error"]

        h.dispatcher = h.new_dispatcher()  # the wait survives a restart
        h.groups = []
        h.poll(62)
        assert len(h.sent_to(h.high)) == 3
        h.poll(63)  # an hour after the last message
        sends = h.sent_to(h.high)
        assert len(sends) == 4
        assert "signature 105" in sends[-1][2]
        assert "signature 106" in sends[-1][2]


def test_a_flood_past_the_budget_cant_hold_back_a_critical_alert(h):
    with patch.object(nd, "DAILY_BUDGET", 1):
        h.groups = [group(1, 4, 0.5)]
        h.poll(1)  # the day's one message on the all-alerts channel
        flood = [group(1000 + n, 4, 1.5) for n in range(nd.MAX_PENDING + 10)]
        h.groups = [*flood, group(7, 1, 1.5)]
        h.poll(2)
        h.groups = []
        h.poll(61)
    title, body = h.sent_to(h.all)[-1][1:3]
    assert title == f"{nd.MAX_PENDING} new alerts (worst: critical)"
    assert body.splitlines()[0].startswith("- [critical] ET TEST signature 7:")


def test_the_hourly_wait_ends_when_the_budget_renews_at_midnight(h):
    with patch.object(nd, "DAILY_BUDGET", 1):
        h.groups = [group(1, 1, 689.5)]
        h.poll(690)  # 23:30 UTC: the day's one message
        h.groups = [group(2, 1, 724.5)]
        h.poll(725)  # 00:05 UTC: a new day's budget
    assert len(h.sent_to(h.high)) == 2


# OLD CODE START — delta review: a failed send no longer uses the budget (an outage spent it)
# def test_failed_attempts_count_against_the_budget(h):
#     """A provider counts each attempt, so retries of one failing batch use the budget too."""
#     h.fail = {h.high}
#     with patch.object(nd, "DAILY_BUDGET", 2):
#         h.groups = [group(1, 1, 0)]
#         for minute in (1, 2, 7, 22):
#             h.poll(minute)
#     assert len(h.sent_to(h.high)) == 2
# OLD CODE END
def test_failed_sends_leave_the_budget_for_when_the_server_is_back(h):
    """The mail server is down for two hours with an alert a minute: nothing was sent, so none of
    the day's messages are used, and alerts go out again once it is back."""
    h.fail = {h.high}
    with patch.object(nd, "DAILY_BUDGET", 3):
        for minute in range(1, 121):
            h.groups = [group(100 + minute, 1, minute - 0.5)]
            h.poll(minute)
        assert len(h.sent_to(h.high)) > 3  # tried on the back-off pace, never delivered
        h.take()
        h.fail = set()
        h.groups = [group(500, 1, 121)]
        h.poll(122)
        assert len(h.sent_to(h.high)) == 1


def test_refused_sends_use_the_budget_so_a_wrong_password_slows_to_hourly(h):
    """Refused 1,440 times a day, a login gets the account locked; past the budget, one an hour."""
    h.refuse = {h.high}
    with patch.object(nd, "DAILY_BUDGET", 3):
        for minute in range(1, 121):  # an alert a minute for two hours
            h.groups = [group(100 + minute, 1, minute - 0.5)]
            h.poll(minute)
    # three refused tries use the day's budget (minutes 1, 2, 3), then one an hour (minute 63)
    assert len(h.sent_to(h.high)) == 4


def test_a_partly_refused_digest_went_out_so_it_isnt_sent_again(h):
    """A retry would send the accepted recipients the same digest up to four more times."""
    h.partly = {h.high}
    with patch.object(nd, "DAILY_BUDGET", 3):
        h.groups = [group(1, 1, 0)]
        for minute in (1, 2, 7, 22):
            h.poll(minute)
    assert len(h.sent_to(h.high)) == 1
    st = json.loads((h.tmp / "dispatch.json").read_text())["channels"][h.high]
    assert st["sent"] == 1 and st["pending"] == []
