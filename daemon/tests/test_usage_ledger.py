"""The durable usage ledger (NET-329, roadmap F4): plan §6, every round's rules.

A fake store holds daily indices (name, UUID) and their records; a fake recount sums them.
No OpenSearch, no sleeping: the clocks are injected.
"""

import json
import threading
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from opensearchpy import ConnectionError as TransportConnectionError
from opensearchpy import AuthenticationException, ConnectionTimeout, SerializationError

from services import owner_tz, usage_report
from services import usage_ledger as ledger_mod
from services.usage_days import day_key, merge_day, trimmed
from services.usage_ledger import UsageLedger, UsageLedgerIncomplete
from storage.exact_terms import SearchTimedOut
from storage.snapshot_search import QueryFailed, TooSlow

UTC = timezone.utc
T0 = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
LA = "America/Los_Angeles"
NOV = {n: date(2026, 11, n) for n in range(1, 31)}


class Clock:
    def __init__(self, wall: datetime) -> None:
        self.wall, self.mono = wall, 1000.0

    def now(self) -> datetime:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def to(self, wall: datetime) -> None:
        self.mono += max(0.0, (wall - self.wall).total_seconds())
        self.wall = wall


class Store:
    """The ledger's OpenSearch: daily indices, each with a UUID, holding records."""

    def __init__(self) -> None:
        self.indices: dict[str, str] = {}  # uuid -> name
        self.records: list[tuple] = []  # (uuid, ts, ip, upload, download, local)
        self.serial = 0
        self.listing_errors: list[Exception] = []  # the next listings fail, one each
        self.cat = SimpleNamespace(indices=self._cat)
        self.bounds_reply: dict = {}  # what the min/max search of undated indices answers

    def create(self, name: str) -> str:
        self.serial += 1
        self.indices = {**self.indices, f"u{self.serial}": name}
        return f"u{self.serial}"

    def add(
        self,
        ts: datetime,
        up: int = 100,
        down: int = 0,
        ip: str = "192.168.1.10",
        local: int = 0,
    ):
        """A record, in its UTC day's index; Logstash creates the index if it is gone."""
        name = f"arkime_sessions3-{ts:%y%m%d}"
        uuid = next((u for u, n in self.indices.items() if n == name), None)
        self.records.append((uuid or self.create(name), ts, ip, up, down, local))

    def fill(self, first: int, last: int, **kw) -> None:
        for n in range(first, last + 1):
            self.add(datetime(2026, 11, n, 10, tzinfo=UTC), **kw)

    def prune(self, day: date) -> None:
        gone = {u for u, n in self.indices.items() if n.endswith(f"{day:%y%m%d}")}
        self.indices = {u: n for u, n in self.indices.items() if u not in gone}
        self.records = [r for r in self.records if r[0] not in gone]

    def _cat(self, **params):
        assert params["index"] == "arkime_sessions3-*"
        assert 0 < params["request_timeout"] <= 10
        if self.listing_errors:
            raise self.listing_errors.pop(0)
        return [{"index": n, "uuid": u} for u, n in self.indices.items()]

    def search(self, index, body, budget):
        assert budget.remaining() > 0 and "idx" in body["aggs"]
        return self.bounds_reply


