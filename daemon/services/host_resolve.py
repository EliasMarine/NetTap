"""
Killable name resolution and route lookup for the tool subprocesses (NET-266, NET-267).

Names are resolved by a `getent ahosts` child that is killed on time-out, never in the default
executor: a stalled resolver there would pile up threads and delay the drill-down workers that
share it. The LAN throughput test and the path MTU check add this identical file.
"""

import asyncio
import contextlib
import ipaddress
import json
import os
import re

from services.loss_window import SYS_NET

RESOLVE_TIMEOUT = 3  # seconds
_IFACE = re.compile(r"[A-Za-z0-9_.\-]{1,15}")  # a Linux interface name; never a path


class HostLookupError(Exception):
    """A name that did not resolve, or an address NetTap has no route to (a plain sentence)."""


async def run(*argv: str) -> tuple[int, str, str]:
    """Run a fixed binary with an argv list; a child still running when this ends is killed and reaped."""
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await proc.communicate()
        return (
            proc.returncode,
            out.decode("utf-8", errors="replace"),
            err.decode("utf-8", errors="replace"),
        )
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()


def _address(text: str) -> str | None:
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return None


async def resolve(name: str) -> list[str]:
    """Every address `name` resolves to, in the resolver's order; an IP literal is returned as is."""
    literal = _address(name)
    if literal:
        return [literal]
    try:
        async with asyncio.timeout(RESOLVE_TIMEOUT):
            code, out, _ = await run("getent", "ahosts", "--", name)
    except TimeoutError:
        raise HostLookupError(f"Looking up {name} took too long.") from None
    # getent prints each address three times (STREAM, DGRAM, RAW); keep the first of each
    found = (_address(line.split()[0]) for line in out.splitlines() if line.strip())
    addresses = list(dict.fromkeys(a for a in found if a))
    if code != 0 or not addresses:
        raise HostLookupError(f"{name} could not be found.")
    return addresses


def _sysfs(dev: str, name: str) -> str:
    try:
        with open(os.path.join(SYS_NET, dev, name)) as f:
            return f.read().strip()
    except OSError:
        return ""


def _positive_int(text: str) -> int | None:
    return int(text) if text.isdigit() and int(text) > 0 else None


async def route_to(ip: str) -> dict:
    """The way out to `ip`: interface, source address, Wi-Fi or not, link speed and MTU.

    Speed and MTU are None when sysfs can't say (a down link reads -1).
    """
    code, out, _ = await run("ip", "-j", "route", "get", ip)
    try:
        route = json.loads(out)[0] if code == 0 else {}
    except (ValueError, IndexError, KeyError):
        route = {}
    dev = route.get("dev") if isinstance(route, dict) else None
    if not isinstance(dev, str) or not _IFACE.fullmatch(dev) or dev in (".", ".."):
        raise HostLookupError(f"NetTap has no route to {ip}.")
    return {
        "interface": dev,
        "source_ip": _address(str(route.get("prefsrc", ""))),
        "wifi": any(
            os.path.exists(os.path.join(SYS_NET, dev, d))
            for d in ("wireless", "phy80211")
        ),
        "speed_mbps": _positive_int(_sysfs(dev, "speed")),
        "mtu": _positive_int(_sysfs(dev, "mtu")),
    }
