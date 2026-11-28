"""NET-340: the weekly report's state machine (plan §3.2-§3.3, §6 "test_report_generator.py").

Consent, the watermark, the confirm token, staging, durability, the send commitment, recovery,
manual reports and the generation lock. The contents (report_sections) and the email text
(report_text) are stubbed: their own tests cover them. Times are UTC unless a test says so;
Monday 16 November 2026 08:00 is the send time used throughout.
"""

import json
import os
import stat
import sys
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import report_generator, report_schedule  # noqa: E402
from services.report_generator import ReportGenerator, ReportRefused  # noqa: E402
from services.report_schedule import UNKNOWN_SEND  # noqa: E402

UTC = timezone.utc
SUNDAY = datetime(2026, 11, 15, 12, tzinfo=UTC)
MONDAY_0805 = datetime(2026, 11, 16, 8, 5, tzinfo=UTC)
SECTIONS = ("traffic", "alerts", "new_devices", "offline", "data_cap")


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class Ledger:
    def __init__(self, tz: str = "UTC") -> None:
        self.tz = tz

    def snapshot(self) -> dict:
        return {"tz": self.tz}


class Hub:
    """send_report_email that records each attempt; `during` runs mid-send."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.parts: list[tuple] = []  # (html, logo) per attempt (NET-381)
        self.during = None

    # OLD CODE: def send_report_email(self, recipients, subject, text) -> dict: (NET-381: html, logo)
    def send_report_email(
        self, recipients, subject, text, html=None, logo=None
    ) -> dict:
        self.calls.append(list(recipients))
        self.parts.append((html, logo))
        if self.during:
            self.during()
        return {"result": "sent", "refused": [], "error": None}


class Crash(BaseException):
    """The process stopping: escapes every `except Exception`."""


class _Built(list):
    """(period, deadline) per build, and the stub itself (`.build.hook` runs mid-build)."""

    build = None


@pytest.fixture(autouse=True)
def contents(monkeypatch):
    """Stub contents and email text; the list collects (period, deadline) per build."""
    built = _Built()

    def build(period, deps, deadline):
        built.append((period, deadline))
        hook = getattr(build, "hook", None)
        if hook:
            hook()
        return {
            name: {"status": "ok", "coverage": "x", "note": None} for name in SECTIONS
        }

    monkeypatch.setattr("services.report_sections.build_sections", build)
    text = types.SimpleNamespace(render_email=lambda report: ("Subject", "Body"))
    monkeypatch.setitem(sys.modules, "services.report_text", text)
    # NET-381: a working HTML renderer that records the cid it was given
    built.cids = []

    def render_html(report, cid):
        built.cids.append(cid)
        return f"<p>{cid}</p>"

    page = types.SimpleNamespace(render_html=render_html, logo_png=lambda: b"PNG")
    monkeypatch.setitem(sys.modules, "services.report_html", page)
    built.build = build
    return built


class Rig:
    def __init__(self, root: Path, now: datetime = SUNDAY, tz: str = "UTC") -> None:
        self.root = root
        self.clock = Clock(now)
        self.ledger = Ledger(tz)
        self.hub = Hub()
        self.gen = self.restart()

    def restart(self) -> ReportGenerator:
        """A new generator on the same files, as after a daemon restart or an upgrade."""
        self.gen = ReportGenerator(
            reports_dir=str(self.root / "reports"),
            schedules_file=str(self.root / "report_schedules.json"),
            deps=types.SimpleNamespace(ledger=self.ledger),
            hub=self.hub,
            now=self.clock,
        )
        return self.gen

    def confirmed(self, **fields) -> dict:
        """The card's schedule, saved and confirmed: only the card sends email."""
        body = {
            "recipients": ["owner@example.com"],
            "weekday": 0,
            "hour": 8,
            "confirm": True,
            **fields,
        }
        # OLD CODE: return self.gen.create(body) (security review: only the card confirms)
        return self.gen.upsert_card(body)[0]

    def confirmed_below_the_api(self, **fields) -> dict:
        """A confirmed schedule that isn't the card. No route makes one (only the card
        confirms); the job's own rules, such as one report per tick, are checked with it."""
        body = {"name": "W", "recipients": ["second@example.com"], "confirm": True}
        with self.gen._state_lock:
            return self.gen._create_locked({**body, **fields}, card=False)

    def tick(self, deadline_s: float = 240) -> None:
        self.gen.run_due(time.monotonic() + deadline_s)

    def reports(self, sid: str) -> list[Path]:
        return sorted((self.root / "reports" / sid).glob("*.json"))

    def schedules_file(self) -> list:
        return json.loads((self.root / "report_schedules.json").read_text())

    def write_schedules_file(self, rows: list) -> None:
        (self.root / "report_schedules.json").write_text(json.dumps(rows))


