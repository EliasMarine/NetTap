"""
tc building blocks for the live bandwidth meter (NET-205): filter lines, the counter dump parser,
ownership by cookie, and one deadline-bound runner for tc / ethtool.

The meter counts a device's bytes with flower filters on the capture interface's ingress hook
(clsact). Every NetTap filter:
  - sits in one of six shared prefs (kind x direction x encapsulation), so a packet costs at most
    six hash lookups however many devices are watched;
  - uses ``action continue``: a terminal action (``pass``) would end classification and every later
    filter would count nothing;
  - carries a cookie: an 8-byte NetTap prefix, the slot and the generation. Only filters whose
    cookie carries the prefix are ever deleted, and only by exact pref, protocol and handle.

Pure functions here are shared with scripts/remote/verify-live-bandwidth.py, which checks the same
lines against a real kernel on a throwaway veth pair.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from dataclasses import dataclass

# "NETTAPBM" in hex: marks every NetTap action
COOKIE_PREFIX = "4e4554544150424d"
COOKIE_RE = re.compile(r"^4e4554544150424d([0-9a-f]{2})([0-9a-f]{14})$")

# (kind, direction) -> (pref, protocol token as tc prints it)
PREFS: dict[tuple[str, str], tuple[int, str]] = {
    ("mac", "down"): (49152, "all"),
    ("mac", "up"): (49153, "all"),
    ("ip", "down"): (49154, "ip"),
    ("ip", "up"): (49155, "ip"),
    ("vlan", "down"): (49156, "802.1Q"),
    ("vlan", "up"): (49157, "802.1Q"),
}
OWNED_PREFS = {pref: proto for pref, proto in PREFS.values()}

# Which filters make up one watch's download and upload counters
COUNTERS: dict[str, dict[str, tuple[tuple[str, str], ...]]] = {
    "mac": {"down": (("mac", "down"),), "up": (("mac", "up"),)},
    "ip": {
        "down": (("ip", "down"), ("vlan", "down")),
        "up": (("ip", "up"), ("vlan", "up")),
    },
}


class TcError(Exception):
    """tc (or ethtool) failed, timed out or printed something we can't read."""


@dataclass(frozen=True)
class Key:
    """What one watch counts: a device's MAC (lower case) or an IPv4 address."""

    kind: str  # "mac" | "ip"
    value: str

    def as_dict(self) -> dict:
        return {"kind": self.kind, "value": self.value}


@dataclass(frozen=True)
class FilterEntry:
    """One filter from ``tc -s -j filter show``; bytes/packets are None when stats are missing."""

    pref: int
    protocol: str
    handle: int
    cookie: str | None
    bytes: int | None
    packets: int | None


def cookie_for(slot: int, gen: int) -> str:
    """The 16-byte cookie for a slot and generation: prefix, slot (1 byte), generation (7 bytes)."""
    return f"{COOKIE_PREFIX}{slot:02x}{gen & ((1 << 56) - 1):014x}"


def parse_cookie(cookie: str | None) -> tuple[int, int] | None:
    """(slot, generation) for a NetTap cookie, else None."""
    if not isinstance(cookie, str):
        return None
    match = COOKIE_RE.match(cookie.lower())
    return (int(match.group(1), 16), int(match.group(2), 16)) if match else None


def handle_for(slot: int) -> int:
    """One handle per slot in every shared pref (1-based: handle 0 means 'pick one')."""
    return slot + 1


def build_filter_lines(iface: str, key: Key, slot: int, gen: int) -> list[str]:
    """``tc -batch`` lines that add one watch's filters. Values must already be validated."""
    handle, cookie = handle_for(slot), cookie_for(slot, gen)
    tail = f"action continue cookie {cookie}"

    def line(part: tuple[str, str], match: str) -> str:
        pref, proto = PREFS[part]
        return (
            f"filter add dev {iface} ingress pref {pref} protocol {proto} "
            f"handle {handle} flower skip_hw {match} {tail}"
        )

    if key.kind == "mac":
        return [
            line(("mac", "down"), f"dst_mac {key.value}"),
            line(("mac", "up"), f"src_mac {key.value}"),
        ]
    return [
        line(("ip", "down"), f"dst_ip {key.value}"),
        line(("ip", "up"), f"src_ip {key.value}"),
        line(("vlan", "down"), f"vlan_ethtype ip dst_ip {key.value}"),
        line(("vlan", "up"), f"vlan_ethtype ip src_ip {key.value}"),
    ]


