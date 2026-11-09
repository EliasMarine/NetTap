"""NET-191 slice 2: "Update now" through the shim, the update status record, the live status additions."""

import asyncio
import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services import rules_lock
from services import suricata_rules as sr
from services.suricata_rules import (
    SuricataRuleManager,
    parse_live_status,
    read_update_status,
    with_update_status,
)


def _record(state_dir, **fields):
    (state_dir / "update-status.json").write_text(json.dumps(fields))


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(rules_lock, "RULES_STATE_DIR", str(tmp_path))
    return tmp_path


def _proc(rc: int, out: bytes = b""):
    proc = AsyncMock()
    proc.returncode = rc
    proc.communicate = AsyncMock(return_value=(out, None))
    return proc


# --- Update now ------------------------------------------------------------------------------


class TestUpdateRulesThroughTheShim:
    def test_runs_the_shim_as_malcolms_user_once(self, state):
        _record(
            state,
            state="active",
            exit_code=0,
            reason="",
            attempt="2026-11-07T10:00:00Z",
        )
        with patch(
            "asyncio.create_subprocess_exec", AsyncMock(return_value=_proc(0, b"ok"))
        ) as ex:
            result = asyncio.run(
                SuricataRuleManager(container_name="live").update_rules()
            )
        assert ex.await_count == 1
        assert ex.await_args.args == (
            "docker", "exec", "-u", "suricata", "live", "/usr/local/bin/suricata-update-rules.sh",
        )  # fmt: skip
        assert result["success"] is True
        assert result["status"]["state"] == "active"

    def test_a_failed_update_reports_the_records_reason(self, state):
        _record(
            state,
            state="failed",
            exit_code=1,
            reason="Failed to fetch https://x.invalid: 404",
        )
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=_proc(1, b"<Error>")),
        ):
            result = asyncio.run(
                SuricataRuleManager(container_name="live").update_rules()
            )
        assert result["success"] is False
        assert result["reload_output"] == "Failed to fetch https://x.invalid: 404"
        assert result["status"]["exit_code"] == 1

    def test_exit_0_without_a_good_record_is_not_success(self, state):
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=_proc(0))):
            result = asyncio.run(
                SuricataRuleManager(container_name="live").update_rules()
            )
        assert result["success"] is False
        assert result["status"]["state"] == "unknown"

    def test_still_running_after_the_wait_answers_running(self, state, monkeypatch):
        monkeypatch.setattr(sr, "RULES_UPDATE_WAIT_S", 0.05)
        never = asyncio.Event()

        async def slow():
            await never.wait()
            return b"", None

        proc = AsyncMock()
        proc.communicate = slow
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = asyncio.run(
                SuricataRuleManager(container_name="live").update_rules()
            )
        assert result["running"] is True
        assert result["success"] is False

    def test_docker_missing_is_a_failure(self, state):
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(side_effect=OSError("no docker")),
        ):
            result = asyncio.run(
                SuricataRuleManager(container_name="live").update_rules()
            )
        assert result["success"] is False
        assert "no docker" in result["output"]

    # NET-229 follow-up: Docker's own failure text (socket path, container name) never reaches the reply
    def test_a_docker_failure_keeps_its_text_in_the_log(self, state, caplog):
        out = b"Cannot connect to the Docker daemon at unix:///private/run/docker.sock"
        with patch(
            "asyncio.create_subprocess_exec", AsyncMock(return_value=_proc(1, out))
        ):
            result = asyncio.run(
                SuricataRuleManager(container_name="live").update_rules()
            )
        assert result["success"] is False
        assert "docker.sock" not in json.dumps(result)
        assert "daemon log" in result["output"]
        assert "/private/run/docker.sock" in caplog.text

    def test_a_missing_docker_binary_shows_the_reason_not_the_path(self, state):
        missing = FileNotFoundError(
            2, "No such file or directory", "/opt/private/bin/docker"
        )
        with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=missing)):
            result = asyncio.run(
                SuricataRuleManager(container_name="live").update_rules()
            )
        assert "No such file or directory" in result["output"]
        assert "/opt/private" not in json.dumps(result)


