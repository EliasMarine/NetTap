"""
NetTap path MTU check (NET-267)

Finds the largest packet that reaches a target from NetTap, with "don't fragment" pings.
Sizes are IP packet sizes (ping's -s payload + 28 bytes for IPv4, + 48 for IPv6).

The daemon's ping (iputils 20221126, Debian bookworm) has no `-M probe`, so probes use `-M do`.
With it the kernel refuses to send a probe above a limit it already holds for the path (an earlier
router report or a route MTU): ping prints "local error: message too long, mtu=N". That is
NetTap's own limit, recorded as `local_error` and never presented as a router report.

Silence never makes the upper limit known: it is known only when the interface MTU itself got a
reply, or a router reported an MTU that the probes then confirmed.

Security:
    - The target is validated (NetworkDiagService.validate_target) and resolved in a killable
      child; ping gets the IP literal as its last argument
    - Two checks at a time, refused (never queued) beyond that
    - One 25 s deadline and at most 16 probed sizes per check
"""

import asyncio
import ipaddress
import logging
import re
import time
from typing import Any

from services.host_resolve import (
    HostLookupError,
    check_name,
    resolve,
    route_to,
    run,
)
from services.network_diag_service import NetworkDiagService

logger = logging.getLogger("nettap.path_mtu")

MAX_CONCURRENT = 2
BUSY = "Two MTU checks are already running. Try again in a moment."
DEADLINE = 25  # seconds: resolution, route lookup and every probe
MAX_PROBES = 16
MAX_IP_SIZE = 65535  # the largest IP packet ping can build
OVERHEAD = {4: 28, 6: 48}  # IP + ICMP headers
# every IPv4 host must take 576 bytes; every IPv6 link carries 1280
FLOOR = {4: 576, 6: 1280}
SMALL = {4: 84, 6: 104}  # ping's default 56-byte payload
TRIES = 2  # a size counts as unanswered after this many pings without a reply

_REPLY = re.compile(r"^\d+ bytes from ", re.M)
# exact iputils 20221126 wording: ping.c pr_icmph, ping6_common.c print_icmp
_TOO_BIG = re.compile(
    r"Frag needed and DF set \(mtu = (\d+)\)|Packet too big: mtu=(\d+)"
)
_LOCAL_MTU = re.compile(r"local error: message too long, mtu[=:] ?(\d+)")
_PING_ERROR = re.compile(r"^ping: (.+)$", re.M)


class PathMtuValidationError(Exception):
    """Bad input (a plain sentence for a 400)."""


class PathMtuBusyError(Exception):
    """MAX_CONCURRENT checks are already running."""


class _Stopped(Exception):
    """The probe cap was reached."""


def parse_probe(stdout: str, stderr: str) -> dict[str, Any]:
    """One `ping -c 1` run as {result, mtu}: reply, icmp_too_big, local_error or no_reply."""
    if _REPLY.search(stdout):
        return {"result": "reply", "mtu": None}
    text = stdout + "\n" + stderr
    too_big = _TOO_BIG.search(text)
    if too_big:
        return {
            "result": "icmp_too_big",
            "mtu": int(too_big.group(1) or too_big.group(2)),
        }
    local = _LOCAL_MTU.search(text)
    if local:
        return {"result": "local_error", "mtu": int(local.group(1))}
    if _PING_ERROR.search(stderr):
        return {"result": "local_error", "mtu": None}
    return {"result": "no_reply", "mtu": None}


class _Check:
    """One check's probes and what they showed; it outlives a cancelled search (the deadline)."""

    def __init__(self, ip: str, family: int, ceiling: int) -> None:
        self.ip, self.family, self.ceiling = ip, family, ceiling
        self.probes: list[dict[str, Any]] = []
        self.confirmed: int | None = None
        self.icmp_mtu: int | None = None
        self.icmp_contradicted = False
        self.local_mtu: int | None = None
        self.first_unanswered: int | None = None
        self.ping_error: str | None = None

    async def _ping(self, size: int) -> dict[str, Any]:
        payload = size - OVERHEAD[self.family]
        _, out, err = await run(
            "ping",
            f"-{self.family}",
            "-M",
            "do",
            "-c",
            "1",
            "-W",
            "1",
            "-s",
            str(payload),
            self.ip,
        )
        probe = parse_probe(out, err)
        if probe["result"] == "local_error" and probe["mtu"] is None:
            # parse_probe matched it
            self.ping_error = _PING_ERROR.search(err).group(1)
        return probe

    async def tried(self, size: int) -> dict[str, Any]:
        """A size's outcome, one probe: a no_reply is pinged again before it counts."""
        # counted per size, not per ping: a silent size costs two 1 s pings,
        # and DEADLINE still bounds them
        if len(self.probes) >= MAX_PROBES:
            raise _Stopped
        for _ in range(TRIES):
            probe = await self._ping(size)
            if probe["result"] != "no_reply":
                break
        self.probes.append({"size": size, **probe})
        if probe["result"] == "reply":
            self.confirmed = max(self.confirmed or 0, size)
        elif probe["result"] == "no_reply":
            self.first_unanswered = min(self.first_unanswered or size, size)
        return probe

    def _limit(self, probe: dict[str, Any], size: int) -> int | None:
        """The MTU a failed probe names, when it is below the size that failed."""
        mtu = probe["mtu"]
        if mtu is None or not 68 <= mtu < size:
            return None
        if probe["result"] == "icmp_too_big":
            self.icmp_mtu = mtu
            # a reply above the reported MTU contradicts it
            self.icmp_contradicted |= (self.confirmed or 0) > mtu
        else:
            self.local_mtu = mtu
        return mtu

    async def search(self) -> str:
        """The plan's algorithm (PLAN.md section 6); returns the status."""
        if (await self.tried(SMALL[self.family]))["result"] != "reply":
            return "ping_error" if self.ping_error else "no_ping_reply"
        floor = min(FLOOR[self.family], self.ceiling)
        if (await self.tried(floor))["result"] != "reply":
            return "floor_unanswered"
        low, high, next_size = floor, self.ceiling + 1, self.ceiling
        while high - low > 1:
            size = (
                next_size if next_size and low < next_size < high else (low + high) // 2
            )
            probe = await self.tried(size)
            next_size = None
            if probe["result"] == "reply":
                low = size
                continue
            high = size
            limit = self._limit(probe, size)
            if limit is not None and limit >= low:
                # with DF set the kernel now holds this limit, so every size above
                # it fails locally; a limit equal to a size that replied ends the search
                next_size, high = limit, min(high, limit + 1)
        if (await self.tried(self.confirmed))["result"] != "reply":
            return "unreliable"
        if self.confirmed == self.ceiling:
            return "interface"
        if self.icmp_mtu == self.confirmed and not self.icmp_contradicted:
            return "icmp_bound"
        # OLD CODE: if self.local_mtu == self.confirmed: return "local_limit" (lead
        # review: it covers every run whose failures above the confirmed size were local)
        above = [p for p in self.probes if p["size"] > self.confirmed]
        # NetTap refused to send them all: the path above was never tested
        if above and all(p["result"] == "local_error" for p in above):
            return "local_limit"
        return "unanswered_above"


