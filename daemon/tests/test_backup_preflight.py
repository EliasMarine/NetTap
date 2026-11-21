"""NET-344: one content check for validate, import and export (plan §2.4, §2.5, §5 "Preflight").

section_errors finds every content problem today's import found while applying, before anything
applies, so a backup with one bad section now changes nothing. Also: the left-out count in the
metadata, the 10,000 excluded-IP cap, duplicates, the atomic excluded-IP writers, and suppression
reasons stored as text.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import services.alert_intelligence as alert_intelligence
from api.alerts import handle_false_positive, handle_suppress_alert
from api.settings import register_settings_routes
from services.config_backup import BackupRefused, ConfigBackup, section_errors
from services.device_custom import DeviceCustomStore
from services.excluded_ips import EXCLUDED_IPS_MAX, load_excluded_ips, save_excluded_ips
from services.notification_hub import NotificationHub

MAC = "AA:BB:CC:DD:EE:01"
CAP = {"monthly_cap_bytes": 500_000_000_000}
OLD_CAP = '{"monthly_cap_bytes": 1000}'
QUIET_7AM = {"enabled": True, "start": "7am", "end": "07:00", "critical_through": True}

# A section today's import refused while applying, and what it said (or part of it)
BAD = {
    "capture mode": (
        {"capture_mode_config": {"capture_mode": "evil"}},
        "Capture mode not restored: this backup's mode isn't valid",
    ),
    "capture interface": (
        {
            "capture_mode_config": {
                "capture_mode": "mirror",
                "capture_interface": "eth2;reboot",
            }
        },
        "Capture mode not restored: 'eth2;reboot' is not a valid network interface name",
    ),
    "DHCP subnet": (
        {
            "capture_mode_config": {
                "capture_mode": "dhcp_gateway",
                "capture_interface": "eth1",
                "dhcp_subnet": "8.8.8.0/24",
            }
        },
        "is not a private subnet",
    ),
    "retention range": (
        {"storage_retention": {"retention": {"hot_days": 0}}},
        "Retention settings not restored: hot_days must be between 1 and 365",
    ),
    "retention shape": (
        {"storage_retention": ["x"]},
        "Retention settings not restored: not a JSON object",
    ),
    "retention null": (  # passed validate_config, failed int(None) in the save's merge
        {"storage_retention": {"retention": {"hot_days": None}}},
        "Retention settings not restored",
    ),
    "channel without id": (
        {"notification_channels": {"bad": {"type": "slack", "config": {}}}},
        "Notifications not restored: the channel 'bad' in this backup has no id",
    ),
    "channels shape": (
        {"notification_channels": ["x"]},
        "Notifications not restored: Notification channels in this backup aren't valid",
    ),
    "rules": (
        {"notification_rules": {"r": "x"}},
        "Notifications not restored: Notification rules in this backup aren't valid",
    ),
    "quiet hours": (
        {"notification_quiet": QUIET_7AM},
        "Quiet hours' start and end must be times such as 22:00",
    ),
    "device name": (
        {"device_aliases": {MAC: ""}, "device_pictures": {}},
        "Device names and pictures not restored: name for",
    ),
    "device picture": (
        {"device_aliases": {}, "device_pictures": {MAC: {"icon": []}}},
        "Device names and pictures not restored: picture for",
    ),
    "excluded range": (
        {"excluded_ips": ["192.0.2.1", "10.0.0.0/8"]},
        "Excluded IPs not restored: each must be a single IP address, and '10.0.0.0/8' isn't",
    ),
    "excluded shape": (
        {"excluded_ips": "192.0.2.1"},
        "Excluded IPs not restored: this backup's copy isn't a list of IP addresses",
    ),
    "bandwidth cap": (
        {"bandwidth_cap": {"monthly_cap_bytes": -1}},
        "Bandwidth cap not restored: this backup's copy isn't valid",
    ),
    "home location": (
        {"home_location": {"lat": 91, "lon": 0}},
        "Home location not restored: 'lat' must be between -90 and 90",
    ),
    "acknowledgements": (
        {"alert_acknowledgements": {"a1": 1}},
        "Alert acknowledgements not restored: this backup's copy isn't valid",
    ),
    "suppressions": (
        {"alert_suppressions": {"global": [None]}},
        "Alert suppressions not restored: this backup's copy isn't valid",
    ),
}


@pytest.fixture
def paths(tmp_path) -> dict:
    out = {
        k: str(tmp_path / f"{k}.json")
        for k in (
            "notification_config",
            "excluded_ips",
            "bandwidth_cap",
            "retention_config",
            "home_location",
            "alert_acks",
            "suppressions",
        )
    }
    out["capture_config"] = str(tmp_path / "capture-mode.conf")
    out["env_file"] = str(tmp_path / ".env")
    Path(out["bandwidth_cap"]).write_text(OLD_CAP)
    Path(out["excluded_ips"]).write_text('["192.0.2.9"]')
    return out


@pytest.fixture
def backup(paths, tmp_path) -> ConfigBackup:
    store = DeviceCustomStore(str(tmp_path / "appdata"))
    store.set_name(MAC, "TV")
    hub = NotificationHub(
        config_path=paths["notification_config"], env_file=paths["env_file"]
    )
    return ConfigBackup(config_paths=paths, device_custom=store, notification_hub=hub)


def _data(sections: dict, **metadata) -> dict:
    return {"metadata": {"schema_version": 2, **metadata}, "sections": sections}


# ---------------------------------------------------------------------------- section_errors


@pytest.mark.parametrize("sections,expected", BAD.values(), ids=BAD.keys())
def test_the_preflight_finds_what_todays_import_refused(sections, expected):
    reasons = [r for rs in section_errors(sections).values() for r in rs]
    assert any(expected in r for r in reasons), reasons


@pytest.mark.parametrize("sections,expected", BAD.values(), ids=BAD.keys())
def test_a_bad_section_beside_a_valid_cap_writes_nothing(
    backup, paths, sections, expected
):
    """Old code applied the cap, then refused the bad section: a half-applied restore."""
    # the bad cap's own case gets a valid home location beside it instead
    valid = (
        {"home_location": {"lat": 1.5, "lon": 2.5}}
        if "bandwidth_cap" in sections
        else {}
    )
    data = _data({"bandwidth_cap": CAP, **valid, **sections})
    validation = backup.validate_import(data)
    assert validation["is_valid"] is False
    assert any(expected in e for e in validation["errors"])
    result = backup.import_config(data)
    assert result["success"] is False and result["applied"] == []
    assert Path(paths["bandwidth_cap"]).read_text() == OLD_CAP
    assert not Path(paths["home_location"]).exists()
    assert backup._device_custom.names() == {MAC: "TV"}


# Sections whose apply step checks again: with the preflight bypassed, the importer refuses with
# the same shared rule and the same words, so the two can't drift apart
SHARED = [
    "bandwidth cap",
    "acknowledgements",
    "suppressions",
    "channel without id",
    "channels shape",
    "rules",
    "quiet hours",
    "device name",
    "device picture",
]


@pytest.mark.parametrize("case", SHARED)
def test_the_importer_refuses_with_the_preflights_own_words(backup, case):
    sections, _ = BAD[case]
    preflight = [r for rs in section_errors(sections).values() for r in rs]
    bypassed = {"is_valid": True, "warnings": [], "errors": []}
    result = backup.import_config(_data(sections), bypassed)
    assert result["applied"] == [] and preflight
    for reason in preflight:
        assert any(reason in e for e in result["errors"]), (reason, result["errors"])


def test_a_channel_the_hub_skipped_at_load_doesnt_block_the_backup(paths, tmp_path):
    """The hub skips an unusable channel at load but leaves it in the file. A backup read from
    the file carried it, the preflight refused it, and no backup could be made."""
    usable = {
        "id": "slack1",
        "type": "slack",
        "config": {"webhook_url": "https://hooks.example.net/a"},
    }
    stale = {"type": "slack", "config": {}}  # no id: the hub can't use it
    Path(paths["notification_config"]).write_text(
        json.dumps({"channels": {"slack1": usable, "old": stale}, "rules": {}})
    )
    hub = NotificationHub(
        config_path=paths["notification_config"], env_file=paths["env_file"]
    )
    store = DeviceCustomStore(str(tmp_path / "appdata"))

    body, _ = ConfigBackup(paths, store, hub).export_file()
    doc = json.loads(body)
    assert list(doc["sections"]["notification_channels"]) == ["slack1"]
    assert ConfigBackup(paths, store, hub).validate_import(doc)["is_valid"]
    # the file itself is untouched; without the hub, the file is what gets read
    saved = json.loads(Path(paths["notification_config"]).read_text())
    assert set(saved["channels"]) == {"slack1", "old"}
    with pytest.raises(BackupRefused) as refused:
        ConfigBackup(paths, store, None).export_file()
    assert refused.value.code == "invalid_section"


def test_a_real_export_passes(backup):
    assert section_errors(backup.export_config()["sections"]) == {}


def test_names_alone_from_before_net_200_arent_checked():
    """import_config skips them (always {} then), so they can't refuse a restore."""
    assert section_errors({"device_aliases": {"not a mac": 5}}) == {}


