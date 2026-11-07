"""
Tests for the SuricataRuleManager service.

Covers source listing, enable/disable, YAML parsing, stats,
schedule management, custom rules, and commercial config.
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

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
        mgr = SuricataRuleManager(sources_config=str(tmp_path / "nonexistent.yaml"))
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


# OLD CODE START — NET-191 slice 2: Update now runs the shim (one docker exec); TestUpdateRulesThroughTheShim below
# class TestUpdateRules:
#     def test_successful_update(self, manager):
#         async def run():
#             with patch("asyncio.create_subprocess_exec") as mock_exec:
#                 # Mock suricata-update process
#                 update_proc = AsyncMock()
#                 update_proc.returncode = 0
#                 update_proc.communicate = AsyncMock(
#                     return_value=(b"Rules updated: 30000 loaded", None)
#                 )
#
#                 # Mock suricatasc reload process
#                 reload_proc = AsyncMock()
#                 reload_proc.returncode = 0
#                 reload_proc.communicate = AsyncMock(
#                     return_value=(b"Rules reloaded", None)
#                 )
#
#                 mock_exec.side_effect = [update_proc, reload_proc]
#
#                 result = await manager.update_rules()
#                 assert result["success"] is True
#                 assert "30000" in result["output"]
#                 assert result["reload_output"] == "Rules reloaded"
#
#         loop = asyncio.new_event_loop()
#         try:
#             loop.run_until_complete(run())
#         finally:
#             loop.close()
#
#     def test_failed_reload_is_not_success(self, manager):
#         """#96: rules downloaded but not loaded into Suricata is not a success."""
#
#         async def run():
#             with patch("asyncio.create_subprocess_exec") as mock_exec:
#                 update_proc = AsyncMock()
#                 update_proc.returncode = 0
#                 update_proc.communicate = AsyncMock(
#                     return_value=(b"30000 loaded", None)
#                 )
#                 reload_proc = AsyncMock()
#                 reload_proc.returncode = 1
#                 reload_proc.communicate = AsyncMock(
#                     return_value=(b'{"return": "NOK", "message": "busy"}', None)
#                 )
#                 mock_exec.side_effect = [update_proc, reload_proc]
#
#                 result = await manager.update_rules()
#                 assert result["success"] is False
#                 assert "NOK" in result["reload_output"]
#
#         asyncio.run(run())
#
#     def test_reload_exception_is_not_success(self, manager):
#         async def run():
#             update_proc = AsyncMock()
#             update_proc.returncode = 0
#             update_proc.communicate = AsyncMock(return_value=(b"ok", None))
#             with patch(
#                 "asyncio.create_subprocess_exec",
#                 side_effect=[update_proc, OSError("docker socket gone")],
#             ):
#                 result = await manager.update_rules()
#             assert result["success"] is False
#             assert "Reload failed" in result["reload_output"]
#
#         asyncio.run(run())
#
#     def test_failed_update(self, manager):
#         async def run():
#             with patch("asyncio.create_subprocess_exec") as mock_exec:
#                 proc = AsyncMock()
#                 proc.returncode = 1
#                 proc.communicate = AsyncMock(
#                     return_value=(b"Error: update failed", None)
#                 )
#                 mock_exec.return_value = proc
#
#                 result = await manager.update_rules()
#                 assert result["success"] is False
#                 assert "Error" in result["output"]
#
#         loop = asyncio.new_event_loop()
#         try:
#             loop.run_until_complete(run())
#         finally:
#             loop.close()
#
#     def test_exec_exception(self, manager):
#         async def run():
#             with patch(
#                 "asyncio.create_subprocess_exec",
#                 side_effect=FileNotFoundError("docker not found"),
#             ):
#                 result = await manager.update_rules()
#                 assert result["success"] is False
#                 assert "docker not found" in result["output"]
#
#         loop = asyncio.new_event_loop()
#         try:
#             loop.run_until_complete(run())
#         finally:
#             loop.close()
# OLD CODE END


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
        mgr = SuricataRuleManager(sources_config=str(tmp_path / "nonexistent.yaml"))
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
            "# My custom rules\n"
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


