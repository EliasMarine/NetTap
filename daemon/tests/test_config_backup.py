"""
Tests for the ConfigBackup service.

Covers: export completeness, import validation, version compatibility,
section writing, round-trip export/import.
"""

import json
from pathlib import Path

import pytest

from services.config_backup import ConfigBackup, _SCHEMA_VERSION, _NETTAP_VERSION


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config_paths(tmp_path):
    """Create temp config files and return the paths dict."""
    paths = {
        "notification_config": str(tmp_path / "notifications.json"),
        "device_baseline": str(tmp_path / "device_baseline.json"),
        "excluded_ips": str(tmp_path / "excluded_ips.json"),
        "env_file": str(tmp_path / ".env"),
        "bandwidth_cap": str(tmp_path / "bandwidth_cap.json"),
        "capture_config": str(tmp_path / "capture_config.json"),
        "retention_config": str(tmp_path / "retention_config.json"),
    }

    # Write sample config files
    (tmp_path / "notifications.json").write_text(json.dumps({
        "channels": {
            "ch1": {"type": "email", "config": {"to": "admin@test.com"}},
        },
        "rules": {
            "r1": {"event_type": "alert", "channel": "ch1"},
        },
    }))

    (tmp_path / "device_baseline.json").write_text(json.dumps({
        "aliases": {"00:11:22:33:44:55": "My Laptop"},
        "devices": [],
    }))

    (tmp_path / "excluded_ips.json").write_text(json.dumps([
        "192.168.1.1", "10.0.0.1"
    ]))

    (tmp_path / "bandwidth_cap.json").write_text(json.dumps({
        "monthly_cap_gb": 1000,
        "enabled": True,
    }))

    (tmp_path / "capture_config.json").write_text(json.dumps({
        "mode": "bridge",
        "interfaces": ["eth0", "eth1"],
    }))

    (tmp_path / "retention_config.json").write_text(json.dumps({
        "hot_days": 90,
        "warm_days": 180,
        "cold_days": 30,
    }))

    return paths


@pytest.fixture
def backup(config_paths):
    """Return a ConfigBackup with temp config paths."""
    return ConfigBackup(config_paths=config_paths)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_has_metadata(self, backup):
        """Export should include version and timestamp metadata."""
        config = backup.export_config()

        assert "metadata" in config
        assert config["metadata"]["nettap_version"] == _NETTAP_VERSION
        assert config["metadata"]["schema_version"] == _SCHEMA_VERSION
        assert "exported_at" in config["metadata"]

    def test_export_has_all_sections(self, backup):
        """Export should include all configuration sections."""
        config = backup.export_config()
        sections = config["sections"]

        assert "capture_mode_config" in sections
        assert "storage_retention" in sections
        assert "notification_channels" in sections
        assert "notification_rules" in sections
        assert "device_aliases" in sections
        assert "excluded_ips" in sections
        assert "bandwidth_cap" in sections

    def test_export_correct_values(self, backup):
        """Export should contain the actual config values."""
        config = backup.export_config()
        sections = config["sections"]

        assert sections["excluded_ips"] == ["192.168.1.1", "10.0.0.1"]
        assert sections["bandwidth_cap"]["monthly_cap_gb"] == 1000
        assert sections["device_aliases"] == {"00:11:22:33:44:55": "My Laptop"}
        assert "ch1" in sections["notification_channels"]

    def test_export_missing_files(self, tmp_path):
        """Export should use defaults for missing config files."""
        paths = {
            "notification_config": str(tmp_path / "nonexistent.json"),
        }
        b = ConfigBackup(config_paths=paths)
        config = b.export_config()

        # Should not crash, should have empty defaults
        assert config["sections"]["notification_channels"] == {}


# ---------------------------------------------------------------------------
# Validate import
# ---------------------------------------------------------------------------