@pytest.fixture
def rig(tmp_path) -> Rig:
    return Rig(tmp_path)


def _legacy_row(sid="5f0d0f6e-7b8a-4c3d-9e2f-1a2b3c4d5e6f", **over) -> dict:
    """A schedule as the old daemon wrote it: enabled, recipients, no sidecar entry."""
    return {
        "id": sid,
        "name": "Old",
        "frequency": "weekly",
        "format": "html",
        "recipients": ["owner@example.com"],
        "sections": ["traffic_summary", "risk"],
        "enabled": True,
        "last_run": None,
        "next_run": "2026-11-16T06:00:00+00:00",
        "created_at": "2026-01-01T00:00:00+00:00",
        **over,
    }


# --- running ---------------------------------------------------------------------


def test_a_confirmed_schedule_sends_once_at_its_boundary(rig):
    sid = rig.confirmed()["id"]
    rig.tick()
    assert (
        rig.hub.calls == []
    )  # Sunday: last Monday's week was the watermark at confirm
    rig.clock.now = MONDAY_0805
    rig.tick()
    rig.tick()
    assert rig.hub.calls == [["owner@example.com"]]
    view = rig.gen.view(sid)
    assert view["last_period"] == {"first": "2026-11-09", "last": "2026-11-15"}
    assert view["last_delivery"]["result"] == "sent"
    (path,) = rig.reports(sid)
    report = json.loads(path.read_text())
    assert report["delivery"]["result"] == "sent"
    assert report["delivery"]["recipients"] == 1
    assert "owner@example.com" not in path.read_text()  # counts only, never addresses
    stored = rig.schedules_file()[0]
    assert stored["last_run"] == report["generated_at"]
    assert stored["next_run"] == "2026-11-23T08:00:00Z"


def test_one_due_schedule_per_tick(rig):
    rig.confirmed()
    # OLD CODE: rig.confirmed(recipients=["second@example.com"]) (only the card confirms)
    rig.confirmed_below_the_api()
    rig.clock.now = MONDAY_0805
    rig.tick()
    assert len(rig.hub.calls) == 1
    rig.tick()
    assert len(rig.hub.calls) == 2
    rig.tick()
    assert len(rig.hub.calls) == 2


def test_each_send_carries_the_html_part_with_its_own_logo_cid(rig, contents):
    rig.confirmed()
    rig.confirmed_below_the_api()
    rig.clock.now = MONDAY_0805
    rig.tick()
    rig.tick()
    assert len(rig.hub.parts) == 2
    for (html, (cid, png)), rendered in zip(rig.hub.parts, contents.cids):
        assert cid == rendered and html == f"<p>{cid}</p>" and png == b"PNG"
        assert "@" in cid and not cid.startswith("<")
    assert contents.cids[0] != contents.cids[1]


def test_a_failed_html_render_still_sends_the_plain_email(rig, monkeypatch):
    def broken(report, cid):
        raise ValueError("bad template")

    monkeypatch.setattr(sys.modules["services.report_html"], "render_html", broken)
    sid = rig.confirmed()["id"]
    rig.clock.now = MONDAY_0805
    rig.tick()
    assert rig.hub.calls == [["owner@example.com"]]
    assert rig.hub.parts == [(None, None)]
    assert rig.gen.view(sid)["last_delivery"]["result"] == "sent"


def test_three_missed_boundaries_give_one_report(rig, contents):
    sid = rig.confirmed()["id"]
    rig.clock.now = MONDAY_0805 + timedelta(weeks=2, hours=3)
    rig.tick()
    rig.tick()
    assert len(rig.hub.calls) == 1
    period = contents[-1][0]
    assert (str(period.first), str(period.last)) == ("2026-11-23", "2026-11-29")
    assert len(rig.reports(sid)) == 1


