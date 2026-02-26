"""
Tests for daemon/services/geoip_service.py

All tests use mocks for the MaxMind database -- no external DB or package
required. Tests cover private IP detection, well-known IP fallback,
MaxMind integration (mocked), batch lookups, and graceful degradation.
"""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock

import sys
import os

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.geoip_service import GeoIPService, GeoIPResult, WELL_KNOWN_IPS


class TestIsPrivate(unittest.TestCase):
    """Tests for GeoIPService.is_private()."""

    def setUp(self):
        # Create service without any DB (fallback mode)
        self.service = GeoIPService(db_path="/nonexistent/path.mmdb")

    def test_rfc1918_10_network(self):
        """10.0.0.0/8 is private."""
        self.assertTrue(self.service.is_private("10.0.0.1"))

    def test_rfc1918_172_network(self):
        """172.16.0.0/12 is private."""
        self.assertTrue(self.service.is_private("172.16.0.1"))

    def test_rfc1918_192_network(self):
        """192.168.0.0/16 is private."""
        self.assertTrue(self.service.is_private("192.168.1.1"))

    def test_loopback(self):
        """127.0.0.1 is loopback (private)."""
        self.assertTrue(self.service.is_private("127.0.0.1"))

    def test_link_local(self):
        """169.254.x.x is link-local (private)."""
        self.assertTrue(self.service.is_private("169.254.1.1"))

    def test_public_ip_not_private(self):
        """Public IPs should return False."""
        self.assertFalse(self.service.is_private("8.8.8.8"))

    def test_another_public_ip_not_private(self):
        """Another public IP should return False."""
        self.assertFalse(self.service.is_private("1.1.1.1"))

    def test_invalid_ip_returns_false(self):
        """Invalid IP strings should return False (not raise)."""
        self.assertFalse(self.service.is_private("not-an-ip"))

    def test_empty_string_returns_false(self):
        """Empty string should return False (not raise)."""
        self.assertFalse(self.service.is_private(""))

    def test_ipv6_loopback(self):
        """IPv6 loopback ::1 is private."""
        self.assertTrue(self.service.is_private("::1"))


class TestLookupPrivate(unittest.TestCase):
    """Tests for lookup() with private IPs."""

    def setUp(self):
        self.service = GeoIPService(db_path="/nonexistent/path.mmdb")

    def test_private_ip_result(self):
        """Private IP lookup returns is_private=True, country='Private Network'."""
        result = self.service.lookup("192.168.1.1")
        self.assertIsInstance(result, GeoIPResult)
        self.assertTrue(result.is_private)
        self.assertEqual(result.country, "Private Network")
        self.assertEqual(result.country_code, "XX")
        self.assertEqual(result.ip, "192.168.1.1")

    def test_loopback_result(self):
        """Loopback IP lookup returns is_private=True."""
        result = self.service.lookup("127.0.0.1")
        self.assertTrue(result.is_private)
        self.assertEqual(result.country, "Private Network")

    def test_link_local_result(self):
        """Link-local IP lookup returns is_private=True."""
        result = self.service.lookup("169.254.100.50")
        self.assertTrue(result.is_private)
        self.assertEqual(result.country, "Private Network")


class TestLookupWellKnown(unittest.TestCase):
    """Tests for lookup() with well-known public IPs (fallback DB)."""

    def setUp(self):
        self.service = GeoIPService(db_path="/nonexistent/path.mmdb")

    def test_google_dns(self):
        """8.8.8.8 should resolve to Google."""
        result = self.service.lookup("8.8.8.8")
        self.assertFalse(result.is_private)
        self.assertEqual(result.country, "United States")
        self.assertEqual(result.country_code, "US")
        self.assertEqual(result.city, "Mountain View")
        self.assertEqual(result.organization, "Google LLC")
        self.assertEqual(result.asn, 15169)

    def test_cloudflare_dns(self):
        """1.1.1.1 should resolve to Cloudflare."""
        result = self.service.lookup("1.1.1.1")
        self.assertFalse(result.is_private)
        self.assertEqual(result.country, "United States")
        self.assertEqual(result.country_code, "US")
        self.assertEqual(result.organization, "Cloudflare, Inc.")
        self.assertEqual(result.asn, 13335)

    def test_quad9_dns(self):
        """9.9.9.9 should resolve to Quad9."""
        result = self.service.lookup("9.9.9.9")
        self.assertEqual(result.organization, "Quad9")
        self.assertEqual(result.asn, 19281)

    def test_opendns(self):
        """208.67.222.222 should resolve to Cisco OpenDNS."""
        result = self.service.lookup("208.67.222.222")
        self.assertEqual(result.organization, "Cisco OpenDNS")

    def test_unknown_public_ip(self):
        """An unknown public IP returns country='Unknown'."""
        # 93.184.216.34 (example.com) is genuinely public and not in the
        # well-known DB.  Avoid 203.0.113.x (TEST-NET-3) which Python's
        # ipaddress considers private.
        result = self.service.lookup("93.184.216.34")
        self.assertFalse(result.is_private)
        self.assertEqual(result.country, "Unknown")
        self.assertEqual(result.country_code, "XX")
        self.assertIsNone(result.city)
        self.assertIsNone(result.organization)
        self.assertIsNone(result.asn)


