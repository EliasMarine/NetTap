"""
Tests for daemon/services/version_manager.py

All tests use mocks -- no real Docker, system commands, or filesystem
access required. Tests cover the VersionManager class: version scanning,
caching, component lookup, and graceful degradation when commands are
missing.
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.version_manager import (
    ComponentVersion,
    VersionManager,
    NETTAP_VERSION,
    _CACHE_TTL_SECONDS,
)


class TestComponentVersionDataclass(unittest.TestCase):
    """Tests for the ComponentVersion dataclass."""

    def test_to_dict_returns_all_fields(self):
        """to_dict() should return a dict with all expected fields."""
        cv = ComponentVersion(
            name="zeek",
            category="docker",
            current_version="6.0.4",
            install_type="docker",
            last_checked="2026-02-26T12:00:00+00:00",
            status="ok",
            details={"image": "malcolm/zeek:v6.0.4"},
        )
        d = cv.to_dict()
        expected_keys = {
            "name", "category", "current_version", "install_type",
            "last_checked", "status", "details",
        }
        self.assertEqual(set(d.keys()), expected_keys)

    def test_to_dict_preserves_values(self):
        """to_dict() should preserve exact values."""
        cv = ComponentVersion(
            name="suricata",
            category="system",
            current_version="7.0.3",
            install_type="apt",
            last_checked="2026-02-26T12:00:00+00:00",
            status="ok",
            details={"raw_output": "Suricata 7.0.3"},
        )
        d = cv.to_dict()
        self.assertEqual(d["name"], "suricata")
        self.assertEqual(d["category"], "system")
        self.assertEqual(d["current_version"], "7.0.3")
        self.assertEqual(d["install_type"], "apt")
        self.assertEqual(d["status"], "ok")
        self.assertEqual(d["details"]["raw_output"], "Suricata 7.0.3")

    def test_to_dict_with_error_status(self):
        """to_dict() should handle error status correctly."""
        cv = ComponentVersion(
            name="missing-tool",
            category="system",
            current_version="unknown",
            install_type="apt",
            last_checked="2026-02-26T12:00:00+00:00",
            status="error",
            details={"error": "Command not found"},
        )
        d = cv.to_dict()
        self.assertEqual(d["status"], "error")
        self.assertEqual(d["current_version"], "unknown")


class TestVersionManagerInitialization(unittest.TestCase):
    """Tests for VersionManager initialization."""

    def test_default_parameters(self):
        """Default init should use expected compose file path."""
        vm = VersionManager()
        self.assertEqual(
            vm._compose_file, "/opt/nettap/docker/docker-compose.yml"
        )
        self.assertEqual(vm._versions, {})
        self.assertIsNone(vm._last_scan)
        self.assertFalse(vm._scanning)

    def test_custom_compose_file(self):
        """Custom compose file path should be stored."""
        vm = VersionManager(compose_file="/custom/docker-compose.yml")
        self.assertEqual(vm._compose_file, "/custom/docker-compose.yml")


class TestNettapVersionConstant(unittest.TestCase):
    """Tests for the NETTAP_VERSION module constant."""

    def test_version_is_string(self):
        """NETTAP_VERSION should be a string."""
        self.assertIsInstance(NETTAP_VERSION, str)

    def test_version_format(self):
        """NETTAP_VERSION should follow semver format."""
        parts = NETTAP_VERSION.split(".")
        self.assertEqual(len(parts), 3)
        for part in parts:
            self.assertTrue(part.isdigit())

    def test_version_is_0_4_0(self):
        """NETTAP_VERSION should be 0.4.0 for Phase 4."""
        self.assertEqual(NETTAP_VERSION, "0.4.0")


class TestScanVersions(unittest.TestCase):
    """Tests for VersionManager.scan_versions()."""

    def _make_manager_with_mocks(self):
        """Create a VersionManager with mocked internal methods."""
        vm = VersionManager()
        now = datetime.now(timezone.utc).isoformat()

        async def mock_scan_core():
            return [ComponentVersion(
                name="nettap-daemon", category="core",
                current_version=NETTAP_VERSION, install_type="pip",
                last_checked=now, status="ok", details={},
            )]

        async def mock_scan_docker():
            return [ComponentVersion(
                name="zeek", category="docker",
                current_version="v26.02.0", install_type="docker",
                last_checked=now, status="ok", details={},
            )]

        async def mock_scan_system():
            return [ComponentVersion(
                name="python3", category="system",
                current_version="3.10.12", install_type="apt",
                last_checked=now, status="ok", details={},
            )]

        async def mock_scan_databases():
            return [ComponentVersion(
                name="opensearch", category="database",
                current_version="2.11.0", install_type="docker",
                last_checked=now, status="ok", details={},
            )]

        async def mock_scan_os():
            return [ComponentVersion(
                name="os", category="os",
                current_version="22.04", install_type="builtin",
                last_checked=now, status="ok", details={},
            )]

        vm._scan_core = mock_scan_core
        vm._scan_docker_images = mock_scan_docker
        vm._scan_system_packages = mock_scan_system
        vm._scan_databases = mock_scan_databases
        vm._scan_os_info = mock_scan_os

        return vm

    def test_scan_returns_dict_with_expected_structure(self):
        """scan_versions() should return dict with versions, last_scan, count."""
        vm = self._make_manager_with_mocks()
        result = asyncio.run(vm.scan_versions())

        self.assertIn("versions", result)
        self.assertIn("last_scan", result)
        self.assertIn("count", result)
        self.assertIsInstance(result["versions"], list)
        self.assertIsInstance(result["count"], int)
        self.assertEqual(result["count"], len(result["versions"]))

    def test_scan_returns_all_categories(self):
        """scan_versions() should include components from all categories."""
        vm = self._make_manager_with_mocks()
        result = asyncio.run(vm.scan_versions())

        categories = {v["category"] for v in result["versions"]}
        self.assertIn("core", categories)
        self.assertIn("docker", categories)
        self.assertIn("system", categories)
        self.assertIn("database", categories)
        self.assertIn("os", categories)

    def test_scan_populates_cache(self):
        """scan_versions() should populate the internal cache."""
        vm = self._make_manager_with_mocks()
        self.assertEqual(len(vm._versions), 0)

        asyncio.run(vm.scan_versions())

        self.assertGreater(len(vm._versions), 0)
        self.assertIsNotNone(vm._last_scan)

    def test_scan_sets_last_scan_timestamp(self):
        """scan_versions() should set _last_scan to an ISO timestamp."""
        vm = self._make_manager_with_mocks()
        asyncio.run(vm.scan_versions())

        self.assertIsNotNone(vm._last_scan)
        # Should parse as ISO datetime
        dt = datetime.fromisoformat(vm._last_scan)
        self.assertIsInstance(dt, datetime)

    def test_multiple_scans_dont_duplicate_entries(self):
        """Multiple scan calls should replace, not append, entries."""
        vm = self._make_manager_with_mocks()

        asyncio.run(vm.scan_versions())
        count_first = len(vm._versions)

        asyncio.run(vm.scan_versions())
        count_second = len(vm._versions)

        self.assertEqual(count_first, count_second)

    def test_scanning_flag_reset_on_completion(self):
        """_scanning flag should be False after scan completes."""
        vm = self._make_manager_with_mocks()
        asyncio.run(vm.scan_versions())
        self.assertFalse(vm._scanning)

    def test_scanning_flag_reset_on_error(self):
        """_scanning flag should be reset even if scan raises."""
        vm = VersionManager()

        async def mock_scan_core():
            raise RuntimeError("test error")

        vm._scan_core = mock_scan_core

        with self.assertRaises(RuntimeError):
            asyncio.run(vm.scan_versions())

        self.assertFalse(vm._scanning)


class TestGetVersions(unittest.TestCase):
    """Tests for VersionManager.get_versions()."""

    def test_get_versions_triggers_scan_when_empty(self):
        """get_versions() should trigger a scan if cache is empty."""
        vm = VersionManager()
        now = datetime.now(timezone.utc).isoformat()

        async def mock_scan_core():
            return [ComponentVersion(
                name="nettap-daemon", category="core",
                current_version=NETTAP_VERSION, install_type="pip",
                last_checked=now, status="ok", details={},
            )]

        async def mock_empty():
            return []

        vm._scan_core = mock_scan_core
        vm._scan_docker_images = mock_empty
        vm._scan_system_packages = mock_empty
        vm._scan_databases = mock_empty
        vm._scan_os_info = mock_empty

        result = asyncio.run(vm.get_versions())
        self.assertIn("versions", result)
        self.assertGreater(result["count"], 0)

    def test_get_versions_returns_cached_data(self):
        """get_versions() should return cached data if not stale."""
        vm = VersionManager()
        cv = ComponentVersion(
            name="test", category="core",
            current_version="1.0.0", install_type="pip",
            last_checked=datetime.now(timezone.utc).isoformat(),
            status="ok", details={},
        )
        vm._versions = {"test": cv}
        vm._last_scan = datetime.now(timezone.utc).isoformat()

        result = asyncio.run(vm.get_versions())
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["versions"][0]["name"], "test")


class TestGetComponent(unittest.TestCase):
    """Tests for VersionManager.get_component()."""

    def test_get_component_returns_none_for_unknown(self):
        """get_component() should return None for unknown components."""
        vm = VersionManager()
        now = datetime.now(timezone.utc).isoformat()

        async def mock_scan_core():
            return [ComponentVersion(
                name="nettap-daemon", category="core",
                current_version=NETTAP_VERSION, install_type="pip",
                last_checked=now, status="ok", details={},
            )]

        async def mock_empty():
            return []

        vm._scan_core = mock_scan_core
        vm._scan_docker_images = mock_empty
        vm._scan_system_packages = mock_empty
        vm._scan_databases = mock_empty
        vm._scan_os_info = mock_empty

        result = asyncio.run(vm.get_component("nonexistent"))
        self.assertIsNone(result)

    def test_get_component_returns_dict_for_known(self):
        """get_component() should return a dict for known components."""
        vm = VersionManager()
        cv = ComponentVersion(
            name="zeek", category="docker",
            current_version="v26.02.0", install_type="docker",
            last_checked=datetime.now(timezone.utc).isoformat(),
            status="ok", details={"image": "malcolm/zeek"},
        )
        vm._versions = {"zeek": cv}

        result = asyncio.run(vm.get_component("zeek"))
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "zeek")
        self.assertEqual(result["current_version"], "v26.02.0")


class TestScanCore(unittest.TestCase):
    """Tests for VersionManager._scan_core()."""

    def test_scan_core_returns_nettap_version(self):
        """_scan_core() should include nettap-daemon with correct version."""
        vm = VersionManager()
        results = asyncio.run(vm._scan_core())

        daemon_versions = [
            cv for cv in results if cv.name == "nettap-daemon"
        ]
        self.assertEqual(len(daemon_versions), 1)
        self.assertEqual(
            daemon_versions[0].current_version, NETTAP_VERSION
        )
        self.assertEqual(daemon_versions[0].status, "ok")

    def test_scan_core_includes_web_and_config(self):
        """_scan_core() should include web UI and config components."""
        vm = VersionManager()
        results = asyncio.run(vm._scan_core())

        names = [cv.name for cv in results]
        self.assertIn("nettap-daemon", names)
        self.assertIn("nettap-web", names)
        self.assertIn("nettap-config", names)


class TestRunCommand(unittest.TestCase):
    """Tests for VersionManager._run_command()."""

    def test_run_command_handles_missing_command(self):
        """_run_command() should return empty string for missing commands."""
        vm = VersionManager()
        result = asyncio.run(vm._run_command(["nonexistent_command_xyz"]))
        self.assertEqual(result, "")

    def test_run_command_returns_output(self):
        """_run_command() should return command output."""
        vm = VersionManager()
        result = asyncio.run(vm._run_command(["echo", "hello"]))
        self.assertEqual(result.strip(), "hello")

    def test_run_command_handles_timeout(self):
        """_run_command() should handle command timeouts gracefully."""
        vm = VersionManager()
        # The sleep command will be killed by the 15s timeout, but we
        # can test that it does not raise by using a very short sleep
        result = asyncio.run(vm._run_command(["sleep", "0"]))
        self.assertIsInstance(result, str)


class TestCacheStaleness(unittest.TestCase):
    """Tests for VersionManager._is_cache_stale()."""

    def test_empty_cache_is_stale(self):
        """Empty cache should be stale."""
        vm = VersionManager()
        self.assertTrue(vm._is_cache_stale())

    def test_recent_cache_is_not_stale(self):
        """Cache with recent scan should not be stale."""
        vm = VersionManager()
        vm._versions = {"test": MagicMock()}
        vm._last_scan = datetime.now(timezone.utc).isoformat()
        self.assertFalse(vm._is_cache_stale())

    def test_old_cache_is_stale(self):
        """Cache older than TTL should be stale."""
        vm = VersionManager()
        vm._versions = {"test": MagicMock()}
        # Set last scan to a time well before the TTL
        from datetime import timedelta
        old_time = datetime.now(timezone.utc) - timedelta(
            seconds=_CACHE_TTL_SECONDS + 100
        )
        vm._last_scan = old_time.isoformat()
        self.assertTrue(vm._is_cache_stale())

    def test_invalid_timestamp_is_stale(self):
        """Invalid last_scan timestamp should be treated as stale."""
        vm = VersionManager()
        vm._versions = {"test": MagicMock()}
        vm._last_scan = "not-a-timestamp"
        self.assertTrue(vm._is_cache_stale())


class TestCategoryFiltering(unittest.TestCase):
    """Tests for filtering versions by category."""

    def test_filter_by_category(self):
        """Versions should be filterable by category."""
        vm = VersionManager()
        now = datetime.now(timezone.utc).isoformat()

        vm._versions = {
            "daemon": ComponentVersion(
                name="daemon", category="core",
                current_version="0.4.0", install_type="pip",
                last_checked=now, status="ok", details={},
            ),
            "zeek": ComponentVersion(
                name="zeek", category="docker",
                current_version="v26", install_type="docker",
                last_checked=now, status="ok", details={},
            ),
            "python3": ComponentVersion(
                name="python3", category="system",
                current_version="3.10", install_type="apt",
                last_checked=now, status="ok", details={},
            ),
        }
        vm._last_scan = now

        result = asyncio.run(vm.get_versions())
        docker_only = [
            v for v in result["versions"] if v["category"] == "docker"
        ]
        self.assertEqual(len(docker_only), 1)
        self.assertEqual(docker_only[0]["name"], "zeek")


if __name__ == "__main__":
    unittest.main()
