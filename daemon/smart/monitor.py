"""
NetTap SMART Monitor — Phase 2 Expanded Implementation

Monitors SSD/NVMe health via nvme-cli (primary for NVMe) and smartctl
(fallback for SATA). Supports both NVMe and SATA drives, TBW calculation,
temperature monitoring, and an extensible alert system with configurable
callbacks.

nvme-cli speaks directly to the NVMe driver via ioctl — no SCSI
translation layer. This gives more reliable results than smartctl for
NVMe drives. smartctl is retained as fallback for SATA/SSD devices.

Phase 1 code is preserved in OLD CODE blocks below per project code
preservation policy.
"""

# =============================================================================
# OLD CODE START — Phase 1 SmartMonitor (single NVMe, basic percentage_used)
# Replaced by Phase 2 multi-device, multi-metric implementation with alerting.
# =============================================================================
#
# """
# NetTap SMART Monitor
#
# Monitors SSD health via smartctl and alerts when drive
# health degrades beyond acceptable thresholds.
# """
#
# import subprocess
# import json
# import logging
#
# logger = logging.getLogger("nettap.smart")
#
#
# class SmartMonitor:
#     """Monitors NVMe/SSD health using smartmontools."""
#
#     def __init__(self, device: str = "/dev/nvme0n1"):
#         self.device = device
#
#     def get_health(self) -> dict:
#         """Query SMART health data from the drive."""
#         try:
#             result = subprocess.run(
#                 ["smartctl", "-j", "-a", self.device],
#                 capture_output=True,
#                 text=True,
#                 timeout=10,
#             )
#             return json.loads(result.stdout)
#         except (subprocess.SubprocessError, json.JSONDecodeError) as e:
#             logger.error("Failed to read SMART data: %s", e)
#             return {}
#
#     def get_percentage_used(self) -> int | None:
#         """Return the NVMe percentage_used value (0-100+)."""
#         health = self.get_health()
#         nvme_attrs = health.get("nvme_smart_health_information_log", {})
#         return nvme_attrs.get("percentage_used")
#
#     def check_health(self, warn_threshold: int = 80) -> bool:
#         """Returns True if drive health is acceptable."""
#         pct = self.get_percentage_used()
#         if pct is None:
#             logger.warning("Could not determine drive wear level")
#             return True  # Assume OK if we can't read it
#         if pct >= warn_threshold:
#             logger.warning(
#                 "SSD wear level %d%% exceeds threshold %d%%",
#                 pct,
#                 warn_threshold,
#             )
#             return False
#         logger.info("SSD wear level: %d%%", pct)
#         return True
#
# OLD CODE END
# =============================================================================

from __future__ import annotations

import glob as globmod
import os
import subprocess
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("nettap.smart")


def auto_detect_device() -> str:
    """Auto-detect the primary storage device for SMART monitoring.

    Checks common NVMe and SATA device paths in order of likelihood.
    Falls back to /dev/nvme0n1 if nothing is found.
    """
    # Try NVMe devices first (most common on N100 mini PCs)
    nvme_devices = sorted(globmod.glob("/dev/nvme[0-9]n[0-9]"))
    if nvme_devices:
        logger.info("SMART auto-detect: found NVMe device %s", nvme_devices[0])
        return nvme_devices[0]

    # Try SATA/SSD devices
    sata_devices = sorted(globmod.glob("/dev/sd[a-z]"))
    if sata_devices:
        logger.info("SMART auto-detect: found SATA device %s", sata_devices[0])
        return sata_devices[0]

    # Try virtio (VMs)
    vd_devices = sorted(globmod.glob("/dev/vd[a-z]"))
    if vd_devices:
        logger.info("SMART auto-detect: found virtio device %s", vd_devices[0])
        return vd_devices[0]

    logger.warning("SMART auto-detect: no block devices found, defaulting to /dev/nvme0n1")
    return "/dev/nvme0n1"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class AlertLevel(Enum):
    """Severity levels for SMART health alerts."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class SmartAlert:
    """Represents a single SMART health alert."""

    level: AlertLevel
    message: str
    metric_name: str
    value: int | float | None
    threshold: int | float | None
    timestamp: str  # ISO 8601

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict representation."""
        return {
            "level": self.level.value,
            "message": self.message,
            "metric_name": self.metric_name,
            "value": self.value,
            "threshold": self.threshold,
            "timestamp": self.timestamp,
        }


@dataclass
class SmartMetrics:
    """Structured SMART health metrics for NVMe or SATA drives."""

    device: str
    device_type: str  # "nvme" or "sata"
    model: str
    serial: str
    temperature_c: int | None
    percentage_used: int | None
    power_on_hours: int | None
    total_bytes_written: int | None  # TBW in bytes
    total_bytes_read: int | None
    media_errors: int | None  # NVMe specific
    reallocated_sectors: int | None  # SATA specific
    healthy: bool
    warnings: list[str] = field(default_factory=list)
    timestamp: str = ""  # ISO 8601, set at creation time

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict representation."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Built-in alert callback
# ---------------------------------------------------------------------------


