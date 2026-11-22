"""The weekly report as plain text (NET-340, plan §3.5)."""

import copy
import unicodedata

import pytest

from services.report_text import NETWORK_TEXT_MAX, POSTURE_LINE, clean, render_email

GB = 10**9


def _report(**sections) -> dict:
    base = {
        "id": "20261116T080012Z-a1b2c3",
        "schedule_id": "1b4e28ba-2fa1-41d2-883f-0016d3cca427",
        "schedule_name": "Weekly report",
        "trigger": "scheduled",
        "frequency": "weekly",
        "period": {
            "first": "2026-11-09",
            "last": "2026-11-15",
            "start": "2026-11-09T00:00:00Z",
            "end": "2026-11-16T00:00:00Z",
            "tz": "Europe/London",
            "days": 7,
        },
        "generated_at": "2026-11-16T08:00:12Z",
        "duration_s": 3.2,
        "delivery": {"result": "pending"},
        "sections": {
            "traffic": {
                "status": "ok",
                "coverage": "7 of 7 days counted",
                "note": None,
                "download": 300 * GB,
                "upload": 100 * GB,
                "total": 400 * GB,
                "local": 0,
                "counted_total": 400 * GB,
                "provisional": False,
                "days_covered": 7,
                "days_total": 7,
                "busiest": {"date": "2026-11-12", "total": 80 * GB},
                "days": [],
            },
            "alerts": {
                "status": "partial",
                "coverage": "6 of 7 days fully stored",
                "note": "Some days are only partly stored, or not stored at all.",
                "total": 1234,
                "by_severity": {"1": 10, "2": 200, "3": 1000, "other": 24},
                "days": [
                    {"date": "2026-11-09", "count": 1200, "stored": "full"},
                    {"date": "2026-11-10", "count": 0, "stored": "full"},
                    {"date": "2026-11-11", "count": 34, "stored": "partial"},
                    {"date": "2026-11-12", "count": 0, "stored": "absent"},
                ],
                "worst": [
                    {
                        "rule": "ET MALWARE Thing CnC",
                        "severity": 1,
                        "count": 12,
                        "family": "malware",
                        "what": "Matches malware traffic.",
                        "risk": "The device may be infected.",
                        "todo": "Check the device.",
                    }
                ],
                "worst_note": None,
            },
            "new_devices": {
                "status": "ok",
                "coverage": "First sightings recorded between 9 Nov 00:00 and 16 Nov 00:00",
                "note": None,
                "count": 2,
                "listed": [
                    {
                        "mac": "AA:BB:CC:00:00:01",
                        "name": "Kitchen tablet",
                        "vendor": "Acme",
                        "ip": "10.0.0.5",
                        "first_seen": "2026-11-12T09:12:00Z",
                    },
                    {
                        "mac": "AA:BB:CC:00:00:02",
                        "name": None,
                        "vendor": None,
                        "ip": None,
                        "first_seen": "2026-11-13T10:00:00Z",
                    },
                ],
                "examined_from": "2026-10-01T00:00:00Z",
                "truncated": False,
            },
            "offline": {
                "status": "ok",
                "coverage": "Watched devices only",
                "note": None,
                "incidents": [
                    {
                        "mac": "AA:BB:CC:00:00:09",
                        "name": "Printer",
                        "from": "2026-11-14T09:12:00Z",
                        "to": "2026-11-14T10:30:00Z",
                        "minutes": 78,
                        "state": "returned",
                        "detail": None,
                    },
                    {
                        "mac": "AA:BB:CC:00:00:0A",
                        "name": None,
                        "from": "2026-11-15T08:00:00Z",
                        "to": None,
                        "minutes": None,
                        "state": "return_unrecorded",
                        "detail": "Return time not recorded",
                    },
                ],
                "watched_now": 3,
            },
            "data_cap": {
                "status": "ok",
                "coverage": "15 of 15 days this month counted under the current rules",
                "note": None,
                "cap_bytes": 1000 * GB,
                "month": "2026-11",
                "used_counted": 412_345_000_000,
                "used_provisional": 412_345_000_000,
                "percent": 41.2,
                "days_counted": 15,
                "days_so_far": 15,
                "crossings": [
                    {
                        "month": "2026-11",
                        "threshold": 80,
                        "cap": 1000 * GB,
                        "at": "2026-11-14T10:00:00Z",
                    }
                ],
            },
        },
    }
    for name, section in sections.items():
        base["sections"][name] = section
    return base


@pytest.mark.parametrize(
    ("first", "last", "frequency", "subject"),
    [
        (
            "2026-11-10",
            "2026-11-16",
            "weekly",
            "NetTap weekly report: 10–16 November 2026",
        ),
        (
            "2026-10-26",
            "2026-11-01",
            "weekly",
            "NetTap weekly report: 26 October – 1 November 2026",
        ),
        (
            "2026-12-28",
            "2027-01-03",
            "weekly",
            "NetTap weekly report: 28 December 2026 – 3 January 2027",
        ),
        ("2026-11-16", "2026-11-16", "daily", "NetTap daily report: 16 November 2026"),
        (
            "2026-10-01",
            "2026-10-31",
            "monthly",
            "NetTap monthly report: 1–31 October 2026",
        ),
    ],
)
def test_the_subject_is_built_from_the_dates_only(first, last, frequency, subject):
    report = _report()
    report["period"] = {**report["period"], "first": first, "last": last}
    report["frequency"] = frequency
    assert render_email(report)[0] == subject


