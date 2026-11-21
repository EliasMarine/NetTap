"""The watched-devices job end to end (NET-331, plan §2.2-§2.4, §5).

Each test drives WatchedDevices.run through tests/watched_rig.py: real details, journal and
state files, and a fake index that evaluates the job's own query bodies over conn records.
"""

import asyncio
import json
import threading
from datetime import timedelta
from unittest.mock import patch

import pytest
from opensearchpy import ConnectionTimeout, OpenSearchException

from services import watched_devices as wd
from services import watched_rules as wr
from services.event_journal import event_id
from services.scheduled_jobs import Job, Scheduler
from tests.test_scheduled_jobs import _settle
from tests.watched_rig import (
    D,
    E,
    GATEWAY,
    MAC_D,
    MAC_E,
    MIRROR,
    OTHER,
    ROUTER,
    Rig,
    at,
    is_presence,
    iso,
)


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def _types(rig) -> list[str]:
    return [e["type"] for e in rig.events()]


# --- the state machine through real runs -------------------------------------


def test_offline_then_back_online_journals_exactly_the_contract(rig):
    rig.names[MAC_D] = "Kitchen plug"
    rig.bring_up()
    rig.checks(at("12:10"), at("12:25"))
    rig.check(at("12:30"))
    assert rig.dev()["silent_from"] == iso(at("12:29", 30)) and rig.events() == []
    rig.check(at("12:35"))
    (offline,) = rig.events()
    assert offline["type"] == "device_offline" and offline["key"] == MAC_D
    assert offline["observed_at"] == iso(at("12:35"))
    assert offline["data"] == {
        "mac": MAC_D,
        "name": "Kitchen plug",
        "after_min": 15,
        "seen_at": iso(at("12:02")),
    }
    assert offline["id"] == event_id(
        "device_offline", MAC_D, "down|" + iso(at("12:02"))
    )
    rig.check(at("12:40"))
    rig.conn(D, ROUTER, at("12:41"), at("12:42"))
    rig.check(at("12:45"))
    online = rig.events()[-1]
    assert online["type"] == "device_online"
    assert online["data"] == {
        "mac": MAC_D,
        "name": "Kitchen plug",
        "after_min": 15,
        "seen_at": iso(at("12:02")),
        "back_at": iso(at("12:41")),
        "away_min": 39,
    }
    assert online["id"] == event_id("device_online", MAC_D, "up|" + iso(at("12:02")))
    dev = rig.dev()
    assert (dev["state"], dev["since"], dev["seen_at"], dev["incident"]) == (
        "up",
        iso(at("12:45")),
        iso(at("12:42")),
        None,
    )


def test_enrollment_ignores_activity_before_the_first_run_that_sees_the_watch(rig):
    rig.conn(D, ROUTER, at("11:55"), at("11:56"))
    rig.watch()
    rig.check(at("12:00"))
    assert rig.dev()["enrolled_at"] == iso(at("12:00"))
    rig.check(at("12:05"))
    assert rig.dev()["state"] == "unknown"
    rig.conn(D, ROUTER, at("12:06"), at("12:07"))
    rig.check(at("12:10"))
    assert rig.dev()["state"] == "up" and rig.events() == []


def test_a_peer_late_packet_neither_enrolls_nor_recovers_a_device(rig):
    # the NAS answered at 12:00 and was unplugged; the watch begins at 12:01
    rig.conn(OTHER, D, at("11:59"), at("12:00"))
    rig.watch()
    rig.check(at("12:01"))
    # the client keeps sending on the same connection: a later end, the same start
    rig.conn(OTHER, D, at("11:59"), at("12:02"), file="conn_long.log")
    rig.check(at("12:05"))
    assert rig.dev()["state"] == "unknown"


def test_no_recovery_from_a_cumulative_conn_long_responder(rig):
    rig.bring_down()
    # an interim record of a connection started before the declaration, replies cumulative
    rig.conn(OTHER, D, at("12:20"), at("12:38"), file="conn_long.log")
    rig.check(at("12:40"))
    assert rig.dev()["state"] == "down" and _types(rig) == ["device_offline"]


