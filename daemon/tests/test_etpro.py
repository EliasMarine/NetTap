"""NET-191 slice 2: the optional ET Pro code (services/etpro.py and its API)."""

import asyncio
import logging
import os
import stat
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from api.suricata_rules import register_suricata_rules_routes
from services import etpro as etpro_mod
from services import rules_lock
from services.etpro import EtProError, EtProManager, read_code
from services.suricata_rules import SuricataRuleManager

CODE = "CANARYa1b2c3d4e5f6g7h8"
OTHER = "CANARYzz99yy88xx77ww66"


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    monkeypatch.setattr(rules_lock, "RULES_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "state").mkdir()
    return tmp_path / "suricata.env"


def _manager(env_file, live=None):
    rules = SuricataRuleManager(container_name="live")
    rules.get_live_status = AsyncMock(return_value=live or {"available": True})
    return EtProManager(rules, env_file=str(env_file))


class _Docker:
    """Fake docker CLI: suricata-offline -V answers the version; restart answers rc."""

    def __init__(self, restart_rc=0, version_rc=0):
        self.calls = []
        self.restart_rc, self.version_rc = restart_rc, version_rc

    async def __call__(self, *cmd, timeout):
        self.calls.append(cmd)
        if cmd[-1] == "-V":
            return self.version_rc, "This is Suricata version 8.0.7 RELEASE"
        return self.restart_rc, "" if self.restart_rc == 0 else "Error: boom"


def _run(coro):
    return asyncio.run(coro)


class TestSave:
    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "short",
            "a" * 65,
            CODE + ";",
            CODE + " ",
            CODE + "\n",
            "$(id)" + CODE,
            None,
            12,
        ],
    )
    def test_shape_is_checked_before_anything_else(self, env_file, bad):
        manager = _manager(env_file)
        docker = _Docker()
        with (
            patch.object(etpro_mod, "_run", docker),
            patch.object(etpro_mod, "preflight", AsyncMock()) as pf,
        ):
            with pytest.raises(EtProError, match="16 to 64 letters and digits"):
                _run(manager.save(bad))
        pf.assert_not_awaited()
        assert docker.calls == []
        assert not env_file.exists()

    @pytest.mark.parametrize(
        "status, words",
        [
            (403, r"didn't accept this code \(HTTP 403\)"),
            (None, "Couldn't reach Proofpoint"),
            (500, "HTTP 500"),
        ],
    )
    def test_preflight_rejection_changes_nothing(self, env_file, status, words):
        manager = _manager(env_file)
        docker = _Docker()
        with (
            patch.object(etpro_mod, "_run", docker),
            patch.object(etpro_mod, "preflight", AsyncMock(return_value=status)),
        ):
            with pytest.raises(EtProError, match=words) as exc:
                _run(manager.save(CODE))
        assert CODE not in str(exc.value)
        assert not env_file.exists()
        assert all(c[1] != "restart" for c in docker.calls)

    def test_preflight_uses_suricatas_version_and_the_url_suricata_update_fetches(
        self, env_file
    ):
        manager = _manager(env_file)
        seen = {}

        async def head(code, version):
            seen.update(code=code, version=version)
            return 200

        with (
            patch.object(etpro_mod, "_run", _Docker()),
            patch.object(etpro_mod, "preflight", head),
        ):
            with patch.object(manager, "_await_activation", AsyncMock()):
                _run(manager.save(CODE))
        assert seen == {"code": CODE, "version": "8.0.7"}
        assert etpro_mod.PREFLIGHT_URL.format(code="C", version="8.0.7") == (
            "https://rules.emergingthreatspro.com/C/suricata-8.0.7/etpro.rules.tar.gz"
        )

    def test_saves_root_600_then_restarts_suricata(self, env_file):
        manager = _manager(env_file)
        docker = _Docker()
        with (
            patch.object(etpro_mod, "_run", docker),
            patch.object(etpro_mod, "preflight", AsyncMock(return_value=200)),
        ):
            with patch.object(manager, "_await_activation", AsyncMock()):
                _run(manager.save(CODE))
        assert env_file.read_text() == f"SURICATA_ETPRO_CODE={CODE}\n"
        assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
        assert docker.calls[-1] == ("docker", "restart", "live")
        assert read_code(str(env_file)) == CODE

    def test_a_partial_answer_to_the_one_byte_preflight_is_accepted(self, env_file):
        manager = _manager(env_file)
        with (
            patch.object(etpro_mod, "_run", _Docker()),
            patch.object(etpro_mod, "preflight", AsyncMock(return_value=206)),
        ):
            with patch.object(manager, "_await_activation", AsyncMock()):
                _run(manager.save(CODE))
        assert read_code(str(env_file)) == CODE

    def test_restart_failure_puts_the_previous_code_back(self, env_file):
        env_file.write_text(f"SURICATA_ETPRO_CODE={OTHER}\n")
        manager = _manager(env_file)
        with (
            patch.object(etpro_mod, "_run", _Docker(restart_rc=1)),
            patch.object(etpro_mod, "preflight", AsyncMock(return_value=200)),
        ):
            with pytest.raises(EtProError, match="didn't restart") as exc:
                _run(manager.save(CODE))
        assert CODE not in str(exc.value)
        assert read_code(str(env_file)) == OTHER

    def test_restart_happens_holding_the_rules_lock(self, env_file):
        import fcntl

        manager = _manager(env_file)
        held = []

        async def docker(*cmd, timeout):
            if cmd[-1] == "-V":
                return 0, "This is Suricata version 8.0.7 RELEASE"
            fd = os.open(
                os.path.join(rules_lock.RULES_STATE_DIR, "rules.lock"), os.O_RDONLY
            )
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held.append(False)
            except BlockingIOError:
                held.append(True)
            finally:
                os.close(fd)
            return 0, ""

        with (
            patch.object(etpro_mod, "_run", docker),
            patch.object(etpro_mod, "preflight", AsyncMock(return_value=200)),
        ):
            with patch.object(manager, "_await_activation", AsyncMock()):
                _run(manager.save(CODE))
        assert held == [True]

    def test_busy_with_another_rule_operation_answers_at_once(self, env_file):
        from services.rules_lock import RulesBusyError

        manager = _manager(env_file)
        docker = _Docker()

        async def run():
            async with manager._rules.op_lock:  # "Update now" running in this daemon
                await manager.save(CODE)

        with (
            patch.object(etpro_mod, "_run", docker),
            patch.object(etpro_mod, "preflight", AsyncMock(return_value=200)),
        ):
            with pytest.raises(RulesBusyError):
                _run(run())
        assert not env_file.exists()
        assert all(c[1] != "restart" for c in docker.calls)

    def test_waits_at_most_a_minute_for_the_rules_lock(self, env_file):
        seen = []

        def fake_lock(wait_s=None):
            seen.append(wait_s)
            return rules_lock.rules_lock(wait_s)

        manager = _manager(env_file)
        with (
            patch.object(etpro_mod, "_run", _Docker()),
            patch.object(etpro_mod, "preflight", AsyncMock(return_value=200)),
        ):
            with (
                patch.object(etpro_mod, "rules_lock", fake_lock),
                patch.object(manager, "_await_activation", AsyncMock()),
            ):
                _run(manager.save(CODE))
        assert seen == [60]
        # with the version check (20 s), preflight (10 s) and restart (120 s) it stays inside the web's 290 s
        assert (
            20
            + etpro_mod.PREFLIGHT_TIMEOUT_S
            + etpro_mod.APPLY_LOCK_WAIT_S
            + etpro_mod.RESTART_TIMEOUT_S
            < 290
        )


