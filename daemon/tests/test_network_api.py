"""GET /api/network/lan (NET-160): the daemon's own LAN rule for the web app's links."""

from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from api.network import register_network_routes
from services.excluded_ips import build_lan_filter
from tests.fake_drill_opensearch import AUTH, make_app


class LanCase(AioHTTPTestCase):
    subnets: list = []

    async def get_application(self):
        return make_app(
            None,
            lambda app, _client: register_network_routes(app),
            lan_filter=build_lan_filter(self.subnets),
        )

    async def lan(self):
        resp = await self.client.get("/api/network/lan", headers=AUTH)
        self.assertEqual(resp.status, 200)
        return await resp.json()


class TestDetected(LanCase):
    subnets = [(192, 168, 1), (10, -1, -1), (172, 16, -1)]

    async def test_detected_subnets_in_cidr_form_and_ipv6_never_lan(self):
        with patch.dict("os.environ", {"LAN_SUBNETS": ""}):
            body = await self.lan()
        self.assertEqual(
            body["subnets"], ["192.168.1.0/24", "10.0.0.0/8", "172.16.0.0/16"]
        )
        self.assertEqual((body["source"], body["ipv6"]), ("detected", "not-lan"))
        self.assertRegex(body["version"], r"^[0-9a-f]{12}$")

    async def test_a_manual_override_is_reported_as_env(self):
        with patch.dict("os.environ", {"LAN_SUBNETS": "192.168.1.0/24"}):
            self.assertEqual((await self.lan())["source"], "env")

    async def test_the_route_needs_the_token(self):
        self.assertEqual((await self.client.get("/api/network/lan")).status, 401)


class TestFallback(LanCase):
    subnets = []

    async def test_no_subnets_means_all_of_rfc1918_with_its_own_version(self):
        body = await self.lan()
        self.assertEqual((body["subnets"], body["source"]), ([], "rfc1918"))
        self.assertNotEqual(body["version"], "")
