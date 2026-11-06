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
