"""
Tests for POST /api/storage/config endpoint in daemon/api/server.py

Covers valid config save, validation errors, missing config manager (503),
ILM success and failure retry scheduling. Uses AioHTTPTestCase with mocked
OpenSearch — no real connections required.
"""

import os
import sys
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
    from api.server import handle_storage_config

    app = web.Application()

    storage, _ = _make_mock_storage()
    app["storage"] = storage
    app["opensearch_url"] = "http://localhost:9200"
    app["http_auth"] = None

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
        return _make_app_with_config_route(
            self._tmp_dir, include_config_manager=False
        )


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


if __name__ == "__main__":
    unittest.main()