def test_the_body_reads_every_section_and_links_to_security_posture():
    subject, text = render_email(_report())
    assert subject == "NetTap weekly report: 9–15 November 2026"
    for line in (
        "9–15 November 2026, times in Europe/London",
        "Total: 400.0 GB (download 300.0 GB, upload 100.0 GB).",
        "Busiest day: Thu 12 Nov, 80.0 GB.",
        "1,234 alerts: 10 high, 200 medium, 1,000 low, 24 other.",
        "  1. ET MALWARE Thing CnC (high, 12 alerts)",
        "     What to do: Check the device.",
        "2 devices seen for the first time.",
        "  - Kitchen tablet (AA:BB:CC:00:00:01), Acme, 10.0.0.5, first seen 12 Nov 09:12",
        "  - AA:BB:CC:00:00:02, first seen 13 Nov 10:00",
        "  - Printer (AA:BB:CC:00:00:09): offline 14 Nov 09:12 to 14 Nov 10:30 (78 minutes).",
        "  - AA:BB:CC:00:00:0A: offline from 15 Nov 08:00. Return time not recorded.",
        "Watched now: 3.",
        "41.2% of your current cap of 1,000 GB used in November up to 15 November, at least "
        "412.3 GB counted under the current rules.",
        "Passed 80% of 1,000 GB on 14 Nov.",
        "Coverage: Watched devices only.",
        "Note: Some days are only partly stored, or not stored at all.",
        POSTURE_LINE,
    ):
        assert line in text.splitlines(), line


def test_each_day_says_what_a_zero_means():
    lines = render_email(_report())[1].splitlines()
    assert (
        "  Tue 10 Nov       0  No alerts recorded: a quiet day, or Suricata wasn't running"
        in lines
    )
    assert "  Wed 11 Nov      34  Only part of this day is stored" in lines
    assert "  Thu 12 Nov       –  Not stored" in lines
    assert "  Mon 9 Nov    1,200" in lines


def test_network_text_loses_line_breaks_and_control_characters_and_is_clipped():
    evil = "TV\r\nBcc: victim@example.net\x00‮" + "x" * 200
    report = _report()
    report["sections"]["new_devices"]["listed"][0]["name"] = evil
    report["sections"]["alerts"]["worst"][0]["rule"] = "ET\nSPOOF"
    text = render_email(report)[1]
    assert "\r" not in text and "\x00" not in text and "‮" not in text
    line = next(ln for ln in text.splitlines() if ln.startswith("  - TVBcc:"))
    assert "victim@example.net" in line  # kept as text on the same line, never a header
    assert "  1. ETSPOOF (high, 12 alerts)" in text.splitlines()
    assert len(clean(evil)) == NETWORK_TEXT_MAX and clean(evil).endswith("…")


def test_unavailable_and_missing_sections_say_so():
    report = _report(
        alerts={
            "status": "unavailable",
            "coverage": "Not available this time",
            "note": "It ran out of time.",
        }
    )
    del report["sections"]["offline"]
    lines = render_email(report)[1].splitlines()
    assert (
        lines[lines.index("Alerts") + 2]
        == "Not available this time. It ran out of time."
    )
    assert lines[lines.index("Offline incidents") + 2] == "Not available this time."


def test_a_provisional_week_shows_the_at_least_figure_floored():
    traffic = copy.deepcopy(_report()["sections"]["traffic"])
    traffic.update(
        provisional=True,
        counted_total=399_990_000_000,
        busiest=None,
        status="partial",
        note="Not every day is fully counted, so the total is provisional.",
    )
    lines = render_email(_report(traffic=traffic))[1].splitlines()
    assert "Total: 400.0 GB (download 300.0 GB, upload 100.0 GB), provisional." in lines
    assert "Counted under the current rules: at least 399.9 GB." in lines  # not 400.0
    assert "No usage was counted for this week." in lines


def test_no_cap_and_no_warnings_reads_no_data_cap_set():
    cap = {
        **_report()["sections"]["data_cap"],
        "cap_bytes": None,
        "percent": None,
        "crossings": [],
    }
    assert "No data cap set." in render_email(_report(data_cap=cap))[1].splitlines()


def test_a_ranking_left_out_says_why():
    alerts = {
        **_report()["sections"]["alerts"],
        "worst": None,
        "worst_note": "Not included this time. It ran out of time.",
    }
    lines = render_email(_report(alerts=alerts))[1].splitlines()
    assert "Worst rules: Not included this time. It ran out of time." in lines


def test_a_truncated_journal_reads_at_least_and_extra_devices_are_counted():
    devices = {**_report()["sections"]["new_devices"], "count": 60, "truncated": True}
    lines = render_email(_report(new_devices=devices))[1].splitlines()
    assert "At least 60 devices seen for the first time." in lines
    assert "  and 58 more: see Devices in NetTap." in lines


def test_the_text_has_no_emoji():
    _subject, text = render_email(_report())
    assert not any(unicodedata.category(ch) == "So" for ch in text)
