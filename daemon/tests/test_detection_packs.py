"""
Tests for daemon/services/detection_packs.py

Covers pack installation, uninstallation, enable/disable, listing,
update checking, statistics, and edge cases. All tests are self-contained
with no external dependencies.
"""

import os
import unittest

import sys

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.detection_packs import (
    DetectionPack,
    DetectionPackManager,
    BUILTIN_PACK_DEFS,
    VALID_CATEGORIES,
)


class TestDetectionPackDataclass(unittest.TestCase):
    """Tests for the DetectionPack dataclass."""

    def test_pack_creation(self):
        """A DetectionPack can be created with all fields."""
        pack = DetectionPack(
            id="test-pack",
            name="Test Pack",
            description="A test pack",
            version="1.0.0",
            author="Tester",
            rule_count=100,
            enabled=True,
            installed_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
            category="custom",
            tags=["test"],
            source_url="https://example.com",
        )
        self.assertEqual(pack.id, "test-pack")
        self.assertEqual(pack.name, "Test Pack")

    def test_pack_to_dict(self):
        """to_dict() returns a serializable dictionary."""
        pack = DetectionPack(
            id="test",
            name="Test",
            description="Desc",
            version="1.0",
            author="Author",
            rule_count=10,
            enabled=True,
            installed_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
            category="custom",
            tags=["a", "b"],
            source_url="",
        )
        d = pack.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["id"], "test")
        self.assertEqual(d["tags"], ["a", "b"])

    def test_pack_default_tags(self):
        """Default tags is an empty list."""
        pack = DetectionPack(
            id="t", name="T", description="", version="1",
            author="A", rule_count=0, enabled=False,
            installed_at="", updated_at="", category="custom",
        )
        self.assertEqual(pack.tags, [])
        self.assertEqual(pack.source_url, "")


class TestDetectionPackManagerInit(unittest.TestCase):
    """Tests for DetectionPackManager initialization."""

    def test_init_with_missing_dir(self):
        """Manager starts empty when directory does not exist."""
        manager = DetectionPackManager(packs_dir="/tmp/nonexistent-packs-dir-test")
        self.assertEqual(len(manager.list_packs()), 0)

    def test_init_with_temp_dir(self, ):
        """Manager can be initialized with a temp directory."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DetectionPackManager(packs_dir=tmpdir)
            self.assertEqual(len(manager.list_packs()), 0)

    def test_persistence_round_trip(self):
        """Installed packs survive reload from disk."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DetectionPackManager(packs_dir=tmpdir)
            manager.install_pack("et-open")

            # Create a new manager pointing to the same dir
            manager2 = DetectionPackManager(packs_dir=tmpdir)
            self.assertEqual(len(manager2.list_packs()), 1)
            self.assertEqual(manager2.list_packs()[0].id, "et-open")