# --- the status record -----------------------------------------------------------------------


class TestReadUpdateStatus:
    def test_missing_is_unknown_never_guessed(self, state):
        record = read_update_status()
        assert record["state"] == "unknown"
        assert record["last_success"] is None
        assert record["recovery_pending"] is False

    def test_reads_the_record(self, state):
        _record(state, state="failed", exit_code=1, reason="r", attempt="a",
                last_success="2026-11-06T00:00:01Z", last_activation="x")  # fmt: skip
        record = read_update_status()
        assert record == {
            "state": "failed", "attempt": "a", "exit_code": 1, "reason": "r",
            "last_success": "2026-11-06T00:00:01Z", "last_activation": "x", "recovery_pending": False,
            "missing_sources": [],
        }  # fmt: skip

    def test_missing_sources_are_names_or_nothing(self, state):
        _record(state, state="active", missing_sources=["ipfire/dbl", 3, None])
        assert read_update_status()["missing_sources"] == ["ipfire/dbl"]
        _record(state, state="active", missing_sources="ipfire/dbl")
        assert read_update_status()["missing_sources"] == []

    def test_a_link_is_not_followed(self, state, tmp_path_factory):
        elsewhere = tmp_path_factory.mktemp("elsewhere") / "record.json"
        elsewhere.write_text(json.dumps({"state": "active"}))
        (state / "update-status.json").symlink_to(elsewhere)
        assert read_update_status()["state"] == "unknown"

    def test_a_fifo_does_not_block(self, state):
        os.mkfifo(state / "update-status.json")
        done = []
        reader = threading.Thread(
            target=lambda: done.append(read_update_status()), daemon=True
        )
        reader.start()
        reader.join(2)
        assert done and done[0]["state"] == "unknown"

    def test_an_oversized_record_is_not_read(self, state):
        _record(state, state="active", reason="x" * (64 * 1024))
        assert read_update_status()["state"] == "unknown"

    def test_marker_after_a_failure_means_recovery_pending(self, state):
        _record(state, state="failed", reason="engine not confirmed")
        (state / "update-in-progress").write_text("t")
        assert read_update_status()["recovery_pending"] is True

    def test_marker_during_a_running_update_is_not_recovery(self, state):
        _record(state, state="active")
        (state / "update-in-progress").write_text("t")
        assert read_update_status()["recovery_pending"] is False

    def test_garbage_is_unknown(self, state):
        (state / "update-status.json").write_text("[1, 2")
        assert read_update_status()["state"] == "unknown"


NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


def _update(**fields):
    base = {"state": "unknown", "attempt": None, "exit_code": None, "reason": "",
            "last_success": None, "last_activation": None, "recovery_pending": False,
            "missing_sources": []}  # fmt: skip
    return {**base, **fields}


class TestWithUpdateStatus:
    def test_prepared_becomes_active_once_the_engine_loaded_later(self):
        live = {"engine": {"reload_time": "2026-11-07T10:01:12.000123+0000"}}
        out = with_update_status(
            live, _update(state="prepared", last_success="2026-11-07T10:00:00Z"), NOW
        )
        assert out["update"]["state"] == "active"
        assert out["update"]["last_activation"] == "2026-11-07T10:01:12.000123+0000"

    def test_prepared_stays_prepared_while_the_engine_runs_older_rules(self):
        live = {"engine": {"reload_time": "2026-11-07T09:00:00.000000+0000"}}
        out = with_update_status(
            live, _update(state="prepared", last_success="2026-11-07T10:00:00Z"), NOW
        )
        assert out["update"]["state"] == "prepared"

    def test_stale_after_48_hours_without_success(self):
        out = with_update_status(
            {}, _update(state="failed", last_success="2026-11-05T11:00:00Z"), NOW
        )
        assert out["update"]["stale"] is True
        out = with_update_status(
            {}, _update(state="active", last_success="2026-11-05T13:00:00Z"), NOW
        )
        assert out["update"]["stale"] is False

    def test_never_succeeded_is_stale_but_unknown_is_not(self):
        assert (
            with_update_status({}, _update(state="failed"), NOW)["update"]["stale"]
            is True
        )
        assert with_update_status({}, _update(), NOW)["update"]["stale"] is False