def test_interim_records_on_either_side_keep_a_device_up(rig):
    rig.watch(MAC_D, 15)
    rig.watch(MAC_E, 15)
    rig.check(at("12:00"))
    rig.conn(D, ROUTER, at("12:01"))
    rig.conn(OTHER, E, at("12:01"))
    for minute in range(5, 125, 5):
        t = at("12:00") + timedelta(minutes=minute)
        # one long transfer each: D sending, the NAS E answering; only checkpoints are written
        rig.conn(D, ROUTER, at("12:01"), t - timedelta(minutes=1), file="conn_long.log")
        rig.conn(OTHER, E, at("12:01"), t - timedelta(minutes=1), file="conn_long.log")
        rig.check(t)
    assert rig.dev(MAC_D)["state"] == rig.dev(MAC_E)["state"] == "up"
    assert rig.events() == []


def test_the_writing_delay_allowance_prevents_a_false_offline(rig):
    rig.watch()
    rig.check(at("11:40"))
    rig.conn(D, ROUTER, at("11:41"), at("11:42"))
    rig.conn(D, ROUTER, at("11:50"), at("12:00"))  # last packet 12:00
    # active 12:14-12:22, written when it closes at 12:23
    rig.conn(D, ROUTER, at("12:14"), at("12:22"), visible=at("12:23"))
    rig.checks(at("11:45"), at("12:10"))
    rig.check(at("12:16"))
    rig.check(at("12:21"))
    assert rig.events() == []
    rig.check(at("12:26"))
    assert rig.dev()["seen_at"] == iso(at("12:22")) and rig.events() == []


def test_without_the_allowance_that_timeline_would_invent_an_outage(tmp_path):
    rig = Rig(tmp_path)
    with patch.object(wr, "LOG_DELAY", timedelta(0)):
        rig.watch()
        rig.check(at("11:40"))
        rig.conn(D, ROUTER, at("11:41"), at("11:42"))
        rig.conn(D, ROUTER, at("11:50"), at("12:00"))
        rig.conn(D, ROUTER, at("12:14"), at("12:22"), visible=at("12:23"))
        rig.checks(at("11:45"), at("12:10"))
        rig.check(at("12:16"))
        rig.check(at("12:21"))
    assert _types(rig) == [
        "device_offline"
    ]  # the contrast that makes the test above mean something


def test_a_future_dated_record_is_ignored(rig):
    rig.watch()
    rig.check(at("12:00"))
    rig.conn(D, ROUTER, at("12:01"), at("12:02"))
    rig.conn(D, ROUTER, at("14:00"), at("14:01"), visible=at("12:00"))
    rig.check(at("12:05"))
    assert rig.dev()["seen_at"] == iso(at("12:02"))
    assert rig.state()["check"]["capture_at"] == iso(at("12:04", 30))


# --- a backlog fakes nothing ---------------------------------------------------


def test_a_drained_backlog_doesnt_make_capture_live(rig):
    rig.bring_up()
    rig.background = False
    # the pipeline stalls at 12:05; at 12:40 a record from 12:06 drains in
    rig.conn(OTHER, ROUTER, at("12:06"), visible=at("12:40"))
    rig.check(at("12:40"))
    check = rig.state()["check"]
    assert check["skipped"] == "pipeline" and rig.dev()["state"] == "up"
    assert rig.events() == []


def test_a_backlog_neither_recovers_nor_enrolls(rig):
    rig.bring_down()
    rig.watch(MAC_E)
    rig.check(at("12:40"))  # E enrolled at 12:40
    # old records indexed late: D before its declaration, E before its enrollment
    rig.conn(D, ROUTER, at("12:30"), at("12:31"), visible=at("12:44"))
    rig.conn(E, ROUTER, at("12:38"), at("12:39"), visible=at("12:44"))
    rig.check(at("12:45"))
    assert rig.dev(MAC_D)["state"] == "down" and rig.dev(MAC_E)["state"] == "unknown"
    assert _types(rig) == ["device_offline"]


# --- streaks and coverage ------------------------------------------------------


def _with_streak(rig) -> None:
    rig.bring_up()
    rig.checks(at("12:10"), at("12:30"))
    assert rig.dev()["silent_from"] is not None


def test_a_skip_clears_the_streak_and_coverage(rig):
    _with_streak(rig)
    rig.health = {**MIRROR, "promisc_enabled": False}
    rig.check(at("12:35"))
    assert rig.dev()["silent_from"] is None
    assert rig.state()["check"]["coverage_since"] is None
    rig.health = dict(MIRROR)
    rig.check(at("12:40"))
    assert rig.dev()["state"] == "up" and rig.events() == []
    assert rig.state()["check"]["coverage_since"] == iso(at("12:39", 30))


