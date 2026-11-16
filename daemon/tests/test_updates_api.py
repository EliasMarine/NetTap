"""
Tests for daemon/api/updates.py

All tests use mocked VersionManager, UpdateChecker, and UpdateExecutor --
no real Docker, HTTP, or filesystem access required. Tests cover all
software update system API endpoints using AioHTTPTestCase.
"""

import os
import sys
import unittest
from unittest.mock import AsyncMock

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.updates import register_update_routes
from services.version_manager import VersionManager
from services.update_checker import UpdateChecker
from services.update_executor import UpdateExecutor


def _make_mock_version_manager():
    """Create a mock VersionManager with async method stubs."""
    vm = VersionManager.__new__(VersionManager)
    vm._versions = {}
    vm._last_scan = None
    vm._scanning = False
    # OLD CODE: vm._compose_file = "/opt/nettap/docker/docker-compose.yml" (NET-288: VersionManager has no compose path)
    return vm


def _make_mock_update_checker():
    """Create a mock UpdateChecker with async method stubs."""
    uc = UpdateChecker.__new__(UpdateChecker)
    uc._available_updates = []
    uc._last_check = None
    # OLD CODE: uc._checking = False (the flag is gone)
    uc._check_task = None
    uc._last_result = None
    uc._github_repo = "EliasMarine/NetTap"
    uc._cache_ttl = 6 * 3600
    uc._version_manager = None
    return uc


def _make_mock_update_executor():
    """Create a mock UpdateExecutor with async method stubs."""
    ue = UpdateExecutor.__new__(UpdateExecutor)
    ue._current_update = None
    ue._update_history = []
    ue._max_history = 50
    # OLD CODE: ue._compose_file = "/opt/nettap/docker/docker-compose.yml" (NET-288: UpdateExecutor has no compose path)
    ue._backup_dir = "/opt/nettap/backups"
    ue._version_manager = None
    ue._update_checker = None
    return ue


def _make_versions_result():
    """Build a mock versions result dict."""
    return {
        "versions": [
            {
                "name": "nettap-daemon",
                "category": "core",
                "current_version": "0.4.0",
                "install_type": "pip",
                "last_checked": "2026-02-26T12:00:00+00:00",
                "status": "ok",
                "details": {},
            },
            {
                "name": "zeek",
                "category": "docker",
                "current_version": "v26.02.0",
                "install_type": "docker",
                "last_checked": "2026-02-26T12:00:00+00:00",
                "status": "ok",
                "details": {},
            },
        ],
        "last_scan": "2026-02-26T12:00:00+00:00",
        "count": 2,
    }


def _make_updates_result():
    """Build a mock available updates result dict."""
    return {
        "updates": [
            {
                "component": "zeek",
                "current_version": "v26.02.0",
                "latest_version": "v26.03.0",
                "update_type": "minor",
                "release_url": "https://example.com",
                "release_date": "2026-02-26T00:00:00+00:00",
                "changelog": "New features",
                "size_mb": 150.0,
                "requires_restart": True,
            }
        ],
        "last_check": "2026-02-26T12:00:00+00:00",
        "count": 1,
        "has_updates": True,
    }


def _make_apply_result():
    """Build a mock update apply result dict."""
    return {
        "results": [
            {
                "component": "zeek",
                "success": True,
                "old_version": "v26.02.0",
                "new_version": "v26.03.0",
                "started_at": "2026-02-26T12:00:00+00:00",
                "completed_at": "2026-02-26T12:05:00+00:00",
                "error": None,
                "rollback_available": True,
            }
        ],
        "success": True,
        "total": 1,
        "succeeded": 1,
        "failed": 0,
    }


# ---------------------------------------------------------------------------
# Version inventory endpoint tests (4C.8)
# ---------------------------------------------------------------------------


class TestGetVersionsEndpoint(AioHTTPTestCase):
    """Tests for GET /api/system/versions."""

    def setUp(self):
        self.mock_vm = _make_mock_version_manager()
        self.mock_uc = _make_mock_update_checker()
        self.mock_ue = _make_mock_update_executor()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_update_routes(app, self.mock_vm, self.mock_uc, self.mock_ue)
        return app

    @unittest_run_loop
    async def test_get_versions_returns_200(self):
        """GET /api/system/versions should return 200."""
        self.mock_vm.get_versions = AsyncMock(return_value=_make_versions_result())
        resp = await self.client.request("GET", "/api/system/versions")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_get_versions_returns_correct_structure(self):
        """Response should contain expected keys."""
        self.mock_vm.get_versions = AsyncMock(return_value=_make_versions_result())
        resp = await self.client.request("GET", "/api/system/versions")
        data = await resp.json()
        self.assertIn("versions", data)
        self.assertIn("last_scan", data)
        self.assertIn("count", data)

    @unittest_run_loop
    async def test_get_versions_error_returns_500(self):
        """Internal error should return 500."""
        self.mock_vm.get_versions = AsyncMock(side_effect=RuntimeError("test error"))
        resp = await self.client.request("GET", "/api/system/versions")
        self.assertEqual(resp.status, 500)
        data = await resp.json()
        self.assertIn("error", data)


