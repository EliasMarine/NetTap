"""
Tests for daemon/api/detection_packs.py

All tests use a real DetectionPackManager with a temp directory --
no external dependencies required. Tests cover all detection pack
API endpoints.
"""

import unittest
import tempfile
import shutil

import sys
import os

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.detection_packs import register_detection_pack_routes
from services.detection_packs import DetectionPackManager


class TestListPacksEndpoint(AioHTTPTestCase):
    """Tests for GET /api/detection-packs."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.manager = DetectionPackManager(packs_dir=self.tmpdir)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def get_application(self):
        app = web.Application()
        register_detection_pack_routes(app, self.manager)
        return app

    @unittest_run_loop
    async def test_list_empty(self):
        """GET /api/detection-packs with no packs returns empty list."""
        resp = await self.client.request("GET", "/api/detection-packs")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["packs"], [])

    @unittest_run_loop
    async def test_list_after_install(self):
        """GET /api/detection-packs after install returns packs."""
        self.manager.install_pack("et-open")
        resp = await self.client.request("GET", "/api/detection-packs")
        data = await resp.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["packs"][0]["id"], "et-open")


class TestGetPackEndpoint(AioHTTPTestCase):
    """Tests for GET /api/detection-packs/{id}."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.manager = DetectionPackManager(packs_dir=self.tmpdir)
        self.manager.install_pack("et-open")
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def get_application(self):
        app = web.Application()
        register_detection_pack_routes(app, self.manager)
        return app

    @unittest_run_loop
    async def test_get_existing_pack(self):
        """GET /api/detection-packs/et-open returns pack details."""
        resp = await self.client.request("GET", "/api/detection-packs/et-open")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["id"], "et-open")
        self.assertEqual(data["name"], "Emerging Threats Open")

    @unittest_run_loop
    async def test_get_nonexistent_pack(self):
        """GET /api/detection-packs/nonexistent returns 404."""
        resp = await self.client.request("GET", "/api/detection-packs/nonexistent")
        self.assertEqual(resp.status, 404)


class TestInstallPackEndpoint(AioHTTPTestCase):
    """Tests for POST /api/detection-packs/{id}/install."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.manager = DetectionPackManager(packs_dir=self.tmpdir)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def get_application(self):
        app = web.Application()
        register_detection_pack_routes(app, self.manager)
        return app

    @unittest_run_loop
    async def test_install_pack(self):
        """POST /api/detection-packs/et-open/install installs the pack."""
        resp = await self.client.request("POST", "/api/detection-packs/et-open/install")
        self.assertEqual(resp.status, 201)
        data = await resp.json()
        self.assertEqual(data["id"], "et-open")
        self.assertTrue(data["enabled"])

    @unittest_run_loop
    async def test_install_already_installed(self):
        """Installing an already-installed pack returns 400."""
        self.manager.install_pack("et-open")
        resp = await self.client.request("POST", "/api/detection-packs/et-open/install")
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("error", data)

    @unittest_run_loop
    async def test_install_unknown_pack(self):
        """Installing an unknown pack returns 400."""
        resp = await self.client.request("POST", "/api/detection-packs/unknown-pack/install")
        self.assertEqual(resp.status, 400)


class TestUninstallPackEndpoint(AioHTTPTestCase):
    """Tests for DELETE /api/detection-packs/{id}."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.manager = DetectionPackManager(packs_dir=self.tmpdir)
        self.manager.install_pack("et-open")
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def get_application(self):
        app = web.Application()
        register_detection_pack_routes(app, self.manager)
        return app

    @unittest_run_loop
    async def test_uninstall_pack(self):
        """DELETE /api/detection-packs/et-open uninstalls the pack."""
        resp = await self.client.request("DELETE", "/api/detection-packs/et-open")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["result"], "uninstalled")

    @unittest_run_loop
    async def test_uninstall_nonexistent(self):
        """DELETE /api/detection-packs/nonexistent returns 404."""
        resp = await self.client.request("DELETE", "/api/detection-packs/nonexistent")
        self.assertEqual(resp.status, 404)


