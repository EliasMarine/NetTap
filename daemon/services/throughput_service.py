"""
NetTap LAN throughput test (NET-266)

One iperf3 run, in one direction, from NetTap to a peer on the local network. The web runs
upload, then download, so each request stays short and the first result shows while the
second runs.

Security:
    - The host is validated (NetworkDiagService.validate_target) and resolved in a killable
      child; only private, CGNAT/VPN and ULA addresses are tested, and iperf3 gets the IP literal
    - iperf3 runs as an unused uid with no capabilities and a 256 MB memory cap (SANDBOX)
    - One test at a time: a second is refused, never queued
    - One deadline (duration + 20 s) covers resolution, route lookup, iperf3 and clean-up
"""

import asyncio
import ipaddress
import json
import logging
import socket
import time
from typing import Any

import psutil

from services.host_resolve import (
    HostLookupError,
    check_name,
    resolve,
    route_to,
    run,
)
from services.network_diag_service import NetworkDiagService

logger = logging.getLogger("nettap.throughput")

DEFAULT_PORT = 5201
DEFAULT_DURATION = 10
MAX_DURATION = 30
# seconds on top of the test: resolution, route lookup, connect, clean-up
DEADLINE_SLACK = 20
# a wrong address fails in 3 s, not at the end of the deadline
CONNECT_TIMEOUT_MS = 3000
DIRECTIONS = ("upload", "download")
BUSY = "A throughput test is already running."
# OLD CODE START — review of #266: range names (CGNAT, ULA, link-local) the page never uses
# NOT_LOCAL = (
#     "The LAN throughput test only runs against local addresses: "
#     "private, CGNAT/VPN or ULA ranges."
# )
# LINK_LOCAL = (
#     "The LAN throughput test can't use link-local addresses. "
#     "Use the peer's IPv4 or ULA address."
# )
# OLD CODE END
NOT_LOCAL = (
    "The LAN throughput test only runs against a device on your own network "
    "or VPN (a private address)."
)
LINK_LOCAL = (
    "The LAN throughput test can't use a self-assigned address "
    "(169.254.x.x or fe80::…). Use the device's usual private address."
)
TOO_LONG = "The test took too long and was stopped."
NO_IPERF3 = "iperf3 is not installed in NetTap's daemon image."
# iperf3 3.12 (bookworm) parses the peer's data with CVE-2026-71218 and CVE-2026-71217 open, so
# it runs as uid 64000 (unused here and on the host; 65534 is dnsmasq's under pid: host), with no
# capabilities, no new privileges and a 256 MB address-space cap. setpriv is in the image; prlimit
# isn't, so sh's ulimit sets the cap before exec.
SANDBOX = (
    "setpriv",
    "--reuid=64000",
    "--regid=64000",
    "--clear-groups",
    "--no-new-privs",
    "--inh-caps=-all",
    "sh",
    "-c",
    'ulimit -v 262144 && exec "$@"',
    "sh",
)
LOCAL_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "100.64.0.0/10",
        "fc00::/7",
    )
)


class ThroughputValidationError(Exception):
    """Bad input, or a peer outside the local ranges (a plain sentence for a 400)."""


class ThroughputBusyError(Exception):
    """A test is already running."""


def _whole(value: Any, name: str, low: int, high: int, default: int) -> int:
    if value is None:
        return default
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not low <= value <= high
    ):
        raise ThroughputValidationError(
            f"{name} must be a whole number from {low} to {high}."
        )
    return value


def _refusal(ip: str) -> str | None:
    """Why `ip` can't be tested, or None when it is in a local range."""
    addr = ipaddress.ip_address(ip)
    if addr.is_link_local:
        return LINK_LOCAL
    return None if any(addr in net for net in LOCAL_NETWORKS) else NOT_LOCAL


def _has_ip(iface: str) -> bool:
    """Whether an interface holds an address; IPv6 link-local doesn't count (as in mirror_manager)."""
    return any(
        a.family == socket.AF_INET
        or (a.family == socket.AF_INET6 and not a.address.lower().startswith("fe80"))
        for a in psutil.net_if_addrs().get(iface, [])
    )


def _number(value: Any) -> float | None:
    return (
        value
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else None
    )


def _parse(stdout: str, download: bool) -> tuple[float | None, int | None, str | None]:
    """bits per second, retransmits (upload only) and iperf3's own error, from its -J output.

    The rate is what the receiver got (sum_received) both ways: sum_sent counts what NetTap
    wrote into its socket, which reads high for a short test to a Wi-Fi peer.
    """
    try:
        data = json.loads(stdout)
    except ValueError:
        return None, None, None
    if not isinstance(data, dict):
        return None, None, None
    if data.get("error"):
        return None, None, str(data["error"])
    end = data.get("end") if isinstance(data.get("end"), dict) else {}
    # OLD CODE START — review of #266: the upload rate came from sum_sent (PLAN.md section 5)
    # side = end.get("sum_received" if download else "sum_sent")
    # side = side if isinstance(side, dict) else {}
    # retransmits = None if download else _number(side.get("retransmits"))
    # return _number(side.get("bits_per_second")), retransmits, None
    # OLD CODE END
    received, sent = (
        side if isinstance(side, dict) else {}
        for side in (end.get("sum_received"), end.get("sum_sent"))
    )
    retransmits = None if download else _number(sent.get("retransmits"))
    return _number(received.get("bits_per_second")), retransmits, None


