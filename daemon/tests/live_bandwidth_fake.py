"""NET-205 test helpers: an in-memory tc / ethtool, a hand-driven clock and a capture manager."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from services.capture_manager import CaptureMode
from services.live_bandwidth_tc import TcError


class Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t


@dataclass
class Manager:
    mode: CaptureMode = CaptureMode.MIRROR
    iface: str = "enp4s0"

    def get_capture_interface(self) -> str:
        return self.iface


class FakeTc:
    """Keeps qdiscs and filters per interface and answers the meter's tc / ethtool calls.

    Dumps come out in the real ``tc -s -j filter show`` shape (see fixtures/tc_filter_show_g11.json).
    A batch is applied line by line, like tc, so a failing line leaves the earlier ones in place.
    """

    def __init__(self, clock: Clock, ifaces=("enp4s0",)) -> None:
        self.clock = clock
        self.qdiscs: dict[str, set[str]] = {i: set() for i in ifaces}
        self.filters: dict[str, dict[tuple[int, int], dict]] = {i: {} for i in ifaces}
        self.ethtool = (
            "generic-receive-offload: off\nlarge-receive-offload: off [fixed]\n"
        )
        self.calls: list[tuple[tuple[str, ...], str | None]] = []
        self.dump_cost = 0.0  # clock seconds every dump takes
        self.call_cost: dict[str, float] = {}  # verb -> clock seconds
        self.add_lines_before_failing: int | None = None
        self.gate: asyncio.Event | None = None  # a delete batch waits for it
        self.at_gate = asyncio.Event()
        self._fail: dict[str, list] = {}

    # ---------------------------------------------------------------- test controls

    def fail(self, verb: str, nth: int = 1, msg: str = "boom") -> None:
        """Make the nth next call of a verb fail."""
        self._fail[verb] = [nth, msg]

    def add_foreign(self, iface: str, pref: int = 1, handle: int = 1) -> None:
        self.qdiscs[iface].add("clsact")
        self.filters[iface][(pref, handle)] = {
            "protocol": "all", "cookie": None, "bytes": 0, "packets": 0,
        }  # fmt: skip

    def bump(self, iface: str, pref: int, handle: int, nbytes: int) -> None:
        entry = self.filters[iface][(pref, handle)]
        entry["bytes"] += nbytes
        entry["packets"] += 1

    def owned(self, iface: str = "enp4s0") -> dict[tuple[int, int], dict]:
        return {k: v for k, v in self.filters[iface].items() if v["cookie"]}

    def verbs(self) -> list[str]:
        return [self._verb(argv, stdin) for argv, stdin in self.calls]

    # ---------------------------------------------------------------- the fake tool

    async def run(self, argv, timeout, stdin=None) -> str:
        if timeout <= 0:
            raise TcError(f"{argv[0]}: no time left")
        verb = self._verb(argv, stdin)
        self.calls.append((tuple(argv), stdin))
        self.clock.t += self.call_cost.get(verb, 0.0) + (
            self.dump_cost if verb == "dump" else 0
        )
        pending = self._fail.get(verb)
        if pending:
            pending[0] -= 1
            if pending[0] == 0:
                del self._fail[verb]
                raise TcError(pending[1])
        if verb == "del-batch" and self.gate is not None:
            self.at_gate.set()
            await self.gate.wait()
        return getattr(self, "_" + verb.replace("-", "_"))(argv, stdin)

    @staticmethod
    def _verb(argv, stdin) -> str:
        argv = list(argv)
        if argv[0] == "ethtool":
            return "ethtool"
        if argv[1:3] == ["-j", "qdisc"]:
            return "qdisc-show"
        if argv[1:3] == ["qdisc", "add"]:
            return "qdisc-add"
        if "filter" in argv and "show" in argv:
            return "dump"
        if argv[1:] == ["-batch", "-"]:
            return "del-batch" if " del " in (stdin or "") else "add-batch"
        raise AssertionError(f"unexpected command {argv}")

    def _ethtool(self, argv, stdin) -> str:
        return self.ethtool

    def _qdisc_show(self, argv, stdin) -> str:
        return json.dumps([{"kind": k} for k in sorted(self.qdiscs[argv[-1]])])

    def _qdisc_add(self, argv, stdin) -> str:
        self.qdiscs[argv[4]].add(argv[5])
        return ""

    def _dump(self, argv, stdin) -> str:
        iface = argv[6]
        out = []
        for pref in sorted({p for p, _ in self.filters[iface]}):
            rows = sorted(
                (h, f) for (p, h), f in self.filters[iface].items() if p == pref
            )
            out.append(
                {"protocol": rows[0][1]["protocol"], "pref": pref, "kind": "flower"}
            )
            for handle, f in rows:
                action = {
                    "order": 1,
                    "kind": "gact",
                    "control_action": {"type": "continue"},
                    "stats": {"bytes": f["bytes"], "packets": f["packets"]},
                }
                if f["cookie"]:
                    action["cookie"] = f["cookie"]
                out.append({
                    "protocol": f["protocol"], "pref": pref, "kind": "flower",
                    "options": {"handle": handle, "skip_hw": True, "actions": [action]},
                })  # fmt: skip
        return json.dumps(out)

    def _add_batch(self, argv, stdin) -> str:
        for n, line in enumerate(stdin.splitlines()):
            if n == self.add_lines_before_failing:
                raise TcError("RTNETLINK answers: Invalid argument")
            words = line.split()
            assert words[:2] == ["filter", "add"] and "continue" in words, line
            iface, pref, handle = (
                words[3],
                int(self._after(words, "pref")),
                int(self._after(words, "handle")),
            )
            if (pref, handle) in self.filters[iface] or "clsact" not in self.qdiscs[
                iface
            ]:
                raise TcError("RTNETLINK answers: File exists")
            self.filters[iface][(pref, handle)] = {
                "protocol": self._after(words, "protocol"),
                "cookie": words[-1],
                "bytes": 0,
                "packets": 0,
            }
        return ""

    def _del_batch(self, argv, stdin) -> str:
        for line in stdin.splitlines():
            words = line.split()
            iface, pref, handle = (
                words[3],
                int(self._after(words, "pref")),
                int(self._after(words, "handle")),
            )
            entry = self.filters[iface].get((pref, handle))
            if entry is None or entry["protocol"] != self._after(words, "protocol"):
                raise TcError("RTNETLINK answers: No such file or directory")
            del self.filters[iface][(pref, handle)]
        return ""

    @staticmethod
    def _after(words: list[str], word: str) -> str:
        return words[words.index(word) + 1]