class TestEnableDisablePackEndpoints(AioHTTPTestCase):
    """Tests for POST enable/disable endpoints."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.manager = DetectionPackManager(packs_dir=self.tmpdir)
        self.manager.install_pack("et-open")
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def get_application(self):
        app = web.Application()
        register_detection_pack_routes(app, self.manager)
        return app

    @unittest_run_loop
    async def test_disable_pack(self):
        """POST /api/detection-packs/et-open/disable disables the pack."""
        resp = await self.client.request("POST", "/api/detection-packs/et-open/disable")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertFalse(data["enabled"])

    @unittest_run_loop
    async def test_enable_pack(self):
        """POST /api/detection-packs/et-open/enable enables the pack."""
        self.manager.disable_pack("et-open")
        resp = await self.client.request("POST", "/api/detection-packs/et-open/enable")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["enabled"])

    @unittest_run_loop
    async def test_disable_nonexistent(self):
        """Disabling nonexistent pack returns 404."""
        resp = await self.client.request("POST", "/api/detection-packs/nope/disable")
        self.assertEqual(resp.status, 404)

    @unittest_run_loop
    async def test_enable_nonexistent(self):
        """Enabling nonexistent pack returns 404."""
        resp = await self.client.request("POST", "/api/detection-packs/nope/enable")
        self.assertEqual(resp.status, 404)


class TestCheckUpdatesEndpoint(AioHTTPTestCase):
    """Tests for GET /api/detection-packs/updates."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.manager = DetectionPackManager(packs_dir=self.tmpdir)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def get_application(self):
        app = web.Application()
        register_detection_pack_routes(app, self.manager)
        return app

    @unittest_run_loop
    async def test_check_updates(self):
        """GET /api/detection-packs/updates returns update info."""
        resp = await self.client.request("GET", "/api/detection-packs/updates")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("updates", data)
        self.assertIn("count", data)


class TestPackStatsEndpoint(AioHTTPTestCase):
    """Tests for GET /api/detection-packs/stats."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.manager = DetectionPackManager(packs_dir=self.tmpdir)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def get_application(self):
        app = web.Application()
        register_detection_pack_routes(app, self.manager)
        return app

    @unittest_run_loop
    async def test_stats_empty(self):
        """GET /api/detection-packs/stats with no packs."""
        resp = await self.client.request("GET", "/api/detection-packs/stats")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["total_packs"], 0)

    @unittest_run_loop
    async def test_stats_with_packs(self):
        """GET /api/detection-packs/stats after installing packs."""
        self.manager.install_pack("et-open")
        resp = await self.client.request("GET", "/api/detection-packs/stats")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["total_packs"], 1)
        self.assertEqual(data["enabled_packs"], 1)


class TestAvailablePacksEndpoint(AioHTTPTestCase):
    """Tests for GET /api/detection-packs/available."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.manager = DetectionPackManager(packs_dir=self.tmpdir)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def get_application(self):
        app = web.Application()
        register_detection_pack_routes(app, self.manager)
        return app

    @unittest_run_loop
    async def test_available_packs(self):
        """GET /api/detection-packs/available lists all builtin packs."""
        resp = await self.client.request("GET", "/api/detection-packs/available")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertGreater(data["count"], 0)
        # All should be not installed
        for p in data["packs"]:
            self.assertFalse(p["installed"])


class TestRouteRegistration(AioHTTPTestCase):
    """Tests for route registration."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.manager = DetectionPackManager(packs_dir=self.tmpdir)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def get_application(self):
        app = web.Application()
        register_detection_pack_routes(app, self.manager)
        return app

    @unittest_run_loop
    async def test_manager_stored_on_app(self):
        """The DetectionPackManager should be stored on the app dict."""
        self.assertIs(self.app["detection_pack_manager"], self.manager)


if __name__ == "__main__":
    unittest.main()