class Tracker:
    """usage_for_ranges over the store's records."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.calls: list[list[str]] = []
        self.fail: list = []  # one entry per call: an exception to raise, or None
        self.during: dict = {}  # call number -> what happens while that query runs
        self.gate: threading.Event | None = None
        self.entered = threading.Event()

    def usage_for_ranges(self, client, ranges, excluded_ips, lan_filter, budget):
        assert client is self.store and budget.remaining() > 0
        self.calls.append([k for k, _s, _e in ranges])
        self.entered.set()
        if self.gate:
            assert self.gate.wait(5)
        if hook := self.during.pop(len(self.calls), None):
            hook()
        if self.fail and (exc := self.fail.pop(0)):
            raise exc
        return {key: self._sum(start, end, excluded_ips) for key, start, end in ranges}

    def _sum(self, start: str, end: str, excluded: list[str]) -> dict:
        lo, hi = (
            datetime.fromisoformat(t.replace("Z", "+00:00")) for t in (start, end)
        )
        rows = [
            r for r in self.store.records if lo <= r[1] < hi and r[2] not in excluded
        ]
        up, down, local = (sum(r[i] for r in rows) for i in (3, 4, 5))
        return {"download": down, "upload": up, "local": local, "total": up + down}


class World:
    def __init__(self, tmp_path, now: datetime = T0, tz: str | None = None) -> None:
        self.path = tmp_path / "usage-ledger.json"
        self.clock = Clock(now)
        self.store = Store()
        self.excluded: list[str] = []
        if tz:
            owner_tz.write(tz)
        self.reload()

    def reload(self) -> None:
        """A daemon restart: a new ledger from the file."""
        self.tracker = Tracker(self.store)
        self.ledger = UsageLedger(
            self.store,
            self.tracker,
            excluded_ips=lambda: self.excluded,
            lan_filter=lambda: None,
            path=str(self.path),
            now=self.clock.now,
            monotonic=self.clock.monotonic,
        )

    def run(self):
        return self.ledger.run(self.clock.monotonic() + 240)

    def report(self, first: date, last: date | None = None) -> dict:
        return usage_report.daily(
            self.ledger.snapshot(),
            first,
            last or first,
            self.clock.now(),
            self.ledger.current_rules(),
            owner_tz.read(),
        )

    def month(self) -> dict:
        snap = self.ledger.snapshot()
        return usage_report.month(
            snap,
            2026,
            11,
            self.clock.now(),
            self.ledger.current_rules(),
            owner_tz.read(),
        )

    def status(self, d: date) -> str:
        return self.report(d)["days"][0]["status"]

    def entry(self, d: date) -> dict:
        return self.ledger.snapshot()["days"].get(day_key(d), {})

    def sweep(self) -> dict:
        return self.ledger.snapshot()["sweep"]


@pytest.fixture(autouse=True)
def _owner_tz_file(tmp_path, monkeypatch):
    monkeypatch.setenv("OWNER_TZ_FILE", str(tmp_path / "owner-timezone.json"))


# --- the basics (round 1) ----------------------------------------------------


def test_a_first_pass_counts_every_covered_day_and_saves_it(tmp_path):
    w = World(tmp_path)
    w.store.fill(1, 18)
    assert w.run() is None  # the whole sweep fit in one pass
    snap = w.ledger.snapshot()
    assert (snap["since"], snap["gaps"], snap["tz"]) == ("2026-11-01", [], "UTC")
    assert w.sweep()["chunks_done"] == 3 and w.sweep()["cursor"] is None
    report = w.report(NOV[1], NOV[18])
    assert {d["status"] for d in report["days"]} == {"counted"}
    assert report["bytes"]["total"] == 1800 and report["complete"]
    # recent first (3 days in one query), then 7-day chunks oldest first
    assert w.tracker.calls[0] == ["2026-11-16", "2026-11-17", "2026-11-18"]
    assert w.tracker.calls[1][0] == "2026-11-01" and len(w.tracker.calls[1]) == 7
    assert json.loads(w.path.read_text())["days"]["2026-11-05"]["total"] == 100
    w.reload()
    assert w.entry(NOV[5])["total"] == 100  # a restart reads the same totals


def test_the_total_never_goes_down_when_raw_data_is_pruned(tmp_path):
    w = World(tmp_path)
    w.store.fill(10, 18)
    w.run()
    w.store.prune(NOV[17])  # before it settled (it ended 12 h ago)
    w.clock.to(T0 + timedelta(minutes=15))
    w.run()
    assert w.entry(NOV[17])["total"] == 100
    assert w.status(NOV[17]) == "approximate"
    # an older day settled first, so pruning it leaves it complete
    assert "settled_at" in w.entry(NOV[10])
    w.store.prune(NOV[10])
    w.run()
    assert (w.entry(NOV[10])["total"], w.status(NOV[10])) == (100, "counted")


def test_a_lower_recount_keeps_the_whole_split_and_a_higher_one_replaces_it():
    """Codex r1 #2: never one direction's maximum beside the other's."""
    stored = {"total": 110, "upload": 100, "download": 10, "local": 0, "rules": "r"}
    higher = {"total": 110, "upload": 10, "download": 100, "local": 0}
    merged = merge_day(stored, higher, "r", "now", "cut")
    assert (merged["upload"], merged["download"]) == (10, 100)
    lower = {"total": 50, "upload": 50, "download": 0, "local": 0}
    kept = merge_day(stored, lower, "r", "now", "cut")
    assert (kept["upload"], kept["download"], kept["total"]) == (100, 10, 110)
    assert kept["coverage_lost_at"] == "now"
    again = merge_day({**kept, "coverage_lost_at": "first"}, lower, "r", "later", "c")
    assert again["coverage_lost_at"] == "first"  # immutable


def test_the_ledger_keeps_only_the_newest_400_days():
    today = date(2026, 11, 18)
    state = {
        "since": "2025-01-01",
        "gaps": ["2025-01-02", "2026-11-01"],
        "days": {"2025-01-01": {"total": 1}, "2026-11-02": {"total": 2}},
    }
    out = trimmed(state, today)
    assert out["since"] == day_key(today - timedelta(days=399))
    assert out["gaps"] == ["2026-11-01"]
    assert list(out["days"]) == ["2026-11-02"]


def test_a_failed_recount_shows_stale_and_midnight_shows_pending(tmp_path):
    """Codex r1 #10: freshness is visible, and the new day isn't called stale or pruned."""
    w = World(tmp_path)
    w.store.fill(16, 18)
    w.run()
    w.clock.to(T0 + timedelta(minutes=46))  # no pass since: today is stale
    assert w.status(NOV[18]) == "stale"
    w.tracker.fail = [QueryFailed("2 shard(s) failed")]
    with pytest.raises(UsageLedgerIncomplete, match="1 of 2 day groups failed"):
        w.run()
    assert w.entry(NOV[18])["failed_at"] and w.entry(NOV[18])["total"] == 100
    assert w.status(NOV[17]) == "stale"  # the last recount failed
    w.clock.to(datetime(2026, 11, 18, 23, 55, tzinfo=UTC))
    w.run()
    assert w.status(NOV[17]) == "counted"
    w.clock.to(datetime(2026, 11, 19, 0, 10, tzinfo=UTC))  # before the next pass
    assert (w.status(NOV[19]), w.status(NOV[18])) == ("pending", "counted")


# --- coverage evidence (round 2) --------------------------------------------


