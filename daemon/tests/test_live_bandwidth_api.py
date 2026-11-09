"""NET-205: the live bandwidth routes: one device key, meter errors, and the opt-in setting."""

import asyncio
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

import services.live_bandwidth as lb
from api.live_bandwidth import (
    METER_KEY,
    handle_get_setting,
    handle_live_bandwidth,
    handle_put_setting,
    register_live_bandwidth_routes,
)
from services.excluded_ips import build_lan_filter
from services.live_bandwidth import (
    BUSY,
    LiveBandwidthBusyError,
    LiveBandwidthError,
    LiveBandwidthMeter,
)
from services.live_bandwidth_tc import Key
from tests.live_bandwidth_fake import Clock, FakeTc, Manager

URL = "/api/live-bandwidth"
SETTING = "/api/settings/live-bandwidth"


class TestLiveBandwidthRoute(AioHTTPTestCase):
    async def get_application(self):
        self.meter = MagicMock()
        self.meter.watch = AsyncMock(return_value={"supported": True})
        app = web.Application()
        app[METER_KEY] = self.meter
        app["lan_filter"] = build_lan_filter([(192, 168, 1)])
        app.router.add_get(URL, handle_live_bandwidth)
        return app

    async def _status(self, query):
        resp = await self.client.get(URL + query)
        return resp.status, await resp.json()

    async def test_bad_keys_are_400_and_never_reach_the_meter(self):
        for query in [
            "",
            "?mac=02:00:00:00:00:0a&ip=192.168.1.5",
            "?mac=02:00:00:00:00:0a&mac=02:00:00:00:00:0b",
            "?mac=zz",
            "?mac=01:00:5e:00:00:01",  # multicast
            "?mac=ff:ff:ff:ff:ff:ff",
            "?mac=00:00:00:00:00:00",
            "?mac=aa:bb:cc:dd:ee:ff%0A:00",  # a newline would split the tc batch line
            "?ip=fe80::1",
            "?ip=192.168.1.0/24",
            "?ip=8.8.8.8",
            "?ip=192.168.2.5",  # outside the detected LAN
        ]:
            status, body = await self._status(query)
            self.assertEqual(status, 400, query)
            self.assertIn("error", body)
        self.meter.watch.assert_not_called()

    async def test_mac_is_normalised_to_lower_case_colons(self):
        status, body = await self._status("?mac=AA-BB-CC-DD-EE-01")
        self.assertEqual((status, body), (200, {"supported": True}))
        self.meter.watch.assert_awaited_once_with(Key("mac", "aa:bb:cc:dd:ee:01"))

    async def test_lan_ip_is_passed_on(self):
        status, _ = await self._status("?ip=192.168.1.5")
        self.assertEqual(status, 200)
        self.meter.watch.assert_awaited_once_with(Key("ip", "192.168.1.5"))

    async def test_busy_is_503_and_a_tc_failure_is_500(self):
        self.meter.watch.side_effect = LiveBandwidthBusyError(BUSY)
        self.assertEqual(await self._status("?ip=192.168.1.5"), (503, {"error": BUSY}))
        self.meter.watch.side_effect = LiveBandwidthError("Couldn't start measuring: x")
        status, body = await self._status("?ip=192.168.1.5")
        self.assertEqual(status, 500)
        self.assertEqual(body, {"error": "Couldn't start measuring: x"})


class TestNoDetectedLan(AioHTTPTestCase):
    async def get_application(self):
        self.meter = MagicMock()
        self.meter.watch = AsyncMock(return_value={"supported": True})
        app = web.Application()
        app[METER_KEY] = self.meter  # no lan_filter: any private address counts
        app.router.add_get(URL, handle_live_bandwidth)
        return app

    async def test_any_rfc1918_address_is_accepted(self):
        resp = await self.client.get(URL + "?ip=10.1.2.3")
        self.assertEqual(resp.status, 200)
        resp = await self.client.get(URL + "?ip=100.64.0.1")
        self.assertEqual(resp.status, 400)


