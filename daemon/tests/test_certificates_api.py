"""A failed certificate stats query is a 503, never zeros that read as real counts."""

import asyncio
import threading
from unittest.mock import MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.certificates import register_certificate_routes
from services.cert_monitor import (
    CertificateMonitor,
    CertQueryFailed,
    CertStatsUnavailable,
)
from services.cert_overview import Budget, CertTooBig, CertTooSlow
from tests.fake_cert_opensearch import RawOpenSearch, ssl, x509


class TestCertStatsEndpoint(AioHTTPTestCase):
    async def get_application(self):
        self.monitor = MagicMock(spec=CertificateMonitor)
        app = web.Application()
        register_certificate_routes(app, self.monitor)
        return app

    async def test_failed_query_is_503(self):
        self.monitor.get_cert_stats.side_effect = CertStatsUnavailable("boom")
        resp = await self.client.get("/api/certificates/stats")
        self.assertEqual(resp.status, 503)
        self.assertIn("error", await resp.json())

    async def test_counts_pass_through(self):
        self.monitor.get_cert_stats.return_value = {"total_certs": 85}
        resp = await self.client.get("/api/certificates/stats")
        self.assertEqual(resp.status, 200)
        self.assertEqual((await resp.json())["total_certs"], 85)

    async def test_failed_list_queries_are_503_not_empty_lists(self):
        """#96: an empty list read as "no expiring / self-signed certificates / CA changes"."""
        for read, path in (
            ("get_certificates", ""),
            ("get_expiring_certs", "/expiring"),
            ("detect_self_signed", "/self-signed"),
            ("detect_issuer_changes", "/issuer-changes"),
        ):
            getattr(self.monitor, read).side_effect = CertQueryFailed("boom")
            resp = await self.client.get(f"/api/certificates{path}")
            self.assertEqual(resp.status, 503, path)
            self.assertIn("error", await resp.json())

    async def test_failed_issuer_change_count_is_503(self):
        """#96: the issuer-change scan failing inside stats read as 0 CA changes."""
        self.monitor.get_cert_stats.side_effect = CertQueryFailed("boom")
        resp = await self.client.get("/api/certificates/stats")
        self.assertEqual(resp.status, 503)


class TestCertificateOverviewEndpoint(AioHTTPTestCase):
    """NET-154: one pass at a time, inside a budget, complete or a 503 with a reason."""

    async def get_application(self):
        self.monitor = MagicMock(spec=CertificateMonitor)
        app = web.Application()
        register_certificate_routes(app, self.monitor)
        return app

    async def test_overview_is_complete_figures_with_capped_lists_and_details(self):
        sessions = [
            ssl(["A"], sni="a.com"),
            ssl(["B"], sni="b.com", status="unable to get local issuer certificate"),
        ]
        real = CertificateMonitor(RawOpenSearch(sessions, [x509("A"), x509("B")]))
        self.monitor.overview.side_effect = real.overview
        resp = await self.client.get(
            "/api/certificates/overview?from=2026-11-05T00:00:00Z&to=2026-11-05T12:00:00Z"
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["summary"]["sessions"], 2)
        self.assertEqual((body["sites_total"], body["sites_truncated"]), (2, False))
        self.assertEqual(body["findings"][0]["kind"], "unverified")
        self.assertEqual(set(body["details"]), {"A", "B"})
        self.assertEqual(body["from"], "2026-11-05T00:00:00Z")

    async def test_each_failure_has_its_own_503_reason(self):
        for error, words in (
            (CertTooSlow("slow"), "took too long"),
            (CertTooBig("big"), "too much"),
            (CertQueryFailed("down"), "unavailable"),
        ):
            self.monitor.overview.side_effect = error
            resp = await self.client.get("/api/certificates/overview")
            self.assertEqual(resp.status, 503)
            self.assertIn(words, (await resp.json())["error"])

    async def test_an_unreadable_window_is_a_400_not_a_default(self):
        resp = await self.client.get("/api/certificates/overview?from=now-5m")
        self.assertEqual(resp.status, 400)
        self.monitor.overview.assert_not_called()

    async def test_a_second_pass_waits_for_the_first_and_the_lock_outlives_a_cancelled_request(
        self,
    ):
        started, release = threading.Event(), threading.Event()

        def slow(*_args, **_kw):
            started.set()
            release.wait(5)
            return {"summary": {}}

        self.monitor.get_cert_stats.side_effect = slow
        first = asyncio.ensure_future(self.client.get("/api/certificates/stats"))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
        lock = self.app["cert_lock"]
        self.assertTrue(lock.locked())
        first.cancel()  # the client gives up; the thread is still working
        await asyncio.sleep(0.05)
        self.assertTrue(lock.locked())
        release.set()
        for _ in range(100):
            if not lock.locked():
                break
            await asyncio.sleep(0.01)
        self.assertFalse(lock.locked())

    async def test_a_request_that_cannot_get_in_within_its_budget_is_busy(self):
        lock = self.app["cert_lock"]
        await lock.acquire()
        try:
            with patch("api.certificates.Budget", lambda: Budget(0.05)):
                resp = await self.client.get("/api/certificates/overview")
            self.assertEqual(resp.status, 503)
            self.assertIn("already being worked out", (await resp.json())["error"])
        finally:
            lock.release()