class TestClear:
    def test_removes_the_file_and_restarts(self, env_file):
        env_file.write_text(f"SURICATA_ETPRO_CODE={CODE}\n")
        manager = _manager(env_file)
        docker = _Docker()
        with (
            patch.object(etpro_mod, "_run", docker),
            patch.object(manager, "_await_activation", AsyncMock()),
        ):
            assert _run(manager.clear()) is True
        assert not env_file.exists()
        assert docker.calls == [("docker", "restart", "live")]

    def test_nothing_saved_restarts_nothing(self, env_file):
        manager = _manager(env_file)
        docker = _Docker()
        with patch.object(etpro_mod, "_run", docker):
            assert _run(manager.clear()) is False
        assert docker.calls == []


LIVE_PRO = {
    "available": True,
    "enabled_sources": ["et/pro", "ipfire/dbl"],
    "etpro_rules": 41000,
    "engine": {
        "loaded": 90000,
        "failed": 0,
        "reload_time": "2999-01-01T00:00:00.000000+0000",
    },
    "update": {"state": "prepared", "reason": ""},
}


class TestActivationAndStatus:
    def test_a_second_change_cancels_the_first_watch(self, env_file):
        manager = _manager(env_file)

        async def slow_watch(started):
            await asyncio.sleep(10)

        async def run():
            with (
                patch.object(etpro_mod, "_run", _Docker()),
                patch.object(etpro_mod, "preflight", AsyncMock(return_value=200)),
                patch.object(manager, "_await_activation", slow_watch),
            ):
                await manager.save(CODE)
                first = manager._watch
                await manager.save(OTHER)
                done, _ = await asyncio.wait({first}, timeout=1)
                manager._watch.cancel()
                return first in done and first.cancelled()

        assert _run(run()) is True

    def test_waits_for_the_restarted_engine_then_reports_and_logs(
        self, env_file, monkeypatch, caplog
    ):
        monkeypatch.setattr(etpro_mod, "READY_POLL_S", 0)
        env_file.write_text(f"SURICATA_ETPRO_CODE={CODE}\n")
        old = {**LIVE_PRO, "engine": {"reload_time": "2000-01-01T00:00:00.000000+0000"}}
        manager = _manager(env_file)
        manager._rules.get_live_status = AsyncMock(side_effect=[old, old, LIVE_PRO])
        from datetime import datetime, timezone

        with caplog.at_level(logging.INFO, logger="nettap.services.etpro"):
            _run(manager._await_activation(datetime.now(timezone.utc)))
        assert manager._rules.get_live_status.await_count == 3
        assert manager._activation["state"] == "active"
        assert manager._activation["etpro_rules"] == 41000
        assert "ET Pro activation result: active" in caplog.text

    def test_et_pro_not_active_after_restart_is_said_honestly(
        self, env_file, monkeypatch
    ):
        monkeypatch.setattr(etpro_mod, "READY_POLL_S", 0)
        env_file.write_text(f"SURICATA_ETPRO_CODE={CODE}\n")
        failed = {
            **LIVE_PRO,
            "etpro_rules": 0,
            "update": {"state": "failed", "reason": "HTTP Error 403"},
        }
        manager = _manager(env_file)
        manager._rules.get_live_status = AsyncMock(return_value=failed)
        from datetime import datetime, timezone

        _run(manager._await_activation(datetime.now(timezone.utc)))
        assert manager._activation["state"] == "failed"
        assert "HTTP Error 403" in manager._activation["message"]

    def test_status_never_carries_the_code(self, env_file):
        env_file.write_text(f"SURICATA_ETPRO_CODE={CODE}\n")
        status = _run(_manager(env_file, LIVE_PRO).status())
        assert status == {
            "configured": True, "active": True, "last_update_ok": True, "applying": False, "activation": None,
        }  # fmt: skip
        assert CODE not in repr(status)

    def test_enabled_but_no_et_pro_rules_is_not_active(self, env_file):
        env_file.write_text(f"SURICATA_ETPRO_CODE={CODE}\n")
        live = {**LIVE_PRO, "etpro_rules": 0, "update": {"state": "failed"}}
        status = _run(_manager(env_file, live).status())
        assert (status["active"], status["last_update_ok"]) == (False, False)


