"""
Tests for POST /api/storage/config endpoint in daemon/api/server.py

Covers valid config save, validation errors, missing config manager (503),
ILM success and failure retry scheduling. Uses AioHTTPTestCase with mocked
OpenSearch — no real connections required.
"""

import asyncio
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from storage.manager import StorageManager, RetentionConfig
from storage.retention_config import RetentionConfigManager


def _make_mock_storage():
    """Create a mock StorageManager with a mock OpenSearch client."""
    config = RetentionConfig()
    with patch.object(StorageManager, "_create_client") as mock_create:
        mock_client = MagicMock()
        mock_create.return_value = mock_client
        storage = StorageManager(config, "http://localhost:9200")
    return storage, mock_client


def _make_app_with_config_route(tmp_path_str, *, include_config_manager=True):
    """Build a minimal aiohttp app with just the /api/storage/config route.

    Avoids importing the full create_app() which pulls in dozens of services.
    """
    # Import the handler directly
    from api.server import IlmSyncState, handle_storage_config

    app = web.Application()

    storage, _ = _make_mock_storage()
    app["storage"] = storage
    app["opensearch_url"] = "http://localhost:9200"
    app["http_auth"] = None
    app["ilm_sync"] = IlmSyncState()

    if include_config_manager:
        config_path = os.path.join(tmp_path_str, "retention.json")
        env_file = os.path.join(tmp_path_str, ".env")
        mgr = RetentionConfigManager(config_path=config_path, env_file=env_file)
        mgr.load()
        app["retention_config_manager"] = mgr

    app.router.add_post("/api/storage/config", handle_storage_config)
    return app


class TestPostValidConfig(AioHTTPTestCase):
    """POST valid config returns 200 with saved=true."""

    def setUp(self):
        import tempfile

        self._tmp_dir = tempfile.mkdtemp()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        import shutil

        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    async def get_application(self):
        return _make_app_with_config_route(self._tmp_dir)

    async def test_post_valid_config(self):
        """POST valid retention config returns 200 and saved=true."""
        with patch(
            "api.server.apply_ilm_policies_from_config",
            return_value={
                "nettap-hot-policy": "created",
                "nettap-warm-policy": "created",
                "nettap-cold-policy": "created",
            },
        ):
            resp = await self.client.request(
                "POST",
                "/api/storage/config",
                json={
                    "hot_days": 60,
                    "warm_days": 120,
                    "cold_days": 14,
                    "disk_threshold_percent": 75,
                    "emergency_threshold_percent": 85,
                },
            )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["saved"])
        self.assertEqual(data["config"]["hot_days"], 60)
        self.assertEqual(data["config"]["warm_days"], 120)
        self.assertEqual(data["config"]["cold_days"], 14)


class TestPostInvalidConfig(AioHTTPTestCase):
    """POST invalid values returns 400 with error message."""

    def setUp(self):
        import tempfile

        self._tmp_dir = tempfile.mkdtemp()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        import shutil

        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    async def get_application(self):
        return _make_app_with_config_route(self._tmp_dir)

    async def test_post_invalid_config_400(self):
        """POST with hot_days=0 returns 400 with validation error."""
        resp = await self.client.request(
            "POST",
            "/api/storage/config",
            json={"hot_days": 0},
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("error", data)
        self.assertIn("hot_days", data["error"])


class TestPostUpdatesStorageManager(AioHTTPTestCase):
    """After POST, verify storage.config has the new values."""

    def setUp(self):
        import tempfile

        self._tmp_dir = tempfile.mkdtemp()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        import shutil

        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    async def get_application(self):
        return _make_app_with_config_route(self._tmp_dir)

    async def test_post_updates_storage_manager(self):
        """After a valid POST, storage.config reflects the new values."""
        with patch(
            "api.server.apply_ilm_policies_from_config",
            return_value={
                "nettap-hot-policy": "created",
                "nettap-warm-policy": "created",
                "nettap-cold-policy": "created",
            },
        ):
            resp = await self.client.request(
                "POST",
                "/api/storage/config",
                json={"hot_days": 45, "warm_days": 100, "cold_days": 7},
            )
        self.assertEqual(resp.status, 200)

        storage = self.app["storage"]
        self.assertEqual(storage.config.hot_days, 45)
        self.assertEqual(storage.config.warm_days, 100)
        self.assertEqual(storage.config.cold_days, 7)


class TestPostMissingConfigManager(AioHTTPTestCase):
    """Request without config manager returns 503."""

    def setUp(self):
        import tempfile

        self._tmp_dir = tempfile.mkdtemp()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        import shutil

        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    async def get_application(self):
        return _make_app_with_config_route(self._tmp_dir, include_config_manager=False)

    async def test_post_missing_config_manager_503(self):
        """Without retention_config_manager on the app, returns 503."""
        resp = await self.client.request(
            "POST",
            "/api/storage/config",
            json={"hot_days": 60},
        )
        self.assertEqual(resp.status, 503)
        data = await resp.json()
        self.assertIn("error", data)


class TestPostIlmSuccess(AioHTTPTestCase):
    """Mock OpenSearch success — verify ilm_applied=true in response."""

    def setUp(self):
        import tempfile

        self._tmp_dir = tempfile.mkdtemp()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        import shutil

        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    async def get_application(self):
        return _make_app_with_config_route(self._tmp_dir)

    async def test_post_ilm_success(self):
        """When ILM application succeeds, response has ilm_applied=true."""
        with patch(
            "api.server.apply_ilm_policies_from_config",
            return_value={
                "nettap-hot-policy": "created",
                "nettap-warm-policy": "updated",
                "nettap-cold-policy": "unchanged",
            },
        ):
            resp = await self.client.request(
                "POST",
                "/api/storage/config",
                json={"hot_days": 60},
            )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["ilm_applied"])
        self.assertIn("ilm_results", data)
        self.assertEqual(data["ilm_results"]["nettap-hot-policy"], "created")