# OLD CODE START — NET-191 slice 2: configure_commercial/get_commercial_config retired (test_etpro.py covers ET Pro)
# class TestCommercialConfig:
#     def test_configure_etpro(self, manager):
#         result = manager.configure_commercial("etpro", "ABCDEFGH12345678")
#         assert result["success"] is True
#         assert result["source_type"] == "etpro"
#         assert "configured_at" in result
#
#     def test_configure_snort(self, manager):
#         result = manager.configure_commercial("snort", "OINKCODE12345678")
#         assert result["success"] is True
#         assert result["source_type"] == "snort"
#
#     def test_invalid_source_type(self, manager):
#         with pytest.raises(ValueError, match="Invalid source type"):
#             manager.configure_commercial("invalid", "ABCDEFGH12345678")
#
#     def test_short_key_raises(self, manager):
#         with pytest.raises(ValueError, match="at least 8"):
#             manager.configure_commercial("etpro", "short")
#
#     def test_get_commercial_config(self, manager):
#         manager.configure_commercial("etpro", "ABCDEFGH12345678")
#         config = manager.get_commercial_config()
#         assert config is not None
#         assert config["source_type"] == "etpro"
#         assert "ABCD" in config["license_key_masked"]
#         assert "5678" in config["license_key_masked"]
#         # Full key should not be exposed
#         assert "ABCDEFGH12345678" not in config["license_key_masked"]
#
#     def test_no_commercial_config(self, manager):
#         config = manager.get_commercial_config()
#         assert config is None
# OLD CODE END


# ---------------------------------------------------------------------------
# Live status read from the Suricata container (#58)
# ---------------------------------------------------------------------------

import subprocess  # noqa: E402

from services.suricata_rules import _LIVE_STATUS_SCRIPT, parse_live_status  # noqa: E402

_LIVE_OUTPUT = """ENABLED 64307
DISABLED 15954
MTIME 1793577636
SOURCE https://rules.emergingthreats.net/open/suricata-%(__version__)s/emerging.rules.tar.gz
SOURCE https://sslbl.abuse.ch/blacklist/sslblacklist.rules
CRON 0 0 * * *
"""


def _gnu_stat() -> bool:
    return (
        subprocess.run(["stat", "-c", "%Y", "/"], capture_output=True).returncode == 0
    )