class PathMtuService:
    """Runs path MTU checks, two at a time."""

    def __init__(self) -> None:
        # Rejects instead of queueing: a wait would count against the web's limit
        self._slots = asyncio.Semaphore(MAX_CONCURRENT)
        self._diag = NetworkDiagService()

    async def check(self, target: Any) -> dict[str, Any]:
        """Returns {target, resolved_ip, family, interface, interface_mtu, largest_confirmed,
        payload, upper_known, icmp_reported_mtu, local_mtu, first_unanswered, probes, status,
        error}. Raises PathMtuValidationError (or NetworkDiagValidationError) on bad input and
        PathMtuBusyError when two checks are running."""
        if not isinstance(target, str):
            raise PathMtuValidationError("Enter a host name or IP address.")
        target = check_name(self._diag.validate_target(target))
        if self._slots.locked():  # checked first, so acquiring below never waits
            raise PathMtuBusyError(BUSY)
        async with self._slots:
            started = time.monotonic()
            result = await self._check(target)
            log = (
                logger.warning
                if result["error"] or result["status"] == "stopped"
                else logger.info
            )
            log(
                "mtu %r -> %s, largest %s, upper known %s, %d probes in %.1f s",
                target,
                result["error"] or result["status"],
                result["largest_confirmed"],
                result["upper_known"],
                len(result["probes"]),
                time.monotonic() - started,
            )
            return result

    async def _check(self, target: str) -> dict[str, Any]:
        base = {
            "target": target,
            "resolved_ip": None,
            "family": None,
            "interface": None,
            "interface_mtu": None,
            "largest_confirmed": None,
            "payload": None,
            "upper_known": False,
            "icmp_reported_mtu": None,
            "local_mtu": None,
            "first_unanswered": None,
            "probes": [],
            "status": None,
            "error": None,
        }
        check = None
        try:
            async with asyncio.timeout(DEADLINE):
                ip = (await resolve(target))[0]
                path = await route_to(ip)
                family = ipaddress.ip_address(ip).version
                # shortcut: 1500 when sysfs can't give the MTU; read the route's
                # own mtu if that ever happens
                ceiling = min(path["mtu"] or 1500, MAX_IP_SIZE)
                base = {
                    **base,
                    "resolved_ip": ip,
                    "family": family,
                    "interface": path["interface"],
                    "interface_mtu": path["mtu"],
                }
                check = _Check(ip, family, ceiling)
                status = await check.search()
        except HostLookupError as exc:
            return {**base, "error": str(exc)}
        except (TimeoutError, _Stopped):
            status = "stopped"
        except OSError as exc:  # a missing binary
            # OLD CODE: return {**base, "error": f"NetTap could not run the check: {exc}"}
            logger.warning("mtu %r: could not start: %r", target, exc)
            reason = exc.strerror or "it failed to start"
            return {**base, "error": f"NetTap could not run the check ({reason})."}
        if check is None:  # the deadline ran out while resolving
            return {**base, "status": "stopped"}
        return self._result(base, check, status)

    @staticmethod
    def _result(base: dict[str, Any], check: _Check, status: str) -> dict[str, Any]:
        confirmed = (
            # OLD CODE: None if status in ("no_ping_reply", "ping_error") else check.confirmed
            # an unreliable run confirmed nothing either (review of #267)
            None
            if status in ("no_ping_reply", "ping_error", "unreliable")
            else check.confirmed
        )
        return {
            **base,
            "largest_confirmed": confirmed,
            "payload": confirmed - OVERHEAD[check.family] if confirmed else None,
            "upper_known": status in ("interface", "icmp_bound"),
            "icmp_reported_mtu": check.icmp_mtu,
            "local_mtu": check.local_mtu,
            "first_unanswered": check.first_unanswered,
            # [{size, result, mtu}]: mtu is the limit a failed probe named
            "probes": check.probes,
            "status": status,
            "error": check.ping_error if status == "ping_error" else None,
        }