class TestPostIlmFailure(AioHTTPTestCase):
    """Mock OpenSearch failure — verify retry scheduled."""

    def setUp(self):
        import tempfile

        self._tmp_dir = tempfile.mkdtemp()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        import shutil

        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    async def get_application(self):
        return _make_app_with_config_route(self._tmp_dir)

    async def test_post_ilm_failure_schedules_retry(self):
        """When ILM fails, config is still saved, retry is scheduled."""
        with patch(
            "api.server.apply_ilm_policies_from_config",
            side_effect=ConnectionError("OpenSearch unreachable"),
        ):
            resp = await self.client.request(
                "POST",
                "/api/storage/config",
                json={"hot_days": 60},
            )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["saved"])
        self.assertFalse(data["ilm_applied"])
        self.assertTrue(data["ilm_retry_scheduled"])
        self.assertIn("ilm_error", data)


# ---------------------------------------------------------------------------
# Revision-aware ILM application (saves and retries share one worker)
# ---------------------------------------------------------------------------

OK_RESULTS = {
    "nettap-hot-policy": "updated",
    "nettap-warm-policy": "unchanged",
    "nettap-cold-policy": "unchanged",
}
ERROR_RESULTS = {
    "nettap-hot-policy": "error: ConnectionError(Connection refused)",
    "nettap-warm-policy": "error: ConnectionError(Connection refused)",
    "nettap-cold-policy": "error: ConnectionError(Connection refused)",
}
SAVE_A = {"hot_days": 30}
SAVE_B = {"hot_days": 120}


def _policies_for(hot_days: int, mgr: RetentionConfigManager) -> dict:
    from storage.ilm_generator import generate_ilm_policies

    config = mgr.get_config()
    return generate_ilm_policies(
        RetentionConfig(
            hot_days=hot_days,
            warm_days=config.warm_days,
            cold_days=config.cold_days,
            disk_threshold=config.disk_threshold,
            emergency_threshold=config.emergency_threshold,
        )
    )


class _GateFirstAcquirer:
    """Wraps the ILM lock and holds the first caller *before* it acquires."""

    def __init__(self, inner):
        self._inner = inner
        self._first = True
        self.waiting = threading.Event()
        self.release = threading.Event()

    def __enter__(self):
        if self._first:
            self._first = False
            self.waiting.set()
            self.release.wait(5)
        return self._inner.__enter__()

    def __exit__(self, *exc):
        return self._inner.__exit__(*exc)


class _IlmTestCase(AioHTTPTestCase):
    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()
        super().setUp()

    def tearDown(self):
        task = self.app.get("_ilm_retry_task")
        if task is not None:
            task.cancel()
        super().tearDown()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    async def get_application(self):
        return _make_app_with_config_route(self._tmp_dir)

    @property
    def mgr(self) -> RetentionConfigManager:
        return self.app["retention_config_manager"]

    async def _save(self, body: dict) -> dict:
        resp = await self.client.post("/api/storage/config", json=body)
        self.assertEqual(resp.status, 200)
        return await resp.json()

    async def _until(self, condition) -> None:
        for _ in range(500):
            if condition():
                return
            await asyncio.sleep(0.01)
        self.fail("condition never became true")


