"""NET-364: DNS by device refuses a value that isn't one IP address with a 400 and a plain reason,
before any query; it used to reach OpenSearch, fail there and answer 502, which the page showed
as "check that NetTap is running". A valid address is queried in its canonical form."""

from unittest.mock import MagicMock

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.dns import handle_device_dns


class TestDeviceDnsAddress(AioHTTPTestCase):
    async def get_application(self):
        self.analytics = MagicMock()
        self.analytics.get_device_dns.return_value = []
        app = web.Application()
        app["dns_analytics"] = self.analytics
        app.router.add_get("/api/dns/device/{ip}", handle_device_dns)
        return app

    async def test_refuses_what_is_not_one_ip_address(self):
        for raw in (
            "not-an-address",
            "999.999.999.999",
            "10.0.0.0%2F8",
            "fe80::1%25eth0",
            "192.168.001.1",
        ):
            resp = await self.client.get(f"/api/dns/device/{raw}")
            self.assertEqual(resp.status, 400, raw)
            self.assertEqual(
                await resp.json(), {"error": "That is not an IP address."}, raw
            )
        self.analytics.get_device_dns.assert_not_called()

    async def test_queries_the_address_as_parsed(self):
        resp = await self.client.get("/api/dns/device/%20192.0.2.1%20")
        self.assertEqual(resp.status, 200)
        self.assertEqual((await resp.json())["device_ip"], "192.0.2.1")
        self.assertEqual(self.analytics.get_device_dns.call_args.args[0], "192.0.2.1")

        resp = await self.client.get("/api/dns/device/2001:DB8::1")
        self.assertEqual(resp.status, 200)
        self.assertEqual(
            self.analytics.get_device_dns.call_args.args[0], "2001:db8::1"
        )