def test_an_edit_during_generation_discards_the_run_and_the_next_tick_sends(
    rig, contents
):
    sid = rig.confirmed()["id"]
    contents.build.hook = lambda: rig.gen.update(sid, {"name": "Renamed"})
    rig.clock.now = MONDAY_0805
    rig.tick()
    assert rig.hub.calls == [] and rig.reports(sid) == []
    contents.build.hook = None
    rig.tick()
    assert len(rig.hub.calls) == 1


def test_no_recipients_means_stored_but_not_emailed(rig):
    sid = rig.confirmed(recipients=[])["id"]
    rig.clock.now = MONDAY_0805
    rig.tick()
    assert rig.hub.calls == []
    assert rig.gen.view(sid)["last_delivery"]["result"] == "not_emailed"
    assert json.loads(rig.reports(sid)[0].read_text())["delivery"]["result"] == (
        "not_emailed"
    )


def test_the_job_passes_one_absolute_deadline_to_the_contents(rig, contents):
    rig.confirmed()
    rig.clock.now = MONDAY_0805
    deadline = time.monotonic() + 240
    rig.gen.run_due(deadline)
    assert contents[-1][1] <= deadline - 30


def test_a_busy_generation_lock_skips_the_job_and_refuses_generate_now(rig):
    sid = rig.confirmed()["id"]
    rig.clock.now = MONDAY_0805
    rig.gen._gen_lock.acquire()
    try:
        rig.tick()
        started = time.monotonic()
        with pytest.raises(ReportRefused) as exc:
            rig.gen.generate_now(sid)
        assert exc.value.status == 409 and time.monotonic() - started < 1
    finally:
        rig.gen._gen_lock.release()
    assert rig.hub.calls == []


# --- consent ---------------------------------------------------------------------


def test_a_legacy_file_through_a_tick_sends_nothing(tmp_path):
    (tmp_path / "report_schedules.json").write_text(json.dumps([_legacy_row()]))
    rig = Rig(tmp_path, now=MONDAY_0805)
    rig.tick()
    assert rig.hub.calls == []
    (view,) = rig.gen.list_views()
    assert (view["confirmed"], view["needs_review"], view["rev"]) == (False, True, 0)


def test_a_name_only_put_on_a_legacy_schedule_leaves_it_paused(tmp_path):
    (tmp_path / "report_schedules.json").write_text(json.dumps([_legacy_row()]))
    rig = Rig(tmp_path, now=MONDAY_0805)
    sid = _legacy_row()["id"]
    view = rig.gen.update(sid, {"name": "Renamed"})
    assert view["needs_review"] and view["rev"] == 1
    rig.tick()
    assert rig.hub.calls == []


def test_an_old_daemons_edit_pauses_the_schedule_after_the_upgrade(rig):
    sid = rig.confirmed()["id"]
    # rolled back: the old daemon changes the recipients and never reads the sidecar
    rows = rig.schedules_file()
    rows[0]["recipients"] = ["attacker@example.com"]
    rig.write_schedules_file(rows)
    rig.clock.now = MONDAY_0805
    rig.restart()
    rig.tick()
    assert rig.hub.calls == []
    assert rig.gen.view(sid)["needs_review"]


def test_narrowing_sections_on_an_old_daemon_pauses_through_the_first_tick(rig):
    sid = rig.confirmed()["id"]
    rows = rig.schedules_file()
    rows[0]["sections"] = ["traffic_summary"]
    rig.write_schedules_file(rows)
    rig.clock.now = MONDAY_0805
    rig.restart()
    rig.tick()
    assert rig.hub.calls == [] and rig.gen.view(sid)["needs_review"]


def test_schedules_written_without_the_sidecar_pause_the_schedule(rig):
    """A restore that wrote the schedules file and stopped (or a hand edit) never sends."""
    sid = rig.confirmed()["id"]
    rows = rig.schedules_file()
    rows[0]["recipients"] = ["new@example.com"]
    rig.write_schedules_file(rows)
    rig.restart()
    rig.clock.now = MONDAY_0805
    rig.tick()
    assert rig.hub.calls == [] and rig.gen.view(sid)["needs_review"]


def test_enabling_never_confirms(rig):
    sid = rig.gen.create({"name": "API only", "recipients": ["a@example.com"]})["id"]
    rig.gen.set_enabled(sid, False)
    view = rig.gen.set_enabled(sid, True)
    assert not view["confirmed"]
    rig.clock.now = MONDAY_0805
    rig.tick()
    assert rig.hub.calls == []


