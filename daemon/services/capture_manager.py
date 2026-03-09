"""
NetTap Capture Manager — Abstract base class for capture modes.

NetTap supports two capture modes:
    - Bridge: Inline transparent tap between modem and router (br0)
    - Mirror/SPAN: Passive listener on a switch port mirror (single NIC, no IP)

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


@dataclass
class CaptureHealth:
    """Health status for any capture mode."""

    mode: str  # "bridge" or "mirror"
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