def _plain(error: str, host: str, port: int) -> str:
    """iperf3's common failures as plain sentences; anything else as iperf3 said it."""
    where = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    if "Connection refused" in error:
        # OLD CODE: where = … (moved up: the timed-out sentence names the peer too)
        return f"No iperf3 server on {where}. Start one there with iperf3 -s."
    # NET-271: a firewall that drops the port gives no refusal, only silence
    if "Connection timed out" in error:
        return (
            f"Nothing answered on {where} within {CONNECT_TIMEOUT_MS // 1000} seconds. "
            f"Start iperf3 -s there, and let TCP port {port} through its firewall."
        )
    if "server is busy" in error:
        return "The iperf3 server is busy with another test."
    return error


class ThroughputService:
    """Runs one iperf3 test at a time against a LAN peer."""

    def __init__(self) -> None:
        self._slot = asyncio.Lock()
        self._diag = NetworkDiagService()

    async def run_test(
        self,
        host: Any,
        port: Any = None,
        duration: Any = None,
        direction: Any = None,
        capture_mode: str | None = None,
        capture_interface: str | None = None,
    ) -> dict[str, Any]:
        """Returns {peer, resolved_ip, port, direction, duration, bits_per_second, retransmits,
        path, capture, error}. Raises ThroughputValidationError (or NetworkDiagValidationError
        for the host) on bad input and ThroughputBusyError when a test is running."""
        if not isinstance(host, str):
            raise ThroughputValidationError("Enter the peer's host name or IP address.")
        host = check_name(self._diag.validate_target(host))
        port = _whole(port, "Port", 1, 65535, DEFAULT_PORT)
        duration = _whole(duration, "Duration", 1, MAX_DURATION, DEFAULT_DURATION)
        if direction not in DIRECTIONS:
            raise ThroughputValidationError("Direction must be upload or download.")

        if self._slot.locked():  # checked first, so acquiring below never waits
            raise ThroughputBusyError(BUSY)
        async with self._slot:
            base = {
                "peer": host,
                "resolved_ip": None,
                "port": port,
                "direction": direction,
                "duration": duration,
                "bits_per_second": None,
                "retransmits": None,
                "path": None,
                "capture": {
                    "mode": capture_mode,
                    "interface": capture_interface,
                    "has_ip": _has_ip(capture_interface) if capture_interface else None,
                },
                "error": None,
            }
            started = time.monotonic()
            try:
                async with asyncio.timeout(duration + DEADLINE_SLACK):
                    result = await self._run(base, direction == "download")
            except TimeoutError:
                result = {**base, "error": TOO_LONG}
            except OSError as exc:  # a missing binary
                # OLD CODE: result = {**base, "error": f"NetTap could not start the test: {exc}"}
                logger.warning("throughput %r: could not start: %r", host, exc)
                reason = exc.strerror or "it failed to start"
                result = {
                    **base,
                    "error": f"NetTap could not start the test ({reason}).",
                }
            log = logger.warning if result["error"] else logger.info
            log(
                "throughput %s %r port %d %d s -> %s in %.1f s",
                direction,
                host,
                port,
                duration,
                result["error"] or f"{result['bits_per_second']:.0f} bit/s",
                time.monotonic() - started,
            )
            return result

    async def _run(self, base: dict[str, Any], download: bool) -> dict[str, Any]:
        host, port = base["peer"], base["port"]
        try:
            addresses = await resolve(host)
        except HostLookupError as exc:
            return {**base, "error": str(exc)}
        ip = next((a for a in addresses if _refusal(a) is None), None)
        if ip is None:
            raise ThroughputValidationError(_refusal(addresses[0]))
        try:
            path = await route_to(ip)
        except HostLookupError as exc:
            return {**base, "resolved_ip": ip, "error": str(exc)}

        # OLD CODE: argv = ["iperf3", "-c", ip, ...] (review of #266: now inside SANDBOX)
        argv = [
            *SANDBOX,
            "iperf3",
            "-c",
            ip,
            "-p",
            str(port),
            "-t",
            str(base["duration"]),
        ]
        argv += ["--connect-timeout", str(CONNECT_TIMEOUT_MS), "-J"]
        code, out, err = await run(*argv, *(["-R"] if download else []))
        bps, retransmits, error = _parse(out, download)
        if code == 127:  # sh: exec: iperf3: not found
            error = NO_IPERF3
        elif error is None and bps is None:  # no result in the output
            error = err.strip() or f"iperf3 exited with code {code}"
        return {
            **base,
            "resolved_ip": ip,
            "path": path,
            "bits_per_second": None if error else bps,
            "retransmits": None if error else retransmits,
            "error": _plain(error, host, port) if error else None,
        }
