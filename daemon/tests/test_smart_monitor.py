"""
Tests for daemon/smart/monitor.py — SmartMonitor.

Covers device type detection, NVMe and SATA metric extraction,
temperature / wear / media-error alerting, alert callbacks,
backward-compatible check_health, JSON-serializable status output,
NVMe fallback parsing for firmware variants, self-test diagnostics,
and nvme-cli as primary NVMe tool.
"""

import json
import subprocess
from unittest.mock import patch, MagicMock


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
    def test_get_metrics_returns_smart_metrics(self, mock_get_raw, mock_smartctl_nvme):
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
    def test_check_health_backward_compat(self, mock_get_raw, mock_smartctl_nvme):
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
    def test_get_status_serializable(self, mock_get_raw, mock_smartctl_nvme):
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


# =========================================================================
# NVMe fallback parsing (firmware variants)
# =========================================================================


class TestNvmeFallbackParsing:
    def test_nvme_temperature_fallback_to_top_level(self):
        """When nvme health log has no temperature, fall back to temperature.current."""
        monitor = SmartMonitor()
        data = {
            "device": {"type": "nvme"},
            "temperature": {"current": 42},
            "nvme_smart_health_information_log": {
                "percentage_used": 5,
                "power_on_hours": 100,
                "data_units_written": 1000,
                "data_units_read": 2000,
                "media_errors": 0,
                "critical_warning": 0,
                # No "temperature" key here
            },
        }
        metrics = monitor._extract_nvme_metrics(data)
        assert metrics["temperature_c"] == 42

    def test_nvme_temperature_fallback_to_sensors(self):
        """Samsung firmware: fall back to temperature_sensors[0]."""
        monitor = SmartMonitor()
        data = {
            "device": {"type": "nvme"},
            "temperature": {},  # No "current" key
            "nvme_smart_health_information_log": {
                "percentage_used": 5,
                "power_on_hours": 100,
                "data_units_written": 1000,
                "data_units_read": 2000,
                "media_errors": 0,
                "critical_warning": 0,
                "temperature_sensors": [45, 50],
                # No "temperature" key here
            },
        }
        metrics = monitor._extract_nvme_metrics(data)
        assert metrics["temperature_c"] == 45

    def test_nvme_temperature_sensors_zero_skipped(self):
        """temperature_sensors[0] = 0 should not be used as temperature."""
        monitor = SmartMonitor()
        data = {
            "device": {"type": "nvme"},
            "temperature": {},
            "nvme_smart_health_information_log": {
                "percentage_used": 5,
                "power_on_hours": 100,
                "data_units_written": 1000,
                "data_units_read": 2000,
                "media_errors": 0,
                "critical_warning": 0,
                "temperature_sensors": [0, 50],
            },
        }
        metrics = monitor._extract_nvme_metrics(data)
        assert metrics["temperature_c"] is None

    def test_percentage_used_zero_is_valid(self):
        """percentage_used=0 is valid for new drives, must not be treated as missing."""
        monitor = SmartMonitor()
        data = {
            "device": {"type": "nvme"},
            "temperature": {"current": 35},
            "nvme_smart_health_information_log": {
                "temperature": 35,
                "percentage_used": 0,
                "power_on_hours": 10,
                "data_units_written": 100,
                "data_units_read": 200,
                "media_errors": 0,
                "critical_warning": 0,
            },
        }
        metrics = monitor._extract_nvme_metrics(data)
        assert metrics["percentage_used"] == 0
        assert metrics["percentage_used"] is not None

    def test_percentage_used_null_means_failure(self):
        """percentage_used=None when field is missing from nvme health log."""
        monitor = SmartMonitor()
        data = {
            "device": {"type": "nvme"},
            "temperature": {"current": 35},
            "nvme_smart_health_information_log": {
                "temperature": 35,
                "power_on_hours": 10,
                # No percentage_used
            },
        }
        metrics = monitor._extract_nvme_metrics(data)
        assert metrics["percentage_used"] is None

    def test_power_on_hours_fallback_to_top_level(self):
        """power_on_hours falls back to power_on_time.hours at top level."""
        monitor = SmartMonitor()
        data = {
            "device": {"type": "nvme"},
            "temperature": {"current": 35},
            "power_on_time": {"hours": 5000},
            "nvme_smart_health_information_log": {
                "temperature": 35,
                "percentage_used": 5,
                # No power_on_hours
            },
        }
        metrics = monitor._extract_nvme_metrics(data)
        assert metrics["power_on_hours"] == 5000


