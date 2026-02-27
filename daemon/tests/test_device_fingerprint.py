"""
Tests for daemon/services/device_fingerprint.py

All tests use mocks -- no OpenSearch connection required.
Tests cover OUI loading, MAC lookup, hostname resolution, MAC-from-IP
resolution, and OS hint extraction.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.device_fingerprint import DeviceFingerprint


class TestOUILoading(unittest.TestCase):
    """Tests for OUI database loading."""

    def test_load_oui_from_file(self):
        """Valid OUI file is loaded and entries are accessible."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("# comment line\n")
            f.write("AA:BB:CC\tTest Manufacturer\n")
            f.write("11:22:33\tAnother Corp\n")
            f.write("\n")  # blank line
            f.write("DD:EE:FF\tThird Vendor\n")
            f.name
            tmp_path = f.name

        try:
            fp = DeviceFingerprint(oui_path=tmp_path)
            self.assertEqual(len(fp._oui_db), 3)
            self.assertEqual(fp._oui_db["AA:BB:CC"], "Test Manufacturer")
            self.assertEqual(fp._oui_db["11:22:33"], "Another Corp")
            self.assertEqual(fp._oui_db["DD:EE:FF"], "Third Vendor")
        finally:
            os.unlink(tmp_path)

    def test_empty_oui_file(self):
        """Empty OUI file loads without error, yields empty database."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("")
            tmp_path = f.name

        try:
            fp = DeviceFingerprint(oui_path=tmp_path)
            self.assertEqual(len(fp._oui_db), 0)
        finally:
            os.unlink(tmp_path)

    def test_missing_oui_file(self):
        """Missing OUI file logs a warning but does not raise."""
        fp = DeviceFingerprint(oui_path="/nonexistent/path/oui.txt")
        self.assertEqual(len(fp._oui_db), 0)

    def test_comments_and_blanks_ignored(self):
        """Comment lines and blank lines are skipped during OUI loading."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("# This is a comment\n")
            f.write("#Another comment\n")
            f.write("\n")
            f.write("   \n")
            f.write("AA:BB:CC\tReal Entry\n")
            tmp_path = f.name

        try:
            fp = DeviceFingerprint(oui_path=tmp_path)
            self.assertEqual(len(fp._oui_db), 1)
            self.assertEqual(fp._oui_db["AA:BB:CC"], "Real Entry")
        finally:
            os.unlink(tmp_path)