def test_settled_then_inventory_lost_then_pruned_then_rules_change_keeps_figures(
    tmp_path,
):
    """Codex r2 #1."""
    w = World(tmp_path)
    w.store.fill(1, 18)
    w.run()
    assert "settled_at" in w.entry(NOV[1])
    data = json.loads(w.path.read_text())
    w.path.write_text(json.dumps({k: v for k, v in data.items() if k != "indices"}))
    w.reload()
    w.clock.to(T0 + timedelta(minutes=15))
    w.run()
    assert "coverage_lost_at" in w.entry(NOV[1])  # every day, settled ones too
    assert w.status(NOV[1]) == "counted"  # it settled first
    assert w.ledger.snapshot()["inventory_ok"] is True  # the inventory restarted
    w.store.prune(NOV[1])
    w.excluded = ["192.168.1.10"]  # would make every day 0
    w.run()
    assert w.entry(NOV[1])["total"] == 100
    assert w.status(NOV[1]) == "old_rules"


def test_prune_then_a_stable_recount_after_72h_then_a_second_prune_stays_approximate(
    tmp_path,
):
    """Codex r2 #2."""
    w = World(tmp_path)
    w.store.fill(16, 18)
    w.run()
    w.store.prune(NOV[17])
    w.run()
    first_loss = w.entry(NOV[17])["coverage_lost_at"]
    w.clock.to(datetime(2026, 11, 21, 12, tzinfo=UTC))  # 84 h after Nov 17 ended
    w.run()  # the daily sweep recounts it, listing unchanged
    assert "2026-11-17" in [k for call in w.tracker.calls for k in call]
    assert "settled_at" not in w.entry(NOV[17])
    w.store.add(
        datetime(2026, 11, 17, 23, tzinfo=UTC), up=5
    )  # recreated, then pruned again
    w.run()
    w.store.prune(NOV[17])
    w.ledger.request_sweep()
    w.run()
    assert w.entry(NOV[17])["coverage_lost_at"] == first_loss
    assert w.status(NOV[17]) == "approximate"


def test_a_failed_save_publishes_nothing_and_a_restart_reads_the_same_totals(
    tmp_path, monkeypatch
):
    """Codex r2 #3: save, then publish."""
    w = World(tmp_path)
    w.store.fill(10, 18)
    w.run()
    before = w.ledger.snapshot()
    report = w.report(NOV[10], NOV[18])
    w.store.add(datetime(2026, 11, 18, 11, tzinfo=UTC), up=50)
    w.ledger.request_sweep()

    def full_disk(*_a, **_kw):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(ledger_mod, "write_file_atomic", full_disk)
    w.clock.to(T0 + timedelta(minutes=15))
    with pytest.raises(UsageLedgerIncomplete, match="couldn't save the usage ledger"):
        w.run()
    assert w.ledger.snapshot() is before
    assert w.report(NOV[10], NOV[18]) == report
    assert w.sweep() == before["sweep"]  # no new sweep, cursor unchanged
    monkeypatch.undo()
    w.reload()
    assert w.ledger.snapshot()["days"] == before["days"]


# --- bootstrap (round 2 #5, round 3 #1, round 4 #1) ----------------------------


def test_sparse_history_leaves_a_permanent_gap_that_is_never_recounted(tmp_path):
    w = World(tmp_path, now=datetime(2026, 11, 4, 12, tzinfo=UTC))
    for n in (1, 3, 4):
        w.store.add(datetime(2026, 11, n, 10, tzinfo=UTC))
    w.run()
    snap = w.ledger.snapshot()
    assert (snap["since"], snap["gaps"]) == ("2026-11-01", ["2026-11-02"])
    assert w.status(NOV[2]) == "not_counted"
    w.clock.to(datetime(2026, 11, 6, 12, tzinfo=UTC))
    w.run()  # a second sweep
    assert all("2026-11-02" not in call for call in w.tracker.calls)
    report = w.report(NOV[1], NOV[4])
    assert report["gaps"] == [{"date": "2026-11-02", "reason": "not_counted"}]


def test_an_empty_store_starts_counting_today(tmp_path):
    w = World(tmp_path)
    assert w.run() is None
    snap = w.ledger.snapshot()
    assert (snap["since"], snap["gaps"]) == ("2026-11-18", [])
    assert (w.status(NOV[18]), w.entry(NOV[18])["total"]) == ("counted", 0)
    assert w.status(NOV[17]) == "not_counted"


def test_a_local_day_with_one_of_its_two_utc_dates_missing_is_a_gap(tmp_path):
    w = World(tmp_path, now=datetime(2026, 11, 13, 20, tzinfo=UTC), tz=LA)
    for n in (9, 10, 12, 13):
        w.store.add(datetime(2026, 11, n, 10, tzinfo=UTC))
    w.run()
    snap = w.ledger.snapshot()
    # Nov 9 in LA is Nov 9 08:00Z to Nov 10 08:00Z: both UTC dates are there
    assert snap["since"] == "2026-11-09"
    assert snap["gaps"] == ["2026-11-10", "2026-11-11"]
    assert w.status(NOV[12]) == "counted"


