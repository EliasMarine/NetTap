"""
Tests for daemon/services/update_checker.py

All tests use mocks -- no real HTTP requests, Docker Hub, or GitHub
API access required. Tests cover the UpdateChecker class: update
checking, version comparison, caching, and graceful error handling.
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.update_checker import AvailableUpdate, UpdateChecker


class TestAvailableUpdateDataclass(unittest.TestCase):
    """Tests for the AvailableUpdate dataclass."""

    def test_to_dict_returns_all_fields(self):
        """to_dict() should return a dict with all expected fields."""
        update = AvailableUpdate(
            component="zeek",
            current_version="6.0.3",
            latest_version="6.0.4",
            update_type="patch",
            release_url="https://example.com/release",
            release_date="2026-02-26T12:00:00+00:00",
            changelog="Bug fixes",
            size_mb=150.0,
            requires_restart=True,
        )
        d = update.to_dict()
        expected_keys = {
            "component", "current_version", "latest_version",
            "update_type", "release_url", "release_date",
            "changelog", "size_mb", "requires_restart",
        }
        self.assertEqual(set(d.keys()), expected_keys)

    def test_to_dict_preserves_values(self):
        """to_dict() should preserve exact values."""
        update = AvailableUpdate(
            component="suricata",
            current_version="7.0.2",
            latest_version="7.0.3",
            update_type="patch",
            release_url="https://example.com",
            release_date="2026-02-20T00:00:00+00:00",
            changelog="Security fixes",
            size_mb=25.5,
            requires_restart=True,
        )
        d = update.to_dict()
        self.assertEqual(d["component"], "suricata")
        self.assertEqual(d["current_version"], "7.0.2")
        self.assertEqual(d["latest_version"], "7.0.3")
        self.assertEqual(d["update_type"], "patch")
        self.assertEqual(d["size_mb"], 25.5)
        self.assertTrue(d["requires_restart"])

    def test_to_dict_with_empty_changelog(self):
        """to_dict() should handle empty changelog."""
        update = AvailableUpdate(
            component="test",
            current_version="1.0.0",
            latest_version="1.1.0",
            update_type="minor",
            release_url="",
            release_date="",
            changelog="",
            size_mb=0.0,
            requires_restart=False,
        )
        d = update.to_dict()
        self.assertEqual(d["changelog"], "")
        self.assertFalse(d["requires_restart"])


class TestUpdateCheckerInitialization(unittest.TestCase):
    """Tests for UpdateChecker initialization."""

    def test_default_parameters(self):
        """Default init should use expected GitHub repo and TTL."""
        uc = UpdateChecker()
        self.assertEqual(uc._github_repo, "EliasMarine/NetTap")
        self.assertEqual(uc._cache_ttl, 6 * 3600)
        self.assertEqual(uc._available_updates, [])
        self.assertIsNone(uc._last_check)
        self.assertFalse(uc._checking)

    def test_custom_parameters(self):
        """Custom parameters should be stored correctly."""
        uc = UpdateChecker(
            github_repo="test/repo",
            cache_ttl_hours=12,
        )
        self.assertEqual(uc._github_repo, "test/repo")
        self.assertEqual(uc._cache_ttl, 12 * 3600)


class TestCheckUpdates(unittest.TestCase):
    """Tests for UpdateChecker.check_updates()."""

    def _make_checker_with_mocks(self, updates=None):
        """Create an UpdateChecker with mocked internal methods."""
        uc = UpdateChecker()

        async def mock_github():
            return updates or []

        async def mock_docker(current_versions):
            return []

        async def mock_rules():
            return None

        async def mock_geoip():
            return None

        uc._check_github_releases = mock_github
        uc._check_docker_updates = mock_docker
        uc._check_suricata_rules = mock_rules
        uc._check_geoip_update = mock_geoip

        return uc

    def test_check_updates_returns_dict_structure(self):
        """check_updates() should return dict with expected keys."""
        uc = self._make_checker_with_mocks()
        result = asyncio.run(uc.check_updates())

        self.assertIn("updates", result)
        self.assertIn("last_check", result)
        self.assertIn("count", result)
        self.assertIn("has_updates", result)

    def test_check_updates_empty_when_no_updates(self):
        """check_updates() should return empty list when current."""
        uc = self._make_checker_with_mocks()
        result = asyncio.run(uc.check_updates())

        self.assertEqual(result["count"], 0)
        self.assertFalse(result["has_updates"])
        self.assertEqual(result["updates"], [])

    def test_check_updates_with_available_update(self):
        """check_updates() should include found updates."""
        update = AvailableUpdate(
            component="nettap-daemon",
            current_version="0.3.0",
            latest_version="0.4.0",
            update_type="minor",
            release_url="https://github.com/EliasMarine/NetTap/releases",
            release_date="2026-02-26T00:00:00+00:00",
            changelog="New features",
            size_mb=50.0,
            requires_restart=True,
        )
        uc = self._make_checker_with_mocks(updates=[update])
        result = asyncio.run(uc.check_updates())

        self.assertEqual(result["count"], 1)
        self.assertTrue(result["has_updates"])
        self.assertEqual(result["updates"][0]["component"], "nettap-daemon")

    def test_check_updates_sets_last_check(self):
        """check_updates() should set _last_check timestamp."""
        uc = self._make_checker_with_mocks()
        asyncio.run(uc.check_updates())

        self.assertIsNotNone(uc._last_check)
        dt = datetime.fromisoformat(uc._last_check)
        self.assertIsInstance(dt, datetime)

    def test_checking_flag_reset_after_check(self):
        """_checking flag should be False after check completes."""
        uc = self._make_checker_with_mocks()
        asyncio.run(uc.check_updates())
        self.assertFalse(uc._checking)


class TestGetAvailable(unittest.TestCase):
    """Tests for UpdateChecker.get_available()."""

    def test_get_available_returns_cached(self):
        """get_available() should return cached updates."""
        uc = UpdateChecker()
        update = AvailableUpdate(
            component="zeek",
            current_version="6.0.3",
            latest_version="6.0.4",
            update_type="patch",
            release_url="",
            release_date="",
            changelog="",
            size_mb=0.0,
            requires_restart=True,
        )
        uc._available_updates = [update]
        uc._last_check = datetime.now(timezone.utc).isoformat()

        result = asyncio.run(uc.get_available())
        self.assertEqual(result["count"], 1)
        self.assertTrue(result["has_updates"])

    def test_get_available_empty_on_fresh_init(self):
        """get_available() should return empty on fresh instance."""
        uc = UpdateChecker()
        result = asyncio.run(uc.get_available())

        self.assertEqual(result["count"], 0)
        self.assertFalse(result["has_updates"])
        self.assertIsNone(result["last_check"])

    def test_get_available_returns_list(self):
        """get_available() updates field should be a list."""
        uc = UpdateChecker()
        result = asyncio.run(uc.get_available())
        self.assertIsInstance(result["updates"], list)


class TestGetUpdateFor(unittest.TestCase):
    """Tests for UpdateChecker.get_update_for()."""

    def test_get_update_for_returns_none_for_unknown(self):
        """get_update_for() should return None for unknown components."""
        uc = UpdateChecker()
        result = asyncio.run(uc.get_update_for("nonexistent"))
        self.assertIsNone(result)

    def test_get_update_for_returns_dict_for_known(self):
        """get_update_for() should return dict for known components."""
        uc = UpdateChecker()
        update = AvailableUpdate(
            component="zeek",
            current_version="6.0.3",
            latest_version="6.0.4",
            update_type="patch",
            release_url="",
            release_date="",
            changelog="",
            size_mb=0.0,
            requires_restart=True,
        )
        uc._available_updates = [update]

        result = asyncio.run(uc.get_update_for("zeek"))
        self.assertIsNotNone(result)
        self.assertEqual(result["component"], "zeek")

    def test_get_update_for_no_match_returns_none(self):
        """get_update_for() returns None when update exists but for different component."""
        uc = UpdateChecker()
        update = AvailableUpdate(
            component="zeek",
            current_version="6.0.3",
            latest_version="6.0.4",
            update_type="patch",
            release_url="",
            release_date="",
            changelog="",
            size_mb=0.0,
            requires_restart=True,
        )
        uc._available_updates = [update]

        result = asyncio.run(uc.get_update_for("suricata"))
        self.assertIsNone(result)


class TestCompareVersions(unittest.TestCase):
    """Tests for UpdateChecker._compare_versions()."""

    def setUp(self):
        self.uc = UpdateChecker()

    def test_major_update(self):
        """Major version bump should return 'major'."""
        result = asyncio.run(self.uc._compare_versions("1.2.3", "2.0.0"))
        self.assertEqual(result, "major")

    def test_minor_update(self):
        """Minor version bump should return 'minor'."""
        result = asyncio.run(self.uc._compare_versions("1.2.3", "1.3.0"))
        self.assertEqual(result, "minor")

    def test_patch_update(self):
        """Patch version bump should return 'patch'."""
        result = asyncio.run(self.uc._compare_versions("1.2.3", "1.2.4"))
        self.assertEqual(result, "patch")

    def test_same_version(self):
        """Same version should return 'same'."""
        result = asyncio.run(self.uc._compare_versions("1.2.3", "1.2.3"))
        self.assertEqual(result, "same")

    def test_current_newer_returns_same(self):
        """Current newer than latest should return 'same'."""
        result = asyncio.run(self.uc._compare_versions("2.0.0", "1.0.0"))
        self.assertEqual(result, "same")

    def test_two_part_version(self):
        """Two-part version (e.g., '1.2') should be handled."""
        result = asyncio.run(self.uc._compare_versions("1.2", "1.3"))
        self.assertEqual(result, "minor")

    def test_unparseable_returns_unknown(self):
        """Unparseable version should return 'unknown'."""
        result = asyncio.run(self.uc._compare_versions("abc", "xyz"))
        self.assertEqual(result, "unknown")

    def test_version_with_v_prefix(self):
        """Version with 'v' prefix should be handled."""
        result = asyncio.run(self.uc._compare_versions("v1.2.3", "v1.2.4"))
        self.assertEqual(result, "patch")

    def test_version_with_prerelease(self):
        """Version with pre-release suffix should parse correctly."""
        result = asyncio.run(
            self.uc._compare_versions("1.0.0-alpha", "1.0.0")
        )
        self.assertEqual(result, "same")


class TestParseVersion(unittest.TestCase):
    """Tests for UpdateChecker._parse_version()."""

    def test_full_semver(self):
        """Full semver string should parse correctly."""
        result = UpdateChecker._parse_version("1.2.3")
        self.assertEqual(result, (1, 2, 3))

    def test_two_part_version(self):
        """Two-part version should have patch = 0."""
        result = UpdateChecker._parse_version("1.2")
        self.assertEqual(result, (1, 2, 0))

    def test_one_part_version(self):
        """One-part version should have minor = patch = 0."""
        result = UpdateChecker._parse_version("3")
        self.assertEqual(result, (3, 0, 0))

    def test_v_prefix_stripped(self):
        """Leading 'v' should be stripped."""
        result = UpdateChecker._parse_version("v2.1.0")
        self.assertEqual(result, (2, 1, 0))

    def test_prerelease_stripped(self):
        """Pre-release suffix should be stripped."""
        result = UpdateChecker._parse_version("1.0.0-beta.1")
        self.assertEqual(result, (1, 0, 0))

    def test_invalid_returns_none(self):
        """Completely invalid version should return None."""
        result = UpdateChecker._parse_version("not-a-version")
        self.assertIsNone(result)


class TestFetchJson(unittest.TestCase):
    """Tests for UpdateChecker._fetch_json() error handling."""

    def test_fetch_json_handles_network_error(self):
        """_fetch_json() should return empty dict on network error."""
        uc = UpdateChecker()
        # Use an unreachable URL to test error handling
        result = asyncio.run(uc._fetch_json("http://192.0.2.1:99999/test"))
        self.assertEqual(result, {})

    def test_fetch_json_handles_invalid_url(self):
        """_fetch_json() should handle invalid URLs gracefully."""
        uc = UpdateChecker()
        result = asyncio.run(uc._fetch_json("not-a-url"))
        self.assertEqual(result, {})


class TestEstimateReleaseSize(unittest.TestCase):
    """Tests for UpdateChecker._estimate_release_size()."""

    def test_with_assets(self):
        """Should calculate size from asset sizes."""
        data = {
            "assets": [
                {"size": 1024 * 1024 * 10},  # 10 MB
                {"size": 1024 * 1024 * 5},   # 5 MB
            ]
        }
        result = UpdateChecker._estimate_release_size(data)
        self.assertAlmostEqual(result, 15.0, places=0)

    def test_without_assets(self):
        """Should return default estimate when no assets."""
        result = UpdateChecker._estimate_release_size({})
        self.assertEqual(result, 50.0)

    def test_empty_assets_list(self):
        """Should return default estimate for empty assets list."""
        result = UpdateChecker._estimate_release_size({"assets": []})
        self.assertEqual(result, 50.0)


if __name__ == "__main__":
    unittest.main()
