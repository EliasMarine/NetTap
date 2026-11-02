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
            "component",
            "current_version",
            "latest_version",
            "update_type",
            "release_url",
            "release_date",
            "changelog",
            "size_mb",
            "requires_restart",
            "applies_with",
        }
        self.assertEqual(set(d.keys()), expected_keys)
        self.assertIsNone(d["applies_with"])  # applicable unless a check says otherwise

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

        async def mock_docker(current_versions, images):
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
        result = asyncio.run(self.uc._compare_versions("1.0.0-alpha", "1.0.0"))
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

    def test_fetch_json_raises_on_network_error(self):
        """#96: a failed request is an error, not an empty answer."""
        uc = UpdateChecker()
        # Use an unreachable URL to test error handling
        with self.assertRaises(Exception):
            asyncio.run(uc._fetch_json("http://192.0.2.1:99999/test"))

    def test_fetch_json_raises_on_invalid_url(self):
        uc = UpdateChecker()
        with self.assertRaises(Exception):
            asyncio.run(uc._fetch_json("not-a-url"))


class TestFailedChecksAreReported(unittest.TestCase):
    """#96: a source that couldn't be asked is listed, never read as "up to date"."""

    def _checker(self, fetch):
        uc = UpdateChecker()
        uc._fetch_json = fetch

        async def none():
            return None

        uc._check_suricata_rules = none
        uc._check_geoip_update = none
        return uc

    def test_github_failure_listed(self):
        async def offline(url):
            raise RuntimeError("HTTP 403 from github")

        uc = self._checker(offline)
        result = asyncio.run(uc.check_updates())
        self.assertEqual(result["failed_checks"], ["nettap-daemon"])
        self.assertEqual(
            asyncio.run(uc.get_available())["failed_checks"], ["nettap-daemon"]
        )

    def test_no_release_published_is_not_a_failure(self):
        async def not_found(url):
            return {}

        result = asyncio.run(self._checker(not_found).check_updates())
        self.assertEqual(result["failed_checks"], [])
        self.assertFalse(result["has_updates"])

    # OLD CODE START — #96: containers are no longer checked on Docker Hub
    # def test_docker_hub_failure_listed(self):
    #     ... Docker Hub HTTP 500 for zeek -> failed_checks == ["zeek"]
    # OLD CODE END

    @staticmethod
    def _vm(*containers):
        class VM:
            async def get_versions(self):
                return {
                    "versions": [
                        {
                            "name": name,
                            "category": "docker",
                            "current_version": image.rsplit(":", 1)[-1],
                            "status": "ok",
                            "details": {"image": image},
                        }
                        for name, image in containers
                    ]
                }

        return VM()

    def test_malcolm_release_failure_listed(self):
        async def fetch(url):
            if "idaholab/Malcolm" in url:
                raise RuntimeError("HTTP 500")
            return {}

        uc = self._checker(fetch)
        uc.set_version_manager(
            self._vm(("suricata", "ghcr.io/idaholab/malcolm/suricata:26.02.0"))
        )
        result = asyncio.run(uc.check_updates())
        self.assertEqual(result["failed_checks"], ["suricata"])

    def test_docker_unavailable_listed(self):
        async def not_found(url):
            return {}

        class VM:
            async def get_versions(self):
                return {
                    "versions": [
                        {"name": "docker", "category": "docker", "status": "error",
                         "current_version": "unknown", "details": {"error": "x"}}
                    ]
                }

        uc = self._checker(not_found)
        uc.set_version_manager(VM())
        self.assertEqual(asyncio.run(uc.check_updates())["failed_checks"], ["docker"])

    def test_version_lookup_failure_listed(self):
        async def not_found(url):
            return {}

        uc = self._checker(not_found)

        class VM:
            async def get_versions(self):
                raise OSError("docker unavailable")

        uc.set_version_manager(VM())
        result = asyncio.run(uc.check_updates())
        self.assertEqual(result["failed_checks"], ["component-versions"])