def test_today_at_la_noon_is_counted_through_utc_and_local_midnight(tmp_path):
    """Codex r3 #1, at bootstrap."""
    w = World(tmp_path, now=datetime(2026, 11, 18, 20, tzinfo=UTC), tz=LA)
    w.store.add(datetime(2026, 11, 17, 10, tzinfo=UTC))
    w.store.add(datetime(2026, 11, 18, 19, tzinfo=UTC), up=7)
    w.run()
    snap = w.ledger.snapshot()
    assert (snap["since"], snap["gaps"]) == ("2026-11-17", [])
    assert (w.status(NOV[18]), w.entry(NOV[18])["total"]) == ("counted", 7)
    w.clock.to(datetime(2026, 11, 19, 2, tzinfo=UTC))  # past UTC midnight, 18:00 in LA
    w.store.add(datetime(2026, 11, 19, 1, tzinfo=UTC), up=3)
    w.run()
    assert (w.status(NOV[18]), w.entry(NOV[18])["total"]) == ("counted", 10)
    w.clock.to(
        datetime(2026, 11, 19, 9, tzinfo=UTC)
    )  # 01:00 in LA: Nov 18 is yesterday
    w.run()
    assert (w.status(NOV[18]), w.entry(NOV[18])["total"]) == ("counted", 10)
    assert w.entry(NOV[18])["cutoff"] == "2026-11-19T08:00:00Z"


def test_a_transition_at_la_noon_counts_today_in_the_new_zone(tmp_path):
    """Codex r3 #1, at a time-zone change."""
    w = World(tmp_path, now=datetime(2026, 11, 18, 20, tzinfo=UTC))
    w.store.fill(15, 18)
    w.run()
    owner_tz.write(LA)
    assert w.report(NOV[18])["pending_tz"] == LA
    w.run()
    snap = w.ledger.snapshot()
    assert (snap["tz"], snap["generation"]) == (LA, 2)
    (kept,) = tmp_path.glob("usage-ledger.gen1.*.json")
    assert json.loads(kept.read_text())["tz"] == "UTC"
    assert w.report(NOV[18])["pending_tz"] is None
    assert NOV[18].isoformat() not in snap["gaps"]
    assert w.status(NOV[18]) == "counted"
    assert w.status(NOV[15]) == "counted"  # Nov 15 LA: Nov 15 08Z to Nov 16 08Z


def test_today_at_la_evening_after_an_emergency_prune_is_approximate(tmp_path):
    """Codex r4 #1: only the new UTC date's index survives; 16 local hours are gone."""
    w = World(tmp_path, now=datetime(2026, 11, 19, 2, tzinfo=UTC), tz=LA)
    w.store.add(datetime(2026, 11, 19, 1, tzinfo=UTC), up=40)
    w.run()
    assert w.ledger.snapshot()["since"] == "2026-11-18"
    assert w.entry(NOV[18])["total"] == 40  # what survives is still counted
    assert w.status(NOV[18]) == "approximate"


def test_a_crash_inside_a_transition_repeats_it_cleanly(tmp_path):
    w = World(tmp_path)
    w.store.fill(16, 18)
    w.run()
    owner_tz.write(LA)
    w.store.listing_errors = [TransportConnectionError("N/A", "refused", None)]
    with pytest.raises(UsageLedgerIncomplete):
        w.run()
    kept = list(tmp_path.glob("usage-ledger.gen1.*.json"))
    assert kept and all(json.loads(k.read_text())["tz"] == "UTC" for k in kept)
    assert (
        w.ledger.snapshot()["tz"] == "UTC"
    )  # the old ledger is still the published one
    assert w.store.listing_errors == []
    w.reload()
    w.run()
    assert (w.ledger.snapshot()["tz"], w.ledger.snapshot()["generation"]) == (LA, 2)


def test_a_zone_change_on_install_day_doesnt_call_today_approximate(tmp_path):
    """Review: Berlin at 10:00 on day one has only today's UTC index; switching from the
    default UTC adds Nov 18 23:00Z to today, which was never captured, not pruned."""
    w = World(tmp_path, now=datetime(2026, 11, 19, 9, tzinfo=UTC))
    w.store.add(datetime(2026, 11, 19, 8, tzinfo=UTC), up=30)
    w.run()
    assert w.ledger.snapshot()["since"] == "2026-11-19"
    owner_tz.write("Europe/Berlin")
    w.run()
    snap = w.ledger.snapshot()
    assert (snap["tz"], snap["since"]) == ("Europe/Berlin", "2026-11-19")
    assert "coverage_lost_at" not in w.entry(NOV[19])
    assert (w.status(NOV[19]), w.entry(NOV[19])["total"]) == ("counted", 30)


def test_a_zone_change_after_an_emergency_prune_still_marks_today(tmp_path):
    """The floor is where the old ledger began: a long-running box keeps Codex r4 #1."""
    w = World(tmp_path, now=datetime(2026, 11, 19, 1, tzinfo=UTC))
    w.store.fill(10, 18)
    w.store.add(datetime(2026, 11, 19, 0, 30, tzinfo=UTC))
    w.run()
    w.store.prune(NOV[18])  # every index before the current UTC date can go
    owner_tz.write(LA)  # 17:00 on Nov 18 in LA: it began Nov 18 08:00Z
    w.run()
    assert w.ledger.snapshot()["tz"] == LA
    assert w.status(NOV[18]) == "approximate"


