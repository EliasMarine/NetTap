"""
Tests for daemon/api/reports.py

All tests use a real ReportGenerator with a temp directory --
no external dependencies required. Tests cover all scheduled report
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

from api.reports import register_report_routes
from services.report_generator import ReportGenerator


class TestListSchedulesEndpoint(AioHTTPTestCase):
    """Tests for GET /api/reports/schedules."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sfile = os.path.join(self.tmpdir, "schedules.json")
        self.generator = ReportGenerator(
            reports_dir=self.tmpdir, schedules_file=self.sfile
        )
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def get_application(self):
        app = web.Application()
        register_report_routes(app, self.generator)
        return app

    @unittest_run_loop
    async def test_list_empty(self):
        """GET /api/reports/schedules with no schedules returns empty list."""
        resp = await self.client.request("GET", "/api/reports/schedules")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["schedules"], [])

    @unittest_run_loop
    async def test_list_after_create(self):
        """GET /api/reports/schedules lists created schedules."""
        self.generator.create_schedule(
            name="Test", frequency="daily", format="json",
            sections=["alerts"],
        )
        resp = await self.client.request("GET", "/api/reports/schedules")
        data = await resp.json()
        self.assertEqual(data["count"], 1)


class TestCreateScheduleEndpoint(AioHTTPTestCase):
    """Tests for POST /api/reports/schedules."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sfile = os.path.join(self.tmpdir, "schedules.json")
        self.generator = ReportGenerator(
            reports_dir=self.tmpdir, schedules_file=self.sfile
        )
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def get_application(self):
        app = web.Application()
        register_report_routes(app, self.generator)
        return app

    @unittest_run_loop
    async def test_create_schedule(self):
        """POST /api/reports/schedules creates a schedule."""
        resp = await self.client.request(
            "POST",
            "/api/reports/schedules",
            json={
                "name": "Daily Alerts",
                "frequency": "daily",
                "format": "json",
                "sections": ["alerts", "risk"],
            },
        )
        self.assertEqual(resp.status, 201)
        data = await resp.json()
        self.assertEqual(data["name"], "Daily Alerts")
        self.assertTrue(data["enabled"])

    @unittest_run_loop
    async def test_create_missing_name(self):
        """POST without name returns 400."""
        resp = await self.client.request(
            "POST",
            "/api/reports/schedules",
            json={
                "frequency": "daily",
                "format": "json",
                "sections": ["alerts"],
            },
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_create_invalid_frequency(self):
        """POST with invalid frequency returns 400."""
        resp = await self.client.request(
            "POST",
            "/api/reports/schedules",
            json={
                "name": "Bad",
                "frequency": "hourly",
                "format": "json",
                "sections": ["alerts"],
            },
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_create_invalid_json(self):
        """POST with invalid JSON returns 400."""
        resp = await self.client.request(
            "POST",
            "/api/reports/schedules",
            data="not json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 400)


class TestGetScheduleEndpoint(AioHTTPTestCase):
    """Tests for GET /api/reports/schedules/{id}."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sfile = os.path.join(self.tmpdir, "schedules.json")
        self.generator = ReportGenerator(
            reports_dir=self.tmpdir, schedules_file=self.sfile
        )
        self.schedule = self.generator.create_schedule(
            name="Test", frequency="daily", format="json",
            sections=["alerts"],
        )
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def get_application(self):
        app = web.Application()
        register_report_routes(app, self.generator)
        return app

    @unittest_run_loop
    async def test_get_existing(self):
        """GET /api/reports/schedules/{id} returns schedule."""
        resp = await self.client.request(
            "GET", f"/api/reports/schedules/{self.schedule.id}"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["name"], "Test")

    @unittest_run_loop
    async def test_get_nonexistent(self):
        """GET /api/reports/schedules/{id} returns 404 for unknown."""
        resp = await self.client.request(
            "GET", "/api/reports/schedules/nonexistent-id"
        )
        self.assertEqual(resp.status, 404)


