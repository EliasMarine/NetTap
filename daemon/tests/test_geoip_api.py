"""
Tests for daemon/api/geoip.py

All tests use mocks -- no MaxMind database or external dependencies required.
Tests cover single IP lookup, batch lookup, validation, error handling,
and edge cases.
"""

import unittest

import sys
import os

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.geoip import register_geoip_routes
from services.geoip_service import GeoIPService


def _make_geoip_service() -> GeoIPService:
    """Create a GeoIPService in fallback mode (no MaxMind DB)."""
    return GeoIPService(db_path="/nonexistent/path.mmdb")


class TestGeoIPLookupHandler(AioHTTPTestCase):
    """Tests for GET /api/geoip/{ip}."""

    def setUp(self):
        self.geoip_service = _make_geoip_service()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_geoip_routes(app, self.geoip_service)
        return app

    @unittest_run_loop
    async def test_lookup_google_dns(self):
        """GET /api/geoip/8.8.8.8 returns Google data."""
        resp = await self.client.request("GET", "/api/geoip/8.8.8.8")
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertEqual(data["ip"], "8.8.8.8")
        self.assertEqual(data["country"], "United States")
        self.assertEqual(data["country_code"], "US")
        self.assertEqual(data["city"], "Mountain View")
        self.assertEqual(data["organization"], "Google LLC")
        self.assertEqual(data["asn"], 15169)
        self.assertFalse(data["is_private"])

    @unittest_run_loop
    async def test_lookup_private_ip(self):
        """GET /api/geoip/192.168.1.1 returns private network data."""
        resp = await self.client.request("GET", "/api/geoip/192.168.1.1")
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertEqual(data["ip"], "192.168.1.1")
        self.assertEqual(data["country"], "Private Network")
        self.assertEqual(data["country_code"], "XX")
        self.assertTrue(data["is_private"])

    @unittest_run_loop
    async def test_lookup_cloudflare_dns(self):
        """GET /api/geoip/1.1.1.1 returns Cloudflare data."""
        resp = await self.client.request("GET", "/api/geoip/1.1.1.1")
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertEqual(data["organization"], "Cloudflare, Inc.")
        self.assertEqual(data["asn"], 13335)

    @unittest_run_loop
    async def test_lookup_invalid_ip(self):
        """GET /api/geoip/invalid returns 400."""
        resp = await self.client.request("GET", "/api/geoip/invalid")
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("error", data)
        self.assertIn("Invalid IP address", data["error"])

    @unittest_run_loop
    async def test_lookup_unknown_public_ip(self):
        """GET /api/geoip/<unknown-public> returns Unknown country."""
        # Use a genuinely public IP (not in TEST-NET ranges which Python
        # considers private) that is not in the well-known database.
        resp = await self.client.request("GET", "/api/geoip/93.184.216.34")
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertEqual(data["country"], "Unknown")
        self.assertEqual(data["country_code"], "XX")
        self.assertFalse(data["is_private"])

    @unittest_run_loop
    async def test_lookup_loopback(self):
        """GET /api/geoip/127.0.0.1 returns private network data."""
        resp = await self.client.request("GET", "/api/geoip/127.0.0.1")
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertTrue(data["is_private"])
        self.assertEqual(data["country"], "Private Network")

    @unittest_run_loop
    async def test_lookup_response_has_all_fields(self):
        """Response JSON should contain all expected GeoIP fields."""
        resp = await self.client.request("GET", "/api/geoip/8.8.8.8")
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        expected_keys = {
            "ip", "country", "country_code", "city",
            "latitude", "longitude", "asn", "organization", "is_private",
        }
        self.assertEqual(set(data.keys()), expected_keys)


class TestGeoIPBatchHandler(AioHTTPTestCase):
    """Tests for GET /api/geoip/batch."""

    def setUp(self):
        self.geoip_service = _make_geoip_service()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_geoip_routes(app, self.geoip_service)
        return app

    @unittest_run_loop
    async def test_batch_success(self):
        """GET /api/geoip/batch?ips=8.8.8.8,1.1.1.1 returns results array."""
        resp = await self.client.request(
            "GET", "/api/geoip/batch?ips=8.8.8.8,1.1.1.1"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertIn("results", data)
        self.assertEqual(len(data["results"]), 2)
        self.assertEqual(data["results"][0]["ip"], "8.8.8.8")
        self.assertEqual(data["results"][0]["organization"], "Google LLC")
        self.assertEqual(data["results"][1]["ip"], "1.1.1.1")
        self.assertEqual(data["results"][1]["organization"], "Cloudflare, Inc.")

    @unittest_run_loop
    async def test_batch_missing_ips_param(self):
        """GET /api/geoip/batch without ips param returns 400."""
        resp = await self.client.request("GET", "/api/geoip/batch")
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("error", data)

    @unittest_run_loop
    async def test_batch_empty_ips_param(self):
        """GET /api/geoip/batch?ips= returns 400."""
        resp = await self.client.request("GET", "/api/geoip/batch?ips=")
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("error", data)

    @unittest_run_loop
    async def test_batch_mixed_valid_invalid(self):
        """Batch with some invalid IPs should return results + invalid list."""
        resp = await self.client.request(
            "GET", "/api/geoip/batch?ips=8.8.8.8,not-an-ip,1.1.1.1"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertEqual(len(data["results"]), 2)
        self.assertIn("invalid", data)
        self.assertEqual(data["invalid"], ["not-an-ip"])

    @unittest_run_loop
    async def test_batch_all_invalid(self):
        """Batch with all invalid IPs returns 400."""
        resp = await self.client.request(
            "GET", "/api/geoip/batch?ips=foo,bar,baz"
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("error", data)
        self.assertIn("No valid IP addresses", data["error"])

    @unittest_run_loop
    async def test_batch_caps_at_50(self):
        """Batch with >50 IPs should only return 50 results."""
        ips = ",".join(f"93.184.{i // 256}.{i % 256}" for i in range(60))
        resp = await self.client.request(
            "GET", f"/api/geoip/batch?ips={ips}"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertEqual(len(data["results"]), 50)

    @unittest_run_loop
    async def test_batch_with_private_ips(self):
        """Batch with private IPs should mark them correctly."""
        resp = await self.client.request(
            "GET", "/api/geoip/batch?ips=192.168.1.1,8.8.8.8"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertEqual(len(data["results"]), 2)
        self.assertTrue(data["results"][0]["is_private"])
        self.assertFalse(data["results"][1]["is_private"])

    @unittest_run_loop
    async def test_batch_single_ip(self):
        """Batch with a single IP still works."""
        resp = await self.client.request(
            "GET", "/api/geoip/batch?ips=9.9.9.9"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["organization"], "Quad9")


class TestRouteRegistration(AioHTTPTestCase):
    """Tests for route registration and route ordering."""

    def setUp(self):
        self.geoip_service = _make_geoip_service()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_geoip_routes(app, self.geoip_service)
        return app

    @unittest_run_loop
    async def test_batch_not_captured_by_ip_route(self):
        """The /batch route should not be captured by the /{ip} route."""
        resp = await self.client.request(
            "GET", "/api/geoip/batch?ips=8.8.8.8"
        )
        # Should get 200 from batch handler, not 400 from IP validation
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("results", data)

    @unittest_run_loop
    async def test_geoip_stored_on_app(self):
        """The GeoIPService should be stored on the app dict."""
        self.assertIs(self.app["geoip"], self.geoip_service)


if __name__ == "__main__":
    unittest.main()
