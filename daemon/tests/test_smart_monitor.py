"""
Tests for daemon/smart/monitor.py — SmartMonitor.

Covers device type detection, NVMe and SATA metric extraction,
temperature / wear / media-error alerting, alert callbacks,
backward-compatible check_health, and JSON-serializable status output.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from smart.monitor import (
    AlertLevel,
    AlertThresholds,
    SmartAlert,
    SmartMetrics,
    SmartMonitor,
)


# =========================================================================
# Device type detection
# =========================================================================

class TestDetectDeviceType:

    def test_detect_device_type_nvme_from_field(self, mock_smartctl_nvme):
        """Mock smartctl with device.type='nvme' and verify detection."""
        monitor = SmartMonitor(device="/dev/sda")  # path is intentionally not nvme
        result = monitor.detect_device_type(mock_smartctl_nvme)
        assert result == "nvme"

    def test_detect_device_type_sata_from_attributes(self, mock_smartctl_sata):
        """Mock smartctl with ata_smart_attributes and verify SATA detection."""
        monitor = SmartMonitor(device="/dev/sda")
        result = monitor.detect_device_type(mock_smartctl_sata)
        assert result == "sata"

    def test_detect_device_type_nvme_from_path(self):
        """Test /dev/nvme0n1 path heuristic when JSON has no type hints."""
        monitor = SmartMonitor(device="/dev/nvme0n1")
        # Provide data that has no device.type and no NVMe/SATA specific sections
        empty_data = {"device": {}, "smart_status": {"passed": True}}
        result = monitor.detect_device_type(empty_data)
        assert result == "nvme"

    def test_detect_device_type_sata_fallback(self):
        """Test default to sata when nothing identifies the drive."""
        monitor = SmartMonitor(device="/dev/sda")
        empty_data = {"device": {}, "smart_status": {"passed": True}}
        result = monitor.detect_device_type(empty_data)
        assert result == "sata"


# =========================================================================
# NVMe metric extraction
# =========================================================================

class TestExtractNvmeMetrics:

    def test_extract_nvme_metrics_temperature(self, mock_smartctl_nvme):
        """Verify temperature extraction from NVMe data."""
        monitor = SmartMonitor()
        metrics = monitor._extract_nvme_metrics(mock_smartctl_nvme)
        assert metrics["temperature_c"] == 38

    def test_extract_nvme_metrics_tbw_calculation(self, mock_smartctl_nvme):
        """Verify data_units_written * 512 * 1000 for TBW calculation."""
        monitor = SmartMonitor()
        metrics = monitor._extract_nvme_metrics(mock_smartctl_nvme)

        expected_tbw = 43285012 * 512 * 1000
        assert metrics["total_bytes_written"] == expected_tbw

    def test_extract_nvme_metrics_percentage_used(self, mock_smartctl_nvme):
        """Verify percentage_used extracted correctly from NVMe health log."""
        monitor = SmartMonitor()
        metrics = monitor._extract_nvme_metrics(mock_smartctl_nvme)
        assert metrics["percentage_used"] == 3


# =========================================================================
# SATA metric extraction
# =========================================================================

class TestExtractSataMetrics:

    def test_extract_sata_metrics_temperature(self, mock_smartctl_sata):
        """Verify attribute 194 temperature extraction."""
        monitor = SmartMonitor(device="/dev/sda")
        metrics = monitor._extract_sata_metrics(mock_smartctl_sata)
        assert metrics["temperature_c"] == 34

    def test_extract_sata_metrics_temperature_packed(self):
        """Verify packed value (>200) handling — low byte is temperature."""
        monitor = SmartMonitor(device="/dev/sda")
        # Simulate a packed temp value like 0x0A22 = 2594 -> low byte = 0x22 = 34
        data = {
            "ata_smart_attributes": {
                "table": [
                    {
                        "id": 194,
                        "name": "Temperature_Celsius",
                        "value": 66,
                        "worst": 53,
                        "thresh": 0,
                        "raw": {"value": 2594, "string": "34 (Min/Max 20/45)"},
                    }
                ]
            }
        }
        metrics = monitor._extract_sata_metrics(data)
        # 2594 & 0xFF = 34
        assert metrics["temperature_c"] == 34

    def test_extract_sata_metrics_wear_inversion(self, mock_smartctl_sata):
        """Verify 100 - value for attribute 177 (remaining -> used)."""
        monitor = SmartMonitor(device="/dev/sda")
        metrics = monitor._extract_sata_metrics(mock_smartctl_sata)
        # Attribute 177 value is 98 (remaining), so percentage_used = 100 - 98 = 2
        assert metrics["percentage_used"] == 2

    def test_extract_sata_metrics_tbw(self, mock_smartctl_sata):
        """Verify TBW from attribute 241 (Total_LBAs_Written * sector size)."""
        monitor = SmartMonitor(device="/dev/sda")
        metrics = monitor._extract_sata_metrics(mock_smartctl_sata)
        # 87654321 LBAs * 512 bytes per sector
        expected = 87654321 * 512
        assert metrics["total_bytes_written"] == expected


# =========================================================================
# get_metrics / check_health
# =========================================================================

class TestGetMetrics:

    @patch.object(SmartMonitor, "get_raw_data")
    def test_get_metrics_returns_smart_metrics(
        self, mock_get_raw, mock_smartctl_nvme
    ):
        """Verify get_metrics returns a SmartMetrics instance with expected fields."""
        mock_get_raw.return_value = mock_smartctl_nvme

        monitor = SmartMonitor(device="/dev/nvme0n1")
        metrics = monitor.get_metrics()

        assert isinstance(metrics, SmartMetrics)
        assert metrics.device == "/dev/nvme0n1"
        assert metrics.device_type == "nvme"
        assert metrics.model == "Samsung 980 PRO 1TB"
        assert metrics.serial == "S6B1NJ0TB12345"
        assert metrics.temperature_c == 38
        assert metrics.percentage_used == 3
        assert metrics.healthy is True

    @patch.object(SmartMonitor, "get_raw_data")
    def test_check_health_backward_compat(
        self, mock_get_raw, mock_smartctl_nvme
    ):
        """Verify check_health returns SmartMetrics (not bool) for backward compat."""
        mock_get_raw.return_value = mock_smartctl_nvme

        monitor = SmartMonitor(device="/dev/nvme0n1")
        result = monitor.check_health()

        assert isinstance(result, SmartMetrics)
        assert result.healthy is True


# =========================================================================
# Alert evaluation
# =========================================================================

class TestAlerts:

    def _make_metrics(self, **overrides):
        """Helper to create a SmartMetrics with sensible defaults."""
        defaults = {
            "device": "/dev/nvme0n1",
            "device_type": "nvme",
            "model": "Test Drive",
            "serial": "TEST123",
            "temperature_c": 35,
            "percentage_used": 5,
            "power_on_hours": 1000,
            "total_bytes_written": 1_000_000_000,
            "total_bytes_read": 2_000_000_000,
            "media_errors": 0,
            "reallocated_sectors": None,
            "healthy": True,
        }
        defaults.update(overrides)
        return SmartMetrics(**defaults)

    def test_alert_temperature_warning(self):
        """Verify temp > 70C triggers WARNING (using default thresholds)."""
        monitor = SmartMonitor(
            device="/dev/nvme0n1",
            thresholds=AlertThresholds(temp_warn_c=70, temp_crit_c=80),
        )
        metrics = self._make_metrics(temperature_c=75)
        alerts = monitor._evaluate_alerts(metrics)

        temp_alerts = [a for a in alerts if a.metric_name == "temperature_c"]
        assert len(temp_alerts) == 1
        assert temp_alerts[0].level == AlertLevel.WARNING

    def test_alert_temperature_critical(self):
        """Verify temp > 80C triggers CRITICAL."""
        monitor = SmartMonitor(
            device="/dev/nvme0n1",
            thresholds=AlertThresholds(temp_warn_c=70, temp_crit_c=80),
        )
        metrics = self._make_metrics(temperature_c=85)
        alerts = monitor._evaluate_alerts(metrics)

        temp_alerts = [a for a in alerts if a.metric_name == "temperature_c"]
        assert len(temp_alerts) == 1
        assert temp_alerts[0].level == AlertLevel.CRITICAL

    def test_alert_wear_warning(self):
        """Verify percentage_used >= 80 triggers WARNING."""
        monitor = SmartMonitor(
            device="/dev/nvme0n1",
            thresholds=AlertThresholds(wear_warn_pct=80, wear_crit_pct=95),
        )
        metrics = self._make_metrics(percentage_used=85)
        alerts = monitor._evaluate_alerts(metrics)

        wear_alerts = [a for a in alerts if a.metric_name == "percentage_used"]
        assert len(wear_alerts) == 1
        assert wear_alerts[0].level == AlertLevel.WARNING

    def test_alert_wear_critical(self):
        """Verify percentage_used >= 95 triggers CRITICAL."""
        monitor = SmartMonitor(
            device="/dev/nvme0n1",
            thresholds=AlertThresholds(wear_warn_pct=80, wear_crit_pct=95),
        )
        metrics = self._make_metrics(percentage_used=97)
        alerts = monitor._evaluate_alerts(metrics)

        wear_alerts = [a for a in alerts if a.metric_name == "percentage_used"]
        assert len(wear_alerts) == 1
        assert wear_alerts[0].level == AlertLevel.CRITICAL

    def test_alert_media_errors(self):
        """Verify media_errors > 0 triggers WARNING."""
        monitor = SmartMonitor(
            device="/dev/nvme0n1",
            thresholds=AlertThresholds(media_errors_warn=0),
        )
        metrics = self._make_metrics(media_errors=3)
        alerts = monitor._evaluate_alerts(metrics)

        media_alerts = [a for a in alerts if a.metric_name == "media_errors"]
        assert len(media_alerts) == 1
        assert media_alerts[0].level == AlertLevel.WARNING

    def test_alert_callback_called(self):
        """Verify custom callbacks receive alerts when thresholds are exceeded."""
        received_alerts = []

        def capture_callback(alert: SmartAlert):
            received_alerts.append(alert)

        monitor = SmartMonitor(
            device="/dev/nvme0n1",
            thresholds=AlertThresholds(temp_warn_c=70, temp_crit_c=80),
            alert_callbacks=[capture_callback],
        )

        metrics = self._make_metrics(temperature_c=75)
        monitor._evaluate_alerts(metrics)

        # The custom callback should have received the alert
        assert len(received_alerts) >= 1
        assert received_alerts[0].metric_name == "temperature_c"


# =========================================================================
# get_status (JSON serialisation)
# =========================================================================

class TestGetStatus:

    @patch.object(SmartMonitor, "get_raw_data")
    def test_get_status_serializable(
        self, mock_get_raw, mock_smartctl_nvme
    ):
        """Verify get_status returns a JSON-serializable dict."""
        mock_get_raw.return_value = mock_smartctl_nvme

        monitor = SmartMonitor(device="/dev/nvme0n1")
        status = monitor.get_status()

        assert isinstance(status, dict)

        # Must be fully JSON-serializable (no datetime objects, Enums, etc.)
        serialized = json.dumps(status)
        assert isinstance(serialized, str)

        # Verify key fields are present
        assert "device" in status
        assert "device_type" in status
        assert "temperature_c" in status
        assert "percentage_used" in status
        assert "healthy" in status
        assert "model" in status
        assert "serial" in status
