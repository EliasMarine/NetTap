"""F2 (NET-320): the owner's details on registry, device and traffic rows, and on both device pages."""

import asyncio
import itertools
import json
import tempfile
from unittest.mock import MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, make_mocked_request

from api.device_custom import register_device_custom_routes
from api.devices import register_device_routes
from api.devices_v2 import handle_registry_detail, handle_registry_list
from api.traffic import handle_category_detail
from services.device_custom import DeviceCustomStore
from services.device_details import DeviceDetailsStore
from services.device_registry import DeviceRegistry
from tests.test_device_custom_routes import _registry
from tests.test_devices_api import _answering, _make_mock_storage, _registry_with

MAC = "AA:BB:CC:DD:EE:01"
ROW_KEYS = ("group", "owner", "watch_after_min")
FOUR = ("watch_after_min", "group", "owner", "notes")
NO_ROW_DETAILS = dict.fromkeys(ROW_KEYS)
KIDS = {"group": "Kids", "owner": "Sam", "watch_after_min": 60}
DEVICE = {"mac": MAC, "ips": ["10.0.0.5"], "hostnames": ["tablet"]}
# #76: Zeek printed a UniFi AP's DHCP chaddr as 8 bytes; the registry files it under six
LONG_MAC = "f4:e2:c6:ff:98:21:62:72"
AP_MAC = "F4:E2:C6:FF:98:21"


def _stores(root: str) -> tuple[DeviceDetailsStore, DeviceCustomStore]:
    details = DeviceDetailsStore(root)
    return details, DeviceCustomStore(root, details=details)


def _row_details(row: dict) -> dict:
    return {k: row[k] for k in ROW_KEYS}


def _snapshots(details: DeviceDetailsStore):
    """Patch get() so each call answers a different, internally consistent revision."""
    counter = itertools.count(1)

    def get(mac):
        n = next(counter)
        return {
            "watch_after_min": 15,
            "group": f"g{n}",
            "owner": f"o{n}",
            "notes": f"n{n}",
        }

    return patch.object(details, "get", side_effect=get)


def _one_revision(device: dict) -> None:
    n = device["group"][1:]
    assert (device["owner"], device["notes"]) == (f"o{n}", f"n{n}"), device


# --------------------------------------------------------------------------- row shape


def test_with_names_carries_the_three_keys_never_notes(tmp_path):
    details, custom = _stores(str(tmp_path))
    details.update(MAC, {**KIDS, "notes": "long text"})
    row = _registry(MagicMock(), custom).with_names(DEVICE)
    assert _row_details(row) == KIDS and "notes" not in row
    # a names store without a details store, and no names store at all
    bare = _registry(MagicMock(), DeviceCustomStore(str(tmp_path))).with_names(DEVICE)
    assert _row_details(bare) == NO_ROW_DETAILS and "notes" not in bare
    fallback = DeviceRegistry.__new__(DeviceRegistry)
    fallback._custom = None
    row = fallback.with_names(DEVICE)
    assert _row_details(row) == NO_ROW_DETAILS and "notes" not in row
    assert set(row) == set(bare)


def test_present_carries_the_three_keys_never_notes(tmp_path):
    details, custom = _stores(str(tmp_path))
    details.update(MAC, {**KIDS, "notes": "long text"})
    row = custom.present({"mac": MAC.lower(), "hostname": "tablet", "ip": "10.0.0.5"})
    assert _row_details(row) == KIDS and "notes" not in row
    bare = DeviceCustomStore(str(tmp_path)).present({"mac": MAC, "hostname": "x"})
    assert _row_details(bare) == NO_ROW_DETAILS and "notes" not in bare


def test_a_details_only_device_shows_its_details(tmp_path):
    details, custom = _stores(str(tmp_path))
    details.update(MAC, {"group": "Kids"})
    fields = custom.owner_fields(MAC)
    assert fields["custom_name"] is None and fields["picture"] is None
    assert fields["group"] == "Kids"
    custom.set_name(MAC, "Tablet")
    assert custom.owner_fields(MAC)["group"] == "Kids"
    # an observed 8-byte MAC reads the details filed under its first six octets
    details.update(AP_MAC, {"owner": "Sam"})
    assert custom.owner_fields(LONG_MAC)["owner"] == "Sam"


def test_a_non_mac_or_a_damaged_details_file_gives_nones(tmp_path):
    details, custom = _stores(str(tmp_path))
    details.update(MAC, KIDS)
    assert _row_details(custom.owner_fields(None)) == NO_ROW_DETAILS
    assert _row_details(custom.owner_fields("nope")) == NO_ROW_DETAILS
    custom.set_name(MAC, "Tablet")
    details._problem = "Device details file is unreadable: x"
    details._devices = {}
    fields = custom.owner_fields(MAC)
    assert fields["custom_name"] == "Tablet" and _row_details(fields) == NO_ROW_DETAILS


# --------------------------------------------------------------------------- registry list, MAC page


def _registry_app(tmp_path) -> tuple[web.Application, DeviceDetailsStore]:
    details, custom = _stores(str(tmp_path))
    client = MagicMock()
    client.search.return_value = {"hits": {"hits": [{"_source": DEVICE}]}}
    client.get.return_value = {"_source": DEVICE}
    app = web.Application()
    app["device_registry"] = _registry(client, custom)
    app["device_custom"] = custom
    app["device_details"] = details
    return app, details


def _detail(app: web.Application) -> dict:
    request = make_mocked_request(
        "GET", f"/api/devices/registry/{MAC}", match_info={"mac": MAC}, app=app
    )
    return json.loads(asyncio.run(handle_registry_detail(request)).text)["device"]