class TestGetManufacturer(unittest.TestCase):
    """Tests for get_manufacturer() MAC prefix lookup."""

    def setUp(self):
        """Create a fingerprint instance with known OUI entries."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("00:03:93\tApple\n")
            f.write("3C:5A:B4\tGoogle\n")
            f.write("00:50:56\tVMware\n")
            f.write("B8:27:EB\tRaspberry Pi Foundation\n")
            f.write("00:E0:4C\tRealtek\n")
            self._tmp_path = f.name

        self.fp = DeviceFingerprint(oui_path=self._tmp_path)

    def tearDown(self):
        os.unlink(self._tmp_path)

    def test_known_prefix_returns_manufacturer(self):
        """Known MAC prefix returns the correct manufacturer."""
        result = self.fp.get_manufacturer("00:03:93:AA:BB:CC")
        self.assertEqual(result, "Apple")

    def test_unknown_prefix_returns_unknown(self):
        """Unknown MAC prefix returns 'Unknown'."""
        result = self.fp.get_manufacturer("FF:FF:FF:AA:BB:CC")
        self.assertEqual(result, "Unknown")

    def test_invalid_format_returns_unknown(self):
        """Invalid MAC format returns 'Unknown'."""
        result = self.fp.get_manufacturer("not-a-mac")
        self.assertEqual(result, "Unknown")

    def test_empty_string_returns_unknown(self):
        """Empty string returns 'Unknown'."""
        result = self.fp.get_manufacturer("")
        self.assertEqual(result, "Unknown")

    def test_none_returns_unknown(self):
        """None input returns 'Unknown'."""
        result = self.fp.get_manufacturer(None)
        self.assertEqual(result, "Unknown")

    def test_case_insensitive_lookup(self):
        """MAC lookup is case-insensitive."""
        result = self.fp.get_manufacturer("00:03:93:aa:bb:cc")
        self.assertEqual(result, "Apple")

        result2 = self.fp.get_manufacturer("3c:5a:b4:dd:ee:ff")
        self.assertEqual(result2, "Google")

    def test_dash_separated_mac(self):
        """Dash-separated MAC addresses are accepted."""
        result = self.fp.get_manufacturer("B8-27-EB-AA-BB-CC")
        self.assertEqual(result, "Raspberry Pi Foundation")

    def test_google_mac(self):
        """Google OUI prefix is found."""
        result = self.fp.get_manufacturer("3C:5A:B4:11:22:33")
        self.assertEqual(result, "Google")


class TestGetHostnameForIP(unittest.TestCase):
    """Tests for get_hostname_for_ip() DNS lookup."""

    def setUp(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("")
            self._tmp_path = f.name
        self.fp = DeviceFingerprint(oui_path=self._tmp_path)

    def tearDown(self):
        os.unlink(self._tmp_path)

    def test_hostname_found(self):
        """Returns the most common hostname when DNS data is available."""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "aggregations": {
                "top_hostname": {
                    "buckets": [
                        {"key": "mydevice.local", "doc_count": 15},
                        {"key": "mydevice.lan", "doc_count": 3},
                    ]
                }
            }
        }

        result = self.fp.get_hostname_for_ip(
            mock_client, "192.168.1.100", "2026-02-25T00:00:00Z", "2026-02-26T00:00:00Z"
        )
        self.assertEqual(result, "mydevice.local")
        mock_client.search.assert_called_once()

    def test_hostname_not_found(self):
        """Returns None when no DNS records match."""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "aggregations": {"top_hostname": {"buckets": []}}
        }

        result = self.fp.get_hostname_for_ip(
            mock_client, "10.0.0.1", "2026-02-25T00:00:00Z", "2026-02-26T00:00:00Z"
        )
        self.assertIsNone(result)

    def test_hostname_search_error(self):
        """Returns None when OpenSearch query fails."""
        mock_client = MagicMock()
        mock_client.search.side_effect = Exception("connection refused")

        result = self.fp.get_hostname_for_ip(
            mock_client, "192.168.1.1", "2026-02-25T00:00:00Z", "2026-02-26T00:00:00Z"
        )
        self.assertIsNone(result)


class TestGetMacForIP(unittest.TestCase):
    """Tests for get_mac_for_ip() DHCP/conn lookup."""

    def setUp(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("")
            self._tmp_path = f.name
        self.fp = DeviceFingerprint(oui_path=self._tmp_path)

    def tearDown(self):
        os.unlink(self._tmp_path)

    def test_mac_from_dhcp(self):
        """Returns MAC from DHCP logs when available."""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "hits": {"hits": [{"_source": {"mac": "AA:BB:CC:DD:EE:FF"}}]}
        }

        result = self.fp.get_mac_for_ip(
            mock_client, "192.168.1.50", "2026-02-25T00:00:00Z", "2026-02-26T00:00:00Z"
        )
        self.assertEqual(result, "AA:BB:CC:DD:EE:FF")

    def test_mac_from_conn_fallback(self):
        """Falls back to conn logs when DHCP has no results."""
        mock_client = MagicMock()
        # First call (DHCP) returns empty, second call (conn) returns MAC
        mock_client.search.side_effect = [
            {"hits": {"hits": []}},
            {"hits": {"hits": [{"_source": {"orig_l2_addr": "11:22:33:44:55:66"}}]}},
        ]

        result = self.fp.get_mac_for_ip(
            mock_client, "192.168.1.50", "2026-02-25T00:00:00Z", "2026-02-26T00:00:00Z"
        )
        self.assertEqual(result, "11:22:33:44:55:66")
        self.assertEqual(mock_client.search.call_count, 2)

    def test_mac_not_found(self):
        """Returns None when neither DHCP nor conn logs have a MAC."""
        mock_client = MagicMock()
        mock_client.search.side_effect = [
            {"hits": {"hits": []}},
            {"hits": {"hits": []}},
        ]

        result = self.fp.get_mac_for_ip(
            mock_client, "10.0.0.99", "2026-02-25T00:00:00Z", "2026-02-26T00:00:00Z"
        )
        self.assertIsNone(result)


class TestGetOSHint(unittest.TestCase):
    """Tests for get_os_hint() User-Agent and JA3 analysis."""

    def setUp(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("")
            self._tmp_path = f.name
        self.fp = DeviceFingerprint(oui_path=self._tmp_path)

    def tearDown(self):
        os.unlink(self._tmp_path)

    def test_os_hint_from_user_agent_windows(self):
        """Detects Windows from User-Agent string."""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "aggregations": {
                "top_ua": {
                    "buckets": [
                        {
                            "key": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                            "doc_count": 100,
                        }
                    ]
                }
            }
        }

        result = self.fp.get_os_hint(
            mock_client, "192.168.1.100", "2026-02-25T00:00:00Z", "2026-02-26T00:00:00Z"
        )
        self.assertEqual(result, "Windows 10/11")

    def test_os_hint_from_user_agent_macos(self):
        """Detects macOS from User-Agent string."""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "aggregations": {
                "top_ua": {
                    "buckets": [
                        {
                            "key": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                            "doc_count": 80,
                        }
                    ]
                }
            }
        }

        result = self.fp.get_os_hint(
            mock_client, "192.168.1.101", "2026-02-25T00:00:00Z", "2026-02-26T00:00:00Z"
        )
        self.assertEqual(result, "macOS")

    def test_os_hint_from_user_agent_android(self):
        """Detects Android from User-Agent string."""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "aggregations": {
                "top_ua": {
                    "buckets": [
                        {
                            "key": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36",
                            "doc_count": 50,
                        }
                    ]
                }
            }
        }

        result = self.fp.get_os_hint(
            mock_client, "192.168.1.102", "2026-02-25T00:00:00Z", "2026-02-26T00:00:00Z"
        )
        self.assertEqual(result, "Android")

    def test_os_hint_from_user_agent_ios(self):
        """Detects iOS from User-Agent string."""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "aggregations": {
                "top_ua": {
                    "buckets": [
                        {
                            "key": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
                            "doc_count": 40,
                        }
                    ]
                }
            }
        }

        result = self.fp.get_os_hint(
            mock_client, "192.168.1.103", "2026-02-25T00:00:00Z", "2026-02-26T00:00:00Z"
        )
        self.assertEqual(result, "iOS")

    def test_os_hint_no_results(self):
        """Returns None when no User-Agent or JA3 data is available."""
        mock_client = MagicMock()
        # HTTP query returns empty, JA3 query returns empty
        mock_client.search.side_effect = [
            {"aggregations": {"top_ua": {"buckets": []}}},
            {"aggregations": {"top_ja3": {"buckets": []}}},
        ]

        result = self.fp.get_os_hint(
            mock_client, "10.0.0.1", "2026-02-25T00:00:00Z", "2026-02-26T00:00:00Z"
        )
        self.assertIsNone(result)

    def test_os_hint_search_error(self):
        """Returns None when OpenSearch queries fail."""
        mock_client = MagicMock()
        mock_client.search.side_effect = Exception("timeout")

        result = self.fp.get_os_hint(
            mock_client, "192.168.1.1", "2026-02-25T00:00:00Z", "2026-02-26T00:00:00Z"
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