def test_a_null_suppression_reason_restores(backup, paths):
    supp = {"global": [{"signature_id": 1, "reason": None}], "per_device": {}}
    assert section_errors({"alert_suppressions": supp}) == {}
    result = backup.import_config(_data({"alert_suppressions": supp}))
    assert result["success"] is True, result
    assert json.loads(Path(paths["suppressions"]).read_text()) == supp


def test_the_import_reuses_the_preflight_it_is_given(backup, paths):
    data = _data({"bandwidth_cap": CAP})
    validation = backup.validate_import(data)
    with patch.object(
        backup, "validate_import", side_effect=AssertionError("ran twice")
    ):
        result = backup.import_config(data, validation)
        assert result["applied"] == ["bandwidth_cap"]
        refused = backup.import_config(data, {**validation, "is_valid": False})
    assert refused["applied"] == [] and refused["success"] is False


# ---------------------------------------------------------------------------- left-out count


def test_a_positive_left_out_count_warns_with_both_numbers(backup):
    acks = {"a1": {}, "a2": {}}
    result = backup.validate_import(
        _data({"alert_acknowledgements": acks}, acknowledgements_left_out=1234)
    )
    assert result["is_valid"] is True, result
    assert (
        "This backup leaves out 1,234 alert acknowledgements. Restoring replaces this "
        "NetTap's acknowledgements with the 2 it carries."
    ) in result["warnings"]