def test_an_unknown_inventory_and_a_failed_listing_stop_the_pass(tmp_path):
    """Review: evidence 4 must be on disk before any recount under new rules can merge."""
    w = World(tmp_path)
    w.store.fill(1, 18)
    w.run()
    data = json.loads(w.path.read_text())
    w.path.write_text(json.dumps({k: v for k, v in data.items() if k != "indices"}))
    w.reload()
    w.store.prune(NOV[17])  # its raw data is gone; it never settled
    w.excluded = ["192.168.1.10"]  # every recount would read 0
    w.store.listing_errors = [ConnectionTimeout("TIMEOUT", "read timed out", None)]
    w.clock.to(T0 + timedelta(minutes=15))
    with pytest.raises(UsageLedgerIncomplete, match="the index listing"):
        w.run()
    assert w.tracker.calls == []  # nothing was recounted, so nothing merged
    assert w.entry(NOV[17])["total"] == 100
    w.run()  # the listing works again: every day is marked first
    assert (w.entry(NOV[17])["total"], w.status(NOV[17])) == (100, "old_rules")
    assert (w.entry(NOV[10])["total"], w.status(NOV[10])) == (100, "old_rules")


def test_two_zone_changes_in_a_row_keep_both_earlier_ledgers(tmp_path):
    """Review (security): a mistaken zone fixed 15 min later must not lose the first ledger,
    the only record of days whose raw data was pruned."""
    w = World(tmp_path)
    w.store.fill(15, 18)
    w.run()
    first = w.ledger.snapshot()
    owner_tz.write(LA)
    w.run()
    second = w.ledger.snapshot()
    w.clock.to(T0 + timedelta(minutes=15))
    owner_tz.write("Europe/London")
    w.run()
    assert w.ledger.snapshot()["generation"] == 3
    (gen1,) = tmp_path.glob("usage-ledger.gen1.*.json")
    (gen2,) = tmp_path.glob("usage-ledger.gen2.*.json")
    assert json.loads(gen1.read_text()) == first
    assert json.loads(gen2.read_text()) == second


def test_every_unreadable_ledger_file_is_kept_on_its_own(tmp_path):
    w = World(tmp_path)
    for n in range(2):
        w.path.write_text(f"{{broken {n}")
        w.clock.to(w.clock.now() + timedelta(seconds=1))
        w.reload()
        assert w.ledger.snapshot() is None
    kept = sorted(tmp_path.glob("usage-ledger.corrupt.*.json"))
    assert [k.read_text() for k in kept] == ["{broken 0", "{broken 1"]


def test_an_unreadable_time_zone_file_keeps_the_ledgers_own_zone(tmp_path):
    w = World(tmp_path, tz=LA)
    w.store.fill(16, 18)
    w.run()
    (tmp_path / "owner-timezone.json").write_text("{not json")
    w.clock.to(T0 + timedelta(minutes=15))
    w.run()
    assert (w.ledger.snapshot()["tz"], w.ledger.snapshot()["generation"]) == (LA, 1)


# --- rules (round 2 #6, round 3 #3) -----------------------------------------------


def test_a_rules_change_sweeps_replaces_unpruned_days_and_keeps_pruned_ones(tmp_path):
    w = World(tmp_path)
    w.store.fill(10, 18, up=100)
    w.store.fill(10, 18, up=50, ip="192.168.1.66")
    w.run()
    w.store.prune(NOV[17])
    w.run()
    first_sweep = w.sweep()["id"]
    w.excluded = ["192.168.1.66"]
    w.clock.to(T0 + timedelta(minutes=15))
    w.run()
    assert w.sweep()["id"] == first_sweep + 1
    assert (w.entry(NOV[10])["total"], w.status(NOV[10])) == (100, "counted")
    assert (w.entry(NOV[17])["total"], w.status(NOV[17])) == (150, "old_rules")
    month = w.month()
    assert not month["complete"] and month["projected"] is None


def test_days_the_sweep_hasnt_reached_after_a_rules_change_are_recount_pending(
    tmp_path,
):
    w = World(tmp_path)
    w.store.fill(1, 18)
    w.run()
    w.excluded = ["10.9.9.9"]
    w.tracker.fail = [None, None, TooSlow("a search took too long")]
    w.clock.to(T0 + timedelta(minutes=15))
    assert w.run() == {"partial": True}
    statuses = {d["date"]: d["status"] for d in w.report(NOV[1], NOV[18])["days"]}
    assert statuses["2026-11-03"] == "counted"  # the first chunk ran
    assert statuses["2026-11-10"] == "recount_pending"
    assert (
        statuses["2026-11-18"] == "counted"
    )  # the recent query ran under the new rules
    month = w.month()
    assert not month["complete"] and month["projected"] is None
    w.run()
    month = w.month()
    assert month["complete"] and month["projected"] is not None


# --- the sweep: recount request, timeouts, failures (round 2 #10, round 3 #4, round 4 #2) ---


def test_a_recount_request_starts_a_new_sweep_even_after_a_recent_one(tmp_path):
    w = World(tmp_path)
    w.store.fill(1, 18)
    w.run()
    days = w.ledger.snapshot()["days"]
    w.clock.to(T0 + timedelta(minutes=15))
    w.run()
    assert w.sweep()["id"] == 1  # one finished 15 min ago: none due
    assert w.ledger.request_sweep() == 1
    w.run()
    assert (w.sweep()["id"], w.sweep()["chunks_done"], w.sweep()["cursor"]) == (
        2,
        3,
        None,
    )
    totals = {k: v["total"] for k, v in w.ledger.snapshot()["days"].items()}
    assert totals == {k: v["total"] for k, v in days.items()}


