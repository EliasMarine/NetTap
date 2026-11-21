"""Test rig for the watched-devices job (NET-331): a fake index that evaluates the job's real
query bodies over conn records, a clock, and real details, journal and state files."""

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from services.device_details import DeviceDetailsStore
from services.event_journal import EventJournal
from services.usage_days import parse_iso
from services.watched_devices import WatchedDevices

T0 = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
MAC_D = "AA:BB:CC:00:00:01"
MAC_E = "AA:BB:CC:00:00:02"
D, E = MAC_D.lower(), MAC_E.lower()
OTHER = "aa:bb:cc:00:00:99"  # unwatched: its records keep capture_at current
ROUTER = "aa:bb:cc:00:00:fe"

MIRROR = {
    "mode": "mirror",
    "status": "normal",
    "capture_interface": "enp1s0",
    "link_up": True,
    "promisc_enabled": True,
    "issues": [],
}
GATEWAY = {
    "mode": "dhcp_gateway",
    "status": "normal",
    "capture_interface": "enp2s0",
    "link_up": True,
    "promisc_enabled": True,
    "routing_active": True,
    "subnet": "10.77.0.0/24",
    "issues": [],
}


def at(hhmm: str, seconds: int = 0) -> datetime:
    hour, minute = map(int, hhmm.split(":"))
    return T0.replace(hour=hour, minute=minute, second=seconds)


def iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


# --- a tiny evaluator for the job's query bodies ----------------------------


def _bound(doc_value: Any, raw: Any) -> Any:
    return parse_iso(raw) if isinstance(doc_value, datetime) else raw


def matches(doc: dict, query: dict) -> bool:
    ((kind, spec),) = query.items()
    if kind == "bool":
        if not all(matches(doc, q) for q in spec.get("filter", [])):
            return False
        if any(matches(doc, q) for q in spec.get("must_not", [])):
            return False
        should = spec.get("should", [])
        need = spec.get("minimum_should_match", 0 if spec.get("filter") else 1)
        return not should or sum(matches(doc, q) for q in should) >= need
    ((field, value),) = spec.items()
    got = doc.get(field)
    if kind == "term":
        return got == value
    if kind == "terms":
        return got in value
    if kind == "range":
        if got is None:
            return False
        ops = {
            "gt": lambda a, b: a > b,
            "gte": lambda a, b: a >= b,
            "lt": lambda a, b: a < b,
            "lte": lambda a, b: a <= b,
        }
        return all(
            ops[op](got, _bound(got, raw)) for op, raw in value.items() if op in ops
        )
    raise AssertionError(f"unsupported query {kind}")


def aggregate(docs: list[dict], aggs: dict) -> dict:
    out = {}
    for name, spec in aggs.items():
        subs = spec.get("aggs", {})
        if "filter" in spec:
            chosen = [d for d in docs if matches(d, spec["filter"])]
            out[name] = {"doc_count": len(chosen), **aggregate(chosen, subs)}
        elif "max" in spec:
            values = [d[spec["max"]["field"]] for d in docs]
            out[name] = {
                "value": float(round(max(values).timestamp() * 1000))
                if values
                else None
            }
        elif "terms" in spec:
            terms, groups = spec["terms"], {}
            for d in docs:
                key = d.get(terms["field"])
                if key is not None and key in terms.get("include", [key]):
                    groups.setdefault(key, []).append(d)
            keys = sorted(groups, key=lambda k: -len(groups[k]))[: terms["size"]]
            out[name] = {
                "buckets": [
                    {
                        "key": k,
                        "doc_count": len(groups[k]),
                        **aggregate(groups[k], subs),
                    }
                    for k in keys
                ]
            }
        else:
            raise AssertionError(f"unsupported aggregation {spec}")
    return out


