"""
Tests for daemon/services/device_baseline.py

Covers baseline load/save (with mocked file I/O), check_devices with known
and unknown devices, add/remove/clear operations, and edge cases.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch, mock_open

import sys

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.device_baseline import DeviceBaseline


class TestBaselineInit(unittest.TestCase):
    """Tests for DeviceBaseline initialization."""

    def test_init_with_nonexistent_file(self):
        """Initializing with a nonexistent file starts empty."""
        baseline = DeviceBaseline(baseline_file="/nonexistent/path.json")
        self.assertEqual(baseline.get_baseline_count(), 0)

    def test_init_with_existing_file(self):
        """Initializing with an existing valid file loads devices."""
        data = {
            "AA:BB:CC:DD:EE:FF": {"ip": "192.168.1.10", "hostname": "laptop"},
            "11:22:33:44:55:66": {"ip": "192.168.1.20", "hostname": "phone"},
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(data, f)
            f.flush()
            temp_path = f.name

        try:
            baseline = DeviceBaseline(baseline_file=temp_path)
            self.assertEqual(baseline.get_baseline_count(), 2)
        finally:
            os.unlink(temp_path)

    def test_init_with_corrupt_file(self):
        """Initializing with a corrupt JSON file starts empty."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            f.write("not valid json{{{")
            f.flush()
            temp_path = f.name

        try:
            baseline = DeviceBaseline(baseline_file=temp_path)
            self.assertEqual(baseline.get_baseline_count(), 0)
        finally:
            os.unlink(temp_path)

    def test_init_with_non_dict_file(self):
        """Initializing with a JSON file containing a list starts empty."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(["not", "a", "dict"], f)
            f.flush()
            temp_path = f.name

        try:
            baseline = DeviceBaseline(baseline_file=temp_path)
            self.assertEqual(baseline.get_baseline_count(), 0)
        finally:
            os.unlink(temp_path)


class TestBaselineSave(unittest.TestCase):
    """Tests for baseline persistence."""

    def test_save_creates_file(self):
        """Adding a device should create the baseline file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "sub", "baseline.json")
            baseline = DeviceBaseline(baseline_file=path)
            baseline.add_to_baseline("AA:BB:CC:DD:EE:FF", {"ip": "192.168.1.1"})
            self.assertTrue(os.path.exists(path))

    def test_save_roundtrip(self):
        """Saved data should be loadable by a new instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "baseline.json")
            baseline1 = DeviceBaseline(baseline_file=path)
            baseline1.add_to_baseline("AA:BB:CC:DD:EE:FF", {"ip": "192.168.1.1"})
            baseline1.add_to_baseline("11:22:33:44:55:66", {"ip": "192.168.1.2"})

            # Create a new instance from the same file
            baseline2 = DeviceBaseline(baseline_file=path)
            self.assertEqual(baseline2.get_baseline_count(), 2)

    def test_save_after_remove(self):
        """After removing a device, re-loading should reflect the removal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "baseline.json")
            baseline1 = DeviceBaseline(baseline_file=path)
            baseline1.add_to_baseline("AA:BB:CC:DD:EE:FF", {"ip": "192.168.1.1"})
            baseline1.add_to_baseline("11:22:33:44:55:66", {"ip": "192.168.1.2"})
            baseline1.remove_from_baseline("AA:BB:CC:DD:EE:FF")

            baseline2 = DeviceBaseline(baseline_file=path)
            self.assertEqual(baseline2.get_baseline_count(), 1)
            self.assertNotIn("AA:BB:CC:DD:EE:FF", baseline2.get_baseline())


class TestCheckDevices(unittest.TestCase):
    """Tests for check_devices()."""

    def setUp(self):
        self.baseline = DeviceBaseline(baseline_file="/nonexistent/path.json")
        # Pre-populate baseline manually
        self.baseline._known_devices = {
            "AA:BB:CC:DD:EE:FF": {"ip": "192.168.1.10", "hostname": "laptop"},
            "11:22:33:44:55:66": {"ip": "192.168.1.20", "hostname": "phone"},
        }

    def test_all_known_devices(self):
        """All known devices should produce no alerts."""
        devices = [
            {"mac": "AA:BB:CC:DD:EE:FF", "ip": "192.168.1.10"},
            {"mac": "11:22:33:44:55:66", "ip": "192.168.1.20"},
        ]
        alerts = self.baseline.check_devices(devices)
        self.assertEqual(len(alerts), 0)

    def test_new_device_detected(self):
        """A new device should produce an alert."""
        devices = [
            {"mac": "AA:BB:CC:DD:EE:FF", "ip": "192.168.1.10"},
            {"mac": "FF:EE:DD:CC:BB:AA", "ip": "192.168.1.30"},
        ]
        alerts = self.baseline.check_devices(devices)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["type"], "new_device")
        self.assertEqual(alerts[0]["mac"], "FF:EE:DD:CC:BB:AA")
        self.assertEqual(alerts[0]["ip"], "192.168.1.30")

    def test_new_device_message_with_manufacturer(self):
        """Alert message includes manufacturer when provided."""
        devices = [
            {
                "mac": "FF:EE:DD:CC:BB:AA",
                "ip": "192.168.1.30",
                "manufacturer": "Apple Inc.",
            }
        ]
        alerts = self.baseline.check_devices(devices)
        self.assertEqual(len(alerts), 1)
        self.assertIn("Apple Inc.", alerts[0]["message"])

    def test_new_device_message_without_manufacturer(self):
        """Alert message shows MAC when no manufacturer provided."""
        devices = [
            {"mac": "FF:EE:DD:CC:BB:AA", "ip": "192.168.1.30"}
        ]
        alerts = self.baseline.check_devices(devices)
        self.assertEqual(len(alerts), 1)
        self.assertIn("FF:EE:DD:CC:BB:AA", alerts[0]["message"])

    def test_multiple_new_devices(self):
        """Multiple new devices produce multiple alerts."""
        devices = [
            {"mac": "FF:EE:DD:CC:BB:AA", "ip": "192.168.1.30"},
            {"mac": "CC:DD:EE:FF:00:11", "ip": "192.168.1.40"},
        ]
        alerts = self.baseline.check_devices(devices)
        self.assertEqual(len(alerts), 2)

    def test_empty_device_list(self):
        """Empty device list produces no alerts."""
        alerts = self.baseline.check_devices([])
        self.assertEqual(len(alerts), 0)

    def test_device_without_mac_skipped(self):
        """Devices without MAC are skipped."""
        devices = [
            {"ip": "192.168.1.30"},
            {"mac": "", "ip": "192.168.1.40"},
        ]
        alerts = self.baseline.check_devices(devices)
        self.assertEqual(len(alerts), 0)

    def test_mac_case_insensitive(self):
        """MAC comparison is case-insensitive."""
        devices = [
            {"mac": "aa:bb:cc:dd:ee:ff", "ip": "192.168.1.10"},
        ]
        alerts = self.baseline.check_devices(devices)
        self.assertEqual(len(alerts), 0)

    def test_does_not_auto_add_to_baseline(self):
        """check_devices does NOT automatically add new devices."""
        devices = [
            {"mac": "FF:EE:DD:CC:BB:AA", "ip": "192.168.1.30"},
        ]
        self.baseline.check_devices(devices)
        self.assertEqual(self.baseline.get_baseline_count(), 2)

    def test_alert_contains_all_fields(self):
        """Alert dict should contain all required fields."""
        devices = [
            {
                "mac": "FF:EE:DD:CC:BB:AA",
                "ip": "192.168.1.30",
                "hostname": "new-laptop",
                "manufacturer": "Dell Inc.",
                "first_seen": "2026-02-25T10:00:00Z",
            }
        ]
        alerts = self.baseline.check_devices(devices)
        alert = alerts[0]
        self.assertEqual(alert["type"], "new_device")
        self.assertEqual(alert["mac"], "FF:EE:DD:CC:BB:AA")
        self.assertEqual(alert["ip"], "192.168.1.30")
        self.assertEqual(alert["hostname"], "new-laptop")
        self.assertEqual(alert["manufacturer"], "Dell Inc.")
        self.assertEqual(alert["first_seen"], "2026-02-25T10:00:00Z")
        self.assertIn("message", alert)


