"""
NetTap Bridge Capture Adapter

Wraps the existing BridgeManager and BridgeHealthMonitor behind the
CaptureManager abstract interface. This adapter is the bridge-mode
implementation of CaptureManager — downstream code never touches
BridgeManager or BridgeHealthMonitor directly; it only uses the
CaptureManager protocol.

The adapter does NOT modify the wrapped objects. It delegates all real
work and maps results to the mode-agnostic CaptureHealth / CaptureStats
dataclasses defined in capture_manager.py.
"""

import logging
import os
from typing import Any

from services.bridge_health import BridgeHealthMonitor
from services.bridge_manager import BridgeManager
from services.capture_manager import (
    CaptureHealth,
    CaptureManager,
    CaptureMode,
    CaptureStats,
)

logger = logging.getLogger("nettap.services.bridge_capture_adapter")

# Host sysfs path for reading NIC/bridge counters inside the container.
# The host's /sys is bind-mounted at /host/sys via docker-compose.
_SYSFS_NET = os.environ.get("HOST_SYS_NET", "/host/sys/class/net")


class BridgeCaptureAdapter(CaptureManager):
    """Adapter that presents BridgeManager + BridgeHealthMonitor as a CaptureManager.

    All bridge lifecycle operations (create/teardown) delegate to
    BridgeManager. Health checks delegate to BridgeHealthMonitor and
    the result is mapped to the mode-agnostic CaptureHealth dataclass.
    Interface statistics are read directly from sysfs counters.

    Args:
        bridge_manager: Existing BridgeManager instance.
        bridge_health: Existing BridgeHealthMonitor instance.
        wan_iface: WAN-side interface name (e.g., 'enp2s0').
        lan_iface: LAN-side interface name (e.g., 'enp3s0').
        bridge_name: Bridge interface name (default 'br0').
    """

    def __init__(
        self,
        bridge_manager: BridgeManager,
        bridge_health: BridgeHealthMonitor,
        wan_iface: str,
        lan_iface: str,
        bridge_name: str = "br0",
    ) -> None:
        self._bridge_manager = bridge_manager
        self._bridge_health = bridge_health
        self._wan_iface = wan_iface
        self._lan_iface = lan_iface
        self._bridge_name = bridge_name

        logger.info(
            "BridgeCaptureAdapter initialized: bridge=%s wan=%s lan=%s",
            bridge_name,
            wan_iface,
            lan_iface,
        )

    # -------------------------------------------------------------------
    # CaptureManager interface implementation
    # -------------------------------------------------------------------

    async def setup(self) -> dict:
        """Configure the bridge capture interface.

        Delegates to BridgeManager.create_bridge() with the WAN and LAN
        interfaces provided at construction time.

        Returns:
            Dict with setup results from BridgeManager (created, bridge_name,
            wan, lan, state, errors, warnings, persistence_files).
        """
        logger.info(
            "Setting up bridge capture: wan=%s lan=%s",
            self._wan_iface,
            self._lan_iface,
        )
        return await self._bridge_manager.create_bridge(
            wan=self._wan_iface,
            lan=self._lan_iface,
        )

    async def teardown(self) -> dict:
        """Tear down the bridge capture interface.

        Delegates to BridgeManager.teardown_bridge().

        Returns:
            Dict with teardown results (torn_down, errors).
        """
        logger.info("Tearing down bridge capture")
        return await self._bridge_manager.teardown_bridge()

    async def get_health(self) -> CaptureHealth:
        """Get current bridge capture health status.

        Delegates to BridgeHealthMonitor.check_health() and maps the
        bridge-specific result to the mode-agnostic CaptureHealth dataclass.

        Returns:
            CaptureHealth with bridge health data mapped to generic fields.
        """
        health_dict = await self._bridge_health.check_health()

        # Map bridge_state + health_status to the CaptureHealth fields.
        # BridgeHealthMonitor returns: bridge_state, wan_link, lan_link,
        # bypass_active, watchdog_active, latency_us, rx/tx deltas,
        # uptime_seconds, health_status, issues, last_check.
        bridge_state = health_dict.get("bridge_state", "unknown")
        wan_link: bool = health_dict.get("wan_link", False)
        lan_link: bool = health_dict.get("lan_link", False)

        # link_up: True if the bridge itself is up (individual NIC status
        # goes into extra for consumers that need it).
        link_up = bridge_state == "up"

        # Promiscuous mode: infer from health status. If bypass is active,
        # promisc was disabled. Otherwise if bridge is up, promisc should
        # be on (BridgeManager enables it during create_bridge).
        bypass_active: bool = health_dict.get("bypass_active", False)
        promisc_enabled = link_up and not bypass_active

        # Build the extra dict with bridge-specific fields that don't map
        # directly to CaptureHealth but are useful for bridge-aware consumers.
        extra: dict[str, Any] = {
            "bridge_state": bridge_state,
            "wan_link": wan_link,
            "lan_link": lan_link,
            "wan_iface": self._wan_iface,
            "lan_iface": self._lan_iface,
            "bypass_active": bypass_active,
            "watchdog_active": health_dict.get("watchdog_active", False),
            "latency_us": health_dict.get("latency_us", 0.0),
            "uptime_seconds": health_dict.get("uptime_seconds", 0.0),
            "last_check": health_dict.get("last_check", ""),
        }

        return CaptureHealth(
            mode=CaptureMode.BRIDGE.value,
            status=health_dict.get("health_status", "unknown"),
            capture_interface=self._bridge_name,
            link_up=link_up,
            promisc_enabled=promisc_enabled,
            issues=health_dict.get("issues", []),
            extra=extra,
        )

    def get_capture_interface(self) -> str:
        """Get the bridge interface name for capture tools.

        Returns:
            The bridge name (default 'br0'). Zeek, Suricata, and Arkime
            should listen on this interface.
        """
        return self._bridge_name

    async def get_stats(self) -> CaptureStats:
        """Get bridge interface statistics from sysfs counters.

        Reads rx_bytes, tx_bytes, rx_packets, tx_packets, rx_dropped,
        rx_missed_errors, and link speed from the bridge interface's
        sysfs statistics directory.

        Returns:
            CaptureStats populated with current counter values.
        """
        stats_dir = os.path.join(_SYSFS_NET, self._bridge_name, "statistics")

        # Counter files to read from sysfs
        counter_names = [
            "rx_bytes",
            "tx_bytes",
            "rx_packets",
            "tx_packets",
            "rx_dropped",
            "rx_missed_errors",
        ]
        counters: dict[str, int] = {}
        for name in counter_names:
            counters[name] = self._read_sysfs_int(
                os.path.join(stats_dir, name)
            )

        # Link speed (in Mbps) — lives at the interface level, not statistics/
        speed_path = os.path.join(_SYSFS_NET, self._bridge_name, "speed")
        link_speed = self._read_sysfs_int(speed_path)
        # sysfs reports -1 or 0 when speed is unknown (e.g., bridge with
        # no carrier). Clamp to 0 for a sensible default.
        if link_speed < 0:
            link_speed = 0

        # Calculate drop rate as a percentage of total received packets
        rx_packets = counters.get("rx_packets", 0)
        rx_dropped = counters.get("rx_dropped", 0)
        rx_missed = counters.get("rx_missed_errors", 0)
        total_drops = rx_dropped + rx_missed
        drop_rate_pct = 0.0
        if rx_packets > 0:
            drop_rate_pct = round((total_drops / rx_packets) * 100, 6)

        return CaptureStats(
            capture_interface=self._bridge_name,
            rx_bytes=counters.get("rx_bytes", 0),
            tx_bytes=counters.get("tx_bytes", 0),
            rx_packets=rx_packets,
            tx_packets=counters.get("tx_packets", 0),
            rx_dropped=rx_dropped,
            rx_missed_errors=rx_missed,
            link_speed_mbps=link_speed,
            drop_rate_pct=drop_rate_pct,
        )

    @property
    def mode(self) -> CaptureMode:
        """The capture mode this adapter implements."""
        return CaptureMode.BRIDGE

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _read_sysfs_int(path: str) -> int:
        """Read a sysfs file and return its contents as an integer.

        Returns 0 if the file does not exist, is not readable, or does
        not contain a valid integer.
        """
        try:
            with open(path, "r") as f:
                return int(f.read().strip())
        except (FileNotFoundError, PermissionError, OSError, ValueError):
            return 0
