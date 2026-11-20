"""Quiet hours' validation and window (NET-330, plans/2026-11-20-f8-quiet-hours.md §4.1)."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from services import quiet_hours as qh

UTC = timezone.utc
ON = {"enabled": True, "start": "22:00", "end": "07:00", "critical_through": True}


def utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


# --- validation ------------------------------------------------------------


def test_the_default_is_valid_and_off():
    assert qh.problem(qh.DEFAULT) is None
    assert qh.DEFAULT["enabled"] is False
    assert qh.DEFAULT["critical_through"] is True


@pytest.mark.parametrize(
    "change",
    [
        {"enabled": "yes"},
        {"critical_through": 1},
        {"start": "24:00"},
        {"start": "29:00"},
        {"start": "7:00"},
        {"end": "07:60"},
        {"end": "07:00\n"},
        {"start": "0٠:0٠"},  # Arabic-Indic digits: \d would take them
        {"start": 2200},
        {"start": "07:00"},  # equal to the end
        {"extra": True},
        {"tz": 5},
    ],
)
def test_a_bad_setting_has_a_reason(change):
    assert qh.problem({**ON, **change})


def test_a_missing_key_has_a_reason():
    assert qh.problem({k: v for k, v in ON.items() if k != "end"})
    assert qh.problem(None)
    assert qh.problem([])


def test_a_backup_s_tz_is_allowed_and_stripped():
    raw = {**ON, "tz": "Europe/London"}
    assert qh.problem(raw) is None
    assert qh.of(raw) == ON


def test_of_falls_back_to_the_default():
    assert qh.of({**ON, "start": "24:00"}) == qh.DEFAULT
    assert qh.of(None) == qh.DEFAULT
    assert qh.of(ON) == ON
    assert qh.of(ON) is not ON


# --- the window ------------------------------------------------------------


def test_off_never_holds():
    assert qh.hold(utc(2026, 11, 20, 23), {**ON, "enabled": False}, "UTC") is None


@pytest.mark.parametrize(
    ("now", "end"),
    [
        (utc(2026, 11, 20, 22, 0), utc(2026, 11, 21, 7, 0)),
        (utc(2026, 11, 20, 23, 30), utc(2026, 11, 21, 7, 0)),
        (utc(2026, 11, 21, 1, 0), utc(2026, 11, 21, 7, 0)),
        (utc(2026, 11, 21, 6, 59, 59), utc(2026, 11, 21, 7, 0)),
    ],
)
def test_across_midnight_the_window_holds_until_the_right_morning(now, end):
    assert qh.hold(now, ON, "UTC") == qh.Hold(end, True)


@pytest.mark.parametrize(
    "now",
    [utc(2026, 11, 21, 7, 0), utc(2026, 11, 21, 12, 0), utc(2026, 11, 20, 21, 59)],
)
def test_outside_the_window_nothing_holds(now):
    assert qh.hold(now, ON, "UTC") is None


def test_a_same_day_window():
    quiet = {**ON, "start": "13:00", "end": "15:00", "critical_through": False}
    assert qh.hold(utc(2026, 11, 20, 14), quiet, "UTC") == qh.Hold(
        utc(2026, 11, 20, 15), False
    )
    assert qh.hold(utc(2026, 11, 20, 15), quiet, "UTC") is None
    assert qh.hold(utc(2026, 11, 20, 12, 59), quiet, "UTC") is None


def test_the_window_is_in_the_owner_s_zone():
    # 23:00 in New York (EST, UTC-5) is 04:00 UTC
    assert qh.hold(utc(2026, 11, 21, 4), ON, "America/New_York") == qh.Hold(
        utc(2026, 11, 21, 12), True
    )
    assert qh.hold(utc(2026, 11, 20, 23), ON, "America/New_York") is None


# --- clock changes -----------------------------------------------------------


def _length(zone: str, night_utc: datetime) -> timedelta:
    found = qh.hold(night_utc, ON, zone)
    assert found is not None
    start = night_utc
    while qh.hold(start - timedelta(minutes=1), ON, zone) is not None:
        start -= timedelta(minutes=1)
    return found.end - start


@pytest.mark.parametrize(
    ("zone", "night", "hours"),
    [
        # New York: clocks go forward on 8 Mar 2026 and back on 1 Nov 2026
        ("America/New_York", utc(2026, 3, 8, 8), 8),
        ("America/New_York", utc(2026, 11, 1, 8), 10),
        # London: forward on 29 Mar 2026, back on 25 Oct 2026
        ("Europe/London", utc(2026, 3, 29, 2), 8),
        ("Europe/London", utc(2026, 10, 25, 2), 10),
        ("Europe/London", utc(2026, 11, 20, 23), 9),
    ],
)
def test_a_window_over_a_clock_change_is_an_hour_shorter_or_longer(zone, night, hours):
    assert _length(zone, night) == timedelta(hours=hours)


def test_an_end_in_the_skipped_hour_lands_an_hour_later():
    # 02:30 doesn't exist in New York on 8 Mar 2026; fold=0 makes it 03:30 EDT (07:30 UTC)
    quiet = {**ON, "end": "02:30"}
    assert qh.hold(utc(2026, 3, 8, 7, 29), quiet, "America/New_York") == qh.Hold(
        utc(2026, 3, 8, 7, 30), True
    )
    assert qh.hold(utc(2026, 3, 8, 7, 30), quiet, "America/New_York") is None


def test_an_end_on_the_repeated_hour_closes_after_its_first_occurrence():
    # 01:30 happens twice in New York on 1 Nov 2026: 05:30 UTC (EDT) and 06:30 UTC (EST)
    quiet = {**ON, "end": "01:30"}
    assert qh.hold(utc(2026, 11, 1, 5, 29), quiet, "America/New_York") is not None
    assert qh.hold(utc(2026, 11, 1, 5, 30), quiet, "America/New_York") is None
    # the second 01:15 (06:15 UTC) is after the end, though its wall time is earlier
    assert qh.hold(utc(2026, 11, 1, 6, 15), quiet, "America/New_York") is None


# --- source --------------------------------------------------------------


class _Hub:
    def __init__(self, quiet):
        self._quiet = quiet

    def quiet(self):
        return dict(self._quiet)


def test_source_reads_the_hub_and_the_owner_zone_at_each_call(tmp_path):
    tz_file = tmp_path / "owner-timezone.json"
    hub = _Hub(ON)
    ask = qh.source(hub, str(tz_file))
    assert ask(utc(2026, 11, 20, 23)) is not None  # no zone file: UTC
    tz_file.write_text(json.dumps({"tz": "America/New_York"}))
    assert ask(utc(2026, 11, 20, 23)) is None  # 18:00 in New York
    hub._quiet = {**ON, "enabled": False}
    assert ask(utc(2026, 11, 21, 4)) is None