def log_alert(alert: SmartAlert) -> None:
    """Default alert callback — logs the alert at the appropriate severity."""
    log_level_map = {
        AlertLevel.INFO: logging.INFO,
        AlertLevel.WARNING: logging.WARNING,
        AlertLevel.CRITICAL: logging.CRITICAL,
    }
    log_level = log_level_map.get(alert.level, logging.WARNING)
    logger.log(
        log_level,
        "SMART Alert [%s] %s: %s (value=%s, threshold=%s)",
        alert.level.value.upper(),
        alert.metric_name,
        alert.message,
        alert.value,
        alert.threshold,
    )


# ---------------------------------------------------------------------------
# Alert thresholds configuration
# ---------------------------------------------------------------------------


@dataclass
class AlertThresholds:
    """Configurable thresholds for SMART metric alerting."""

    temp_warn_c: int = 70
    temp_crit_c: int = 80
    wear_warn_pct: int = 80
    wear_crit_pct: int = 95
    media_errors_warn: int = 0  # Any media errors trigger warning
    reallocated_sectors_warn: int = 100


# ---------------------------------------------------------------------------
# Main monitor class
# ---------------------------------------------------------------------------


class SmartMonitor:
    """Monitors NVMe and SATA/SSD health using nvme-cli and smartmontools.

    Uses nvme-cli (``nvme smart-log``) as the primary tool for NVMe drives
    and smartctl as fallback for SATA/SSD devices. Auto-detects device type,
    extracts device-specific metrics, calculates TBW, and fires alerts via
    configurable callbacks.

    Args:
        device: Block device path (e.g., "/dev/nvme0n1", "/dev/sda").
            Defaults to "/dev/nvme0n1".
        warn_threshold: Percentage-used level that triggers a warning
            alert (0-100). Defaults to 80.
        critical_threshold: Percentage-used level that triggers a critical
            alert (0-100). Defaults to 95.
        alert_callbacks: List of callables that accept a SmartAlert.
            The built-in log_alert is always included.
        thresholds: Optional AlertThresholds override. If provided,
            warn_threshold and critical_threshold are ignored in favor
            of thresholds.wear_warn_pct and thresholds.wear_crit_pct.
    """

    # NVMe data_units are 512-byte sectors in groups of 1000 (512 * 1000 bytes)
    NVME_DATA_UNIT_BYTES = 512 * 1000

    def __init__(
        self,
        device: str = "/dev/nvme0n1",
        warn_threshold: int = 80,
        critical_threshold: int = 95,
        alert_callbacks: list[Callable[[SmartAlert], None]] | None = None,
        thresholds: AlertThresholds | None = None,
    ):
        self.device = device
        self._raw_data: dict = {}
        self._device_type: str | None = None

        # Configure thresholds
        if thresholds:
            self.thresholds = thresholds
        else:
            self.thresholds = AlertThresholds(
                wear_warn_pct=warn_threshold,
                wear_crit_pct=critical_threshold,
            )

        # Alert callbacks — always include the built-in logger
        self.alert_callbacks: list[Callable[[SmartAlert], None]] = [log_alert]
        if alert_callbacks:
            self.alert_callbacks.extend(alert_callbacks)
        logger.info(
            "SmartMonitor initialized: device=%s, thresholds(temp_warn=%dC, temp_crit=%dC, wear_warn=%d%%, wear_crit=%d%%)",
            self.device,
            self.thresholds.temp_warn_c,
            self.thresholds.temp_crit_c,
            self.thresholds.wear_warn_pct,
            self.thresholds.wear_crit_pct,
        )

    # ------------------------------------------------------------------
    # Raw data retrieval
    # ------------------------------------------------------------------

    def _get_nvme_controller(self) -> str:
        """Derive the NVMe controller device from the namespace device.

        nvme-cli admin commands target the controller (/dev/nvme0), not the
        namespace (/dev/nvme0n1). This extracts the controller path.

        Returns:
            Controller device path (e.g., "/dev/nvme0").
        """
        import re
        m = re.match(r"(/dev/nvme\d+)", self.device)
        if m:
            return m.group(1)
        return self.device

    def _get_nvme_raw_data(self) -> dict:
        """Query NVMe SMART data via nvme-cli (primary tool for NVMe).

        Uses ``nvme smart-log /dev/nvmeX -o json`` which speaks directly
        to the NVMe driver via ioctl — no SCSI translation layer.

        Returns:
            Parsed JSON dict from nvme-cli, or empty dict on failure.
        """
        ctrl = self._get_nvme_controller()
        try:
            result = subprocess.run(
                ["nvme", "smart-log", ctrl, "-o", "json"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                logger.warning(
                    "nvme smart-log exited with code %d for %s: %s",
                    result.returncode,
                    ctrl,
                    result.stderr.strip() if result.stderr else "",
                )
                return {}
            data = json.loads(result.stdout)
            logger.debug("nvme smart-log returned %d fields for %s", len(data), ctrl)
            return data
        except FileNotFoundError:
            logger.warning("nvme-cli not installed — falling back to smartctl")
            return {}
        except subprocess.SubprocessError as e:
            logger.error("Failed to run nvme smart-log for %s: %s", ctrl, e)
            return {}
        except json.JSONDecodeError as e:
            logger.error("Failed to parse nvme-cli JSON for %s: %s", ctrl, e)
            return {}

    def _get_nvme_identity(self) -> tuple[str, str]:
        """Get NVMe model and serial via nvme-cli id-ctrl.

        Returns:
            Tuple of (model_name, serial_number). Uses "Unknown" as fallback.
        """
        ctrl = self._get_nvme_controller()
        try:
            result = subprocess.run(
                ["nvme", "id-ctrl", ctrl, "-o", "json"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                return "Unknown", "Unknown"
            data = json.loads(result.stdout)
            model = (data.get("mn") or "Unknown").strip()
            serial = (data.get("sn") or "Unknown").strip()
            return model, serial
        except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError):
            return "Unknown", "Unknown"

    def get_raw_data(self) -> dict:
        """Query SMART health data from the drive.

        For NVMe devices, uses nvme-cli as the primary source. Falls back
        to smartctl for SATA drives or when nvme-cli is unavailable.

        Returns:
            Parsed JSON dict, or empty dict on failure.
        """
        # Try nvme-cli first for NVMe devices
        if "nvme" in self.device.lower():
            nvme_data = self._get_nvme_raw_data()
            if nvme_data:
                # Wrap in a structure compatible with the rest of the code
                self._raw_data = {"_source": "nvme-cli", "_nvme_smart_log": nvme_data}
                return self._raw_data
            logger.info("nvme-cli returned no data for %s, falling back to smartctl", self.device)

        # Fallback: smartctl (SATA primary, NVMe fallback)
        try:
            result = subprocess.run(
                ["smartctl", "-j", "-a", self.device],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # smartctl may return non-zero exit codes for certain conditions
            # (e.g., SMART warnings) but still produce valid JSON output
            if result.returncode != 0:
                logger.warning(
                    "smartctl exited with code %d for %s (may still have valid data)",
                    result.returncode,
                    self.device,
                )
                if result.stderr.strip():
                    logger.warning("smartctl stderr: %s", result.stderr.strip())
            self._raw_data = json.loads(result.stdout)
            return self._raw_data
        except subprocess.SubprocessError as e:
            logger.error("Failed to run smartctl for %s: %s", self.device, e)
            self._raw_data = {}
            return {}
        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse smartctl JSON for %s: %s (stderr: %s)",
                self.device,
                e,
                result.stderr.strip() if result.stderr else "none",
            )
            self._raw_data = {}
            return {}

    # ------------------------------------------------------------------
    # Device type detection
    # ------------------------------------------------------------------

    def detect_device_type(self, raw_data: dict | None = None) -> str:
        """Auto-detect device type (NVMe vs SATA) from smartctl output.

        The detection checks multiple indicators in the smartctl JSON:
        1. The "device.type" field (most reliable)
        2. Presence of nvme_smart_health_information_log (NVMe-specific)
        3. Presence of ata_smart_attributes (SATA-specific)
        4. Device path heuristic (/dev/nvme* vs /dev/sd*)

        Args:
            raw_data: Pre-fetched smartctl output. If None, fetches fresh data.

        Returns:
            "nvme" or "sata"
        """
        data = raw_data or self._raw_data or self.get_raw_data()

        # nvme-cli source is always NVMe
        if data.get("_source") == "nvme-cli":
            self._device_type = "nvme"
            return "nvme"

        # Check device.type from smartctl
        device_info = data.get("device", {})
        device_type = device_info.get("type", "").lower()
        if "nvme" in device_type:
            self._device_type = "nvme"
            return "nvme"

        # Check for NVMe-specific data section
        if "nvme_smart_health_information_log" in data:
            self._device_type = "nvme"
            return "nvme"

        # Check for SATA-specific data section
        if "ata_smart_attributes" in data:
            self._device_type = "sata"
            return "sata"

        # Fallback: device path heuristic
        if "nvme" in self.device.lower():
            self._device_type = "nvme"
            return "nvme"

        # Default to SATA if we cannot determine the type
        self._device_type = "sata"
        return "sata"

    # ------------------------------------------------------------------
    # Metric extraction — NVMe
    # ------------------------------------------------------------------

    def _extract_nvme_metrics(self, data: dict) -> dict:
        """Extract health metrics from NVMe data.

        Supports two data sources:
        1. nvme-cli (``nvme smart-log -o json``) — primary, via _nvme_smart_log key
        2. smartctl JSON — fallback, via nvme_smart_health_information_log key

        nvme-cli reports temperature in Kelvin; smartctl in Celsius.

        Returns dict with normalized metric keys.
        """
        # Determine data source
        nvme_cli_data = data.get("_nvme_smart_log", {})
        smartctl_log = data.get("nvme_smart_health_information_log", {})

        if nvme_cli_data:
            return self._extract_nvme_cli_metrics(nvme_cli_data)

        if smartctl_log:
            return self._extract_nvme_smartctl_metrics(data, smartctl_log)

        logger.warning(
            "No NVMe SMART data found for %s. Check SYS_ADMIN capability "
            "and /dev mount. Available keys: %s",
            self.device,
            list(data.keys()),
        )
        return {
            "temperature_c": None, "percentage_used": None,
            "power_on_hours": None, "total_bytes_written": None,
            "total_bytes_read": None, "media_errors": None,
            "critical_warning": None, "reallocated_sectors": None,
        }

    @staticmethod
    def _safe_int(value) -> int | None:
        """Convert a value to int, handling nvme-cli's string-typed numbers.

        nvme-cli 2.x returns large numeric values as JSON strings
        (e.g., "data_units_written":"16375391", "media_errors":"0").
        This safely converts both int and str to int.
        """
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    def _extract_nvme_cli_metrics(self, nvme_log: dict) -> dict:
        """Extract metrics from nvme-cli smart-log JSON output.

        Field names follow the NVMe spec as output by nvme-cli:
        temperature (Kelvin), avail_spare, percent_used, data_units_written,
        power_on_hours, media_errors, etc.

        Note: nvme-cli 2.x returns some numeric fields as JSON strings
        (large values). All fields are passed through _safe_int().
        """
        # Temperature: nvme-cli reports in Kelvin — convert to Celsius
        temperature_c = None
        temp_raw = self._safe_int(nvme_log.get("temperature"))
        if temp_raw is not None:
            # nvme-cli returns Kelvin (e.g., 311 = 38C)
            temperature_c = temp_raw - 273 if temp_raw > 200 else temp_raw
            logger.debug("NVMe temperature from nvme-cli: %dK -> %dC", temp_raw, temperature_c)

        percentage_used = self._safe_int(nvme_log.get("percent_used"))
        power_on_hours = self._safe_int(nvme_log.get("power_on_hours"))

        # TBW: data_units_written * 512 * 1000 bytes
        data_units_written = self._safe_int(nvme_log.get("data_units_written"))
        total_bytes_written = None
        if data_units_written is not None:
            total_bytes_written = data_units_written * self.NVME_DATA_UNIT_BYTES

        data_units_read = self._safe_int(nvme_log.get("data_units_read"))
        total_bytes_read = None
        if data_units_read is not None:
            total_bytes_read = data_units_read * self.NVME_DATA_UNIT_BYTES

        media_errors = self._safe_int(nvme_log.get("media_errors"))
        critical_warning = self._safe_int(nvme_log.get("critical_warning"))

        return {
            "temperature_c": temperature_c,
            "percentage_used": percentage_used,
            "power_on_hours": power_on_hours,
            "total_bytes_written": total_bytes_written,
            "total_bytes_read": total_bytes_read,
            "media_errors": media_errors,
            "critical_warning": critical_warning,
            "reallocated_sectors": None,
        }

    def _extract_nvme_smartctl_metrics(self, data: dict, nvme_log: dict) -> dict:
        """Extract metrics from smartctl JSON (fallback for NVMe).

        Used when nvme-cli is unavailable. Field names follow smartctl's
        nvme_smart_health_information_log structure.
        """
        # Temperature: try multiple fallback paths for firmware variants
        temperature_c = None
        if "temperature" in nvme_log and nvme_log["temperature"] is not None:
            temperature_c = nvme_log["temperature"]
        elif data.get("temperature", {}).get("current") is not None:
            temperature_c = data["temperature"]["current"]
        else:
            sensors = nvme_log.get("temperature_sensors")
            if sensors and isinstance(sensors, list) and len(sensors) > 0:
                if sensors[0] is not None and sensors[0] != 0:
                    temperature_c = sensors[0]

        percentage_used = nvme_log.get("percentage_used")

        power_on_hours = nvme_log.get("power_on_hours")
        if power_on_hours is None:
            poh_top = data.get("power_on_time", {})
            if isinstance(poh_top, dict) and "hours" in poh_top:
                power_on_hours = poh_top["hours"]

        data_units_written = nvme_log.get("data_units_written")
        total_bytes_written = None
        if data_units_written is not None:
            total_bytes_written = data_units_written * self.NVME_DATA_UNIT_BYTES

        data_units_read = nvme_log.get("data_units_read")
        total_bytes_read = None
        if data_units_read is not None:
            total_bytes_read = data_units_read * self.NVME_DATA_UNIT_BYTES

        return {
            "temperature_c": temperature_c,
            "percentage_used": percentage_used,
            "power_on_hours": power_on_hours,
            "total_bytes_written": total_bytes_written,
            "total_bytes_read": total_bytes_read,
            "media_errors": nvme_log.get("media_errors"),
            "critical_warning": nvme_log.get("critical_warning"),
            "reallocated_sectors": None,
        }

    # ------------------------------------------------------------------
    # Metric extraction — SATA
    # ------------------------------------------------------------------

    def _extract_sata_metrics(self, data: dict) -> dict:
        """Extract health metrics from SATA/SSD smartctl JSON output.

        SATA drives use ATA SMART attributes with numeric IDs.
        Key attribute IDs:
          - 5:   Reallocated_Sector_Ct
          - 9:   Power_On_Hours
          - 177: Wear_Leveling_Count
          - 194: Temperature_Celsius
          - 241: Total_LBAs_Written

        Returns dict with normalized metric keys.
        """
        attrs = data.get("ata_smart_attributes", {}).get("table", [])

        # Build a lookup by attribute ID for fast access
        attr_by_id: dict[int, dict] = {}
        for attr in attrs:
            attr_id = attr.get("id")
            if attr_id is not None:
                attr_by_id[attr_id] = attr

        # Temperature — try attribute 194, fall back to top-level
        temperature_c = None
        temp_attr = attr_by_id.get(194)
        if temp_attr:
            temperature_c = temp_attr.get("raw", {}).get("value")
            # Some drives store temp in format "34 (Min/Max 20/45)"
            # The raw value is usually just the numeric temperature
            if temperature_c is not None and temperature_c > 200:
                # Likely a packed value; low byte is the temperature
                temperature_c = temperature_c & 0xFF
        if temperature_c is None:
            temp_obj = data.get("temperature", {})
            temperature_c = temp_obj.get("current")

        # Wear level / percentage used
        # Attribute 177 (Wear_Leveling_Count) raw value is typically
        # remaining wear as a percentage (0-100) on Samsung/Micron SSDs.
        # We invert it to get "percentage used" for consistency with NVMe.
        percentage_used = None
        wear_attr = attr_by_id.get(177)
        if wear_attr:
            raw_val = wear_attr.get("value")  # "value" is normalized 0-100
            if raw_val is not None:
                # Normalized value is remaining life (100 = new, 0 = worn)
                percentage_used = max(0, 100 - raw_val)

        # Power on hours — attribute 9
        power_on_hours = None
        poh_attr = attr_by_id.get(9)
        if poh_attr:
            power_on_hours = poh_attr.get("raw", {}).get("value")

        # TBW from Total_LBAs_Written (attribute 241)
        # Each LBA is typically 512 bytes
        total_bytes_written = None
        lbas_written_attr = attr_by_id.get(241)
        if lbas_written_attr:
            lbas = lbas_written_attr.get("raw", {}).get("value")
            if lbas is not None:
                # Determine sector size; default to 512 bytes
                sector_size = data.get("logical_block_size", 512)
                total_bytes_written = lbas * sector_size

        # Total bytes read — attribute 242 (Total_LBAs_Read)
        total_bytes_read = None
        lbas_read_attr = attr_by_id.get(242)
        if lbas_read_attr:
            lbas = lbas_read_attr.get("raw", {}).get("value")
            if lbas is not None:
                sector_size = data.get("logical_block_size", 512)
                total_bytes_read = lbas * sector_size

        # Reallocated sectors — attribute 5
        reallocated_sectors = None
        realloc_attr = attr_by_id.get(5)
        if realloc_attr:
            reallocated_sectors = realloc_attr.get("raw", {}).get("value")

        return {
            "temperature_c": temperature_c,
            "percentage_used": percentage_used,
            "power_on_hours": power_on_hours,
            "total_bytes_written": total_bytes_written,
            "total_bytes_read": total_bytes_read,
            "media_errors": None,  # Not applicable for SATA
            "reallocated_sectors": reallocated_sectors,
        }

    # ------------------------------------------------------------------
    # Device identity extraction
    # ------------------------------------------------------------------

    def _extract_identity(self, data: dict) -> tuple[str, str]:
        """Extract model name and serial number.

        For nvme-cli sources, uses ``nvme id-ctrl`` to get identity.
        For smartctl sources, reads model_name and serial_number from JSON.

        Returns:
            Tuple of (model_name, serial_number). Uses "Unknown" as fallback.
        """
        if data.get("_source") == "nvme-cli":
            return self._get_nvme_identity()
        model = data.get("model_name") or data.get("model_family") or "Unknown"
        serial = data.get("serial_number", "Unknown")
        return model, serial

    # ------------------------------------------------------------------
    # Alert evaluation
    # ------------------------------------------------------------------

    def _evaluate_alerts(self, metrics: SmartMetrics) -> list[SmartAlert]:
        """Evaluate SMART metrics against alert thresholds.

        Generates SmartAlert objects for any metric that exceeds its
        configured threshold. All generated alerts are also dispatched
        to the registered alert callbacks.

        Args:
            metrics: The SmartMetrics to evaluate.

        Returns:
            List of generated SmartAlert objects.
        """
        alerts: list[SmartAlert] = []
        now = datetime.now(timezone.utc).isoformat()

        # --- Temperature alerts ---
        if metrics.temperature_c is not None:
            if metrics.temperature_c > self.thresholds.temp_crit_c:
                alerts.append(
                    SmartAlert(
                        level=AlertLevel.CRITICAL,
                        message=(
                            f"Drive temperature {metrics.temperature_c}C exceeds "
                            f"critical threshold {self.thresholds.temp_crit_c}C"
                        ),
                        metric_name="temperature_c",
                        value=metrics.temperature_c,
                        threshold=self.thresholds.temp_crit_c,
                        timestamp=now,
                    )
                )
            elif metrics.temperature_c > self.thresholds.temp_warn_c:
                alerts.append(
                    SmartAlert(
                        level=AlertLevel.WARNING,
                        message=(
                            f"Drive temperature {metrics.temperature_c}C exceeds "
                            f"warning threshold {self.thresholds.temp_warn_c}C"
                        ),
                        metric_name="temperature_c",
                        value=metrics.temperature_c,
                        threshold=self.thresholds.temp_warn_c,
                        timestamp=now,
                    )
                )

        # --- Wear level alerts ---
        if metrics.percentage_used is not None:
            if metrics.percentage_used >= self.thresholds.wear_crit_pct:
                alerts.append(
                    SmartAlert(
                        level=AlertLevel.CRITICAL,
                        message=(
                            f"SSD wear level {metrics.percentage_used}% exceeds "
                            f"critical threshold {self.thresholds.wear_crit_pct}%"
                        ),
                        metric_name="percentage_used",
                        value=metrics.percentage_used,
                        threshold=self.thresholds.wear_crit_pct,
                        timestamp=now,
                    )
                )
            elif metrics.percentage_used >= self.thresholds.wear_warn_pct:
                alerts.append(
                    SmartAlert(
                        level=AlertLevel.WARNING,
                        message=(
                            f"SSD wear level {metrics.percentage_used}% exceeds "
                            f"warning threshold {self.thresholds.wear_warn_pct}%"
                        ),
                        metric_name="percentage_used",
                        value=metrics.percentage_used,
                        threshold=self.thresholds.wear_warn_pct,
                        timestamp=now,
                    )
                )

        # --- NVMe media errors ---
        if metrics.media_errors is not None:
            if metrics.media_errors > self.thresholds.media_errors_warn:
                alerts.append(
                    SmartAlert(
                        level=AlertLevel.WARNING,
                        message=(f"NVMe media errors detected: {metrics.media_errors}"),
                        metric_name="media_errors",
                        value=metrics.media_errors,
                        threshold=self.thresholds.media_errors_warn,
                        timestamp=now,
                    )
                )

        # --- SATA reallocated sectors ---
        if metrics.reallocated_sectors is not None:
            if metrics.reallocated_sectors > self.thresholds.reallocated_sectors_warn:
                alerts.append(
                    SmartAlert(
                        level=AlertLevel.WARNING,
                        message=(
                            f"Reallocated sector count {metrics.reallocated_sectors} "
                            f"exceeds threshold {self.thresholds.reallocated_sectors_warn}"
                        ),
                        metric_name="reallocated_sectors",
                        value=metrics.reallocated_sectors,
                        threshold=self.thresholds.reallocated_sectors_warn,
                        timestamp=now,
                    )
                )

        # Dispatch alerts to all registered callbacks
        for alert in alerts:
            for callback in self.alert_callbacks:
                try:
                    callback(alert)
                except Exception as exc:
                    logger.error(
                        "Alert callback %s failed: %s",
                        callback.__name__,
                        exc,
                    )

        return alerts

    # ------------------------------------------------------------------
    # Public API — primary methods
    # ------------------------------------------------------------------

    def get_metrics(self) -> SmartMetrics:
        """Collect and return structured SMART metrics from the drive.

        This is the main method. It queries smartctl, detects the device
        type, extracts all available metrics, evaluates alert conditions,
        and returns a SmartMetrics dataclass.

        Returns:
            SmartMetrics dataclass with all available health data.
        """
        raw_data = self.get_raw_data()
        device_type = self.detect_device_type(raw_data)
        model, serial = self._extract_identity(raw_data)

        # Extract type-specific metrics
        if device_type == "nvme":
            extracted = self._extract_nvme_metrics(raw_data)
        else:
            extracted = self._extract_sata_metrics(raw_data)

        # Determine overall health status
        # Consider the drive healthy unless we find a concerning metric
        healthy = True
        warnings: list[str] = []

        # Check overall health assessment
        if raw_data.get("_source") == "nvme-cli":
            # nvme-cli: critical_warning != 0 means unhealthy
            cw = raw_data.get("_nvme_smart_log", {}).get("critical_warning")
            if cw is not None and cw != 0:
                healthy = False
                warnings.append(f"NVMe critical warning flag: {cw}")
        else:
            smart_status = raw_data.get("smart_status", {})
            if smart_status.get("passed") is False:
                healthy = False
                warnings.append("smartctl overall-health assessment: FAILED")

        metrics = SmartMetrics(
            device=self.device,
            device_type=device_type,
            model=model,
            serial=serial,
            temperature_c=extracted["temperature_c"],
            percentage_used=extracted["percentage_used"],
            power_on_hours=extracted["power_on_hours"],
            total_bytes_written=extracted["total_bytes_written"],
            total_bytes_read=extracted["total_bytes_read"],
            media_errors=extracted.get("media_errors"),
            reallocated_sectors=extracted.get("reallocated_sectors"),
            healthy=healthy,
            warnings=warnings,
        )

        # Evaluate alert thresholds and update health/warnings
        alerts = self._evaluate_alerts(metrics)
        for alert in alerts:
            metrics.warnings.append(alert.message)
            if alert.level == AlertLevel.CRITICAL:
                metrics.healthy = False

        if metrics.healthy:
            logger.info(
                "SMART health OK for %s (%s %s): temp=%sC, wear=%s%%",
                self.device,
                model,
                device_type,
                extracted["temperature_c"],
                extracted["percentage_used"],
            )
        else:
            logger.warning(
                "SMART health DEGRADED for %s (%s %s): %s",
                self.device,
                model,
                device_type,
                "; ".join(metrics.warnings),
            )

        return metrics

    def check_health(self) -> SmartMetrics:
        """Check drive health and return metrics.

        This is a convenience wrapper around get_metrics() that maintains
        backward compatibility. In Phase 1 this returned a bool; it now
        returns the full SmartMetrics object. The .healthy attribute can
        be used as the boolean equivalent.

        Returns:
            SmartMetrics with .healthy indicating overall health status.
        """
        return self.get_metrics()

    def get_status(self) -> dict:
        """Return drive health status as a JSON-serializable dict.

        Intended for use by the HTTP API endpoint that exposes SMART
        health data to the web dashboard.

        Returns:
            Dict representation of SmartMetrics, or a fallback dict with
            basic disk info from sysfs if smartctl fails completely.
        """
        metrics = self.get_metrics()
        result = metrics.to_dict()

        # If smartctl returned nothing useful, try sysfs fallback for basic info
        if not result.get("model") or result["model"] == "Unknown":
            sysfs_info = self._sysfs_fallback()
            if sysfs_info:
                result.update(sysfs_info)

        return result

    def _sysfs_fallback(self) -> dict:
        """Read basic disk info from sysfs when smartctl fails.

        This provides at least model/serial/size even when smartctl
        can't access the device (permission issues, missing capabilities).
        """
        try:
            # Extract block device name from path (e.g., /dev/nvme0n1 -> nvme0n1)
            dev_name = os.path.basename(self.device)

            # For NVMe, the sysfs path uses the controller (nvme0) not the namespace
            if dev_name.startswith("nvme"):
                # nvme0n1 -> nvme0
                model_path = f"/sys/block/{dev_name}/device/model"
                serial_path = f"/sys/block/{dev_name}/device/serial"
                size_path = f"/sys/block/{dev_name}/size"
            else:
                model_path = f"/sys/block/{dev_name}/device/model"
                serial_path = f"/sys/block/{dev_name}/device/serial"
                size_path = f"/sys/block/{dev_name}/size"

            info: dict = {}

            if os.path.exists(model_path):
                with open(model_path) as f:
                    info["model"] = f.read().strip()

            if os.path.exists(serial_path):
                with open(serial_path) as f:
                    info["serial"] = f.read().strip()

            if os.path.exists(size_path):
                with open(size_path) as f:
                    # Size is in 512-byte sectors
                    sectors = int(f.read().strip())
                    info["total_capacity_bytes"] = sectors * 512

            if info:
                logger.info("SMART sysfs fallback: found %s", info.get("model", "unknown"))

            return info
        except Exception as exc:
            logger.debug("sysfs fallback failed: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Startup self-test & diagnostics
    # ------------------------------------------------------------------

    def run_self_test(self) -> dict[str, Any]:
        """Run a startup diagnostic test and return results.

        Queries smartctl, logs full output at DEBUG level, and checks
        for missing key fields. Returns a diagnostics dict suitable
        for the /api/smart/diagnostics endpoint.

        Returns:
            Dict with keys: device, device_type, model, raw_output_available,
            missing_fields, guidance.
        """
        raw_data = self.get_raw_data()
        raw_available = bool(raw_data)

        logger.debug(
            "SMART self-test raw output for %s: %s",
            self.device,
            json.dumps(raw_data, indent=2) if raw_data else "(empty)",
        )

        device_type = self.detect_device_type(raw_data)
        model, serial = self._extract_identity(raw_data)

        # Extract metrics to check what's missing
        if device_type == "nvme":
            extracted = self._extract_nvme_metrics(raw_data)
        else:
            extracted = self._extract_sata_metrics(raw_data)

        # Check which key fields are missing
        key_fields = ["temperature_c", "percentage_used", "power_on_hours"]
        missing_fields: list[str] = []
        for field_name in key_fields:
            if extracted.get(field_name) is None:
                missing_fields.append(field_name)

        # Build guidance messages for missing fields
        guidance: list[str] = []
        if missing_fields:
            if not raw_available:
                guidance.append(
                    "smartctl returned no data — check that smartmontools is "
                    "installed and the device path is correct"
                )
            else:
                nvme_log = raw_data.get("nvme_smart_health_information_log", {})
                if device_type == "nvme" and not nvme_log:
                    guidance.append(
                        "NVMe health log empty — check /dev mount (must not "
                        "be :ro) and SYS_ADMIN + SYS_RAWIO capabilities. "
                        "nvme-cli requires SYS_ADMIN for NVMe admin commands."
                    )
                if "temperature_c" in missing_fields:
                    guidance.append(
                        "temperature field missing — check "
                        "nvme_smart_health_information_log and temperature.current"
                    )
                if "percentage_used" in missing_fields:
                    guidance.append(
                        "percentage_used field missing — NVMe health log may "
                        "not be accessible (check /dev mount and SYS_RAWIO)"
                    )
                if "power_on_hours" in missing_fields:
                    guidance.append(
                        "power_on_hours field missing — check NVMe health log "
                        "or power_on_time.hours fallback"
                    )

        # Log warnings for missing fields
        if missing_fields:
            logger.warning(
                "SMART self-test for %s: missing fields %s",
                self.device,
                missing_fields,
            )
            for msg in guidance:
                logger.warning("SMART guidance: %s", msg)
        else:
            logger.info(
                "SMART self-test for %s: all key fields present", self.device
            )

        self._diagnostics = {
            "device": self.device,
            "device_type": device_type,
            "model": model,
            "serial": serial,
            "raw_output_available": raw_available,
            "missing_fields": missing_fields,
            "guidance": guidance,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return self._diagnostics

    def get_diagnostics(self) -> dict[str, Any]:
        """Return the most recent diagnostics dict.

        If run_self_test() has not been called yet, runs it first.
        """
        if not hasattr(self, "_diagnostics") or not self._diagnostics:
            return self.run_self_test()
        return self._diagnostics

    # ------------------------------------------------------------------
    # OpenSearch indexing
    # ------------------------------------------------------------------

    def index_to_opensearch(self, metrics: SmartMetrics, client: Any) -> bool:
        """Index SMART metrics to OpenSearch for historical tracking.

        Creates one document per check in the nettap-smart-YYYY.MM.DD index.

        Args:
            metrics: The SmartMetrics to index.
            client: An opensearch-py OpenSearch client instance.

        Returns:
            True if indexing succeeded, False otherwise.
        """
        now = datetime.now(timezone.utc)
        index_name = f"nettap-smart-{now.strftime('%Y.%m.%d')}"

        doc = {
            "@timestamp": now.isoformat(),
            "device": metrics.device,
            "device_type": metrics.device_type,
            "model": metrics.model,
            "serial": metrics.serial,
            "temperature_c": metrics.temperature_c,
            "percentage_used": metrics.percentage_used,
            "power_on_hours": metrics.power_on_hours,
            "total_bytes_written": metrics.total_bytes_written,
            "total_bytes_read": metrics.total_bytes_read,
            "media_errors": metrics.media_errors,
            "reallocated_sectors": metrics.reallocated_sectors,
            "healthy": metrics.healthy,
            "warnings": metrics.warnings,
        }

        try:
            client.index(index=index_name, body=doc)
            logger.debug(
                "Indexed SMART metrics to %s for %s", index_name, metrics.device
            )
            return True
        except Exception as exc:
            logger.error(
                "Failed to index SMART metrics to %s: %s", index_name, exc
            )
            return False