def test_a_failure_clears_the_streak(rig):
    _with_streak(rig)

    def fail(body):
        if is_presence(body):
            raise OpenSearchException("down")

    rig.index.hook = fail
    with pytest.raises(wd.QueryFailed):
        rig.check(at("12:35"))
    assert rig.dev()["silent_from"] is None
    assert rig.state()["check"]["error"] == wd.ERR_SEARCH
    rig.index.hook = None
    rig.check(at("12:40"))
    assert rig.dev()["state"] == "up" and rig.events() == []


def test_a_capture_gap_over_900_s_restarts_coverage(rig):
    _with_streak(rig)
    rig.check(at("12:46"))  # 16 minutes after the last successful check
    assert rig.dev()["state"] == "up" and rig.events() == []
    assert rig.state()["check"]["coverage_since"] == iso(at("12:45", 30))


def test_a_restart_into_a_fresh_pipeline_needs_new_checks(rig):
    _with_streak(rig)
    rig.watcher = rig.new_watcher()  # the daemon was down 12:30-13:30
    rig.check(at("13:30"))
    rig.check(at("13:35"))
    assert rig.dev()["state"] == "up" and rig.events() == []


def test_a_manual_run_seconds_later_isnt_a_second_check(rig):
    _with_streak(rig)
    rig.check(at("12:30", 10))
    assert rig.dev()["state"] == "up" and rig.events() == []
    rig.check(at("12:35"))
    assert _types(rig) == ["device_offline"]


def test_silence_never_counts_a_known_capture_gap(rig):
    rig.watch(MAC_D, 60)
    rig.check(at("11:50"))
    rig.conn(D, ROUTER, at("11:54"), at("11:55"))
    rig.check(at("11:56"))
    rig.background = False  # capture down 12:00-14:00
    rig.checks(at("12:00"), at("14:00"))
    assert rig.state()["check"]["skipped"] == "pipeline"
    rig.background = True
    rig.check(at("14:05"))
    rig.check(at("14:10"))
    assert rig.dev()["state"] == "up" and rig.events() == []


def test_capture_older_than_ten_minutes_pauses(rig):
    rig.bring_up()
    rig.background = False
    rig.conn(OTHER, ROUTER, at("12:08"), visible=at("12:08"))
    rig.check(at("12:19"))
    assert rig.state()["check"]["skipped"] == "pipeline"


# --- readiness and scope --------------------------------------------------------


@pytest.mark.parametrize(
    ("health", "reason"),
    [
        ({**MIRROR, "promisc_enabled": False}, "promiscuous mode is off"),
        ({**GATEWAY, "routing_active": False}, "DHCP gateway routing is off"),
        ({**GATEWAY, "status": "degraded"}, "capture is degraded"),
        (
            {**MIRROR, "status": "not_configured", "link_up": False, "stub": True},
            "capture is still starting",
        ),
        ({**MIRROR, "mode": "bridge"}, "bridge mode can't tell devices apart"),
        (TimeoutError("5 s"), wd.NO_HEALTH),
    ],
)
def test_capture_not_ready_skips_with_fresh_traffic_and_clears_streaks(
    rig, health, reason
):
    _with_streak(rig)
    rig.health = health
    rig.conn(OTHER, ROUTER, at("12:34"), visible=at("12:34"))  # fresh broadcasts
    searches = len(rig.index.calls)
    rig.check(at("12:35"))
    check = rig.state()["check"]
    assert (check["skipped"], check["reason"], check["error"]) == ("mode", reason, None)
    assert rig.dev()["silent_from"] is None and rig.events() == []
    assert len(rig.index.calls) == searches


def test_a_skip_still_prunes_and_enrolls(rig):
    rig.watch(MAC_D)
    rig.check(at("12:00"))
    rig.health = {**MIRROR, "link_up": False}
    rig.watch(MAC_D, None)
    rig.watch(MAC_E, 30)
    rig.check(at("12:05"))
    devices = rig.state()["devices"]
    assert list(devices) == [MAC_E] and devices[MAC_E]["after_min"] == 30
    assert devices[MAC_E]["enrolled_at"] == iso(at("12:05"))