# --- the live status script ------------------------------------------------------------------

STATS = '{"message": [{"id": 0, "rules_loaded": 65378, "rules_failed": 0, "rules_skipped": 0}], "return": "OK"}'
RELOAD = '{"message": [{"id": 0, "last_reload": "2026-11-07T00:01:12.123456+0000"}], "return": "OK"}'


class TestLiveStatusAdditions:
    def test_reads_etpro_enabled_sources_and_the_engine(self):
        out = (
            "ENABLED 65378\nDISABLED 16031\nETPRO 41000\nMTIME 1793577636\n"
            "ENABLED_SOURCE et/pro\nENABLED_SOURCE ipfire/dbl\n"
            f"STATS {STATS}\nRELOAD {RELOAD}\n"
        )
        status = parse_live_status(out)
        assert status["etpro_rules"] == 41000
        assert status["enabled_sources"] == ["et/pro", "ipfire/dbl"]
        assert status["engine"] == {
            "loaded": 65378, "failed": 0, "reload_time": "2026-11-07T00:01:12.123456+0000",
        }  # fmt: skip

    def test_no_answer_from_the_engine_is_none_not_zero(self):
        status = parse_live_status(
            "ENABLED 5\nDISABLED 0\nSTATS \nRELOAD Error: connection refused\n"
        )
        assert status["engine"] is None
        nok = '{"message": "busy", "return": "NOK"}'
        assert parse_live_status(f"ENABLED 5\nSTATS {nok}\n")["engine"] is None

    def test_get_live_status_adds_the_record(self, state):
        _record(
            state, state="active", last_success=datetime.now(timezone.utc).isoformat()
        )
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"ENABLED 3\nDISABLED 1\n", b""))
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            status = asyncio.run(
                SuricataRuleManager(container_name="live").get_live_status()
            )
        assert status["update"]["state"] == "active"
        assert status["update"]["stale"] is False

    def test_script_counts_etpro_and_lists_sources_by_name_only(self, tmp_path):
        if (
            subprocess.run(["stat", "-c", "%Y", "/"], capture_output=True).returncode
            != 0
        ):
            pytest.skip("the script runs on Linux (GNU stat)")
        rules = tmp_path / "suricata.rules"
        rules.write_text(
            'alert ip any any -> any any (msg:"ET Pro"; sid:2800001; rev:1;)\n'
            'alert ip any any -> any any (msg:"ET Open"; sid:2000001; rev:1;)\n'
            '# alert ip any any -> any any (msg:"off"; sid:2800002; rev:1;)\n'
        )
        sources = tmp_path / "sources"
        sources.mkdir()
        (sources / "et-pro.yaml").write_text(
            "source: et/pro\nparams:\n  secret-code: CANARY0123456789ab\n"
        )
        script = sr._LIVE_STATUS_SCRIPT.replace(
            "/var/lib/suricata/rules/suricata.rules", str(rules)
        ).replace("/var/lib/suricata/update/sources", str(sources))
        out = subprocess.run(
            ["sh", "-c", script], capture_output=True, text=True
        ).stdout
        assert "CANARY" not in out
        status = parse_live_status(out)
        assert (
            status["enabled_rules"],
            status["disabled_rules"],
            status["etpro_rules"],
        ) == (2, 1, 1)
        assert status["enabled_sources"] == ["et/pro"]
