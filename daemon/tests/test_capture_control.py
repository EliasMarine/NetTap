"""
Tests for daemon/api/capture_control.py

Covers GET /api/capture/status, PUT /api/capture/toggle,
PUT /api/capture/settings.  All Docker interactions are mocked.
Uses temporary env files to avoid touching real configuration.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.capture_control import register_capture_control_routes
from api.settings import _load_env_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MODULE = "api.capture_control"


def _mock_container_status(running: bool, status: str = "running"):
    """Return a dict matching _get_container_status return shape."""
    return {"running": running, "status": status if running else "exited"}


# ---------------------------------------------------------------------------
# GET /api/capture/status
# ---------------------------------------------------------------------------


class TestGetCaptureStatus(AioHTTPTestCase):
    """Tests for GET /api/capture/status."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            suffix=".env", delete=False, mode="w"
        )
        self.tmp.write('PCAP_CAPTURE_ENABLED="true"\n')
        self.tmp.write('PCAP_ROTATE_MB="250"\n')
        self.tmp.close()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    async def get_application(self):
        app = web.Application()
        register_capture_control_routes(app, env_file=self.tmp.name)
        return app

    @unittest_run_loop
    @patch(f"{MODULE}._get_container_status", new_callable=AsyncMock)
    async def test_status_returns_correct_values(self, mock_status):
        mock_status.return_value = _mock_container_status(True)
        resp = await self.client.request("GET", "/api/capture/status")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["enabled"])
        self.assertEqual(data["maxFileSizeMB"], 250)
        self.assertTrue(data["containerRunning"])
        self.assertEqual(data["containerStatus"], "running")

    @unittest_run_loop
    @patch(f"{MODULE}._get_container_status", new_callable=AsyncMock)
    async def test_status_returns_defaults_when_env_empty(self, mock_status):
        # Overwrite env file to be empty
        with open(self.tmp.name, "w") as f:
            f.write("")
        mock_status.return_value = _mock_container_status(False, "exited")
        resp = await self.client.request("GET", "/api/capture/status")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        # Defaults: enabled=true, maxFileSizeMB=100
        self.assertTrue(data["enabled"])
        self.assertEqual(data["maxFileSizeMB"], 100)
        self.assertFalse(data["containerRunning"])
        self.assertEqual(data["containerStatus"], "exited")


# ---------------------------------------------------------------------------
# PUT /api/capture/toggle
# ---------------------------------------------------------------------------