def test_a_scope_change_rebaselines_every_watch(rig):
    rig.bring_up()
    assert rig.state()["check"]["scope"] == "mirror|enp1s0"
    rig.health = dict(GATEWAY)
    rig.conn(D, ROUTER, at("12:06"), at("12:09"))
    rig.check(at("12:10"))
    dev = rig.dev()
    assert (dev["state"], dev["enrolled_at"], dev["silent_from"]) == (
        "unknown",
        iso(at("12:10")),
        None,
    )
    assert rig.state()["check"]["scope"] == "dhcp_gateway|enp2s0|10.77.0.0/24"
    assert rig.events() == []


def test_a_scope_reset_while_down_journals_the_carried_recovery(rig):
    rig.bring_down()
    seen = rig.dev()["incident"]["seen_at"]
    rig.health = dict(GATEWAY)
    rig.check(at("12:40"))
    assert rig.dev()["state"] == "unknown" and rig.dev()["incident"]["seen_at"] == seen
    rig.conn(D, ROUTER, at("12:41"), at("12:42"))
    rig.check(at("12:45"))
    online = rig.events()[-1]
    assert online["type"] == "device_online"
    assert online["id"] == event_id("device_online", MAC_D, "up|" + seen)
    assert online["data"]["back_at"] == iso(at("12:41"))
    assert rig.dev()["incident"] is None


def test_a_scope_change_during_the_search_drops_the_transitions(rig):
    _with_streak(rig)
    rig.index.hook = lambda body: (
        rig.__setattr__("health", dict(GATEWAY)) if is_presence(body) else None
    )
    rig.check(at("12:35"))
    assert rig.dev()["state"] == "up" and rig.events() == []


# --- the watch list --------------------------------------------------------------


def test_no_watches_means_no_search_and_a_successful_check(rig):
    rig.check(at("12:00"))
    check = rig.state()["check"]
    assert rig.index.calls == [] and check["success_at"] == iso(at("12:00"))
    assert check["skipped"] is None and check["error"] is None


def test_a_changed_time_resets_the_streak(rig):
    _with_streak(rig)
    rig.watch(MAC_D, 30)
    rig.check(at("12:35"))
    dev = rig.dev()
    assert dev["after_min"] == 30 and dev["state"] == "up" and rig.events() == []


@pytest.mark.parametrize("change", [30, None])
def test_a_watch_edited_during_the_search_drops_the_transition(rig, change):
    _with_streak(rig)

    def edit(body):
        if is_presence(body):
            # the edit commits on another thread before the job's commit (order 1)
            t = threading.Thread(target=rig.watch, args=(MAC_D, change))
            t.start()
            t.join()

    rig.index.hook = edit
    rig.check(at("12:35"))
    assert rig.events() == [] and rig.dev()["state"] == "up"


def test_an_edit_waiting_on_the_lock_lands_after_the_transition(rig):
    """Order 2: watch_is is held first; the edit waits until the transition is saved."""
    _with_streak(rig)
    real_save, held = rig.watcher._save, []
    editor = threading.Thread(target=rig.watch, args=(MAC_D, 30))

    def save(state):
        if state["devices"][MAC_D]["pending"] is not None:
            got = rig.details._lock.acquire(blocking=False)
            if got:
                rig.details._lock.release()
            held.append(not got)  # the store's lock is held while the pending is saved
            editor.start()  # its update can only land once the lock is released
        real_save(state)

    rig.watcher._save = save
    rig.check(at("12:35"))
    editor.join(5)
    assert held == [True]
    (offline,) = rig.events()
    assert offline["data"]["after_min"] == 15
    assert rig.details.get(MAC_D)["watch_after_min"] == 30


# --- the two-phase commit ------------------------------------------------------


def test_a_crash_before_the_append_is_finished_by_the_next_run(rig):
    _with_streak(rig)
    with patch.object(rig.journal, "append", side_effect=OSError("disk full")):
        with pytest.raises(wd.JournalFailed):
            rig.check(at("12:35"))
    pending = rig.dev()["pending"]
    assert pending["type"] == "device_offline" and pending["observed_at"] == iso(
        at("12:35")
    )
    assert rig.state()["check"]["error"] == wd.ERR_JOURNAL
    rig.check(at("12:40"))
    (offline,) = rig.events()
    assert offline["observed_at"] == iso(at("12:35")) and rig.dev()["pending"] is None