class TestAddToBaseline(unittest.TestCase):
    """Tests for add_to_baseline()."""

    def test_add_device(self):
        """Adding a device increases the baseline count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "baseline.json")
            baseline = DeviceBaseline(baseline_file=path)
            baseline.add_to_baseline("AA:BB:CC:DD:EE:FF", {"ip": "192.168.1.1"})
            self.assertEqual(baseline.get_baseline_count(), 1)

    def test_add_device_normalises_mac(self):
        """MAC addresses are normalised to uppercase."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "baseline.json")
            baseline = DeviceBaseline(baseline_file=path)
            baseline.add_to_baseline("aa:bb:cc:dd:ee:ff", {"ip": "192.168.1.1"})
            devices = baseline.get_baseline()
            self.assertIn("AA:BB:CC:DD:EE:FF", devices)

    def test_add_device_stores_added_at(self):
        """Added device should have an 'added_at' timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "baseline.json")
            baseline = DeviceBaseline(baseline_file=path)
            baseline.add_to_baseline("AA:BB:CC:DD:EE:FF", {"ip": "192.168.1.1"})
            info = baseline.get_baseline()["AA:BB:CC:DD:EE:FF"]
            self.assertIn("added_at", info)

    def test_add_device_preserves_info(self):
        """Device info passed is stored alongside added_at."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "baseline.json")
            baseline = DeviceBaseline(baseline_file=path)
            baseline.add_to_baseline(
                "AA:BB:CC:DD:EE:FF",
                {"ip": "192.168.1.1", "hostname": "laptop", "manufacturer": "Dell"},
            )
            info = baseline.get_baseline()["AA:BB:CC:DD:EE:FF"]
            self.assertEqual(info["ip"], "192.168.1.1")
            self.assertEqual(info["hostname"], "laptop")
            self.assertEqual(info["manufacturer"], "Dell")

    def test_add_duplicate_overwrites(self):
        """Adding a device with same MAC overwrites the existing entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "baseline.json")
            baseline = DeviceBaseline(baseline_file=path)
            baseline.add_to_baseline("AA:BB:CC:DD:EE:FF", {"ip": "192.168.1.1"})
            baseline.add_to_baseline("AA:BB:CC:DD:EE:FF", {"ip": "192.168.1.99"})
            self.assertEqual(baseline.get_baseline_count(), 1)
            self.assertEqual(
                baseline.get_baseline()["AA:BB:CC:DD:EE:FF"]["ip"], "192.168.1.99"
            )


class TestRemoveFromBaseline(unittest.TestCase):
    """Tests for remove_from_baseline()."""

    def test_remove_existing_device(self):
        """Removing an existing device returns True and decreases count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "baseline.json")
            baseline = DeviceBaseline(baseline_file=path)
            baseline.add_to_baseline("AA:BB:CC:DD:EE:FF", {"ip": "192.168.1.1"})
            result = baseline.remove_from_baseline("AA:BB:CC:DD:EE:FF")
            self.assertTrue(result)
            self.assertEqual(baseline.get_baseline_count(), 0)

    def test_remove_nonexistent_device(self):
        """Removing a nonexistent device returns False."""
        baseline = DeviceBaseline(baseline_file="/nonexistent/path.json")
        result = baseline.remove_from_baseline("AA:BB:CC:DD:EE:FF")
        self.assertFalse(result)

    def test_remove_case_insensitive(self):
        """Removal should be case-insensitive for MAC."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "baseline.json")
            baseline = DeviceBaseline(baseline_file=path)
            baseline.add_to_baseline("AA:BB:CC:DD:EE:FF", {"ip": "192.168.1.1"})
            result = baseline.remove_from_baseline("aa:bb:cc:dd:ee:ff")
            self.assertTrue(result)
            self.assertEqual(baseline.get_baseline_count(), 0)


class TestClearBaseline(unittest.TestCase):
    """Tests for clear_baseline()."""

    def test_clear_empties_baseline(self):
        """Clearing should remove all devices."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "baseline.json")
            baseline = DeviceBaseline(baseline_file=path)
            baseline.add_to_baseline("AA:BB:CC:DD:EE:FF", {"ip": "192.168.1.1"})
            baseline.add_to_baseline("11:22:33:44:55:66", {"ip": "192.168.1.2"})
            baseline.clear_baseline()
            self.assertEqual(baseline.get_baseline_count(), 0)
            self.assertEqual(baseline.get_baseline(), {})

    def test_clear_persists(self):
        """After clearing, a new instance should also be empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "baseline.json")
            baseline1 = DeviceBaseline(baseline_file=path)
            baseline1.add_to_baseline("AA:BB:CC:DD:EE:FF", {"ip": "192.168.1.1"})
            baseline1.clear_baseline()

            baseline2 = DeviceBaseline(baseline_file=path)
            self.assertEqual(baseline2.get_baseline_count(), 0)


class TestGetBaseline(unittest.TestCase):
    """Tests for get_baseline() and get_baseline_count()."""

    def test_get_baseline_returns_copy(self):
        """get_baseline() should return a copy, not the internal dict."""
        baseline = DeviceBaseline(baseline_file="/nonexistent/path.json")
        baseline._known_devices = {"AA:BB:CC:DD:EE:FF": {"ip": "192.168.1.1"}}
        result = baseline.get_baseline()
        # Modify the returned dict
        result["NEW:MA:CA:DD:RE:SS"] = {}
        # Internal state should be unchanged
        self.assertEqual(baseline.get_baseline_count(), 1)

    def test_get_baseline_count_empty(self):
        """Count for empty baseline is 0."""
        baseline = DeviceBaseline(baseline_file="/nonexistent/path.json")
        self.assertEqual(baseline.get_baseline_count(), 0)

    def test_get_baseline_count_with_devices(self):
        """Count reflects number of devices."""
        baseline = DeviceBaseline(baseline_file="/nonexistent/path.json")
        baseline._known_devices = {
            "AA:BB:CC:DD:EE:FF": {},
            "11:22:33:44:55:66": {},
            "00:11:22:33:44:55": {},
        }
        self.assertEqual(baseline.get_baseline_count(), 3)


if __name__ == "__main__":
    unittest.main()
