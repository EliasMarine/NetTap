"""
Tests for daemon/api/baseline.py

All tests use mocks -- no file I/O or external dependencies required.
Tests cover the device baseline API endpoints using AioHTTPTestCase.
"""

import os
import tempfile
import unittest

import sys

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.baseline import register_baseline_routes
from services.device_baseline import DeviceBaseline


class TestGetBaselineEndpoint(AioHTTPTestCase):
    """Tests for GET /api/devices/baseline."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._baseline_path = os.path.join(self._tmpdir, "baseline.json")
        self.baseline = DeviceBaseline(baseline_file=self._baseline_path)
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_baseline_routes(app, self.baseline)
        return app

    def tearDown(self):
        super().tearDown()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    @unittest_run_loop
    async def test_get_empty_baseline(self):
        """GET /api/devices/baseline returns empty baseline."""
        resp = await self.client.request("GET", "/api/devices/baseline")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["devices"], {})

    @unittest_run_loop
    async def test_get_baseline_with_devices(self):
        """GET /api/devices/baseline returns devices after adding."""
        self.baseline.add_to_baseline("AA:BB:CC:DD:EE:FF", {"ip": "192.168.1.10"})
        resp = await self.client.request("GET", "/api/devices/baseline")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["count"], 1)
        self.assertIn("AA:BB:CC:DD:EE:FF", data["devices"])

    @unittest_run_loop
    async def test_get_baseline_response_has_count(self):
        """Response should include count field."""
        resp = await self.client.request("GET", "/api/devices/baseline")
        data = await resp.json()
        self.assertIn("count", data)
        self.assertIn("devices", data)


class TestCheckBaselineGetEndpoint(AioHTTPTestCase):
    """Tests for GET /api/devices/baseline/check."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._baseline_path = os.path.join(self._tmpdir, "baseline.json")
        self.baseline = DeviceBaseline(baseline_file=self._baseline_path)
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_baseline_routes(app, self.baseline)
        return app

    def tearDown(self):
        super().tearDown()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    @unittest_run_loop
    async def test_check_no_current_devices(self):
        """GET check with no current devices returns empty alerts."""
        resp = await self.client.request("GET", "/api/devices/baseline/check")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["new_device_count"], 0)
        self.assertEqual(data["alerts"], [])

    @unittest_run_loop
    async def test_check_with_current_devices_in_app(self):
        """GET check uses current_devices from app context."""
        self.app["current_devices"] = [
            {"mac": "FF:EE:DD:CC:BB:AA", "ip": "192.168.1.99"}
        ]
        resp = await self.client.request("GET", "/api/devices/baseline/check")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["new_device_count"], 1)
        self.assertEqual(data["alerts"][0]["mac"], "FF:EE:DD:CC:BB:AA")