class FakeIndex:
    """client.search over in-memory conn records, each searchable from its `_visible` time."""

    def __init__(self, rig: "Rig") -> None:
        self.rig = rig
        self.docs: list[dict] = []
        self.calls: list[tuple[str, dict, float]] = []
        self.hook = None  # hook(body) runs before the reply is built
        self.patch = None  # patch(reply, body) -> reply

    def search(self, index: str, body: dict, request_timeout: float) -> dict:
        self.calls.append((index, body, request_timeout))
        if self.hook:
            self.hook(body)
        visible = [d for d in self.docs if d["_visible"] <= self.rig.clock]
        hits = [d for d in visible if matches(d, body["query"])]
        reply = {
            "timed_out": False,
            "_shards": {"total": 3, "successful": 3, "skipped": 0, "failed": 0},
            "hits": {"total": {"value": len(hits), "relation": "eq"}, "hits": []},
            "aggregations": aggregate(hits, body["aggs"]),
        }
        return self.patch(reply, body) if self.patch else reply


def is_presence(body: dict) -> bool:
    return "sent" in body["aggs"]


class Rig:
    def __init__(self, tmp_path) -> None:
        self.tmp = tmp_path
        self.clock = T0
        self.details = DeviceDetailsStore(str(tmp_path))
        self.journal = EventJournal(str(tmp_path / "events.jsonl"))
        self.index = FakeIndex(self)
        self.health: Any = dict(MIRROR)
        self.names: dict[str, str] = {}
        self.background = True
        self.watcher = self.new_watcher()

    @property
    def path(self):
        return self.tmp / "watched-devices.json"

    def new_watcher(self) -> WatchedDevices:
        return WatchedDevices(
            details=self.details,
            journal=self.journal,
            name_for=self.names.get,
            client=self.index,
            index="arkime_sessions3-*",
            capture_health=self.read_health,
            path=str(self.path),
            now=lambda: self.clock,
        )

    def read_health(self) -> dict:
        if isinstance(self.health, Exception):
            raise self.health
        return dict(self.health)

    def watch(self, mac: str = MAC_D, minutes: int | None = 15) -> None:
        self.details.update(mac, {"watch_after_min": minutes})

    def conn(
        self,
        src: str,
        dst: str,
        start: datetime,
        end: datetime | None = None,
        *,
        visible: datetime | None = None,
        replies: bool = True,
        state: str | None = None,
        file: str = "conn.log",
    ) -> None:
        end = end or start
        self.index.docs.append(
            {
                "event.dataset": "conn",
                "log.file.path": file,
                "source.mac": src,
                "destination.mac": dst,
                "@timestamp": start,
                "event.end": end,
                "destination.packets": 3 if replies else 0,
                "destination.bytes": 120 if replies else 0,
                "zeek.conn.conn_state": state or ("SF" if replies else "S0"),
                "_visible": visible or end,
            }
        )

    def check(self, t: datetime) -> None:
        self.clock = t
        if self.background:
            self.conn(OTHER, ROUTER, t - timedelta(seconds=30), visible=t)
        self.watcher.run(time.monotonic() + 60)

    def checks(self, start: datetime, end: datetime, every_min: int = 5) -> None:
        t = start
        while t <= end:
            self.check(t)
            t += timedelta(minutes=every_min)

    def state(self) -> dict:
        return json.loads(self.path.read_text())

    def dev(self, mac: str = MAC_D) -> dict:
        return self.state()["devices"][mac]

    def events(self) -> list[dict]:
        return self.journal.after(0, 1000)

    def bring_up(self) -> None:
        """D watched at 15 minutes, enrolled at 12:00, up at 12:05, last seen 12:02."""
        self.watch()
        self.check(at("12:00"))
        self.conn(D, ROUTER, at("12:01"), at("12:02"))
        self.check(at("12:05"))
        assert self.dev()["state"] == "up"

    def bring_down(self) -> None:
        """bring_up, then silent: silent_from at 12:30, declared down at 12:35."""
        self.bring_up()
        self.checks(at("12:10"), at("12:35"))
        assert self.dev()["state"] == "down"