def delete_args(iface: str, pref: int, handle: int) -> list[str]:
    """argv deleting exactly one owned filter (pref and protocol come from our own table)."""
    return [
        "filter", "del", "dev", iface, "ingress",
        "pref", str(pref), "protocol", OWNED_PREFS[pref],
        "handle", str(handle), "flower",
    ]  # fmt: skip


def parse_filter_dump(text: str) -> list[FilterEntry]:
    """Every filter (with options) in a ``tc -s -j filter show`` dump."""
    try:
        data = json.loads(text or "[]")
    except json.JSONDecodeError as exc:
        raise TcError(f"tc printed a filter list we can't read: {exc}") from exc
    if not isinstance(data, list):
        raise TcError("tc printed a filter list we can't read")
    return [
        _entry(item) for item in data if isinstance(item, dict) and "options" in item
    ]


def _entry(item: dict) -> FilterEntry:
    options = item.get("options") or {}
    actions = options.get("actions") or [{}]
    action = actions[0] if isinstance(actions[0], dict) else {}
    stats = action.get("stats") or {}
    count = stats.get("bytes"), stats.get("packets")
    try:
        pref, handle = int(item.get("pref")), int(options.get("handle", 0))
    except (TypeError, ValueError) as exc:
        raise TcError("tc printed a filter we can't read") from exc
    return FilterEntry(
        pref=pref,
        protocol=str(item.get("protocol", "")),
        handle=handle,
        cookie=action.get("cookie"),
        bytes=count[0] if isinstance(count[0], int) else None,
        packets=count[1] if isinstance(count[1], int) else None,
    )


def foreign_filters(entries: list[FilterEntry]) -> list[FilterEntry]:
    """Filters NetTap doesn't own: no NetTap cookie, or a NetTap cookie outside our prefs."""
    return [
        e
        for e in entries
        if parse_cookie(e.cookie) is None or e.pref not in OWNED_PREFS
    ]


def has_ingress_qdisc(text: str) -> tuple[bool, bool]:
    """(clsact present, plain ingress qdisc present) from ``tc -j qdisc show``."""
    try:
        kinds = {q.get("kind") for q in json.loads(text or "[]") if isinstance(q, dict)}
    except (json.JSONDecodeError, AttributeError, TypeError) as exc:
        raise TcError("tc printed a qdisc list we can't read") from exc
    return "clsact" in kinds, "ingress" in kinds


def parse_offloads(text: str) -> dict[str, bool | None]:
    """GRO and LRO state from ``ethtool -k``; None when the line is missing."""
    found: dict[str, bool | None] = {"gro": None, "lro": None}
    names = {"generic-receive-offload": "gro", "large-receive-offload": "lro"}
    for line in (text or "").splitlines():
        name, _, value = line.partition(":")
        if name.strip() in names:
            found[names[name.strip()]] = value.strip().startswith("on")
    return found


async def run_tool(argv: list[str], timeout: float, stdin: str | None = None) -> str:
    """Run one command with a hard deadline and return its stdout.

    The child is killed and reaped on a timeout, an error or a cancellation (NET-203 pattern).
    """
    if timeout <= 0:
        raise TcError(f"{argv[0]}: no time left")
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        data = stdin.encode() if stdin is not None else None
        out, err = await asyncio.wait_for(proc.communicate(data), timeout=timeout)
        if proc.returncode != 0:
            reason = err.decode("utf-8", errors="replace").strip().splitlines()
            raise TcError(
                f"{argv[0]} failed: {reason[0] if reason else proc.returncode}"
            )
        return out.decode("utf-8", errors="replace")
    except asyncio.TimeoutError as exc:
        raise TcError(f"{argv[0]} took longer than {timeout:.1f} s") from exc
    except OSError as exc:
        raise TcError(f"{argv[0]} could not run: {exc}") from exc
    finally:
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