class TestValidateImport:
    def test_valid_data(self, backup):
        """Valid import data should pass validation."""
        data = {
            "metadata": {
                "nettap_version": _NETTAP_VERSION,
                "schema_version": _SCHEMA_VERSION,
            },
            "sections": {
                "excluded_ips": ["1.2.3.4"],
            },
        }
        result = backup.validate_import(data)
        assert result["is_valid"] is True
        assert len(result["errors"]) == 0

    def test_non_dict_data(self, backup):
        """Non-dict data should fail validation."""
        result = backup.validate_import("not a dict")
        assert result["is_valid"] is False

    def test_missing_metadata_still_valid(self, backup):
        """Missing metadata defaults to empty — still valid but may warn."""
        result = backup.validate_import({"sections": {}})
        assert result["is_valid"] is True

    def test_missing_sections_still_valid(self, backup):
        """Missing sections defaults to empty — valid with warning."""
        result = backup.validate_import({
            "metadata": {"schema_version": 1, "nettap_version": "0.4.0"},
        })
        assert result["is_valid"] is True

    def test_newer_schema_version(self, backup):
        """Schema version newer than supported should fail."""
        data = {
            "metadata": {
                "nettap_version": _NETTAP_VERSION,
                "schema_version": _SCHEMA_VERSION + 10,
            },
            "sections": {},
        }
        result = backup.validate_import(data)
        assert result["is_valid"] is False
        assert any("newer" in e for e in result["errors"])

    def test_different_nettap_version_warns(self, backup):
        """Different NetTap version should produce a warning."""
        data = {
            "metadata": {
                "nettap_version": "99.99.99",
                "schema_version": _SCHEMA_VERSION,
            },
            "sections": {"excluded_ips": []},
        }
        result = backup.validate_import(data)
        assert result["is_valid"] is True
        assert len(result["warnings"]) > 0

    def test_unknown_section_warns(self, backup):
        """Unknown sections should produce a warning."""
        data = {
            "metadata": {
                "nettap_version": _NETTAP_VERSION,
                "schema_version": _SCHEMA_VERSION,
            },
            "sections": {"unknown_section": {}},
        }
        result = backup.validate_import(data)
        assert result["is_valid"] is True
        assert any("unknown" in w.lower() for w in result["warnings"])

    def test_preview_included(self, backup):
        """Validation should include preview of importable sections."""
        data = {
            "metadata": {
                "nettap_version": _NETTAP_VERSION,
                "schema_version": _SCHEMA_VERSION,
            },
            "sections": {
                "excluded_ips": ["1.2.3.4", "5.6.7.8"],
                "bandwidth_cap": {"monthly_cap_gb": 500},
            },
        }
        result = backup.validate_import(data)
        assert "excluded_ips" in result["preview"]
        assert result["preview"]["excluded_ips"]["size"] == 2


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


class TestImport:
    def test_import_applies_sections(self, backup, config_paths):
        """Import should write sections to their config files."""
        data = {
            "metadata": {
                "nettap_version": _NETTAP_VERSION,
                "schema_version": _SCHEMA_VERSION,
            },
            "sections": {
                "excluded_ips": ["10.10.10.10"],
                "bandwidth_cap": {"monthly_cap_gb": 500, "enabled": False},
            },
        }

        result = backup.import_config(data)

        assert result["success"] is True
        assert "excluded_ips" in result["applied"]
        assert "bandwidth_cap" in result["applied"]

        # Verify files were written
        ips = json.loads(Path(config_paths["excluded_ips"]).read_text())
        assert ips == ["10.10.10.10"]

        cap = json.loads(Path(config_paths["bandwidth_cap"]).read_text())
        assert cap["monthly_cap_gb"] == 500

    def test_import_no_sections(self, backup):
        """Import with no sections should succeed but apply nothing."""
        result = backup.import_config({"metadata": {"schema_version": 1, "nettap_version": "0.4.0"}, "sections": {}})
        assert result["success"] is True
        assert result["applied"] == []

    def test_import_non_dict_fails(self, backup):
        """Import with non-dict data should fail validation."""
        result = backup.import_config("not a dict")
        assert result["success"] is False

    def test_import_notification_config(self, backup, config_paths):
        """Import should merge notification channels and rules."""
        data = {
            "metadata": {
                "nettap_version": _NETTAP_VERSION,
                "schema_version": _SCHEMA_VERSION,
            },
            "sections": {
                "notification_channels": {
                    "ch2": {"type": "discord", "config": {}},
                },
                "notification_rules": {
                    "r2": {"event_type": "new_device", "channel": "ch2"},
                },
            },
        }

        result = backup.import_config(data)
        assert result["success"] is True

        notif = json.loads(Path(config_paths["notification_config"]).read_text())
        assert "ch2" in notif["channels"]
        assert "r2" in notif["rules"]

    def test_round_trip(self, backup):
        """Export then import should preserve data."""
        exported = backup.export_config()
        result = backup.import_config(exported)
        assert result["success"] is True

        # Re-export and compare sections
        re_exported = backup.export_config()
        for key in exported["sections"]:
            assert re_exported["sections"][key] == exported["sections"][key]