class TestCertificateOverviewNarrowed(AioHTTPTestCase):
    """NET-160: ?site= and ?server= narrow the sessions before anything is tallied or cut."""

    WINDOW = "from=2026-11-05T00:00:00Z&to=2026-11-05T12:00:00Z"

    async def get_application(self):
        sessions = [
            # one name served by two addresses, each with its own certificate
            ssl(["A"], sni="shop.example.com", server="93.184.216.34"),
            ssl(["B"], sni="Shop.Example.com.", server="93.184.216.35"),
            ssl(["B"], sni="shop.example.com", server="93.184.216.35"),
            # busier sites that fill a capped unfiltered list
            *[ssl(["C"], sni="busy.com") for _ in range(3)],
            *[ssl(["D"], sni="busier.com") for _ in range(4)],
        ]
        self.os = RawOpenSearch(sessions, [x509(fp) for fp in "ABCD"])
        app = web.Application()
        register_certificate_routes(app, CertificateMonitor(self.os))
        return app

    async def overview(self, query, status=200):
        resp = await self.client.get(
            f"/api/certificates/overview?{self.WINDOW}&{query}"
        )
        self.assertEqual(resp.status, status, await resp.text())
        return await resp.json()

    async def test_site_and_server_show_only_that_servers_certificate(self):
        body = await self.overview("site=shop.example.com&server=93.184.216.35")
        self.assertEqual(body["summary"]["sessions"], 2)
        self.assertEqual(set(body["details"]), {"B"})
        site_only = await self.overview("site=SHOP.example.com.")
        self.assertEqual(site_only["summary"]["sessions"], 3)  # both forms, any case
        self.assertEqual(set(site_only["details"]), {"A", "B"})

    async def test_a_site_past_the_row_cap_is_still_reached(self):
        with patch("api.certificates._ROW_LIMIT", 2):
            everything = await self.overview("")
            narrowed = await self.overview("site=shop.example.com")
        self.assertNotIn("shop.example.com", [s["name"] for s in everything["sites"]])
        self.assertTrue(everything["sites_truncated"])
        # the page keeps each spelling the network sent as its own site row
        self.assertEqual(
            {s["name"].lower().rstrip(".") for s in narrowed["sites"]},
            {"shop.example.com"},
        )

    async def test_a_bad_site_or_server_is_a_400(self):
        for query in ("site=bad..name", "server=example.com", "server=10.0.0.0/8"):
            self.assertIn("error", await self.overview(query, status=400))
        self.assertEqual(self.os.bodies, [])


class TestCertificateTimeouts(AioHTTPTestCase):
    """NET-160 review: an OpenSearch timeout is "too slow" (try a shorter window), not "unavailable"."""

    async def get_application(self):
        def timed_out(kind, reply):
            return {**reply, "timed_out": True} if kind == "sessions" else reply

        self.os = RawOpenSearch([ssl(["A"])], [x509("A")], tamper=timed_out)
        app = web.Application()
        register_certificate_routes(app, CertificateMonitor(self.os))
        return app

    async def test_a_timed_out_search_is_a_503_saying_it_took_too_long(self):
        resp = await self.client.get(
            "/api/certificates/overview?from=2026-11-05T00:00:00Z&to=2026-11-05T12:00:00Z"
        )
        self.assertEqual(resp.status, 503)
        self.assertIn("took too long", (await resp.json())["error"])
