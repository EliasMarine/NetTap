"""
Tests for daemon/api/nic_identify.py

All tests use mocked subprocess calls -- no real ethtool, NIC hardware,
or network interfaces required. Tests cover input validation, duration
capping, ethtool availability checks, and shell injection prevention.
"""

import os
import sys
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.nic_identify import register_nic_identify_routes


class TestNicIdentifyEndpoint(AioHTTPTestCase):
    """Tests for POST /api/setup/nics/identify."""

    async def get_application(self):
        app = web.Application()
        register_nic_identify_routes(app)
        return app

    @unittest_run_loop
    @patch("api.nic_identify.shutil.which", return_value="/usr/sbin/ethtool")
    @patch("api.nic_identify.asyncio.create_subprocess_exec")
    async def test_valid_interface_returns_200(self, mock_exec, mock_which):
        """Valid interface name should return 200 with blinking result."""
        mock_process = AsyncMock()
        mock_process.wait = AsyncMock(side_effect=TimeoutError)
        mock_process.stderr = AsyncMock()
        mock_exec.return_value = mock_process

        resp = await self.client.request(
            "POST",
            "/api/setup/nics/identify",
            json={"interface": "eth0", "duration": 15},
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["result"], "blinking")
        self.assertEqual(data["interface"], "eth0")
        self.assertEqual(data["duration"], 15)

    @unittest_run_loop
    async def test_missing_interface_returns_400(self):
        """Missing 'interface' field should return 400."""
        resp = await self.client.request(
            "POST",
            "/api/setup/nics/identify",
            json={"duration": 15},
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("interface", data["error"].lower())

    @unittest_run_loop
    async def test_empty_interface_returns_400(self):
        """Empty string interface should return 400."""
        resp = await self.client.request(
            "POST",
            "/api/setup/nics/identify",
            json={"interface": "", "duration": 15},
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("interface", data["error"].lower())

    @unittest_run_loop
    async def test_shell_injection_interface_returns_400(self):
        """Interface name with shell metacharacters should return 400."""
        resp = await self.client.request(
            "POST",
            "/api/setup/nics/identify",
            json={"interface": "eth0; rm -rf /", "duration": 15},
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("invalid interface name", data["error"].lower())

    @unittest_run_loop
    async def test_pipe_injection_returns_400(self):
        """Interface name with pipe character should return 400."""
        resp = await self.client.request(
            "POST",
            "/api/setup/nics/identify",
            json={"interface": "eth0|cat /etc/passwd"},
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_backtick_injection_returns_400(self):
        """Interface name with backticks should return 400."""
        resp = await self.client.request(
            "POST",
            "/api/setup/nics/identify",
            json={"interface": "`whoami`"},
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_dollar_injection_returns_400(self):
        """Interface name with dollar sign should return 400."""
        resp = await self.client.request(
            "POST",
            "/api/setup/nics/identify",
            json={"interface": "$(reboot)"},
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_spaces_in_interface_returns_400(self):
        """Interface name with spaces should return 400."""
        resp = await self.client.request(
            "POST",
            "/api/setup/nics/identify",
            json={"interface": "eth 0"},
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    @patch("api.nic_identify.shutil.which", return_value="/usr/sbin/ethtool")
    @patch("api.nic_identify.asyncio.create_subprocess_exec")
    async def test_duration_defaults_to_15(self, mock_exec, mock_which):
        """When duration is not provided, it should default to 15."""
        mock_process = AsyncMock()
        mock_process.wait = AsyncMock(side_effect=TimeoutError)
        mock_process.stderr = AsyncMock()
        mock_exec.return_value = mock_process

        resp = await self.client.request(
            "POST",
            "/api/setup/nics/identify",
            json={"interface": "eth0"},
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["duration"], 15)

    @unittest_run_loop
    @patch("api.nic_identify.shutil.which", return_value="/usr/sbin/ethtool")
    @patch("api.nic_identify.asyncio.create_subprocess_exec")
    async def test_duration_capped_at_30(self, mock_exec, mock_which):
        """Duration above 30 should be capped to 30."""
        mock_process = AsyncMock()
        mock_process.wait = AsyncMock(side_effect=TimeoutError)
        mock_process.stderr = AsyncMock()
        mock_exec.return_value = mock_process

        resp = await self.client.request(
            "POST",
            "/api/setup/nics/identify",
            json={"interface": "eth0", "duration": 120},
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["duration"], 30)

    @unittest_run_loop
    @patch("api.nic_identify.shutil.which", return_value="/usr/sbin/ethtool")
    @patch("api.nic_identify.asyncio.create_subprocess_exec")
    async def test_duration_must_be_positive(self, mock_exec, mock_which):
        """Duration of 0 or negative should be clamped to minimum 1."""
        mock_process = AsyncMock()
        mock_process.wait = AsyncMock(side_effect=TimeoutError)
        mock_process.stderr = AsyncMock()
        mock_exec.return_value = mock_process

        resp = await self.client.request(
            "POST",
            "/api/setup/nics/identify",
            json={"interface": "eth0", "duration": -5},
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["duration"], 1)

    @unittest_run_loop
    @patch("api.nic_identify.shutil.which", return_value=None)
    async def test_ethtool_not_found_returns_error(self, mock_which):
        """When ethtool is not installed, should return 500 with helpful hint."""
        resp = await self.client.request(
            "POST",
            "/api/setup/nics/identify",
            json={"interface": "eth0", "duration": 15},
        )
        self.assertEqual(resp.status, 500)
        data = await resp.json()
        self.assertEqual(data["error"], "ethtool is not installed")
        self.assertIn("apt install ethtool", data["hint"])

    @unittest_run_loop
    @patch("api.nic_identify.shutil.which", return_value="/usr/sbin/ethtool")
    @patch("api.nic_identify.asyncio.create_subprocess_exec")
    async def test_valid_interface_with_hyphens_underscores(self, mock_exec, mock_which):
        """Interface names with hyphens and underscores should be accepted."""
        mock_process = AsyncMock()
        mock_process.wait = AsyncMock(side_effect=TimeoutError)
        mock_process.stderr = AsyncMock()
        mock_exec.return_value = mock_process

        resp = await self.client.request(
            "POST",
            "/api/setup/nics/identify",
            json={"interface": "enp3s0-wan_mgmt", "duration": 10},
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["interface"], "enp3s0-wan_mgmt")

    @unittest_run_loop
    async def test_invalid_json_returns_400(self):
        """Non-JSON body should return 400."""
        resp = await self.client.request(
            "POST",
            "/api/setup/nics/identify",
            data="not json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("invalid json", data["error"].lower())

    @unittest_run_loop
    @patch("api.nic_identify.shutil.which", return_value="/usr/sbin/ethtool")
    @patch("api.nic_identify.asyncio.create_subprocess_exec")
    async def test_ethtool_immediate_failure_returns_500(self, mock_exec, mock_which):
        """When ethtool exits immediately with error, return 500."""
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_stderr = MagicMock()
        mock_stderr.read = AsyncMock(return_value=b"Cannot find device eth99")
        mock_process.stderr = mock_stderr
        mock_process.wait = AsyncMock(return_value=1)
        mock_exec.return_value = mock_process

        resp = await self.client.request(
            "POST",
            "/api/setup/nics/identify",
            json={"interface": "eth99", "duration": 5},
        )
        self.assertEqual(resp.status, 500)
        data = await resp.json()
        self.assertIn("ethtool failed", data["error"])

    @unittest_run_loop
    @patch("api.nic_identify.shutil.which", return_value="/usr/sbin/ethtool")
    @patch("api.nic_identify.asyncio.create_subprocess_exec", side_effect=OSError("Permission denied"))
    async def test_oserror_starting_ethtool_returns_500(self, mock_exec, mock_which):
        """OSError when starting ethtool should return 500."""
        resp = await self.client.request(
            "POST",
            "/api/setup/nics/identify",
            json={"interface": "eth0", "duration": 15},
        )
        self.assertEqual(resp.status, 500)
        data = await resp.json()
        self.assertIn("failed to start ethtool", data["error"].lower())


if __name__ == "__main__":
    unittest.main()
