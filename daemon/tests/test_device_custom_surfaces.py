"""NET-200: owner names on traffic categories and IoT, and device names in config backups."""

import base64
import json
import os
from unittest.mock import MagicMock

from services import device_custom as dc
from services.config_backup import _NETTAP_VERSION, _SCHEMA_VERSION, ConfigBackup
from services.device_custom import DeviceCustomStore
from services.iot_monitor import IoTMonitor
from services.notification_hub import NotificationHub
from services.traffic_classifier import get_category_devices
from tests.test_category_devices import _asn_page, _mock_device_response

MAC = "AA:BB:CC:DD:EE:01"


# --------------------------------------------------------------------------- traffic categories


def test_category_rows_get_their_mac_from_one_batched_lookup():
    client = MagicMock()
    client.search.side_effect = [
        _asn_page("AS2906 Netflix Inc"),
        _mock_device_response(
            [("10.0.0.5", 3, 900, 800, 100), ("10.0.0.6", 1, 100, 90, 10)]
        ),
    ]
    fingerprint = MagicMock()
    fingerprint.lookup_many.return_value = {
        "10.0.0.5": ("aa:bb:cc:dd:ee:01", "tv.local", None)
    }
    result = get_category_devices(
        client,
        "streaming",
        "2026-03-01T00:00:00Z",
        "2026-03-02T00:00:00Z",
        fingerprint=fingerprint,
    )
    fingerprint.lookup_many.assert_called_once()
    fingerprint.get_hostname_for_ip.assert_not_called()
    by_ip = {d["ip"]: d for d in result["devices"]}
    assert (by_ip["10.0.0.5"]["mac"], by_ip["10.0.0.5"]["hostname"]) == (
        "aa:bb:cc:dd:ee:01",
        "tv.local",
    )
    assert (by_ip["10.0.0.6"]["mac"], by_ip["10.0.0.6"]["hostname"]) == (None, None)


def test_a_failed_name_lookup_keeps_the_figures():
    client = MagicMock()
    client.search.side_effect = [
        _asn_page("AS2906 Netflix Inc"),
        _mock_device_response([("10.0.0.5", 3, 900, 800, 100)]),
    ]
    fingerprint = MagicMock()
    fingerprint.lookup_many.side_effect = RuntimeError("msearch down")
    result = get_category_devices(
        client,
        "streaming",
        "2026-03-01T00:00:00Z",
        "2026-03-02T00:00:00Z",
        fingerprint=fingerprint,
    )
    assert result["total_bytes"] == 900 and result["devices"][0]["hostname"] is None


def test_present_puts_the_owner_name_on_a_category_row(tmp_path):
    store = DeviceCustomStore(str(tmp_path))
    store.set_name(MAC, "Living room TV")
    row = store.present(
        {"ip": "10.0.0.5", "mac": "aa:bb:cc:dd:ee:01", "hostname": "tv.local"}
    )
    assert (row["hostname"], row["custom_name"]) == ("Living room TV", "Living room TV")


# --------------------------------------------------------------------------- IoT


def test_iot_names_prefer_the_owner_name_and_categories_ignore_it(tmp_path):
    store = DeviceCustomStore(str(tmp_path))
    monitor = IoTMonitor.__new__(IoTMonitor)
    monitor._owner_name = store.name_for
    info = {"manufacturer": "Espressif Inc.", "hostname": None}
    assert monitor._device_name(MAC, info) == "Espressif Inc."
    category_before = IoTMonitor._categorize_device(monitor, info)
    store.set_name(MAC, "Front door camera")
    assert monitor._device_name(MAC, info) == "Front door camera"
    assert IoTMonitor._categorize_device(monitor, info) == category_before


def test_iot_without_a_store_keeps_its_old_names():
    monitor = IoTMonitor.__new__(IoTMonitor)
    monitor._owner_name = None
    assert (
        monitor._device_name(MAC, {"hostname": "plug", "manufacturer": "Tuya"})
        == "plug"
    )


# --------------------------------------------------------------------------- backup