def test_a_recount_request_while_a_sweep_runs_lets_it_finish(tmp_path):
    """Review (security): a request mid-sweep restarted it at the oldest chunk, so a request
    loop re-queried those days for ever. Now the running sweep answers it."""
    w = World(tmp_path)
    w.store.fill(1, 18)
    w.tracker.fail = [None, None, TooSlow("a search took too long")]
    assert w.run() == {"partial": True}
    assert (w.sweep()["id"], w.sweep()["cursor"]) == (1, "2026-11-08")
    assert w.ledger.request_sweep() == 1
    w.tracker.calls.clear()
    assert w.run() is None
    assert w.tracker.calls[1][0] == "2026-11-08"  # resumed at its cursor, not Nov 1
    assert (w.sweep()["id"], w.sweep()["chunks_done"], w.sweep()["cursor"]) == (
        1,
        3,
        None,
    )
    assert not w.ledger._take_sweep_request()  # answered, not kept for later
    w.clock.to(T0 + timedelta(minutes=15))
    w.run()
    assert w.sweep()["id"] == 1


def _out_of_time(w: World):
    """The budget runs out while the query runs: the after-query listing can't start."""

    def spend():
        w.clock.mono += 1000

    return spend


@pytest.mark.parametrize(
    "where",
    [
        "search",
        "gateway lookup",
        "after-query listing",
        "connection timeout",
        "server timeout",
    ],
)
def test_a_timeout_inside_a_chunk_is_a_continuation(tmp_path, where):
    """Codex r3 #4, r4 #2: the cursor stays, nothing is counted done, the next run redoes it."""
    w = World(tmp_path)
    w.store.fill(1, 18)
    raised = {
        "search": TooSlow("a search took too long"),
        "gateway lookup": TooSlow("usage totals: the next-hop check took too long"),
        "connection timeout": ConnectionTimeout("TIMEOUT", "read timed out", None),
        "server timeout": SearchTimedOut("the search timed out on arkime_sessions3-*"),
    }
    if where == "after-query listing":
        w.tracker.during = {2: _out_of_time(w)}
    else:
        w.tracker.fail = [None, raised[where]]
    assert w.run() == {"partial": True}
    sweep = w.sweep()
    assert (sweep["cursor"], sweep["chunks_done"], sweep["chunks_failed"]) == (
        "2026-11-01",
        0,
        0,
    )
    assert sweep["retries"] == 1 and "total" not in w.entry(NOV[1])
    w.reload()  # a restart resumes from the saved cursor
    assert w.run() is None
    assert w.tracker.calls[1][0] == "2026-11-01"
    assert (w.sweep()["chunks_done"], w.status(NOV[1])) == (3, "counted")


def test_a_third_timeout_in_a_row_fails_the_chunk_and_the_sweep_moves_on(tmp_path):
    w = World(tmp_path)
    w.store.fill(1, 18)
    timeout = ConnectionTimeout("TIMEOUT", "read timed out", None)
    for attempt in (1, 2):
        w.tracker.fail = [None, timeout]
        assert w.run() == {"partial": True}
        assert w.sweep()["retries"] == attempt
    w.tracker.fail = [None, timeout]
    with pytest.raises(UsageLedgerIncomplete, match="days 2026-11-01 to 2026-11-07"):
        w.run()
    sweep = w.sweep()
    # the cursor moved on, and the run stopped there (review: one failed chunk a run)
    assert (sweep["chunks_failed"], sweep["chunks_done"], sweep["cursor"]) == (
        1,
        0,
        "2026-11-08",
    )
    assert w.run() is None
    assert (w.sweep()["chunks_done"], w.sweep()["cursor"]) == (2, None)
    assert w.status(NOV[1]) == "stale" and w.status(NOV[9]) == "counted"


def test_another_failure_fails_the_chunk_and_the_cursor_advances(tmp_path):
    w = World(tmp_path)
    w.store.fill(1, 18)
    w.tracker.fail = [None, QueryFailed("usage totals: 1 shard(s) failed")]
    # OLD CODE: match="1 of 5 day groups failed" (review: a failed chunk now ends the run)
    with pytest.raises(UsageLedgerIncomplete, match="1 of 3 day groups failed"):
        w.run()
    sweep = w.sweep()
    assert (sweep["chunks_failed"], sweep["chunks_done"], sweep["cursor"]) == (
        1,
        0,
        "2026-11-08",
    )
    assert w.run() is None  # the next run finishes the sweep
    assert (w.sweep()["chunks_failed"], w.sweep()["chunks_done"]) == (1, 2)
    assert w.entry(NOV[2])["error"].startswith("QueryFailed: usage totals")
    assert w.status(NOV[2]) == "stale"


def _unauthorized() -> list:
    """OpenSearch answering 401 to everything, as after a recreate until its security bootstrap."""
    return [AuthenticationException(401, "Unauthorized", {}) for _ in range(20)]


