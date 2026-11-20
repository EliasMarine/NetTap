"""Data cap warnings (NET-339): the job reads the ledger's month through month_reply and appends
each warning due to a real event journal, once per (month, cap, threshold)."""

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from services import owner_tz
from services.data_cap import DataCapWatch
from services.device_accounting import lan_cidrs
from services.event_journal import EventJournal
from services.notification_dispatcher import event_item
from services.usage_days import rules_hash, utc_iso
from services.usage_ledger import UsageLedger

GB = 10**9
RULES = rules_hash([], lan_cidrs(None))
NOV_18 = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)  # 17.5 days in
NOV_28 = datetime(
    2026, 11, 28, 12, 0, tzinfo=timezone.utc
)  # 27.5 days in: no projection over


def _entry(total: int, now: datetime, **extra) -> dict:
    stamp = utc_iso(now)
    return {
        "total": total,
        "download": total,
        "upload": 0,
        "local": 0,
        "rules": RULES,
        "counted_at": stamp,
        "cutoff": stamp,
        **extra,
    }


def _ledger(now: datetime, today_total: int, since: str, tz: str, extra: dict) -> dict:
    """Every day of now's local month so far counted at 0, and today at `today_total`."""
    today = now.astimezone(ZoneInfo(tz)).date()
    days = {
        date(today.year, today.month, n).isoformat(): _entry(0, now)
        for n in range(1, today.day)
    }
    return {
        "version": 1,
        "generation": 1,
        "tz": tz,
        "since": since,
        "rules": RULES,
        "updated_at": utc_iso(now),
        "sweep": {"id": 1, "cursor": None, "chunks_done": 0, "chunks_failed": 0},
        "inventory_ok": True,
        "indices": {},
        "gaps": [],
        "days": {**days, today.isoformat(): _entry(today_total, now), **extra},
    }


