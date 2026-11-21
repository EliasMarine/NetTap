"""NET-331 deploy check: the watched-devices job end to end, isolated (plan §2.8 step 5).

Runs inside a throwaway copy of the just-built daemon image (deploy-watched-devices.sh):
    docker run --rm -i --network none --entrypoint python3 <image id> -
        < verify_watched_devices.py
No mounts and no network: a stub OpenSearch client answers the job's two searches, and every
store, journal and state file lives in a fresh temp directory. The watch-only clear goes through
the real route on a loopback test server. Prints WATCHED-DEVICES-OK only after the last check.
Locally, from daemon/:
    PYTHONPATH=. python ../scripts/remote/verify_watched_devices.py
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, "/opt/nettap/daemon")

TMP = tempfile.mkdtemp(prefix="watched-verify-")
os.environ["NETTAP_DATA_DIR"] = os.path.join(TMP, "data")

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402
from opensearchpy import ConnectionTimeout  # noqa: E402

from api.device_custom import register_device_custom_routes  # noqa: E402
from services import watched_devices as wd  # noqa: E402
from services import watched_rules as rules  # noqa: E402
from services.capture_config import write_file_atomic  # noqa: E402
from services.device_custom import DeviceCustomStore  # noqa: E402
from services.device_details import DeviceDetailsStore  # noqa: E402
from services.event_journal import EventJournal  # noqa: E402

T0 = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
A, B, C = "02:00:00:00:00:0A", "02:00:00:00:00:0B", "02:00:00:00:00:0C"
NAMES = {A: "Kitchen plug"}
MIRROR = {
    "mode": "mirror",
    "status": "normal",
    "capture_interface": "enp1s0",
    "link_up": True,
    "promisc_enabled": True,
}
GATEWAY = {
    "mode": "dhcp_gateway",
    "status": "normal",
    "capture_interface": "enp2s0",
    "link_up": True,
    "promisc_enabled": True,
    "routing_active": True,
    "subnet": "10.77.0.0/24",
}
FRESH = "fresh"  # Rig.run's default: capture_at 30 s before the run


class Crash(BaseException):
    """A process dying mid-run: the job's `except Exception` never sees it."""


def fail(why: str) -> None:
    print("FAIL", why, flush=True)
    sys.exit(1)


def say(line: str) -> None:
    print(f"   {line}", flush=True)


def expect(ok: bool, why: str) -> None:
    if not ok:
        fail(why)


