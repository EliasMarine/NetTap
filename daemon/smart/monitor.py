"""
NetTap SMART Monitor — Phase 2 Expanded Implementation

Monitors SSD/NVMe health via smartctl with support for both NVMe and SATA
drives, TBW calculation, temperature monitoring, and an extensible alert
system with configurable callbacks.

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

import subprocess
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Callable

logger = logging.getLogger("nettap.smart")


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
    """Monitors NVMe and SATA/SSD health using smartmontools.

    Supports auto-detection of device type (NVMe vs SATA), extracts
    device-specific metrics, calculates TBW, and fires alerts via
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

    # ------------------------------------------------------------------
    # Raw data retrieval
    # ------------------------------------------------------------------

    def get_raw_data(self) -> dict:
        """Query SMART health data from the drive via smartctl JSON output.

        Returns:
            Parsed JSON dict from smartctl, or empty dict on failure.
        """
        try:
            result = subprocess.run(
                ["smartctl", "-j", "-a", self.device],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # smartctl may return non-zero exit codes for certain conditions
            # (e.g., SMART warnings) but still produce valid JSON output
            self._raw_data = json.loads(result.stdout)
            return self._raw_data
        except (subprocess.SubprocessError, json.JSONDecodeError) as e:
            logger.error("Failed to read SMART data from %s: %s", self.device, e)
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
        """Extract health metrics from NVMe smartctl JSON output.

        NVMe drives expose metrics through the
        nvme_smart_health_information_log section of smartctl output.

        Returns dict with normalized metric keys.
        """
        nvme_log = data.get("nvme_smart_health_information_log", {})

        # Temperature: smartctl provides temperature in the top-level
        # "temperature" object and inside the nvme health log
        temperature_c = None
        temp_obj = data.get("temperature", {})
        if "current" in temp_obj:
            temperature_c = temp_obj["current"]
        elif "temperature" in nvme_log:
            temperature_c = nvme_log["temperature"]

        percentage_used = nvme_log.get("percentage_used")
        power_on_hours = nvme_log.get("power_on_hours")

        # TBW calculation:
        # data_units_written is in 512-byte units * 1000
        # So actual bytes = data_units_written * 512 * 1000
        data_units_written = nvme_log.get("data_units_written")
        total_bytes_written = None
        if data_units_written is not None:
            total_bytes_written = data_units_written * self.NVME_DATA_UNIT_BYTES

        data_units_read = nvme_log.get("data_units_read")
        total_bytes_read = None
        if data_units_read is not None:
            total_bytes_read = data_units_read * self.NVME_DATA_UNIT_BYTES

        media_errors = nvme_log.get("media_errors")
        critical_warning = nvme_log.get("critical_warning")

        return {
            "temperature_c": temperature_c,
            "percentage_used": percentage_used,
            "power_on_hours": power_on_hours,
            "total_bytes_written": total_bytes_written,
            "total_bytes_read": total_bytes_read,
            "media_errors": media_errors,
            "critical_warning": critical_warning,
            "reallocated_sectors": None,  # Not applicable for NVMe
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
        """Extract model name and serial number from smartctl output.

        Returns:
            Tuple of (model_name, serial_number). Uses "Unknown" as fallback.
        """
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

        # Check smartctl overall health assessment
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
            Dict representation of SmartMetrics.
        """
        metrics = self.get_metrics()
        return metrics.to_dict()