class TestGetVersionComponentEndpoint(AioHTTPTestCase):
    """Tests for GET /api/system/versions/{name}."""

    def setUp(self):
        self.mock_vm = _make_mock_version_manager()
        self.mock_uc = _make_mock_update_checker()
        self.mock_ue = _make_mock_update_executor()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_update_routes(app, self.mock_vm, self.mock_uc, self.mock_ue)
        return app

    @unittest_run_loop
    async def test_get_component_returns_200(self):
        """Known component should return 200."""
        self.mock_vm.get_component = AsyncMock(
            return_value={
                "name": "zeek",
                "category": "docker",
                "current_version": "v26.02.0",
                "install_type": "docker",
                "last_checked": "2026-02-26T12:00:00+00:00",
                "status": "ok",
                "details": {},
            }
        )
        resp = await self.client.request("GET", "/api/system/versions/zeek")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_get_component_returns_404_for_unknown(self):
        """Unknown component should return 404."""
        self.mock_vm.get_component = AsyncMock(return_value=None)
        resp = await self.client.request("GET", "/api/system/versions/nonexistent")
        self.assertEqual(resp.status, 404)


class TestComponentRowsThePageCanAskFor(AioHTTPTestCase):
    """NET-288: the real VersionManager and handler. nettap-config read the compose file, which
    isn't in the daemon container, so it was an "unknown" row; it is gone, and nettap-web
    answers with the Docker row."""

    async def get_application(self):
        vm = VersionManager()

        async def docker_ps(cmd):
            return "nettap-web\tnettap/web:latest\tf\n"

        async def none():
            return []

        vm._run_command = docker_ps
        vm._scan_system_packages = none
        vm._scan_databases = none
        vm._scan_os_info = none
        app = web.Application()
        register_update_routes(
            app, vm, _make_mock_update_checker(), _make_mock_update_executor()
        )
        return app

    @unittest_run_loop
    async def test_component_nettap_config_is_404(self):
        resp = await self.client.request("GET", "/api/system/versions/nettap-config")
        self.assertEqual(resp.status, 404)

    @unittest_run_loop
    async def test_component_nettap_web_comes_from_the_docker_row(self):
        resp = await self.client.request("GET", "/api/system/versions/nettap-web")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        # OLD CODE: ("docker", "latest") (a nettap/*:latest image now reads "built locally")
        self.assertEqual(
            (data["category"], data["current_version"]), ("docker", "built locally")
        )


class TestScanVersionsEndpoint(AioHTTPTestCase):
    """Tests for POST /api/system/versions/scan."""

    def setUp(self):
        self.mock_vm = _make_mock_version_manager()
        self.mock_uc = _make_mock_update_checker()
        self.mock_ue = _make_mock_update_executor()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_update_routes(app, self.mock_vm, self.mock_uc, self.mock_ue)
        return app

    @unittest_run_loop
    async def test_scan_versions_returns_200(self):
        """POST /api/system/versions/scan should return 200."""
        self.mock_vm.scan_versions = AsyncMock(return_value=_make_versions_result())
        resp = await self.client.request("POST", "/api/system/versions/scan")
        self.assertEqual(resp.status, 200)


# ---------------------------------------------------------------------------
# Update checker endpoint tests (4C.9)
# ---------------------------------------------------------------------------