class World:
    def __init__(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("OWNER_TZ_FILE", str(tmp_path / "owner-timezone.json"))
        self.tmp = tmp_path
        self.ledger_path = tmp_path / "usage-ledger.json"
        self.journal = EventJournal(str(tmp_path / "events.jsonl"))
        self.now = NOV_28
        self.cap = 100 * GB
        self.tracker = SimpleNamespace(get_cap=lambda: {"monthly_cap_bytes": self.cap})

    def counted(
        self,
        total: int,
        now: datetime | None = None,
        since: str = "2026-11-01",
        tz: str = "UTC",
        extra: dict | None = None,
    ) -> None:
        self.now = now or self.now
        ledger = _ledger(self.now, total, since, tz, extra or {})
        self.ledger_path.write_text(json.dumps(ledger))

    def watch(self) -> DataCapWatch:
        ledger = UsageLedger(
            None,
            None,
            excluded_ips=lambda: [],
            lan_filter=lambda: None,
            path=str(self.ledger_path),
            now=lambda: self.now,
        )
        return DataCapWatch(self.tracker, ledger, self.journal)

    def run(self) -> list[str]:
        return self.watch().run(0.0)["sent"]

    def lines(self) -> list[dict]:
        path = self.tmp / "events.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture
def w(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def test_no_cap_or_no_ledger_sends_nothing(w):
    w.cap = 0
    w.counted(500 * GB)
    assert w.run() == []
    w.cap = 100 * GB
    w.ledger_path.unlink()  # before the ledger's first pass
    assert w.run() == []
    assert w.lines() == []


def test_80_percent_sends_once_and_79_9_nothing(w):
    w.counted(int(79.9 * GB))
    assert w.run() == []
    w.counted(80 * GB)
    assert w.run() == ["80"]
    assert w.run() == []  # the journal's id: once
    [line] = w.lines()
    assert (line["type"], line["key"]) == ("data_cap", "80")
    assert line["data"] == {
        "month": "2026-11",
        "month_label": "November",
        "used": 80 * GB,
        "cap": 100 * GB,
        "projected": int(80 * GB / (27.5 * 86400) * (30 * 86400)),
        "tz": "UTC",
        "since": "2026-11-01",
        "complete": True,
        "threshold": "80",
    }


def test_80_and_100_in_one_run(w):
    w.counted(100 * GB)
    assert w.run() == ["80", "100"]


def test_the_projection_only_from_day_3_and_only_below_the_cap(w):
    # 3 days less a minute in: 40 GB would be about 405 GB by the end
    w.counted(40 * GB, now=datetime(2026, 11, 3, 23, 59, tzinfo=timezone.utc))
    assert w.run() == []
    w.counted(40 * GB, now=datetime(2026, 11, 4, 0, 0, tzinfo=timezone.utc))
    assert w.run() == ["projected"]


def test_80_and_projected_both_stay_but_not_projected_at_the_cap(w):
    w.counted(85 * GB, now=NOV_18)  # on track for about 146 GB
    assert w.run() == ["80", "projected"]
    w.cap = 110 * GB
    w.counted(115 * GB, now=NOV_18)  # past the cap: "projected" says nothing new
    assert w.run() == ["80", "100"]


def test_never_a_projection_when_the_ledger_cant_project(w):
    # counted only since the 5th: the month has no projection
    w.counted(60 * GB, now=NOV_18, since="2026-11-05")
    assert w.run() == []


def test_a_new_cap_rearms_and_going_back_sends_nothing_again(w):
    w.counted(85 * GB)
    assert w.run() == ["80"]
    w.cap = 105 * GB  # 80% is 84 GB: a new set of warnings
    assert w.run() == ["80"]
    w.cap = 100 * GB
    assert w.run() == []
    w.cap = 105 * GB
    assert w.run() == []
    instances = [line["data"]["cap"] for line in w.lines()]
    assert instances == [100 * GB, 105 * GB]


def test_a_zone_change_mid_month_sends_nothing_again(w):
    w.counted(85 * GB)
    assert w.run() == ["80"]
    owner_tz.write("Asia/Tokyo")
    w.counted(
        85 * GB, tz="Asia/Tokyo"
    )  # the ledger moved to the new zone: still November
    assert w.run() == []


def test_a_new_month_rearms(w):
    w.counted(85 * GB)
    assert w.run() == ["80"]
    w.counted(85 * GB, now=datetime(2026, 12, 28, 12, 0, tzinfo=timezone.utc))
    assert w.run() == ["80"]
    assert [line["data"]["month"] for line in w.lines()] == ["2026-11", "2026-12"]


def test_an_incomplete_month_sends_on_what_was_counted_and_says_at_least(w):
    w.counted(85 * GB, since="2026-11-13")
    assert w.run() == ["80"]
    [line] = w.lines()
    assert line["data"]["complete"] is False
    item = event_item(line)
    assert item["line"] == (
        "85.0 GB of your 100 GB cap used in November (UTC), at least: counted since 13 Nov"
    )
    assert len(item["line"]) <= 140


def test_days_under_older_exclusions_dont_count(w):
    old = {
        # counted before the exclusions changed: not yet recounted, and lost to pruning
        "2026-11-10": _entry(40 * GB, w.now, rules="old"),
        "2026-11-11": _entry(
            40 * GB, w.now, rules="old", coverage_lost_at="2026-11-20T00:00:00Z"
        ),
    }
    w.counted(50 * GB, extra=old)
    assert w.run() == []  # 130 GB on the page, but only 50 GB under today's rules


def test_a_failed_append_is_raised_after_the_others_and_retried(w):
    w.counted(100 * GB)
    real = w.journal.append

    def failing(event_type, key, *args, **kwargs):
        if key == "80":
            raise OSError(28, "No space left")
        return real(event_type, key, *args, **kwargs)

    with patch.object(w.journal, "append", side_effect=failing):
        with pytest.raises(OSError):
            w.run()
    assert [line["key"] for line in w.lines()] == ["100"]
    assert w.run() == ["80"]  # the next run appends it; "100" isn't sent again


def test_the_last_local_minute_counts_and_after_midnight_the_month_is_over(w):
    owner_tz.write("Europe/Berlin")
    last_minute = datetime(2026, 11, 30, 22, 59, tzinfo=timezone.utc)  # 23:59 in Berlin
    w.counted(85 * GB, now=last_minute, tz="Europe/Berlin")
    assert w.run() == ["80"]
    w.journal = EventJournal(str(w.tmp / "other.jsonl"))
    w.counted(79 * GB, now=last_minute, tz="Europe/Berlin")
    assert w.run() == []
    # a recount after midnight raises November past 80%: not warned about (plan §3.5)
    after = datetime(2026, 11, 30, 23, 5, tzinfo=timezone.utc)
    w.counted(
        0,
        now=after,
        tz="Europe/Berlin",
        extra={"2026-11-30": _entry(85 * GB, after)},
    )
    assert w.run() == []


def test_now_is_the_ledgers_month_and_the_cap(w):
    w.counted(
        1,
        now=datetime(2026, 12, 1, 1, 0, tzinfo=timezone.utc),
        tz="America/Los_Angeles",
    )
    owner_tz.write("Europe/Berlin")  # pending: the ledger still counts in Los Angeles
    w.now = datetime(2026, 12, 1, 1, 0, tzinfo=timezone.utc)  # Nov 30, 17:00 there
    assert w.watch().now() == ("2026-11", 100 * GB)
    w.cap = 0
    assert w.watch().now() == ("2026-11", 0)