# =========================================================================
# Self-test diagnostics
# =========================================================================


class TestSelfTest:
    @patch.object(SmartMonitor, "get_raw_data")
    def test_self_test_reports_missing_fields(self, mock_get_raw):
        """Self-test correctly identifies missing fields."""
        mock_get_raw.return_value = {
            "device": {"type": "nvme"},
            "model_name": "Test NVMe",
            "serial_number": "SN123",
            "nvme_smart_health_information_log": {
                # All key fields missing
            },
        }
        monitor = SmartMonitor(device="/dev/nvme0n1")
        diag = monitor.run_self_test()

        assert "temperature_c" in diag["missing_fields"]
        assert "percentage_used" in diag["missing_fields"]
        assert "power_on_hours" in diag["missing_fields"]

    @patch.object(SmartMonitor, "get_raw_data")
    def test_self_test_reports_guidance(self, mock_get_raw):
        """Self-test provides guidance messages for missing fields."""
        mock_get_raw.return_value = {
            "device": {"type": "nvme"},
            "model_name": "Test NVMe",
            "serial_number": "SN123",
            # Empty nvme health log triggers NVMe-specific guidance
            "nvme_smart_health_information_log": {},
        }
        monitor = SmartMonitor(device="/dev/nvme0n1")
        diag = monitor.run_self_test()

        assert len(diag["guidance"]) > 0
        # Should mention /dev mount and SYS_ADMIN capability
        guidance_text = " ".join(diag["guidance"])
        assert "SYS_ADMIN" in guidance_text

    @patch.object(SmartMonitor, "get_raw_data")
    def test_self_test_no_missing_fields_when_all_present(self, mock_get_raw, mock_smartctl_nvme):
        """Self-test reports no missing fields when all data is present."""
        mock_get_raw.return_value = mock_smartctl_nvme
        monitor = SmartMonitor(device="/dev/nvme0n1")
        diag = monitor.run_self_test()

        assert diag["missing_fields"] == []
        assert diag["guidance"] == []

    @patch.object(SmartMonitor, "get_raw_data")
    def test_diagnostics_dict_format(self, mock_get_raw, mock_smartctl_nvme):
        """Diagnostics dict has expected keys and is JSON-serializable."""
        mock_get_raw.return_value = mock_smartctl_nvme
        monitor = SmartMonitor(device="/dev/nvme0n1")
        diag = monitor.run_self_test()

        # Required keys
        assert "device" in diag
        assert "device_type" in diag
        assert "model" in diag
        assert "serial" in diag
        assert "raw_output_available" in diag
        assert "missing_fields" in diag
        assert "guidance" in diag
        assert "timestamp" in diag

        # Must be JSON-serializable
        serialized = json.dumps(diag)
        assert isinstance(serialized, str)

        # Values make sense
        assert diag["device"] == "/dev/nvme0n1"
        assert diag["device_type"] == "nvme"
        assert diag["raw_output_available"] is True

    @patch.object(SmartMonitor, "get_raw_data")
    def test_self_test_no_raw_data(self, mock_get_raw):
        """Self-test handles smartctl returning no data gracefully."""
        mock_get_raw.return_value = {}
        monitor = SmartMonitor(device="/dev/nvme0n1")
        diag = monitor.run_self_test()

        assert diag["raw_output_available"] is False
        assert len(diag["missing_fields"]) == 3
        assert "smartctl returned no data" in diag["guidance"][0]

    @patch.object(SmartMonitor, "get_raw_data")
    def test_get_diagnostics_caches_result(self, mock_get_raw, mock_smartctl_nvme):
        """get_diagnostics returns cached result after first run_self_test."""
        mock_get_raw.return_value = mock_smartctl_nvme
        monitor = SmartMonitor(device="/dev/nvme0n1")

        diag1 = monitor.run_self_test()
        diag2 = monitor.get_diagnostics()
        assert diag1 is diag2


# =========================================================================
# OpenSearch indexing
# =========================================================================


