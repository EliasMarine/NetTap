"""GET /api/pcap/search answers at once with job progress instead of blocking."""

from unittest.mock import AsyncMock, MagicMock

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.error_replies import safe_error_middleware
from api.pcap import register_pcap_routes
from services.container_exec import ReaderBusy
from services.pcap_search import PcapSearchService, SearchStartExpired


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
        # OLD CODE START — unreadable times were passed on (and dropped downstream); now a 400
        # resp = await self.client.get("/api/pcap/search?filter=dns&from=a&to=b")
        # self.svc.search_progress.assert_awaited_once_with("dns", "a", "b")
        # OLD CODE END
        resp = await self.client.get(
            "/api/pcap/search?filter=dns&from=2026-11-02T21:00:00Z&to=2026-11-02T22:00:00Z"
        )
        self.assertEqual(resp.status, 200)
        self.assertEqual(await resp.json(), progress)
        self.svc.search_progress.assert_awaited_once_with(
            "dns", "2026-11-02T21:00:00Z", "2026-11-02T22:00:00Z"
        )

    async def test_an_unreadable_time_is_400_not_every_file(self):
        # the service dropped an unreadable bound, so from=now-5m searched every capture
        for path in (
            "/api/pcap/files?from=now-5m",
            "/api/pcap/search?filter=dns&from=now-5m",
            "/api/pcap/download?filter=dns&to=yesterday",
        ):
            resp = await self.client.get(path)
            self.assertEqual(resp.status, 400, path)
            self.assertIn("ISO 8601", (await resp.json())["error"], path)
        self.svc.get_available_pcaps.assert_not_called()
        self.svc.search_progress.assert_not_called()
        self.svc.download_filtered.assert_not_called()

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


class TestNet347Replies(AioHTTPTestCase):
    """Written 5xx messages survive the error middleware; a refused filter is a 400 (NET-347)."""

    async def get_application(self):
        self.svc = MagicMock(spec=PcapSearchService)
        app = web.Application(middlewares=[safe_error_middleware])
        register_pcap_routes(app, self.svc)
        return app

    async def _search(self):
        resp = await self.client.get("/api/pcap/search?filter=dns")
        return resp.status, (await resp.json())["error"]

    async def test_busy_reader_is_503_with_its_message(self):
        self.svc.search_progress = AsyncMock(
            side_effect=ReaderBusy("The packet reader is busy; try again in a moment.")
        )
        self.assertEqual(
            await self._search(),
            (503, "The packet reader is busy; try again in a moment."),
        )

    async def test_a_late_start_is_503_with_its_message(self):
        self.svc.search_progress = AsyncMock(
            side_effect=SearchStartExpired(
                "The search took too long to start; try again."
            )
        )
        self.assertEqual(
            await self._search(), (503, "The search took too long to start; try again.")
        )

    async def test_a_check_that_could_not_run_is_500_without_internals(self):
        self.svc.search_progress = AsyncMock(
            side_effect=RuntimeError("sh: 1: Cannot fork")
        )
        status, error = await self._search()
        self.assertEqual(status, 500)
        self.assertIn("packet reader is running", error)
        self.assertNotIn("fork", error)

    async def test_check_filter_ok_and_refused(self):
        self.svc.check_filter = AsyncMock(return_value=None)
        resp = await self.client.post(
            "/api/pcap/check-filter", json={"filter": " dns "}
        )
        self.assertEqual(
            (resp.status, await resp.json()), (200, {"ok": True, "filter": "dns"})
        )
        self.svc.check_filter.assert_awaited_once_with("dns")
        self.svc.check_filter = AsyncMock(
            side_effect=ValueError("tshark: x is neither a field nor a protocol name.")
        )
        resp = await self.client.post("/api/pcap/check-filter", json={"filter": "x"})
        self.assertEqual(resp.status, 400)
        self.assertIn("neither a field", (await resp.json())["error"])

    async def test_check_filter_busy_and_unavailable(self):
        self.svc.check_filter = AsyncMock(
            side_effect=ReaderBusy("The packet reader is busy; try again in a moment.")
        )
        resp = await self.client.post("/api/pcap/check-filter", json={"filter": "dns"})
        self.assertEqual(resp.status, 503)
        self.assertIn("busy", (await resp.json())["error"])
        self.svc.check_filter = AsyncMock(
            side_effect=RuntimeError("docker: no such container")
        )
        resp = await self.client.post("/api/pcap/check-filter", json={"filter": "dns"})
        self.assertEqual(
            (resp.status, (await resp.json())["error"]),
            (500, "Couldn't check the filter just now."),
        )

    async def test_check_filter_needs_a_json_filter(self):
        for body in (b"not json", b"[]", b'{"filter": ""}', b'{"filter": 5}'):
            resp = await self.client.post(
                "/api/pcap/check-filter",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(resp.status, 400, body)
        self.svc.check_filter.assert_not_called()
