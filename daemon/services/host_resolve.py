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
# the host's: the daemon shares its network namespace
PROC_IPV6_CONF = "/proc/sys/net/ipv6/conf"
_IFACE = re.compile(r"[A-Za-z0-9_.\-]{1,15}")  # a Linux interface name; never a path
_DOTTED = re.compile(r"[0-9.]+")


class HostLookupError(Exception):
    """A name that did not resolve, or an address NetTap has no route to (a plain sentence)."""


class HostNameError(ValueError):
    """Input getent would misread, such as 192.168.001.010 (a plain sentence for a 400)."""


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


def check_name(name: str) -> str:
    """`name`, unless it is digits and dots but not an IP address.

    getent reads such input the inet_aton way: 192.168.001.010 is octal (192.168.1.8), 1234 is
    0.0.4.210. Raises HostNameError.
    """
    if _DOTTED.fullmatch(name) and _address(name) is None:
        raise HostNameError(f"{name} is not a valid IP address.")
    return name


async def resolve(name: str) -> list[str]:
    """Every address `name` resolves to, in the resolver's order; an IP literal is returned as is."""
    literal = _address(name)
    if literal:
        return [literal]
    check_name(name)
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


# OLD CODE START — review of #266/#267: sysfs only; the MTU now also reads /proc/sys/net/ipv6
# def _sysfs(dev: str, name: str) -> str:
#     try:
#         with open(os.path.join(SYS_NET, dev, name)) as f:
#             return f.read().strip()
#     except OSError:
#         return ""
# OLD CODE END
def _read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def _positive_int(text: str) -> int | None:
    return int(text) if text.isdigit() and int(text) > 0 else None


def _route_mtu(route: dict) -> int | None:
    """A route's own MTU (`ip route add … mtu N`), from `"metrics": [{"mtu": N}]`.

    A cached router report shows the same way but with "expires": that is NetTap's PMTU cache,
    which the MTU check reports as NetTap's own limit, so it is not the path's ceiling.
    """
    metrics = route.get("metrics")
    if "expires" in route or not isinstance(metrics, list) or not metrics:
        return None
    mtu = metrics[0].get("mtu") if isinstance(metrics[0], dict) else None
    return (
        mtu if isinstance(mtu, int) and not isinstance(mtu, bool) and mtu > 0 else None
    )


def _mtu(ip: str, dev: str, route: dict) -> int | None:
    """The smallest MTU that applies: the link's, IPv6's own for the link (a router's
    advertisement can lower it, e.g. 1492 behind PPPoE) and the route's."""
    known = [
        _positive_int(_read(os.path.join(SYS_NET, dev, "mtu"))),
        _positive_int(_read(os.path.join(PROC_IPV6_CONF, dev, "mtu")))
        if ":" in ip
        else None,
        _route_mtu(route),
    ]
    return min((m for m in known if m), default=None)


async def route_to(ip: str) -> dict:
    """The way out to `ip`: interface, source address, Wi-Fi or not, link speed and MTU.

    Speed and MTU are None when the system can't say (a down link reads -1).
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
        "speed_mbps": _positive_int(_read(os.path.join(SYS_NET, dev, "speed"))),
        # OLD CODE: "mtu": _positive_int(_sysfs(dev, "mtu")), (review: IPv6 and route MTUs)
        "mtu": _mtu(ip, dev, route),
    }