class TestOpenSearchIndexing:
    def test_index_to_opensearch_success(self):
        """index_to_opensearch indexes a document and returns True."""
        monitor = SmartMonitor(device="/dev/nvme0n1")
        metrics = SmartMetrics(
            device="/dev/nvme0n1",
            device_type="nvme",
            model="Test",
            serial="SN",
            temperature_c=35,
            percentage_used=5,
            power_on_hours=1000,
            total_bytes_written=1_000_000,
            total_bytes_read=2_000_000,
            media_errors=0,
            reallocated_sectors=None,
            healthy=True,
        )

        mock_client = MagicMock()
        mock_client.index.return_value = {"result": "created"}

        result = monitor.index_to_opensearch(metrics, mock_client)
        assert result is True
        mock_client.index.assert_called_once()

        # Verify the index name pattern
        call_kwargs = mock_client.index.call_args
        assert call_kwargs[1]["index"].startswith("nettap-smart-")
        doc = call_kwargs[1]["body"]
        assert doc["device"] == "/dev/nvme0n1"
        assert doc["temperature_c"] == 35
        assert "@timestamp" in doc

    def test_index_to_opensearch_failure(self):
        """index_to_opensearch returns False on error."""
        monitor = SmartMonitor(device="/dev/nvme0n1")
        metrics = SmartMetrics(
            device="/dev/nvme0n1",
            device_type="nvme",
            model="Test",
            serial="SN",
            temperature_c=35,
            percentage_used=5,
            power_on_hours=1000,
            total_bytes_written=1_000_000,
            total_bytes_read=2_000_000,
            media_errors=0,
            reallocated_sectors=None,
            healthy=True,
        )

        mock_client = MagicMock()
        mock_client.index.side_effect = Exception("Connection refused")

        result = monitor.index_to_opensearch(metrics, mock_client)
        assert result is False


# =========================================================================
# nvme-cli controller path extraction
# =========================================================================


class TestNvmeControllerPath:
    def test_controller_from_namespace(self):
        """Derive /dev/nvme0 from /dev/nvme0n1."""
        monitor = SmartMonitor(device="/dev/nvme0n1")
        assert monitor._get_nvme_controller() == "/dev/nvme0"

    def test_controller_from_multi_digit(self):
        """Derive /dev/nvme1 from /dev/nvme1n1."""
        monitor = SmartMonitor(device="/dev/nvme1n1")
        assert monitor._get_nvme_controller() == "/dev/nvme1"

    def test_controller_from_non_nvme(self):
        """Non-NVMe paths return the device as-is."""
        monitor = SmartMonitor(device="/dev/sda")
        assert monitor._get_nvme_controller() == "/dev/sda"


# =========================================================================
# nvme-cli raw data retrieval
# =========================================================================


class TestNvmeCliRawData:
    @patch("smart.monitor.subprocess.run")
    def test_get_nvme_raw_data_success(self, mock_run, mock_nvme_cli_smart_log):
        """nvme smart-log returns valid JSON."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(mock_nvme_cli_smart_log),
            stderr="",
        )
        monitor = SmartMonitor(device="/dev/nvme0n1")
        data = monitor._get_nvme_raw_data()

        assert data == mock_nvme_cli_smart_log
        mock_run.assert_called_once_with(
            ["nvme", "smart-log", "/dev/nvme0", "-o", "json"],
            capture_output=True,
            text=True,
            timeout=15,
        )

    @patch("smart.monitor.subprocess.run")
    def test_get_nvme_raw_data_not_installed(self, mock_run):
        """nvme-cli not installed returns empty dict."""
        mock_run.side_effect = FileNotFoundError("nvme not found")
        monitor = SmartMonitor(device="/dev/nvme0n1")
        data = monitor._get_nvme_raw_data()
        assert data == {}

    @patch("smart.monitor.subprocess.run")
    def test_get_nvme_raw_data_nonzero_exit(self, mock_run):
        """nvme smart-log non-zero exit returns empty dict."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="NVMe Status: Permission denied",
        )
        monitor = SmartMonitor(device="/dev/nvme0n1")
        data = monitor._get_nvme_raw_data()
        assert data == {}

    @patch("smart.monitor.subprocess.run")
    def test_get_nvme_raw_data_bad_json(self, mock_run):
        """nvme smart-log returns invalid JSON."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="not json at all",
            stderr="",
        )
        monitor = SmartMonitor(device="/dev/nvme0n1")
        data = monitor._get_nvme_raw_data()
        assert data == {}


# =========================================================================
# nvme-cli identity retrieval
# =========================================================================


class TestNvmeCliIdentity:
    @patch("smart.monitor.subprocess.run")
    def test_get_nvme_identity_success(self, mock_run, mock_nvme_cli_id_ctrl):
        """nvme id-ctrl returns model and serial (trimmed)."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(mock_nvme_cli_id_ctrl),
            stderr="",
        )
        monitor = SmartMonitor(device="/dev/nvme0n1")
        model, serial = monitor._get_nvme_identity()

        assert model == "Samsung 980 PRO 1TB"
        assert serial == "S6B1NJ0TB12345"

    @patch("smart.monitor.subprocess.run")
    def test_get_nvme_identity_failure(self, mock_run):
        """nvme id-ctrl failure returns Unknown."""
        mock_run.side_effect = FileNotFoundError("nvme not found")
        monitor = SmartMonitor(device="/dev/nvme0n1")
        model, serial = monitor._get_nvme_identity()

        assert model == "Unknown"
        assert serial == "Unknown"


