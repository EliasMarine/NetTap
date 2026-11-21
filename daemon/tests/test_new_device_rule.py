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


# --- NET-339: the same fixed-rule switch for "Tell me when I near my data cap" ----------


def test_data_cap_warnings_are_on_by_default_and_routed(tmp_path, env_file):
    hub = _hub(tmp_path, env_file)
    view = _quick(hub)
    assert view["data_cap"] is True
    assert hub.channels_for("data_cap", 4) == [nc.QUICK_WEBHOOK]


def test_an_existing_setup_gets_the_data_cap_rule_on_when_it_has_a_channel():
    channels = {nc.QUICK_WEBHOOK: {"id": nc.QUICK_WEBHOOK, "type": "webhook"}}
    rules = nc.with_default_event_rules(channels, {}, "2026-11-18T00:00:00+00:00")
    assert rules[nc.QUICK_DATACAP] == {
        "id": nc.QUICK_DATACAP,
        "event_type": "data_cap",
        "channels": [nc.QUICK_WEBHOOK],
        "min_severity": 4,
        "enabled": True,
        "created_at": "2026-11-18T00:00:00+00:00",
    }
    # an off rule is the owner's choice and stays
    off = {nc.QUICK_DATACAP: {"id": nc.QUICK_DATACAP, "enabled": False}}
    assert (
        nc.with_default_event_rules(channels, off, "t")[nc.QUICK_DATACAP]
        == off[nc.QUICK_DATACAP]
    )


def test_turning_data_cap_off_is_kept_and_leaves_new_devices_alone(tmp_path, env_file):
    hub = _hub(tmp_path, env_file)
    _quick(hub)
    assert _quick(hub, data_cap=False)["data_cap"] is False
    assert hub.channels_for("data_cap", 4) == []
    assert hub.channels_for("new_device", 4) == [nc.QUICK_WEBHOOK]
    # a save that leaves it out keeps the off, and so does a restart
    assert _quick(hub)["data_cap"] is False
    assert _hub(tmp_path, env_file).get_quick_settings()["data_cap"] is False
    # and the other way: turning new devices off doesn't touch data cap
    assert _quick(hub, data_cap=True, new_device=False)["data_cap"] is True


def test_a_data_cap_value_that_isnt_a_bool_is_refused(tmp_path, env_file):
    hub = _hub(tmp_path, env_file)
    with pytest.raises(ValueError, match="data_cap"):
        _quick(hub, data_cap="yes")


def test_deleting_the_data_cap_rule_turns_it_off_not_back_on(tmp_path, env_file):
    hub = _hub(tmp_path, env_file)
    _quick(hub)
    assert hub.delete_rule(nc.QUICK_DATACAP) is True
    assert hub.channels_for("data_cap", 4) == []
    # the other fixed rule stays on
    assert hub.channels_for("new_device", 4) == [nc.QUICK_WEBHOOK]
    again = _hub(tmp_path, env_file)  # the load default must not turn it back on
    assert again.get_quick_settings()["data_cap"] is False
    assert again.channels_for("data_cap", 4) == []


def test_an_opt_out_before_any_channel_survives_a_restart_and_the_first_channel(
    tmp_path, env_file
):
    """Codex r1 #6: with no Settings channel the opt-out was dropped and came back on."""
    hub = _hub(tmp_path, env_file)
    hub.set_quick_settings(
        {
            "min_severity": 2,
            "email": {"enabled": False},
            "webhook": {"enabled": False},
            "new_device": False,
            "data_cap": False,
        }
    )
    restarted = _hub(tmp_path, env_file)  # the load default runs on the saved rules
    view = _quick(restarted)  # the first channel, with the switches left out
    assert (view["new_device"], view["data_cap"]) == (False, False)
    assert restarted.channels_for("new_device", 4) == []
    assert restarted.channels_for("data_cap", 4) == []
    assert restarted.channels_for("alert", 2) == [nc.QUICK_WEBHOOK]


# --- F5 (NET-331): the same fixed-rule switch for watched devices ------------------------


def test_watched_devices_are_on_by_default_at_low_and_routed(tmp_path, env_file):
    hub = _hub(tmp_path, env_file)
    assert _quick(hub)["watched_device"] is True
    assert hub.channels_for("watched_device", 4) == [nc.QUICK_WEBHOOK]


def test_an_existing_setup_gets_the_watched_rule_on_when_it_has_a_channel():
    channels = {nc.QUICK_WEBHOOK: {"id": nc.QUICK_WEBHOOK, "type": "webhook"}}
    rules = nc.with_default_event_rules(channels, {}, "2026-11-20T00:00:00+00:00")
    assert rules[nc.QUICK_WATCHED] == {
        "id": nc.QUICK_WATCHED,
        "event_type": "watched_device",
        "channels": [nc.QUICK_WEBHOOK],
        "min_severity": 4,
        "enabled": True,
        "created_at": "2026-11-20T00:00:00+00:00",
    }


def test_a_quick_save_keeps_and_sets_the_watched_switch(tmp_path, env_file):
    hub = _hub(tmp_path, env_file)
    _quick(hub)
    assert _quick(hub, watched_device=False)["watched_device"] is False
    assert hub.channels_for("watched_device", 2) == []
    # the other fixed rules are untouched
    assert hub.channels_for("new_device", 4) == [nc.QUICK_WEBHOOK]
    assert hub.channels_for("data_cap", 4) == [nc.QUICK_WEBHOOK]
    # left out keeps the off, and so does a restart
    assert _quick(hub)["watched_device"] is False
    again = _hub(tmp_path, env_file)
    assert again.get_quick_settings()["watched_device"] is False
    assert _quick(again, watched_device=True)["watched_device"] is True
    assert again.channels_for("watched_device", 4) == [nc.QUICK_WEBHOOK]
    with pytest.raises(ValueError, match="watched_device"):
        _quick(again, watched_device="yes")


def test_deleting_the_watched_rule_stays_off_until_the_switch_turns_it_on(
    tmp_path, env_file
):
    hub = _hub(tmp_path, env_file)
    _quick(hub)
    assert hub.delete_rule(nc.QUICK_WATCHED) is True
    assert hub.channels_for("watched_device", 2) == []
    again = _hub(tmp_path, env_file)  # the load default must not turn it back on
    assert again.get_quick_settings()["watched_device"] is False
    assert again.channels_for("watched_device", 2) == []
    assert _quick(again, watched_device=True)["watched_device"] is True
    assert again.channels_for("watched_device", 2) == [nc.QUICK_WEBHOOK]


def test_a_custom_channel_only_setup_routes_watched_devices_by_its_own_rule(
    tmp_path, env_file
):
    hub = _hub(tmp_path, env_file)
    cid = hub.configure("webhook", {"url": "https://hooks.example.net/y"})["id"]
    body = {"event_type": "watched_device", "min_severity": 4, "channels": [cid]}
    assert nc.validate_rule(body, {cid}) is None
    hub.add_rule("watched_device", [cid], 4)
    assert nc.QUICK_WATCHED not in {r["id"] for r in hub.get_rules()}
    assert hub.channels_for("watched_device", 4) == [cid]
