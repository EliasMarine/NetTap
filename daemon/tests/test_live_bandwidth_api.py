"""NET-205: GET /api/live-bandwidth validates exactly one device key and maps meter errors."""

from unittest.mock import AsyncMock, MagicMock

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.live_bandwidth import (
    METER_KEY,
    handle_live_bandwidth,
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

URL = "/api/live-bandwidth"


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


def test_register_adds_the_route_the_meter_and_its_cleanup():
    app = web.Application()
    meter = register_live_bandwidth_routes(app)
    assert isinstance(meter, LiveBandwidthMeter) and app[METER_KEY] is meter
    assert meter.shutdown in app.on_cleanup
    assert any(r.resource.canonical == URL for r in app.router.routes())
