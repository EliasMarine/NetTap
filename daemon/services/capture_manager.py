"""
NetTap Capture Manager — Abstract base class for capture modes.

NetTap supports three capture modes:
    - DHCP gateway: NetTap hands out addresses on its own subnet and routes
      devices to the router, so capture sees each device before the router's NAT
    - Mirror/SPAN: Passive listener on a switch port mirror (single NIC, no IP)
    - Bridge: Inline transparent tap between modem and router (br0)

This module defines the CaptureMode enum and the CaptureManager abstract base
class that both modes implement. Downstream code calls get_capture_interface()
to determine which interface Zeek/Suricata/Arkime should capture on — never
hardcoding br0 or any specific NIC name.
"""

import enum
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("nettap.services.capture_manager")


class CaptureMode(enum.Enum):
    """Supported capture modes."""

    BRIDGE = "bridge"
    MIRROR = "mirror"
    DHCP_GATEWAY = "dhcp_gateway"


@dataclass
class CaptureHealth:
    """Health status for any capture mode."""

    mode: str  # "bridge", "mirror" or "dhcp_gateway"
    status: str  # "normal", "degraded", "down", "not_configured"
    capture_interface: str  # interface being captured (br0, enp2s0, etc.)
    link_up: bool  # primary capture interface has carrier
    promisc_enabled: bool  # promiscuous mode active on capture interface
    issues: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "status": self.status,
            "capture_interface": self.capture_interface,
            "link_up": self.link_up,
            "promisc_enabled": self.promisc_enabled,
            "issues": self.issues,
            **self.extra,
        }


# OLD CODE START — NET-167: counted host drops twice; the kernel already includes them in
# rx_packets (rtnl_link_stats64), so the share read low (100 drops in 1,000 packets: 9.09%)
# def packet_loss_pct(rx_packets: int, rx_dropped: int, rx_missed_errors: int) -> float:
#     """S9: the one loss rate every capture mode reports, unrounded so a real loss never reads 0.
#
#     Lost = kernel drops + NIC misses (neither is in rx_packets), as a share of every
#     packet that reached the port. The counters are cumulative since they last reset.
#     """
#     lost = rx_dropped + rx_missed_errors
#     arrived = rx_packets + lost
#     return lost / arrived * 100 if arrived else 0.0
# OLD CODE END
def packet_loss_pct(rx_packets: int, rx_dropped: int, rx_missed_errors: int) -> float:
    """S9: the one loss rate every capture mode reports, unrounded so a real loss never reads 0.

    Kernel semantics (rtnl_link_stats64): rx_packets already counts the packets the host
    dropped (rx_dropped); rx_missed_errors are packets the device dropped before the host saw
    them, so they are not in rx_packets. Lost = rx_dropped + rx_missed_errors, as a share of
    rx_packets + rx_missed_errors. Cumulative since the counters last reset; not clamped.
    """
    lost = rx_dropped + rx_missed_errors
    arrived = rx_packets + rx_missed_errors
    return lost / arrived * 100 if arrived else 0.0


@dataclass
class CaptureStats:
    """Capture statistics for any capture mode."""

    capture_interface: str
    rx_bytes: int = 0
    tx_bytes: int = 0
    rx_packets: int = 0
    tx_packets: int = 0
    rx_dropped: int = 0
    rx_missed_errors: int = 0
    link_speed_mbps: int = 0
    drop_rate_pct: float = 0.0

    def to_dict(self) -> dict:
        return {
            "capture_interface": self.capture_interface,
            "rx_bytes": self.rx_bytes,
            "tx_bytes": self.tx_bytes,
            "rx_packets": self.rx_packets,
            "tx_packets": self.tx_packets,
            "rx_dropped": self.rx_dropped,
            "rx_missed_errors": self.rx_missed_errors,
            "link_speed_mbps": self.link_speed_mbps,
            "drop_rate_pct": self.drop_rate_pct,
        }


class CaptureManager(ABC):
    """Abstract base class for capture mode managers.

    Both BridgeCaptureAdapter and MirrorManager implement this interface.
    The daemon instantiates the correct one based on the capture mode config.
    """

    @abstractmethod
    async def setup(self) -> dict:
        """Configure the capture interface(s).

        Returns:
            Dict with setup results (success, warnings, errors).
        """

    @abstractmethod
    async def teardown(self) -> dict:
        """Deconfigure the capture interface(s).

        Returns:
            Dict with teardown results.
        """

    @abstractmethod
    async def get_health(self) -> CaptureHealth:
        """Get current capture health status.

        Returns:
            CaptureHealth dataclass with mode-agnostic health info.
        """

    @abstractmethod
    def get_capture_interface(self) -> str:
        """Get the interface name that capture tools should listen on.

        Returns:
            Interface name string (e.g., 'br0' for bridge, 'enp2s0' for mirror).
        """

    @abstractmethod
    async def get_stats(self) -> CaptureStats:
        """Get capture interface statistics (counters, drops, speed).

        Returns:
            CaptureStats dataclass with interface metrics.
        """

    @property
    @abstractmethod
    def mode(self) -> CaptureMode:
        """The capture mode this manager implements."""

    async def reconcile(self) -> None:
        """Re-apply runtime state that has gone missing (addresses, rules, processes).

        Called every capture-health interval, so it must be cheap and must
        never raise. The default is a no-op for modes with nothing to re-apply.
        """