def _png(seed: int, size: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + os.urandom(size - 8 - 1) + bytes([seed])


def _backup(tmp_path, store) -> ConfigBackup:
    paths = {
        k: str(tmp_path / f"{k}.json")
        for k in (
            "notification_config",
            "excluded_ips",
            "bandwidth_cap",
            "capture_config",
            "retention_config",
            "device_baseline",
            # A9: the owner files a backup now carries
            "home_location",
            "alert_acks",
            "suppressions",
        )
    }
    # OLD CODE: return ConfigBackup(config_paths=paths, device_custom=store) (NET-224: notifications restore through the hub)
    hub = NotificationHub(
        config_path=paths["notification_config"], env_file=str(tmp_path / ".env")
    )
    return ConfigBackup(config_paths=paths, device_custom=store, notification_hub=hub)


def test_a_backup_over_1_mib_round_trips(tmp_path):
    store = DeviceCustomStore(str(tmp_path / "a"))
    for i in range(6):
        mac = f"AA:BB:CC:DD:EE:{i:02X}"
        store.set_name(mac, f"Device {i}")
        store.set_photo(mac, base64.b64encode(_png(i, 250 * 1024)).decode())
    exported = _backup(tmp_path, store).export_config()
    assert len(json.dumps(exported)) > 1024 * 1024

    fresh = DeviceCustomStore(str(tmp_path / "b"))
    result = _backup(tmp_path, fresh).import_config(json.loads(json.dumps(exported)))
    assert result["success"], result
    assert {"device_aliases", "device_pictures"} <= set(result["applied"])
    assert fresh.names() == store.names()
    assert fresh.photo("AA:BB:CC:DD:EE:03")[0] == store.photo("AA:BB:CC:DD:EE:03")[0]


def test_the_daemon_accepts_a_body_that_size():
    from api.server import MAX_REQUEST_BYTES

    # photos ≤ 8 MiB, base64 4/3, plus room for the other settings
    assert MAX_REQUEST_BYTES >= dc.PHOTOS_MAX_TOTAL * 4 // 3 + 1024 * 1024


def test_a_backup_from_before_net_200_keeps_current_names(tmp_path):
    store = DeviceCustomStore(str(tmp_path))
    store.set_name(MAC, "TV")
    old = {
        "metadata": {
            "nettap_version": _NETTAP_VERSION,
            "schema_version": _SCHEMA_VERSION,
        },
        "sections": {
            "device_aliases": {}
        },  # what the dead baseline code always exported
    }
    result = _backup(tmp_path, store).import_config(old)
    assert result["success"] and "device_aliases" not in result["applied"]
    assert any("before device names" in w for w in result["warnings"])
    assert store.names() == {MAC: "TV"}


def test_a_bad_picture_restores_nothing(tmp_path):
    store = DeviceCustomStore(str(tmp_path))
    store.set_name(MAC, "TV")
    data = {
        "metadata": {
            "nettap_version": _NETTAP_VERSION,
            "schema_version": _SCHEMA_VERSION,
        },
        "sections": {
            "device_aliases": {"AA:BB:CC:DD:EE:02": "Laptop"},
            "device_pictures": {MAC: {"image": "data:image/svg+xml;base64,PHN2Zy8+"}},
        },
    }
    result = _backup(tmp_path, store).import_config(data)
    assert (
        not result["success"]
        and "Device names and pictures not restored" in result["errors"][0]
    )
    assert store.names() == {MAC: "TV"}


def test_a_malformed_picture_entry_is_an_error_not_a_crash(tmp_path):
    store = DeviceCustomStore(str(tmp_path))
    data = {
        "metadata": {
            "nettap_version": _NETTAP_VERSION,
            "schema_version": _SCHEMA_VERSION,
        },
        "sections": {"device_aliases": {}, "device_pictures": {MAC: {"icon": []}}},
    }
    result = _backup(tmp_path, store).import_config(data)
    assert not result["success"] and result["errors"]


def test_export_fails_rather_than_drop_a_missing_photo(tmp_path):
    store = DeviceCustomStore(str(tmp_path / "s"))
    store.set_photo(MAC, base64.b64encode(_png(1, 100)).decode())
    os.unlink(
        os.path.join(
            str(tmp_path / "s"), "device-pictures", store.get(MAC)["photo"]["file"]
        )
    )
    try:
        _backup(tmp_path, store).export_config()
    except ValueError as exc:
        assert MAC in str(exc)
    else:
        raise AssertionError("export should fail")
