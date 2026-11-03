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
from services.capture_config import (
    CaptureConfig,
    CaptureMode,
    load_capture_config,
    save_capture_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MODULE = "api.capture_control"


def _capture_paths(test: unittest.TestCase, environ: dict | None = None) -> str:
    """Point capture-mode.conf / capture.env at a temp dir for this test."""
    tmpdir = tempfile.mkdtemp()
    env = {
        "CAPTURE_CONFIG_PATH": os.path.join(tmpdir, "capture-mode.conf"),
        "CAPTURE_ENV_PATH": os.path.join(tmpdir, "capture.env"),
        **(environ or {}),
    }
    patcher = patch.dict(os.environ, env)
    patcher.start()
    test.addCleanup(patcher.stop)
    for name in ("PCAP_ROTATE_MB", "PCAP_ROTATE_MIN"):
        if name not in env:
            os.environ.pop(name, None)
    return tmpdir


def _mock_container_status(running: bool, status: str = "running"):
    """Return a dict matching _get_container_status return shape."""
    return {"running": running, "status": status if running else "exited"}


# ---------------------------------------------------------------------------
# GET /api/capture/status
# ---------------------------------------------------------------------------


class TestGetCaptureStatus(AioHTTPTestCase):
    """Tests for GET /api/capture/status."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".env", delete=False, mode="w")
        self.tmp.write('PCAP_CAPTURE_ENABLED="true"\n')
        self.tmp.write(
            'PCAP_ROTATE_MB="250"\n'
        )  # legacy store: pcap-capture never reads it
        self.tmp.close()
        _capture_paths(self, {"PCAP_ROTATE_MB": "4096", "PCAP_ROTATE_MIN": "10"})
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
        # what netsniff runs with: the compose value, not the legacy 250 (G11, 2026-11-02)
        self.assertEqual(data["maxFileSizeMB"], 4096)
        self.assertEqual(data["rotateMinutes"], 10)
        self.assertTrue(data["containerRunning"])
        self.assertEqual(data["containerStatus"], "running")

    @unittest_run_loop
    @patch(f"{MODULE}._get_container_status", new_callable=AsyncMock)
    async def test_status_returns_defaults_when_env_empty(self, mock_status):
        # Overwrite env file to be empty
        with open(self.tmp.name, "w") as f:
            f.write("")
        os.environ.pop("PCAP_ROTATE_MB", None)
        mock_status.return_value = _mock_container_status(False, "exited")
        resp = await self.client.request("GET", "/api/capture/status")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        # Defaults: enabled=true, maxFileSizeMB=100
        self.assertTrue(data["enabled"])
        self.assertEqual(data["maxFileSizeMB"], 100)
        self.assertFalse(data["containerRunning"])
        self.assertEqual(data["containerStatus"], "exited")

    @unittest_run_loop
    @patch(f"{MODULE}._get_container_status", new_callable=AsyncMock)
    async def test_saved_setting_wins_over_compose_value(self, mock_status):
        mock_status.return_value = _mock_container_status(True)
        save_capture_config(
            CaptureConfig(
                mode=CaptureMode.MIRROR, interface="enp4s0", pcap_rotate_mb=250
            )
        )
        data = await (await self.client.request("GET", "/api/capture/status")).json()
        self.assertEqual(data["maxFileSizeMB"], 250)


# ---------------------------------------------------------------------------
# PUT /api/capture/toggle
# ---------------------------------------------------------------------------


class TestPutCaptureToggle(AioHTTPTestCase):
    """Tests for PUT /api/capture/toggle."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".env", delete=False, mode="w")
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
        self.tmp = tempfile.NamedTemporaryFile(suffix=".env", delete=False, mode="w")
        self.tmp.write('PCAP_ROTATE_MB="100"\n')
        self.tmp.close()
        self.capture_dir = _capture_paths(self)
        save_capture_config(CaptureConfig(mode=CaptureMode.MIRROR, interface="enp4s0"))
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
        """Saved where pcap-capture's loader reads it: capture.env (+ capture-mode.conf)."""
        mock_status.return_value = _mock_container_status(False, "exited")
        resp = await self.client.request(
            "PUT", "/api/capture/settings", json={"maxFileSizeMB": 750}
        )
        self.assertEqual(resp.status, 200)
        capture_env = _load_env_file(os.path.join(self.capture_dir, "capture.env"))
        self.assertEqual(capture_env["PCAP_ROTATE_MEGABYTES"], "750")
        self.assertEqual(capture_env["PCAP_IFACE"], "enp4s0")  # mode untouched
        saved = load_capture_config()
        self.assertEqual(saved.pcap_rotate_mb, 750)
        self.assertEqual(saved.mode, CaptureMode.MIRROR)

    @unittest_run_loop
    @patch(f"{MODULE}._docker_cmd", new_callable=AsyncMock)
    async def test_settings_before_setup_is_409(self, mock_cmd):
        os.unlink(os.path.join(self.capture_dir, "capture-mode.conf"))
        resp = await self.client.request(
            "PUT", "/api/capture/settings", json={"maxFileSizeMB": 750}
        )
        self.assertEqual(resp.status, 409)
        self.assertFalse(os.path.exists(os.path.join(self.capture_dir, "capture.env")))
        mock_cmd.assert_not_called()

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

        tmp = tempfile.NamedTemporaryFile(suffix=".env", delete=False, mode="w")
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

        tmp = tempfile.NamedTemporaryFile(suffix=".env", delete=False, mode="w")
        tmp.write('PCAP_CAPTURE_ENABLED="true"\n')
        tmp.close()
        try:
            with patch(f"{MODULE}._docker_cmd", new_callable=AsyncMock) as mock_cmd:
                asyncio.run(enforce_capture_state(tmp.name))
                mock_cmd.assert_not_called()
        finally:
            os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# restart_capture_containers
# ---------------------------------------------------------------------------


class TestRestartCaptureContainers(unittest.TestCase):
    """Tests for restart_capture_containers (capture.env reload helper)."""

    ALL = [
        "nettap-zeek-live",
        "nettap-suricata-live",
        "nettap-pcap-capture",
    ]

    def _run(self, status_side_effect, cmd_side_effect):
        import asyncio
        from api.capture_control import restart_capture_containers

        with (
            patch(
                f"{MODULE}._get_container_status",
                new_callable=AsyncMock,
                side_effect=status_side_effect,
            ),
            patch(
                f"{MODULE}._docker_cmd",
                new_callable=AsyncMock,
                side_effect=cmd_side_effect,
            ) as mock_cmd,
        ):
            result = asyncio.run(restart_capture_containers())
        return result, mock_cmd

    def test_restarts_all_three_running_containers(self):
        result, mock_cmd = self._run(
            lambda c: _mock_container_status(True), lambda a, c: (0, "")
        )
        self.assertEqual(result, {"restarted": self.ALL, "errors": []})
        self.assertEqual(
            sorted(call.args for call in mock_cmd.await_args_list),
            sorted(("restart", c) for c in self.ALL),
        )

    def test_one_failure_does_not_stop_the_others(self):
        def cmd(action, container):
            if container == "nettap-suricata-live":
                return (1, "Error response from daemon: boom")
            return (0, "")

        result, _ = self._run(lambda c: _mock_container_status(True), cmd)
        self.assertEqual(
            result["restarted"],
            ["nettap-zeek-live", "nettap-pcap-capture"],
        )
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("nettap-suricata-live", result["errors"][0])
        self.assertIn("boom", result["errors"][0])

    def test_never_raises_when_docker_is_missing(self):
        def cmd(action, container):
            raise FileNotFoundError("docker")

        result, _ = self._run(lambda c: _mock_container_status(True), cmd)
        self.assertEqual(result["restarted"], [])
        self.assertEqual(len(result["errors"]), 3)

    def test_never_touches_arkime(self):
        """arkime-live is off by default (compose profile "arkime", #44): even a
        running one is never restarted, since restarting would keep it going."""
        result, mock_cmd = self._run(
            lambda c: _mock_container_status(True), lambda a, c: (0, "")
        )
        self.assertNotIn("nettap-arkime-live", result["restarted"])
        self.assertNotIn(
            "nettap-arkime-live", [call.args[1] for call in mock_cmd.await_args_list]
        )

    def test_stopped_container_is_left_stopped(self):
        """docker restart would start it; the PCAP toggle stops it on purpose."""

        def status(container):
            return _mock_container_status(container != "nettap-pcap-capture")

        result, mock_cmd = self._run(status, lambda a, c: (0, ""))
        self.assertNotIn("nettap-pcap-capture", result["restarted"])
        self.assertEqual(result["errors"], [])
        self.assertNotIn(
            ("restart", "nettap-pcap-capture"),
            [call.args for call in mock_cmd.await_args_list],
        )


if __name__ == "__main__":
    unittest.main()
