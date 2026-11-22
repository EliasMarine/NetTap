"""The weekly report's sections (NET-340, plans/2026-11-21-weekly-report.md §3.4, §6)."""

import time
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from opensearchpy import ConnectionTimeout

from services import report_sections as rs
from services import usage_report
from services.event_journal import EventJournal
from services.report_sections import Period, ReportDeps, build_sections
from services.usage_days import day_bounds, utc_iso
from storage.snapshot_search import Budget
from zoneinfo import ZoneInfo

LONDON = "Europe/London"
RULES = "rules-now"
WEEK = Period.of(date(2026, 11, 9), date(2026, 11, 15), LONDON)  # GMT: local = UTC
NEXT = Period.of(date(2026, 11, 16), date(2026, 11, 22), LONDON)
GENERATED = datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc)
GB = 10**9


@pytest.fixture(autouse=True)
def _owner_zone(monkeypatch):
    monkeypatch.setattr(
        rs.owner_tz, "read", lambda: {"tz": LONDON, "set": True, "ok": True}
    )


def _far() -> float:
    return time.monotonic() + 120


def _t(day: int, hour: int = 0, minute: int = 0, month: int = 11) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=timezone.utc)


# --- fakes ---------------------------------------------------------------------------


class FakeLedger:
    def __init__(self, snapshot, now=GENERATED, rules=RULES):
        self._snapshot, self._now, self._rules = snapshot, now, rules

    def snapshot(self):
        return self._snapshot

    def now(self):
        return self._now

    def current_rules(self):
        return self._rules


def _day(total, rules=RULES, cutoff=None, d=None, tz=LONDON, **extra):
    end = day_bounds(d, ZoneInfo(tz))[1] if d else None
    return {
        "total": total,
        "download": total * 3 // 4,
        "upload": total - total * 3 // 4,
        "local": 5,
        "rules": rules,
        "cutoff": cutoff or (utc_iso(end) if end else None),
        "counted_at": utc_iso(GENERATED),
        **extra,
    }


def _snapshot(days: dict, tz=LONDON, since="2026-01-01"):
    return {
        "tz": tz,
        "since": since,
        "gaps": [],
        "days": days,
        "generation": 1,
        "updated_at": utc_iso(GENERATED),
        "sweep": {"id": 0, "cursor": None},
    }


def _week_days(totals, period=WEEK, **kw):
    out, d = {}, period.first
    for total in totals:
        out[d.isoformat()] = _day(total, d=d, **kw)
        d += timedelta(days=1)
    return out


class FakeClient:
    """Evaluates what the alerts section sends: the @timestamp range (gte/lte), date_range
    ([from, to)), the severity terms and composite paging over rule.name with a min."""

    def __init__(self, docs=(), indices=None, clock=None, cost=0.0):
        self.docs = list(docs)  # (timestamp, severity or None, rule or None)
        self.indices = indices
        self.searches = []
        self.clock, self.cost = clock, cost
        self.page_hook = None
        self.cat = MagicMock()
        self.cat.indices.side_effect = self._cat

    def _cat(self, **kw):
        if isinstance(self.indices, Exception):
            raise self.indices
        names = self.indices if self.indices is not None else []
        return [{"index": n, "uuid": f"u-{n}"} for n in names]

    def _tick(self):
        if self.clock is not None:
            self.clock.now += self.cost

    def search(self, index=None, body=None, budget=None, **kw):
        if budget is not None:
            budget.check("a search")
        self.searches.append(body)
        self._tick()
        rng = body["query"]["bool"]["filter"][0]["range"]["@timestamp"]
        low, high = _parse(rng["gte"]), _parse(rng["lte"])
        docs = [d for d in self.docs if low <= d[0] <= high]
        aggs = body["aggs"]
        if "all" in aggs:
            return self._page(docs, aggs["all"]["composite"])
        severities = {}
        for _ts, sev, _rule in docs:
            if sev is not None:
                severities[sev] = severities.get(sev, 0) + 1
        ranges = aggs["per_day"]["date_range"]["ranges"]
        return {
            "_shards": {"total": 1, "failed": 0},
            "timed_out": False,
            "hits": {"total": {"value": len(docs), "relation": "eq"}},
            "aggregations": {
                "by_severity": {
                    "buckets": [
                        {"key": k, "doc_count": v}
                        for k, v in sorted(severities.items())
                    ]
                },
                "per_day": {
                    "buckets": [
                        {
                            "key": r["key"],
                            "doc_count": sum(
                                _parse(r["from"]) <= d[0] < _parse(r["to"])
                                for d in docs
                            ),
                        }
                        for r in ranges
                    ]
                },
            },
        }

    def _page(self, docs, composite):
        groups = {}
        for _ts, sev, rule in docs:
            count, worst = groups.get(rule, (0, None))
            worst = (
                sev if worst is None else (worst if sev is None else min(worst, sev))
            )
            groups[rule] = (count + 1, worst)
        keys = sorted(
            groups, key=lambda k: (k is not None, k or "")
        )  # null first, as asc
        after = (composite.get("after") or {}).get("key", "<start>")
        if after != "<start>":
            keys = keys[keys.index(after) + 1 :]
        page = keys[: composite["size"]]
        reply = {
            "_shards": {"total": 1, "failed": 0},
            "timed_out": False,
            "aggregations": {
                "all": {
                    "buckets": [
                        {
                            "key": {"key": k},
                            "doc_count": groups[k][0],
                            "worst": {
                                "value": None
                                if groups[k][1] is None
                                else float(groups[k][1])
                            },
                        }
                        for k in page
                    ],
                    **({"after_key": {"key": page[-1]}} if page else {}),
                }
            },
        }
        return self.page_hook(reply, composite) if self.page_hook else reply