class TestContainerImagesCheckedAtTheirSource(unittest.TestCase):
    """#96: the deployed images (ghcr.io/idaholab/malcolm) are compared with Malcolm's
    releases; Docker Hub malcolm/* could never find an update."""

    def _run(self, release, containers):
        urls = []

        async def fetch(url):
            urls.append(url)
            return release if "idaholab/Malcolm" in url else {}

        uc = UpdateChecker()
        uc._fetch_json = fetch

        async def none():
            return None

        uc._check_suricata_rules = none
        uc._check_geoip_update = none
        uc.set_version_manager(TestFailedChecksAreReported._vm(*containers))
        return asyncio.run(uc.check_updates()), urls

    def test_newer_malcolm_release_is_an_update(self):
        result, urls = self._run(
            {"tag_name": "v26.03.0", "html_url": "https://github.com/idaholab/Malcolm"},
            [
                ("suricata", "ghcr.io/idaholab/malcolm/suricata:26.02.0"),
                ("opensearch", "ghcr.io/idaholab/malcolm/opensearch:26.02.0"),
            ],
        )
        by_component = {u["component"]: u for u in result["updates"]}
        self.assertEqual(set(by_component), {"suricata", "opensearch"})
        self.assertEqual(by_component["suricata"]["latest_version"], "26.03.0")
        self.assertEqual(by_component["suricata"]["update_type"], "minor")
        self.assertIsNone(by_component["suricata"]["size_mb"])
        self.assertEqual(result["failed_checks"], [])
        self.assertFalse(any("hub.docker.com" in u for u in urls))

    def test_same_release_is_up_to_date(self):
        result, _ = self._run(
            {"tag_name": "v26.02.0"},
            [("suricata", "ghcr.io/idaholab/malcolm/suricata:26.02.0")],
        )
        self.assertEqual((result["updates"], result["failed_checks"]), ([], []))

    def test_nettap_images_skipped_others_cant_be_checked(self):
        result, _ = self._run(
            {"tag_name": "v26.02.0"},
            [
                ("nettap-web", "nettap/web:latest"),
                ("nettap-grafana", "grafana/grafana:10.4.2"),
            ],
        )
        self.assertEqual(result["failed_checks"], ["nettap-grafana"])

    def test_unparseable_tag_cant_be_checked(self):
        result, _ = self._run(
            {"tag_name": "v26.03.0"},
            [("arkime", "ghcr.io/idaholab/malcolm/arkime:latest")],
        )
        self.assertEqual(result["failed_checks"], ["arkime"])
        self.assertEqual(result["updates"], [])

    def test_malcolm_update_comes_with_nettap_release(self):
        """Malcolm's images are pinned: NetTap can't apply a newer release itself."""
        result, _ = self._run(
            {"tag_name": "v26.03.0"},
            [("suricata", "ghcr.io/idaholab/malcolm/suricata:26.02.0")],
        )
        (update,) = result["updates"]
        self.assertEqual(
            update["applies_with"],
            "Comes with NetTap's pinned Malcolm release: update NetTap to get it.",
        )

    def test_says_which_components_it_checked(self):
        """The Updates page read "Up to Date" for the OS, Docker and Python, which nothing checks."""
        result, _ = self._run(
            {"tag_name": "v26.02.0"},
            [
                ("logstash", "ghcr.io/idaholab/malcolm/logstash:26.02.0"),
                ("nettap-web", "nettap/web:latest"),
                ("nettap-nginx", "nginx:stable-alpine"),
            ],
        )
        self.assertEqual(result["checked"], ["geoip-db", "logstash", "nettap-daemon", "nettap-web", "suricata-rules"])
        self.assertNotIn("nettap-nginx", result["checked"])


class TestNetTapImagesFollowTheRelease(unittest.TestCase):
    """NetTap's images (nettap-web, nettap-tshark...) read "Up to Date" beside a newer NetTap
    release or a failed release check: nothing compares them but that check."""

    def _checked(self, release):
        uc = UpdateChecker()

        async def fetch(url):
            if isinstance(release, Exception):
                raise release
            return release if "EliasMarine" in url else {}

        async def none():
            return None

        uc._fetch_json = fetch
        uc._check_suricata_rules = none
        uc._check_geoip_update = none
        uc.set_version_manager(TestFailedChecksAreReported._vm(("nettap-web", "nettap/web:latest")))
        return asyncio.run(uc.check_updates())["checked"]

    def test_no_newer_release_means_checked(self):
        self.assertIn("nettap-web", self._checked({}))

    def test_a_newer_release_is_not_up_to_date(self):
        self.assertNotIn("nettap-web", self._checked({"tag_name": "v99.0.0", "html_url": ""}))

    def test_a_failed_release_check_is_not_up_to_date(self):
        self.assertNotIn("nettap-web", self._checked(RuntimeError("HTTP 403 rate limited")))