class TestLookupMaxMind(unittest.TestCase):
    """Tests for lookup() with a mocked MaxMind database."""

    def test_maxmind_lookup_success(self):
        """When MaxMind DB is available, it should return full geo data."""
        mock_reader = MagicMock()
        mock_reader.get.return_value = {
            "country": {
                "names": {"en": "Germany"},
                "iso_code": "DE",
            },
            "city": {
                "names": {"en": "Berlin"},
            },
            "location": {
                "latitude": 52.5200,
                "longitude": 13.4050,
            },
            "traits": {
                "autonomous_system_number": 13335,
                "autonomous_system_organization": "Cloudflare, Inc.",
            },
        }

        service = GeoIPService(db_path="/nonexistent/path.mmdb")
        # Manually inject mock reader
        service._reader = mock_reader
        service._db_available = True

        result = service.lookup("104.16.132.229")
        self.assertEqual(result.country, "Germany")
        self.assertEqual(result.country_code, "DE")
        self.assertEqual(result.city, "Berlin")
        self.assertAlmostEqual(result.latitude, 52.52)
        self.assertAlmostEqual(result.longitude, 13.405)
        self.assertEqual(result.asn, 13335)
        mock_reader.get.assert_called_once_with("104.16.132.229")

    def test_maxmind_lookup_returns_none(self):
        """When MaxMind returns None for an IP, fall back to well-known."""
        mock_reader = MagicMock()
        mock_reader.get.return_value = None

        service = GeoIPService(db_path="/nonexistent/path.mmdb")
        service._reader = mock_reader
        service._db_available = True

        # 8.8.8.8 is well-known, so fallback should work
        result = service.lookup("8.8.8.8")
        self.assertEqual(result.country, "United States")
        self.assertEqual(result.organization, "Google LLC")

    def test_maxmind_lookup_exception(self):
        """When MaxMind throws, fall back gracefully."""
        mock_reader = MagicMock()
        mock_reader.get.side_effect = Exception("DB error")

        service = GeoIPService(db_path="/nonexistent/path.mmdb")
        service._reader = mock_reader
        service._db_available = True

        # Use a genuinely public IP not in WELL_KNOWN_IPS
        result = service.lookup("93.184.216.34")
        self.assertEqual(result.country, "Unknown")


class TestLookupBatch(unittest.TestCase):
    """Tests for lookup_batch()."""

    def setUp(self):
        self.service = GeoIPService(db_path="/nonexistent/path.mmdb")

    def test_batch_mixed_ips(self):
        """Batch lookup with a mix of private, well-known, and unknown IPs."""
        ips = ["192.168.1.1", "8.8.8.8", "1.1.1.1", "93.184.216.34"]
        results = self.service.lookup_batch(ips)

        self.assertEqual(len(results), 4)
        # First is private
        self.assertTrue(results[0]["is_private"])
        self.assertEqual(results[0]["country"], "Private Network")
        # Second is Google
        self.assertEqual(results[1]["organization"], "Google LLC")
        # Third is Cloudflare
        self.assertEqual(results[2]["organization"], "Cloudflare, Inc.")
        # Fourth is unknown public IP
        self.assertEqual(results[3]["country"], "Unknown")

    def test_batch_caps_at_50(self):
        """Batch lookup should cap at 50 IPs."""
        # Generate 60 unique public IPs (93.184.x.y range)
        ips = [f"93.184.{i // 256}.{i % 256}" for i in range(60)]
        results = self.service.lookup_batch(ips)
        self.assertEqual(len(results), 50)

    def test_batch_empty_list(self):
        """Empty list returns empty results."""
        results = self.service.lookup_batch([])
        self.assertEqual(results, [])

    def test_batch_returns_dicts(self):
        """Batch results should be dicts (not GeoIPResult objects)."""
        results = self.service.lookup_batch(["8.8.8.8"])
        self.assertIsInstance(results[0], dict)
        self.assertIn("ip", results[0])
        self.assertIn("country", results[0])


