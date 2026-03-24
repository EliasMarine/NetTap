"""
Tests for daemon/storage/retention_config.py

Covers validate_config() range/type checks, RetentionConfigManager load/save
priority chains, atomic writes, .env sync, ILM status tracking, and
partial-update merging.

All tests use tmp_path / monkeypatch — no real filesystem side-effects.
"""

import json
import os

import pytest

from storage.retention_config import RetentionConfigManager, validate_config
from storage.manager import RetentionConfig


# =========================================================================
# validate_config — valid input
# =========================================================================


class TestValidateConfigValid:
    def test_validate_config_valid(self):
        """A complete, in-range flat config passes without error."""
        validate_config({
            "hot_days": 90,
            "warm_days": 180,
            "cold_days": 30,
            "disk_threshold_percent": 80,
            "emergency_threshold_percent": 90,
        })

    def test_validate_config_nested_format(self):
        """Nested retention.json-shaped config is accepted."""
        validate_config({
            "retention": {
                "hot_days": 60,
                "warm_days": 120,
                "cold_days": 14,
            },
            "thresholds": {
                "disk_threshold_percent": 75,
                "emergency_threshold_percent": 85,
            },
        })


# =========================================================================
# validate_config — out-of-range
# =========================================================================


class TestValidateConfigHotDays:
    def test_hot_days_too_low(self):
        """hot_days < 1 raises ValueError."""
        with pytest.raises(ValueError, match="hot_days"):
            validate_config({"hot_days": 0})

    def test_hot_days_too_high(self):
        """hot_days > 365 raises ValueError."""
        with pytest.raises(ValueError, match="hot_days"):
            validate_config({"hot_days": 366})


class TestValidateConfigWarmDays:
    def test_warm_days_too_low(self):
        """warm_days < 1 raises ValueError."""
        with pytest.raises(ValueError, match="warm_days"):
            validate_config({"warm_days": 0})

    def test_warm_days_too_high(self):
        """warm_days > 730 raises ValueError."""
        with pytest.raises(ValueError, match="warm_days"):
            validate_config({"warm_days": 731})


class TestValidateConfigColdDays:
    def test_cold_days_too_low(self):
        """cold_days < 1 raises ValueError."""
        with pytest.raises(ValueError, match="cold_days"):
            validate_config({"cold_days": 0})

    def test_cold_days_too_high(self):
        """cold_days > 365 raises ValueError."""
        with pytest.raises(ValueError, match="cold_days"):
            validate_config({"cold_days": 366})


class TestValidateConfigDiskThreshold:
    def test_disk_threshold_too_low(self):
        """disk_threshold_percent < 50 raises ValueError."""
        with pytest.raises(ValueError, match="disk_threshold_percent"):
            validate_config({"disk_threshold_percent": 49})

    def test_disk_threshold_too_high(self):
        """disk_threshold_percent > 95 raises ValueError."""
        with pytest.raises(ValueError, match="disk_threshold_percent"):
            validate_config({"disk_threshold_percent": 96})


class TestValidateConfigEmergencyThreshold:
    def test_emergency_must_exceed_disk(self):
        """emergency_threshold_percent <= disk_threshold_percent raises ValueError."""
        with pytest.raises(ValueError, match="emergency_threshold_percent.*greater"):
            validate_config({
                "disk_threshold_percent": 80,
                "emergency_threshold_percent": 80,
            })

    def test_emergency_max_99(self):
        """emergency_threshold_percent > 99 raises ValueError."""
        with pytest.raises(ValueError, match="emergency_threshold_percent"):
            validate_config({"emergency_threshold_percent": 100})

    def test_emergency_min_51(self):
        """emergency_threshold_percent < 51 raises ValueError."""
        with pytest.raises(ValueError, match="emergency_threshold_percent"):
            validate_config({"emergency_threshold_percent": 50})


class TestValidateConfigWrongType:
    def test_wrong_type_string_for_int(self):
        """String where int expected raises ValueError."""
        with pytest.raises(ValueError, match="must be an integer"):
            validate_config({"hot_days": "ninety"})


# =========================================================================
# RetentionConfigManager — load()
# =========================================================================