class TestPutCaptureToggle(AioHTTPTestCase):
    """Tests for PUT /api/capture/toggle."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            suffix=".env", delete=False, mode="w"
        )
        self.tmp.write('PCAP_CAPTURE_ENABLED="true"\n')
        self.tmp.close()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    async def get_application(self):
        app = web.Application()
        register_capture_control_routes(app, env_file=self.tmp.name)
        return app

    @unittest_run_loop
    @patch(f"{MODULE}._get_container_status", new_callable=AsyncMock)
    @patch(f"{MODULE}._docker_cmd", new_callable=AsyncMock)
    async def test_toggle_off_stops_container(self, mock_cmd, mock_status):
        mock_cmd.return_value = (0, "")
        mock_status.return_value = _mock_container_status(False, "exited")
        resp = await self.client.request(
            "PUT", "/api/capture/toggle", json={"enabled": False}
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertFalse(data["enabled"])
        mock_cmd.assert_called_once_with("stop", "nettap-pcap-capture")
        # Verify persisted to env file
        env = _load_env_file(self.tmp.name)
        self.assertEqual(env["PCAP_CAPTURE_ENABLED"], "false")

    @unittest_run_loop
    @patch(f"{MODULE}._get_container_status", new_callable=AsyncMock)
    @patch(f"{MODULE}._docker_cmd", new_callable=AsyncMock)
    async def test_toggle_on_starts_container(self, mock_cmd, mock_status):
        mock_cmd.return_value = (0, "")
        mock_status.return_value = _mock_container_status(True)
        resp = await self.client.request(
            "PUT", "/api/capture/toggle", json={"enabled": True}
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["enabled"])
        mock_cmd.assert_called_once_with("start", "nettap-pcap-capture")
        # Verify persisted to env file
        env = _load_env_file(self.tmp.name)
        self.assertEqual(env["PCAP_CAPTURE_ENABLED"], "true")

    @unittest_run_loop
    async def test_toggle_invalid_json_returns_400(self):
        resp = await self.client.request(
            "PUT",
            "/api/capture/toggle",
            data="not json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("error", data)

    @unittest_run_loop
    async def test_toggle_missing_enabled_returns_400(self):
        resp = await self.client.request(
            "PUT", "/api/capture/toggle", json={"something": True}
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("error", data)


# ---------------------------------------------------------------------------
# PUT /api/capture/settings
# ---------------------------------------------------------------------------


class TestPutCaptureSettings(AioHTTPTestCase):
    """Tests for PUT /api/capture/settings."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            suffix=".env", delete=False, mode="w"
        )
        self.tmp.write('PCAP_ROTATE_MB="100"\n')
        self.tmp.close()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    async def get_application(self):
        app = web.Application()
        register_capture_control_routes(app, env_file=self.tmp.name)
        return app

    @unittest_run_loop
    @patch(f"{MODULE}._get_container_status", new_callable=AsyncMock)
    @patch(f"{MODULE}._docker_cmd", new_callable=AsyncMock)
    async def test_settings_updates_and_restarts_if_running(
        self, mock_cmd, mock_status
    ):
        mock_status.return_value = _mock_container_status(True)
        mock_cmd.return_value = (0, "")
        resp = await self.client.request(
            "PUT", "/api/capture/settings", json={"maxFileSizeMB": 500}
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["maxFileSizeMB"], 500)
        self.assertTrue(data["restarted"])
        mock_cmd.assert_called_once_with("restart", "nettap-pcap-capture")

    @unittest_run_loop
    @patch(f"{MODULE}._get_container_status", new_callable=AsyncMock)
    @patch(f"{MODULE}._docker_cmd", new_callable=AsyncMock)
    async def test_settings_no_restart_when_stopped(self, mock_cmd, mock_status):
        mock_status.return_value = _mock_container_status(False, "exited")
        resp = await self.client.request(
            "PUT", "/api/capture/settings", json={"maxFileSizeMB": 200}
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["maxFileSizeMB"], 200)
        self.assertFalse(data["restarted"])
        mock_cmd.assert_not_called()

    @unittest_run_loop
    async def test_settings_too_small_returns_400(self):
        resp = await self.client.request(
            "PUT", "/api/capture/settings", json={"maxFileSizeMB": 5}
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("error", data)

    @unittest_run_loop
    async def test_settings_too_large_returns_400(self):
        resp = await self.client.request(
            "PUT", "/api/capture/settings", json={"maxFileSizeMB": 50000}
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("error", data)

    @unittest_run_loop
    @patch(f"{MODULE}._get_container_status", new_callable=AsyncMock)
    @patch(f"{MODULE}._docker_cmd", new_callable=AsyncMock)
    async def test_settings_persists_to_env_file(self, mock_cmd, mock_status):
        mock_status.return_value = _mock_container_status(False, "exited")
        resp = await self.client.request(
            "PUT", "/api/capture/settings", json={"maxFileSizeMB": 750}
        )
        self.assertEqual(resp.status, 200)
        env = _load_env_file(self.tmp.name)
        self.assertEqual(env["PCAP_ROTATE_MB"], "750")

    @unittest_run_loop
    async def test_settings_missing_field_returns_400(self):
        resp = await self.client.request(
            "PUT", "/api/capture/settings", json={"fileSize": 200}
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("error", data)

    @unittest_run_loop
    async def test_settings_invalid_json_returns_400(self):
        """PUT /api/capture/settings with invalid JSON returns 400."""
        resp = await self.client.request(
            "PUT",
            "/api/capture/settings",
            data="not json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 400)


# ---------------------------------------------------------------------------
# enforce_capture_state
# ---------------------------------------------------------------------------


class TestEnforceCaptureState(unittest.TestCase):
    """Tests for enforce_capture_state startup helper."""

    def test_enforce_stops_container_when_disabled(self):
        """When PCAP_CAPTURE_ENABLED=false, enforce_capture_state stops the container."""
        import asyncio
        from api.capture_control import enforce_capture_state

        tmp = tempfile.NamedTemporaryFile(
            suffix=".env", delete=False, mode="w"
        )
        tmp.write('PCAP_CAPTURE_ENABLED="false"\n')
        tmp.close()
        try:
            with patch(f"{MODULE}._docker_cmd", new_callable=AsyncMock) as mock_cmd:
                mock_cmd.return_value = (0, "")
                asyncio.run(enforce_capture_state(tmp.name))
                mock_cmd.assert_called_once_with("stop", "nettap-pcap-capture")
        finally:
            os.unlink(tmp.name)

    def test_enforce_does_nothing_when_enabled(self):
        """When PCAP_CAPTURE_ENABLED=true (default), enforce_capture_state does nothing."""
        import asyncio
        from api.capture_control import enforce_capture_state

        tmp = tempfile.NamedTemporaryFile(
            suffix=".env", delete=False, mode="w"
        )
        tmp.write('PCAP_CAPTURE_ENABLED="true"\n')
        tmp.close()
        try:
            with patch(f"{MODULE}._docker_cmd", new_callable=AsyncMock) as mock_cmd:
                asyncio.run(enforce_capture_state(tmp.name))
                mock_cmd.assert_not_called()
        finally:
            os.unlink(tmp.name)


if __name__ == "__main__":
    unittest.main()
