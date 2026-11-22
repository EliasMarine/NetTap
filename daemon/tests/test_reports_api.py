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

from unittest.mock import patch

from api.reports import register_report_routes
from services.report_generator import ReportGenerator

# NET-340: the sections module's output shape, so these route tests don't query anything
FAKE_SECTIONS = {
    name: {"status": "ok", "coverage": "7 of 7 days", "note": None}
    for name in ("traffic", "alerts", "new_devices", "offline", "data_cap")
}


def _create(generator: ReportGenerator, name: str):
    """A schedule made through the new create(), as the ReportSchedule the old tests used."""
    return generator.get_schedule(
        generator.create({"name": name, "frequency": "daily"})["id"]
    )


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
        # OLD CODE START — NET-340: create() takes validated fields; sections are fixed
        # self.generator.create_schedule(
        #     name="Test",
        #     frequency="daily",
        #     format="json",
        #     sections=["alerts"],
        # )
        # OLD CODE END
        _create(self.generator, "Test")
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
            # OLD CODE: "sections": ["alerts", "risk"], (NET-340: refused with a 400 now)
            json={
                "name": "Daily Alerts",
                "frequency": "daily",
                "format": "json",
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
        # OLD CODE START — NET-340: create() takes validated fields; sections are fixed
        # self.schedule = self.generator.create_schedule(
        #     name="Test",
        #     frequency="daily",
        #     format="json",
        #     sections=["alerts"],
        # )
        # OLD CODE END
        self.schedule = _create(self.generator, "Test")
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
        resp = await self.client.request("GET", "/api/reports/schedules/nonexistent-id")
        self.assertEqual(resp.status, 404)


class TestUpdateScheduleEndpoint(AioHTTPTestCase):
    """Tests for PUT /api/reports/schedules/{id}."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sfile = os.path.join(self.tmpdir, "schedules.json")
        self.generator = ReportGenerator(
            reports_dir=self.tmpdir, schedules_file=self.sfile
        )
        # OLD CODE START — NET-340: create() takes validated fields; sections are fixed
        # self.schedule = self.generator.create_schedule(
        #     name="Original",
        #     frequency="daily",
        #     format="json",
        #     sections=["alerts"],
        # )
        # OLD CODE END
        self.schedule = _create(self.generator, "Original")
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
        # OLD CODE START — NET-340: create() takes validated fields; sections are fixed
        # self.schedule = self.generator.create_schedule(
        #     name="To Delete",
        #     frequency="daily",
        #     format="json",
        #     sections=["alerts"],
        # )
        # OLD CODE END
        self.schedule = _create(self.generator, "To Delete")
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
        resp = await self.client.request("DELETE", "/api/reports/schedules/nonexistent")
        self.assertEqual(resp.status, 404)


class TestEnableDisableScheduleEndpoints(AioHTTPTestCase):
    """Tests for enable/disable endpoints."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sfile = os.path.join(self.tmpdir, "schedules.json")
        self.generator = ReportGenerator(
            reports_dir=self.tmpdir, schedules_file=self.sfile
        )
        # OLD CODE START — NET-340: create() takes validated fields; sections are fixed
        # self.schedule = self.generator.create_schedule(
        #     name="Test",
        #     frequency="daily",
        #     format="json",
        #     sections=["alerts"],
        # )
        # OLD CODE END
        self.schedule = _create(self.generator, "Test")
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
        # OLD CODE: self.generator.disable_schedule(self.schedule.id) (NET-340: set_enabled)
        self.generator.set_enabled(self.schedule.id, False)
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
        # OLD CODE START — NET-340: create() takes validated fields; sections are fixed
        # self.schedule = self.generator.create_schedule(
        #     name="Full Report",
        #     frequency="daily",
        #     format="json",
        #     sections=["traffic_summary", "alerts", "risk"],
        # )
        # OLD CODE END
        self.schedule = _create(self.generator, "Full Report")
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def get_application(self):
        app = web.Application()
        register_report_routes(app, self.generator)
        return app

    @unittest_run_loop
    @patch("services.report_sections.build_sections", lambda *_a: FAKE_SECTIONS)
    async def test_generate_report(self):
        """POST /api/reports/generate/{id} generates report."""
        resp = await self.client.request(
            "POST", f"/api/reports/generate/{self.schedule.id}"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("sections", data)
        # OLD CODE START — NET-340: the five real sections replaced the placeholders
        # self.assertIn("traffic_summary", data["sections"])
        # self.assertIn("alerts", data["sections"])
        # self.assertIn("risk", data["sections"])
        # OLD CODE END
        self.assertEqual(set(data["sections"]), set(FAKE_SECTIONS))
        self.assertEqual(data["delivery"]["result"], "not_emailed")

    @unittest_run_loop
    async def test_generate_nonexistent(self):
        """Generating report for unknown schedule returns 404."""
        resp = await self.client.request("POST", "/api/reports/generate/nonexistent")
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


# ---------------------------------------------------------------------------
# NET-340: validation, the card, history, the claim and the event loop (plan §3.7, §6)
# ---------------------------------------------------------------------------


class _ReportsApp(AioHTTPTestCase):
    """The report routes on a generator in a temp dir, plus a stand-in /api/health."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.generator = ReportGenerator(
            reports_dir=os.path.join(self.tmpdir, "reports"),
            schedules_file=os.path.join(self.tmpdir, "report_schedules.json"),
        )
        # OLD CODE: self.sid = self.generator.create({..., "confirm": True})["id"]
        # (security review: only the card's schedule can be confirmed)
        self.sid = self.generator.upsert_card(
            {"recipients": ["a@example.com"], "confirm": True}
        )[0]["id"]
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def get_application(self):
        app = web.Application()
        register_report_routes(app, self.generator)

        async def health(_request):
            return web.json_response({"status": "ok"})

        app.router.add_get("/api/health", health)
        return app

    def _stored(self) -> str:
        return open(os.path.join(self.tmpdir, "report_schedules.json")).read()


BAD_BODIES = [
    {"name": "W", "recipients": ["a@example.com\r\nBcc: x@example.com"]},
    {"name": "W", "recipients": ["a@example.com\n"]},
    {"name": "W", "recipients": ["a@example.com,b@example.com"]},
    {"name": "W", "recipients": [f"r{i}@example.com" for i in range(11)]},
    {"name": "W", "recipients": "a@example.com"},
    {"name": "W", "enabled": "true"},
    {"name": "W", "enabled": 1},
    {"name": "W", "confirm": "yes"},
    {"name": "W", "weekday": 7},
    {"name": "W", "hour": 24},
    {"name": "W", "hour": True},
    {"name": "W", "frequency": "hourly"},
    {"name": "x" * 101},
    {"name": "   "},
    ["not", "an", "object"],
    "a string",
    {"name": "W", "sections": ["traffic_summary"], "confirm": True},
]


class TestValidation(_ReportsApp):
    @unittest_run_loop
    async def test_each_bad_create_is_a_400_and_saves_nothing(self):
        before = self._stored()
        for body in BAD_BODIES:
            resp = await self.client.post("/api/reports/schedules", json=body)
            self.assertEqual(resp.status, 400, body)
            self.assertIn("error", await resp.json())
        self.assertEqual(self._stored(), before)

    @unittest_run_loop
    async def test_each_bad_update_is_a_400_and_changes_nothing(self):
        before = self._stored()
        for body in BAD_BODIES:
            resp = await self.client.put(
                f"/api/reports/schedules/{self.sid}", json=body
            )
            self.assertEqual(resp.status, 400, body)
        self.assertEqual(self._stored(), before)
        self.assertEqual(self.generator.view(self.sid)["rev"], 1)

    @unittest_run_loop
    async def test_sections_are_refused_with_the_five_named(self):
        view = self.generator.view(self.sid)
        resp = await self.client.put(
            f"/api/reports/schedules/{self.sid}",
            json={
                "sections": ["traffic_summary"],
                "confirm": True,
                "confirm_token": view["confirm_token"],
            },
        )
        self.assertEqual(resp.status, 400)
        self.assertIn("all five sections", (await resp.json())["error"])
        self.assertEqual(
            self.generator.get_schedule(self.sid).sections,
            ["traffic_summary", "alerts", "devices"],
        )

    @unittest_run_loop
    async def test_a_stale_confirm_is_a_409_and_changes_nothing(self):
        stale = self.generator.view(self.sid)
        self.generator.update(self.sid, {"name": "Elsewhere"})
        before = self._stored()
        resp = await self.client.put(
            f"/api/reports/schedules/{self.sid}",
            json={
                "recipients": ["b@example.com"],
                "confirm": True,
                "confirm_token": stale["confirm_token"],
            },
        )
        self.assertEqual(resp.status, 409)
        self.assertIn("another window", (await resp.json())["error"])
        self.assertEqual(self._stored(), before)

    @unittest_run_loop
    async def test_a_reply_carries_the_new_fields(self):
        resp = await self.client.get(f"/api/reports/schedules/{self.sid}")
        data = await resp.json()
        for key in (
            "rev",
            "confirm_token",
            "weekday",
            "hour",
            "tz",
            "next_send",
            "confirmed",
            "needs_review",
            "card",
            "sending",
            "last_period",
            "last_delivery",
        ):
            self.assertIn(key, data)
        self.assertTrue(data["confirmed"])


class TestScheduleList(_ReportsApp):
    @unittest_run_loop
    async def test_the_list_names_the_ledger_zone_even_with_no_schedules(self):
        self.generator.delete(self.sid)
        with patch.object(self.generator, "tz_name", return_value="Europe/London"):
            resp = await self.client.get("/api/reports/schedules")
        self.assertEqual(
            await resp.json(), {"schedules": [], "count": 0, "tz": "Europe/London"}
        )


class TestUnavailableStore(AioHTTPTestCase):
    """Review: an unreadable store's 503 keeps its reason past the error middleware."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        sfile = os.path.join(self.tmpdir, "report_schedules.json")
        with open(sfile, "w") as f:
            f.write("not json")
        self.generator = ReportGenerator(
            reports_dir=os.path.join(self.tmpdir, "reports"), schedules_file=sfile
        )
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def get_application(self):
        from api.error_replies import safe_error_middleware

        app = web.Application(middlewares=[safe_error_middleware])
        register_report_routes(app, self.generator)
        return app

    @unittest_run_loop
    async def test_the_503_says_why(self):
        from services.report_schedule import UNAVAILABLE

        for method, path, body in (
            ("GET", "/api/reports/schedules", None),
            ("POST", "/api/reports/schedules", {"name": "W"}),
            ("PUT", "/api/reports/card", {"confirm": True}),
        ):
            resp = await self.client.request(method, path, json=body)
            self.assertEqual(resp.status, 503, path)
            self.assertEqual((await resp.json())["error"], UNAVAILABLE)


class TestOnlyTheCardConfirms(_ReportsApp):
    """Security review: a confirmed API-only schedule emails like a hidden forwarding rule."""

    @unittest_run_loop
    async def test_a_confirming_create_is_a_400_and_saves_nothing(self):
        before = self._stored()
        resp = await self.client.post(
            "/api/reports/schedules",
            json={"name": "Hidden", "recipients": ["x@example.com"], "confirm": True},
        )
        self.assertEqual(resp.status, 400)
        self.assertIn("Settings › Notifications", (await resp.json())["error"])
        self.assertEqual(self._stored(), before)

    @unittest_run_loop
    async def test_a_confirming_put_on_another_schedule_is_a_400_and_changes_nothing(
        self,
    ):
        other = self.generator.create({"name": "Deploy check"})
        before = self._stored()
        resp = await self.client.put(
            f"/api/reports/schedules/{other['id']}",
            json={
                "recipients": ["x@example.com"],
                "confirm": True,
                "confirm_token": other["confirm_token"],
            },
        )
        self.assertEqual(resp.status, 400)
        self.assertEqual(self._stored(), before)
        self.assertEqual(self.generator.view(other["id"])["rev"], other["rev"])

    @unittest_run_loop
    async def test_other_schedules_still_save_and_generate_by_hand(self):
        resp = await self.client.post("/api/reports/schedules", json={"name": "Check"})
        self.assertEqual(resp.status, 201)
        sid = (await resp.json())["id"]
        resp = await self.client.put(
            f"/api/reports/schedules/{sid}", json={"name": "Check 2", "hour": 3}
        )
        self.assertEqual(resp.status, 200)


class TestCardRoute(_ReportsApp):
    @unittest_run_loop
    async def test_the_card_is_created_then_updated_with_its_token(self):
        self.generator.delete(self.sid)  # setUp's schedule is the card
        resp = await self.client.put(
            "/api/reports/card",
            json={"recipients": ["c@example.com"], "weekday": 4, "confirm": True},
        )
        self.assertEqual(resp.status, 201)  # made the card schedule
        card = await resp.json()
        self.assertTrue(card["card"] and card["confirmed"])
        self.assertNotEqual(card["id"], self.sid)
        resp = await self.client.put(
            "/api/reports/card",
            json={
                "hour": 7,
                "confirm": True,
                "confirm_token": card["confirm_token"],
                "rev": card["rev"],
            },
        )
        self.assertEqual(resp.status, 200)  # saved it
        self.assertEqual((await resp.json())["hour"], 7)


class TestHistoryRoutes(_ReportsApp):
    @unittest_run_loop
    @patch("services.report_sections.build_sections", lambda *_a: FAKE_SECTIONS)
    async def test_history_lists_and_reads_a_report(self):
        resp = await self.client.post(f"/api/reports/generate/{self.sid}")
        self.assertEqual(resp.status, 200)
        rid = (await resp.json())["id"]
        resp = await self.client.get(f"/api/reports/history?schedule={self.sid}")
        (summary,) = (await resp.json())["reports"]
        self.assertEqual(summary["id"], rid)
        self.assertEqual(summary["status"]["traffic"], "ok")
        self.assertNotIn("sections", summary)
        resp = await self.client.get("/api/reports/history")
        self.assertEqual(len((await resp.json())["reports"]), 1)
        resp = await self.client.get(f"/api/reports/history/{self.sid}/{rid}")
        self.assertEqual((await resp.json())["id"], rid)

    @unittest_run_loop
    async def test_traversal_and_bad_ids_are_404(self):
        for path in (
            f"/api/reports/history/{self.sid}/..%2F..%2Freport_schedules",
            f"/api/reports/history/{self.sid}/20261116T080500Z-zzzzzz",
            "/api/reports/history/not-a-uuid/20261116T080500Z-abcdef",
            f"/api/reports/history/{self.sid}/20261116T080500Z-abcdef",
            "/api/reports/history?schedule=..",
        ):
            resp = await self.client.get(path)
            self.assertEqual(resp.status, 404, path)

    @unittest_run_loop
    async def test_generate_now_is_an_immediate_409_while_busy(self):
        self.generator._gen_lock.acquire()
        try:
            resp = await self.client.post(f"/api/reports/generate/{self.sid}")
            self.assertEqual(resp.status, 409)
            self.assertIn("being generated", (await resp.json())["error"])
        finally:
            self.generator._gen_lock.release()


class TestEventLoop(_ReportsApp):
    @unittest_run_loop
    async def test_health_answers_while_a_settings_write_is_paused(self):
        import asyncio
        import threading

        from services import report_schedule

        gate, entered = threading.Event(), threading.Event()
        real = report_schedule._replace_file  # the settings write in _commit

        def paused(path, data):
            entered.set()
            gate.wait(5)
            return real(path, data)

        with patch("services.report_generator._replace_file", paused):
            put = asyncio.ensure_future(
                self.client.put(
                    f"/api/reports/schedules/{self.sid}", json={"name": "Slow"}
                )
            )
            await asyncio.get_running_loop().run_in_executor(None, entered.wait, 5)
            self.assertFalse(put.done())
            resp = await asyncio.wait_for(self.client.get("/api/health"), 2)
            self.assertEqual(resp.status, 200)
            gate.set()
            self.assertEqual((await put).status, 200)


if __name__ == "__main__":
    unittest.main()