class TestLoad:
    def test_load_from_json_file(self, tmp_path):
        """Load reads from an existing retention.json with correct values."""
        config_file = tmp_path / "retention.json"
        config_file.write_text(json.dumps({
            "version": 1,
            "retention": {"hot_days": 60, "warm_days": 120, "cold_days": 14},
            "thresholds": {
                "disk_threshold_percent": 75,
                "emergency_threshold_percent": 85,
            },
        }))

        mgr = RetentionConfigManager(
            config_path=str(config_file),
            env_file=str(tmp_path / ".env"),
        )
        cfg = mgr.load()

        assert cfg.hot_days == 60
        assert cfg.warm_days == 120
        assert cfg.cold_days == 14
        assert abs(cfg.disk_threshold - 0.75) < 0.001
        assert abs(cfg.emergency_threshold - 0.85) < 0.001

    def test_load_fallback_env_vars(self, tmp_path, monkeypatch):
        """When no JSON file exists, env vars are used."""
        monkeypatch.setenv("RETENTION_HOT", "45")
        monkeypatch.setenv("RETENTION_WARM", "100")
        monkeypatch.setenv("RETENTION_COLD", "10")
        monkeypatch.setenv("DISK_THRESHOLD_PERCENT", "70")
        monkeypatch.setenv("EMERGENCY_THRESHOLD_PERCENT", "88")

        mgr = RetentionConfigManager(
            config_path=str(tmp_path / "nonexistent.json"),
            env_file=str(tmp_path / ".env"),
        )
        cfg = mgr.load()

        assert cfg.hot_days == 45
        assert cfg.warm_days == 100
        assert cfg.cold_days == 10
        assert abs(cfg.disk_threshold - 0.70) < 0.001
        assert abs(cfg.emergency_threshold - 0.88) < 0.001

    def test_load_fallback_defaults(self, tmp_path, monkeypatch):
        """No JSON file, no env vars -> RetentionConfig defaults (90/180/30)."""
        for var in (
            "RETENTION_HOT", "RETENTION_WARM", "RETENTION_COLD",
            "DISK_THRESHOLD_PERCENT", "EMERGENCY_THRESHOLD_PERCENT",
        ):
            monkeypatch.delenv(var, raising=False)

        mgr = RetentionConfigManager(
            config_path=str(tmp_path / "nonexistent.json"),
            env_file=str(tmp_path / ".env"),
        )
        cfg = mgr.load()

        assert cfg.hot_days == 90
        assert cfg.warm_days == 180
        assert cfg.cold_days == 30
        assert abs(cfg.disk_threshold - 0.80) < 0.001
        assert abs(cfg.emergency_threshold - 0.90) < 0.001

    def test_load_corrupt_json(self, tmp_path, monkeypatch):
        """Corrupt retention.json falls back to defaults without crashing."""
        for var in (
            "RETENTION_HOT", "RETENTION_WARM", "RETENTION_COLD",
            "DISK_THRESHOLD_PERCENT", "EMERGENCY_THRESHOLD_PERCENT",
        ):
            monkeypatch.delenv(var, raising=False)

        config_file = tmp_path / "retention.json"
        config_file.write_text("{this is not valid JSON!!!}")

        mgr = RetentionConfigManager(
            config_path=str(config_file),
            env_file=str(tmp_path / ".env"),
        )
        cfg = mgr.load()

        # Falls back to defaults
        assert cfg.hot_days == 90
        assert cfg.warm_days == 180
        assert cfg.cold_days == 30

    def test_load_priority_json_over_env(self, tmp_path, monkeypatch):
        """When both JSON file and env vars exist, JSON wins."""
        monkeypatch.setenv("RETENTION_HOT", "999")

        config_file = tmp_path / "retention.json"
        config_file.write_text(json.dumps({
            "version": 1,
            "retention": {"hot_days": 45, "warm_days": 120, "cold_days": 14},
            "thresholds": {
                "disk_threshold_percent": 75,
                "emergency_threshold_percent": 85,
            },
        }))

        mgr = RetentionConfigManager(
            config_path=str(config_file),
            env_file=str(tmp_path / ".env"),
        )
        cfg = mgr.load()

        # JSON value (45) should win over env var (999)
        assert cfg.hot_days == 45


# =========================================================================
# RetentionConfigManager — save()
# =========================================================================


