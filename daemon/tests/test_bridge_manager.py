"""
Tests for daemon/services/bridge_manager.py

All tests use mocked subprocess calls — no real nsenter, ip, or sysfs access
required. Tests cover bridge creation, teardown, readiness checks, persistence
file generation, and error handling.
"""

import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.bridge_manager import BridgeManager


class TestBridgeManagerInit(unittest.TestCase):
    """Tests for BridgeManager initialization."""

    def test_default_parameters(self):
        """Default init should use br0 and empty dirs."""
        mgr = BridgeManager()
        self.assertEqual(mgr._bridge_name, "br0")

    def test_custom_parameters(self):
        """Custom parameters should be stored."""
        mgr = BridgeManager(
            bridge_name="br1",
            netplan_dir="/tmp/netplan",
            systemd_dir="/tmp/systemd",
            sysctl_dir="/tmp/sysctl",
        )
        self.assertEqual(mgr._bridge_name, "br1")
        self.assertEqual(mgr._netplan_dir, "/tmp/netplan")
        self.assertEqual(mgr._systemd_dir, "/tmp/systemd")
        self.assertEqual(mgr._sysctl_dir, "/tmp/sysctl")


class TestCreateBridge(unittest.TestCase):
    """Tests for BridgeManager.create_bridge()."""

    def _make_manager(self):
        """Create a BridgeManager with no persistence dirs."""
        return BridgeManager(bridge_name="br0", netplan_dir="", systemd_dir="", sysctl_dir="")

    def test_rejects_same_wan_lan(self):
        """create_bridge should reject wan == lan."""
        mgr = self._make_manager()
        result = asyncio.run(mgr.create_bridge("eth0", "eth0"))
        self.assertFalse(result["created"])
        self.assertIn("WAN and LAN interfaces must be different", result["errors"])

    def test_rejects_missing_interface(self):
        """create_bridge should reject non-existent interfaces."""
        mgr = self._make_manager()

        async def mock_nsenter(*args):
            cmd = list(args)
            # ip -j link show <iface> — fail for both
            if "link" in cmd and "show" in cmd:
                return (1, "", "Device does not exist")
            return (0, "", "")

        mgr._run_nsenter = mock_nsenter

        result = asyncio.run(mgr.create_bridge("fake0", "fake1"))
        self.assertFalse(result["created"])
        self.assertTrue(len(result["errors"]) >= 1)

    def test_successful_creation(self):
        """create_bridge should succeed with valid interfaces."""
        mgr = self._make_manager()
        commands_run: list[list[str]] = []

        async def mock_nsenter(*args):
            commands_run.append(list(args))
            # Bridge doesn't exist yet (ip link show br0 fails)
            if args == ("ip", "link", "show", "br0"):
                return (1, "", "Device \"br0\" does not exist.")
            return (0, "", "")

        mgr._run_nsenter = mock_nsenter

        result = asyncio.run(mgr.create_bridge("enp2s0", "enp3s0", persist=False))
        self.assertTrue(result["created"])
        self.assertEqual(result["bridge_name"], "br0")
        self.assertEqual(result["wan"], "enp2s0")
        self.assertEqual(result["lan"], "enp3s0")
        self.assertEqual(result["state"], "created")
        self.assertEqual(result["errors"], [])

        # Verify key commands were issued
        cmd_strs = [" ".join(c) for c in commands_run]

        # Should have validated both interfaces
        self.assertTrue(any("ip -j link show enp2s0" in c for c in cmd_strs))
        self.assertTrue(any("ip -j link show enp3s0" in c for c in cmd_strs))

        # Should have checked if bridge exists
        self.assertTrue(any("ip link show br0" in c for c in cmd_strs))

        # Should have created bridge
        self.assertTrue(any("ip link add br0 type bridge" in c for c in cmd_strs))

        # Should have added interfaces to bridge
        self.assertTrue(any("ip link set enp2s0 master br0" in c for c in cmd_strs))
        self.assertTrue(any("ip link set enp3s0 master br0" in c for c in cmd_strs))

        # Should have enabled promisc
        self.assertTrue(any("ip link set enp2s0 promisc on" in c for c in cmd_strs))
        self.assertTrue(any("ip link set enp3s0 promisc on" in c for c in cmd_strs))

        # Should have disabled netfilter
        self.assertTrue(any("net.bridge.bridge-nf-call-iptables=0" in c for c in cmd_strs))

        # Should have brought bridge up
        self.assertTrue(any("ip link set br0 up" in c for c in cmd_strs))

    def test_bridge_already_exists_reconfigures(self):
        """create_bridge should reconfigure an existing bridge."""
        mgr = self._make_manager()
        commands_run: list[list[str]] = []

        async def mock_nsenter(*args):
            commands_run.append(list(args))
            # ip link show br0 — bridge exists
            if args == ("ip", "link", "show", "br0"):
                return (0, "", "")
            return (0, "", "")

        mgr._run_nsenter = mock_nsenter

        result = asyncio.run(mgr.create_bridge("enp2s0", "enp3s0", persist=False))
        self.assertTrue(result["created"])
        self.assertEqual(result["state"], "reconfigured")

        # Should NOT have created bridge (it already exists)
        cmd_strs = [" ".join(c) for c in commands_run]
        self.assertFalse(any("ip link add br0 type bridge" in c for c in cmd_strs))

        # Should have removed interfaces first (nomaster)
        self.assertTrue(any("ip link set enp2s0 nomaster" in c for c in cmd_strs))
        self.assertTrue(any("ip link set enp3s0 nomaster" in c for c in cmd_strs))

    def test_bridge_creation_failure(self):
        """create_bridge should handle ip link add failure."""
        mgr = self._make_manager()
        call_count = 0

        async def mock_nsenter(*args):
            nonlocal call_count
            call_count += 1
            # Interface validation passes
            if "link" in args and "show" in args and args != ("ip", "link", "show", "br0"):
                return (0, "", "")
            # Bridge doesn't exist yet
            if args == ("ip", "link", "show", "br0"):
                return (1, "", "not found")
            # Bridge creation fails
            if "add" in args:
                return (1, "", "RTNETLINK answers: Operation not permitted")
            return (0, "", "")

        mgr._run_nsenter = mock_nsenter

        result = asyncio.run(mgr.create_bridge("enp2s0", "enp3s0", persist=False))
        self.assertFalse(result["created"])
        self.assertTrue(any("Failed to create bridge" in e for e in result["errors"]))