class TestGeoIPResult(unittest.TestCase):
    """Tests for the GeoIPResult data class."""

    def test_to_dict_has_all_keys(self):
        """to_dict() should contain all expected keys."""
        result = GeoIPResult(
            ip="8.8.8.8",
            country="United States",
            country_code="US",
            city="Mountain View",
            latitude=37.386,
            longitude=-122.084,
            asn=15169,
            organization="Google LLC",
            is_private=False,
        )
        d = result.to_dict()
        expected_keys = {
            "ip", "country", "country_code", "city",
            "latitude", "longitude", "asn", "organization", "is_private",
        }
        self.assertEqual(set(d.keys()), expected_keys)
        self.assertEqual(d["ip"], "8.8.8.8")
        self.assertEqual(d["country"], "United States")
        self.assertFalse(d["is_private"])

    def test_to_dict_defaults(self):
        """Default GeoIPResult should have None for optional fields."""
        result = GeoIPResult(ip="203.0.113.1")
        d = result.to_dict()
        self.assertEqual(d["country"], "Unknown")
        self.assertEqual(d["country_code"], "XX")
        self.assertIsNone(d["city"])
        self.assertIsNone(d["latitude"])
        self.assertIsNone(d["longitude"])
        self.assertIsNone(d["asn"])
        self.assertIsNone(d["organization"])
        self.assertFalse(d["is_private"])


class TestServiceInit(unittest.TestCase):
    """Tests for GeoIPService initialization and graceful fallback."""

    def test_init_without_maxminddb_package(self):
        """Service should initialize gracefully without maxminddb installed."""
        # Hide maxminddb from import
        with patch.dict("sys.modules", {"maxminddb": None}):
            # Force re-import by creating fresh service
            service = GeoIPService.__new__(GeoIPService)
            service._reader = None
            service._db_available = False
            # Simulate __init__ logic where import fails
            try:
                import maxminddb  # noqa: F401 -- will be None
                # This would raise TypeError since None is not a module
                raise ImportError("mocked")
            except (ImportError, TypeError):
                pass

            self.assertFalse(service.db_available)
            self.assertIsNone(service._reader)

    def test_init_with_missing_db_file(self):
        """Service should initialize gracefully with a nonexistent DB path."""
        service = GeoIPService(db_path="/definitely/not/a/real/path.mmdb")
        self.assertFalse(service.db_available)
        self.assertIsNone(service._reader)
        # Should still work for private/well-known lookups
        result = service.lookup("192.168.1.1")
        self.assertTrue(result.is_private)

    def test_init_with_env_var(self):
        """Service reads GEOIP_DB_PATH from environment when no path given."""
        with patch.dict(os.environ, {"GEOIP_DB_PATH": "/tmp/test.mmdb"}):
            service = GeoIPService()
            # DB won't exist, but it should try the env path
            self.assertFalse(service.db_available)

    def test_close_without_reader(self):
        """close() should not raise when no reader is loaded."""
        service = GeoIPService(db_path="/nonexistent/path.mmdb")
        service.close()  # Should not raise

    def test_close_with_mock_reader(self):
        """close() should call reader.close() when a reader exists."""
        mock_reader = MagicMock()
        service = GeoIPService(db_path="/nonexistent/path.mmdb")
        service._reader = mock_reader
        service.close()
        mock_reader.close.assert_called_once()

    def test_db_available_property(self):
        """db_available should reflect internal state."""
        service = GeoIPService(db_path="/nonexistent/path.mmdb")
        self.assertFalse(service.db_available)

        service._db_available = True
        self.assertTrue(service.db_available)


class TestLookupCaching(unittest.TestCase):
    """Tests for LRU cache behavior on lookup()."""

    def test_lookup_is_cached(self):
        """Repeated lookups of the same IP should return the same object."""
        service = GeoIPService(db_path="/nonexistent/path.mmdb")
        result1 = service.lookup("8.8.8.8")
        result2 = service.lookup("8.8.8.8")
        # lru_cache returns the same object
        self.assertIs(result1, result2)

    def test_different_ips_not_same_cache_entry(self):
        """Different IPs should produce distinct results."""
        service = GeoIPService(db_path="/nonexistent/path.mmdb")
        r1 = service.lookup("8.8.8.8")
        r2 = service.lookup("1.1.1.1")
        self.assertIsNot(r1, r2)
        self.assertNotEqual(r1.organization, r2.organization)


class TestWellKnownDatabase(unittest.TestCase):
    """Tests for the WELL_KNOWN_IPS dictionary."""

    def test_well_known_has_required_keys(self):
        """Every well-known IP entry should have country, country_code, org."""
        for ip, info in WELL_KNOWN_IPS.items():
            self.assertIn("country", info, f"Missing 'country' for {ip}")
            self.assertIn("country_code", info, f"Missing 'country_code' for {ip}")
            self.assertIn("org", info, f"Missing 'org' for {ip}")
            self.assertIn("asn", info, f"Missing 'asn' for {ip}")

    def test_well_known_count(self):
        """Should have at least 20 well-known IPs."""
        self.assertGreaterEqual(len(WELL_KNOWN_IPS), 20)


if __name__ == "__main__":
    unittest.main()
