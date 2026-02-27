"""
NetTap Bridge Health Monitor Service

Monitors Linux bridge health for the NetTap inline tap appliance.
Tracks bridge interface state, NIC link carrier status, packet counters,
bypass mode state, and watchdog heartbeat. Provides rolling history,
health status determination, and aggregate statistics.

Designed to run inside a Docker container where direct access to the
host bridge may not be available. Methods gracefully degrade when sysfs
or proc entries are missing, returning "unknown" states rather than
crashing.

Health status levels:
    normal:   Bridge up, both NICs linked, no bypass
    degraded: Bridge up but one NIC down, or elevated latency
    bypass:   Bypass mode is active (traffic flows direct, no inspection)
    down:     Bridge interface is down or both NICs unlinked
"""

import asyncio
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

logger = logging.getLogger("nettap.services.bridge_health")

# Path constants for Linux sysfs/proc/run
_SYSFS_NET = "/sys/class/net"
_BYPASS_STATE_FILE = "/var/run/nettap-bypass-active"


@dataclass
class BridgeHealthCheck:
    """Result of a single bridge health check cycle."""

    bridge_state: str  # "up" | "down" | "unknown"
    wan_link: bool  # carrier detected on WAN NIC
    lan_link: bool  # carrier detected on LAN NIC
    bypass_active: bool
    watchdog_active: bool
    latency_us: float  # bridge latency estimate in microseconds
    rx_bytes_delta: int  # bytes received since last check
    tx_bytes_delta: int  # bytes transmitted since last check
    rx_packets_delta: int  # packets received since last check
    tx_packets_delta: int  # packets transmitted since last check
    uptime_seconds: float  # bridge uptime since last state change
    health_status: str  # "normal" | "degraded" | "bypass" | "down"
    issues: list  # human-readable issue descriptions
    last_check: str  # ISO timestamp

    def to_dict(self) -> dict:
        return asdict(self)


