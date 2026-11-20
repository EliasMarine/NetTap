"""F2 (NET-320): PUT and DELETE /api/devices/registry/{mac}/details."""

import tempfile
from unittest.mock import MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase
from opensearchpy import OpenSearchException

from api.device_custom import register_device_custom_routes
from services import device_details as dd
from services.device_custom import DeviceCustomStore, normalize_mac
from services.device_details import DeviceDetailsStore
from tests.test_device_custom_routes import _get_returns, _registry

MAC = "AA:BB:CC:DD:EE:FF"
GONE = "AA:BB:CC:DD:EE:99"
FOUR = ("watch_after_min", "group", "owner", "notes")
TV = {
    "mac": MAC,
    "ips": ["10.0.0.5"],
    "hostnames": ["android-5a1b"],
    "manufacturer": "Sonos, Inc.",
}
URL = f"/api/devices/registry/{MAC}/details"
STORAGE_FAILED = "Couldn't save the change: the device's storage failed."
# Each would edit MAC's details if the route truncated like normalize_mac does
BAD_MACS = (
    "AA:BB:CC:DD:EE:FF:00",
    "AA:BB:CC:DD:EE:FF:",
    "AA:BB:CC:DD:EE:FF:ZZ",
    "AA:BB-CC:DD:EE:FF",
    "AA-BB-CC-DD-EE:FF",
    "AABBCCDDEEFF",
    "nope",
)


def _four(device: dict) -> dict:
    return {k: device[k] for k in FOUR}


