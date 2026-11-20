"""NET-330: quiet hours are kept by the hub through every save, set from Settings › Notifications
(GET and PUT name the owner's zone), and carried by a config backup: exported as this version
accepts them, refused in preflight when bad, and restored with a note when the zone differs."""

import json
import logging
import os
import sys
import tempfile
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.notifications_hub import register_notification_hub_routes  # noqa: E402
from services import owner_tz, quiet_hours  # noqa: E402
from services.config_backup import _SCHEMA_VERSION, ConfigBackup  # noqa: E402
from services.notification_hub import NotificationHub  # noqa: E402

HOOK = "https://hooks.example.net/x"
ON = {"enabled": True, "start": "23:00", "end": "06:30", "critical_through": False}
# not valid quiet hours, each with its reason (problem() says why)
BAD_BY_NAME = {
    "Arabic-Indic digits": {**ON, "start": "0٠:0٠"},
    "a trailing newline": {**ON, "end": "07:00\n"},
    "24:00": {**ON, "end": "24:00"},
    "start equals end": {**ON, "end": ON["start"]},
    "enabled not a bool": {**ON, "enabled": "yes"},
    "an extra key": {**ON, "extra": 1},
    "a string": "22:00-07:00",
    "null": None,
}
BAD = list(BAD_BY_NAME.values())


@pytest.fixture
def owner_zone(tmp_path, monkeypatch):
    """The owner's zone file, Europe/London."""
    path = tmp_path / "owner-timezone.json"
    monkeypatch.setenv("OWNER_TZ_FILE", str(path))
    owner_tz.write("Europe/London", str(path))
    return "Europe/London"


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text("")
    return path


@pytest.fixture
def config(tmp_path):
    return tmp_path / "notifications.json"


@pytest.fixture
def hub(config, env_file):
    return NotificationHub(config_path=str(config), env_file=str(env_file))


def _quick(hub, **extra):
    return hub.set_quick_settings(
        {"min_severity": 2, "email": {}, "webhook": {}, **extra}
    )


def _saved_quiet(config):
    return json.loads(config.read_text())["quiet"]


# ---------------------------------------------------------------------------
# Hub
# ---------------------------------------------------------------------------


def _delete_channel(hub):
    hub.delete_channel(hub.configure("webhook", {"url": HOOK})["id"])


def _delete_rule(hub):
    ch = hub.configure("webhook", {"url": HOOK})
    hub.delete_rule(hub.add_rule("alert", [ch["id"]], 2)["id"])


SAVES = {
    "configure a channel": lambda hub: hub.configure("webhook", {"url": HOOK}),
    "delete a channel": _delete_channel,
    "add a rule": lambda hub: hub.add_rule(
        "alert", [hub.configure("webhook", {"url": HOOK})["id"]], 2
    ),
    "delete a rule": _delete_rule,
    "save quick settings without quiet": _quick,
    "restore a backup without the section": lambda hub: hub.restore_backup(
        {"notification_rules": {}}
    ),
}


@pytest.mark.parametrize("save", SAVES.values(), ids=SAVES.keys())
def test_every_save_keeps_quiet_hours(hub, config, save):
    _quick(hub, quiet=ON)

    save(hub)

    assert hub.quiet() == ON
    assert _saved_quiet(config) == ON  # old code: _commit wrote channels and rules only


def test_quiet_is_a_copy(hub):
    hub.quiet()["enabled"] = True
    assert hub.quiet() == quiet_hours.DEFAULT


def test_saved_quiet_hours_load_and_survive_the_event_rule_seed(config, env_file):
    # a Settings channel with no event rules: loading saves the default rules at once
    channel = {"id": "settings-webhook", "type": "webhook", "config": {"url": HOOK}}
    config.write_text(
        json.dumps(
            {"channels": {"settings-webhook": channel}, "rules": {}, "quiet": ON}
        )
    )

    hub = NotificationHub(config_path=str(config), env_file=str(env_file))

    assert hub.quiet() == ON
    saved = json.loads(config.read_text())
    assert "settings-newdevice" in saved["rules"]  # the seed did save
    assert saved["quiet"] == ON


def test_an_invalid_saved_value_reads_as_the_default_with_one_warning(
    config, env_file, caplog
):
    config.write_text(
        json.dumps({"channels": {}, "rules": {}, "quiet": {**ON, "end": "25:00"}})
    )
    with caplog.at_level(logging.WARNING):
        hub = NotificationHub(config_path=str(config), env_file=str(env_file))

    assert hub.quiet() == quiet_hours.DEFAULT
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "quiet hours" in warnings[0].getMessage()


def test_a_config_from_before_quiet_hours_loads_without_a_warning(
    config, env_file, caplog
):
    config.write_text(json.dumps({"channels": {}, "rules": {}}))
    with caplog.at_level(logging.WARNING):
        hub = NotificationHub(config_path=str(config), env_file=str(env_file))

    assert hub.quiet() == quiet_hours.DEFAULT
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_a_first_start_seeded_from_the_environment_writes_the_default(config, env_file):
    env_file.write_text(f"WEBHOOK_URL={HOOK}\n")

    NotificationHub(config_path=str(config), env_file=str(env_file))

    assert _saved_quiet(config) == quiet_hours.DEFAULT


def test_a_restore_with_a_bad_section_raises_and_changes_nothing(hub, config):
    _quick(hub, quiet=ON)
    before = config.read_text()

    with pytest.raises(ValueError):
        hub.restore_backup({"notification_quiet": {**ON, "start": "7am"}})

    assert hub.quiet() == ON and config.read_text() == before