def test_no_left_out_count_means_none_left_out(backup):
    result = backup.validate_import(_data({"alert_acknowledgements": {}}))
    assert result["is_valid"] and not any("leaves out" in w for w in result["warnings"])


@pytest.mark.parametrize(
    "value,sections",
    [
        (-1, {"alert_acknowledgements": {}}),
        ("3", {"alert_acknowledgements": {}}),
        (True, {"alert_acknowledgements": {}}),
        (1.5, {"alert_acknowledgements": {}}),
        (None, {"alert_acknowledgements": {}}),
        (3, {}),  # says some were left out, carries no map
        (3, {"alert_acknowledgements": []}),
    ],
)
def test_a_malformed_left_out_count_is_a_validation_error(backup, value, sections):
    result = backup.validate_import(_data(sections, acknowledgements_left_out=value))
    assert result["is_valid"] is False
    assert any("left-out" in e or "leaves out" in e for e in result["errors"]), result


# ---------------------------------------------------------------------------- excluded IPs


def test_the_restore_refuses_the_10001st_excluded_ip():
    ips = [f"10.0.{i >> 8}.{i & 255}" for i in range(EXCLUDED_IPS_MAX + 1)]
    assert section_errors({"excluded_ips": ips}) == {
        "excluded_ips": [
            "Excluded IPs not restored: up to 10,000, and this backup has 10,001"
        ]
    }
    assert (
        section_errors({"excluded_ips": ips[:-1] + ips[:5]}) == {}
    )  # duplicates don't count


def test_duplicate_spellings_restore_as_one_entry(backup, paths):
    result = backup.import_config(
        _data(
            {
                "excluded_ips": [
                    "2001:db8::1",
                    "2001:DB8:0::1",
                    " 192.0.2.1",
                    "192.0.2.1",
                ]
            }
        )
    )
    assert result["success"] is True, result
    assert json.loads(Path(paths["excluded_ips"]).read_text()) == [
        "2001:db8::1",
        "192.0.2.1",
    ]


def test_load_removes_duplicates_in_order(tmp_path):
    path = tmp_path / "ips.json"
    path.write_text('["192.0.2.1", "10.0.0.0/8", "192.0.2.1", 5, ""]')
    assert load_excluded_ips(str(path)) == ["192.0.2.1", "10.0.0.0/8"]