# --- the watermark ---------------------------------------------------------------


def test_moving_the_hour_after_a_send_doesnt_send_the_week_again(rig):
    sid = rig.confirmed()["id"]
    rig.clock.now = MONDAY_0805
    rig.tick()
    rig.clock.now = MONDAY_0805 + timedelta(hours=1)
    token = rig.gen.view(sid)["confirm_token"]
    rig.gen.update(sid, {"hour": 18, "confirm": True, "confirm_token": token})
    rig.clock.now = MONDAY_0805 + timedelta(hours=10)
    rig.tick()
    assert len(rig.hub.calls) == 1


def test_a_weekday_edit_after_a_send_doesnt_send_at_once(rig):
    sid = rig.confirmed()["id"]
    rig.clock.now = MONDAY_0805
    rig.tick()
    token = rig.gen.view(sid)["confirm_token"]
    rig.gen.update(sid, {"weekday": 1, "confirm": True, "confirm_token": token})
    rig.tick()
    assert len(rig.hub.calls) == 1


def test_a_zone_change_doesnt_send_again(rig):
    rig.confirmed()
    rig.clock.now = MONDAY_0805
    rig.tick()
    rig.ledger.tz = (
        "Pacific/Auckland"  # local Monday 21:05: a week boundary passed there too
    )
    rig.tick()
    assert len(rig.hub.calls) == 1


def test_an_unchanged_save_between_the_boundary_and_the_tick_doesnt_skip(rig):
    sid = rig.confirmed()["id"]
    rig.clock.now = MONDAY_0805 - timedelta(minutes=4)
    view = rig.gen.view(sid)
    rig.gen.update(
        sid,
        {
            "recipients": ["owner@example.com"],
            "hour": 8,
            "confirm": True,
            "confirm_token": view["confirm_token"],
        },
    )
    rig.clock.now = MONDAY_0805
    rig.tick()
    assert len(rig.hub.calls) == 1


def test_confirming_a_paused_schedule_skips_the_weeks_it_missed(rig):
    # OLD CODE: sid = rig.gen.create({"name": "W", "recipients": ["a@example.com"]})["id"]
    sid = rig.gen.upsert_card({"recipients": ["a@example.com"]})[0][
        "id"
    ]  # not confirmed
    rig.clock.now = MONDAY_0805 + timedelta(days=2)
    token = rig.gen.view(sid)["confirm_token"]
    # OLD CODE: rig.gen.update(sid, {"confirm": True, "confirm_token": token})
    rig.gen.upsert_card({"confirm": True, "confirm_token": token})
    rig.tick()
    assert rig.hub.calls == []
    assert rig.gen.view(sid)["last_period"]["last"] == "2026-11-15"


# --- the confirm token -------------------------------------------------------------


def test_a_token_from_before_an_old_daemons_edit_is_refused(rig):
    sid = rig.confirmed()["id"]
    shown = rig.gen.view(sid)
    rows = rig.schedules_file()
    rows[0]["recipients"] = ["attacker@example.com"]  # sidecar rev unchanged
    rig.write_schedules_file(rows)
    rig.restart()
    with pytest.raises(ReportRefused) as exc:
        rig.gen.update(sid, {"confirm": True, "confirm_token": shown["confirm_token"]})
    assert exc.value.status == 409
    rig.clock.now = MONDAY_0805
    rig.tick()
    assert rig.hub.calls == []


def test_a_stale_rev_or_token_from_another_window_is_refused(rig):
    sid = rig.confirmed()["id"]
    shown = rig.gen.view(sid)
    rig.gen.update(sid, {"name": "Changed elsewhere"})
    for body in (
        {"rev": shown["rev"], "name": "Mine"},
        {"confirm": True, "confirm_token": shown["confirm_token"]},
        {"confirm": True},  # no token at all
    ):
        with pytest.raises(ReportRefused) as exc:
            rig.gen.update(sid, body)
        assert exc.value.status == 409
    assert rig.gen.view(sid)["name"] == "Changed elsewhere"


def test_a_replaced_card_refuses_the_old_cards_token(rig):
    card, created = rig.gen.upsert_card(
        {"recipients": ["a@example.com"], "confirm": True}
    )
    assert card["rev"] == 1 and card["card"] and created
    rig.gen.delete(card["id"])
    new, created = rig.gen.upsert_card(
        {"recipients": ["a@example.com"], "confirm": True}
    )
    assert new["rev"] == 1 and new["id"] != card["id"] and created
    with pytest.raises(ReportRefused) as exc:
        rig.gen.upsert_card(
            {"hour": 9, "confirm": True, "confirm_token": card["confirm_token"]}
        )
    assert exc.value.status == 409


