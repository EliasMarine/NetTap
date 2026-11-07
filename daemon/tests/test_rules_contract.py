"""NET-191 slice 2: the exact keys of every rule-status reply, checked against the web's TypeScript types.

The Settings page reads these fields by name (web/src/lib/api/suricata-rules.ts). A rename on either
side breaks this test instead of showing "undefined" on the page.
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from api.suricata_rules import register_suricata_rules_routes
from services import etpro as etpro_mod
from services import owner_rules as owner_mod
from services import rules_lock
from services import suricata_rules as sr
from services.etpro import EtProManager
from services.suricata_rules import SuricataRuleManager

WEB_TYPES = (
    Path(__file__).resolve().parents[2]
    / "web"
    / "src"
    / "lib"
    / "api"
    / "suricata-rules.ts"
)
pytestmark = pytest.mark.skipif(
    not WEB_TYPES.exists(), reason="needs the web sources beside the daemon"
)

CODE = "CANARYa1b2c3d4e5f6g7h8"
ENGINE_KEYS = {"loaded", "failed", "reload_time"}
ACTIVATION_KEYS = {
    "state", "finished_at", "rules_loaded", "rules_failed", "etpro_rules", "enabled_sources",
    "update_state", "message",
}  # fmt: skip


def ts_fields(interface: str) -> set:
    """Top-level field names of a TypeScript interface (tab-indented, one per line)."""
    body = re.search(
        rf"export interface {interface} \{{\n(.*?)\n\}}", WEB_TYPES.read_text(), re.S
    )
    assert body, f"interface {interface} not found in {WEB_TYPES}"
    return set(re.findall(r"^\t(\w+)\??:", body.group(1), re.M))


def ts_object_fields(interface: str, field: str) -> set:
    """Field names of an inline object type, e.g. `engine?: { loaded: number; ... } | null;`."""
    text = WEB_TYPES.read_text()
    block = re.search(
        rf"export interface {interface} \{{\n(.*?)\n\}}", text, re.S
    ).group(1)
    inline = re.search(rf"^\t{field}\??: (?:null \| )?\{{(.*?)\}}", block, re.M | re.S)
    assert inline, f"{interface}.{field} is not an inline object type"
    return set(re.findall(r"(\w+)\??:", inline.group(1)))


STATS = (
    '{"message": [{"id": 0, "rules_loaded": 65378, "rules_failed": 0}], "return": "OK"}'
)
RELOAD = '{"message": [{"id": 0, "last_reload": "2026-11-07T00:01:12.123456+0000"}], "return": "OK"}'
LIVE_OUT = (
    "ENABLED 65378\nDISABLED 16031\nETPRO 0\nMTIME 1793577636\nSOURCE et/open\nCRON 0 0 * * *\n"
    f"ENABLED_SOURCE et/open\nOWNER 1\nSTATS {STATS}\nRELOAD {RELOAD}\n"
).encode()


def _proc(rc: int, out: bytes):
    proc = AsyncMock()
    proc.returncode = rc
    proc.communicate = AsyncMock(return_value=(out, b""))
    return proc


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(rules_lock, "RULES_STATE_DIR", str(tmp_path))
    record = {"attempt": "2026-11-07T00:00:01Z", "exit_code": 0, "state": "active", "reason": "",
              "last_success": "2026-11-07T00:00:01Z", "last_activation": "2026-11-07T00:01:12Z"}  # fmt: skip
    (tmp_path / "update-status.json").write_text(json.dumps(record))
    return tmp_path


def _call(method: str, path: str, *, env_file=None, prepare=None, body=None) -> tuple:
    async def run():
        app = web.Application()
        register_suricata_rules_routes(app, SuricataRuleManager(container_name="live"))
        if env_file:
            app["etpro_manager"]._env_file = str(env_file)
        if prepare:
            await prepare(app)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            resp = await client.request(method, path, json=body)
            return resp.status, await resp.json()
        finally:
            await client.close()

    return asyncio.run(run())


class TestLiveStatus:
    def test_keys_match_live_rule_status(self, state):
        with patch(
            "asyncio.create_subprocess_exec", AsyncMock(return_value=_proc(0, LIVE_OUT))
        ):
            status, body = _call("GET", "/api/suricata/rules/live")
        assert status == 200
        assert set(body) == ts_fields("LiveRuleStatus")
        assert (
            set(body["engine"])
            == ENGINE_KEYS
            == ts_object_fields("LiveRuleStatus", "engine")
        )
        assert set(body["update"]) == ts_fields("RuleUpdateStatus")
        assert body["owner_rules"] == 1


class TestUpdateNow:
    def test_done_keys_match_rule_update_result(self, state):
        with patch(
            "asyncio.create_subprocess_exec", AsyncMock(return_value=_proc(0, b"ok"))
        ):
            status, body = _call("POST", "/api/suricata/rules/update")
        assert status == 200
        assert set(body) == ts_fields("RuleUpdateResult") - {"running"}
        assert set(body["status"]) == ts_fields("RuleUpdateStatus")

    def test_still_running_is_202_with_running_true(self, state, monkeypatch):
        monkeypatch.setattr(sr, "RULES_UPDATE_WAIT_S", 0.05)
        proc = AsyncMock()

        async def slow():
            await asyncio.sleep(10)
            return b"", None

        proc.communicate = slow
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            status, body = _call("POST", "/api/suricata/rules/update")
        assert status == 202
        assert body["running"] is True and body["success"] is False
        assert set(body) == ts_fields("RuleUpdateResult")
        assert set(body["status"]) == ts_fields("RuleUpdateStatus")


class TestEtPro:
    def test_status_keys_match_et_pro_status(self, state, tmp_path, monkeypatch):
        env_file = tmp_path / "suricata.env"
        env_file.write_text(f"SURICATA_ETPRO_CODE={CODE}\n")
        monkeypatch.setattr(etpro_mod, "READY_POLL_S", 0)
        live = {"available": True, "enabled_sources": ["et/pro"], "etpro_rules": 41000,
                "engine": {"loaded": 9, "failed": 0, "reload_time": "2999-01-01T00:00:00.000000+0000"},
                "update": {"state": "active", "reason": ""}}  # fmt: skip

        async def activated(app):
            manager: EtProManager = app["etpro_manager"]
            manager._rules.get_live_status = AsyncMock(return_value=live)
            await manager._await_activation(datetime.now(timezone.utc))

        status, body = _call(
            "GET",
            "/api/suricata/rules/commercial",
            env_file=env_file,
            prepare=activated,
        )
        assert status == 200
        assert set(body) == ts_fields("EtProStatus")
        assert (
            set(body["activation"])
            == ACTIVATION_KEYS
            == ts_object_fields("EtProStatus", "activation")
        )
        assert CODE not in json.dumps(body)

    def test_change_keys_are_ones_et_pro_change_names(self, state, tmp_path):
        env_file = tmp_path / "suricata.env"
        change = ts_fields("EtProChange")

        async def docker(*cmd, timeout):
            return (
                (0, "This is Suricata version 8.0.7 RELEASE")
                if cmd[-1] == "-V"
                else (0, "")
            )

        with (
            patch.object(etpro_mod, "_run", docker),
            patch.object(etpro_mod, "preflight", AsyncMock(return_value=200)),
            patch.object(EtProManager, "_await_activation", AsyncMock()),
        ):
            saved = _call(
                "POST",
                "/api/suricata/rules/commercial",
                env_file=env_file,
                body={"code": CODE},
            )
            cleared = _call(
                "DELETE", "/api/suricata/rules/commercial", env_file=env_file
            )
            again = _call("DELETE", "/api/suricata/rules/commercial", env_file=env_file)
            refused = _call(
                "POST",
                "/api/suricata/rules/commercial",
                env_file=env_file,
                body={"code": "short"},
            )
        assert saved == (202, {"saved": True, "applying": True})
        assert cleared == (202, {"cleared": True, "applying": True})
        assert again == (200, {"cleared": False})
        assert refused[0] == 400 and set(refused[1]) == {"error"}
        for _, body in (saved, cleared, again, refused):
            assert set(body) <= change


RULE = 'alert dns any any -> any any (msg:"t"; dns.query; content:"x.invalid"; sid:1000001; rev:1;)\n'


class TestOwnerRules:
    """NET-191 slice 3: GET, check and save answer with the fields web/src/lib/api/suricata-rules.ts names."""

    @pytest.fixture
    def custom(self, state, tmp_path, monkeypatch):
        from tests.test_owner_rules import FakeDocker

        custom, staging = tmp_path / "custom", tmp_path / "staging"
        custom.mkdir()
        staging.mkdir()
        monkeypatch.setattr(owner_mod, "CUSTOM_DIR", str(custom))
        monkeypatch.setattr(owner_mod, "STAGING_DIR", str(staging))
        monkeypatch.setattr(owner_mod, "THRESHOLD_FILE", str(tmp_path / "none"))
        monkeypatch.setattr(owner_mod, "_run", FakeDocker("/host/staging", str(custom)))
        return custom

    def test_get_keys_match_owner_rules(self, custom):
        status, body = _call("GET", "/api/suricata/rules/custom")
        assert status == 200
        assert set(body) == ts_fields("OwnerRules")
        assert (
            body["content"] == "" and (custom / "owner.rules").exists()
        )  # made at start

    def test_check_keys(self, custom):
        good = _call("POST", "/api/suricata/rules/custom/check", body={"content": RULE})
        bad = _call(
            "POST",
            "/api/suricata/rules/custom/check",
            body={"content": "drop" + RULE[5:]},
        )
        assert good == (200, {"ok": True, "rule_count": 1})
        assert bad[0] == 400 and set(bad[1]) == {"error", "errors"}
        assert set(bad[1]["errors"][0]) == ts_fields("OwnerRuleError")
        assert (custom / "owner.rules").read_text() == ""  # a check never saves

    def test_save_keys_match_owner_rules_save_result(self, custom):
        status, body = _call(
            "POST", "/api/suricata/rules/custom", body={"content": RULE}
        )
        assert status == 200
        assert set(body) == ts_fields("OwnerRulesSaveResult")
        assert set(body["engine"]) == ts_object_fields("OwnerRulesSaveResult", "engine")
        assert (custom / "owner.rules").read_text() == RULE

    @pytest.mark.parametrize("body", [None, {"content": 5}, ["x"]])
    def test_save_without_text_is_400(self, custom, body):
        status, reply = _call("POST", "/api/suricata/rules/custom", body=body)
        assert status == 400 and set(reply) == {"error", "errors"}

    def test_save_refused_by_suricata_is_422_with_lines(self, custom):
        from tests.test_owner_rules import REFUSED

        owner_mod._run.test = (1, REFUSED)
        status, body = _call(
            "POST", "/api/suricata/rules/custom", body={"content": RULE}
        )
        assert status == 422
        assert body["errors"] == [
            {"line": 2, "message": "unknown rule keyword 'nosuchkeyword'."}
        ]
        assert (custom / "owner.rules").read_text() == ""

    def test_unexpected_failure_is_500_without_detail(self, custom, monkeypatch):
        monkeypatch.setattr(
            owner_mod.OwnerRules, "save", AsyncMock(side_effect=OSError(RULE))
        )
        status, body = _call(
            "POST", "/api/suricata/rules/custom", body={"content": RULE}
        )
        assert status == 500 and RULE not in json.dumps(body)