def test_an_outage_at_the_listing_ends_the_pass_before_any_recount(tmp_path):
    """Review HIGH: every chunk failed in one pass and every older day read stale for a day."""
    w = World(tmp_path)
    w.store.fill(1, 18)
    w.run()
    before = w.sweep()
    w.tracker.calls.clear()
    w.clock.to(T0 + timedelta(hours=25))  # a new sweep is due
    w.store.listing_errors = _unauthorized()
    w.tracker.fail = _unauthorized()
    with pytest.raises(UsageLedgerIncomplete, match="1 of 1 day groups failed"):
        w.run()
    assert w.tracker.calls == [] and w.sweep() == before
    assert w.status(NOV[5]) == "counted"  # older days aren't called stale


def test_an_outage_at_the_search_costs_one_chunk_a_run(tmp_path):
    w = World(tmp_path)
    w.store.fill(1, 18)
    w.run()
    w.clock.to(T0 + timedelta(hours=25))
    w.tracker.fail = _unauthorized()
    with pytest.raises(UsageLedgerIncomplete):
        w.run()
    sweep = w.sweep()
    assert (sweep["chunks_failed"], sweep["finished_at"]) == (1, None)
    assert sweep["cursor"] == "2026-11-08"  # moved on, so one bad chunk can't stall it
    assert w.status(NOV[10]) == "counted"


def test_updated_at_dates_the_last_successful_recount(tmp_path):
    """Review MEDIUM: failure-only saves kept "Not updated since" from ever showing."""
    w = World(tmp_path)
    w.store.fill(1, 18)
    w.run()
    assert w.ledger.snapshot()["updated_at"] == "2026-11-18T12:00:00Z"
    w.clock.to(T0 + timedelta(minutes=30))
    w.ledger.request_sweep()
    w.tracker.fail = [QueryFailed("1 shard(s) failed"), TooSlow("too long")]
    with pytest.raises(UsageLedgerIncomplete):
        w.run()  # a failed recent query, a new sweep and a continuation: all saved
    snap = w.ledger.snapshot()
    assert snap["sweep"]["id"] == 2 and snap["sweep"]["retries"] == 1
    assert snap["updated_at"] == "2026-11-18T12:00:00Z"
    w.run()
    assert w.ledger.snapshot()["updated_at"] == "2026-11-18T12:30:00Z"


def test_a_serialization_error_fails_the_chunk_instead_of_escaping(tmp_path):
    """Review LOW: an OpenSearchException that isn't a TransportError never moved the cursor."""
    w = World(tmp_path)
    w.store.fill(1, 18)
    w.tracker.fail = [None, SerializationError("Unable to deserialize the reply")]
    with pytest.raises(UsageLedgerIncomplete, match="SerializationError"):
        w.run()
    assert (w.sweep()["chunks_failed"], w.sweep()["cursor"]) == (1, "2026-11-08")


def test_a_malformed_bounds_reply_is_a_failed_listing_not_a_crash(tmp_path):
    w = World(tmp_path)
    w.store.fill(16, 18)
    w.store.create(
        "arkime_sessions3-reindexed"
    )  # no date in its name: its bounds are searched
    w.store.bounds_reply = {
        "_shards": {"total": 1, "failed": 0},
        "aggregations": {"idx": {"buckets": [{"key": "arkime_sessions3-reindexed"}]}},
    }
    with pytest.raises(UsageLedgerIncomplete, match="the index bounds: malformed"):
        w.run()
    assert w.ledger.snapshot() is None
    w.store.bounds_reply["aggregations"]["idx"]["buckets"][0].update(
        {"lo": {"value": None}, "hi": {"value": None}}  # an empty index
    )
    w.run()
    assert w.ledger.snapshot()["since"] == "2026-11-16"


def test_a_chunk_never_starts_with_under_30_seconds_left(tmp_path):
    """Review LOW: it would time out and spend one of its three tries for nothing."""
    w = World(tmp_path)
    w.store.fill(1, 18)

    def leave_20_seconds():
        w.clock.mono += 215  # of the pass's 235

    w.tracker.during = {1: leave_20_seconds}
    assert w.run() == {"partial": True}
    assert len(w.tracker.calls) == 1  # only the recent days
    sweep = w.sweep()
    assert (sweep["cursor"], sweep["retries"], sweep["chunks_done"]) == (
        "2026-11-01",
        0,
        0,
    )


# --- the index listing around a query (round 1 #4, #5, round 3 #2) -----------------


def test_an_index_added_during_a_query_defers_settling_but_is_not_loss(tmp_path):
    w = World(tmp_path)
    w.store.fill(1, 18)
    w.tracker.during = {2: lambda: w.store.create("arkime_sessions3-261119")}
    w.run()
    assert "coverage_lost_at" not in w.entry(NOV[2])
    assert "settled_at" not in w.entry(NOV[2])  # that recount may have missed records
    assert "settled_at" in w.entry(NOV[9])  # the next chunk's listing was stable
    w.ledger.request_sweep()
    w.run()
    assert "settled_at" in w.entry(NOV[2]) and w.status(NOV[2]) == "counted"


def test_an_index_deleted_or_recreated_during_a_query_is_loss(tmp_path):
    w = World(tmp_path)
    w.store.fill(1, 18)

    def prune_and_recreate():
        w.store.prune(NOV[3])
        w.store.prune(NOV[4])
        w.store.add(datetime(2026, 11, 4, 9, tzinfo=UTC), up=500)  # same name, new UUID

    w.tracker.during = {2: prune_and_recreate}
    w.run()
    for n in (3, 4):
        assert "coverage_lost_at" in w.entry(NOV[n]), n
        assert w.status(NOV[n]) == "approximate"