# =========================================================================
# nvme-cli metric extraction
# =========================================================================


class TestExtractNvmeCliMetrics:
    def test_temperature_kelvin_conversion(self, mock_nvme_cli_smart_log):
        """Temperature in Kelvin (311) converts to Celsius (38)."""
        monitor = SmartMonitor()
        metrics = monitor._extract_nvme_cli_metrics(mock_nvme_cli_smart_log)
        assert metrics["temperature_c"] == 38

    def test_temperature_already_celsius(self):
        """Temperature < 200 treated as already Celsius."""
        monitor = SmartMonitor()
        data = {"temperature": 42, "percent_used": 5, "power_on_hours": 100}
        metrics = monitor._extract_nvme_cli_metrics(data)
        assert metrics["temperature_c"] == 42

    def test_percent_used_field_name(self, mock_nvme_cli_smart_log):
        """nvme-cli uses 'percent_used' not 'percentage_used'."""
        monitor = SmartMonitor()
        metrics = monitor._extract_nvme_cli_metrics(mock_nvme_cli_smart_log)
        assert metrics["percentage_used"] == 3

    def test_tbw_calculation(self, mock_nvme_cli_smart_log):
        """data_units_written * 512 * 1000."""
        monitor = SmartMonitor()
        metrics = monitor._extract_nvme_cli_metrics(mock_nvme_cli_smart_log)
        expected_tbw = 43285012 * 512 * 1000
        assert metrics["total_bytes_written"] == expected_tbw

    def test_bytes_read_calculation(self, mock_nvme_cli_smart_log):
        """data_units_read * 512 * 1000."""
        monitor = SmartMonitor()
        metrics = monitor._extract_nvme_cli_metrics(mock_nvme_cli_smart_log)
        expected = 52459106 * 512 * 1000
        assert metrics["total_bytes_read"] == expected

    def test_media_errors(self, mock_nvme_cli_smart_log):
        """media_errors extracted correctly."""
        monitor = SmartMonitor()
        metrics = monitor._extract_nvme_cli_metrics(mock_nvme_cli_smart_log)
        assert metrics["media_errors"] == 0

    def test_critical_warning(self, mock_nvme_cli_smart_log):
        """critical_warning extracted correctly."""
        monitor = SmartMonitor()
        metrics = monitor._extract_nvme_cli_metrics(mock_nvme_cli_smart_log)
        assert metrics["critical_warning"] == 0

    def test_missing_temperature_returns_none(self):
        """Missing temperature field returns None."""
        monitor = SmartMonitor()
        data = {"percent_used": 5, "power_on_hours": 100}
        metrics = monitor._extract_nvme_cli_metrics(data)
        assert metrics["temperature_c"] is None

    def test_reallocated_sectors_always_none(self, mock_nvme_cli_smart_log):
        """NVMe has no reallocated sectors concept."""
        monitor = SmartMonitor()
        metrics = monitor._extract_nvme_cli_metrics(mock_nvme_cli_smart_log)
        assert metrics["reallocated_sectors"] is None


# =========================================================================
# nvme-cli device detection
# =========================================================================


class TestNvmeCliDeviceDetection:
    def test_nvme_cli_source_detected_as_nvme(self, mock_nvme_cli_wrapped):
        """Data with _source='nvme-cli' always detects as nvme."""
        monitor = SmartMonitor(device="/dev/sda")  # path doesn't matter
        result = monitor.detect_device_type(mock_nvme_cli_wrapped)
        assert result == "nvme"


# =========================================================================
# nvme-cli identity routing
# =========================================================================