class TestGetAvailableUpdatesEndpoint(AioHTTPTestCase):
    """Tests for GET /api/system/updates/available."""

    def setUp(self):
        self.mock_vm = _make_mock_version_manager()
        self.mock_uc = _make_mock_update_checker()
        self.mock_ue = _make_mock_update_executor()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_update_routes(app, self.mock_vm, self.mock_uc, self.mock_ue)
        return app

    @unittest_run_loop
    async def test_get_available_returns_200(self):
        """GET /api/system/updates/available should return 200."""
        self.mock_uc.get_available = AsyncMock(return_value=_make_updates_result())
        resp = await self.client.request("GET", "/api/system/updates/available")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_get_available_returns_updates_list(self):
        """Response should contain updates list."""
        self.mock_uc.get_available = AsyncMock(return_value=_make_updates_result())
        resp = await self.client.request("GET", "/api/system/updates/available")
        data = await resp.json()
        self.assertIn("updates", data)
        self.assertIn("has_updates", data)
        self.assertIsInstance(data["updates"], list)


class TestCheckUpdatesEndpoint(AioHTTPTestCase):
    """Tests for POST /api/system/updates/check."""

    def setUp(self):
        self.mock_vm = _make_mock_version_manager()
        self.mock_uc = _make_mock_update_checker()
        self.mock_ue = _make_mock_update_executor()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_update_routes(app, self.mock_vm, self.mock_uc, self.mock_ue)
        return app

    @unittest_run_loop
    async def test_check_updates_returns_200(self):
        """POST /api/system/updates/check should return 200."""
        self.mock_uc.check_updates = AsyncMock(return_value=_make_updates_result())
        resp = await self.client.request("POST", "/api/system/updates/check")
        self.assertEqual(resp.status, 200)


class TestGetUpdateForComponentEndpoint(AioHTTPTestCase):
    """Tests for GET /api/system/updates/available/{component}."""

    def setUp(self):
        self.mock_vm = _make_mock_version_manager()
        self.mock_uc = _make_mock_update_checker()
        self.mock_ue = _make_mock_update_executor()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_update_routes(app, self.mock_vm, self.mock_uc, self.mock_ue)
        return app

    @unittest_run_loop
    async def test_get_update_for_known_returns_200(self):
        """Known component with update should return 200."""
        self.mock_uc.get_update_for = AsyncMock(
            return_value={
                "component": "zeek",
                "current_version": "v26.02.0",
                "latest_version": "v26.03.0",
                "update_type": "minor",
            }
        )
        resp = await self.client.request("GET", "/api/system/updates/available/zeek")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_get_update_for_unknown_returns_404(self):
        """Component with no update should return 404."""
        self.mock_uc.get_update_for = AsyncMock(return_value=None)
        resp = await self.client.request(
            "GET", "/api/system/updates/available/nonexistent"
        )
        self.assertEqual(resp.status, 404)


# ---------------------------------------------------------------------------
# Update executor endpoint tests (4C.10)
# ---------------------------------------------------------------------------