class TestPreflight:
    def test_asks_for_one_byte_with_a_get_and_follows_redirects(self):
        seen = {}

        class Resp:
            status = 206

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        class Session:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def get(self, url, **kwargs):
                seen.update(url=url, **kwargs)
                return Resp()

        with patch.object(etpro_mod.aiohttp, "ClientSession", Session):
            assert _run(etpro_mod.preflight(CODE, "8.0.7")) == 206
        assert seen == {
            "url": etpro_mod.PREFLIGHT_URL.format(code=CODE, version="8.0.7"),
            "headers": {"Range": "bytes=0-0"},
            "allow_redirects": True,
        }

    def test_unreachable_is_none_and_logs_no_url(self, caplog):
        class Boom:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                raise aiohttp.ClientConnectorError(
                    None, OSError(f"cannot reach {CODE}")
                )

            async def __aexit__(self, *a):
                return False

        with (
            patch.object(etpro_mod.aiohttp, "ClientSession", Boom),
            caplog.at_level(logging.WARNING),
        ):
            assert _run(etpro_mod.preflight(CODE, "8.0.7")) is None
        assert CODE not in caplog.text

    def test_timeout_is_none(self):
        class Slow:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                raise asyncio.TimeoutError

            async def __aexit__(self, *a):
                return False

        with patch.object(etpro_mod.aiohttp, "ClientSession", Slow):
            assert _run(etpro_mod.preflight(CODE, "8.0.7")) is None


# --- API ---------------------------------------------------------------------------------------