class _Base(AioHTTPTestCase):
    async def get_application(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.details = DeviceDetailsStore(self.tmp.name)
        self.custom = DeviceCustomStore(self.tmp.name, details=self.details)
        self.os = MagicMock()
        self.os.get.side_effect = _get_returns(TV)
        app = web.Application()
        app["device_registry"] = _registry(self.os, self.custom)
        register_device_custom_routes(app, self.custom, self.details)
        return app

    async def tearDownAsync(self):
        self.tmp.cleanup()


class TestPut(_Base):
    async def test_put_saves_and_answers_with_the_committed_snapshot(self):
        resp = await self.client.put(
            URL, json={"group": " Kids ", "watch_after_min": 30, "notes": "Sam's"}
        )
        assert resp.status == 200
        device = (await resp.json())["device"]
        assert _four(device) == {
            "watch_after_min": 30,
            "group": "Kids",
            "owner": None,
            "notes": "Sam's",
        }
        assert _four(device) == self.details.get(MAC)
        # the registry row comes with it
        assert device["ips"] == ["10.0.0.5"] and device["mac"] == MAC
        assert device["display_name"] == "android-5a1b"

    async def test_a_partial_put_merges_and_null_or_empty_clears(self):
        await self.client.put(URL, json={"group": "Kids", "owner": "Sam"})
        resp = await self.client.put(URL, json={"owner": None, "notes": "x"})
        assert _four((await resp.json())["device"]) == {
            "watch_after_min": None,
            "group": "Kids",
            "owner": None,
            "notes": "x",
        }
        resp = await self.client.put(URL, json={"group": "", "notes": "  "})
        assert _four((await resp.json())["device"]) == dict.fromkeys(FOUR)
        assert self.details.export() == {}

    async def test_the_reply_is_the_snapshot_not_a_second_read(self):
        # a row read after the commit that disagrees must not leak into the reply
        stale = dict.fromkeys(("group", "owner", "watch_after_min"), "stale")
        with patch.object(self.details, "row_fields", return_value=stale):
            resp = await self.client.put(URL, json={"group": "Kids"})
        assert (await resp.json())["device"]["group"] == "Kids"

    async def test_percent_encoded_lower_case_and_dashed_macs_work(self):
        for raw in ("aa%3Abb%3Acc%3Add%3Aee%3Aff", "aa-bb-cc-dd-ee-ff"):
            resp = await self.client.put(
                f"/api/devices/registry/{raw}/details", json={"owner": raw}
            )
            assert resp.status == 200, raw
            assert self.details.get(MAC)["owner"] == raw

    async def test_an_unknown_device_is_a_404_and_saves_nothing(self):
        resp = await self.client.put(
            f"/api/devices/registry/{GONE}/details", json={"group": "Kids"}
        )
        assert resp.status == 404
        assert (await resp.json())["error"] == f"Device not found: {GONE}"
        assert self.details.export() == {}

    async def test_opensearch_down_is_a_502_and_saves_nothing(self):
        self.os.get.side_effect = OpenSearchException("down")
        resp = await self.client.put(URL, json={"group": "Kids"})
        assert resp.status == 502 and self.details.export() == {}


class TestBadInput(_Base):
    async def test_bad_bodies_are_400s_with_the_reason(self):
        cases = [
            ({}, dd.NO_FIELDS),
            ({"colour": "red"}, dd.UNKNOWN_FIELD),
            ({"group": "Kids", "name": "TV"}, dd.UNKNOWN_FIELD),
            ({"watch_after_min": 45}, dd.BAD_WATCH),
            ({"watch_after_min": True}, dd.BAD_WATCH),
            ({"watch_after_min": "30"}, dd.BAD_WATCH),
            ({"group": "x" * 33}, "The group can be at most 32 characters."),
            ({"owner": 3}, "The owner must be text."),
            (
                {"notes": "a\nb"},
                "Notes can't contain line breaks, control or formatting characters.",
            ),
            ([1, 2], "The request body must be a JSON object."),
        ]
        await self.client.put(URL, json={"group": "Kids"})
        for body, reason in cases:
            resp = await self.client.put(URL, json=body)
            assert resp.status == 400, body
            assert (await resp.json())["error"] == reason, body
        resp = await self.client.put(
            URL, data="not json", headers={"Content-Type": "application/json"}
        )
        assert resp.status == 400
        assert (await resp.json())["error"] == "The request body must be JSON."
        assert self.details.export() == {MAC: {"group": "Kids"}}

    async def test_a_malformed_mac_is_a_400_and_leaves_the_real_device_alone(self):
        assert normalize_mac("AA:BB:CC:DD:EE:FF:00") == MAC  # why strict_mac exists
        await self.client.put(URL, json={"group": "Kids", "notes": "keep"})
        before = self.details.get(MAC)
        for raw in BAD_MACS:
            url = f"/api/devices/registry/{raw}/details"
            put = await self.client.put(url, json={"group": "Other"})
            delete = await self.client.delete(url)
            for resp in (put, delete):
                assert resp.status == 400, raw
                assert (await resp.json())["error"] == dd.BAD_MAC, raw
            assert self.details.get(MAC) == before, raw
        assert self.details.export() == {MAC: {"group": "Kids", "notes": "keep"}}


class TestDelete(_Base):
    async def test_delete_clears_and_answers_with_nones(self):
        await self.client.put(URL, json={"group": "Kids", "notes": "x"})
        resp = await self.client.delete(URL)
        assert resp.status == 200
        device = (await resp.json())["device"]
        assert _four(device) == dict.fromkeys(FOUR) and device["ips"] == ["10.0.0.5"]
        assert self.details.export() == {}

    async def test_delete_works_for_a_device_the_registry_doesnt_know(self):
        self.details.update(GONE, {"owner": "Sam"})
        resp = await self.client.delete(f"/api/devices/registry/{GONE}/details")
        assert resp.status == 200
        device = (await resp.json())["device"]
        assert device["mac"] == GONE and _four(device) == dict.fromkeys(FOUR)
        assert self.details.export() == {}

    async def test_delete_works_while_opensearch_is_down(self):
        self.details.update(MAC, {"owner": "Sam"})
        self.os.get.side_effect = OpenSearchException("down")
        resp = await self.client.delete(URL)
        assert resp.status == 200 and self.details.export() == {}


class TestStoreFailures(_Base):
    async def test_a_damaged_file_is_a_503_for_both_routes(self):
        self.details._problem = "Device details file is unreadable: x"
        for resp in (
            await self.client.put(URL, json={"group": "Kids"}),
            await self.client.delete(URL),
        ):
            assert resp.status == 503
            assert (await resp.json())["error"] == dd.UNREADABLE

    async def test_the_names_routes_keep_their_own_503(self):
        self.custom._problem = "Device names file is unreadable: x"
        resp = await self.client.put(
            f"/api/devices/registry/{MAC}/name", json={"name": "TV"}
        )
        assert resp.status == 503
        assert (await resp.json())["error"] == (
            "Device names and pictures can't be saved: their file is unreadable."
        )

    async def test_a_write_failure_is_a_500_and_changes_nothing(self):
        self.details.update(MAC, {"group": "Kids"})
        with patch.object(dd, "write_file_atomic", side_effect=OSError("disk full")):
            resp = await self.client.put(URL, json={"group": "Other"})
            delete = await self.client.delete(URL)
        for r in (resp, delete):
            assert r.status == 500
            assert (await r.json())["error"] == STORAGE_FAILED
        assert self.details.get(MAC)["group"] == "Kids"
        assert DeviceDetailsStore(self.tmp.name).get(MAC)["group"] == "Kids"


class TestRegisteredOnlyWithAStore(AioHTTPTestCase):
    async def get_application(self):
        self.tmp = tempfile.TemporaryDirectory()
        custom = DeviceCustomStore(self.tmp.name)
        os_client = MagicMock()
        os_client.get.side_effect = _get_returns(TV)
        app = web.Application()
        app["device_registry"] = _registry(os_client, custom)
        register_device_custom_routes(app, custom)  # the two-argument form
        return app

    async def tearDownAsync(self):
        self.tmp.cleanup()

    async def test_no_details_routes_and_names_still_work(self):
        assert (await self.client.put(URL, json={"group": "Kids"})).status == 404
        resp = await self.client.put(
            f"/api/devices/registry/{MAC}/name", json={"name": "TV"}
        )
        assert resp.status == 200
        assert (await resp.json())["device"]["group"] is None