class TestCheckBaselinePostEndpoint(AioHTTPTestCase):
    """Tests for POST /api/devices/baseline/check."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._baseline_path = os.path.join(self._tmpdir, "baseline.json")
        self.baseline = DeviceBaseline(baseline_file=self._baseline_path)
        self.baseline.add_to_baseline("AA:BB:CC:DD:EE:FF", {"ip": "192.168.1.10"})
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_baseline_routes(app, self.baseline)
        return app

    def tearDown(self):
        super().tearDown()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    @unittest_run_loop
    async def test_check_post_known_device(self):
        """POST check with known device returns no alerts."""
        body = {"devices": [{"mac": "AA:BB:CC:DD:EE:FF", "ip": "192.168.1.10"}]}
        resp = await self.client.request(
            "POST", "/api/devices/baseline/check", json=body
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["new_device_count"], 0)

    @unittest_run_loop
    async def test_check_post_new_device(self):
        """POST check with unknown device returns alert."""
        body = {"devices": [{"mac": "FF:EE:DD:CC:BB:AA", "ip": "192.168.1.99"}]}
        resp = await self.client.request(
            "POST", "/api/devices/baseline/check", json=body
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["new_device_count"], 1)
        self.assertEqual(data["alerts"][0]["type"], "new_device")

    @unittest_run_loop
    async def test_check_post_invalid_json(self):
        """POST check with invalid JSON returns 400."""
        resp = await self.client.request(
            "POST",
            "/api/devices/baseline/check",
            data="not json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_check_post_devices_not_list(self):
        """POST check with non-list devices returns 400."""
        body = {"devices": "not a list"}
        resp = await self.client.request(
            "POST", "/api/devices/baseline/check", json=body
        )
        self.assertEqual(resp.status, 400)


class TestAddToBaselineEndpoint(AioHTTPTestCase):
    """Tests for POST /api/devices/baseline/add."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._baseline_path = os.path.join(self._tmpdir, "baseline.json")
        self.baseline = DeviceBaseline(baseline_file=self._baseline_path)
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_baseline_routes(app, self.baseline)
        return app

    def tearDown(self):
        super().tearDown()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    @unittest_run_loop
    async def test_add_device_success(self):
        """POST /api/devices/baseline/add adds a device."""
        body = {"mac": "AA:BB:CC:DD:EE:FF", "ip": "192.168.1.10", "hostname": "laptop"}
        resp = await self.client.request(
            "POST", "/api/devices/baseline/add", json=body
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["result"], "added")
        self.assertEqual(data["mac"], "AA:BB:CC:DD:EE:FF")
        self.assertEqual(data["baseline_count"], 1)

    @unittest_run_loop
    async def test_add_device_missing_mac(self):
        """POST add without MAC returns 400."""
        body = {"ip": "192.168.1.10"}
        resp = await self.client.request(
            "POST", "/api/devices/baseline/add", json=body
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_add_device_invalid_json(self):
        """POST add with invalid JSON returns 400."""
        resp = await self.client.request(
            "POST",
            "/api/devices/baseline/add",
            data="not json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_add_device_empty_mac(self):
        """POST add with empty MAC returns 400."""
        body = {"mac": "", "ip": "192.168.1.10"}
        resp = await self.client.request(
            "POST", "/api/devices/baseline/add", json=body
        )
        self.assertEqual(resp.status, 400)


class TestRemoveFromBaselineEndpoint(AioHTTPTestCase):
    """Tests for DELETE /api/devices/baseline/{mac}."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._baseline_path = os.path.join(self._tmpdir, "baseline.json")
        self.baseline = DeviceBaseline(baseline_file=self._baseline_path)
        self.baseline.add_to_baseline("AA:BB:CC:DD:EE:FF", {"ip": "192.168.1.10"})
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_baseline_routes(app, self.baseline)
        return app

    def tearDown(self):
        super().tearDown()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    @unittest_run_loop
    async def test_remove_existing_device(self):
        """DELETE baseline/{mac} removes known device."""
        resp = await self.client.request(
            "DELETE", "/api/devices/baseline/AA:BB:CC:DD:EE:FF"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["result"], "removed")
        self.assertEqual(data["baseline_count"], 0)

    @unittest_run_loop
    async def test_remove_nonexistent_device(self):
        """DELETE baseline/{mac} for unknown MAC returns 404."""
        resp = await self.client.request(
            "DELETE", "/api/devices/baseline/FF:EE:DD:CC:BB:AA"
        )
        self.assertEqual(resp.status, 404)

    @unittest_run_loop
    async def test_remove_device_reduces_count(self):
        """After removal, baseline count decreases."""
        self.baseline.add_to_baseline("11:22:33:44:55:66", {"ip": "192.168.1.20"})
        resp = await self.client.request(
            "DELETE", "/api/devices/baseline/AA:BB:CC:DD:EE:FF"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["baseline_count"], 1)


class TestBaselineRouteRegistration(AioHTTPTestCase):
    """Tests for route registration."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._baseline_path = os.path.join(self._tmpdir, "baseline.json")
        self.baseline = DeviceBaseline(baseline_file=self._baseline_path)
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_baseline_routes(app, self.baseline)
        return app

    def tearDown(self):
        super().tearDown()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    @unittest_run_loop
    async def test_baseline_stored_on_app(self):
        """The DeviceBaseline should be stored on the app dict."""
        self.assertIs(self.app["device_baseline"], self.baseline)

    @unittest_run_loop
    async def test_all_routes_registered(self):
        """All baseline routes should be registered."""
        # Test GET baseline
        resp = await self.client.request("GET", "/api/devices/baseline")
        self.assertNotEqual(resp.status, 404)
        # Test GET check
        resp = await self.client.request("GET", "/api/devices/baseline/check")
        self.assertNotEqual(resp.status, 404)
        # Test POST add
        resp = await self.client.request(
            "POST",
            "/api/devices/baseline/add",
            json={"mac": "AA:BB:CC:DD:EE:FF"},
        )
        self.assertNotEqual(resp.status, 404)


if __name__ == "__main__":
    unittest.main()