def test_a_card_save_confirms_weekly_even_for_a_daily_card_schedule(rig):
    """Security review: a restored or API-edited card schedule could be daily, and the weekly
    card confirmed it as daily."""
    entry = {
        "id": "0b6c8f8e-6f1e-4c55-9a3e-2d7c1b0e9a11",
        "name": "Weekly report",
        "frequency": "daily",
        "format": "json",
        "recipients": ["a@example.com"],
        "sections": ["traffic_summary", "alerts", "devices"],
        "enabled": True,
        "created_at": "2026-11-01T00:00:00Z",
        "weekday": 0,
        "hour": 8,
        "card": True,
    }
    rig.gen.restore_backup([entry])
    token = rig.gen.view(entry["id"])["confirm_token"]
    saved, created = rig.gen.upsert_card({"confirm": True, "confirm_token": token})
    assert (saved["id"], saved["frequency"], created) == (entry["id"], "weekly", False)
    assert saved["confirmed"]


def test_the_card_counts_toward_the_schedule_limit(rig):
    for i in range(50):
        rig.gen.create({"name": f"S{i}"})
    with pytest.raises(ValueError):
        rig.gen.upsert_card({"recipients": ["a@example.com"], "confirm": True})
    assert len(rig.gen.list_schedules()) == 50


def test_only_the_card_can_be_confirmed(rig):
    """Security review: an API-only schedule confirmed for email is a hidden forwarding rule."""
    with pytest.raises(ValueError) as exc:
        rig.gen.create({"name": "W", "recipients": ["x@example.com"], "confirm": True})
    assert "Settings › Notifications" in str(exc.value)
    assert rig.gen.list_schedules() == []
    sid = rig.gen.create({"name": "W", "recipients": ["x@example.com"]})["id"]
    shown = rig.gen.view(sid)
    with pytest.raises(ValueError):
        rig.gen.update(sid, {"confirm": True, "confirm_token": shown["confirm_token"]})
    assert rig.gen.view(sid) == shown


def test_two_first_card_saves_make_one_schedule(rig):
    first, _ = rig.gen.upsert_card({"recipients": ["a@example.com"], "confirm": True})
    with pytest.raises(ReportRefused) as exc:  # the second tab saw no card, so no token
        rig.gen.upsert_card({"recipients": ["b@example.com"], "confirm": True})
    assert exc.value.status == 409
    assert [v["id"] for v in rig.gen.list_views()] == [first["id"]]
    assert first["name"] == "Weekly report" and first["frequency"] == "weekly"


def test_a_card_save_updates_the_card_schedule_not_the_first_listed(rig):
    # OLD CODE: other = rig.confirmed(frequency="daily") (only the card confirms)
    other = rig.gen.create({"name": "Other", "frequency": "daily"})
    card, _ = rig.gen.upsert_card({"recipients": ["a@example.com"], "confirm": True})
    saved, created = rig.gen.upsert_card(
        {"hour": 9, "confirm": True, "confirm_token": card["confirm_token"]}
    )
    assert saved["id"] == card["id"] and saved["hour"] == 9 and saved["confirmed"]
    assert not created
    assert rig.gen.view(other["id"])["hour"] == 8


# --- staging, durability and recovery ---------------------------------------------


def test_a_crash_after_staging_leaves_one_visible_report_for_the_period(rig):
    sid = rig.confirmed()["id"]
    leftover = rig.root / "reports" / sid / "20261116T080500Z-abcdef.json.staged"
    leftover.parent.mkdir(parents=True)
    leftover.write_text("{}")  # a crash before its claim was saved
    rig.clock.now = MONDAY_0805
    rig.restart()
    rig.tick()
    assert not leftover.exists()
    assert len(rig.reports(sid)) == 1 and len(rig.hub.calls) == 1


def _fail_for(path: Path, real):
    def wrapped(target, *args, **kwargs):
        if Path(target) == path:
            raise OSError("injected")
        return real(target, *args, **kwargs)

    return wrapped


def _raise(*_args, **_kwargs):
    raise OSError("injected")