class TestSave:
    def test_save_writes_json(self, tmp_path):
        """save() writes a valid retention.json with expected structure."""
        config_file = tmp_path / "retention.json"
        mgr = RetentionConfigManager(
            config_path=str(config_file),
            env_file=str(tmp_path / ".env"),
        )
        mgr.load()  # initialise in-memory config
        mgr.save({"hot_days": 60, "warm_days": 120, "cold_days": 14})

        assert config_file.exists()
        data = json.loads(config_file.read_text())
        assert data["retention"]["hot_days"] == 60
        assert data["retention"]["warm_days"] == 120
        assert data["retention"]["cold_days"] == 14
        assert "version" in data
        assert "updated_at" in data

    def test_save_atomic_write(self, tmp_path):
        """save() uses a .tmp file for atomic writes — no .tmp remains."""
        config_file = tmp_path / "retention.json"
        mgr = RetentionConfigManager(
            config_path=str(config_file),
            env_file=str(tmp_path / ".env"),
        )
        mgr.load()
        mgr.save({"hot_days": 60})

        # The .tmp file should have been renamed, so it should NOT exist
        tmp_file = config_file.with_suffix(".tmp")
        assert not tmp_file.exists()
        # But the final file should exist
        assert config_file.exists()

    def test_save_syncs_env(self, tmp_path, monkeypatch):
        """save() writes correct env var names (RETENTION_HOT) to .env."""
        for var in (
            "RETENTION_HOT", "RETENTION_WARM", "RETENTION_COLD",
            "DISK_THRESHOLD_PERCENT", "EMERGENCY_THRESHOLD_PERCENT",
        ):
            monkeypatch.delenv(var, raising=False)

        config_file = tmp_path / "retention.json"
        env_file = tmp_path / ".env"
        mgr = RetentionConfigManager(
            config_path=str(config_file),
            env_file=str(env_file),
        )
        mgr.load()
        mgr.save({"hot_days": 60, "warm_days": 120, "cold_days": 14})

        assert env_file.exists()
        env_content = env_file.read_text()
        assert "RETENTION_HOT=60" in env_content
        assert "RETENTION_WARM=120" in env_content
        assert "RETENTION_COLD=14" in env_content

    def test_save_validation_error(self, tmp_path, monkeypatch):
        """Invalid values raise ValueError, file not modified."""
        for var in (
            "RETENTION_HOT", "RETENTION_WARM", "RETENTION_COLD",
            "DISK_THRESHOLD_PERCENT", "EMERGENCY_THRESHOLD_PERCENT",
        ):
            monkeypatch.delenv(var, raising=False)

        config_file = tmp_path / "retention.json"
        mgr = RetentionConfigManager(
            config_path=str(config_file),
            env_file=str(tmp_path / ".env"),
        )
        mgr.load()

        # Capture state before the bad save attempt
        original_cfg = mgr.get_config()

        with pytest.raises(ValueError):
            mgr.save({"hot_days": 0})  # out of range

        # Config should not have changed
        assert mgr.get_config().hot_days == original_cfg.hot_days

    def test_save_partial_update(self, tmp_path, monkeypatch):
        """Saving only some fields retains current values for the rest."""
        for var in (
            "RETENTION_HOT", "RETENTION_WARM", "RETENTION_COLD",
            "DISK_THRESHOLD_PERCENT", "EMERGENCY_THRESHOLD_PERCENT",
        ):
            monkeypatch.delenv(var, raising=False)

        config_file = tmp_path / "retention.json"
        mgr = RetentionConfigManager(
            config_path=str(config_file),
            env_file=str(tmp_path / ".env"),
        )
        mgr.load()  # defaults: 90/180/30

        # Only update hot_days
        cfg = mgr.save({"hot_days": 45})

        assert cfg.hot_days == 45
        assert cfg.warm_days == 180  # retained
        assert cfg.cold_days == 30  # retained

    def test_save_partial_update_cross_field_violation(self, tmp_path, monkeypatch):
        """Partial update that creates invalid cross-field state is rejected.

        If current disk_threshold is 80% and user sends only
        emergency_threshold=75%, the merged result (80/75) should fail
        validation because emergency must be > disk threshold.
        """
        for var in (
            "RETENTION_HOT", "RETENTION_WARM", "RETENTION_COLD",
            "DISK_THRESHOLD_PERCENT", "EMERGENCY_THRESHOLD_PERCENT",
        ):
            monkeypatch.delenv(var, raising=False)

        config_file = tmp_path / "retention.json"
        mgr = RetentionConfigManager(
            config_path=str(config_file),
            env_file=str(tmp_path / ".env"),
        )
        mgr.load()  # defaults: disk=80%, emergency=90%

        # Try to lower emergency below existing disk threshold
        with pytest.raises(ValueError, match="emergency_threshold_percent"):
            mgr.save({"emergency_threshold_percent": 75})


# =========================================================================
# RetentionConfigManager — ILM status
# =========================================================================


class TestIlmStatus:
    def test_mark_ilm_applied(self, tmp_path, monkeypatch):
        """mark_ilm_applied() writes ilm_applied section to retention.json."""
        for var in (
            "RETENTION_HOT", "RETENTION_WARM", "RETENTION_COLD",
            "DISK_THRESHOLD_PERCENT", "EMERGENCY_THRESHOLD_PERCENT",
        ):
            monkeypatch.delenv(var, raising=False)

        config_file = tmp_path / "retention.json"
        mgr = RetentionConfigManager(
            config_path=str(config_file),
            env_file=str(tmp_path / ".env"),
        )
        mgr.load()

        mgr.mark_ilm_applied({
            "nettap-hot-policy": "created",
            "nettap-warm-policy": "created",
            "nettap-cold-policy": "created",
        })

        # Read the file and check
        data = json.loads(config_file.read_text())
        assert "ilm_applied" in data
        assert data["ilm_applied"]["last_success"] is not None
        assert data["ilm_applied"]["policies"]["nettap-hot-policy"] == "created"

    def test_get_ilm_status(self, tmp_path, monkeypatch):
        """After mark_ilm_applied(), get_ilm_status() returns the data."""
        for var in (
            "RETENTION_HOT", "RETENTION_WARM", "RETENTION_COLD",
            "DISK_THRESHOLD_PERCENT", "EMERGENCY_THRESHOLD_PERCENT",
        ):
            monkeypatch.delenv(var, raising=False)

        config_file = tmp_path / "retention.json"
        mgr = RetentionConfigManager(
            config_path=str(config_file),
            env_file=str(tmp_path / ".env"),
        )
        mgr.load()

        results = {"nettap-hot-policy": "updated"}
        mgr.mark_ilm_applied(results)

        status = mgr.get_ilm_status()
        assert status["last_success"] is not None
        assert status["last_attempt"] is not None
        assert status["policies"]["nettap-hot-policy"] == "updated"
