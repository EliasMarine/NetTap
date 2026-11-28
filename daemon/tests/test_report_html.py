"""The weekly report as a branded HTML email (NET-381)."""

import copy
import unicodedata
from html.parser import HTMLParser

from services.report_html import ACCENT, render_html
from services.rule_explainer import explain_name
from tests.test_report_text import _report

GB = 10**9
CID = "1.2.3@nettap.local"
SHAPES = {"▲", "■", "●", "○"}


class _Page(HTMLParser):
    """The page's text (entities decoded) and every tag with its attributes."""

    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.tags: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def _page(html: str) -> _Page:
    page = _Page()
    page.feed(html)
    return page


def _text(html: str) -> str:
    return " ".join(" ".join(_page(html).text).split())


def owner_week() -> dict:
    """The owner's 20–26 Nov 2026 report, as received in plain text (the preview fixture)."""
    rules = [
        ("IPFire DBL [Phishing] Blocked DNS Query", 221),
        ("IPFire DBL [Malware] Blocked TLS Connection", 201),
        ("IPFire DBL [Malware] Blocked DNS Query", 75),
        ("IPFire DBL [Malware] Blocked HTTP Request", 40),
        ("ET EXPLOIT GraphQL Introspection Query Attempt", 15),
    ]
    days = [1105, 499, 407, 529, 609, 502, 278]
    report = _report(
        traffic={
            "status": "ok",
            "coverage": "7 of 7 days counted",
            "note": None,
            "download": 369_700_000_000,
            "upload": 1_045_100_000_000,
            "total": 1_414_800_000_000,
            "local": 173_100_000_000,
            "counted_total": 1_414_800_000_000,
            "provisional": False,
            "busiest": {"date": "2026-11-20", "total": 723_100_000_000},
            "days": [],
        },
        alerts={
            "status": "ok",
            "coverage": "7 of 7 days fully stored",
            "note": None,
            "total": 3929,
            "by_severity": {"1": 629, "2": 1925, "3": 1375, "other": 0},
            "days": [
                {"date": f"2026-11-{20 + i}", "count": n, "stored": "full"}
                for i, n in enumerate(days)
            ],
            "worst": [
                {"rule": r, "severity": 1, "count": n, **explain_name(r, 1)}
                for r, n in rules
            ],
            "worst_note": None,
        },
        new_devices={
            "status": "ok",
            "coverage": "First sightings recorded between 20 Nov 00:00 and 27 Nov 00:00. "
            "Devices seen only while NetTap was offline aren't listed",
            "note": None,
            "count": 4,
            "listed": [
                {
                    "mac": "BC:24:11:B3:FF:20",
                    "name": None,
                    "vendor": "Proxmox Server Solutions GmbH",
                    "ip": "10.60.0.24",
                    "first_seen": "2026-11-21T17:26:00Z",
                },
                {
                    "mac": "BC:24:11:23:71:64",
                    "name": None,
                    "vendor": "Proxmox Server Solutions GmbH",
                    "ip": "192.168.1.25",
                    "first_seen": "2026-11-21T22:07:00Z",
                },
                {
                    "mac": "2C:4D:79:55:6C:B8",
                    "name": None,
                    "vendor": "Weifang Goertek Electronics Co.,Ltd",
                    "ip": "192.168.1.150",
                    "first_seen": "2026-11-22T20:00:00Z",
                },
                {
                    "mac": "68:55:D4:D8:C6:55",
                    "name": "EPSOND8C655",
                    "vendor": "Seiko Epson Corporation",
                    "ip": "10.10.0.59",
                    "first_seen": "2026-11-24T18:12:00Z",
                },
            ],
            "examined_from": "2026-10-01T00:00:00Z",
            "truncated": False,
        },
        offline={
            "status": "ok",
            "coverage": "Watched devices only",
            "note": None,
            "incidents": [],
            "watched_now": 0,
        },
        data_cap={
            "status": "partial",
            "coverage": "8 of 26 days this month counted under the current rules",
            "note": "Not every day this month is counted under the current rules, so usage "
            "is at least this much.",
            "cap_bytes": None,
            "month": "2026-11",
            "used_counted": 0,
            "used_provisional": 0,
            "percent": None,
            "days_counted": 8,
            "days_so_far": 26,
            "crossings": [
                {"month": "2026-11", "threshold": t, "cap": 1_200_000_000, "at": at}
                for t, at in (
                    (80, "2026-11-20T15:00:00Z"),
                    (100, "2026-11-20T21:00:00Z"),
                )
            ],
        },
    )
    report["period"] = {
        **report["period"],
        "first": "2026-11-20",
        "last": "2026-11-26",
        "tz": "America/Los_Angeles",
    }
    return report


def test_every_figure_and_line_of_the_fixture_is_in_the_page():
    text = _text(render_html(_report(), CID))
    for part in (
        "Weekly report",
        "9–15 November 2026 · times in Europe/London",
        "Total: 400.0 GB (download 300.0 GB, upload 100.0 GB).",
        "Busiest day: Thu 12 Nov, 80.0 GB.",
        "1,234 alerts",
        "10 high",
        "200 medium",
        "1,000 low",
        "24 other",
        "Mon 9 Nov 1,200",
        "Wed 11 Nov 34 Only part of this day is stored",
        "1. ET MALWARE Thing CnC",
        "12 alerts",
        "Matches malware traffic.",
        "What to do Check the device.",
        "2 devices seen for the first time.",
        "Kitchen tablet Acme AA:BB:CC:00:00:01 10.0.0.5 First seen 12 Nov 09:12",
        "AA:BB:CC:00:00:02 First seen 13 Nov 10:00",
        "Printer (AA:BB:CC:00:00:09): offline 14 Nov 09:12 to 14 Nov 10:30 (78 minutes).",
        "Watched now: 3.",
        "41.2% of your current cap of 1,000 GB used in November up to 15 November",
        "Passed 80% of 1,000 GB on 14 Nov.",
        "Coverage: 6 of 7 days fully stored. Note: Some days are only partly stored, "
        "or not stored at all.",
        "Coverage: Watched devices only.",
        "Security posture: open NetTap",
        "on a report schedule in Settings › Notifications",
    ):
        assert part in text, part


