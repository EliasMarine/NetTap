"""
NetTap DHCP Gateway — host-side helpers.

Host network commands (``nsenter -t 1 -n``, ``ip -j``, iptables), the dnsmasq
child process supervisor, and small sysfs and file helpers used by
DhcpGatewayManager. Split out to keep the manager focused on the
enable / disable / reconcile flow.
"""

import asyncio
import contextlib
import ipaddress
import json
import logging
import os

from services.capture_manager import CaptureStats

logger = logging.getLogger("nettap.services.dhcp_gateway")

# Tried in this order; the first one with a DOCKER-USER chain wins
FIREWALL_BACKENDS = ("iptables-nft", "iptables-legacy")

# dnsmasq is treated as started once it has stayed up this long
_STARTUP_GRACE_S = 1.0
# Time to wait after SIGTERM before SIGKILL
_STOP_TIMEOUT_S = 5.0


class HostNetOps:
    """Host network namespace queries and firewall rule operations.

    Every command runs through ``_run_nsenter`` with list arguments, so tests
    can replace that one method.
    """

    _backend: str | None = None

    async def _run_nsenter(self, *args: str) -> tuple[int, str, str]:
        """Run a command in the host network namespace via nsenter.

        Returns:
            Tuple of (returncode, stdout, stderr).
        """
        cmd = ["nsenter", "-t", "1", "-n", "--"] + list(args)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            return (
                proc.returncode or 0,
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
            )
        except asyncio.TimeoutError:
            logger.warning("nsenter command timed out: %s", " ".join(cmd))
            return (1, "", "timeout")
        except FileNotFoundError:
            logger.debug("nsenter not available")
            return (1, "", "nsenter not found")

    async def ip_json(self, *args: str) -> list:
        """``ip -j <args>`` parsed to a list; empty list on any failure."""
        rc, out, _ = await self._run_nsenter("ip", "-j", *args)
        if rc != 0:
            return []
        try:
            data = json.loads(out or "[]")
        except ValueError:
            return []
        return data if isinstance(data, list) else []

    async def inet_addrs(
        self, iface: str = ""
    ) -> list[tuple[str, ipaddress.IPv4Interface]]:
        """(ifname, address) for every IPv4 address, on ``iface`` or on all NICs."""
        args = ("-4", "addr", "show") + (("dev", iface) if iface else ())
        result = []
        for link in await self.ip_json(*args):
            for addr in link.get("addr_info", []) if isinstance(link, dict) else []:
                try:
                    cidr = ipaddress.IPv4Interface(
                        f"{addr['local']}/{addr['prefixlen']}"
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                result.append((link.get("ifname", iface), cidr))
        return result

    async def _iface_cidrs(self, iface: str) -> set[str]:
        return {cidr.with_prefixlen for _, cidr in await self.inet_addrs(iface)}

    async def detect_firewall_backend(self) -> str | None:
        """First iptables backend that has Docker's DOCKER-USER chain, else None."""
        for cmd in FIREWALL_BACKENDS:
            rc, _, _ = await self._run_nsenter(cmd, "-w", "-S", "DOCKER-USER")
            if rc == 0:
                self._backend = cmd
                return cmd
        self._backend = None
        return None

    async def _rule_present(self, backend: str, rule: tuple) -> bool:
        table, chain, _, args = rule
        rc, _, _ = await self._run_nsenter(
            backend, "-w", "-t", table, "-C", chain, *args
        )
        return rc == 0

    async def _ensure_rule(self, backend: str, rule: tuple) -> bool:
        """Add ``rule`` unless ``-C`` finds it. True if added; RuntimeError on failure."""
        if await self._rule_present(backend, rule):
            return False
        table, chain, action, args = rule
        rc, _, err = await self._run_nsenter(
            backend, "-w", "-t", table, action, chain, *args
        )
        if rc != 0:
            raise RuntimeError(
                f"Could not add the {table}/{chain} firewall rule: {err.strip()}"
            )
        return True

    async def _delete_rule(self, backend: str, rule: tuple) -> str:
        """Delete ``rule`` if present. Returns an error message, or "" on success."""
        if not await self._rule_present(backend, rule):
            return ""
        table, chain, _, args = rule
        rc, _, err = await self._run_nsenter(
            backend, "-w", "-t", table, "-D", chain, *args
        )
        return (
            ""
            if rc == 0
            else f"Could not delete the {table}/{chain} rule: {err.strip()}"
        )

    async def _disable_gro(self, iface: str) -> str:
        """GRO/LRO off for accurate capture. Returns a warning, or "" on success."""
        rc, _, err = await self._run_nsenter(
            "ethtool", "-K", iface, "gro", "off", "lro", "off"
        )
        if rc == 0:
            return ""
        # Non-critical — some NICs don't support all offloads
        warning = f"Could not turn off GRO/LRO on {iface}: {err.strip()}"
        logger.warning(warning)
        return warning


class DnsmasqProcess:
    """Runs dnsmasq as an asyncio child process and logs its stderr."""

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task | None = None
        self._last_line = ""

    @property
    def running(self) -> bool:
        """True while the child process is alive."""
        return self._proc is not None and self._proc.returncode is None

    async def start(self, args: list[str], lease_dir: str) -> bool:
        """Start dnsmasq with ``args`` (a list, never a shell string).

        Returns:
            True if a new process was started, False if one was already running.

        Raises:
            RuntimeError: dnsmasq could not be started or exited at once.
        """
        if self.running:
            return False
        # Lease file stays root-owned on purpose: dnsmasq opens it as root
        # before dropping to nobody, and root without DAC_OVERRIDE can't open a
        # nobody-owned file (dnsmasq then exits "cannot open lease file").
        os.makedirs(lease_dir, exist_ok=True)
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise RuntimeError(f"Could not start dnsmasq: {exc}") from exc

        self._proc = proc
        self._last_line = ""
        self._reader = asyncio.create_task(self._log_stderr(proc))
        try:
            await asyncio.wait_for(proc.wait(), timeout=_STARTUP_GRACE_S)
        except asyncio.TimeoutError:
            logger.info("dnsmasq started (pid %s)", proc.pid)
            return True

        # Exited inside the grace period: let the reader catch the last line
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._reader, timeout=1.0)
        self._proc = None
        raise RuntimeError(
            f"dnsmasq stopped right after starting (exit code {proc.returncode})"
            + (f": {self._last_line}" if self._last_line else "")
        )

    async def stop(self) -> None:
        """Stop dnsmasq: SIGTERM, then SIGKILL after 5 s. No-op if not running."""
        proc = self._proc
        if proc is None:
            return
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=_STOP_TIMEOUT_S)
            except asyncio.TimeoutError:
                logger.warning(
                    "dnsmasq ignored SIGTERM for %ss, killing it", _STOP_TIMEOUT_S
                )
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()
            logger.info("dnsmasq stopped")
        if self._reader is not None:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._reader, timeout=1.0)
        self._proc = None
        self._reader = None

    async def _log_stderr(self, proc: asyncio.subprocess.Process) -> None:
        """Forward dnsmasq's log lines (``--log-facility=-``) to the daemon log."""
        if proc.stderr is None:
            return
        async for raw in proc.stderr:
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                self._last_line = line
                logger.info("dnsmasq: %s", line)


