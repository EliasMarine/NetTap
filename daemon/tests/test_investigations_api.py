"""
Tests for daemon/api/investigations.py

All tests use a temporary file-backed InvestigationStore. Tests cover
all CRUD endpoints, notes management, alert linking, device linking,
and statistics.
"""

import os
import tempfile
import unittest

import sys

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.investigations import register_investigation_routes
from services.investigation_store import InvestigationStore


class TestListInvestigations(AioHTTPTestCase):
    """Tests for GET /api/investigations."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = InvestigationStore(store_file=self.tmp.name)
        self.store.create(title="Case 1", severity="high")
        self.store.create(title="Case 2", severity="low")
        super().setUp()

    def tearDown(self):
        super().tearDown()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    async def get_application(self):
        app = web.Application()
        register_investigation_routes(app, self.store)
        return app

    @unittest_run_loop
    async def test_list_all(self):
        """GET /api/investigations returns all investigations."""
        resp = await self.client.request("GET", "/api/investigations")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["count"], 2)

    @unittest_run_loop
    async def test_list_filter_severity(self):
        """GET /api/investigations?severity=high returns filtered list."""
        resp = await self.client.request("GET", "/api/investigations?severity=high")
        data = await resp.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["investigations"][0]["severity"], "high")

    @unittest_run_loop
    async def test_list_filter_invalid_status(self):
        """GET /api/investigations?status=bad returns 400."""
        resp = await self.client.request("GET", "/api/investigations?status=bad")
        self.assertEqual(resp.status, 400)


class TestCreateInvestigation(AioHTTPTestCase):
    """Tests for POST /api/investigations."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = InvestigationStore(store_file=self.tmp.name)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    async def get_application(self):
        app = web.Application()
        register_investigation_routes(app, self.store)
        return app

    @unittest_run_loop
    async def test_create_success(self):
        """POST /api/investigations creates a new investigation."""
        resp = await self.client.request(
            "POST", "/api/investigations",
            json={"title": "New Case", "severity": "high"},
        )
        self.assertEqual(resp.status, 201)
        data = await resp.json()
        self.assertEqual(data["title"], "New Case")
        self.assertEqual(data["severity"], "high")
        self.assertEqual(data["status"], "open")
        self.assertIn("id", data)

    @unittest_run_loop
    async def test_create_missing_title(self):
        """POST /api/investigations without title returns 400."""
        resp = await self.client.request(
            "POST", "/api/investigations",
            json={"description": "No title"},
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_create_invalid_severity(self):
        """POST /api/investigations with invalid severity returns 400."""
        resp = await self.client.request(
            "POST", "/api/investigations",
            json={"title": "Bad", "severity": "extreme"},
        )
        self.assertEqual(resp.status, 400)


class TestGetUpdateDeleteInvestigation(AioHTTPTestCase):
    """Tests for GET/PUT/DELETE /api/investigations/{id}."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = InvestigationStore(store_file=self.tmp.name)
        self.inv = self.store.create(title="Test Case")
        super().setUp()

    def tearDown(self):
        super().tearDown()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    async def get_application(self):
        app = web.Application()
        register_investigation_routes(app, self.store)
        return app

    @unittest_run_loop
    async def test_get_existing(self):
        """GET /api/investigations/{id} returns the investigation."""
        resp = await self.client.request("GET", f"/api/investigations/{self.inv.id}")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["title"], "Test Case")

    @unittest_run_loop
    async def test_get_nonexistent(self):
        """GET /api/investigations/{id} returns 404 for unknown ID."""
        resp = await self.client.request("GET", "/api/investigations/bad-id")
        self.assertEqual(resp.status, 404)

    @unittest_run_loop
    async def test_update_title(self):
        """PUT /api/investigations/{id} updates the investigation."""
        resp = await self.client.request(
            "PUT", f"/api/investigations/{self.inv.id}",
            json={"title": "Updated Title"},
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["title"], "Updated Title")

    @unittest_run_loop
    async def test_update_nonexistent(self):
        """PUT /api/investigations/bad-id returns 404."""
        resp = await self.client.request(
            "PUT", "/api/investigations/bad-id",
            json={"title": "Nope"},
        )
        self.assertEqual(resp.status, 404)

    @unittest_run_loop
    async def test_update_invalid_status(self):
        """PUT /api/investigations/{id} with invalid status returns 400."""
        resp = await self.client.request(
            "PUT", f"/api/investigations/{self.inv.id}",
            json={"status": "invalid"},
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_delete_existing(self):
        """DELETE /api/investigations/{id} deletes the investigation."""
        resp = await self.client.request("DELETE", f"/api/investigations/{self.inv.id}")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["result"], "deleted")

    @unittest_run_loop
    async def test_delete_nonexistent(self):
        """DELETE /api/investigations/bad-id returns 404."""
        resp = await self.client.request("DELETE", "/api/investigations/bad-id")
        self.assertEqual(resp.status, 404)


class TestNotesEndpoints(AioHTTPTestCase):
    """Tests for note CRUD endpoints."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = InvestigationStore(store_file=self.tmp.name)
        self.inv = self.store.create(title="Notes Test")
        super().setUp()

    def tearDown(self):
        super().tearDown()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    async def get_application(self):
        app = web.Application()
        register_investigation_routes(app, self.store)
        return app

    @unittest_run_loop
    async def test_add_note(self):
        """POST /api/investigations/{id}/notes adds a note."""
        resp = await self.client.request(
            "POST", f"/api/investigations/{self.inv.id}/notes",
            json={"content": "New note"},
        )
        self.assertEqual(resp.status, 201)
        data = await resp.json()
        self.assertEqual(data["content"], "New note")
        self.assertIn("id", data)

    @unittest_run_loop
    async def test_add_note_missing_content(self):
        """POST /api/investigations/{id}/notes without content returns 400."""
        resp = await self.client.request(
            "POST", f"/api/investigations/{self.inv.id}/notes",
            json={},
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_update_note(self):
        """PUT /api/investigations/{id}/notes/{note_id} updates a note."""
        note = self.store.add_note(self.inv.id, "Original")
        resp = await self.client.request(
            "PUT", f"/api/investigations/{self.inv.id}/notes/{note.id}",
            json={"content": "Updated"},
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["content"], "Updated")

    @unittest_run_loop
    async def test_delete_note(self):
        """DELETE /api/investigations/{id}/notes/{note_id} deletes a note."""
        note = self.store.add_note(self.inv.id, "Delete me")
        resp = await self.client.request(
            "DELETE", f"/api/investigations/{self.inv.id}/notes/{note.id}",
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["result"], "deleted")


class TestAlertLinkingEndpoints(AioHTTPTestCase):
    """Tests for alert linking/unlinking endpoints."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = InvestigationStore(store_file=self.tmp.name)
        self.inv = self.store.create(title="Alert Link Test")
        super().setUp()

    def tearDown(self):
        super().tearDown()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    async def get_application(self):
        app = web.Application()
        register_investigation_routes(app, self.store)
        return app

    @unittest_run_loop
    async def test_link_alert(self):
        """POST /api/investigations/{id}/alerts links an alert."""
        resp = await self.client.request(
            "POST", f"/api/investigations/{self.inv.id}/alerts",
            json={"alert_id": "alert-123"},
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["result"], "linked")

    @unittest_run_loop
    async def test_link_alert_missing_id(self):
        """POST /api/investigations/{id}/alerts without alert_id returns 400."""
        resp = await self.client.request(
            "POST", f"/api/investigations/{self.inv.id}/alerts",
            json={},
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_unlink_alert(self):
        """DELETE /api/investigations/{id}/alerts/{alert_id} unlinks an alert."""
        self.store.link_alert(self.inv.id, "alert-456")
        resp = await self.client.request(
            "DELETE", f"/api/investigations/{self.inv.id}/alerts/alert-456",
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["result"], "unlinked")


class TestDeviceLinkingEndpoints(AioHTTPTestCase):
    """Tests for device linking endpoint."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = InvestigationStore(store_file=self.tmp.name)
        self.inv = self.store.create(title="Device Link Test")
        super().setUp()

    def tearDown(self):
        super().tearDown()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    async def get_application(self):
        app = web.Application()
        register_investigation_routes(app, self.store)
        return app

    @unittest_run_loop
    async def test_link_device(self):
        """POST /api/investigations/{id}/devices links a device."""
        resp = await self.client.request(
            "POST", f"/api/investigations/{self.inv.id}/devices",
            json={"device_ip": "192.168.1.100"},
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["result"], "linked")

    @unittest_run_loop
    async def test_link_device_missing_ip(self):
        """POST /api/investigations/{id}/devices without device_ip returns 400."""
        resp = await self.client.request(
            "POST", f"/api/investigations/{self.inv.id}/devices",
            json={},
        )
        self.assertEqual(resp.status, 400)


class TestStatsEndpoint(AioHTTPTestCase):
    """Tests for GET /api/investigations/stats."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = InvestigationStore(store_file=self.tmp.name)
        self.store.create(title="A", severity="high")
        self.store.create(title="B", severity="low")
        super().setUp()

    def tearDown(self):
        super().tearDown()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    async def get_application(self):
        app = web.Application()
        register_investigation_routes(app, self.store)
        return app

    @unittest_run_loop
    async def test_stats_returns_200(self):
        """GET /api/investigations/stats returns 200."""
        resp = await self.client.request("GET", "/api/investigations/stats")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_stats_has_expected_keys(self):
        """GET /api/investigations/stats returns expected structure."""
        resp = await self.client.request("GET", "/api/investigations/stats")
        data = await resp.json()
        self.assertIn("total", data)
        self.assertIn("by_status", data)
        self.assertIn("by_severity", data)
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["by_severity"]["high"], 1)
        self.assertEqual(data["by_severity"]["low"], 1)


class TestRouteRegistration(AioHTTPTestCase):
    """Tests for route registration."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = InvestigationStore(store_file=self.tmp.name)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    async def get_application(self):
        app = web.Application()
        register_investigation_routes(app, self.store)
        return app

    @unittest_run_loop
    async def test_store_on_app(self):
        """The InvestigationStore should be stored on the app dict."""
        self.assertIs(self.app["investigation_store"], self.store)

    @unittest_run_loop
    async def test_stats_not_captured_by_id_route(self):
        """The /stats route should not be captured by the /{id} route."""
        resp = await self.client.request("GET", "/api/investigations/stats")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("total", data)


if __name__ == "__main__":
    unittest.main()