def test_the_registry_list_shows_a_details_only_device_without_notes(tmp_path):
    app, details = _registry_app(tmp_path)
    details.update(MAC, {**KIDS, "notes": "long text"})
    resp = asyncio.run(handle_registry_list(make_mocked_request("GET", "/x", app=app)))
    (device,) = json.loads(resp.text)["devices"]
    assert _row_details(device) == KIDS and "notes" not in device


def test_the_mac_page_carries_all_four(tmp_path):
    app, details = _registry_app(tmp_path)
    details.update(MAC, {**KIDS, "notes": "long text"})
    device = _detail(app)
    assert {k: device[k] for k in FOUR} == {**KIDS, "notes": "long text"}
    assert device["display_name"] == "tablet"


def test_the_mac_page_takes_all_four_from_one_snapshot(tmp_path):
    app, details = _registry_app(tmp_path)
    with _snapshots(details):
        _one_revision(_detail(app))


def test_the_mac_page_without_a_details_store_has_nones(tmp_path):
    app, _ = _registry_app(tmp_path)
    del app["device_details"]
    device = _detail(app)
    assert {k: device[k] for k in FOUR} == dict.fromkeys(FOUR)


# --------------------------------------------------------------------------- traffic breakdown


def test_the_traffic_breakdown_shows_a_details_only_device(tmp_path):
    details, custom = _stores(str(tmp_path))
    details.update(MAC, {**KIDS, "notes": "long text"})
    app = web.Application()
    app["storage"] = MagicMock()
    app["device_custom"] = custom
    breakdown = {
        "devices": [
            {"ip": "10.0.0.5", "mac": MAC.lower(), "hostname": "tv", "total_bytes": 9}
        ],
        "device_count": 1,
        "total_bytes": 9,
        "connection_count": 1,
    }
    request = make_mocked_request(
        "GET",
        "/api/traffic/categories/streaming",
        match_info={"category": "streaming"},
        app=app,
    )
    with (
        patch(
            "api.traffic.traffic_classifier.get_category_devices",
            return_value=breakdown,
        ),
        patch("api.traffic.traffic_classifier.get_category_services", return_value=[]),
    ):
        resp = asyncio.run(handle_category_detail(request))
    assert resp.status == 200
    (device,) = json.loads(resp.text)["devices"]
    assert _row_details(device) == KIDS and "notes" not in device
    assert device["total_bytes"] == 9 and device["percent"] == 100.0


# --------------------------------------------------------------------------- the IP page


_CONN = {
    "hits": {"total": {"value": 10}},
    "aggregations": {
        "src": {"value": 5000},
        "started": {
            "protocols": {"buckets": []},
            "first_seen": {"value_as_string": "2026-02-25T12:00:00.000Z"},
            "last_seen": {"value_as_string": "2026-02-25T12:30:00.000Z"},
            "top_destinations": {"buckets": []},
        },
        "bandwidth_series": {"buckets": []},
    },
}
AP = {"mac": AP_MAC, "ips": ["192.168.1.198"], "hostnames": ["U7Pro"]}


class TestIpPage(AioHTTPTestCase):
    async def get_application(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.details, self.custom = _stores(self.tmp.name)
        self.storage, self.mock_client = _make_mock_storage()
        registry = _registry_with({AP_MAC: AP})
        registry._custom = self.custom
        app = web.Application()
        app["storage"] = self.storage
        app["device_registry"] = registry
        register_device_routes(app, self.storage)
        register_device_custom_routes(app, self.custom, self.details)
        return app

    async def tearDownAsync(self):
        self.tmp.cleanup()

    def _replies(self, mac: str | None) -> None:
        dhcp = {
            "hits": {"hits": [{"_source": {"source": {"mac": mac}}}] if mac else []}
        }
        self.mock_client.search.side_effect = _answering(
            [
                _CONN,
                {"aggregations": {"dns_queries": {"buckets": []}}},
                {"hits": {"total": {"value": 0}}},
                dhcp,
            ]
            + [{"hits": {"hits": []}}, {"aggregations": {}}] * 20
        )

    async def _device(self, mac: str | None) -> dict:
        self._replies(mac)
        resp = await self.client.request("GET", "/api/devices/192.168.1.198")
        assert resp.status == 200
        return (await resp.json())["device"]

    async def test_an_8_byte_mac_shows_the_details_filed_under_the_registry_mac(self):
        self.details.update(AP_MAC, {**KIDS, "notes": "in the loft"})
        device = await self._device(LONG_MAC)
        assert device["mac"] == LONG_MAC and device["registry_mac"] == AP_MAC
        assert {k: device[k] for k in FOUR} == {**KIDS, "notes": "in the loft"}
        assert device["total_bytes"] == 5000  # the traffic figures are untouched

    async def test_its_registry_mac_is_a_working_put_target(self):
        device = await self._device(LONG_MAC)
        resp = await self.client.put(
            f"/api/devices/registry/{device['registry_mac']}/details",
            json={"owner": "Sam"},
        )
        assert resp.status == 200
        assert self.details.export() == {AP_MAC: {"owner": "Sam"}}
        assert (await self._device(LONG_MAC))["owner"] == "Sam"

    async def test_a_details_only_device_shows_them(self):
        self.details.update(AP_MAC, {"group": "Network"})
        device = await self._device("f4:e2:c6:ff:98:21")
        assert device["group"] == "Network" and device["custom_name"] is None

    async def test_all_four_come_from_one_snapshot(self):
        with _snapshots(self.details):
            _one_revision(await self._device(LONG_MAC))

    async def test_no_mac_means_nones_and_a_null_registry_mac(self):
        self.details.update(AP_MAC, KIDS)
        device = await self._device(None)
        assert device["mac"] is None and device["registry_mac"] is None
        assert {k: device[k] for k in FOUR} == dict.fromkeys(FOUR)
        assert device["total_bytes"] == 5000
