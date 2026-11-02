"""A failed certificate stats query is a 503, never zeros that read as real counts."""

from unittest.mock import MagicMock

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.certificates import register_certificate_routes
from services.cert_monitor import CertificateMonitor, CertQueryFailed, CertStatsUnavailable


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