async def _client(env_file):
    app = web.Application()
    rules = SuricataRuleManager(container_name="live")
    rules.get_live_status = AsyncMock(return_value=LIVE_PRO)
    register_suricata_rules_routes(app, rules)
    app["etpro_manager"]._env_file = str(env_file)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


class TestApi:
    def test_save_202_and_the_code_is_never_answered_or_logged(self, env_file, caplog):
        async def run():
            client = await _client(env_file)
            try:
                with (
                    patch.object(etpro_mod, "_run", _Docker()),
                    patch.object(etpro_mod, "preflight", AsyncMock(return_value=200)),
                    patch.object(EtProManager, "_await_activation", AsyncMock()),
                ):
                    saved = await client.post(
                        "/api/suricata/rules/commercial", json={"code": CODE}
                    )
                    got = await client.get("/api/suricata/rules/commercial")
                return saved.status, await saved.text(), await got.text()
            finally:
                await client.close()

        with caplog.at_level(logging.DEBUG):
            status, saved, got = _run(run())
        assert status == 202
        for text in (saved, got, caplog.text):
            assert CODE not in text
        assert '"configured": true' in got

    def test_rejected_code_is_400_with_a_plain_message(self, env_file):
        async def run():
            client = await _client(env_file)
            try:
                with (
                    patch.object(etpro_mod, "_run", _Docker()),
                    patch.object(etpro_mod, "preflight", AsyncMock(return_value=403)),
                ):
                    resp = await client.post(
                        "/api/suricata/rules/commercial", json={"code": CODE}
                    )
                return resp.status, await resp.json()
            finally:
                await client.close()

        status, body = _run(run())
        assert status == 400
        assert "didn't accept this code" in body["error"] and CODE not in body["error"]

    def test_busy_lock_is_409(self, env_file, monkeypatch):
        from services.rules_lock import RulesBusyError

        async def busy(self, content):
            raise RulesBusyError(
                "A Suricata rule update is running. Try again in a few minutes."
            )

        monkeypatch.setattr(EtProManager, "_apply", busy)

        async def run():
            client = await _client(env_file)
            try:
                with (
                    patch.object(etpro_mod, "_run", _Docker()),
                    patch.object(etpro_mod, "preflight", AsyncMock(return_value=200)),
                ):
                    resp = await client.post(
                        "/api/suricata/rules/commercial", json={"code": CODE}
                    )
                return resp.status
            finally:
                await client.close()

        assert _run(run()) == 409

    def test_delete_clears(self, env_file):
        env_file.write_text(f"SURICATA_ETPRO_CODE={CODE}\n")

        async def run():
            client = await _client(env_file)
            try:
                with (
                    patch.object(etpro_mod, "_run", _Docker()),
                    patch.object(EtProManager, "_await_activation", AsyncMock()),
                ):
                    first = await client.delete("/api/suricata/rules/commercial")
                    second = await client.delete("/api/suricata/rules/commercial")
                return first.status, second.status, await second.json()
            finally:
                await client.close()

        assert _run(run()) == (202, 200, {"cleared": False})
        assert not env_file.exists()

    def test_unexpected_error_logs_the_type_only(self, env_file, monkeypatch, caplog):
        async def boom(self, content):
            raise PermissionError(f"/etc/nettap: {content}")

        monkeypatch.setattr(EtProManager, "_apply", boom)

        async def run():
            client = await _client(env_file)
            try:
                with (
                    patch.object(etpro_mod, "_run", _Docker()),
                    patch.object(etpro_mod, "preflight", AsyncMock(return_value=200)),
                ):
                    resp = await client.post(
                        "/api/suricata/rules/commercial", json={"code": CODE}
                    )
                return resp.status, await resp.text()
            finally:
                await client.close()

        with caplog.at_level(logging.DEBUG):
            status, text = _run(run())
        assert status == 500
        assert CODE not in text and CODE not in caplog.text


class TestRunCommand:
    """NET-191 slice 3 review (P5): a timeout is told apart by its exit code, not by its text."""

    def test_a_command_that_runs_too_long_has_no_exit_code(self):
        rc, out = _run(etpro_mod._run("sleep", "30", timeout=0.2))
        assert rc is None and out == "no answer in 0 s"

    @pytest.mark.parametrize(
        "cmd, rc", [(("true",), 0), (("false",), 1), (("sh", "-c", "kill -HUP $$"), -1)]
    )
    def test_a_finished_command_keeps_its_exit_code(self, cmd, rc):
        assert _run(etpro_mod._run(*cmd, timeout=10))[0] == rc