class BridgeHealthMonitor:
    """Monitors Linux bridge health for the NetTap inline tap.

    Tracks:
    - Bridge interface state (up/down)
    - NIC link carrier status on both WAN and LAN interfaces
    - Packet counters (TX/RX delta) for throughput estimation
    - Whether bypass mode is active
    - Watchdog heartbeat status
    """

    # Maximum history entries: 24h at 30s intervals = 2880
    DEFAULT_MAX_HISTORY = 2880

    def __init__(
        self,
        bridge_name: str = "br0",
        wan_iface: str = "eth0",
        lan_iface: str = "eth1",
        max_history: int = DEFAULT_MAX_HISTORY,
    ) -> None:
        self._bridge_name = bridge_name
        self._wan_iface = wan_iface
        self._lan_iface = lan_iface
        self._max_history = max_history

        # Health check history (bounded deque)
        self._history: deque[BridgeHealthCheck] = deque(maxlen=max_history)

        # Previous counter snapshots for delta calculation
        self._prev_rx_bytes: int | None = None
        self._prev_tx_bytes: int | None = None
        self._prev_rx_packets: int | None = None
        self._prev_tx_packets: int | None = None

        # Bridge uptime tracking
        self._bridge_up_since: float | None = None
        self._last_bridge_state: str | None = None

        # Bypass state
        self._bypass_active: bool = False

        logger.info(
            "BridgeHealthMonitor initialized: bridge=%s wan=%s lan=%s max_history=%d",
            bridge_name,
            wan_iface,
            lan_iface,
            max_history,
        )

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    async def check_health(self) -> dict:
        """Run a health check cycle.

        Reads bridge/NIC state from sysfs, computes packet counter deltas,
        checks bypass/watchdog status, and determines overall health.

        Returns:
            Dict with bridge_state, wan_link, lan_link, bypass_active,
            watchdog_active, latency_us, rx/tx deltas, uptime_seconds,
            health_status, issues, and last_check timestamp.
        """
        now = datetime.now(timezone.utc)
        issues: list[str] = []

        # Read interface states
        bridge_state = await self._check_bridge_state()
        wan_link = await self._check_carrier(self._wan_iface)
        lan_link = await self._check_carrier(self._lan_iface)

        # Read packet counters and compute deltas
        stats = await self._read_interface_stats(self._bridge_name)
        rx_bytes_delta, tx_bytes_delta, rx_packets_delta, tx_packets_delta = (
            self._calculate_deltas(stats)
        )

        # Update previous counters
        if stats:
            self._prev_rx_bytes = stats.get("rx_bytes")
            self._prev_tx_bytes = stats.get("tx_bytes")
            self._prev_rx_packets = stats.get("rx_packets")
            self._prev_tx_packets = stats.get("tx_packets")

        # Track bridge uptime
        if bridge_state != self._last_bridge_state:
            if bridge_state == "up":
                self._bridge_up_since = time.monotonic()
            else:
                self._bridge_up_since = None
            self._last_bridge_state = bridge_state

        uptime_seconds = 0.0
        if self._bridge_up_since is not None:
            uptime_seconds = round(time.monotonic() - self._bridge_up_since, 2)

        # Check bypass mode
        bypass_active = self._bypass_active or self._check_bypass_file()

        # Check watchdog
        watchdog_active = await self._check_watchdog()

        # Estimate bridge latency (simulated -- real measurement would
        # require timestamped packets through the bridge path)
        latency_us = self._estimate_latency(bridge_state, wan_link, lan_link)

        # Build issue list
        if bridge_state == "down":
            issues.append("Bridge interface is down")
        elif bridge_state == "unknown":
            issues.append("Bridge interface state could not be determined")

        if not wan_link:
            issues.append(f"WAN interface {self._wan_iface} has no carrier")
        if not lan_link:
            issues.append(f"LAN interface {self._lan_iface} has no carrier")
        if bypass_active:
            issues.append("Bypass mode is active -- traffic is not being inspected")
        if not watchdog_active:
            issues.append("Watchdog service is not running")

        # Determine health status
        health_status = self._determine_health_status(
            bridge_state, wan_link, lan_link, bypass_active
        )

        check = BridgeHealthCheck(
            bridge_state=bridge_state,
            wan_link=wan_link,
            lan_link=lan_link,
            bypass_active=bypass_active,
            watchdog_active=watchdog_active,
            latency_us=latency_us,
            rx_bytes_delta=rx_bytes_delta,
            tx_bytes_delta=tx_bytes_delta,
            rx_packets_delta=rx_packets_delta,
            tx_packets_delta=tx_packets_delta,
            uptime_seconds=uptime_seconds,
            health_status=health_status,
            issues=issues,
            last_check=now.isoformat(),
        )

        self._history.append(check)

        return check.to_dict()

    async def get_history(self, limit: int = 100) -> list[dict]:
        """Return recent health check history, newest first.

        Args:
            limit: Maximum number of entries to return (default 100).

        Returns:
            List of health check dicts, newest first.
        """
        entries = list(self._history)[-limit:]
        return [h.to_dict() for h in reversed(entries)]

    async def get_statistics(self) -> dict:
        """Return aggregate statistics over the health check history.

        Returns:
            Dict with average_latency_us, total_rx_bytes, total_tx_bytes,
            total_rx_packets, total_tx_packets, uptime_percentage,
            longest_downtime_seconds, total_checks, and status_counts.
        """
        if not self._history:
            return {
                "average_latency_us": None,
                "total_rx_bytes": 0,
                "total_tx_bytes": 0,
                "total_rx_packets": 0,
                "total_tx_packets": 0,
                "uptime_percentage": None,
                "longest_downtime_seconds": 0,
                "total_checks": 0,
                "status_counts": {
                    "normal": 0,
                    "degraded": 0,
                    "bypass": 0,
                    "down": 0,
                },
            }

        latencies = [h.latency_us for h in self._history if h.latency_us > 0]
        avg_latency = (
            round(sum(latencies) / len(latencies), 2) if latencies else None
        )

        total_rx_bytes = sum(h.rx_bytes_delta for h in self._history)
        total_tx_bytes = sum(h.tx_bytes_delta for h in self._history)
        total_rx_packets = sum(h.rx_packets_delta for h in self._history)
        total_tx_packets = sum(h.tx_packets_delta for h in self._history)

        # Status counts
        status_counts: dict[str, int] = {
            "normal": 0,
            "degraded": 0,
            "bypass": 0,
            "down": 0,
        }
        for h in self._history:
            if h.health_status in status_counts:
                status_counts[h.health_status] += 1

        # Uptime percentage (normal + degraded are considered "up")
        total = len(self._history)
        up_count = status_counts["normal"] + status_counts["degraded"]
        uptime_pct = round((up_count / total) * 100, 2)

        # Longest consecutive downtime (in check intervals)
        longest_down_streak = 0
        current_down_streak = 0
        for h in self._history:
            if h.health_status == "down":
                current_down_streak += 1
                longest_down_streak = max(longest_down_streak, current_down_streak)
            else:
                current_down_streak = 0

        # Estimate seconds: assume 30s check interval
        longest_downtime_seconds = longest_down_streak * 30

        return {
            "average_latency_us": avg_latency,
            "total_rx_bytes": total_rx_bytes,
            "total_tx_bytes": total_tx_bytes,
            "total_rx_packets": total_rx_packets,
            "total_tx_packets": total_tx_packets,
            "uptime_percentage": uptime_pct,
            "longest_downtime_seconds": longest_downtime_seconds,
            "total_checks": total,
            "status_counts": status_counts,
        }

    async def trigger_bypass(self) -> dict:
        """Activate bypass mode.

        In bypass mode, traffic flows directly between WAN and LAN
        without inspection. This is typically used during maintenance
        or when the bridge is degraded.

        Returns:
            Dict confirming bypass activation with timestamp.
        """
        self._bypass_active = True
        self._write_bypass_file(active=True)
        ts = datetime.now(timezone.utc).isoformat()
        logger.warning("Bypass mode ACTIVATED at %s", ts)
        return {
            "bypass_active": True,
            "activated_at": ts,
            "message": "Bypass mode activated -- traffic is flowing uninspected",
        }

    async def disable_bypass(self) -> dict:
        """Deactivate bypass mode.

        Returns:
            Dict confirming bypass deactivation with timestamp.
        """
        self._bypass_active = False
        self._write_bypass_file(active=False)
        ts = datetime.now(timezone.utc).isoformat()
        logger.info("Bypass mode DEACTIVATED at %s", ts)
        return {
            "bypass_active": False,
            "deactivated_at": ts,
            "message": "Bypass mode deactivated -- traffic inspection resumed",
        }

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    async def _check_bridge_state(self) -> str:
        """Check the bridge interface operational state via sysfs.

        Returns:
            "up", "down", or "unknown" if sysfs is not accessible.
        """
        operstate_path = os.path.join(
            _SYSFS_NET, self._bridge_name, "operstate"
        )
        try:
            loop = asyncio.get_running_loop()
            content = await loop.run_in_executor(
                None, self._read_sysfs_file, operstate_path
            )
            if content is None:
                return "unknown"
            state = content.strip().lower()
            if state in ("up",):
                return "up"
            elif state in ("down", "lowerlayerdown"):
                return "down"
            else:
                return "unknown"
        except Exception as exc:
            logger.debug("Could not read bridge state: %s", exc)
            return "unknown"

    async def _check_carrier(self, iface: str) -> bool:
        """Check if a NIC has carrier (link) detected via sysfs.

        Returns:
            True if carrier is detected, False otherwise (including
            when sysfs is not accessible).
        """
        carrier_path = os.path.join(_SYSFS_NET, iface, "carrier")
        try:
            loop = asyncio.get_running_loop()
            content = await loop.run_in_executor(
                None, self._read_sysfs_file, carrier_path
            )
            if content is None:
                return False
            return content.strip() == "1"
        except Exception as exc:
            logger.debug("Could not read carrier for %s: %s", iface, exc)
            return False

    async def _read_interface_stats(self, iface: str) -> dict[str, int]:
        """Read TX/RX byte and packet counters from sysfs.

        Returns:
            Dict with rx_bytes, tx_bytes, rx_packets, tx_packets.
            Values are 0 if sysfs is not accessible.
        """
        stats_dir = os.path.join(_SYSFS_NET, iface, "statistics")
        result: dict[str, int] = {
            "rx_bytes": 0,
            "tx_bytes": 0,
            "rx_packets": 0,
            "tx_packets": 0,
        }

        try:
            loop = asyncio.get_running_loop()
            for key in result:
                path = os.path.join(stats_dir, key)
                content = await loop.run_in_executor(
                    None, self._read_sysfs_file, path
                )
                if content is not None:
                    try:
                        result[key] = int(content.strip())
                    except ValueError:
                        pass
        except Exception as exc:
            logger.debug("Could not read stats for %s: %s", iface, exc)

        return result

    def _calculate_deltas(
        self, current_stats: dict[str, int]
    ) -> tuple[int, int, int, int]:
        """Calculate packet/byte counter deltas since last check.

        Returns:
            Tuple of (rx_bytes_delta, tx_bytes_delta, rx_packets_delta,
            tx_packets_delta). All zeros on first check or if counters
            wrapped.
        """
        if self._prev_rx_bytes is None or not current_stats:
            return (0, 0, 0, 0)

        rx_bytes = current_stats.get("rx_bytes", 0)
        tx_bytes = current_stats.get("tx_bytes", 0)
        rx_packets = current_stats.get("rx_packets", 0)
        tx_packets = current_stats.get("tx_packets", 0)

        rx_bytes_delta = max(0, rx_bytes - (self._prev_rx_bytes or 0))
        tx_bytes_delta = max(0, tx_bytes - (self._prev_tx_bytes or 0))
        rx_packets_delta = max(0, rx_packets - (self._prev_rx_packets or 0))
        tx_packets_delta = max(0, tx_packets - (self._prev_tx_packets or 0))

        return (rx_bytes_delta, tx_bytes_delta, rx_packets_delta, tx_packets_delta)

    def _determine_health_status(
        self,
        bridge_state: str,
        wan_link: bool,
        lan_link: bool,
        bypass_active: bool,
    ) -> str:
        """Determine overall health status from component states.

        Returns:
            "normal", "degraded", "bypass", or "down".
        """
        if bypass_active:
            return "bypass"

        if bridge_state == "down" or (not wan_link and not lan_link):
            return "down"

        if bridge_state == "unknown" or not wan_link or not lan_link:
            return "degraded"

        return "normal"

    def _estimate_latency(
        self, bridge_state: str, wan_link: bool, lan_link: bool
    ) -> float:
        """Estimate bridge forwarding latency in microseconds.

        This is a simulated estimate. Real latency measurement would
        require timestamped test packets through the bridge path.

        Returns:
            Estimated latency in microseconds.
        """
        if bridge_state != "up":
            return 0.0

        # Base latency for a software bridge on modern hardware
        base_latency = 50.0  # ~50us for Linux bridge forwarding

        if not wan_link or not lan_link:
            # Degraded -- higher latency estimate
            return base_latency * 3

        return base_latency

    def _check_bypass_file(self) -> bool:
        """Check if the bypass state file exists on disk."""
        try:
            return os.path.exists(_BYPASS_STATE_FILE)
        except OSError:
            return False

    def _write_bypass_file(self, active: bool) -> None:
        """Write or remove the bypass state file.

        Silently ignores write failures (e.g., read-only filesystem
        in container).
        """
        try:
            if active:
                os.makedirs(os.path.dirname(_BYPASS_STATE_FILE), exist_ok=True)
                with open(_BYPASS_STATE_FILE, "w") as f:
                    f.write(datetime.now(timezone.utc).isoformat())
            else:
                if os.path.exists(_BYPASS_STATE_FILE):
                    os.remove(_BYPASS_STATE_FILE)
        except OSError as exc:
            logger.debug("Could not write bypass state file: %s", exc)

    async def _check_watchdog(self) -> bool:
        """Check if the nettap-watchdog systemd service is active.

        Returns:
            True if the watchdog service is running, False otherwise.
            Returns False gracefully when systemctl is not available
            (e.g., inside a container).
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "is-active", "nettap-watchdog",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            return stdout.decode("utf-8", errors="replace").strip() == "active"
        except (FileNotFoundError, asyncio.TimeoutError, OSError) as exc:
            logger.debug("Watchdog check unavailable: %s", exc)
            return False

    @staticmethod
    def _read_sysfs_file(path: str) -> str | None:
        """Read a sysfs file and return its contents, or None on error."""
        try:
            with open(path, "r") as f:
                return f.read()
        except (FileNotFoundError, PermissionError, OSError):
            return None