class TestTeardownBridge(unittest.TestCase):
    """Tests for BridgeManager.teardown_bridge()."""

    def test_teardown_nonexistent_bridge(self):
        """teardown_bridge should fail if bridge doesn't exist."""
        mgr = BridgeManager()

        async def mock_nsenter(*args):
            if args == ("ip", "link", "show", "br0"):
                return (1, "", "not found")
            return (0, "", "")

        mgr._run_nsenter = mock_nsenter

        result = asyncio.run(mgr.teardown_bridge())
        self.assertFalse(result["torn_down"])
        self.assertTrue(len(result["errors"]) >= 1)

    def test_teardown_success(self):
        """teardown_bridge should remove members and delete bridge."""
        mgr = BridgeManager()
        commands_run: list[list[str]] = []

        async def mock_nsenter(*args):
            commands_run.append(list(args))
            # Bridge exists
            if args == ("ip", "link", "show", "br0"):
                return (0, "", "")
            # Member discovery
            if "master" in args:
                import json
                return (0, json.dumps([
                    {"ifname": "enp2s0"},
                    {"ifname": "enp3s0"},
                ]), "")
            return (0, "", "")

        mgr._run_nsenter = mock_nsenter

        result = asyncio.run(mgr.teardown_bridge())
        self.assertTrue(result["torn_down"])

        cmd_strs = [" ".join(c) for c in commands_run]
        # Should remove members
        self.assertTrue(any("ip link set enp2s0 nomaster" in c for c in cmd_strs))
        self.assertTrue(any("ip link set enp3s0 nomaster" in c for c in cmd_strs))
        # Should disable promisc
        self.assertTrue(any("ip link set enp2s0 promisc off" in c for c in cmd_strs))
        self.assertTrue(any("ip link set enp3s0 promisc off" in c for c in cmd_strs))
        # Should delete bridge
        self.assertTrue(any("ip link del br0" in c for c in cmd_strs))