class TestNvmeCliIdentityRouting:
    @patch.object(SmartMonitor, "_get_nvme_identity")
    def test_extract_identity_uses_id_ctrl_for_nvme_cli(self, mock_id):
        """_extract_identity routes to nvme id-ctrl for nvme-cli source."""
        mock_id.return_value = ("NVMe Model", "NVMe Serial")
        monitor = SmartMonitor(device="/dev/nvme0n1")
        data = {"_source": "nvme-cli", "_nvme_smart_log": {}}
        model, serial = monitor._extract_identity(data)
        assert model == "NVMe Model"
        assert serial == "NVMe Serial"
        mock_id.assert_called_once()


# =========================================================================
# nvme-cli end-to-end: get_raw_data wrapping
# =========================================================================


class TestNvmeCliGetRawData:
    @patch.object(SmartMonitor, "_get_nvme_raw_data")
    def test_get_raw_data_wraps_nvme_cli(self, mock_nvme_raw, mock_nvme_cli_smart_log):
        """get_raw_data wraps nvme-cli output with _source marker."""
        mock_nvme_raw.return_value = mock_nvme_cli_smart_log
        monitor = SmartMonitor(device="/dev/nvme0n1")
        data = monitor.get_raw_data()

        assert data["_source"] == "nvme-cli"
        assert data["_nvme_smart_log"] == mock_nvme_cli_smart_log

    @patch("smart.monitor.subprocess.run")
    @patch.object(SmartMonitor, "_get_nvme_raw_data")
    def test_get_raw_data_falls_back_to_smartctl(self, mock_nvme_raw, mock_run, mock_smartctl_nvme):
        """When nvme-cli returns nothing, falls back to smartctl."""
        mock_nvme_raw.return_value = {}
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(mock_smartctl_nvme),
            stderr="",
        )
        monitor = SmartMonitor(device="/dev/nvme0n1")
        data = monitor.get_raw_data()

        # Should be smartctl data, not wrapped
        assert "_source" not in data
        assert "nvme_smart_health_information_log" in data


# =========================================================================
# nvme-cli health assessment
# =========================================================================


class TestNvmeCliHealthAssessment:
    @patch.object(SmartMonitor, "get_raw_data")
    @patch.object(SmartMonitor, "_get_nvme_identity")
    def test_healthy_when_critical_warning_zero(self, mock_id, mock_get_raw, mock_nvme_cli_wrapped):
        """critical_warning=0 means healthy."""
        mock_get_raw.return_value = mock_nvme_cli_wrapped
        mock_id.return_value = ("Test NVMe", "SN123")

        monitor = SmartMonitor(device="/dev/nvme0n1")
        metrics = monitor.get_metrics()

        assert metrics.healthy is True
        assert metrics.device_type == "nvme"

    @patch.object(SmartMonitor, "get_raw_data")
    @patch.object(SmartMonitor, "_get_nvme_identity")
    def test_unhealthy_when_critical_warning_nonzero(self, mock_id, mock_get_raw):
        """critical_warning != 0 means unhealthy."""
        mock_get_raw.return_value = {
            "_source": "nvme-cli",
            "_nvme_smart_log": {
                "critical_warning": 4,
                "temperature": 311,
                "percent_used": 3,
                "power_on_hours": 8760,
                "data_units_written": 43285012,
                "data_units_read": 52459106,
                "media_errors": 0,
            },
        }
        mock_id.return_value = ("Test NVMe", "SN123")

        monitor = SmartMonitor(device="/dev/nvme0n1")
        metrics = monitor.get_metrics()

        assert metrics.healthy is False
        assert any("critical warning" in w for w in metrics.warnings)

    @patch.object(SmartMonitor, "get_raw_data")
    @patch.object(SmartMonitor, "_get_nvme_identity")
    def test_get_status_with_nvme_cli(self, mock_id, mock_get_raw, mock_nvme_cli_wrapped):
        """get_status returns JSON-serializable dict from nvme-cli data."""
        mock_get_raw.return_value = mock_nvme_cli_wrapped
        mock_id.return_value = ("Test NVMe", "SN123")

        monitor = SmartMonitor(device="/dev/nvme0n1")
        status = monitor.get_status()

        assert isinstance(status, dict)
        serialized = json.dumps(status)
        assert isinstance(serialized, str)
        assert status["device_type"] == "nvme"
        assert status["temperature_c"] == 38
