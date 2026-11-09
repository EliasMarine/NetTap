"""NET-224 × NET-227: a backup restore of notification settings goes through the running hub.

It is live at once, an empty section clears, a channel the hub or the dispatcher can't use is
refused as a whole (nothing changes, in memory or on disk), and no reader sees half a restore."""

import asyncio
import json
import os
import sys
import threading
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import notification_config as nc  # noqa: E402
from services.notification_dispatcher import AlertDispatcher  # noqa: E402
from services.notification_hub import NotificationHub  # noqa: E402

HOOK = "https://hooks.example.net/T0KEN"


@pytest.fixture
def paths(tmp_path):
    env = tmp_path / ".env"
    env.write_text("")
    return tmp_path / "notifications.json", env


@pytest.fixture
def hub(paths):
    config, env = paths
    return NotificationHub(config_path=str(config), env_file=str(env))


def _slack(cid, enabled=True):
    return {"id": cid, "type": "slack", "name": cid, "config": {}, "enabled": enabled}


def test_a_restore_is_live_at_once_and_saved_private(hub, paths):
    old = hub.configure("webhook", {"url": HOOK})
    hub.add_rule("alert", [old["id"]], 2)

    hub.restore_backup(
        {
            "notification_channels": {"s1": _slack("s1")},
            "notification_rules": {
                "r1": {"id": "r1", "event_type": "alert", "channels": ["s1"]}
            },
        }
    )

    assert [c["id"] for c in hub.get_channels()] == ["s1"]
    assert hub.channels_for("alert", 4) == ["s1"]
    saved = json.loads(paths[0].read_text())
    assert list(saved["channels"]) == ["s1"] and list(saved["rules"]) == ["r1"]
    assert paths[0].stat().st_mode & 0o777 == 0o600


def test_an_empty_section_clears_and_a_missing_one_keeps(hub):
    ch = hub.configure("webhook", {"url": HOOK})
    rule = hub.add_rule("alert", [ch["id"]], 2)

    hub.restore_backup({"notification_rules": {}})
    assert hub.get_rules() == [] and [c["id"] for c in hub.get_channels()] == [ch["id"]]

    hub.restore_backup({"notification_channels": {}})
    assert hub.get_channels() == []

    hub.restore_backup({"notification_rules": {rule["id"]: rule}})
    assert [r["id"] for r in hub.get_rules()] == [rule["id"]]


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "slack", "config": {}},  # no id
        {"id": "other", "type": "slack", "config": {}},  # id isn't its key
        {"id": "bad", "config": {}},  # no type
        {"id": "bad", "type": "fax", "config": {}},  # unknown type
        {"id": "bad", "type": "slack", "config": []},  # config isn't an object
        {
            "id": "bad",
            "type": "webhook",
            "config": {"url": "http://["},
        },  # urlsplit raises
        {"id": "bad", "type": "webhook", "config": {"url": "file:///etc/passwd"}},
        "not an object",
    ],
)
def test_a_channel_the_hub_cant_use_is_refused_and_nothing_changes(hub, paths, bad):
    kept = hub.configure("webhook", {"url": HOOK})
    before = paths[0].read_bytes()

    with pytest.raises(ValueError, match="'bad'"):
        hub.restore_backup({"notification_channels": {"ok": _slack("ok"), "bad": bad}})

    assert [c["id"] for c in hub.get_channels()] == [kept["id"]]
    assert paths[0].read_bytes() == before


def test_a_failed_write_changes_nothing(hub):
    kept = hub.configure("webhook", {"url": HOOK})
    with (
        patch(
            "services.notification_hub.write_file_atomic",
            side_effect=OSError(28, "No space left on device"),
        ),
        pytest.raises(OSError),
    ):
        hub.restore_backup({"notification_channels": {}})
    assert [c["id"] for c in hub.get_channels()] == [kept["id"]]