def test_a_crash_after_the_append_repeats_nothing(rig):
    _with_streak(rig)
    real_save, real_append, appended = rig.watcher._save, rig.journal.append, []

    def append(*args, **kwargs):
        appended.append(True)
        return real_append(*args, **kwargs)

    def save(state):
        if (
            appended
            and len(appended) == 1
            and state["devices"][MAC_D]["pending"] is None
        ):
            appended.append(True)
            raise OSError("disk gone")
        real_save(state)

    rig.journal.append, rig.watcher._save = append, save
    with pytest.raises(OSError):
        rig.check(at("12:35"))
    assert rig.dev()["pending"] is not None
    rig.check(at("12:40"))
    assert _types(rig) == ["device_offline"] and rig.dev()["pending"] is None


def test_a_failed_first_save_journals_nothing_and_decides_again(rig):
    _with_streak(rig)
    real_save, failed = rig.watcher._save, []

    def save(state):
        if not failed and state["devices"][MAC_D]["pending"] is not None:
            failed.append(True)
            raise OSError("read-only")
        real_save(state)

    rig.watcher._save = save
    with pytest.raises(OSError):
        rig.check(at("12:35"))
    assert rig.events() == [] and rig.dev()["state"] == "up"
    assert rig.state()["check"]["error"] == wd.ERR_SAVE
    rig.checks(at("12:40"), at("13:20"))
    assert _types(rig) == ["device_offline"]


def test_a_restart_while_down_gives_the_same_recovery_id(rig):
    rig.bring_down()
    seen = rig.dev()["incident"]["seen_at"]
    rig.watcher = rig.new_watcher()
    rig.conn(D, ROUTER, at("12:51"), at("12:52"))
    rig.check(at("12:55"))
    assert rig.events()[-1]["id"] == event_id("device_online", MAC_D, "up|" + seen)


def _write_pending(rig, observed_at: str) -> None:
    rig.bring_up()
    state = rig.state()
    pending = {
        "type": "device_offline",
        "key": MAC_D,
        "instance": "down|x",
        "observed_at": observed_at,
        "data": {"mac": MAC_D},
    }
    state["devices"][MAC_D]["pending"] = pending
    rig.path.write_text(json.dumps(state))


def test_a_pending_older_than_24_hours_is_dropped(rig):
    _write_pending(rig, iso(at("12:05") - timedelta(hours=24, minutes=1)))
    rig.check(at("12:10"))
    assert rig.events() == [] and rig.dev()["pending"] is None


def test_a_pending_under_24_hours_is_appended_as_saved(rig):
    _write_pending(rig, iso(at("12:05") - timedelta(hours=23)))
    rig.check(at("12:10"))
    (entry,) = rig.events()
    assert entry["observed_at"] == iso(at("12:05") - timedelta(hours=23))
    assert entry["id"] == event_id("device_offline", MAC_D, "down|x")


@pytest.mark.parametrize(
    "content",
    [b"{not json", b'{"version": 2, "check": {}, "devices": {}}', b"[]"],
)
def test_an_unreadable_state_file_is_never_overwritten(rig, content):
    rig.watch()
    rig.path.write_bytes(content)
    with pytest.raises(wd.StateUnreadable):
        rig.check(at("12:00"))
    assert rig.path.read_bytes() == content and rig.index.calls == []


def test_a_corrupt_state_file_logs_only_the_reason(rig, caplog):
    # invalid UTF-8 after a device name: a UnicodeDecodeError's repr would carry it all
    content = b'{"devices": {"Kitchen plug secret": "' + b"x" * 200_000 + b'\xff"}}'
    rig.watch()
    rig.path.write_bytes(content)
    with pytest.raises(wd.StateUnreadable):
        rig.check(at("12:00"))
    (record,) = [r for r in caplog.records if r.name == wd.logger.name]
    line = record.getMessage()
    assert "can't decode byte 0xff" in line
    assert len(line) < 400 and "Kitchen plug" not in line


def test_a_damaged_details_store_skips_and_clears_streaks(rig):
    _with_streak(rig)
    rig.details._problem = "Device details file is unreadable: test"
    rig.check(at("12:35"))
    check = rig.state()["check"]
    assert (check["skipped"], check["error"], check["coverage_since"]) == (
        "store",
        None,
        None,
    )
    assert rig.dev()["silent_from"] is None and rig.events() == []