class TestSetting(AioHTTPTestCase):
    """A real meter on a fake tc; the setting file in a temporary directory."""

    async def get_application(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        net_dir = os.path.join(tmp.name, "net")
        os.makedirs(os.path.join(net_dir, "enp4s0"))
        with open(os.path.join(net_dir, "enp4s0", "operstate"), "w") as f:
            f.write("up\n")
        self.file = os.path.join(tmp.name, "data", "live_bandwidth.json")
        clock = Clock()
        self.fake = FakeTc(clock)
        for patcher in (
            patch.dict(os.environ, {"LIVE_BANDWIDTH_FILE": self.file}),
            patch.object(lb, "run_tool", self.fake.run),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        manager = Manager()
        self.meter = LiveBandwidthMeter(
            get_manager=lambda: manager,
            get_capture_lock=lambda: None,
            clock=clock,
            net_dir=net_dir,
            autostart=False,
        )
        app = web.Application()
        app[METER_KEY] = self.meter
        app.router.add_get(SETTING, handle_get_setting)
        app.router.add_put(SETTING, handle_put_setting)
        return app

    async def _put(self, data):
        resp = await self.client.put(SETTING, data=data)
        return resp.status, await resp.json()

    async def test_get_shape(self):
        resp = await self.client.get(SETTING)
        self.assertEqual(resp.status, 200)
        self.assertEqual(
            await resp.json(),
            {
                "enabled": False,
                "supported": True,
                "reason": None,
                "mode": "mirror",
                "cleanup": {"state": "idle", "failed": {}},
            },
        )

    async def test_put_refuses_anything_but_a_json_bool(self):
        for data in ["{not json", "[]", "{}", '{"enabled": "true"}', '{"enabled": 1}']:
            status, body = await self._put(data)
            self.assertEqual(status, 400, data)
            self.assertIn("error", body)
        self.assertFalse(self.meter.enabled)
        self.assertFalse(os.path.exists(self.file))

    async def test_put_on_saves_then_applies(self):
        status, body = await self._put('{"enabled": true}')
        self.assertEqual((status, body["enabled"]), (200, True))
        self.assertTrue(self.meter.enabled)
        with open(self.file) as f:
            self.assertEqual(json.load(f), {"enabled": True})

    async def test_a_save_failure_changes_nothing(self):
        with patch("api.live_bandwidth.save_enabled", side_effect=OSError("disk full")):
            status, body = await self._put('{"enabled": true}')
        self.assertEqual(status, 500)
        self.assertEqual(body, {"error": "Couldn't save the setting", "enabled": False})
        self.assertFalse(self.meter.enabled)
        self.assertFalse(os.path.exists(self.file))

    async def test_put_off_returns_while_the_cleanup_is_still_blocked_in_tc(self):
        self.meter.set_enabled(True)
        await self.meter.reconcile()
        await self.meter.watch(Key("mac", "02:00:00:00:00:0a"))
        self.fake.gate = asyncio.Event()  # removal waits until the test lets it go
        status, body = await self._put('{"enabled": false}')
        self.assertEqual((status, body["enabled"]), (200, False))
        self.assertEqual(body["cleanup"]["state"], "running")
        await self.fake.at_gate.wait()
        self.fake.gate.set()
        await self.meter._cleanup_task
        self.assertEqual(self.fake.owned(), {})
        resp = await self.client.get(SETTING)
        self.assertEqual(
            (await resp.json())["cleanup"], {"state": "idle", "failed": {}}
        )


def test_register_adds_the_routes_and_reads_the_saved_setting(tmp_path, monkeypatch):
    path = tmp_path / "live_bandwidth.json"
    path.write_text('{"enabled": true}')
    monkeypatch.setenv("LIVE_BANDWIDTH_FILE", str(path))
    app = web.Application()
    meter = register_live_bandwidth_routes(app)
    assert isinstance(meter, LiveBandwidthMeter) and app[METER_KEY] is meter
    assert meter.enabled is True
    assert meter.shutdown in app.on_cleanup
    routes = {(r.method, r.resource.canonical) for r in app.router.routes()}
    assert {("GET", URL), ("GET", SETTING), ("PUT", SETTING)} <= routes


def test_register_starts_off_without_a_saved_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_BANDWIDTH_FILE", str(tmp_path / "missing.json"))
    assert register_live_bandwidth_routes(web.Application()).enabled is False