# ---------------------------------------------------------------------------
# Settings › Notifications: GET and PUT /api/notifications/config
# ---------------------------------------------------------------------------


class QuietHoursApiTest(AioHTTPTestCase):
    async def get_application(self):
        self.dir = tempfile.mkdtemp()
        zone_file = os.path.join(self.dir, "owner-timezone.json")
        owner_tz.write("America/New_York", zone_file)
        env = patch.dict(os.environ, {"OWNER_TZ_FILE": zone_file})
        env.start()
        self.addCleanup(env.stop)
        env_file = os.path.join(self.dir, ".env")
        open(env_file, "w").close()
        self.config = os.path.join(self.dir, "n.json")
        self.hub = NotificationHub(config_path=self.config, env_file=env_file)
        app = web.Application()
        register_notification_hub_routes(app, self.hub)
        return app

    async def _put(self, **extra):
        body = {"min_severity": 2, "email": {}, "webhook": {}, **extra}
        resp = await self.client.put("/api/notifications/config", json=body)
        return resp.status, await resp.json()

    async def test_get_names_the_setting_and_the_owners_zone(self):
        got = await (await self.client.get("/api/notifications/config")).json()
        self.assertEqual(got["quiet"], quiet_hours.DEFAULT)
        self.assertEqual(got["tz"], "America/New_York")

    async def test_put_saves_and_its_reply_names_the_zone(self):
        status, reply = await self._put(quiet=ON)
        self.assertEqual(status, 200, reply)
        self.assertEqual(reply["quiet"], ON)
        self.assertEqual(reply["tz"], "America/New_York")
        self.assertEqual(self.hub.quiet(), ON)
        with open(self.config) as f:
            self.assertEqual(json.load(f)["quiet"], ON)

    async def test_put_without_quiet_keeps_the_saved_setting(self):
        await self._put(quiet=ON)
        status, reply = await self._put(min_severity=1)
        self.assertEqual(status, 200, reply)
        self.assertEqual(reply["quiet"], ON)
        self.assertEqual(self.hub.quiet(), ON)

    async def test_put_with_bad_quiet_is_a_400_with_the_reason(self):
        await self._put(quiet=ON)
        for bad in BAD:
            with self.subTest(bad=bad):
                status, reply = await self._put(quiet=bad)
                self.assertEqual(status, 400)
                self.assertEqual(reply["error"], quiet_hours.problem(bad))
                self.assertEqual(self.hub.quiet(), ON)


# ---------------------------------------------------------------------------
# Config backup
# ---------------------------------------------------------------------------


@pytest.fixture
def backup(tmp_path, config, env_file, owner_zone):
    paths = {
        "notification_config": str(config),
        "env_file": str(env_file),
        "bandwidth_cap": str(tmp_path / "bandwidth_cap.json"),
        "excluded_ips": str(tmp_path / "excluded_ips.json"),
        "capture_config": str(tmp_path / "capture-mode.conf"),
        "retention_config": str(tmp_path / "retention.json"),
        "home_location": str(tmp_path / "home_location.json"),
        "alert_acks": str(tmp_path / "alert_acks.json"),
        "suppressions": str(tmp_path / "nettap-suppress.json"),
    }
    hub = NotificationHub(config_path=str(config), env_file=str(env_file))
    return ConfigBackup(config_paths=paths, notification_hub=hub)


def _data(sections):
    return {"metadata": {"schema_version": _SCHEMA_VERSION}, "sections": sections}


@pytest.mark.parametrize(
    "saved, exported",
    [
        (ON, ON),
        ({**ON, "start": "22:00:00"}, quiet_hours.DEFAULT),  # a hand edit
        (None, quiet_hours.DEFAULT),  # no quiet key at all
    ],
)
def test_export_is_a_setting_this_version_accepts_with_the_zone(
    backup, config, saved, exported
):
    data = {"channels": {}, "rules": {}}
    config.write_text(json.dumps(data if saved is None else {**data, "quiet": saved}))

    section = backup.export_config()["sections"]["notification_quiet"]

    assert section == {**exported, "tz": "Europe/London"}
    assert quiet_hours.problem(section) is None


@pytest.mark.parametrize("bad", BAD, ids=BAD_BY_NAME.keys())
def test_preflight_refuses_a_bad_section_with_the_reason(backup, bad):
    result = backup.validate_import(_data({"notification_quiet": bad}))

    assert result["is_valid"] is False
    assert quiet_hours.problem(bad) in result["errors"]


def test_restore_applies_the_section_and_notes_another_zone(backup, config):
    result = backup.import_config(
        _data({"notification_quiet": {**ON, "tz": "Asia/Tokyo"}})
    )

    assert result["success"] is True and result["applied"] == ["notification_quiet"]
    assert backup._notification_hub.quiet() == ON
    assert _saved_quiet(config) == ON
    assert (
        "Quiet hours in this backup were set for Asia/Tokyo; this NetTap uses "
        "Europe/London. Times follow this NetTap's zone (Settings › Display)."
    ) in result["warnings"]


def test_restore_in_the_same_zone_adds_no_note(backup):
    result = backup.import_config(
        _data({"notification_quiet": {**ON, "tz": "Europe/London"}})
    )

    assert backup._notification_hub.quiet() == ON
    assert not any("Quiet hours" in w for w in result["warnings"])


def test_a_backup_without_the_section_keeps_the_boxs_setting(backup, config):
    _quick(backup._notification_hub, quiet=ON)

    result = backup.import_config(_data({"notification_rules": {}}))

    assert result["success"] is True
    assert backup._notification_hub.quiet() == ON
    assert _saved_quiet(config) == ON
