"""
NetTap Device Baseline Service

Tracks known devices on the network and generates alerts when new,
previously unseen devices appear. The baseline is persisted to a JSON
file on disk so it survives daemon restarts.

Each device is identified by MAC address with associated metadata
(IP, hostname, manufacturer, first_seen timestamp).
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("nettap.services.device_baseline")


class DeviceBaseline:
    """Tracks known devices and detects new device appearances."""

    def __init__(self, baseline_file: str = "/opt/nettap/data/device_baseline.json"):
        self._baseline_file = baseline_file
        self._known_devices: dict[str, dict[str, Any]] = {}  # MAC -> device info
        self._load_baseline()

    def _load_baseline(self) -> None:
        """Load known devices from disk.

        If the file does not exist or is unreadable, starts with an empty
        baseline (no error raised -- the file will be created on first save).
        """
        try:
            if os.path.exists(self._baseline_file):
                with open(self._baseline_file, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    if isinstance(data, dict):
                        self._known_devices = data
                        logger.info(
                            "Loaded device baseline with %d devices from %s",
                            len(self._known_devices),
                            self._baseline_file,
                        )
                    else:
                        logger.warning(
                            "Baseline file %s has unexpected format, starting fresh",
                            self._baseline_file,
                        )
                        self._known_devices = {}
            else:
                logger.info(
                    "No baseline file at %s, starting with empty baseline",
                    self._baseline_file,
                )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Failed to load baseline from %s: %s -- starting fresh",
                self._baseline_file,
                exc,
            )
            self._known_devices = {}

    def _save_baseline(self) -> None:
        """Persist known devices to disk.

        Creates parent directories if they do not exist.
        """
        try:
            parent_dir = os.path.dirname(self._baseline_file)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            with open(self._baseline_file, "w", encoding="utf-8") as fh:
                json.dump(self._known_devices, fh, indent=2)
            logger.debug(
                "Saved device baseline (%d devices) to %s",
                len(self._known_devices),
                self._baseline_file,
            )
        except OSError as exc:
            logger.error(
                "Failed to save baseline to %s: %s",
                self._baseline_file,
                exc,
            )
            raise

    def check_devices(self, current_devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Compare current device list against baseline.

        Args:
            current_devices: List of device dicts, each with keys:
                mac: str (required -- used as unique identifier)
                ip: str
                hostname: str | None
                manufacturer: str | None
                first_seen: str (ISO timestamp)

        Returns:
            List of new device alert dicts for devices not in the baseline:
            [{
                type: 'new_device',
                mac: str,
                ip: str,
                hostname: str | None,
                manufacturer: str | None,
                first_seen: str,
                message: str
            }]

        Side effect:
            Does NOT automatically add new devices to the baseline.
            The caller must explicitly call add_to_baseline() to accept
            a device as known.
        """
        alerts: list[dict[str, Any]] = []

        for device in current_devices:
            mac = device.get("mac", "")
            if not mac:
                continue

            # Normalise MAC to uppercase for consistent comparison
            mac_normalised = mac.strip().upper()

            if mac_normalised not in self._known_devices:
                ip = device.get("ip", "unknown")
                hostname = device.get("hostname")
                manufacturer = device.get("manufacturer")
                first_seen = device.get(
                    "first_seen",
                    datetime.now(timezone.utc).isoformat(),
                )

                # Build a human-readable message
                if manufacturer:
                    message = f"New device detected: {manufacturer} ({mac_normalised}) at {ip}"
                else:
                    message = f"New device detected: {mac_normalised} at {ip}"

                alerts.append({
                    "type": "new_device",
                    "mac": mac_normalised,
                    "ip": ip,
                    "hostname": hostname,
                    "manufacturer": manufacturer,
                    "first_seen": first_seen,
                    "message": message,
                })

        return alerts

    def add_to_baseline(self, mac: str, device_info: dict[str, Any]) -> None:
        """Add a device to the known baseline.

        Args:
            mac: The device MAC address (will be normalised to uppercase).
            device_info: Metadata dict (ip, hostname, manufacturer, first_seen, etc.).
        """
        mac_normalised = mac.strip().upper()
        self._known_devices[mac_normalised] = {
            **device_info,
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_baseline()
        logger.info("Added device %s to baseline", mac_normalised)

    def remove_from_baseline(self, mac: str) -> bool:
        """Remove a device from the known baseline.

        Args:
            mac: The device MAC address.

        Returns:
            True if the device was found and removed, False otherwise.
        """
        mac_normalised = mac.strip().upper()
        if mac_normalised in self._known_devices:
            del self._known_devices[mac_normalised]
            self._save_baseline()
            logger.info("Removed device %s from baseline", mac_normalised)
            return True
        return False

    def get_baseline(self) -> dict[str, dict[str, Any]]:
        """Return a copy of the current baseline."""
        return dict(self._known_devices)

    def get_baseline_count(self) -> int:
        """Return number of known devices in the baseline."""
        return len(self._known_devices)

    def clear_baseline(self) -> None:
        """Reset baseline to empty and persist to disk."""
        self._known_devices = {}
        self._save_baseline()
        logger.info("Baseline cleared")