class TestIlmErrorResultsAreFailures(_IlmTestCase):
    async def test_error_dict_schedules_retry_and_reports_not_applied(self):
        with patch(
            "api.server.apply_ilm_policies_from_config", return_value=ERROR_RESULTS
        ):
            data = await self._save(SAVE_A)

        self.assertFalse(data["ilm_applied"])
        self.assertTrue(data["ilm_retry_scheduled"])
        self.assertIn("ILM policies failed", data["ilm_error"])
        self.assertIsNotNone(self.app["_ilm_retry_task"])
        self.assertNotIn("last_success", self.mgr.get_ilm_status())
        self.assertEqual(self.app["ilm_sync"].applied_revision, 0)


class TestRetryNeverReappliesOlderSave(_IlmTestCase):
    async def test_failed_a_then_successful_b_then_retry(self):
        from api.server import _ilm_retry_background

        applied: list[dict] = []

        def fake_apply(url, policies, http_auth=None):
            applied.append(policies)
            return ERROR_RESULTS if len(applied) == 1 else OK_RESULTS

        with patch("api.server.apply_ilm_policies_from_config", fake_apply):
            data_a = await self._save(SAVE_A)
            self.app["_ilm_retry_task"].cancel()  # run the retry by hand below
            data_b = await self._save(SAVE_B)
            await _ilm_retry_background(self.app, max_retries=1, base_delay=0)

        self.assertFalse(data_a["ilm_applied"])
        self.assertTrue(data_b["ilm_applied"])
        self.assertEqual(len(applied), 2)  # the retry skipped: B is applied
        self.assertEqual(applied[-1], _policies_for(120, self.mgr))
        self.assertEqual(self.app["ilm_sync"].applied_revision, 2)

    async def test_retry_applies_the_current_config(self):
        from api.server import _ilm_retry_background

        applied: list[dict] = []

        def fake_apply(url, policies, http_auth=None):
            applied.append(policies)
            return ERROR_RESULTS if len(applied) == 1 else OK_RESULTS

        with patch("api.server.apply_ilm_policies_from_config", fake_apply):
            await self._save(SAVE_A)
            self.app["_ilm_retry_task"].cancel()
            await _ilm_retry_background(self.app, max_retries=1, base_delay=0)

        self.assertEqual(applied[-1], _policies_for(30, self.mgr))
        self.assertEqual(self.app["ilm_sync"].applied_revision, 1)
        self.assertIsNone(self.app["_ilm_retry_task"])
        self.assertIn("last_success", self.mgr.get_ilm_status())


class TestSavesNeverOverlapAndNewestWins(_IlmTestCase):
    async def test_a_blocked_inside_apply_then_b(self):
        applied: list[dict] = []
        active = {"now": 0, "max": 0}
        counter_lock = threading.Lock()
        a_inside = threading.Event()
        release_a = threading.Event()

        def fake_apply(url, policies, http_auth=None):
            with counter_lock:
                active["now"] += 1
                active["max"] = max(active["max"], active["now"])
                first = not applied
                applied.append(policies)
            try:
                if first:
                    a_inside.set()
                    release_a.wait(5)
                return OK_RESULTS
            finally:
                with counter_lock:
                    active["now"] -= 1

        loop = asyncio.get_running_loop()
        state = self.app["ilm_sync"]
        with patch("api.server.apply_ilm_policies_from_config", fake_apply):
            task_a = asyncio.ensure_future(self._save(SAVE_A))
            await loop.run_in_executor(None, a_inside.wait, 5)
            task_b = asyncio.ensure_future(self._save(SAVE_B))
            await self._until(lambda: state.config_revision == 2)
            release_a.set()
            data_a, data_b = await task_a, await task_b

        self.assertEqual(active["max"], 1)
        self.assertEqual(
            applied, [_policies_for(30, self.mgr), _policies_for(120, self.mgr)]
        )
        self.assertEqual(state.applied_revision, 2)
        self.assertTrue(data_a["ilm_applied"])
        self.assertTrue(data_b["ilm_applied"])

    async def test_a_paused_before_lock_skips_after_b(self):
        applied: list[dict] = []

        def fake_apply(url, policies, http_auth=None):
            applied.append(policies)
            return OK_RESULTS

        loop = asyncio.get_running_loop()
        state = self.app["ilm_sync"]
        gate = _GateFirstAcquirer(state.lock)
        state.lock = gate
        with patch("api.server.apply_ilm_policies_from_config", fake_apply):
            task_a = asyncio.ensure_future(self._save(SAVE_A))
            await loop.run_in_executor(None, gate.waiting.wait, 5)
            data_b = await self._save(SAVE_B)
            gate.release.set()
            data_a = await task_a

        self.assertEqual(applied, [_policies_for(120, self.mgr)])  # A never applied
        self.assertEqual(state.applied_revision, 2)
        self.assertTrue(data_b["ilm_applied"])
        self.assertTrue(data_a["ilm_applied"])  # superseded by the applied B


if __name__ == "__main__":
    unittest.main()
