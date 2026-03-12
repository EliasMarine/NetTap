"""
Tests for daemon/services/mac_lookup_service.py

Tests MAC normalization, OUI lookup, and error cases.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.mac_lookup_service import MacLookupService, MacLookupValidationError


class TestNormalizeMac(unittest.TestCase):
    """Tests for MacLookupService.normalize_mac."""

    def setUp(self):
        self.svc = MacLookupService()

    def test_colon_format(self):
        result = self.svc.normalize_mac("aa:bb:cc:dd:ee:ff")
        self.assertEqual(result, "AA:BB:CC:DD:EE:FF")

    def test_dash_format(self):
        result = self.svc.normalize_mac("AA-BB-CC-DD-EE-FF")
        self.assertEqual(result, "AA:BB:CC:DD:EE:FF")

    def test_raw_hex_format(self):
        result = self.svc.normalize_mac("aabbccddeeff")
        self.assertEqual(result, "AA:BB:CC:DD:EE:FF")

    def test_mixed_case(self):
        result = self.svc.normalize_mac("Aa:Bb:Cc:Dd:Ee:Ff")
        self.assertEqual(result, "AA:BB:CC:DD:EE:FF")

    def test_strips_whitespace(self):
        result = self.svc.normalize_mac("  aa:bb:cc:dd:ee:ff  ")
        self.assertEqual(result, "AA:BB:CC:DD:EE:FF")

    def test_empty_string(self):
        with self.assertRaises(MacLookupValidationError):
            self.svc.normalize_mac("")

    def test_too_short(self):
        with self.assertRaises(MacLookupValidationError):
            self.svc.normalize_mac("aa:bb:cc")

    def test_too_long(self):
        with self.assertRaises(MacLookupValidationError):
            self.svc.normalize_mac("aa:bb:cc:dd:ee:ff:11")

    def test_invalid_chars(self):
        with self.assertRaises(MacLookupValidationError):
            self.svc.normalize_mac("gg:hh:ii:jj:kk:ll")

    def test_mixed_separators(self):
        with self.assertRaises(MacLookupValidationError):
            self.svc.normalize_mac("aa:bb-cc:dd-ee:ff")


class TestLookup(unittest.TestCase):
    """Tests for MacLookupService.lookup."""

    def setUp(self):
        # Create a temporary OUI database for testing
        self.oui_data = {
            "AA:BB:CC": "Test Vendor",
            "00:50:56": "VMware",
            "B8:27:EB": "Raspberry Pi Foundation",
        }
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        json.dump(self.oui_data, self.tmp)
        self.tmp.close()
        self.svc = MacLookupService(oui_db_path=self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_found_vendor(self):
        result = self.svc.lookup("aa:bb:cc:11:22:33")
        self.assertTrue(result["found"])
        self.assertEqual(result["vendor"], "Test Vendor")
        self.assertEqual(result["mac"], "AA:BB:CC:11:22:33")
        self.assertEqual(result["oui_prefix"], "AA:BB:CC")

    def test_vmware_lookup(self):
        result = self.svc.lookup("00:50:56:ab:cd:ef")
        self.assertTrue(result["found"])
        self.assertEqual(result["vendor"], "VMware")

    def test_not_found(self):
        result = self.svc.lookup("ff:ff:ff:00:00:00")
        self.assertFalse(result["found"])
        self.assertIsNone(result["vendor"])
        self.assertEqual(result["oui_prefix"], "FF:FF:FF")

    def test_validation_error_propagates(self):
        with self.assertRaises(MacLookupValidationError):
            self.svc.lookup("not-a-mac")


class TestLookupMissingDb(unittest.TestCase):
    """Tests for MacLookupService when OUI database is missing."""

    def test_missing_db_returns_not_found(self):
        svc = MacLookupService(oui_db_path="/nonexistent/oui.json")
        result = svc.lookup("aa:bb:cc:dd:ee:ff")
        self.assertFalse(result["found"])
        self.assertIsNone(result["vendor"])


class TestLookupCorruptDb(unittest.TestCase):
    """Tests for MacLookupService when OUI database is corrupt."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        self.tmp.write("not valid json {{{")
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_corrupt_db_returns_not_found(self):
        svc = MacLookupService(oui_db_path=self.tmp.name)
        result = svc.lookup("aa:bb:cc:dd:ee:ff")
        self.assertFalse(result["found"])
        self.assertIsNone(result["vendor"])


class TestBundledOuiDb(unittest.TestCase):
    """Test that the bundled OUI database loads and contains expected entries."""

    def test_bundled_db_loads(self):
        svc = MacLookupService()
        result = svc.lookup("B8:27:EB:12:34:56")
        self.assertTrue(result["found"])
        self.assertEqual(result["vendor"], "Raspberry Pi Foundation")

    def test_bundled_db_apple(self):
        svc = MacLookupService()
        result = svc.lookup("00:03:93:00:00:00")
        self.assertTrue(result["found"])
        self.assertEqual(result["vendor"], "Apple")


if __name__ == "__main__":
    unittest.main()