class TestCheckReadiness(unittest.TestCase):
    """Tests for BridgeManager.check_readiness()."""

    def test_no_bridge_returns_not_ready(self):
        """Readiness should fail if bridge directory doesn't exist."""
        mgr = BridgeManager(bridge_name="nonexistent_br99")

        result = asyncio.run(mgr.check_readiness())
        self.assertFalse(result["ready"])
        self.assertEqual(len(result["checks"]), 8)
        self.assertFalse(result["checks"][0]["passed"])  # bridge_exists
        self.assertIn("not been configured", result["message"].lower())

    def test_readiness_returns_correct_structure(self):
        """Readiness should return ready, checks[], message."""
        mgr = BridgeManager(bridge_name="nonexistent_br99")

        result = asyncio.run(mgr.check_readiness())
        self.assertIn("ready", result)
        self.assertIn("checks", result)
        self.assertIn("message", result)
        self.assertIsInstance(result["checks"], list)

    def test_readiness_check_names(self):
        """All 8 expected check names should be present."""
        mgr = BridgeManager(bridge_name="nonexistent_br99")

        result = asyncio.run(mgr.check_readiness())
        check_names = [c["name"] for c in result["checks"]]
        expected = [
            "bridge_exists",
            "bridge_up",
            "wan_carrier",
            "lan_carrier",
            "wan_promisc",
            "lan_promisc",
            "stp_disabled",
            "netfilter_disabled",
        ]
        self.assertEqual(check_names, expected)


class TestRunNsenter(unittest.TestCase):
    """Tests for BridgeManager._run_nsenter()."""

    def test_nsenter_not_available(self):
        """_run_nsenter should handle missing nsenter gracefully."""
        mgr = BridgeManager()

        # On macOS/test environments, nsenter is not available
        rc, stdout, stderr = asyncio.run(mgr._run_nsenter("ip", "link", "show"))
        # Should return non-zero (nsenter not found or failed)
        self.assertIsInstance(rc, int)
        self.assertIsInstance(stdout, str)
        self.assertIsInstance(stderr, str)

    def test_nsenter_timeout(self):
        """_run_nsenter should handle timeout gracefully."""
        mgr = BridgeManager()

        async def test():
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
                mock_exec.return_value = mock_proc

                rc, stdout, stderr = await mgr._run_nsenter("sleep", "60")
                self.assertEqual(rc, 1)
                self.assertEqual(stderr, "timeout")

        asyncio.run(test())


