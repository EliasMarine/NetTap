"""
Tests for the SuricataRuleManager service.

Covers source listing, enable/disable, YAML parsing, stats,
schedule management, custom rules, and commercial config.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import yaml

from services.suricata_rules import SuricataRuleManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Create a temp directory with a sample update-sources.yaml."""
    sources_file = tmp_path / "update-sources.yaml"
    sources_data = {
        "sources": {
            "et/open": {
                "enabled": True,
                "description": "Emerging Threats Open",
            },
            "sslbl/ssl-fp-blacklist": {
                "enabled": True,
                "description": "abuse.ch SSL Blacklist",
            },
            "tgreen/hunting": {
                "enabled": False,
                "description": "tgreen Hunting Rules",
            },
        }
    }
    with open(sources_file, "w") as f:
        yaml.dump(sources_data, f)
    return tmp_path


@pytest.fixture
def manager(tmp_config_dir):
    """Create a SuricataRuleManager pointing at temp config files."""
    return SuricataRuleManager(
        sources_config=str(tmp_config_dir / "update-sources.yaml"),
        container_name="test-suricata",
        schedule_file=str(tmp_config_dir / "rule-schedule.yaml"),
        custom_rules_file=str(tmp_config_dir / "custom.rules"),
        commercial_config=str(tmp_config_dir / "commercial.yaml"),
    )


# ---------------------------------------------------------------------------
# Source listing
# ---------------------------------------------------------------------------


class TestGetEnabledSources:
    def test_returns_all_sources(self, manager):
        sources = manager.get_enabled_sources()
        assert len(sources) == 3

    def test_source_structure(self, manager):
        sources = manager.get_enabled_sources()
        et_open = next(s for s in sources if s["id"] == "et/open")
        assert et_open["enabled"] is True
        assert "Emerging Threats" in et_open["description"]

    def test_disabled_source(self, manager):
        sources = manager.get_enabled_sources()
        tgreen = next(s for s in sources if s["id"] == "tgreen/hunting")
        assert tgreen["enabled"] is False

    def test_missing_config_returns_empty(self, tmp_path):
        mgr = SuricataRuleManager(
            sources_config=str(tmp_path / "nonexistent.yaml")
        )
        sources = mgr.get_enabled_sources()
        assert sources == []


# ---------------------------------------------------------------------------
# Enable / Disable
# ---------------------------------------------------------------------------


class TestEnableDisable:
    def test_enable_source(self, manager):
        assert manager.enable_source("tgreen/hunting") is True
        sources = manager.get_enabled_sources()
        tgreen = next(s for s in sources if s["id"] == "tgreen/hunting")
        assert tgreen["enabled"] is True

    def test_disable_source(self, manager):
        assert manager.disable_source("et/open") is True
        sources = manager.get_enabled_sources()
        et_open = next(s for s in sources if s["id"] == "et/open")
        assert et_open["enabled"] is False

    def test_enable_nonexistent_returns_false(self, manager):
        assert manager.enable_source("nonexistent/source") is False

    def test_disable_nonexistent_returns_false(self, manager):
        assert manager.disable_source("nonexistent/source") is False

    def test_persists_to_yaml(self, manager, tmp_config_dir):
        manager.enable_source("tgreen/hunting")
        # Re-read from disk
        with open(tmp_config_dir / "update-sources.yaml") as f:
            data = yaml.safe_load(f)
        assert data["sources"]["tgreen/hunting"]["enabled"] is True


# ---------------------------------------------------------------------------
# Rule update (mocked docker exec)
# ---------------------------------------------------------------------------


class TestUpdateRules:
    def test_successful_update(self, manager):
        async def run():
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                # Mock suricata-update process
                update_proc = AsyncMock()
                update_proc.returncode = 0
                update_proc.communicate = AsyncMock(
                    return_value=(b"Rules updated: 30000 loaded", None)
                )

                # Mock suricatasc reload process
                reload_proc = AsyncMock()
                reload_proc.returncode = 0
                reload_proc.communicate = AsyncMock(
                    return_value=(b"Rules reloaded", None)
                )

                mock_exec.side_effect = [update_proc, reload_proc]

                result = await manager.update_rules()
                assert result["success"] is True
                assert "30000" in result["output"]
                assert result["reload_output"] == "Rules reloaded"

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run())
        finally:
            loop.close()

    def test_failed_update(self, manager):
        async def run():
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                proc = AsyncMock()
                proc.returncode = 1
                proc.communicate = AsyncMock(
                    return_value=(b"Error: update failed", None)
                )
                mock_exec.return_value = proc

                result = await manager.update_rules()
                assert result["success"] is False
                assert "Error" in result["output"]

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run())
        finally:
            loop.close()

    def test_exec_exception(self, manager):
        async def run():
            with patch(
                "asyncio.create_subprocess_exec",
                side_effect=FileNotFoundError("docker not found"),
            ):
                result = await manager.update_rules()
                assert result["success"] is False
                assert "docker not found" in result["output"]

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run())
        finally:
            loop.close()


