"""NET-200 routes and name order: the owner's name and picture for a device."""

import base64
from unittest.mock import MagicMock

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from opensearchpy import NotFoundError, OpenSearchException

from api.device_custom import register_device_custom_routes
from api.devices import register_device_routes
from api.devices_v2 import handle_registry_list, handle_registry_search
from services.device_custom import DeviceCustomStore
from services.device_registry import DeviceRegistry
from tests.test_devices_api import (
    _device_bucket,
    _device_list_response,
    _empty_alert_response,
    _make_mock_storage,
    _registry_with,
)

MAC = "AA:BB:CC:DD:EE:01"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPEG = b"\xff\xd8\xff\xe0" + b"\x01" * 40
TV = {
    "mac": MAC,
    "ips": ["10.0.0.5"],
    "hostnames": ["android-5a1b"],
    "manufacturer": "Sonos, Inc.",
    "category": "iot",
    "enrichment_sources": {"unifi": {"unifi_alias": "UniFi TV"}},
}


def b64(data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode()


def _registry(client: MagicMock, store: DeviceCustomStore) -> DeviceRegistry:
    registry = DeviceRegistry.__new__(DeviceRegistry)
    registry._client = client
    registry._custom = store
    return registry


def _get_returns(doc: dict | None):
    def get(index, id):
        if doc is None or id != doc["mac"]:
            raise NotFoundError(404, "not found", {})
        return {"_source": doc}

    return get


# --------------------------------------------------------------------------- name order


class TestNameOrder:
    def test_the_owner_name_beats_the_unifi_alias(self, tmp_path):
        store = DeviceCustomStore(str(tmp_path))
        registry = _registry(MagicMock(), store)
        assert registry.get_display_name(TV) == "UniFi TV"
        store.set_name(MAC, "Living room TV")
        assert registry.get_display_name(TV) == "Living room TV"
        assert registry.get_display_name(TV, own=False) == "UniFi TV"

    def test_get_name_keeps_an_owner_name_that_matches_the_maker(self, tmp_path):
        store = DeviceCustomStore(str(tmp_path))
        registry = _registry(MagicMock(), store)
        bare = {"mac": MAC, "manufacturer": "Sonos, Inc."}
        assert registry.get_name(bare) is None
        store.set_name(MAC, "Sonos, Inc.")
        assert registry.get_name(bare) == "Sonos, Inc."
        assert registry.get_name(bare, own=False) is None

    def test_with_names_is_a_copy(self, tmp_path):
        store = DeviceCustomStore(str(tmp_path))
        store.set_name(MAC, "TV")
        registry = _registry(MagicMock(), store)
        out = registry.with_names(TV)
        assert "display_name" not in TV
        assert (out["display_name"], out["discovered_name"], out["custom_name"]) == (
            "TV",
            "UniFi TV",
            "TV",
        )

    def test_no_store_means_no_owner_fields(self):
        registry = DeviceRegistry.__new__(DeviceRegistry)
        out = registry.with_names(TV)
        assert out["custom_name"] is None and out["picture"] is None


# --------------------------------------------------------------------------- routes


class _RoutesBase(AioHTTPTestCase):
    async def get_application(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.store = DeviceCustomStore(self.tmp.name)
        self.os = MagicMock()
        self.os.get.side_effect = _get_returns(TV)
        app = web.Application()
        app["device_registry"] = _registry(self.os, self.store)
        register_device_custom_routes(app, self.store)
        return app

    async def tearDownAsync(self):
        self.tmp.cleanup()


class TestNameRoutes(_RoutesBase):
    @unittest_run_loop
    async def test_put_sets_and_answers_with_the_device(self):
        resp = await self.client.put(
            f"/api/devices/registry/{MAC}/name", json={"name": " TV "}
        )
        body = await resp.json()
        assert resp.status == 200
        assert body["device"]["display_name"] == "TV"
        assert body["device"]["discovered_name"] == "UniFi TV"
        assert body["device"]["ips"] == ["10.0.0.5"]

    @unittest_run_loop
    async def test_percent_encoded_and_lower_case_macs_work(self):
        resp = await self.client.put(
            "/api/devices/registry/aa%3Abb%3Acc%3Add%3Aee%3A01/name",
            json={"name": "TV"},
        )
        assert resp.status == 200 and self.store.name_for(MAC) == "TV"

    @unittest_run_loop
    async def test_bad_input_is_a_400(self):
        for body in ({"name": ""}, {"name": "x" * 65}, {"name": 3}, {}):
            resp = await self.client.put(f"/api/devices/registry/{MAC}/name", json=body)
            assert resp.status == 400, body
        resp = await self.client.put(
            f"/api/devices/registry/{MAC}/name",
            data="not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400
        resp = await self.client.put(
            "/api/devices/registry/nope/name", json={"name": "TV"}
        )
        assert resp.status == 400

    @unittest_run_loop
    async def test_unknown_device_is_a_404_and_saves_nothing(self):
        resp = await self.client.put(
            "/api/devices/registry/AA:BB:CC:DD:EE:99/name", json={"name": "TV"}
        )
        assert resp.status == 404 and self.store.names() == {}

    @unittest_run_loop
    async def test_opensearch_down_is_a_502_for_a_put(self):
        self.os.get.side_effect = OpenSearchException("down")
        resp = await self.client.put(
            f"/api/devices/registry/{MAC}/name", json={"name": "TV"}
        )
        assert resp.status == 502 and self.store.names() == {}

    @unittest_run_loop
    async def test_delete_clears_even_while_opensearch_is_down(self):
        self.store.set_name(MAC, "TV")
        self.os.get.side_effect = OpenSearchException("down")
        resp = await self.client.delete(f"/api/devices/registry/{MAC}/name")
        assert resp.status == 200 and self.store.names() == {}

    @unittest_run_loop
    async def test_an_unreadable_store_is_a_503(self):
        self.store._problem = "Device names file is unreadable: x"
        resp = await self.client.put(
            f"/api/devices/registry/{MAC}/name", json={"name": "TV"}
        )
        assert resp.status == 503


class TestPictureRoutes(_RoutesBase):
    @unittest_run_loop
    async def test_icon_then_photo_then_clear(self):
        resp = await self.client.put(
            f"/api/devices/registry/{MAC}/picture", json={"icon": "tv"}
        )
        assert (await resp.json())["device"]["icon"] == "tv"
        resp = await self.client.put(
            f"/api/devices/registry/{MAC}/picture", json={"image": b64(PNG)}
        )
        device = (await resp.json())["device"]
        assert device["icon"] is None and device["picture"].startswith(
            f"/api/devices/registry/{MAC}/picture?v="
        )
        resp = await self.client.delete(f"/api/devices/registry/{MAC}/picture")
        assert (await resp.json())["device"]["picture"] is None

    @unittest_run_loop
    async def test_exactly_one_of_icon_or_image(self):
        for body in (
            {},
            {"icon": "tv", "image": b64(PNG)},
            {"icon": "tv", "x": 1},
            {"colour": "red"},
        ):
            resp = await self.client.put(
                f"/api/devices/registry/{MAC}/picture", json=body
            )
            assert resp.status == 400, body

    @unittest_run_loop
    async def test_svg_is_a_400_in_plain_english(self):
        svg = "data:image/svg+xml;base64," + base64.b64encode(b"<svg/>").decode()
        resp = await self.client.put(
            f"/api/devices/registry/{MAC}/picture", json={"image": svg}
        )
        assert resp.status == 400
        assert (await resp.json())["error"] == "Pictures must be PNG, JPEG or WebP."

    @unittest_run_loop
    async def test_get_serves_its_own_version_only(self):
        self.store.set_photo(MAC, b64(PNG))
        url = self.store.owner_fields(MAC)["picture"]
        resp = await self.client.get(url)
        assert resp.status == 200 and await resp.read() == PNG
        assert resp.headers["Content-Type"] == "image/png"
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert "immutable" in resp.headers["Cache-Control"]
        assert resp.headers["Content-Security-Policy"] == "default-src 'none'"

        self.store.set_photo(MAC, b64(JPEG))
        stale = await self.client.get(url)
        assert stale.status == 404 and stale.headers["Cache-Control"] == "no-store"
        # restoring the original makes the old URL hold its own bytes again
        self.store.set_photo(MAC, b64(PNG))
        again = await self.client.get(url)
        assert again.status == 200 and await again.read() == PNG

    @unittest_run_loop
    async def test_get_without_a_good_version_is_a_404_nobody_caches(self):
        self.store.set_photo(MAC, b64(PNG))
        for q in ("", "?v=", "?v=../../x", "?v=0123456789abcdef"):
            resp = await self.client.get(f"/api/devices/registry/{MAC}/picture{q}")
            assert resp.status == 404 and resp.headers["Cache-Control"] == "no-store", q


# --------------------------------------------------------------------------- list, search


def test_registry_list_and_search_carry_owner_fields(tmp_path):
    import asyncio
    import json

    from aiohttp.test_utils import make_mocked_request

    store = DeviceCustomStore(str(tmp_path))
    store.set_name(MAC, "Kitchen speaker")
    client = MagicMock()
    client.search.return_value = {"hits": {"hits": []}}
    client.mget.return_value = {"docs": [{"_id": MAC, "found": True, "_source": TV}]}
    app = web.Application()
    app["device_registry"] = _registry(client, store)
    app["device_custom"] = store

    resp = asyncio.run(
        handle_registry_search(make_mocked_request("GET", "/x?q=kitchen", app=app))
    )
    (device,) = json.loads(resp.text)["devices"]
    assert (
        device["display_name"] == "Kitchen speaker"
        and device["custom_name"] == "Kitchen speaker"
    )

    client.search.return_value = {"hits": {"hits": [{"_source": TV}]}}
    resp = asyncio.run(handle_registry_list(make_mocked_request("GET", "/x", app=app)))
    (device,) = json.loads(resp.text)["devices"]
    assert device["discovered_name"] == "UniFi TV"


# --------------------------------------------------------------------------- legacy list


CAMERA = {
    "mac": "BC:89:C1:E1:8A:D6",
    "hostnames": ["MacBook-Pro"],
    "manufacturer": "Apple, Inc.",
    "enrichment_sources": {"dhcp": {"hostname": "MacBook-Pro"}},
}


class TestLegacyListPresentationOnly(AioHTTPTestCase):
    """A cosmetic rename never moves a device between categories."""

    async def get_application(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.store = DeviceCustomStore(self.tmp.name)
        self.storage, self.mock_client = _make_mock_storage()
        app = web.Application()
        app["storage"] = self.storage
        app["device_registry"] = _registry_with({CAMERA["mac"]: CAMERA})
        app["device_custom"] = self.store
        register_device_routes(app, self.storage)
        return app

    async def tearDownAsync(self):
        self.tmp.cleanup()

    async def _list(self) -> dict:
        self.mock_client.search.side_effect = [
            _device_list_response([_device_bucket("192.168.1.188")]),
            _empty_alert_response(),
        ] + [{"hits": {"hits": []}}] * 10
        dhcp = {
            "hits": {"hits": [{"_source": {"source": {"mac": "bc:89:c1:e1:8a:d6"}}}]}
        }
        self.mock_client.msearch.return_value = {
            "responses": [
                dhcp,
                {"aggregations": {}},
                {"aggregations": {}},
                {"aggregations": {}},
            ]
        }
        resp = await self.client.request("GET", "/api/devices")
        (device,) = (await resp.json())["devices"]
        return device

    @unittest_run_loop
    async def test_owner_names_with_category_hints_change_nothing_but_the_name(self):
        before = await self._list()
        for name in ("Front door cam", "Ring doorbell", "Nest thermostat", "Roku TV"):
            self.store.set_name(CAMERA["mac"], name)
            after = await self._list()
            assert after["category"] == before["category"], name
            assert after["hostname"] == name and after["custom_name"] == name
        self.store.clear_name(CAMERA["mac"])
        cleared = await self._list()
        assert cleared["hostname"] == before["hostname"] == "MacBook-Pro"
        assert cleared["custom_name"] is None