class TestUpdateScheduleEndpoint(AioHTTPTestCase):
    """Tests for PUT /api/reports/schedules/{id}."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sfile = os.path.join(self.tmpdir, "schedules.json")
        self.generator = ReportGenerator(
            reports_dir=self.tmpdir, schedules_file=self.sfile
        )
        self.schedule = self.generator.create_schedule(
            name="Original", frequency="daily", format="json",
            sections=["alerts"],
        )
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def get_application(self):
        app = web.Application()
        register_report_routes(app, self.generator)
        return app

    @unittest_run_loop
    async def test_update_name(self):
        """PUT updates schedule name."""
        resp = await self.client.request(
            "PUT",
            f"/api/reports/schedules/{self.schedule.id}",
            json={"name": "Updated"},
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["name"], "Updated")

    @unittest_run_loop
    async def test_update_nonexistent(self):
        """PUT on nonexistent schedule returns 404."""
        resp = await self.client.request(
            "PUT",
            "/api/reports/schedules/nonexistent",
            json={"name": "Test"},
        )
        self.assertEqual(resp.status, 404)


class TestDeleteScheduleEndpoint(AioHTTPTestCase):
    """Tests for DELETE /api/reports/schedules/{id}."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sfile = os.path.join(self.tmpdir, "schedules.json")
        self.generator = ReportGenerator(
            reports_dir=self.tmpdir, schedules_file=self.sfile
        )
        self.schedule = self.generator.create_schedule(
            name="To Delete", frequency="daily", format="json",
            sections=["alerts"],
        )
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def get_application(self):
        app = web.Application()
        register_report_routes(app, self.generator)
        return app

    @unittest_run_loop
    async def test_delete_schedule(self):
        """DELETE removes schedule."""
        resp = await self.client.request(
            "DELETE", f"/api/reports/schedules/{self.schedule.id}"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["result"], "deleted")

    @unittest_run_loop
    async def test_delete_nonexistent(self):
        """DELETE nonexistent returns 404."""
        resp = await self.client.request(
            "DELETE", "/api/reports/schedules/nonexistent"
        )
        self.assertEqual(resp.status, 404)


class TestEnableDisableScheduleEndpoints(AioHTTPTestCase):
    """Tests for enable/disable endpoints."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sfile = os.path.join(self.tmpdir, "schedules.json")
        self.generator = ReportGenerator(
            reports_dir=self.tmpdir, schedules_file=self.sfile
        )
        self.schedule = self.generator.create_schedule(
            name="Test", frequency="daily", format="json",
            sections=["alerts"],
        )
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def get_application(self):
        app = web.Application()
        register_report_routes(app, self.generator)
        return app

    @unittest_run_loop
    async def test_disable_schedule(self):
        """POST /api/reports/schedules/{id}/disable disables schedule."""
        resp = await self.client.request(
            "POST", f"/api/reports/schedules/{self.schedule.id}/disable"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertFalse(data["enabled"])

    @unittest_run_loop
    async def test_enable_schedule(self):
        """POST /api/reports/schedules/{id}/enable enables schedule."""
        self.generator.disable_schedule(self.schedule.id)
        resp = await self.client.request(
            "POST", f"/api/reports/schedules/{self.schedule.id}/enable"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["enabled"])

    @unittest_run_loop
    async def test_disable_nonexistent(self):
        """Disable nonexistent returns 404."""
        resp = await self.client.request(
            "POST", "/api/reports/schedules/nonexistent/disable"
        )
        self.assertEqual(resp.status, 404)

    @unittest_run_loop
    async def test_enable_nonexistent(self):
        """Enable nonexistent returns 404."""
        resp = await self.client.request(
            "POST", "/api/reports/schedules/nonexistent/enable"
        )
        self.assertEqual(resp.status, 404)


class TestGenerateReportEndpoint(AioHTTPTestCase):
    """Tests for POST /api/reports/generate/{id}."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sfile = os.path.join(self.tmpdir, "schedules.json")
        self.generator = ReportGenerator(
            reports_dir=self.tmpdir, schedules_file=self.sfile
        )
        self.schedule = self.generator.create_schedule(
            name="Full Report",
            frequency="daily",
            format="json",
            sections=["traffic_summary", "alerts", "risk"],
        )
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def get_application(self):
        app = web.Application()
        register_report_routes(app, self.generator)
        return app

    @unittest_run_loop
    async def test_generate_report(self):
        """POST /api/reports/generate/{id} generates report."""
        resp = await self.client.request(
            "POST", f"/api/reports/generate/{self.schedule.id}"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("sections", data)
        self.assertIn("traffic_summary", data["sections"])
        self.assertIn("alerts", data["sections"])
        self.assertIn("risk", data["sections"])

    @unittest_run_loop
    async def test_generate_nonexistent(self):
        """Generating report for unknown schedule returns 404."""
        resp = await self.client.request(
            "POST", "/api/reports/generate/nonexistent"
        )
        self.assertEqual(resp.status, 404)


class TestRouteRegistration(AioHTTPTestCase):
    """Tests for route registration."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sfile = os.path.join(self.tmpdir, "schedules.json")
        self.generator = ReportGenerator(
            reports_dir=self.tmpdir, schedules_file=self.sfile
        )
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def get_application(self):
        app = web.Application()
        register_report_routes(app, self.generator)
        return app

    @unittest_run_loop
    async def test_generator_stored_on_app(self):
        """The ReportGenerator should be stored on the app dict."""
        self.assertIs(self.app["report_generator"], self.generator)


if __name__ == "__main__":
    unittest.main()
