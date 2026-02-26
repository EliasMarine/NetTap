"""
NetTap SMART Monitor

Monitors SSD health via smartctl and alerts when drive
health degrades beyond acceptable thresholds.
"""

import subprocess
import json
import logging

logger = logging.getLogger("nettap.smart")


class SmartMonitor:
    """Monitors NVMe/SSD health using smartmontools."""

    def __init__(self, device: str = "/dev/nvme0n1"):
        self.device = device

    def get_health(self) -> dict:
        """Query SMART health data from the drive."""
        try:
            result = subprocess.run(
                ["smartctl", "-j", "-a", self.device],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return json.loads(result.stdout)
        except (subprocess.SubprocessError, json.JSONDecodeError) as e:
            logger.error("Failed to read SMART data: %s", e)
            return {}

    def get_percentage_used(self) -> int | None:
        """Return the NVMe percentage_used value (0-100+)."""
        health = self.get_health()
        nvme_attrs = health.get("nvme_smart_health_information_log", {})
        return nvme_attrs.get("percentage_used")

    def check_health(self, warn_threshold: int = 80) -> bool:
        """Returns True if drive health is acceptable."""
        pct = self.get_percentage_used()
        if pct is None:
            logger.warning("Could not determine drive wear level")
            return True  # Assume OK if we can't read it
        if pct >= warn_threshold:
            logger.warning(
                "SSD wear level %d%% exceeds threshold %d%%",
                pct,
                warn_threshold,
            )
            return False
        logger.info("SSD wear level: %d%%", pct)
        return True