class TestNetTapUpdatesStayApplicable(unittest.TestCase):
    """Updates NetTap applies itself carry no applies_with sentence; the rest say how they arrive."""

    # OLD CODE START — a NetTap release was offered as applicable, and the executor
    # answered "Unsupported component for update: nettap-daemon"
    # def test_nettap_release_is_applicable(self):
    #     ...
    #     self.assertIsNone(update.applies_with)
    # OLD CODE END
    def test_nettap_release_says_how_to_get_it(self):
        from services.update_checker import NETTAP_APPLIES_WITH

        async def fetch(url):
            return {"tag_name": "v99.0.0", "html_url": "https://github.com/x"}

        uc = UpdateChecker()
        uc._fetch_json = fetch
        (update,) = asyncio.run(uc._check_github_releases())
        self.assertEqual(update.component, "nettap-daemon")
        self.assertEqual(update.applies_with, NETTAP_APPLIES_WITH)

    def test_stale_suricata_rules_are_applicable(self):
        from unittest.mock import patch

        month_old = datetime.now(timezone.utc).timestamp() - 30 * 86400
        with (
            patch("os.path.exists", return_value=True),
            patch("os.path.getmtime", return_value=month_old),
        ):
            update = asyncio.run(UpdateChecker()._check_suricata_rules())
        self.assertEqual(update.component, "suricata-rules")
        self.assertIsNone(update.applies_with)


class TestRulesAreReadInTheSuricataContainer(unittest.TestCase):
    """The daemon container has no rules file: the check found none and read as current."""

    def _check(self, live):
        from unittest.mock import AsyncMock, patch

        uc = UpdateChecker()
        with (
            patch("os.path.exists", return_value=False),
            patch("services.update_checker.SuricataRuleManager.get_live_status", AsyncMock(return_value=live)),
        ):
            return asyncio.run(uc._check_suricata_rules()), uc._failed_checks

    def test_stale_rules_in_the_container_are_an_update(self):
        update, failed = self._check({"available": True, "last_updated": "2026-01-02T00:00:00+00:00"})
        self.assertEqual((update.component, update.current_version), ("suricata-rules", "2026-01-02"))
        self.assertFalse(update.requires_restart)  # the update reloads them
        self.assertEqual(failed, [])

    def test_unreadable_rules_are_a_failed_check(self):
        update, failed = self._check({"available": False, "error": "Could not reach the Suricata container."})
        self.assertIsNone(update)
        self.assertEqual(failed, ["suricata-rules"])

    def test_a_failed_check_is_not_listed_as_checked(self):
        uc = UpdateChecker()

        async def unreadable():
            uc._failed_checks.append("suricata-rules")

        async def nothing():
            return []

        async def none():
            return None

        uc._check_suricata_rules = unreadable
        uc._check_github_releases = nothing
        uc._check_geoip_update = none
        result = asyncio.run(uc.check_updates())
        self.assertEqual(result["failed_checks"], ["suricata-rules"])
        self.assertNotIn("suricata-rules", result["checked"])


class TestEstimateReleaseSize(unittest.TestCase):
    """Tests for UpdateChecker._estimate_release_size()."""

    def test_with_assets(self):
        """Should calculate size from asset sizes."""
        data = {
            "assets": [
                {"size": 1024 * 1024 * 10},  # 10 MB
                {"size": 1024 * 1024 * 5},  # 5 MB
            ]
        }
        result = UpdateChecker._estimate_release_size(data)
        self.assertAlmostEqual(result, 15.0, places=0)

    def test_without_assets_size_is_unknown(self):
        """#96: no assets means the size isn't known, not a made-up 50 MB."""
        self.assertIsNone(UpdateChecker._estimate_release_size({}))

    def test_empty_assets_list_size_is_unknown(self):
        self.assertIsNone(UpdateChecker._estimate_release_size({"assets": []}))