def test_a_same_name_recreation_between_passes_is_loss_even_when_the_total_rises(
    tmp_path,
):
    w = World(tmp_path)
    w.store.fill(10, 18)
    w.run()
    w.store.prune(NOV[17])
    w.store.add(
        datetime(2026, 11, 17, 22, tzinfo=UTC), up=300
    )  # late records, more bytes
    w.clock.to(T0 + timedelta(minutes=15))
    w.run()
    assert w.entry(NOV[17])["total"] == 300  # the high-water mark moved up
    assert w.status(NOV[17]) == "approximate"


# --- concurrency -------------------------------------------------------------------


def test_a_snapshot_read_during_a_blocked_query_answers_at_once(tmp_path):
    w = World(tmp_path)
    w.store.fill(16, 18)
    w.run()
    before = w.ledger.snapshot()
    w.store.add(datetime(2026, 11, 18, 11, tzinfo=UTC), up=50)
    w.tracker.gate, w.tracker.entered = threading.Event(), threading.Event()
    w.clock.to(T0 + timedelta(minutes=15))
    job = threading.Thread(target=w.run)
    job.start()
    try:
        assert w.tracker.entered.wait(5)
        assert w.ledger.snapshot() is before  # the lock is never held during a query
        assert w.report(NOV[18])["days"][0]["total"] == 100
    finally:
        w.tracker.gate.set()
        job.join(5)
    assert w.entry(NOV[18])["total"] == 150


# --- what the report says (round 2 #7, #8) ---------------------------------------------


def test_mid_month_caught_up_future_days_are_not_gaps_and_the_month_is_complete(
    tmp_path,
):
    w = World(tmp_path)
    w.store.fill(1, 18)
    w.run()
    month = w.month()
    assert month["complete"] and month["gaps"] == []
    assert {d["status"] for d in month["days"][18:]} == {"future"}
    assert month["days"][20]["total"] is None
    assert not any(d["status"] == "pending" for d in month["days"])
    elapsed = (T0 - datetime(2026, 11, 1, tzinfo=UTC)).total_seconds()
    assert month["daily_rate"] == int(1800 / elapsed * 86400)
    assert month["projected"] == int(1800 / elapsed * 30 * 86400)
    assert month["days_remaining"] == 12.5


def test_the_projection_on_the_first_day_uses_the_cutoff_not_the_read_time(tmp_path):
    w = World(tmp_path, now=datetime(2026, 11, 1, 0, 30, tzinfo=UTC))
    w.store.add(datetime(2026, 11, 1, 0, 10, tzinfo=UTC), up=600)
    w.run()
    assert w.month()["projected"] is None  # 30 min in: under an hour
    w.clock.to(datetime(2026, 11, 1, 2, tzinfo=UTC))
    w.run()
    w.clock.to(datetime(2026, 11, 1, 2, 14, tzinfo=UTC))  # read between passes
    month = w.month()
    assert month["daily_rate"] == int(
        600 / 7200 * 86400
    )  # 2 h to the cutoff, not 2 h 14


def test_the_projection_of_a_daylight_saving_month_uses_real_seconds(tmp_path):
    # Nov 2026 in LA has 30 days and one 25-hour day (Nov 1): 721 hours
    w = World(tmp_path, now=datetime(2026, 11, 3, 8, tzinfo=UTC), tz=LA)
    w.store.fill(1, 3)
    w.store.add(datetime(2026, 10, 31, 10, tzinfo=UTC), up=0)
    w.run()
    month = w.month()
    assert month["month_start"] == "2026-11-01T00:00:00-07:00"
    assert month["month_end"] == "2026-12-01T00:00:00-08:00"
    elapsed = (
        datetime(2026, 11, 3, 8, tzinfo=UTC) - datetime(2026, 11, 1, 7, tzinfo=UTC)
    ).total_seconds()
    total = month["bytes"]["total"]
    assert month["projected"] == int(total / elapsed * 721 * 3600)
    first = month["days"][0]
    assert (first["start"], first["end"]) == (
        "2026-11-01T07:00:00Z",
        "2026-11-02T08:00:00Z",
    )


def test_local_bytes_never_reach_the_total_the_high_water_mark_or_the_projection(
    tmp_path,
):
    """The total is Internet bytes (download + upload); traffic between your own devices is
    kept as `local` beside it (plan §2, NET-226)."""
    w = World(tmp_path)
    w.store.fill(1, 18, up=100, down=20, local=5000)
    w.run()
    month = w.month()
    assert month["bytes"] == {
        "download": 360,
        "upload": 1800,
        "local": 90000,
        "total": 2160,
    }
    assert month["days"][0]["total"] == 120 and month["days"][0]["local"] == 5000
    elapsed = (T0 - datetime(2026, 11, 1, tzinfo=UTC)).total_seconds()
    assert month["daily_rate"] == int(2160 / elapsed * 86400)
    # a recount with less local but more Internet traffic is higher, not lower
    w.store.records = [(*r[:5], 0) for r in w.store.records]
    w.store.add(datetime(2026, 11, 18, 11, tzinfo=UTC), up=1)
    w.clock.to(T0 + timedelta(minutes=15))
    w.run()
    entry = w.entry(NOV[18])
    assert (entry["total"], entry["local"]) == (121, 0)
    assert "coverage_lost_at" not in entry
