"""GET /api/tools/mac-lookup falls back to Malcolm's IEEE vendor for prefixes seen on the network (#26)."""

from unittest.mock import MagicMock

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.tools import register_tools_routes
from services.mac_lookup_service import MacLookupService


class TestMacLookupNetworkFallback(AioHTTPTestCase):
    async def get_application(self):
        self.storage = MagicMock()
        app = web.Application()
        app["storage"] = self.storage
        register_tools_routes(app, MagicMock(), MacLookupService(), MagicMock(), MagicMock())
        return app

    async def test_unknown_prefix_uses_vendor_seen_on_network(self):
        self.storage._client.search.return_value = {
            "hits": {"hits": [{"_source": {"source": {"oui": "Proxmox Server Solutions GmbH"}}}]}
        }
        resp = await self.client.get("/api/tools/mac-lookup/BC:24:11:E9:4E:56")
        body = await resp.json()
        self.assertEqual(resp.status, 200)
        self.assertEqual((body["vendor"], body["found"]), ("Proxmox Server Solutions GmbH", True))
        query = self.storage._client.search.call_args.kwargs["body"]["query"]["bool"]["filter"]
        self.assertIn({"prefix": {"source.mac": "bc:24:11"}}, query)

    async def test_never_seen_prefix_stays_not_found(self):
        self.storage._client.search.return_value = {"hits": {"hits": []}}
        body = await (await self.client.get("/api/tools/mac-lookup/BC:24:11:E9:4E:56")).json()
        self.assertEqual((body["vendor"], body["found"]), (None, False))

    async def test_opensearch_down_still_answers(self):
        self.storage._client.search.side_effect = ConnectionError("down")
        resp = await self.client.get("/api/tools/mac-lookup/BC:24:11:E9:4E:56")
        self.assertEqual(resp.status, 200)
        self.assertFalse((await resp.json())["found"])