@pytest.mark.parametrize("step", ["temp write", "replace", "directory fsync"])
def test_a_failed_claim_write_means_no_smtp_attempt(rig, monkeypatch, step):
    """Before the claim is durable nothing is sent. A failed directory fsync leaves the file
    replaced, so memory holds the claim too, and recovery reads it as unknown."""
    sid = rig.confirmed()["id"]
    meta = rig.root / "report_schedule_meta.json"
    real = {
        "temp write": (report_schedule, "write_file_atomic"),
        "replace": (os, "replace"),
        "directory fsync": (report_generator, "_fsync_dir"),
    }[step]
    original = getattr(*real)
    if step == "replace":
        failing = lambda src, dst: _fail_for(meta, lambda d: original(src, d))(dst)  # noqa: E731
    else:
        failing = _fail_for(meta if step == "temp write" else rig.root, original)
    monkeypatch.setattr(*real, failing)
    rig.clock.now = MONDAY_0805
    with pytest.raises(OSError):
        rig.tick()
    replaced = step == "directory fsync"  # the new sidecar is on disk, only not synced
    assert rig.hub.calls == [] and rig.reports(sid) == []
    assert rig.gen.view(sid)["sending"] is replaced  # memory matches the file
    monkeypatch.setattr(*real, original)
    rig.restart()
    rig.tick()
    assert not list((rig.root / "reports" / sid).glob("*.staged"))
    (path,) = rig.reports(sid)
    result = rig.gen.view(sid)["last_delivery"]["result"]
    if replaced:  # claimed, never sent: unknown, and the period isn't sent again
        assert rig.hub.calls == [] and result == "unknown"
    else:  # never claimed: the period is still due and goes now
        assert len(rig.hub.calls) == 1 and result == "sent"
    assert json.loads(path.read_text())["delivery"]["result"] == result


@pytest.mark.parametrize("step", ["staged rename", "reports-dir fsync", "prune"])
def test_a_file_error_after_the_claim_still_sends_once(rig, monkeypatch, step):
    """Python review: these lost the period with no send and read "NetTap stopped while
    sending". The claim is durable, so the send goes ahead."""
    sid = rig.confirmed()["id"]
    d = rig.root / "reports" / sid
    if step == "staged rename":
        original = os.replace

        def replace(src, dst):
            if str(src).endswith(".json.staged"):
                raise OSError("injected")
            return original(src, dst)

        monkeypatch.setattr(os, "replace", replace)
    elif step == "reports-dir fsync":
        monkeypatch.setattr(
            report_generator, "_fsync_dir", _fail_for(d, report_generator._fsync_dir)
        )
    else:
        monkeypatch.setattr(report_generator, "prune", _raise)
    rig.clock.now = MONDAY_0805
    rig.tick()
    rig.tick()  # recovery deletes a staged file left behind; nothing is sent again
    assert len(rig.hub.calls) == 1
    view = rig.gen.view(sid)
    assert view["last_delivery"]["result"] == "sent" and not view["sending"]
    (path,) = rig.reports(sid)
    assert json.loads(path.read_text())["delivery"]["result"] == "sent"
    assert not list(d.glob("*.staged"))


def test_a_failing_claim_write_holds_the_period_for_an_hour(rig, contents):
    """Review: a full disk rebuilt the whole report every 5 minutes; now once an hour."""
    sid = rig.confirmed()["id"]
    meta = rig.root / "report_schedule_meta.json"
    real = report_schedule.write_file_atomic
    report_schedule.write_file_atomic = _fail_for(meta, real)
    try:
        rig.clock.now = MONDAY_0805
        with pytest.raises(OSError):
            rig.tick()
        rig.clock.now = MONDAY_0805 + timedelta(minutes=55)
        rig.tick()  # held: no rebuild, no error
        assert len(contents) == 1
    finally:
        report_schedule.write_file_atomic = real
    rig.clock.now = MONDAY_0805 + timedelta(minutes=61)
    rig.tick()
    assert len(contents) == 2 and len(rig.hub.calls) == 1
    assert rig.gen.view(sid)["last_delivery"]["result"] == "sent"
    assert not (rig.root / "report_schedule_meta.json").read_text().count("held")


def test_the_sidecar_sits_beside_the_schedules_and_deadlines_use_the_real_clock():
    """Review: no meta_file or monotonic option, so the deadline is the sections' clock."""
    import inspect

    params = inspect.signature(ReportGenerator).parameters
    assert "meta_file" not in params and "monotonic" not in params


