"""MAC Lookup falls back to Malcolm's IEEE vendor for prefixes seen on the network (#26)."""

from unittest.mock import MagicMock

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.tools import register_tools_routes
from services.mac_lookup_service import MacLookupService

PROXMOX_HIT = {
    "hits": {
        "hits": [{"_source": {"source": {"oui": "Proxmox Server Solutions GmbH"}}}]
    }
}


class TestMacLookupNetworkFallback(AioHTTPTestCase):
    async def get_application(self):
        self.client_os = MagicMock()
        app = web.Application()
        mac_lookup = MacLookupService(opensearch_client=self.client_os)
        register_tools_routes(app, MagicMock(), mac_lookup, MagicMock(), MagicMock())
        return app

    async def test_unknown_prefix_uses_vendor_seen_on_network(self):
        self.client_os.search.return_value = PROXMOX_HIT
        resp = await self.client.get("/api/tools/mac-lookup/BC:24:11:E9:4E:56")
        body = await resp.json()
        self.assertEqual(resp.status, 200)
        self.assertEqual(
            (body["vendor"], body["found"]), ("Proxmox Server Solutions GmbH", True)
        )
        query = self.client_os.search.call_args.kwargs["body"]["query"]["bool"][
            "filter"
        ]
        self.assertIn({"prefix": {"source.mac": "bc:24:11"}}, query)

    async def test_never_seen_prefix_stays_not_found(self):
        self.client_os.search.return_value = {"hits": {"hits": []}}
        body = await (
            await self.client.get("/api/tools/mac-lookup/BC:24:11:E9:4E:56")
        ).json()
        self.assertEqual((body["vendor"], body["found"]), (None, False))

    async def test_opensearch_down_still_answers(self):
        self.client_os.search.side_effect = ConnectionError("down")
        resp = await self.client.get("/api/tools/mac-lookup/BC:24:11:E9:4E:56")
        self.assertEqual(resp.status, 200)
        self.assertFalse((await resp.json())["found"])


def test_randomized_mac_never_queries():
    client = MagicMock()
    result = MacLookupService(opensearch_client=client).lookup("0E:CC:55:A1:28:66")
    assert result["found"] is False
    client.search.assert_not_called()


def test_registry_vendor_pass_uses_the_fallback():
    """enrich_with_oui fills registry entries that the 1-hour refresh no longer revisits."""
    from services.device_registry import DeviceRegistry

    client = MagicMock()
    client.search.side_effect = [
        {
            "hits": {
                "hits": [
                    {"_source": {"mac": "70:A7:41:3F:1B:59", "ips": ["192.168.1.220"]}}
                ]
            }
        },
        {"hits": {"hits": [{"_source": {"source": {"oui": "Ubiquiti Inc"}}}]}},
    ]
    client.get.return_value = {
        "_source": {"mac": "70:A7:41:3F:1B:59", "ips": ["192.168.1.220"]}
    }
    registry = DeviceRegistry(client=client)

    assert registry.enrich_with_oui(MacLookupService(opensearch_client=client)) == 1
    assert client.index.call_args.kwargs["body"]["manufacturer"] == "Ubiquiti Inc"