def test_the_kpis_lead_with_the_big_numbers():
    text = _text(render_html(owner_week(), CID))
    assert (
        "Internet use 1,414.8 GB This week Alerts 3,929 ▲ 629 high "
        "New devices 4 Seen for the first time Offline incidents 0 0 watched now"
    ) in text


def test_network_text_and_explanations_are_escaped_never_markup():
    hostile_rule = 'IPFire DBL [<img src=x onerror=alert(1)>] Blocked DNS Query"&'
    report = _report()
    report["sections"]["new_devices"]["listed"][0]["name"] = (
        '<script>alert(1)</script>"&'
    )
    report["sections"]["new_devices"]["listed"][0]["vendor"] = "<b>Acme</b>"
    report["sections"]["alerts"]["worst"] = [
        {
            "rule": hostile_rule,
            "severity": 1,
            "count": 3,
            **explain_name(hostile_rule, 1),
        }
    ]
    html = render_html(report, CID)
    page = _page(html)
    assert {tag for tag, _ in page.tags}.isdisjoint(
        {"script", "b", "a", "link", "style"}
    )
    assert [a["src"] for tag, a in page.tags if tag == "img"] == [f"cid:{CID}"]
    assert not any(k.startswith("on") for _, a in page.tags for k in a)
    text = " ".join(page.text)
    assert '<script>alert(1)</script>"&' in text and "<b>Acme</b>" in text
    assert "<img src=x onerror=alert(1)>" in text  # in the rule name, as text


def test_no_remote_resources_and_no_logo_without_a_cid():
    html = render_html(_report(), None)
    assert "cid:" not in html and "<img" not in html
    assert "http://" not in html and "https://" not in html
    assert "NetTap" in _text(html)  # the wordmark still reads


def test_unavailable_and_missing_sections_say_so():
    report = _report(
        alerts={"status": "unavailable", "coverage": "x", "note": "It ran out of time."}
    )
    del report["sections"]["offline"]
    text = _text(render_html(report, CID))
    assert "Alerts Not available this time. It ran out of time." in text
    assert "Offline incidents Not available this time." in text
    assert "Alerts – Not available" in text  # its KPI tile


def test_each_explanation_paragraph_appears_once():
    text = _text(render_html(owner_week(), CID))
    todo = explain_name("IPFire DBL [Malware] Blocked DNS Query", 1)["todo"]
    malware = explain_name("IPFire DBL [Malware] Blocked DNS Query", 1)["what"]
    assert text.count(todo) == 1 and text.count(malware) == 1
    assert (
        "3. IPFire DBL [Malware] Blocked DNS Query ▲ high 75 alerts Same as rule 2."
        in text
    )
    assert "What to do Same as rule 1." in text


def test_the_only_symbols_are_the_severity_shapes():
    html = render_html(owner_week(), CID)
    assert {ch for ch in html if unicodedata.category(ch) == "So"} <= SHAPES


def test_a_quiet_week_has_no_bars_and_tells_a_zero_from_a_gap():
    alerts = {
        **_report()["sections"]["alerts"],
        "total": 0,
        "by_severity": {"1": 0, "2": 0, "3": 0, "other": 0},
        "days": [
            {"date": "2026-11-09", "count": 0, "stored": "full"},
            {"date": "2026-11-10", "count": 0, "stored": "absent"},
        ],
        "worst": [],
    }
    html = render_html(_report(alerts=alerts), CID)
    text = _text(html)
    assert (
        "Mon 9 Nov 0 No alerts recorded: a quiet day, or Suricata wasn't running"
        in text
    )
    assert "Tue 10 Nov – Not stored" in text
    assert f'bgcolor="{ACCENT}"' not in html


def test_device_counts_say_more_and_at_least_on_their_own_conditions():
    base = _report()["sections"]["new_devices"]
    one = base["listed"][1]
    complete = {**base, "count": 51, "listed": [one] * 50, "truncated": False}
    text = _text(render_html(_report(new_devices=complete), CID))
    assert "51 devices seen for the first time." in text
    assert "and 1 more: see Devices in NetTap." in text
    cut = {**base, "count": 2, "truncated": True}
    text = _text(render_html(_report(new_devices=cut), CID))
    assert "At least 2 devices seen for the first time." in text
    assert "New devices At least 2" in text and "and 1 more" not in text


def test_a_provisional_week_says_so_on_its_tile():
    traffic = copy.deepcopy(_report()["sections"]["traffic"])
    traffic["provisional"] = True
    text = _text(render_html(_report(traffic=traffic), CID))
    assert "Internet use 400.0 GB Provisional total" in text


def test_a_monthly_report_is_headed_monthly():
    report = _report()
    report["frequency"] = "monthly"
    html = render_html(report, CID)
    assert "<title>NetTap monthly report</title>" in html
    assert "Monthly report" in _text(html)