def test_a_crash_after_smtp_acceptance_reads_unknown_and_never_resends(rig):
    sid = rig.confirmed()["id"]

    def crash():
        raise Crash()

    rig.hub.during = crash  # the server accepted it, then NetTap stopped
    rig.clock.now = MONDAY_0805
    with pytest.raises(Crash):
        rig.tick()
    rig.hub.during = None
    rig.restart()
    rig.tick()
    assert len(rig.hub.calls) == 1
    view = rig.gen.view(sid)
    assert view["last_delivery"]["result"] == "unknown" and not view["sending"]
    report = json.loads(rig.reports(sid)[0].read_text())
    assert report["delivery"]["result"] == "unknown"
    assert report["delivery"]["error"] == UNKNOWN_SEND


def test_a_failed_result_save_gives_one_attempt_then_unknown(rig, monkeypatch):
    sid = rig.confirmed()["id"]
    rig.clock.now = MONDAY_0805
    real = report_schedule._write_durable

    def no_result(path, data):
        if (
            path.suffix == ".json"
            and (data.get("delivery") or {}).get("result") == "sent"
        ):
            raise OSError("injected")
        return real(path, data)

    monkeypatch.setattr("services.report_generator._write_durable", no_result)
    with pytest.raises(OSError):
        rig.tick()
    assert rig.gen.view(sid)["sending"]
    monkeypatch.setattr("services.report_generator._write_durable", real)
    rig.tick()  # recovery: no result with this claim in the report
    assert len(rig.hub.calls) == 1
    assert rig.gen.view(sid)["last_delivery"]["result"] == "unknown"


def test_a_crash_between_the_result_and_the_sidecar_recovers_the_real_result(
    rig, monkeypatch
):
    sid = rig.confirmed()["id"]
    rig.clock.now = MONDAY_0805
    gen = rig.gen
    real_commit = gen._commit
    calls = []

    def commit(schedules, meta):
        calls.append(1)
        if len(calls) == 2:  # 1: the claim, 2: the finish, after the report file
            raise Crash()
        return real_commit(schedules, meta)

    monkeypatch.setattr(gen, "_commit", commit)
    with pytest.raises(Crash):
        rig.tick()
    rig.restart()
    view = rig.gen.view(sid)
    assert view["last_delivery"]["result"] == "sent" and not view["sending"]
    assert len(rig.hub.calls) == 1


# --- the claim is a commitment ---------------------------------------------------


def test_destination_edits_and_deletes_are_refused_while_sending(rig):
    sid = rig.confirmed()["id"]
    seen = {}

    def during():
        view = rig.gen.view(sid)
        seen["sending"] = view["sending"]
        for change in (
            lambda: rig.gen.update(sid, {"recipients": ["x@example.com"]}),
            lambda: rig.gen.update(sid, {"hour": 9}),
            lambda: rig.gen.set_enabled(sid, False),
            lambda: rig.gen.delete(sid),
            lambda: rig.gen.restore_backup([]),
        ):
            with pytest.raises(ReportRefused) as exc:
                change()
            assert exc.value.status == 409
        seen["renamed"] = rig.gen.update(sid, {"name": "Renamed"})["name"]

    rig.hub.during = during
    rig.clock.now = MONDAY_0805
    rig.tick()
    assert seen == {"sending": True, "renamed": "Renamed"}
    view = rig.gen.view(sid)
    assert view["last_delivery"]["result"] == "sent" and not view["sending"]
    assert view["recipients"] == ["owner@example.com"]


def test_only_the_matching_claim_finalises(rig):
    sid = rig.confirmed()["id"]
    claim = {"claim_id": "aaa", "report_id": "20261116T080500Z-abcdef", "at": "x"}
    meta = {**rig.gen._meta[sid], "claim": {**claim, "recipients": []}}
    rig.gen._meta = {**rig.gen._meta, sid: meta}
    with rig.gen._state_lock:
        rig.gen._finish(
            sid, {**claim, "claim_id": "other"}, {"result": "sent", "at": "y"}
        )
    assert rig.gen._meta[sid]["claim"]["claim_id"] == "aaa"


# --- manual reports ----------------------------------------------------------------