class TestStaleDatabaseSizeIsUnknown(unittest.TestCase):
    """#96: rule and GeoIP update sizes were approximations shown as figures."""

    def test_rules_and_geoip_sizes_are_none(self):
        from unittest.mock import patch

        month_old = datetime.now(timezone.utc).timestamp() - 30 * 86400
        uc = UpdateChecker()
        with (
            patch("os.path.exists", return_value=True),
            patch("os.path.getmtime", return_value=month_old),
        ):
            rule_update = asyncio.run(uc._check_suricata_rules())
            geoip_update = asyncio.run(uc._check_geoip_update())

        self.assertIsNone(rule_update.size_mb)
        self.assertIsNone(geoip_update.size_mb)


class TestGeoIPDatabaseInLogstash(unittest.TestCase):
    """With no local database, the one enrichment actually uses (bundled in the Logstash
    container) is checked; before, the check said "no update" without looking."""

    G11_DB_MTIME = 1769552063  # 2026-01-27, the bundled database on the G11

    def _check(self, mtime=None, returncode=0, raises=None, local_db=False):
        """Run the GeoIP check; docker exec prints mtime (or fails). Returns
        (update, failed_checks, docker exec argv or None)."""
        from unittest.mock import patch

        calls = []

        class Proc:
            def __init__(self):
                self.returncode = returncode

            async def communicate(self):
                out = b"" if mtime is None else f"{mtime}\n".encode()
                return out, b"" if returncode == 0 else b"No such container"

        async def exec_(*argv, **kwargs):
            calls.append(argv)
            if raises:
                raise raises
            return Proc()

        uc = UpdateChecker()
        with (
            patch("os.path.exists", return_value=local_db),
            patch("os.path.getmtime", return_value=mtime or 0),
            patch("asyncio.create_subprocess_exec", exec_),
        ):
            update = asyncio.run(uc._check_geoip_update())
        return update, uc._failed_checks, (calls[0] if calls else None)

    def test_old_bundled_database_is_an_update_that_comes_with_nettap(self):
        update, failed, argv = self._check(mtime=self.G11_DB_MTIME)
        self.assertEqual(argv[:5], ("docker", "exec", "nettap-logstash", "sh", "-c"))
        self.assertIn("stat -c %Y /usr/share/logstash/vendor/bundle/jruby/*/gems/", argv[5])
        self.assertTrue(argv[5].endswith("logstash-filter-geoip-*/vendor/GeoLite2-City.mmdb"))
        self.assertEqual(update.component, "geoip-db")
        self.assertEqual(update.current_version, "2026-01-27")
        self.assertEqual(
            update.applies_with,
            "Comes with Malcolm's Logstash image: update NetTap to get a newer one.",
        )
        self.assertEqual(failed, [])

    def test_unreadable_container_is_a_failed_check_not_no_update(self):
        for case in ({"returncode": 1}, {"raises": FileNotFoundError("docker")}):
            with self.subTest(**case):
                update, failed, _ = self._check(**case)
                self.assertIsNone(update)
                self.assertEqual(failed, ["geoip-db"])

    def test_failed_geoip_check_reaches_the_update_result(self):
        from unittest.mock import patch

        async def not_found(url):
            return {}

        async def none():
            return None

        async def unreadable():
            raise RuntimeError("No such container: nettap-logstash")

        uc = UpdateChecker()
        uc._fetch_json = not_found
        uc._check_suricata_rules = none
        uc._logstash_geoip_mtime = unreadable
        with patch("os.path.exists", return_value=False):
            result = asyncio.run(uc.check_updates())
        self.assertEqual(result["failed_checks"], ["geoip-db"])

    def test_fresh_bundled_database_is_no_update(self):
        two_days_old = datetime.now(timezone.utc).timestamp() - 2 * 86400
        update, failed, _ = self._check(mtime=two_days_old)
        self.assertIsNone(update)
        self.assertEqual(failed, [])

    def test_fresh_local_database_is_no_update_and_logstash_is_not_asked(self):
        two_days_old = datetime.now(timezone.utc).timestamp() - 2 * 86400
        update, failed, argv = self._check(mtime=two_days_old, local_db=True)
        self.assertIsNone(update)
        self.assertEqual(failed, [])
        self.assertIsNone(argv)

    def test_stale_local_database_stays_applicable(self):
        update, _, argv = self._check(mtime=self.G11_DB_MTIME, local_db=True)
        self.assertEqual(update.component, "geoip-db")
        self.assertIsNone(update.applies_with)
        self.assertIsNone(argv)


if __name__ == "__main__":
    unittest.main()