class TestInstallPack(unittest.TestCase):
    """Tests for install_pack()."""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.manager = DetectionPackManager(packs_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_install_et_open(self):
        """Install the Emerging Threats Open pack."""
        pack = self.manager.install_pack("et-open")
        self.assertEqual(pack.id, "et-open")
        self.assertEqual(pack.name, "Emerging Threats Open")
        self.assertTrue(pack.enabled)
        self.assertGreater(pack.rule_count, 0)

    def test_install_et_iot(self):
        """Install the ET IoT Ruleset."""
        pack = self.manager.install_pack("et-iot")
        self.assertEqual(pack.id, "et-iot")
        self.assertEqual(pack.category, "iot")

    def test_install_abuse_ch(self):
        """Install the abuse.ch pack."""
        pack = self.manager.install_pack("abuse-ch")
        self.assertEqual(pack.id, "abuse-ch")

    def test_install_tgreen_hunting(self):
        """Install the TGreen Hunting Rules."""
        pack = self.manager.install_pack("tgreen-hunting")
        self.assertEqual(pack.id, "tgreen-hunting")

    def test_install_nettap_defaults(self):
        """Install the NetTap Default Rules."""
        pack = self.manager.install_pack("nettap-defaults")
        self.assertEqual(pack.id, "nettap-defaults")

    def test_install_already_installed_raises(self):
        """Installing an already-installed pack raises ValueError."""
        self.manager.install_pack("et-open")
        with self.assertRaises(ValueError) as ctx:
            self.manager.install_pack("et-open")
        self.assertIn("already installed", str(ctx.exception))

    def test_install_unknown_pack_raises(self):
        """Installing an unknown pack ID raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.manager.install_pack("nonexistent-pack")
        self.assertIn("Unknown pack ID", str(ctx.exception))

    def test_installed_pack_has_timestamps(self):
        """Installed packs have installed_at and updated_at set."""
        pack = self.manager.install_pack("et-open")
        self.assertTrue(len(pack.installed_at) > 0)
        self.assertTrue(len(pack.updated_at) > 0)


class TestUninstallPack(unittest.TestCase):
    """Tests for uninstall_pack()."""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.manager = DetectionPackManager(packs_dir=self.tmpdir)
        self.manager.install_pack("et-open")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_uninstall_installed_pack(self):
        """Uninstalling an installed pack returns True."""
        result = self.manager.uninstall_pack("et-open")
        self.assertTrue(result)
        self.assertEqual(len(self.manager.list_packs()), 0)

    def test_uninstall_nonexistent_pack(self):
        """Uninstalling a non-existent pack returns False."""
        result = self.manager.uninstall_pack("nonexistent")
        self.assertFalse(result)

    def test_uninstall_persists(self):
        """Uninstall is persisted to disk."""
        self.manager.uninstall_pack("et-open")
        manager2 = DetectionPackManager(packs_dir=self.tmpdir)
        self.assertEqual(len(manager2.list_packs()), 0)


class TestEnableDisablePack(unittest.TestCase):
    """Tests for enable_pack() and disable_pack()."""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.manager = DetectionPackManager(packs_dir=self.tmpdir)
        self.manager.install_pack("et-open")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_disable_pack(self):
        """Disabling a pack sets enabled=False."""
        result = self.manager.disable_pack("et-open")
        self.assertTrue(result)
        pack = self.manager.get_pack("et-open")
        self.assertFalse(pack.enabled)

    def test_enable_pack(self):
        """Enabling a disabled pack sets enabled=True."""
        self.manager.disable_pack("et-open")
        result = self.manager.enable_pack("et-open")
        self.assertTrue(result)
        pack = self.manager.get_pack("et-open")
        self.assertTrue(pack.enabled)

    def test_disable_nonexistent_pack(self):
        """Disabling a non-existent pack returns False."""
        result = self.manager.disable_pack("nonexistent")
        self.assertFalse(result)

    def test_enable_nonexistent_pack(self):
        """Enabling a non-existent pack returns False."""
        result = self.manager.enable_pack("nonexistent")
        self.assertFalse(result)


class TestListAndGetPack(unittest.TestCase):
    """Tests for list_packs() and get_pack()."""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.manager = DetectionPackManager(packs_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_list_empty(self):
        """list_packs() returns empty list when nothing installed."""
        self.assertEqual(self.manager.list_packs(), [])

    def test_list_after_install(self):
        """list_packs() returns installed packs."""
        self.manager.install_pack("et-open")
        self.manager.install_pack("et-iot")
        packs = self.manager.list_packs()
        self.assertEqual(len(packs), 2)

    def test_get_existing_pack(self):
        """get_pack() returns the pack if installed."""
        self.manager.install_pack("et-open")
        pack = self.manager.get_pack("et-open")
        self.assertIsNotNone(pack)
        self.assertEqual(pack.id, "et-open")

    def test_get_nonexistent_pack(self):
        """get_pack() returns None for unknown ID."""
        pack = self.manager.get_pack("nonexistent")
        self.assertIsNone(pack)


class TestCheckUpdates(unittest.TestCase):
    """Tests for check_updates()."""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.manager = DetectionPackManager(packs_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_check_updates_returns_empty_list(self):
        """check_updates() returns empty list (placeholder)."""
        updates = self.manager.check_updates()
        self.assertEqual(updates, [])
        self.assertIsInstance(updates, list)


class TestGetStats(unittest.TestCase):
    """Tests for get_stats()."""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.manager = DetectionPackManager(packs_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_stats_empty(self):
        """Stats with no packs installed."""
        stats = self.manager.get_stats()
        self.assertEqual(stats["total_packs"], 0)
        self.assertEqual(stats["enabled_packs"], 0)
        self.assertEqual(stats["total_rules"], 0)

    def test_stats_with_installed_packs(self):
        """Stats with packs installed."""
        self.manager.install_pack("et-open")
        self.manager.install_pack("et-iot")
        stats = self.manager.get_stats()
        self.assertEqual(stats["total_packs"], 2)
        self.assertEqual(stats["enabled_packs"], 2)
        self.assertGreater(stats["total_rules"], 0)

    def test_stats_with_disabled_pack(self):
        """Stats correctly count disabled packs."""
        self.manager.install_pack("et-open")
        self.manager.disable_pack("et-open")
        stats = self.manager.get_stats()
        self.assertEqual(stats["total_packs"], 1)
        self.assertEqual(stats["enabled_packs"], 0)
        self.assertEqual(stats["disabled_packs"], 1)

    def test_stats_has_by_category(self):
        """Stats include by_category breakdown."""
        self.manager.install_pack("et-open")
        self.manager.install_pack("et-iot")
        stats = self.manager.get_stats()
        self.assertIn("by_category", stats)
        self.assertIn("malware", stats["by_category"])
        self.assertIn("iot", stats["by_category"])

    def test_stats_enabled_rules(self):
        """enabled_rules counts only rules from enabled packs."""
        self.manager.install_pack("et-open")
        self.manager.install_pack("et-iot")
        self.manager.disable_pack("et-iot")
        stats = self.manager.get_stats()
        et_open_rules = self.manager.get_pack("et-open").rule_count
        self.assertEqual(stats["enabled_rules"], et_open_rules)


class TestGetAvailablePacks(unittest.TestCase):
    """Tests for get_available_packs()."""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.manager = DetectionPackManager(packs_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_all_available_before_install(self):
        """All builtin packs are available before any install."""
        available = self.manager.get_available_packs()
        self.assertEqual(len(available), len(BUILTIN_PACK_DEFS))
        for p in available:
            self.assertFalse(p["installed"])

    def test_installed_marked_after_install(self):
        """Installed packs are marked in available list."""
        self.manager.install_pack("et-open")
        available = self.manager.get_available_packs()
        et_open = next(p for p in available if p["id"] == "et-open")
        self.assertTrue(et_open["installed"])


class TestBuiltinPacks(unittest.TestCase):
    """Tests for builtin pack definitions."""

    def test_all_builtins_have_required_fields(self):
        """Each builtin definition has all required fields."""
        required_keys = {"id", "name", "description", "version", "author",
                         "rule_count", "category", "tags"}
        for bdef in BUILTIN_PACK_DEFS:
            for key in required_keys:
                self.assertIn(key, bdef, f"Missing '{key}' in {bdef['id']}")

    def test_all_builtins_have_valid_category(self):
        """Each builtin has a valid category."""
        for bdef in BUILTIN_PACK_DEFS:
            self.assertIn(
                bdef["category"],
                VALID_CATEGORIES,
                f"Invalid category '{bdef['category']}' in {bdef['id']}",
            )

    def test_builtin_ids_unique(self):
        """All builtin pack IDs are unique."""
        ids = [b["id"] for b in BUILTIN_PACK_DEFS]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