class TestWritePersistence(unittest.TestCase):
    """Tests for BridgeManager._write_persistence()."""

    def test_writes_netplan_yaml(self):
        """_write_persistence should write valid netplan YAML."""
        with tempfile.TemporaryDirectory() as tmpdir:
            netplan_dir = os.path.join(tmpdir, "netplan")
            os.makedirs(netplan_dir)

            mgr = BridgeManager(
                netplan_dir=netplan_dir,
                systemd_dir="",
                sysctl_dir="",
            )
            files = mgr._write_persistence("enp2s0", "enp3s0")
            self.assertEqual(len(files), 1)
            self.assertIn("10-nettap-bridge.yaml", files[0])

            content = open(files[0]).read()
            self.assertIn("enp2s0", content)
            self.assertIn("enp3s0", content)
            self.assertIn("br0", content)
            self.assertIn("stp: false", content)

    def test_writes_systemd_unit(self):
        """_write_persistence should write valid systemd unit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            systemd_dir = os.path.join(tmpdir, "systemd")
            os.makedirs(systemd_dir)

            mgr = BridgeManager(
                netplan_dir="",
                systemd_dir=systemd_dir,
                sysctl_dir="",
            )
            files = mgr._write_persistence("enp2s0", "enp3s0")
            self.assertEqual(len(files), 1)
            self.assertIn("nettap-bridge.service", files[0])

            content = open(files[0]).read()
            self.assertIn("[Unit]", content)
            self.assertIn("[Service]", content)
            self.assertIn("[Install]", content)
            self.assertIn("enp2s0", content)
            self.assertIn("enp3s0", content)

    def test_writes_sysctl_config(self):
        """_write_persistence should write sysctl config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sysctl_dir = os.path.join(tmpdir, "sysctl")
            os.makedirs(sysctl_dir)

            mgr = BridgeManager(
                netplan_dir="",
                systemd_dir="",
                sysctl_dir=sysctl_dir,
            )
            files = mgr._write_persistence("enp2s0", "enp3s0")
            self.assertEqual(len(files), 1)
            self.assertIn("99-nettap-bridge.conf", files[0])

            content = open(files[0]).read()
            self.assertIn("net.bridge.bridge-nf-call-iptables = 0", content)

    def test_writes_all_three(self):
        """_write_persistence should write all 3 files when all dirs set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for d in ("netplan", "systemd", "sysctl"):
                os.makedirs(os.path.join(tmpdir, d))

            mgr = BridgeManager(
                netplan_dir=os.path.join(tmpdir, "netplan"),
                systemd_dir=os.path.join(tmpdir, "systemd"),
                sysctl_dir=os.path.join(tmpdir, "sysctl"),
            )
            files = mgr._write_persistence("enp2s0", "enp3s0")
            self.assertEqual(len(files), 3)

    def test_no_dirs_writes_nothing(self):
        """_write_persistence should write nothing if no dirs configured."""
        mgr = BridgeManager(netplan_dir="", systemd_dir="", sysctl_dir="")
        files = mgr._write_persistence("enp2s0", "enp3s0")
        self.assertEqual(len(files), 0)


class TestCheckPromisc(unittest.TestCase):
    """Tests for BridgeManager._check_promisc()."""

    def test_promisc_enabled(self):
        """_check_promisc should return True when IFF_PROMISC flag is set."""
        mgr = BridgeManager()

        # 0x1103 includes IFF_PROMISC (0x100)
        with patch.object(mgr, "_read_sysfs", return_value="0x1103"):
            result = asyncio.run(mgr._check_promisc("eth0"))
            self.assertTrue(result)

    def test_promisc_disabled(self):
        """_check_promisc should return False when IFF_PROMISC flag is not set."""
        mgr = BridgeManager()

        # 0x1003 does NOT include IFF_PROMISC (0x100)
        with patch.object(mgr, "_read_sysfs", return_value="0x1003"):
            result = asyncio.run(mgr._check_promisc("eth0"))
            self.assertFalse(result)

    def test_promisc_missing_file(self):
        """_check_promisc should return False when sysfs file is missing."""
        mgr = BridgeManager()

        with patch.object(mgr, "_read_sysfs", return_value=""):
            result = asyncio.run(mgr._check_promisc("eth0"))
            self.assertFalse(result)


class TestDiscoverMembers(unittest.TestCase):
    """Tests for BridgeManager._discover_members()."""

    def test_fallback_to_env_vars(self):
        """_discover_members should fall back to env vars when sysfs unavailable."""
        mgr = BridgeManager(bridge_name="nonexistent_br99")

        wan, lan = asyncio.run(mgr._discover_members())
        # Should return defaults from env vars
        self.assertIsInstance(wan, str)
        self.assertIsInstance(lan, str)

    def test_discovers_from_sysfs(self):
        """_discover_members should read brif directory when available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brif_dir = os.path.join(tmpdir, "br0", "brif")
            os.makedirs(brif_dir)
            os.makedirs(os.path.join(brif_dir, "enp2s0"))
            os.makedirs(os.path.join(brif_dir, "enp3s0"))

            mgr = BridgeManager(bridge_name="br0")

            with patch("services.bridge_manager._SYSFS_NET", tmpdir):
                wan, lan = asyncio.run(mgr._discover_members())
                self.assertEqual(wan, "enp2s0")
                self.assertEqual(lan, "enp3s0")


if __name__ == "__main__":
    unittest.main()
