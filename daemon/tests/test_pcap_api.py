"""GET /api/pcap/search answers at once with job progress instead of blocking."""

from unittest.mock import AsyncMock, MagicMock

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.pcap import register_pcap_routes
from services.pcap_search import PcapSearchService


class TestPcapSearchEndpoint(AioHTTPTestCase):
    async def get_application(self):
        self.svc = MagicMock(spec=PcapSearchService)
        app = web.Application()
        register_pcap_routes(app, self.svc)
        return app

    async def test_returns_progress(self):
        progress = {
            "filter": "dns",
            "count": 0,
            "results": [],
            "files_checked": 1,
            "files_total": 53,
            "complete": False,
            "timed_out": 0,
        }
        self.svc.search_progress = AsyncMock(return_value=progress)
        resp = await self.client.get("/api/pcap/search?filter=dns&from=a&to=b")
        self.assertEqual(resp.status, 200)
        self.assertEqual(await resp.json(), progress)
        self.svc.search_progress.assert_awaited_once_with("dns", "a", "b")

    async def test_invalid_filter_is_400(self):
        self.svc.search_progress = AsyncMock(
            side_effect=ValueError("Invalid display filter: x")
        )
        resp = await self.client.get("/api/pcap/search?filter=bad")
        self.assertEqual(resp.status, 400)

    async def test_missing_filter_is_400(self):
        resp = await self.client.get("/api/pcap/search")
        self.assertEqual(resp.status, 400)

    async def test_preview_reports_timed_out(self):
        self.svc.preview_with_status = AsyncMock(
            return_value={"packets": [], "timed_out": True}
        )
        resp = await self.client.get(
            "/api/pcap/preview?file=/opt/nettap/pcap/a.pcap&filter=dns"
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body["timed_out"])
        self.assertEqual(body["count"], 0)
