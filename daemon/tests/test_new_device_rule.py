"""The Settings tab's "Tell me about new devices" and rule on/off (NET-319)."""

import json

import pytest

from services import notification_config as nc
from services.notification_hub import NotificationHub


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text("")
    return path


def _hub(tmp_path, env_file) -> NotificationHub:
    return NotificationHub(config_path=str(tmp_path / "n.json"), env_file=str(env_file))


def _quick(hub: NotificationHub, **extra) -> dict:
    return hub.set_quick_settings(
        {
            "min_severity": 2,
            "email": {"enabled": False},
            "webhook": {"enabled": True, "url": "https://hooks.example.net/x"},
            **extra,
        }
    )


def test_new_devices_are_on_by_default_and_routed(tmp_path, env_file):
    hub = _hub(tmp_path, env_file)
    view = _quick(hub)
    assert view["new_device"] is True
    assert hub.channels_for("new_device", 3) == [nc.QUICK_WEBHOOK]


def test_turning_new_devices_off_keeps_the_rule_off(tmp_path, env_file):
    hub = _hub(tmp_path, env_file)
    _quick(hub)
    assert _quick(hub, new_device=False)["new_device"] is False
    assert hub.channels_for("new_device", 3) == []
    assert hub.channels_for("alert", 2) == [nc.QUICK_WEBHOOK]  # alerts unaffected
    # a save that leaves it out keeps the off
    assert _quick(hub)["new_device"] is False
    again = _hub(tmp_path, env_file)  # a restart doesn't turn it back on
    assert again.get_quick_settings()["new_device"] is False
    assert again.channels_for("new_device", 3) == []


def test_a_bad_value_is_refused(tmp_path, env_file):
    hub = _hub(tmp_path, env_file)
    with pytest.raises(ValueError, match="new_device"):
        _quick(hub, new_device="yes")


def test_deleting_the_fixed_rule_turns_it_off_not_back_on(tmp_path, env_file):
    hub = _hub(tmp_path, env_file)
    _quick(hub)
    assert hub.delete_rule(nc.QUICK_NEWDEVICE) is True
    assert hub.channels_for("new_device", 3) == []
    again = _hub(tmp_path, env_file)
    assert again.get_quick_settings()["new_device"] is False
    assert again.channels_for("new_device", 3) == []


def test_an_existing_setup_gets_new_devices_once_at_load(tmp_path, env_file):
    path = tmp_path / "n.json"
    channel = {
        "id": nc.QUICK_WEBHOOK,
        "type": "webhook",
        "name": "Webhook (Settings)",
        "config": {"url": "https://hooks.example.net/x"},
        "enabled": True,
    }
    alert_rule = {
        "id": nc.QUICK_RULE,
        "event_type": "alert",
        "channels": [nc.QUICK_WEBHOOK],
        "min_severity": 2,
    }
    path.write_text(
        json.dumps(
            {
                "channels": {nc.QUICK_WEBHOOK: channel},
                "rules": {nc.QUICK_RULE: alert_rule},
            }
        )
    )
    hub = _hub(tmp_path, env_file)
    assert hub.channels_for("new_device", 3) == [nc.QUICK_WEBHOOK]
    saved = json.loads(path.read_text())["rules"]
    assert saved[nc.QUICK_NEWDEVICE]["enabled"] is True
    # idempotent: a second load writes nothing new
    before = path.read_text()
    _hub(tmp_path, env_file)
    assert path.read_text() == before


def test_a_setup_without_settings_channels_gets_no_rule(tmp_path, env_file):
    hub = _hub(tmp_path, env_file)
    assert hub.get_rules() == []
    assert hub.channels_for("new_device", 3) == []


def test_any_rule_turned_off_is_skipped(tmp_path, env_file):
    hub = _hub(tmp_path, env_file)
    cid = hub.configure("webhook", {"url": "https://hooks.example.net/y"})["id"]
    rule = hub.add_rule("alert", [cid], 4)
    rules = {
        **{r["id"]: r for r in hub.get_rules()},
        rule["id"]: {**rule, "enabled": False},
    }
    hub._commit(hub._channels, rules)
    assert hub.channels_for("alert", 1) == []


def test_a_restored_backup_from_before_gets_the_default(tmp_path, env_file):
    hub = _hub(tmp_path, env_file)
    _quick(hub, new_device=False)
    old_rules = {r["id"]: r for r in hub.get_rules() if r["id"] != nc.QUICK_NEWDEVICE}
    hub.restore_backup({"notification_rules": old_rules})
    assert hub.get_quick_settings()["new_device"] is True