def _parse(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _alert(ts, sev=3, rule="ET INFO thing"):
    return (ts, sev, rule)


def _dated(*days: date) -> list[str]:
    return [f"arkime_sessions3-{d:%y%m%d}" for d in days]


def _all_dated(period=WEEK, before=1, after=1):
    d = period.first - timedelta(days=before)
    out = []
    while d <= period.last + timedelta(days=after):
        out.append(d)
        d += timedelta(days=1)
    return _dated(*out)


def _alerts(period, client, budget=None):
    return rs.alerts(period, client, "arkime_sessions3-*", budget or Budget(60))


def _scan(entries=(), examined_from=None, truncated=False):
    return {
        "entries": list(entries),
        "examined_from": examined_from or WEEK.start - timedelta(days=30),
        "truncated": truncated,
    }


# --- 1. internet use ------------------------------------------------------------------


def _pinned(snapshot, now=GENERATED):
    return rs._Pinned(snapshot, now, RULES, {"tz": LONDON, "set": True, "ok": True})


def test_traffic_equals_the_usage_api_for_the_same_dates():
    snap = _snapshot(_week_days([1, 2, 3, 4, 5, 6, 7]))
    section = rs.traffic(WEEK, _pinned(snap))
    api = usage_report.daily(
        snap,
        WEEK.first,
        WEEK.last,
        GENERATED,
        RULES,
        {"tz": LONDON, "set": True, "ok": True},
    )
    assert {k: section[k] for k in ("download", "upload", "local", "total")} == api[
        "bytes"
    ]
    assert section["status"] == "ok" and section["provisional"] is False
    assert section["coverage"] == "7 of 7 days counted"
    assert section["busiest"] == {"date": "2026-11-15", "total": 7}
    assert section["counted_total"] == section["total"] == 28


def test_a_cutoff_at_utc_midnight_does_not_cover_a_new_york_day():
    ny = "America/New_York"
    period = Period.of(date(2026, 11, 10), date(2026, 11, 10), ny)
    # the local day ends at 05:00 UTC on the 11th; counting stopped at UTC midnight
    snap = _snapshot({"2026-11-10": _day(9, cutoff="2026-11-11T00:00:00Z")}, tz=ny)
    section = rs.traffic(period, _pinned(snap))
    assert section["days"][0]["covered"] is False
    assert section["provisional"] is True and section["status"] == "partial"
    assert section["coverage"] == "0 of 1 day counted"


def test_an_exclusions_change_gives_a_provisional_total_and_a_lower_counted_figure():
    days = _week_days([10] * 7)
    days["2026-11-12"] = _day(50, rules="rules-before", d=date(2026, 11, 12))
    section = rs.traffic(WEEK, _pinned(_snapshot(days)))
    assert section["total"] == 110  # every row with figures, as /api/usage/daily
    assert section["counted_total"] == 60  # the current rules only: never too high
    assert section["provisional"] is True and section["days_covered"] == 6


def test_an_empty_ledger_has_no_busiest_day():
    section = rs.traffic(WEEK, _pinned(None))
    assert section["busiest"] is None and section["total"] == 0
    assert section["days_covered"] == 0 and section["status"] == "partial"


# --- 2. alerts ---------------------------------------------------------------------------


def test_alert_totals_use_the_counted_query_with_an_inclusive_end_one_ms_early():
    client = FakeClient([_alert(_t(10, 9))], indices=_all_dated())
    section = _alerts(WEEK, client)
    body = client.searches[0]
    rng = body["query"]["bool"]["filter"][0]["range"]["@timestamp"]
    assert rng == {
        "gte": "2026-11-09T00:00:00.000Z",
        "lte": "2026-11-15T23:59:59.999Z",
        "format": "strict_date_optional_time",
    }
    assert body["track_total_hits"] is True and body["size"] == 0
    assert "date_histogram" not in str(body)
    assert section["total"] == 1 and section["status"] == "ok"


def test_an_alert_at_exactly_midnight_belongs_to_the_later_period_only():
    client = FakeClient([_alert(WEEK.end)], indices=_all_dated(after=8))
    assert _alerts(WEEK, client)["total"] == 0
    later = _alerts(NEXT, client)
    assert later["total"] == 1 and later["days"][0]["count"] == 1


@pytest.mark.parametrize(
    ("first", "day", "start", "end"),
    [
        # the clocks go back: a 25-hour day
        (
            date(2026, 10, 19),
            "2026-10-25",
            "2026-10-24T23:00:00.000Z",
            "2026-10-26T00:00:00.000Z",
        ),
        # the clocks go forward: a 23-hour day
        (
            date(2026, 3, 23),
            "2026-03-29",
            "2026-03-29T00:00:00.000Z",
            "2026-03-29T23:00:00.000Z",
        ),
    ],
)
def test_each_local_day_is_one_date_range_across_both_dst_changes(
    first, day, start, end
):
    period = Period.of(first, first + timedelta(days=6), LONDON)
    client = FakeClient([], indices=[])
    _alerts(period, client)
    ranges = client.searches[0]["aggs"]["per_day"]["date_range"]["ranges"]
    assert len(ranges) == 7
    assert {"key": day, "from": start, "to": end} in ranges
    # contiguous: each day starts where the one before ended
    assert all(a["to"] == b["from"] for a, b in zip(ranges, ranges[1:]))


def test_an_alert_without_a_severity_counts_in_the_total_as_other():
    docs = [_alert(_t(10), 1), _alert(_t(10), 2), _alert(_t(11), None)]
    section = _alerts(WEEK, FakeClient(docs, indices=_all_dated()))
    assert section["total"] == 3
    assert section["by_severity"] == {"1": 1, "2": 1, "3": 0, "other": 1}


def test_one_high_alert_outranks_five_rules_of_many_medium_alerts():
    docs = [_alert(_t(10), 1, "ET HIGH once")]
    docs += [_alert(_t(10), 3, "ET HIGH once") for _ in range(100)]
    for n in range(5):
        docs += [_alert(_t(11), 2, f"ET MEDIUM {n}") for _ in range(50)]
    worst = _alerts(WEEK, FakeClient(docs, indices=_all_dated()))["worst"]
    assert [w["rule"] for w in worst][0] == "ET HIGH once"
    assert worst[0]["severity"] == 1 and worst[0]["count"] == 101
    assert len(worst) == 5 and {"family", "what", "risk", "todo"} <= worst[0].keys()


def test_an_unnamed_high_alert_appears_and_unknown_severity_sorts_last():
    docs = [
        _alert(_t(10), None, "ET NO SEVERITY"),
        _alert(_t(10), 3, "ET LOW"),
        _alert(_t(10), 1, None),
    ]
    worst = _alerts(WEEK, FakeClient(docs, indices=_all_dated()))["worst"]
    assert [(w["rule"], w["severity"]) for w in worst] == [
        ("Unnamed rule", 1),
        ("ET LOW", 3),
        ("ET NO SEVERITY", None),
    ]


def test_a_ranking_stopped_by_its_cap_is_left_out_but_the_totals_stand(monkeypatch):
    monkeypatch.setattr(rs, "RANK_PAGE", 2)
    monkeypatch.setattr(rs, "RANK_MAX", 2)
    docs = [_alert(_t(10), 2, f"ET RULE {n}") for n in range(5)]
    section = _alerts(WEEK, FakeClient(docs, indices=_all_dated()))
    assert section["worst"] is None and "more than 2 rules" in section["worst_note"]
    assert section["total"] == 5 and section["status"] == "partial"


def test_the_ranking_budget_running_out_starts_no_further_page(monkeypatch):
    monkeypatch.setattr(rs, "RANK_PAGE", 2)
    clock = Clock()
    docs = [_alert(_t(10), 2, f"ET RULE {n}") for n in range(5)]
    client = FakeClient(docs, indices=_all_dated(), clock=clock, cost=4.0)
    # totals at 4 s, then the listing (no search); the first ranking page ends at 8 s
    section = _alerts(WEEK, client, Budget(7.5, clock))
    ranking_pages = [b for b in client.searches if "all" in b["aggs"]]
    assert len(ranking_pages) == 1
    assert section["worst"] is None and "ran out of time" in section["worst_note"]
    assert section["total"] == 5


def test_a_malformed_second_ranking_page_leaves_the_ranking_out(monkeypatch):
    monkeypatch.setattr(rs, "RANK_PAGE", 2)
    client = FakeClient(
        [_alert(_t(10), 2, f"ET RULE {n}") for n in range(5)], indices=_all_dated()
    )

    def hook(reply, composite):
        if composite.get("after"):
            reply["aggregations"]["all"] = {"after_key": {"key": "x"}}  # no bucket list
        return reply

    client.page_hook = hook
    section = _alerts(WEEK, client)
    assert section["worst"] is None and section["total"] == 5


def test_a_local_day_with_one_of_its_two_utc_dates_stored_is_partial_with_its_counts():
    ny = "America/New_York"
    period = Period.of(
        date(2026, 11, 10), date(2026, 11, 10), ny
    )  # 05:00Z 10th to 05:00Z 11th
    docs = [_alert(_t(10, 12)), _alert(_t(10, 13))]
    section = _alerts(period, FakeClient(docs, indices=_dated(date(2026, 11, 10))))
    assert section["days"] == [{"date": "2026-11-10", "count": 2, "stored": "partial"}]
    assert section["status"] == "partial"


def test_a_non_utc_local_day_across_two_stored_dated_indices_is_full():
    ny = "America/New_York"
    period = Period.of(date(2026, 11, 10), date(2026, 11, 10), ny)
    indices = _dated(date(2026, 11, 10), date(2026, 11, 11))
    assert (
        _alerts(period, FakeClient([], indices=indices))["days"][0]["stored"] == "full"
    )


def test_a_missing_middle_index_reads_not_stored():
    days = [WEEK.first + timedelta(days=n) for n in range(7) if n != 3]
    section = _alerts(WEEK, FakeClient([], indices=_dated(*days)))
    stored = [d["stored"] for d in section["days"]]
    assert stored == ["full", "full", "full", "absent", "full", "full", "full"]
    assert (
        section["status"] == "partial"
        and section["coverage"] == "6 of 7 days fully stored"
    )


def test_a_quiet_week_with_every_index_is_ok_not_expired():
    section = _alerts(WEEK, FakeClient([], indices=_all_dated()))
    assert section["status"] == "ok" and section["note"] is None
    assert section["total"] == 0 and section["worst"] == []
    assert all(
        d == {"date": d["date"], "count": 0, "stored": "full"} for d in section["days"]
    )


def test_an_undated_index_covers_only_its_observed_span():
    entry = {
        "name": "arkime_sessions3-x",
        "min_ts": "2026-11-09T06:00:00Z",
        "max_ts": "2026-11-20T00:00:00Z",
    }
    spans = rs._spans({"u": entry})
    assert (
        rs._stored(*day_bounds(date(2026, 11, 9), ZoneInfo(LONDON)), spans) == "partial"
    )
    assert (
        rs._stored(*day_bounds(date(2026, 11, 10), ZoneInfo(LONDON)), spans) == "full"
    )


def test_a_failed_index_listing_makes_storage_unknown_and_keeps_the_counts():
    client = FakeClient(
        [_alert(_t(10))], indices=ConnectionTimeout("TIMEOUT", "slow", None)
    )
    section = _alerts(WEEK, client)
    assert {d["stored"] for d in section["days"]} == {"unknown"}
    assert section["total"] == 1 and section["coverage"] == "Storage coverage unknown"


# --- 3. new devices ------------------------------------------------------------------


def _registry(devices=None, error=None):
    registry = MagicMock()
    if error:
        registry.get_devices.side_effect = error
    else:
        registry.get_devices.return_value = devices or {}
    registry.get_name.side_effect = lambda d: d.get("friendly_name")
    return registry


def _new(mac, at, vendor="Acme", ip="10.0.0.5", seq=1):
    return {
        "seq": seq,
        "type": "new_device",
        "key": mac,
        "observed_at": utc_iso(at),
        "data": {"ip": ip, "vendor": vendor, "source": "dhcp"},
    }


def test_new_devices_come_from_the_journal_with_names_from_the_no_retry_client():
    client = object()
    registry = _registry({"AA:BB:CC:00:00:01": {"friendly_name": "Kitchen tablet"}})
    scan = _scan(
        [_new("AA:BB:CC:00:00:01", _t(10, 9)), _new("AA:BB:CC:00:00:02", _t(11, 9))]
    )
    section = rs.new_devices(WEEK, scan, registry, client, Budget(60))
    assert section["count"] == 2 and section["status"] == "ok"
    assert section["listed"][0] == {
        "mac": "AA:BB:CC:00:00:01",
        "name": "Kitchen tablet",
        "vendor": "Acme",
        "ip": "10.0.0.5",
        "first_seen": "2026-11-10T09:00:00Z",
    }
    assert section["listed"][1]["name"] is None
    kwargs = registry.get_devices.call_args.kwargs
    assert kwargs["fields"] == rs.NAME_FIELDS and kwargs["client"] is client
    assert 0 < kwargs["timeout"] <= rs.ENRICH_MAX_S
    assert (
        "Devices seen only while NetTap was offline aren't listed"
        in section["coverage"]
    )


def test_a_registry_retry_cannot_move_a_device_into_the_next_week(tmp_path):
    journal = EventJournal(str(tmp_path / "events.jsonl"))
    mac = "AA:BB:CC:00:00:09"
    journal.append(
        "new_device", mac, utc_iso(_t(15, 23, 50)), {"vendor": "Acme"}, instance=""
    )
    # the registry retried the same MAC after midnight: the journal already has it
    journal.append(
        "new_device", mac, utc_iso(_t(16, 0, 10)), {"vendor": "Acme"}, instance=""
    )
    registry = _registry()
    week = rs.new_devices(
        WEEK, journal.scan(WEEK.start, WEEK.end, _far()), registry, object(), Budget(60)
    )
    nxt = rs.new_devices(
        NEXT, journal.scan(NEXT.start, NEXT.end, _far()), registry, object(), Budget(60)
    )
    assert week["count"] == 1 and nxt["count"] == 0


def test_a_name_lookup_timeout_keeps_the_list_and_the_count():
    registry = _registry(error=ConnectionTimeout("TIMEOUT", "slow", None))
    scan = _scan([_new(f"AA:BB:CC:00:00:{n:02d}", _t(10, n)) for n in range(3)])
    section = rs.new_devices(WEEK, scan, registry, object(), Budget(60))
    assert (
        section["count"] == 3
        and [d["vendor"] for d in section["listed"]] == ["Acme"] * 3
    )
    assert all(d["name"] is None for d in section["listed"])
    assert section["status"] == "partial" and "couldn't be looked up" in section["note"]


def test_names_are_not_looked_up_when_the_deadline_is_near():
    registry = _registry()
    section = rs.new_devices(
        WEEK, _scan([_new("AA", _t(10))]), registry, object(), Budget(1)
    )
    registry.get_devices.assert_not_called()
    assert section["count"] == 1 and section["status"] == "partial"


def test_at_most_50_are_listed_and_the_count_is_all_of_them():
    scan = _scan(
        [_new(f"AA:{n:04d}", _t(10) + timedelta(minutes=n)) for n in range(60)]
    )
    section = rs.new_devices(WEEK, scan, _registry(), object(), Budget(60))
    assert section["count"] == 60 and len(section["listed"]) == 50


def test_a_journal_that_starts_after_the_week_began_makes_new_devices_partial():
    scan = _scan([_new("AA", _t(12))], examined_from=_t(11, 6))
    section = rs.new_devices(WEEK, scan, _registry(), object(), Budget(60))
    assert section["status"] == "partial"
    assert section["coverage"].startswith(
        "First sightings recorded between 11 Nov 06:00"
    )
    assert section["examined_from"] == "2026-11-11T06:00:00Z"


# --- 4. offline incidents ---------------------------------------------------------------


def _down(mac, seen, declared, name="Printer"):
    return {
        "type": "device_offline",
        "key": mac,
        "observed_at": utc_iso(declared),
        "data": {"mac": mac, "name": name, "after_min": 15, "seen_at": utc_iso(seen)},
    }


def _up(mac, seen, back, detected, name="Printer"):
    return {
        "type": "device_online",
        "key": mac,
        "observed_at": utc_iso(detected),
        "data": {
            "mac": mac,
            "name": name,
            "after_min": 15,
            "seen_at": utc_iso(seen),
            "back_at": utc_iso(back),
            "away_min": 1,
        },
    }


def _watched(rows=(), success_at=GENERATED - timedelta(minutes=2)):
    watched = MagicMock()
    watched.view.return_value = {
        "check": {"success_at": utc_iso(success_at) if success_at else None},
        "devices": list(rows),
    }
    return watched


def _offline(entries, period=WEEK, watched=None, now=GENERATED, **scan_kw):
    return rs.offline(period, _scan(entries, **scan_kw), watched or _watched(), now)


def test_a_return_at_2359_detected_at_0003_still_pairs():
    entries = [
        _down("AA", _t(15, 20), _t(15, 20, 30)),
        _up("AA", _t(15, 20), _t(15, 23, 59), _t(16, 0, 3)),
    ]
    [incident] = _offline(entries)["incidents"]
    assert incident["state"] == "returned"
    assert (incident["from"], incident["to"]) == (
        "2026-11-15T20:00:00Z",
        "2026-11-15T23:59:00Z",
    )
    assert incident["minutes"] == 239 and incident["name"] == "Printer"


def test_an_outage_across_midnight_on_sunday_is_clipped_to_each_week():
    entries = [
        _down("AA", _t(15, 22), _t(15, 22, 30)),
        _up("AA", _t(15, 22), _t(16, 2), _t(16, 2, 5)),
    ]
    [week] = _offline(entries)["incidents"]
    [nxt] = _offline(entries, period=NEXT, now=_t(23, 8))["incidents"]
    assert (week["from"], week["to"], week["minutes"]) == (
        "2026-11-15T22:00:00Z",
        "2026-11-16T00:00:00Z",
        120,
    )
    assert (nxt["from"], nxt["to"], nxt["minutes"]) == (
        "2026-11-16T00:00:00Z",
        "2026-11-16T02:00:00Z",
        120,
    )


def test_an_online_entry_without_its_offline_is_a_whole_interval():
    [incident] = _offline([_up("AA", _t(12, 9), _t(12, 10), _t(12, 10, 4))])[
        "incidents"
    ]
    assert incident["state"] == "returned" and incident["minutes"] == 60


def test_an_outage_left_by_an_unwatch_never_haunts_later_weeks():
    w1 = Period.of(date(2026, 11, 2), date(2026, 11, 8), LONDON)
    opening = _down("AA", _t(3, 9), _t(3, 9, 30))
    # in its own week: it reached the week, its return wasn't recorded
    [first] = _offline([opening], period=w1, now=_t(9, 8))["incidents"]
    assert first["state"] == "return_unrecorded" and first["to"] is None
    assert first["detail"] == "Return time not recorded"
    # the next week, with no later event: nothing shows it reached the week
    assert _offline([opening])["incidents"] == []
    # re-watched later and down again on 18 Nov: superseded, so it ended before then
    again = _down("AA", _t(18, 7), _t(18, 7, 30))
    after = Period.of(date(2026, 11, 23), date(2026, 11, 29), LONDON)
    assert _offline([opening, again], period=after, now=_t(30, 8))["incidents"] == []


def test_a_superseded_opening_reads_returned_before_the_next_sighting():
    entries = [
        _down("AA", _t(5, 9), _t(5, 9, 30)),
        _down("AA", _t(11, 7), _t(11, 7, 30)),
    ]
    incidents = _offline(entries)["incidents"]
    old = next(i for i in incidents if i["state"] == "returned_unrecorded")
    assert old["from"] == "2026-11-09T00:00:00Z" and old["to"] is None
    assert old["detail"] == "Returned before 11 Nov 07:00, time not recorded"
    new = next(i for i in incidents if i["from"] == "2026-11-11T07:00:00Z")
    assert new["state"] == "return_unrecorded"


def test_seen_sunday_declared_monday_then_unwatched_shows_in_that_week_only():
    opening = _down(
        "AA", _t(8, 23), _t(9, 0, 20)
    )  # last seen Sun 8th, declared Mon 9th
    [incident] = _offline([opening])["incidents"]
    assert incident["state"] == "return_unrecorded"
    assert incident["from"] == "2026-11-09T00:00:00Z"
    assert _offline([opening], period=NEXT, now=_t(23, 8))["incidents"] == []


def test_a_pre_week_opening_with_no_later_event_is_dropped():
    assert _offline([_down("AA", _t(4, 9), _t(4, 9, 30))])["incidents"] == []


def test_still_offline_needs_a_fresh_check_and_the_same_last_sighting():
    opening = _down("AA", _t(14, 9), _t(14, 9, 30))
    row = {"mac": "AA", "state": "down", "seen_at": utc_iso(_t(14, 9))}
    [still] = _offline([opening], watched=_watched([row]))["incidents"]
    assert still["state"] == "still_offline" and still["to"] == utc_iso(WEEK.end)
    stale = _watched([row], success_at=GENERATED - timedelta(minutes=20))
    assert (
        _offline([opening], watched=stale)["incidents"][0]["state"]
        == "return_unrecorded"
    )
    other = _watched([{**row, "seen_at": utc_iso(_t(14, 10))}])
    assert (
        _offline([opening], watched=other)["incidents"][0]["state"]
        == "return_unrecorded"
    )


def test_offline_counts_the_watched_devices_and_says_whom_it_covers():
    section = _offline([], watched=_watched([{"mac": "AA"}, {"mac": "BB"}]))
    assert section["watched_now"] == 2 and section["coverage"] == "Watched devices only"
    assert section["status"] == "ok"


def test_an_unreadable_watched_list_never_claims_still_offline():
    watched = MagicMock()
    watched.view.side_effect = RuntimeError("store unavailable")
    opening = _down("AA", _t(14, 9), _t(14, 9, 30))
    section = _offline([opening], watched=watched)
    assert section["incidents"][0]["state"] == "return_unrecorded"
    assert section["watched_now"] is None and section["status"] == "partial"


def test_5000_closed_pre_week_outages_then_one_in_the_week(tmp_path):
    journal = EventJournal(str(tmp_path / "events.jsonl"))
    for n in range(5_000):
        seen = _t(1) + timedelta(minutes=2 * n)
        d, u = (
            _down("AA", seen, seen),
            _up("AA", seen, seen + timedelta(minutes=1), seen),
        )
        journal.append(d["type"], "AA", d["observed_at"], d["data"])
        journal.append(u["type"], "AA", u["observed_at"], u["data"])
    inside = _down("AA", _t(12, 9), _t(12, 9, 30))
    journal.append(inside["type"], "AA", inside["observed_at"], inside["data"])
    scan = journal.scan(WEEK.start, WEEK.end, _far())
    section = rs.offline(WEEK, scan, _watched(), GENERATED)
    assert [i["from"] for i in section["incidents"]] == ["2026-11-12T09:00:00Z"]
    assert scan["truncated"] is False


def test_a_re_enrolled_mac_down_again_is_its_own_incident():
    entries = [
        _down("AA", _t(10, 9), _t(10, 9, 30)),
        _up("AA", _t(10, 9), _t(10, 11), _t(10, 11, 3)),
        _down("AA", _t(13, 18), _t(13, 18, 30)),
        _up("AA", _t(13, 18), _t(13, 19), _t(13, 19, 2)),
    ]
    incidents = _offline(entries)["incidents"]
    assert [(i["from"], i["minutes"]) for i in incidents] == [
        ("2026-11-10T09:00:00Z", 120),
        ("2026-11-13T18:00:00Z", 60),
    ]


# --- 5. data cap ---------------------------------------------------------------------------


def _tracker(cap):
    tracker = MagicMock()
    tracker.get_cap.return_value = {"monthly_cap_bytes": cap}
    return tracker


def _crossing_entry(at, threshold="80", month="2026-11", cap=1000 * GB):
    return {
        "type": "data_cap",
        "key": threshold,
        "observed_at": utc_iso(at),
        "data": {"month": month, "used": 1, "cap": cap, "threshold": threshold},
    }


def test_the_cap_percentage_uses_the_current_rules_lower_bound_floored():
    days = {
        f"2026-11-{n:02d}": _day(100 * GB, d=date(2026, 11, n)) for n in range(1, 16)
    }
    days["2026-11-03"] = _day(500 * GB, rules="rules-before", d=date(2026, 11, 3))
    section = rs.data_cap(WEEK, _pinned(_snapshot(days)), _tracker(3000 * GB), _scan())
    assert section["used_counted"] == 1400 * GB  # 14 days under the current rules
    assert section["used_provisional"] == 1900 * GB
    assert section["percent"] == 46.6  # 46.66…, floored
    assert (section["days_counted"], section["days_so_far"]) == (14, 15)
    assert section["status"] == "partial" and section["month"] == "2026-11"


def test_a_delayed_report_counts_no_usage_after_the_period():
    days = {f"2026-11-{n:02d}": _day(GB, d=date(2026, 11, n)) for n in range(1, 21)}
    pinned = _pinned(_snapshot(days), now=_t(21, 12))
    section = rs.data_cap(WEEK, pinned, _tracker(100 * GB), _scan())
    assert section["used_counted"] == 15 * GB and section["days_so_far"] == 15


def test_a_month_rollover_shows_the_recorded_month_and_cap_after_the_cap_is_cleared():
    period = Period.of(date(2026, 10, 26), date(2026, 11, 1), LONDON)
    pinned = _pinned(_snapshot({"2026-11-01": _day(GB, d=date(2026, 11, 1))}))
    scan = _scan([_crossing_entry(_t(28, 10, month=10), "100", "2026-10", 500 * GB)])
    section = rs.data_cap(period, pinned, _tracker(0), scan)
    assert section["cap_bytes"] is None and section["percent"] is None
    assert section["month"] == "2026-11" and section["days_so_far"] == 1
    assert section["crossings"] == [
        {
            "month": "2026-10",
            "threshold": 100,
            "cap": 500 * GB,
            "at": "2026-10-28T10:00:00Z",
        }
    ]


def test_an_unreadable_journal_leaves_the_crossings_unknown():
    pinned = _pinned(_snapshot(_week_days([GB] * 7)))
    section = rs.data_cap(WEEK, pinned, _tracker(100 * GB), OSError("unreadable"))
    assert section["crossings"] is None and section["status"] == "partial"


# --- build_sections -------------------------------------------------------------------------


def _deps(tmp_path, client=None, journal=None, ledger=None):
    return ReportDeps(
        ledger=ledger or FakeLedger(_snapshot(_week_days([GB] * 7))),
        journal=journal or EventJournal(str(tmp_path / "events.jsonl")),
        registry=_registry(),
        watched=_watched(),
        tracker=_tracker(100 * GB),
        client=client or FakeClient([], indices=_all_dated()),
        network_index="arkime_sessions3-*",
    )


def test_build_sections_gives_the_five_sections_in_order(tmp_path):
    journal = MagicMock()
    journal.scan.return_value = _scan([_new("AA", _t(10))])
    month = {f"2026-11-{n:02d}": _day(GB, d=date(2026, 11, n)) for n in range(1, 16)}
    ledger = FakeLedger(_snapshot(month))
    sections = build_sections(
        WEEK, _deps(tmp_path, journal=journal, ledger=ledger), _far()
    )
    assert list(sections) == ["traffic", "alerts", "new_devices", "offline", "data_cap"]
    assert {s["status"] for s in sections.values()} == {"ok"}


def test_build_sections_never_raises_when_everything_fails(tmp_path):
    ledger = MagicMock()
    ledger.snapshot.side_effect = RuntimeError("boom")
    journal = MagicMock()
    journal.scan.side_effect = OSError("the event journal can't be read")
    client = MagicMock()
    client.search.side_effect = ConnectionTimeout("TIMEOUT", "x", None)
    deps = ReportDeps(
        ledger=ledger,
        journal=journal,
        registry=_registry(),
        watched=_watched(),
        tracker=_tracker(0),
        client=client,
        network_index="arkime_sessions3-*",
    )
    sections = build_sections(WEEK, deps, _far())
    assert {s["status"] for s in sections.values()} == {"unavailable"}
    assert sections["alerts"]["note"] == "It ran out of time."
    assert sections["new_devices"]["note"] == "A file it needs couldn't be read."


def test_an_expired_deadline_sends_no_search_and_never_reports_ok_alerts(tmp_path):
    client = FakeClient([_alert(_t(10))], indices=_all_dated())
    sections = build_sections(
        WEEK, _deps(tmp_path, client=client), time.monotonic() - 1
    )
    assert client.searches == [] and client.cat.indices.call_count == 0
    assert sections["alerts"]["status"] == "unavailable"
    assert sections["traffic"]["status"] == "ok"  # no I/O: the pinned ledger


def test_one_deadline_reaches_the_journal_scan(tmp_path):
    journal = MagicMock()
    journal.scan.return_value = _scan()
    deadline = _far()
    build_sections(WEEK, _deps(tmp_path, journal=journal), deadline)
    journal.scan.assert_called_once_with(WEEK.start, WEEK.end, deadline)