def test_generate_now_stores_a_manual_report_and_moves_nothing(rig, contents):
    sid = rig.confirmed()["id"]
    before = rig.gen.view(sid)
    rig.clock.now = MONDAY_0805
    started = time.monotonic()
    report = rig.gen.generate_now(sid)
    assert report["trigger"] == "manual"
    assert report["delivery"]["result"] == "not_emailed"
    assert report["period"]["first"] == "2026-11-09" and report["period"]["days"] == 7
    assert contents[-1][1] <= started + 46
    after = rig.gen.view(sid)
    assert after["last_period"] == before["last_period"]
    assert after["last_run"] is None and after["rev"] == before["rev"]
    assert rig.hub.calls == []
    assert rig.gen.history(sid)[0]["trigger"] == "manual"


def test_a_delete_before_publication_recreates_nothing(rig, contents):
    sid = rig.gen.create({"name": "W"})["id"]
    contents.build.hook = lambda: rig.gen.delete(sid)
    with pytest.raises(ReportRefused) as exc:
        rig.gen.generate_now(sid)
    assert exc.value.status == 409
    assert not (rig.root / "reports" / sid).exists()


def test_report_ids_differ_under_a_frozen_clock(rig):
    sid = rig.gen.create({"name": "W"})["id"]
    ids = {rig.gen.generate_now(sid)["id"] for _ in range(5)}
    assert len(ids) == 5


def test_the_newest_twelve_are_kept_with_private_modes(rig):
    sid = rig.gen.create({"name": "W"})["id"]
    for _ in range(14):
        rig.gen.generate_now(sid)
    files = rig.reports(sid)
    assert len(files) == 12
    assert len(rig.gen.history(sid)) == 12
    for path in (
        *files,
        rig.root / "report_schedules.json",
        rig.root / "report_schedule_meta.json",
    ):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE((rig.root / "reports" / sid).stat().st_mode) == 0o700


# --- the store ---------------------------------------------------------------------


def test_an_invalid_stored_id_makes_the_store_unavailable_and_untouched(tmp_path):
    raw = json.dumps([_legacy_row(sid="not-a-uuid")])
    (tmp_path / "report_schedules.json").write_text(raw)
    rig = Rig(tmp_path, now=MONDAY_0805)
    for call in (
        rig.gen.list_views,
        lambda: rig.gen.create({"name": "W"}),
        lambda: rig.gen.upsert_card({"confirm": True}),
        rig.gen.export_backup,
    ):
        with pytest.raises(ReportRefused) as exc:
            call()
        assert exc.value.status == 503
    rig.tick()
    assert (tmp_path / "report_schedules.json").read_text() == raw
    assert not (tmp_path / "report_schedule_meta.json").exists()


@pytest.mark.parametrize(
    "tampered",
    [
        "0b6c8f8e-6f1e-4c55-9a3e-2d7c1b0e9a11/..",
        "../0b6c8f8e-6f1e-4c55-9a3e-2d7c1b0e9a1",
        "0b6c8f8e-6f1e-4c55-9a3e-2d7c1b0e9a11\x00",
        "/etc/0b6c8f8e-6f1e-4c55-9a3e-2d7c1b0e",
        "0B6C8F8E-6F1E-4C55-9A3E-2D7C1B0E9A11",
        "",
        None,
    ],
)
def test_schedule_dir_refuses_a_tampered_id(rig, tampered):
    """CodeQL py/path-injection: every request id reaches the disk through schedule_dir."""
    with pytest.raises(ValueError):
        rig.gen.schedule_dir(tampered)


def test_schedule_dir_stays_inside_the_reports_directory(rig):
    sid = "0b6c8f8e-6f1e-4c55-9a3e-2d7c1b0e9a11"
    assert rig.gen.schedule_dir(sid) == rig.root / "reports" / sid


def test_history_and_report_reads_reject_bad_ids(rig):
    sid = rig.gen.create({"name": "W"})["id"]
    rid = rig.gen.generate_now(sid)["id"]
    assert rig.gen.report(sid, rid)["id"] == rid
    for bad_sid, bad_rid in (
        ("../reports", rid),
        (sid, "../../report_schedules"),
        (sid, rid + ".json"),
        (sid.upper(), rid),
    ):
        with pytest.raises(ReportRefused) as exc:
            rig.gen.report(bad_sid, bad_rid)
        assert exc.value.status == 404
    with pytest.raises(ReportRefused):
        rig.gen.history("../..")