def t(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def iso(when: datetime) -> str:
    """The state file's form: milliseconds, Z."""
    return when.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def ms(when: datetime) -> int:
    return int(when.timestamp() * 1000)


# --- the stubs -----------------------------------------------------------------------------


class StubIndex:
    """Answers the capture-time and presence searches from what a check sets; keeps each body."""

    def __init__(self) -> None:
        self.capture_at: datetime | None = None
        self.sent: dict[
            str, tuple[datetime, datetime]
        ] = {}  # MAC: (event.end, @timestamp)
        self.answered: dict[str, tuple[datetime, datetime]] = {}
        self.fault: tuple[str, str] | None = None  # (which search, how)
        self.during_presence = None  # called while the presence search runs
        self.calls: list[dict] = []

    def search(self, *, index: str, body: dict, request_timeout: float) -> dict:
        self.calls.append(body)
        which = "capture" if "capture_at" in body["aggs"] else "presence"
        if which == "presence" and self.during_presence:
            self.during_presence()
        how = self.fault[1] if self.fault and self.fault[0] == which else None
        if how == "timeout":
            raise ConnectionTimeout("TIMEOUT", "stub", TimeoutError("timed out"))
        shards = {"total": 2, "successful": 2, "skipped": 0, "failed": 0}
        reply = {"timed_out": how == "timed_out", "_shards": shards}
        if how == "shard":
            reply["_shards"] = {**shards, "successful": 1, "failed": 1}
        elif how == "zero":
            reply["_shards"] = {**shards, "total": 0, "successful": 0}
        if how != "noaggs":
            reply["aggregations"] = self._aggs(which, body)
        return reply

    def _aggs(self, which: str, body: dict) -> dict:
        if which == "capture":
            value = ms(self.capture_at) if self.capture_at else None
            return {"capture_at": {"value": value}}
        wanted = set(body["aggs"]["sent"]["aggs"]["macs"]["terms"]["include"])

        def side(found: dict) -> dict:
            buckets = [
                {
                    "key": mac.lower(),
                    "doc_count": 1,
                    "seen": {"value": ms(seen)},
                    "started": {"value": ms(started)},
                }
                for mac, (seen, started) in sorted(found.items())
                if mac.lower() in wanted
            ]
            return {"doc_count": len(buckets), "macs": {"buckets": buckets}}

        return {"sent": side(self.sent), "answered": side(self.answered)}


class CrashableJournal:
    """The real journal, with a crash before or after its append on demand."""

    def __init__(self, path: str) -> None:
        self.real = EventJournal(path)
        self.crash: str | None = None

    def append(self, *args, **kwargs):
        if self.crash == "before":
            raise Crash()
        entry = self.real.append(*args, **kwargs)
        if self.crash == "after":
            raise Crash()
        return entry


class Rig:
    """One watched-devices job on temp files, a stub index and a clock the checks move."""

    def __init__(self, name: str) -> None:
        self.dir = os.path.join(TMP, name)
        self.details = DeviceDetailsStore(root=self.dir)
        self.index = StubIndex()
        self.health: dict | Exception = dict(MIRROR)
        self.active: set[str] = set()  # heard a minute before every run
        self.now = T0
        self.state_path = os.path.join(self.dir, "watched-devices.json")
        self.journal_path = os.path.join(self.dir, "events.jsonl")
        self.restart()

    def restart(self) -> None:
        """A new daemon process on the same files."""
        self.journal = CrashableJournal(self.journal_path)
        self.job = wd.WatchedDevices(
            details=self.details,
            journal=self.journal,
            name_for=NAMES.get,
            client=self.index,
            index="arkime_sessions3-*",
            capture_health=self._health,
            path=self.state_path,
            now=lambda: self.now,
        )

    def _health(self) -> dict:
        if isinstance(self.health, Exception):
            raise self.health
        return self.health

    def watch(self, mac: str, minutes: int | None = 15) -> None:
        self.details.update(mac, {"watch_after_min": minutes})

    def heard(self, mac: str, seen: datetime, started: datetime) -> None:
        self.index.sent[mac] = (seen, started)

    def run(self, at: datetime, capture_at: datetime | str | None = FRESH):
        """None, or the exception the run raised, or "crashed"."""
        self.now = at
        self.index.capture_at = (
            at - timedelta(seconds=30) if capture_at == FRESH else capture_at
        )
        for mac in self.active:
            self.heard(mac, at - timedelta(minutes=1), at - timedelta(minutes=2))
        try:
            return self.job.run(time.monotonic() + 60)
        except Crash:
            return "crashed"
        except Exception as exc:  # the checks look at what was raised
            return exc

    def outcome(self, at: datetime, capture_at: datetime | str | None = FRESH):
        """Run once: the check's `skipped` (None for a full check), else what went wrong."""
        result = self.run(at, capture_at)
        if result is not None:
            return f"raised {result!r}"
        check = self.check()
        return f"error {check['error']}" if check["error"] else check["skipped"]

    def state(self) -> dict:
        with open(self.state_path) as fh:
            return json.load(fh)

    def dev(self, mac: str) -> dict:
        return self.state()["devices"][mac]

    def check(self) -> dict:
        return self.state()["check"]

    def events(self) -> list[dict]:
        return EventJournal(self.journal_path).after(0, 1000)  # read from disk


def up_and_silent(rig: Rig, mac: str = A) -> None:
    """`mac` watched at 15 minutes, heard at 12:04, its silence streak started at 12:30."""
    rig.watch(mac)
    rig.heard(mac, t(-1), t(-2))  # before the watch: never counts
    rig.run(t(0))
    rig.heard(mac, t(4), t(3))
    for minute in range(5, 31, 5):
        rig.run(t(minute))
    dev = rig.dev(mac)
    expect(
        (dev["state"], dev["silent_from"]) == ("up", iso(t(29.5))),
        f"setup: {mac} should be up with its streak from 12:29:30, got {dev}",
    )


# --- 1. every step row ------------------------------------------------------------------------


def dev_of(**change) -> dict:
    base = dict.fromkeys(rules.DEVICE_KEYS)
    return {
        **base,
        "enrolled_at": iso(t(0)),
        "after_min": 15,
        "state": "unknown",
        **change,
    }


def check_step_rows() -> None:
    now, cov = t(50), t(0)
    over = t(35) + timedelta(
        milliseconds=1
    )  # seen 12:10, 15 minutes + LOG_DELAY: 12:35
    expect(rules.LOG_DELAY == timedelta(minutes=10), f"LOG_DELAY is {rules.LOG_DELAY}")
    up = {"state": "up", "seen_at": iso(t(10)), "since": iso(t(5))}
    streak = {**up, "silent_from": iso(t(40))}
    gone = {
        "state": "down",
        "seen_at": iso(t(10)),
        "incident": {"seen_at": iso(t(10)), "declared_at": iso(t(44))},
    }
    carried = {"incident": {"seen_at": iso(t(-60)), "declared_at": iso(t(-30))}}
    back = {"state": "up", "since": iso(now), "incident": None}
    declared = {"seen_at": iso(t(10)), "declared_at": iso(now)}
    down = {
        "state": "down",
        "since": iso(now),
        "silent_from": None,
        "incident": declared,
    }
    # (row, device, seen_new, started_new, capture_at, the fields it changes, event type)
    rows = [
        ("unknown, started at enrolment", {}, t(1), t(0), t(2),
         {"state": "up", "seen_at": iso(t(1)), "since": iso(now)}, None),
        ("unknown, started before it", {}, t(1), t(-0.01), t(2), {}, None),
        ("unknown, nothing heard", {}, None, None, t(2), {}, None),
        ("unknown, a carried incident", carried, t(2), t(1), t(3),
         {**back, "seen_at": iso(t(2))}, rules.ONLINE),
        ("up, silence at the threshold", {**up, "silent_from": iso(t(20))}, None, None,
         t(35), {"silent_from": None}, None),
        ("up, 1 ms over it", up, None, None, over, {"silent_from": iso(over)}, None),
        ("up, a newer sighting", up, t(30), t(29), t(40), {"seen_at": iso(t(30))}, None),
        ("up, under 240 s of streak", streak, None, None, t(43.99), {}, None),
        ("up, a streak from before coverage", {**up, "silent_from": iso(t(-5))}, None,
         None, t(44), {"silent_from": iso(t(44))}, None),
        ("up, 240 s of streak", streak, None, None, t(44), down, rules.OFFLINE),
        ("down, a peer's late packet", gone, t(48), t(44), t(49), {}, None),
        ("down, nothing heard", gone, None, None, t(49), {}, None),
        ("down, a connection after it", gone, t(46), t(45), t(49),
         {**back, "seen_at": iso(t(46))}, rules.ONLINE),
    ]  # fmt: skip
    events = {}
    for label, change, seen, started, capture_at, moved, kind in rows:
        before = dev_of(**change)
        after, event = rules.step(before, seen, started, capture_at, cov, now)
        expect(
            after == {**before, **moved} and (event or {}).get("type") == kind,
            f"step row {label!r}: {after}, {event}",
        )
        events[label] = event
    expect(
        events["up, 240 s of streak"]
        == {
            "type": rules.OFFLINE,
            "instance": "down|" + iso(t(10)),
            "data": {"after_min": 15, "seen_at": iso(t(10))},
        },
        f"the offline event: {events['up, 240 s of streak']}",
    )
    for label, seen_at, back_at, away in (
        ("unknown, a carried incident", t(-60), t(1), 61),
        ("down, a connection after it", t(10), t(45), 35),
    ):
        event = events[label]
        expect(
            event["instance"] == "up|" + iso(seen_at)
            and event["data"]["back_at"] == iso(back_at)
            and event["data"]["away_min"] == away,
            f"the online event for {label!r}: {event}",
        )
    say(f"all {len(rows)} step rows, with the threshold and 240 s streak boundaries")


# --- 2. through the job: enrol, offline, a restart while down, back online --------------------


def check_lifecycle() -> None:
    rig = Rig("lifecycle")
    up_and_silent(rig)
    body = next(b for b in rig.index.calls if "sent" in b["aggs"])
    for side, field in (("sent", "source.mac"), ("answered", "destination.mac")):
        terms = body["aggs"][side]["aggs"]["macs"]["terms"]
        expect(
            terms == {"field": field, "size": 1, "include": [A.lower()]},
            f"the presence search's {side} terms: {terms}",
        )
    say("presence search: size and include on both sides, lower case")
    rig.run(t(30) + timedelta(seconds=20))  # a manual run seconds later
    expect(
        rig.dev(A)["state"] == "up" and not rig.events(), "a run seconds later declared"
    )
    rig.run(t(35))
    [offline] = rig.events()
    expect(
        (offline["type"], offline["key"], offline["observed_at"])
        == (rules.OFFLINE, A, iso(t(35)))
        and offline["data"]
        == {"mac": A, "name": "Kitchen plug", "after_min": 15, "seen_at": iso(t(4))},
        f"the offline entry: {offline}",
    )
    [row] = rig.job.view()["devices"]
    expect(
        (row["state"], row["seen_at"]) == ("down", iso(t(4))), f"the card's row: {row}"
    )
    say("enrolled at 12:00, up at 12:05, offline at 12:35 with the owner's name")
    rig.heard(A, t(38), t(3))  # a peer's late packet on an old connection
    rig.run(t(40))
    rig.restart()
    rig.run(t(45))
    expect(len(rig.events()) == 1 and rig.dev(A)["state"] == "down", "down didn't hold")
    rig.heard(A, t(47), t(46))
    rig.run(t(50))
    rig.run(t(55))
    events = rig.events()
    expect(len(events) == 2, f"{len(events)} entries after the recovery")
    online = events[1]
    expect(
        online["type"] == rules.ONLINE
        and online["id"] != offline["id"]
        and online["data"]["back_at"] == iso(t(46))
        and online["data"]["away_min"] == 42,
        f"the online entry: {online}",
    )
    say(
        "a late packet and a restart kept it down; back online at 12:46, 42 minutes away"
    )


# --- 3. the two-phase commit's crash cases -------------------------------------------------------


def check_crashes() -> None:
    for when in ("before", "after"):
        rig = Rig(f"crash-{when}")
        up_and_silent(rig)
        rig.journal.crash = when
        expect(
            rig.run(t(35)) == "crashed", f"the crash {when} the append didn't happen"
        )
        pending = rig.dev(A)["pending"]
        expect(
            pending is not None and pending["type"] == rules.OFFLINE,
            f"no pending: {pending}",
        )
        expect(len(rig.events()) == (when == "after"), f"journal after a crash {when}")
        rig.restart()
        rig.run(t(40))
        rig.run(t(45))
        events = rig.events()
        expect(
            len(events) == 1 and events[0]["observed_at"] == iso(t(35)),
            f"after a crash {when} the append: {events}",
        )
        expect(rig.dev(A)["pending"] is None, "the pending wasn't cleared")
        say(f"a crash {when} the append: the restart journals it exactly once")

    rig = Rig("crash-save")
    up_and_silent(rig)
    # patched where the job looks it up; if it moves out of watched_devices, this fails loudly

    def no_pending_save(path, text, **kwargs):
        if '"pending":{' in text:
            raise OSError(28, "No space left on device")
        return write_file_atomic(path, text, **kwargs)

    with patch.object(wd, "write_file_atomic", side_effect=no_pending_save):
        result = rig.run(t(35))
    expect(isinstance(result, OSError), f"a failed pending save didn't raise: {result}")
    expect(rig.check()["error"] == wd.ERR_SAVE, f"check: {rig.check()}")
    expect(
        rig.dev(A)["state"] == "up" and not rig.events(), "a failed save still declared"
    )
    first = None
    for minute in range(40, 121, 5):
        rig.run(t(minute))
        if rig.events() and first is None:
            first = minute
    expect(
        first == 75 and len(rig.events()) == 1, f"declared at {first}: {rig.events()}"
    )
    say(
        "a failed first save: nothing journalled, coverage restarted, declared once at 13:15"
    )


def check_old_pending() -> None:
    rig = Rig("old-pending")
    for mac in (A, B):
        rig.watch(mac)
    now = t(0)
    devices = {}
    for mac, age in ((A, 25), (B, 23)):
        seen = iso(now - timedelta(hours=age + 1))
        devices[mac] = dev_of(
            state="down",
            seen_at=seen,
            since=iso(now - timedelta(hours=age)),
            incident={"seen_at": seen, "declared_at": iso(now - timedelta(hours=age))},
            pending={
                "type": rules.OFFLINE,
                "key": mac,
                "instance": "down|" + seen,
                "observed_at": iso(now - timedelta(hours=age)),
                "data": {"mac": mac, "name": None, "after_min": 15, "seen_at": seen},
            },
        )
    os.makedirs(rig.dir, exist_ok=True)
    with open(rig.state_path, "w") as fh:
        json.dump(
            {"version": 1, "check": dict(rules.EMPTY_CHECK), "devices": devices}, fh
        )
    rig.run(now)
    keys = [e["key"] for e in rig.events()]
    expect(keys == [B], f"journalled {keys}, expected only the 23-hour-old pending")
    expect(
        all(rig.dev(m)["pending"] is None for m in (A, B)), "a pending wasn't cleared"
    )
    say("a pending 25 hours old is dropped, one 23 hours old is journalled")


# --- 4. skips -------------------------------------------------------------------------------------


def check_skips() -> None:
    rig = Rig("no-watches")
    expect(rig.outcome(t(0)) is None, "no watches")
    expect(
        not rig.index.calls and rig.check()["success_at"] == iso(t(0)),
        "no watches searched",
    )
    say("no watches: no search, a successful check")

    root = os.path.join(TMP, "store")
    os.makedirs(root)
    with open(os.path.join(root, "device_details.json"), "w") as fh:
        fh.write("{")
    rig = Rig("store")
    rig.details = DeviceDetailsStore(root=root)
    rig.restart()
    expect(rig.outcome(t(0)) == "store", f"a damaged store: {rig.check()}")
    say("a damaged details store: skipped store")

    healths = {
        "bridge": {**MIRROR, "mode": "bridge"},
        "promiscuous off": {**MIRROR, "promisc_enabled": False},
        "mirror down": {**MIRROR, "status": "down"},
        "gateway degraded": {**GATEWAY, "status": "degraded"},
        "gateway routing off": {**GATEWAY, "routing_active": False},
        "start-up stub": {"stub": True, "mode": "unknown", "status": "not_configured"},
        "health timeout": TimeoutError("no answer in 5 s"),
    }
    for label, health in healths.items():
        rig = Rig(f"mode-{label.replace(' ', '-')}")
        rig.watch(A)
        rig.health = health
        outcome = rig.outcome(t(0))
        check = rig.check()
        expect(
            outcome == "mode" and check["reason"] and not rig.index.calls,
            f"{label}: {outcome}, {check}",
        )
    expect(
        check["reason"] == wd.NO_HEALTH, f"a health timeout's reason: {check['reason']}"
    )
    say(f"skipped mode with a reason and no search: {', '.join(healths)}")

    rig = Rig("gateway")
    rig.watch(A)
    rig.health = dict(GATEWAY)
    expect(rig.outcome(t(0)) is None, f"gateway normal: {rig.check()}")
    say("DHCP gateway, normal with routing on: checked")

    rig = Rig("prune")
    for mac in (A, B):
        rig.watch(mac)
    rig.run(t(0))
    rig.watch(B, None)
    rig.watch(C)
    rig.health = {**MIRROR, "mode": "bridge"}
    rig.run(t(5))
    devices = rig.state()["devices"]
    expect(
        sorted(devices) == [A, C] and devices[C]["enrolled_at"] == iso(t(5)),
        f"{devices}",
    )
    say("a skip still prunes a removed watch and enrols a new one")

    for label, capture_at in (
        ("11 minutes old", t(-11)),
        ("none in the last hour", None),
    ):
        rig = Rig(f"pipeline-{label.split()[0]}")
        rig.watch(A)
        outcome = rig.outcome(t(0), capture_at)
        presence = [b for b in rig.index.calls if "sent" in b["aggs"]]
        expect(outcome == "pipeline" and not presence, f"{label}: {outcome}")
    say("a capture time 11 minutes old, or none: skipped pipeline, no presence search")

    rig = Rig("skip-streak")
    up_and_silent(rig)
    rig.health = {**MIRROR, "mode": "bridge"}
    rig.run(t(32))
    expect(
        rig.dev(A)["silent_from"] is None and rig.check()["coverage_since"] is None,
        "streak kept",
    )
    rig.health = dict(MIRROR)
    for minute in (35, 40):
        rig.run(t(minute))
    expect(rig.dev(A)["state"] == "up" and not rig.events(), "declared across a skip")
    say("a skip clears the streak and the coverage; no offline across it")


# --- 5. refused replies ----------------------------------------------------------------------------


def check_refused() -> None:
    faults = {
        ("presence", "timeout"): wd.ERR_SLOW,
        ("presence", "timed_out"): wd.ERR_SLOW,
        ("presence", "shard"): wd.ERR_SEARCH,
        ("presence", "zero"): wd.ERR_SEARCH,
        ("presence", "noaggs"): wd.ERR_SEARCH,
        ("capture", "shard"): wd.ERR_SEARCH,
    }
    for (which, how), error in faults.items():
        rig = Rig(f"refused-{which}-{how}")
        up_and_silent(rig)  # a reply read as "nothing heard" would declare it now
        before = rig.dev(A)
        rig.index.fault = (which, how)
        result = rig.run(t(35))
        check = rig.check()
        expect(isinstance(result, Exception), f"{which} {how}: not refused ({result})")
        expect(
            check["error"] == error and check["coverage_since"] is None,
            f"{which} {how}: {check}",
        )
        after = rig.dev(A)
        expect(
            after["state"] == "up"
            and after["seen_at"] == before["seen_at"]
            and not rig.events(),
            f"{which} {how} changed the device: {after}",
        )
        rig.index.fault = None
        expect(rig.outcome(t(40)) is None, f"{which} {how}: no recovery")
    say("refused, nothing changed: " + ", ".join(f"{w} {h}" for w, h in faults))


# --- 6. the coverage gap ------------------------------------------------------------------------------


def check_coverage_gap() -> None:
    for label in ("daemon down", "capture down"):
        rig = Rig(f"gap-{label.split()[0]}")
        rig.watch(A, 60)
        rig.heard(A, t(-1), t(-2))
        rig.run(t(0))
        rig.heard(A, t(4), t(3))
        rig.run(t(5))
        if label == "capture down":
            for minute in range(10, 126, 5):
                rig.run(t(minute), t(5))  # capture stuck at 12:05: skipped pipeline
        first = None
        for minute in range(130, 216, 5):
            rig.run(t(minute))
            if rig.events() and first is None:
                first = minute
        expect(first == 210, f"{label} 12:05-14:05: declared at minute {first}")
    say(
        "a 1-hour watch across 2 hours with the daemon or capture down: silence counted from the first check after, offline at 15:30"
    )


# --- 7. a threshold change and a clear during the search -----------------------------------------------


def check_watch_is() -> None:
    for label, minutes in (("a threshold change", 60), ("a clear", None)):
        rig = Rig(f"watch-is-{minutes}")
        up_and_silent(rig)
        rig.index.during_presence = lambda r=rig, m=minutes: r.watch(A, m)
        rig.run(t(35))
        rig.index.during_presence = None
        expect(
            not rig.events(),
            f"{label} during the search: the transition was journalled",
        )
        devices = rig.state()["devices"]
        expect(
            A in devices
            and devices[A]["state"] == "up"
            and devices[A]["pending"] is None,
            f"{label}: {devices.get(A)}",
        )
        rig.run(t(40))
        devices = rig.state()["devices"]
        if minutes is None:
            expect(A not in devices, "the cleared watch wasn't pruned")
        else:
            expect(
                devices[A]["after_min"] == 60
                and devices[A]["silent_from"] is None
                and not rig.events(),
                f"after the change: {devices[A]}",
            )
    say(
        "a threshold change or a clear during the search drops the transition (watch_is)"
    )


# --- 8. a capture scope reset with an open incident ---------------------------------------------------


def check_scope_reset() -> None:
    rig = Rig("scope")
    rig.watch(B)
    rig.active = {B}
    up_and_silent(rig)
    rig.run(t(35))
    expect(rig.dev(A)["state"] == "down" and rig.dev(B)["state"] == "up", "setup")
    rig.health = {**MIRROR, "capture_interface": "enp3s0"}
    rig.run(t(40))
    a, b = rig.dev(A), rig.dev(B)
    expect(
        a["state"] == b["state"] == "unknown"
        and a["incident"] is not None
        and a["enrolled_at"] == iso(t(40))
        and rig.check()["scope"] == "mirror|enp3s0",
        f"after the reset: {a}, {b}, {rig.check()}",
    )
    rig.heard(A, t(44), t(43))
    rig.run(t(45))
    events = rig.events()
    expect(
        [e["type"] for e in events] == [rules.OFFLINE, rules.ONLINE]
        and events[1]["key"] == A
        and events[1]["data"]["seen_at"] == iso(t(4)),
        f"after the first sighting: {events}",
    )
    expect(rig.dev(B)["state"] == "up", "B wasn't heard again after the reset")
    say(
        "a scope change re-baselines every watch; the carried incident's sighting journals online"
    )


# --- 9. the watch-only clear through the real route ----------------------------------------------------


class GoneRegistry:
    """A registry that no longer knows the device."""

    def get_device(self, _mac: str) -> None:
        return None

    def with_names(self, device: dict) -> dict:
        return device


async def _puts(app: web.Application, mac: str, bodies: list[dict]) -> list[tuple]:
    """Each body PUT in turn on one loopback server: (status, reply)."""
    replies = []
    async with TestClient(TestServer(app)) as client:
        for body in bodies:
            resp = await client.put(f"/api/devices/registry/{mac}/details", json=body)
            replies.append((resp.status, await resp.json()))
    return replies


def check_watch_only_clear() -> None:
    root = os.path.join(TMP, "route")
    details = DeviceDetailsStore(root=root)
    app = web.Application()
    register_device_custom_routes(
        app, DeviceCustomStore(root=root, details=details), details
    )
    app["device_registry"] = GoneRegistry()
    details.update(A, {"watch_after_min": 60, "group": "Kids"})
    others = [{"watch_after_min": 15}, {"watch_after_min": None, "group": None}]
    (status, reply), *refused = asyncio.run(
        _puts(app, A, [{"watch_after_min": None}, *others])
    )
    expect(
        status == 200 and reply["device"]["watch_after_min"] is None,
        f"{status} {reply}",
    )
    expect(details.export() == {A: {"group": "Kids"}}, f"left {details.export()}")
    for body, (status, _reply) in zip(others, refused):
        expect(status == 404, f"{body} for an unknown device answered {status}")
    say(
        "the watch-only clear frees an unknown device's watch and keeps its group; other bodies 404"
    )


def main() -> None:
    check_step_rows()
    check_lifecycle()
    check_crashes()
    check_old_pending()
    check_skips()
    check_refused()
    check_coverage_gap()
    check_watch_is()
    check_scope_reset()
    check_watch_only_clear()
    print("WATCHED-DEVICES-OK", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # the deploy script passes only on WATCHED-DEVICES-OK
        fail(f"{type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
