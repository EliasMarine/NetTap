"""NET-340: the weekly report's pure rules (plan §3.1, §3.2, §3.7): periods, send times, the
consent digest, what a stored schedule must look like, and the backup check."""

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.report_generator import ReportGenerator  # noqa: E402
from services.report_schedule import (  # noqa: E402
    ReportSchedule,
    _schedule_from,
    backup_problems,
    consent_digest,
    latest_boundary,
    next_send,
    period_for,
    send_instant,
)

UTC = timezone.utc
LONDON = ZoneInfo("Europe/London")
SID = "0b6c8f8e-6f1e-4c55-9a3e-2d7c1b0e9a11"


def _at(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


# --- periods ---------------------------------------------------------------------


def test_a_weekly_period_is_the_seven_days_before_the_send_day():
    p = period_for("weekly", date(2026, 11, 16), "UTC")  # a Monday
    assert (p.first, p.last) == (date(2026, 11, 9), date(2026, 11, 15))
    assert (p.start, p.end) == (_at(2026, 11, 9), _at(2026, 11, 16))


def test_a_daily_period_is_the_day_before():
    p = period_for("daily", date(2026, 11, 21), "UTC")
    assert (p.first, p.last) == (date(2026, 11, 20), date(2026, 11, 20))


def test_a_monthly_period_is_the_previous_calendar_month_across_a_year():
    p = period_for("monthly", date(2026, 1, 1), "UTC")
    assert (p.first, p.last) == (date(2025, 12, 1), date(2025, 12, 31))


def test_a_london_week_with_the_spring_change_has_167_hours():
    p = period_for("weekly", date(2026, 3, 30), "Europe/London")
    assert (p.first, p.last) == (date(2026, 3, 23), date(2026, 3, 29))
    assert p.end - p.start == timedelta(hours=7 * 24 - 1)
    assert p.end == _at(2026, 3, 29, 23)  # midnight BST


def test_a_london_week_with_the_autumn_change_has_169_hours():
    p = period_for("weekly", date(2026, 10, 26), "Europe/London")
    assert p.end - p.start == timedelta(hours=7 * 24 + 1)
    assert p.start == _at(2026, 10, 18, 23)  # midnight BST


def test_a_send_hour_skipped_by_the_spring_change_sends_at_the_change():
    # 01:00 doesn't exist in London on 29 March; the first valid instant after it is 02:00 BST
    assert send_instant(date(2026, 3, 29), 1, LONDON) == _at(2026, 3, 29, 1)
    assert _at(2026, 3, 29, 1).astimezone(LONDON).hour == 2


def test_a_repeated_hour_uses_its_first_occurrence():
    assert send_instant(date(2026, 10, 25), 1, LONDON) == _at(
        2026, 10, 25, 0
    )  # 01:00 BST


def test_the_latest_boundary_waits_for_the_send_hour():
    before = _at(2026, 11, 16, 7, 59)
    after = _at(2026, 11, 16, 8)
    assert latest_boundary("weekly", 0, 8, UTC, before) == date(2026, 11, 9)
    assert latest_boundary("weekly", 0, 8, UTC, after) == date(2026, 11, 16)
    assert latest_boundary("monthly", 0, 8, UTC, after) == date(2026, 11, 1)
    assert latest_boundary("daily", 0, 8, UTC, before) == date(2026, 11, 15)


def test_the_latest_boundary_is_in_the_ledger_zone():
    # 07:30 UTC on Monday 30 March is 08:30 BST: London's Monday send has happened
    when = _at(2026, 3, 30, 7, 30)
    assert latest_boundary("weekly", 0, 8, LONDON, when) == date(2026, 3, 30)
    assert latest_boundary("weekly", 0, 8, UTC, when) == date(2026, 3, 23)


def test_next_send_is_strictly_after_now():
    assert next_send("weekly", 0, 8, UTC, _at(2026, 11, 16, 8)) == _at(2026, 11, 23, 8)
    assert next_send("monthly", 0, 8, UTC, _at(2026, 11, 16)) == _at(2026, 12, 1, 8)


# --- consent ---------------------------------------------------------------------


def _schedule(**over) -> ReportSchedule:
    base = dict(
        id=SID,
        name="Weekly report",
        frequency="weekly",
        format="json",
        recipients=["Owner@example.com", "b@example.com"],
        sections=["traffic_summary", "alerts", "devices"],
    )
    return ReportSchedule(**{**base, **over})


def test_the_digest_ignores_recipient_order_but_not_case():
    meta = {"weekday": 0, "hour": 8}
    digest = consent_digest(_schedule(), meta)
    reordered = _schedule(recipients=["b@example.com", "Owner@example.com"])
    assert consent_digest(reordered, meta) == digest
    recased = _schedule(recipients=["owner@example.com", "b@example.com"])
    assert consent_digest(recased, meta) != digest


@pytest.mark.parametrize(
    "change",
    [
        {"sections": ["traffic_summary"]},
        {"frequency": "daily"},
        {"enabled": False},
    ],
)
def test_the_digest_binds_sections_cadence_and_on_off(change):
    meta = {"weekday": 0, "hour": 8}
    assert consent_digest(_schedule(**change), meta) != consent_digest(
        _schedule(), meta
    )


def test_the_digest_binds_weekday_and_hour():
    s = _schedule()
    assert consent_digest(s, {"weekday": 0, "hour": 8}) != consent_digest(
        s, {"weekday": 1, "hour": 8}
    )
    assert consent_digest(s, {"weekday": 0, "hour": 8}) != consent_digest(
        s, {"weekday": 0, "hour": 9}
    )


# --- stored schedules ----------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "abc"},
        {"id": SID.upper()},
        {"frequency": "hourly"},
        {"enabled": "yes"},
        {"recipients": "a@example.com"},
        {"recipients": [1]},
        {"last_run": 5},
    ],
)
def test_a_stored_schedule_with_a_bad_id_or_type_is_refused(bad):
    with pytest.raises((ValueError, TypeError)):
        _schedule_from({**asdict(_schedule()), **bad})