# ---------------------------------------------------------------------------
# Rule stats
# ---------------------------------------------------------------------------


class TestRuleStats:
    def test_stats_structure(self, manager):
        stats = manager.get_rule_stats()
        assert "total_rules" in stats
        assert "enabled_sources" in stats
        assert "total_sources" in stats
        assert "categories" in stats
        assert "category_prefixes" in stats

    def test_enabled_source_count(self, manager):
        stats = manager.get_rule_stats()
        # 2 enabled out of 3 (et/open and sslbl enabled, tgreen disabled)
        assert stats["enabled_sources"] == 2
        assert stats["total_sources"] == 3


# ---------------------------------------------------------------------------
# Last update
# ---------------------------------------------------------------------------


class TestLastUpdate:
    def test_returns_iso_string(self, manager):
        last = manager.get_last_update()
        assert last is not None
        assert "T" in last  # ISO format

    def test_missing_file_returns_none(self, tmp_path):
        mgr = SuricataRuleManager(
            sources_config=str(tmp_path / "nonexistent.yaml")
        )
        assert mgr.get_last_update() is None


# ---------------------------------------------------------------------------
# Schedule management
# ---------------------------------------------------------------------------


class TestSchedule:
    def test_default_schedule(self, manager):
        schedule = manager.get_update_schedule()
        assert schedule["interval"] == "daily"
        assert schedule["enabled"] is True

    def test_set_weekly(self, manager):
        result = manager.set_update_schedule("weekly")
        assert result["interval"] == "weekly"
        assert result["enabled"] is True

    def test_set_manual_disables(self, manager):
        result = manager.set_update_schedule("manual")
        assert result["interval"] == "manual"
        assert result["enabled"] is False

    def test_invalid_interval_raises(self, manager):
        with pytest.raises(ValueError, match="Invalid interval"):
            manager.set_update_schedule("hourly")

    def test_persists_schedule(self, manager, tmp_config_dir):
        manager.set_update_schedule("weekly")
        with open(tmp_config_dir / "rule-schedule.yaml") as f:
            data = yaml.safe_load(f)
        assert data["interval"] == "weekly"

    def test_read_persisted_schedule(self, manager):
        manager.set_update_schedule("weekly")
        schedule = manager.get_update_schedule()
        assert schedule["interval"] == "weekly"


# ---------------------------------------------------------------------------
# Custom rules
# ---------------------------------------------------------------------------


class TestCustomRules:
    def test_add_custom_rules(self, manager):
        content = (
            '# My custom rules\n'
            'alert tcp any any -> any any (msg:"Test 1"; sid:9999001; rev:1;)\n'
            'alert tcp any any -> any 443 (msg:"Test 2"; sid:9999002; rev:1;)\n'
        )
        result = manager.add_custom_rules(content)
        assert result["success"] is True
        assert result["rules_written"] == 2

    def test_get_custom_rules(self, manager):
        content = 'alert tcp any any -> any any (msg:"Test"; sid:9999001; rev:1;)\n'
        manager.add_custom_rules(content)
        retrieved = manager.get_custom_rules()
        assert "sid:9999001" in retrieved

    def test_empty_custom_rules(self, manager):
        content = manager.get_custom_rules()
        assert content == ""

    def test_comments_not_counted(self, manager):
        content = "# comment\n# another comment\n"
        result = manager.add_custom_rules(content)
        assert result["rules_written"] == 0


# ---------------------------------------------------------------------------
# Commercial config
# ---------------------------------------------------------------------------


class TestCommercialConfig:
    def test_configure_etpro(self, manager):
        result = manager.configure_commercial("etpro", "ABCDEFGH12345678")
        assert result["success"] is True
        assert result["source_type"] == "etpro"
        assert "configured_at" in result

    def test_configure_snort(self, manager):
        result = manager.configure_commercial("snort", "OINKCODE12345678")
        assert result["success"] is True
        assert result["source_type"] == "snort"

    def test_invalid_source_type(self, manager):
        with pytest.raises(ValueError, match="Invalid source type"):
            manager.configure_commercial("invalid", "ABCDEFGH12345678")

    def test_short_key_raises(self, manager):
        with pytest.raises(ValueError, match="at least 8"):
            manager.configure_commercial("etpro", "short")

    def test_get_commercial_config(self, manager):
        manager.configure_commercial("etpro", "ABCDEFGH12345678")
        config = manager.get_commercial_config()
        assert config is not None
        assert config["source_type"] == "etpro"
        assert "ABCD" in config["license_key_masked"]
        assert "5678" in config["license_key_masked"]
        # Full key should not be exposed
        assert "ABCDEFGH12345678" not in config["license_key_masked"]

    def test_no_commercial_config(self, manager):
        config = manager.get_commercial_config()
        assert config is None