class TestParseLiveStatus:
    def test_reads_counts_refresh_sources_and_schedule(self):
        status = parse_live_status(_LIVE_OUTPUT)
        assert status["available"] is True
        assert status["enabled_rules"] == 64307
        assert status["disabled_rules"] == 15954
        assert status["last_updated"] == "2026-11-02T00:00:36+00:00"
        assert status["sources"] == [
            "https://rules.emergingthreats.net/open/suricata-%(__version__)s/emerging.rules.tar.gz",
            "https://sslbl.abuse.ch/blacklist/sslblacklist.rules",
        ]
        assert status["schedule"] == "0 0 * * *"
        assert status["error"] is None

    def test_no_rules_file(self):
        assert parse_live_status("MISSING\n") == {
            "available": False,
            "error": "Suricata has no rules file yet.",
        }

    def test_unreadable_output_is_not_reported_as_zero_rules(self):
        status = parse_live_status("grep: something broke\n")
        assert status["available"] is False
        assert status["error"]

    def test_owner_rule_count(self):
        """NET-191 slice 3: None when suricata-live has no owner rules file, else its alert rules."""
        assert parse_live_status(_LIVE_OUTPUT)["owner_rules"] is None
        assert parse_live_status(_LIVE_OUTPUT + "OWNER 0\n")["owner_rules"] == 0
        assert parse_live_status(_LIVE_OUTPUT + "OWNER 3\n")["owner_rules"] == 3

    def test_the_owner_count_reads_lines_as_suricata_does(self, tmp_path):
        """Run the script's own OWNER line. Suricata skips a line that starts with a space or a
        tab (the validator refuses one), and "alert<TAB>tcp" is a rule."""
        import subprocess

        from services.suricata_rules import _LIVE_STATUS_SCRIPT

        rules = tmp_path / "owner.rules"
        rules.write_text(
            "alert tcp a\n\talert tcp b\n  alert\ttcp c\n# alert tcp d\nalerts e\nalert\ttcp f\n"
        )
        line = next(
            ln
            for ln in _LIVE_STATUS_SCRIPT.splitlines()
            if ln.startswith('[ -f "$O" ]')
        )
        out = subprocess.run(
            ["sh", "-c", line],
            env={"O": str(rules), "PATH": os.environ["PATH"]},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert parse_live_status(_LIVE_OUTPUT + out)["owner_rules"] == 2


class TestGetLiveStatus:
    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_runs_one_bounded_exec_in_the_suricata_container(self, manager):
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(_LIVE_OUTPUT.encode(), b""))
        with patch(
            "asyncio.create_subprocess_exec", AsyncMock(return_value=proc)
        ) as mock_exec:
            status = self._run(manager.get_live_status())
        args = mock_exec.call_args.args
        assert args[:4] == (
            "docker",
            "exec",
            "test-suricata",
            "timeout",
        )  # timeout -k 5 N inside
        assert args[-3:-1] == ("sh", "-c")
        assert status["enabled_rules"] == 64307

    def test_exec_failure_is_unavailable(self, manager):
        proc = AsyncMock()
        proc.returncode = 1
        proc.communicate = AsyncMock(
            return_value=(b"", b"Error: No such container: test-suricata")
        )
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            status = self._run(manager.get_live_status())
        assert status == {
            "available": False,
            "error": "Could not read Suricata's rules.",
        }

    def test_docker_missing_is_unavailable(self, manager):
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(side_effect=OSError("no docker")),
        ):
            status = self._run(manager.get_live_status())
        assert status["available"] is False


@pytest.mark.skipif(not _gnu_stat(), reason="the script runs on Linux (GNU stat)")
class TestLiveStatusScript:
    def test_script_against_sample_files(self, tmp_path):
        rules = tmp_path / "suricata.rules"
        rules.write_text(
            'alert ip any any -> any any (msg:"a"; sid:1;)\n'
            '# alert ip any any -> any any (msg:"b"; sid:2;)\n'
            'drop ip any any -> any any (msg:"c"; sid:3;)\n'
            "# a comment\n"
        )
        update = tmp_path / "update.yaml"
        update.write_text(
            "disable-conf: /etc/suricata/disable.conf\nsources:\n  - https://a.example/r.tar.gz\n"
            "  - https://b.example/r.rules\nlocal:\n  - /etc/suricata/rules\n"
        )
        cron = tmp_path / "crontab"
        cron.write_text("0 0 * * * /bin/bash /usr/local/bin/suricata-update-rules.sh\n")
        script = (
            _LIVE_STATUS_SCRIPT.replace(
                "/var/lib/suricata/rules/suricata.rules", str(rules)
            )
            .replace("/etc/suricata/update.yaml", str(update))
            .replace("/etc/crontab", str(cron))
            .replace(
                "/opt/suricata/rules/custom/owner.rules", str(tmp_path / "owner.rules")
            )
        )
        out = subprocess.run(
            ["sh", "-c", script], capture_output=True, text=True, check=True
        ).stdout
        assert parse_live_status(out)["owner_rules"] is None
        (tmp_path / "owner.rules").write_text(
            'alert dns any any -> any any (msg:"a"; sid:1000001;)\n# alert x\n\n'
            'alert dns any any -> any any (msg:"b"; sid:1000002;)\n'
        )
        out = subprocess.run(
            ["sh", "-c", script], capture_output=True, text=True, check=True
        ).stdout
        status = parse_live_status(out)
        assert status["owner_rules"] == 2
        assert status["enabled_rules"] == 2
        assert status["disabled_rules"] == 1
        assert status["sources"] == [
            "https://a.example/r.tar.gz",
            "https://b.example/r.rules",
        ]
        assert status["schedule"] == "0 0 * * *"
        assert status["last_updated"]