def test_unknown_stored_fields_are_dropped():
    assert _schedule_from({**asdict(_schedule()), "colour": "red"}) == _schedule()


# A copy of the loader before NET-340 (report_generator.py at main 940179a8), to prove an older
# daemon still reads the file the new code writes
@dataclass
class _OldSchedule:
    id: str
    name: str
    frequency: str
    format: str
    recipients: list[str] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    enabled: bool = True
    last_run: str | None = None
    next_run: str | None = None
    created_at: str = ""


def _old_load(path: str) -> dict:
    schedules = {}
    with open(path) as f:
        raw = json.load(f)
    for data in raw:
        sched = _OldSchedule(**data)
        schedules[sched.id] = sched
    return schedules


def test_the_old_loader_reads_a_file_the_new_code_wrote(tmp_path):
    gen = ReportGenerator(
        reports_dir=str(tmp_path / "reports"),
        schedules_file=str(tmp_path / "report_schedules.json"),
    )
    view = gen.create(
        {
            "name": "Weekly report",
            "recipients": ["a@example.com"],
            "weekday": 2,
            "hour": 18,
            "confirm": True,
        }
    )
    gen.update(view["id"], {"name": "Renamed"})
    old = _old_load(str(tmp_path / "report_schedules.json"))
    assert old[view["id"]].name == "Renamed"
    assert old[view["id"]].sections == ["traffic_summary", "alerts", "devices"]
    assert old[view["id"]].format == "json"


# --- backups -------------------------------------------------------------------


def _entry(**over) -> dict:
    return {
        **{
            k: v
            for k, v in asdict(_schedule()).items()
            if k not in ("last_run", "next_run")
        },
        "weekday": 0,
        "hour": 8,
        "card": True,
        **over,
    }


def test_a_good_backup_section_has_no_problems():
    assert backup_problems([_entry()]) == []


@pytest.mark.parametrize(
    "items",
    [
        {"not": "a list"},
        [_entry(id="nope")],
        [_entry(recipients=["a@example.com\r\nBcc: x@example.com"])],
        [_entry(recipients=["a@example.com,b@example.com"])],
        [_entry(recipients=[f"r{i}@example.com" for i in range(11)])],
        [_entry(weekday=7)],
        [_entry(hour=True)],
        [_entry(name="")],
        [_entry(), _entry()],
    ],
)
def test_a_bad_backup_section_is_refused_before_anything_applies(items):
    problems = backup_problems(items)
    assert problems and all(
        p.startswith("Report schedules not restored: ") for p in problems
    )


def test_a_stored_claim_missing_its_time_makes_the_store_unavailable(tmp_path):
    """Recovery reads claim["at"]; a claim without it must never reach recovery."""
    sid = "0b6c8f8e-6f1e-4c55-9a3e-2d7c1b0e9a11"
    (tmp_path / "report_schedules.json").write_text(
        json.dumps([{**asdict(_schedule()), "id": sid}])
    )
    claim = {"claim_id": "c", "report_id": "20261116T080500Z-abcdef", "recipients": []}
    (tmp_path / "report_schedule_meta.json").write_text(
        json.dumps({sid: {"claim": claim}})
    )
    gen = ReportGenerator(
        reports_dir=str(tmp_path / "reports"),
        schedules_file=str(tmp_path / "report_schedules.json"),
    )
    assert gen._available is False