class TestApplyUpdatesEndpoint(AioHTTPTestCase):
    """Tests for POST /api/system/updates/apply."""

    def setUp(self):
        self.mock_vm = _make_mock_version_manager()
        self.mock_uc = _make_mock_update_checker()
        self.mock_ue = _make_mock_update_executor()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_update_routes(app, self.mock_vm, self.mock_uc, self.mock_ue)
        return app

    # OLD CODE START — apply ran the whole batch in the request (cut off by the 10 s web proxy)
    # @unittest_run_loop
    # async def test_apply_updates_returns_200(self):
    #     """POST /api/system/updates/apply should return 200."""
    #     self.mock_ue.apply_update = AsyncMock(return_value=_make_apply_result())
    #     resp = await self.client.request(
    #         "POST",
    #         "/api/system/updates/apply",
    #         json={"components": ["zeek"]},
    #     )
    #     self.assertEqual(resp.status, 200)
    # OLD CODE END

    @unittest_run_loop
    async def test_apply_starts_in_the_background_and_answers_202(self):
        self.mock_ue.start_update = AsyncMock(
            return_value=({"state": "in_progress", "components": ["malcolm"]}, 202)
        )
        resp = await self.client.request(
            "POST", "/api/system/updates/apply", json={"components": ["malcolm"]}
        )
        self.assertEqual(resp.status, 202)
        self.assertEqual((await resp.json())["state"], "in_progress")
        self.mock_ue.start_update.assert_awaited_once_with(["malcolm"])

    @unittest_run_loop
    async def test_apply_while_one_runs_answers_409(self):
        self.mock_ue.start_update = AsyncMock(
            return_value=(
                {"error": "An update is already running", "state": "in_progress"},
                409,
            )
        )
        resp = await self.client.request(
            "POST", "/api/system/updates/apply", json={"components": ["malcolm"]}
        )
        self.assertEqual(resp.status, 409)

    @unittest_run_loop
    async def test_apply_with_a_non_string_component_is_400(self):
        self.mock_ue.start_update = AsyncMock(return_value=({}, 202))
        resp = await self.client.request(
            "POST", "/api/system/updates/apply", json={"components": [{"x": 1}]}
        )
        self.assertEqual(resp.status, 400)
        self.mock_ue.start_update.assert_not_awaited()

    @unittest_run_loop
    async def test_apply_updates_invalid_body_returns_400(self):
        """Invalid JSON body should return 400."""
        resp = await self.client.request(
            "POST",
            "/api/system/updates/apply",
            data="not json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_apply_updates_missing_components_returns_400(self):
        """Missing 'components' field should return 400."""
        resp = await self.client.request(
            "POST",
            "/api/system/updates/apply",
            json={"not_components": []},
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_apply_updates_wrong_type_returns_400(self):
        """Non-list 'components' field should return 400."""
        resp = await self.client.request(
            "POST",
            "/api/system/updates/apply",
            json={"components": "zeek"},
        )
        self.assertEqual(resp.status, 400)


class TestGetUpdateStatusEndpoint(AioHTTPTestCase):
    """Tests for GET /api/system/updates/status."""

    def setUp(self):
        self.mock_vm = _make_mock_version_manager()
        self.mock_uc = _make_mock_update_checker()
        self.mock_ue = _make_mock_update_executor()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_update_routes(app, self.mock_vm, self.mock_uc, self.mock_ue)
        return app

    @unittest_run_loop
    async def test_get_status_returns_200(self):
        """GET /api/system/updates/status should return 200."""
        self.mock_ue.get_status = AsyncMock(
            return_value={
                "status": "idle",
                "current_update": None,
                "last_completed": None,
            }
        )
        resp = await self.client.request("GET", "/api/system/updates/status")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_get_status_returns_correct_structure(self):
        """Response should contain status key."""
        self.mock_ue.get_status = AsyncMock(
            return_value={
                "status": "idle",
                "current_update": None,
                "last_completed": None,
            }
        )
        resp = await self.client.request("GET", "/api/system/updates/status")
        data = await resp.json()
        self.assertIn("status", data)


class TestGetUpdateHistoryEndpoint(AioHTTPTestCase):
    """Tests for GET /api/system/updates/history."""

    def setUp(self):
        self.mock_vm = _make_mock_version_manager()
        self.mock_uc = _make_mock_update_checker()
        self.mock_ue = _make_mock_update_executor()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_update_routes(app, self.mock_vm, self.mock_uc, self.mock_ue)
        return app

    @unittest_run_loop
    async def test_get_history_returns_200(self):
        """GET /api/system/updates/history should return 200."""
        self.mock_ue.get_history = AsyncMock(return_value=[])
        resp = await self.client.request("GET", "/api/system/updates/history")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_get_history_returns_list(self):
        """Response should contain history list."""
        self.mock_ue.get_history = AsyncMock(return_value=[])
        resp = await self.client.request("GET", "/api/system/updates/history")
        data = await resp.json()
        self.assertIn("history", data)
        self.assertIn("count", data)
        self.assertIsInstance(data["history"], list)


class TestRollbackEndpoint(AioHTTPTestCase):
    """Tests for POST /api/system/updates/rollback."""

    def setUp(self):
        self.mock_vm = _make_mock_version_manager()
        self.mock_uc = _make_mock_update_checker()
        self.mock_ue = _make_mock_update_executor()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_update_routes(app, self.mock_vm, self.mock_uc, self.mock_ue)
        return app

    @unittest_run_loop
    async def test_rollback_success_returns_200(self):
        """Successful rollback should return 200."""
        self.mock_ue.rollback = AsyncMock(
            return_value={
                "success": True,
                "component": "zeek",
                "message": "Rolled back successfully",
            }
        )
        resp = await self.client.request(
            "POST",
            "/api/system/updates/rollback",
            json={"component": "zeek"},
        )
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_rollback_failure_returns_404(self):
        """Failed rollback (no backup) should return 404."""
        self.mock_ue.rollback = AsyncMock(
            return_value={
                "success": False,
                "component": "zeek",
                "message": "No backup available",
            }
        )
        resp = await self.client.request(
            "POST",
            "/api/system/updates/rollback",
            json={"component": "zeek"},
        )
        self.assertEqual(resp.status, 404)

    @unittest_run_loop
    async def test_rollback_invalid_body_returns_400(self):
        """Invalid JSON body should return 400."""
        resp = await self.client.request(
            "POST",
            "/api/system/updates/rollback",
            data="not json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_rollback_missing_component_returns_400(self):
        """Missing 'component' field should return 400."""
        resp = await self.client.request(
            "POST",
            "/api/system/updates/rollback",
            json={"not_component": "zeek"},
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_rollback_empty_component_returns_400(self):
        """Empty 'component' string should return 400."""
        resp = await self.client.request(
            "POST",
            "/api/system/updates/rollback",
            json={"component": ""},
        )
        self.assertEqual(resp.status, 400)


class _RealExecutorCase(AioHTTPTestCase):
    """The real UpdateExecutor behind the real handlers (NET-291), with its history seeded so a
    batch that slipped through shows. start_update and rollback are spied, not replaced."""

    SENTINEL = {"sentinel": "history before the request"}

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.ue = UpdateExecutor(backup_dir=self._tmp.name)
        self.ue._update_history = [dict(self.SENTINEL)]
        self.ue.start_update = AsyncMock(wraps=self.ue.start_update)
        self.ue.rollback = AsyncMock(wraps=self.ue.rollback)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self._tmp.cleanup()

    async def get_application(self):
        app = web.Application()
        register_update_routes(
            app,
            _make_mock_version_manager(),
            _make_mock_update_checker(),
            self.ue,
        )
        return app

    async def _settle(self):
        if self.ue._task is not None:  # a batch that was queued runs to its end
            await self.ue._task

    async def assert_nothing_queued_or_recorded(self):
        await self._settle()
        self.ue.start_update.assert_not_called()
        self.assertEqual(self.ue._update_history, [self.SENTINEL])
        self.assertEqual(self.ue._live_results, [])
        self.assertIsNone(self.ue._current_update)


class TestApplyChecksNamesBeforeQueuing(_RealExecutorCase):
    """NET-291: any list of strings was turned into a result each and kept in the history."""

    async def _refuses(self, body):
        resp = await self.client.request("POST", "/api/system/updates/apply", json=body)
        self.assertEqual(
            resp.status, 400, body if len(str(body)) < 200 else "a big body"
        )
        await self.assert_nothing_queued_or_recorded()

    @unittest_run_loop
    async def test_a_list_over_the_cap_is_refused_even_of_allowed_names(self):
        from services.update_executor import MAX_APPLY_COMPONENTS

        self.assertEqual(MAX_APPLY_COMPONENTS, 16)
        await self._refuses({"components": ["zeek"] * 17})

    @unittest_run_loop
    async def test_a_list_at_the_cap_is_queued(self):
        self.ue.start_update = AsyncMock(return_value=({"state": "in_progress"}, 202))
        resp = await self.client.request(
            "POST", "/api/system/updates/apply", json={"components": ["zeek"] * 16}
        )
        self.assertEqual(resp.status, 202)
        self.ue.start_update.assert_awaited_once()

    @unittest_run_loop
    async def test_a_repeated_name_is_queued_once(self):
        """Two results with one component broke the Updates page's keyed lists."""
        self.ue.start_update = AsyncMock(return_value=({"state": "in_progress"}, 202))
        resp = await self.client.request(
            "POST",
            "/api/system/updates/apply",
            json={"components": ["zeek", "suricata-rules", "zeek"]},
        )
        self.assertEqual(resp.status, 202)
        self.ue.start_update.assert_awaited_once_with(["zeek", "suricata-rules"])

    @unittest_run_loop
    async def test_unknown_names_are_refused(self):
        for components in (
            ["../../etc/passwd"],
            ["nettap-nothing"],
            ["x" * 100_000],  # a long one is refused, not stored
            ["suricata-rules", "../x"],  # one bad name refuses the batch
        ):
            await self._refuses({"components": components})

    @unittest_run_loop
    async def test_a_body_that_is_not_an_object_is_a_400_not_a_500(self):
        for body in (None, [], 5, "malcolm"):
            await self._refuses(body)

    @unittest_run_loop
    async def test_the_page_names_and_the_malcolm_rows_are_queued(self):
        self.ue.start_update = AsyncMock(return_value=({"state": "in_progress"}, 202))
        for components in (
            ["malcolm", "suricata-rules", "geoip-db"],
            ["zeek", "suricata", "nettap-logstash", "nettap-zeek-live"],
        ):
            resp = await self.client.request(
                "POST", "/api/system/updates/apply", json={"components": components}
            )
            self.assertEqual(resp.status, 202, components)
            self.assertEqual(self.ue.start_update.await_args.args[0], components)


class TestRollbackChecksTheBody(_RealExecutorCase):
    """NET-291: a body that is not an object reached body.get and became a logged 500; a name
    that is not a string never reaches rollback()."""

    async def _refuses(self, body):
        resp = await self.client.request(
            "POST", "/api/system/updates/rollback", json=body
        )
        self.assertEqual(resp.status, 400, body)
        self.ue.rollback.assert_not_called()

    @unittest_run_loop
    async def test_a_body_that_is_not_an_object_is_a_400_not_a_500(self):
        for body in (None, [], 5, "suricata-rules"):
            await self._refuses(body)

    @unittest_run_loop
    async def test_a_component_that_is_not_a_string_is_a_400(self):
        for component in (["suricata-rules"], 5, {"a": 1}, None, ""):
            await self._refuses({"component": component})

    @unittest_run_loop
    async def test_a_traversal_name_is_refused_as_not_supported(self):
        resp = await self.client.request(
            "POST", "/api/system/updates/rollback", json={"component": "../../../etc/x"}
        )
        self.assertEqual(resp.status, 404)
        self.assertIn("not supported", (await resp.json())["message"])


class TestRouteRegistration(AioHTTPTestCase):
    """Tests for route registration."""

    def setUp(self):
        self.mock_vm = _make_mock_version_manager()
        self.mock_uc = _make_mock_update_checker()
        self.mock_ue = _make_mock_update_executor()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_update_routes(app, self.mock_vm, self.mock_uc, self.mock_ue)
        return app

    @unittest_run_loop
    async def test_services_stored_on_app(self):
        """Services should be stored on the app dict."""
        self.assertIs(self.app["version_manager"], self.mock_vm)
        self.assertIs(self.app["update_checker"], self.mock_uc)
        self.assertIs(self.app["update_executor"], self.mock_ue)

    @unittest_run_loop
    async def test_all_routes_registered(self):
        """All 10 update routes should be registered (not 404)."""
        # Set up mocks for all endpoints
        self.mock_vm.get_versions = AsyncMock(return_value=_make_versions_result())
        self.mock_vm.get_component = AsyncMock(
            return_value={
                "name": "zeek",
                "category": "docker",
                "current_version": "v26",
                "install_type": "docker",
                "last_checked": "ts",
                "status": "ok",
                "details": {},
            }
        )
        self.mock_vm.scan_versions = AsyncMock(return_value=_make_versions_result())
        self.mock_uc.get_available = AsyncMock(return_value=_make_updates_result())
        self.mock_uc.check_updates = AsyncMock(return_value=_make_updates_result())
        self.mock_uc.get_update_for = AsyncMock(
            return_value={
                "component": "zeek",
                "current_version": "v26",
                "latest_version": "v27",
                "update_type": "major",
            }
        )
        self.mock_ue.apply_update = AsyncMock(return_value=_make_apply_result())
        self.mock_ue.start_update = AsyncMock(
            return_value=({"state": "in_progress"}, 202)
        )
        self.mock_ue.get_status = AsyncMock(
            return_value={
                "status": "idle",
                "current_update": None,
                "last_completed": None,
            }
        )
        self.mock_ue.get_history = AsyncMock(return_value=[])
        self.mock_ue.rollback = AsyncMock(
            return_value={
                "success": True,
                "component": "zeek",
                "message": "Rolled back",
            }
        )

        routes_to_check = [
            ("GET", "/api/system/versions"),
            ("GET", "/api/system/versions/zeek"),
            ("POST", "/api/system/versions/scan"),
            ("GET", "/api/system/updates/available"),
            ("POST", "/api/system/updates/check"),
            ("GET", "/api/system/updates/available/zeek"),
            ("GET", "/api/system/updates/status"),
            ("GET", "/api/system/updates/history"),
        ]

        for method, path in routes_to_check:
            resp = await self.client.request(method, path)
            self.assertNotEqual(
                resp.status,
                404,
                f"Route {method} {path} returned 404 -- not registered",
            )

        # POST routes with body
        resp = await self.client.request(
            "POST",
            "/api/system/updates/apply",
            json={"components": ["zeek"]},
        )
        self.assertNotEqual(resp.status, 404)

        resp = await self.client.request(
            "POST",
            "/api/system/updates/rollback",
            json={"component": "zeek"},
        )
        self.assertNotEqual(resp.status, 404)


if __name__ == "__main__":
    unittest.main()