def read_sysfs(path: str) -> str:
    """Read a sysfs/proc file and return its contents. Empty string on error."""
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except OSError:
        return ""


def _read_sysfs_int(path: str) -> int:
    """Read a sysfs file containing an integer value. Returns 0 on error."""
    try:
        return int(read_sysfs(path))
    except ValueError:
        return 0


def read_iface_stats(sys_net: str, iface: str) -> CaptureStats:
    """Interface counters, link speed and drop rate from sysfs."""
    stats_dir = os.path.join(sys_net, iface, "statistics")
    counters = {
        name: _read_sysfs_int(os.path.join(stats_dir, name))
        for name in (
            "rx_bytes",
            "tx_bytes",
            "rx_packets",
            "tx_packets",
            "rx_dropped",
            "rx_missed_errors",
        )
    }
    speed = _read_sysfs_int(os.path.join(sys_net, iface, "speed"))
    # Kernel returns -1 or very large values when speed is unknown
    if speed < 0 or speed > 400000:
        speed = 0
    total_rx = counters["rx_packets"] + counters["rx_dropped"]
    drop_rate = (
        round((counters["rx_dropped"] / total_rx) * 100, 4) if total_rx > 0 else 0.0
    )
    return CaptureStats(
        capture_interface=iface,
        link_speed_mbps=speed,
        drop_rate_pct=drop_rate,
        **counters,
    )


def remove_path(path: str) -> None:
    """Delete a file or symlink (dangling links too). Missing is fine."""
    if os.path.lexists(path):
        os.unlink(path)


def replace_symlink(target: str, link_path: str) -> None:
    """Point ``link_path`` at ``target``, replacing any existing link.

    ``target`` is a host path, so the link dangles inside the container;
    lexists() is used because exists() follows the link.
    """
    os.makedirs(os.path.dirname(link_path), exist_ok=True)
    remove_path(link_path)
    os.symlink(target, link_path)