def test_a_failed_settings_save_leaves_the_old_list(tmp_path):
    path = tmp_path / "ips.json"
    save_excluded_ips(["192.0.2.1"], str(path))
    with patch("os.fsync", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            save_excluded_ips(["192.0.2.2", "192.0.2.3"], str(path))
    assert load_excluded_ips(str(path)) == ["192.0.2.1"]
    assert [p.name for p in tmp_path.iterdir()] == ["ips.json"]  # no temp file left


def test_a_failed_restore_write_leaves_the_old_list(backup, paths, caplog):
    with patch("os.fsync", side_effect=OSError("disk full")):
        result = backup.import_config(_data({"excluded_ips": ["192.0.2.2"]}))
    assert result["success"] is False and "excluded_ips" not in result["applied"]
    # a fixed reply (the 400 never carries an OSError's text or a path); the reason is logged
    assert (
        "Excluded IPs not restored: the file couldn't be written." in result["errors"]
    )
    assert not any("disk full" in e for e in result["errors"])
    assert "disk full" in caplog.text
    assert load_excluded_ips(paths["excluded_ips"]) == ["192.0.2.9"]


@pytest.mark.parametrize(
    "bad",
    [
        ["192.0.2.2", "10.0.0.0/8"],  # parses to None
        [
            f"10.0.{i >> 8}.{i & 255}" for i in range(EXCLUDED_IPS_MAX + 1)
        ],  # over the cap
        "192.0.2.2",  # not a list
        5,
    ],
    ids=["range", "over the cap", "text", "number"],
)
def test_a_hand_built_validation_cant_write_bad_excluded_ips(backup, paths, bad):
    """The write checks again, so a caller passing its own validation writes nothing bad."""
    result = backup.import_config(_data({"excluded_ips": bad}), {"is_valid": True})
    assert result["success"] is False and result["applied"] == []
    assert any(e.startswith("Excluded IPs not restored:") for e in result["errors"])
    assert Path(paths["excluded_ips"]).read_text() == '["192.0.2.9"]'


async def _settings_client(tmp_path) -> TestClient:
    app = web.Application()
    app["excluded_ips"] = []
    app["excluded_ips_file"] = str(tmp_path / "ips.json")
    register_settings_routes(app, env_file=str(tmp_path / ".env"))
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


@pytest.mark.asyncio
async def test_the_settings_put_takes_10000_and_refuses_10001(tmp_path):
    ips = [f"10.0.{i >> 8}.{i & 255}" for i in range(EXCLUDED_IPS_MAX + 1)]
    client = await _settings_client(tmp_path)
    try:
        resp = await client.put(
            "/api/settings/excluded-ips", json={"excluded_ips": ips}
        )
        assert resp.status == 400
        assert (await resp.json())[
            "error"
        ] == "Up to 10,000 excluded IPs. Remove some first."
        assert not (tmp_path / "ips.json").exists()
        # duplicates go first, so 10,000 distinct plus repeats is fine
        body = {"excluded_ips": ips[:-1] + ips[:3]}
        resp = await client.put("/api/settings/excluded-ips", json=body)
        assert resp.status == 200 and (await resp.json())["count"] == EXCLUDED_IPS_MAX
    finally:
        await client.close()


# ---------------------------------------------------------------------------- reasons as text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sent,stored", [(None, ""), (0, "0"), (7, "7"), ("", ""), ("noisy", "noisy")]
)
async def test_suppress_and_false_positive_store_the_reason_as_text(
    tmp_path, monkeypatch, sent, stored
):
    monkeypatch.setattr(
        alert_intelligence, "_SUPPRESS_PATH", tmp_path / "suppress.json"
    )
    app = web.Application()
    app.router.add_post("/api/alerts/suppress", handle_suppress_alert)
    app.router.add_post("/api/alerts/false-positive", handle_false_positive)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        for path in ("/api/alerts/suppress", "/api/alerts/false-positive"):
            resp = await client.post(path, json={"signature_id": 5, "reason": sent})
            assert resp.status == 200
    finally:
        await client.close()
    data = json.loads((tmp_path / "suppress.json").read_text())
    assert [e["reason"] for e in data["global"] + data["false_positives"]] == [
        stored
    ] * 2