def test_a_broken_channel_in_the_file_is_skipped_so_nothing_raises(paths, caplog):
    config, env = paths
    config.write_text(
        json.dumps(
            {
                "channels": {
                    "good": _slack("good"),
                    "noid": {"type": "slack", "config": {}},
                    "badurl": {
                        "id": "badurl",
                        "type": "webhook",
                        "config": {"url": "http://["},
                    },
                },
                "rules": {
                    "r": {
                        "id": "r",
                        "event_type": "alert",
                        "channels": ["good", "noid", "badurl"],
                    }
                },
            }
        )
    )
    hub = NotificationHub(config_path=str(config), env_file=str(env))

    assert [c["id"] for c in hub.get_channels()] == ["good"]
    assert "noid" in caplog.text and "badurl" in caplog.text
    hub.public_channels()
    hub.get_quick_settings()
    dispatcher = AlertDispatcher(
        hub, client=object(), lan_cidrs=list, state_path=str(config.parent / "d.json")
    )
    with patch("services.alert_intelligence.get_smart_alerts", return_value=[]):
        asyncio.run(dispatcher.poll_once())


def test_url_helpers_never_raise_on_a_malformed_url():
    assert nc.url_hint("http://[") == ""
    assert nc.url_problem("http://[") == "the URL isn't valid"


def _blocking_write(entered, release):
    real = __import__(
        "services.capture_config", fromlist=["write_file_atomic"]
    ).write_file_atomic

    def write(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return real(*args, **kwargs)

    return write


def test_a_reader_waits_for_a_restore_and_sees_only_the_new_config(hub):
    """Before: x off with a rule to it. After: x on, no rules. Routing must never say x."""
    hub.restore_backup(
        {
            "notification_channels": {"x": _slack("x", enabled=False)},
            "notification_rules": {
                "r": {"id": "r", "event_type": "alert", "channels": ["x"]}
            },
        }
    )
    entered, release = threading.Event(), threading.Event()
    routed: list = []
    with patch(
        "services.notification_hub.write_file_atomic",
        side_effect=_blocking_write(entered, release),
    ):
        restore = threading.Thread(
            target=hub.restore_backup,
            args=(
                {
                    "notification_channels": {"x": _slack("x")},
                    "notification_rules": {},
                },
            ),
        )
        restore.start()
        assert entered.wait(5)
        reader = threading.Thread(
            target=lambda: routed.append(hub.channels_for("alert", 1))
        )
        reader.start()
        reader.join(0.3)
        assert reader.is_alive()  # it waits for the restore to finish
        release.set()
        restore.join(5)
        reader.join(5)
    assert routed == [[]]


def test_a_change_during_a_restore_is_kept_with_the_restored_channels(hub):
    entered, release = threading.Event(), threading.Event()
    with patch(
        "services.notification_hub.write_file_atomic",
        side_effect=_blocking_write(entered, release),
    ):
        restore = threading.Thread(
            target=hub.restore_backup,
            args=({"notification_channels": {"s1": _slack("s1")}},),
        )
        restore.start()
        assert entered.wait(5)
        added: list = []
        change = threading.Thread(
            target=lambda: added.append(hub.configure("webhook", {"url": HOOK})["id"])
        )
        change.start()
        change.join(0.3)
        release.set()
        restore.join(5)
        change.join(5)
    assert sorted(c["id"] for c in hub.get_channels()) == sorted(["s1", *added])


def test_after_a_restore_turns_a_channel_off_a_new_one_with_its_rule_gets_the_alerts(
    hub,
):
    """The report's recovery steps: a new channel has a new id, so its rule is added again."""
    warnings = hub.restore_backup(
        {
            "notification_channels": {
                "hook": {
                    "id": "hook",
                    "type": "webhook",
                    "name": "Hook",
                    "config": {},
                    "secrets_left_out": ["url"],
                },
                nc.QUICK_WEBHOOK: {
                    "id": nc.QUICK_WEBHOOK,
                    "type": "webhook",
                    "name": "Webhook (Settings)",
                    "config": {},
                    "secrets_left_out": ["url"],
                },
            },
            "notification_rules": {
                "r": {"id": "r", "event_type": "alert", "channels": ["hook"]}
            },
        }
    )
    assert hub.channels_for("alert", 1) == []
    page = next(w for w in warnings if "Hook" in w)
    assert "Notification channels page" in page and "routing rules" in page
    assert any("Turn it on in Settings › Notifications" in w for w in warnings)

    new = hub.configure("webhook", {"url": HOOK, "name": "Hook"})
    hub.add_rule("alert", [new["id"]], 4)
    assert hub.channels_for("alert", 1) == [new["id"]]