def test_a_failed_search_after_a_scope_change_changes_no_device(rig):
    rig.bring_up()
    before = rig.dev()
    rig.health = dict(GATEWAY)

    def fail(body):
        if is_presence(body):
            raise OpenSearchException("down")

    rig.index.hook = fail
    with pytest.raises(wd.QueryFailed):
        rig.check(at("12:10"))
    assert rig.dev() == before  # not re-baselined
    assert rig.state()["check"]["scope"] == "mirror|enp1s0"


def test_a_transport_timeout_is_too_slow(rig):
    rig.bring_up()

    def time_out(body):
        if is_presence(body):
            raise ConnectionTimeout("TIMEOUT", "Read timed out", TimeoutError())

    rig.index.hook = time_out
    with pytest.raises(wd.TooSlow):
        rig.check(at("12:10"))
    assert rig.state()["check"]["error"] == wd.ERR_SLOW


# --- refused replies -----------------------------------------------------------


def _refuse(field: str):
    def patch_reply(reply, body):
        if not is_presence(body):
            return reply
        if field == "timed_out":
            return {**reply, "timed_out": True}
        if field == "failed":
            return {**reply, "_shards": {**reply["_shards"], "failed": 1}}
        if field == "total":
            return {**reply, "_shards": {**reply["_shards"], "total": 0}}
        return {k: v for k, v in reply.items() if k != "aggregations"}

    return patch_reply


@pytest.mark.parametrize(
    ("field", "error"),
    [
        ("timed_out", wd.ERR_SLOW),
        ("failed", wd.ERR_SEARCH),
        ("total", wd.ERR_SEARCH),
        ("aggregations", wd.ERR_SEARCH),
    ],
)
def test_a_refused_reply_changes_no_device(rig, field, error):
    rig.bring_up()
    rig.conn(D, ROUTER, at("12:06"), at("12:07"))
    rig.index.patch = _refuse(field)
    with pytest.raises(wd.QueryFailed):
        rig.check(at("12:10"))
    dev = rig.dev()
    assert (dev["state"], dev["seen_at"]) == ("up", iso(at("12:02")))
    assert rig.state()["check"]["error"] == error


# --- the answered side -----------------------------------------------------------


def test_a_one_way_send_credits_the_sender_not_the_target(rig):
    rig.watch(MAC_D)
    rig.watch(MAC_E)
    rig.check(at("12:00"))
    rig.conn(D, E, at("12:01"), replies=False)  # A→B, S0, no reply
    rig.conn(OTHER, E, at("12:02"), replies=False, state="S0")
    rig.check(at("12:05"))
    assert rig.dev(MAC_D)["state"] == "up" and rig.dev(MAC_E)["state"] == "unknown"


def test_an_answer_with_replies_credits_the_responder(rig):
    rig.watch(MAC_E)
    rig.check(at("12:00"))
    rig.conn(OTHER, E, at("12:01"), at("12:03"))
    rig.check(at("12:05"))
    assert rig.dev(MAC_E)["state"] == "up"
    assert rig.dev(MAC_E)["seen_at"] == iso(at("12:03"))


# --- the scheduler -----------------------------------------------------------


def test_one_run_through_the_real_scheduler(rig, tmp_path):
    rig.watch()
    rig.conn(OTHER, ROUTER, at("11:59"), visible=at("12:00"))

    async def go():
        scheduler = Scheduler(
            [
                Job(
                    "watched-devices",
                    "Watched devices",
                    every_s=300,
                    deadline_s=60,
                    run=rig.watcher.run,
                )
            ],
            str(tmp_path / "jobs.json"),
        )
        assert scheduler.tick() == ["watched-devices"]
        await _settle(scheduler, "watched-devices")
        return scheduler.view()

    (row,) = asyncio.run(go())
    assert row["last_error"] is None and row["name"] == "watched-devices"
    assert rig.state()["check"]["success_at"] == iso(at("12:00"))
    timeouts = [timeout for _, _, timeout in rig.index.calls]
    assert len(timeouts) == 2 and all(0 < t <= 60 for t in timeouts)
    for _, body, timeout in rig.index.calls:
        assert body["timeout"] == f"{int(timeout * 1000)}ms"
