"""
Unreadable from/to is a 400 everywhere, never the default window.

On the device the Infrastructure page sent from=now-5m, got 24 h of connections
back and showed 1,601 evt/s for a real rate of about 5/s.
"""

import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.alerts import register_alert_routes
from api.changelog import _parse_time_range as changelog_time_range
from api.changelog import register_changelog_routes
from api.dns import register_dns_routes
from api.threats import register_threat_routes
from api.time_range import parse_time_range
from api.traffic import register_traffic_routes
from storage.manager import RetentionConfig, StorageManager

DAY = timedelta(hours=24)


def _request(params: dict) -> MagicMock:
    req = MagicMock()
    req.query = params
    return req


def _span(from_ts: str, to_ts: str) -> float:
    return (datetime.fromisoformat(to_ts) - datetime.fromisoformat(from_ts)).total_seconds()


class TestParseTimeRange(unittest.TestCase):
    def test_rejects_relative_time(self):
        with self.assertRaises(web.HTTPBadRequest) as ctx:
            parse_time_range(_request({"from": "now-5m", "to": "now"}), DAY)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.content_type, "application/json")
        self.assertEqual(
            json.loads(ctx.exception.text),
            {"error": "from must be an ISO 8601 time such as 2026-11-02T21:00:00Z"},
        )

    def test_rejects_bad_to_by_name(self):
        with self.assertRaises(web.HTTPBadRequest) as ctx:
            parse_time_range(_request({"from": "2026-11-02T21:00:00Z", "to": "now"}), DAY)
        self.assertIn("to must be", json.loads(ctx.exception.text)["error"])

    def test_accepts_z_and_offset(self):
        req = _request({"from": "2026-11-02T21:00:00Z", "to": "2026-11-02T21:05:00+00:00"})
        self.assertEqual(
            parse_time_range(req, DAY), ("2026-11-02T21:00:00Z", "2026-11-02T21:05:00+00:00")
        )

    def test_empty_and_absent_use_default_span(self):
        for params in ({}, {"from": "", "to": ""}):
            from_ts, to_ts = parse_time_range(_request(params), DAY)
            self.assertAlmostEqual(_span(from_ts, to_ts), DAY.total_seconds(), delta=5)

    def test_changelog_keeps_none_and_empty(self):
        self.assertEqual(changelog_time_range(_request({})), (None, None))
        self.assertEqual(changelog_time_range(_request({"from": "", "to": ""})), ("", ""))
        with self.assertRaises(web.HTTPBadRequest):
            changelog_time_range(_request({"from": "now-7d"}))


class TestEndpointsRejectUnreadableTimes(AioHTTPTestCase):
    """Several modules' endpoints answer 400 and never reach OpenSearch."""

    def setUp(self):
        with patch.object(StorageManager, "_create_client") as mock_create:
            self.os_client = MagicMock()
            mock_create.return_value = self.os_client
            self.storage = StorageManager(RetentionConfig(), "http://localhost:9200")
        self.changelog = MagicMock()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_traffic_routes(app, self.storage)
        register_alert_routes(app, self.storage)
        register_dns_routes(app, self.storage)
        register_threat_routes(app, self.storage)
        register_changelog_routes(app, self.changelog)
        return app

    @unittest_run_loop
    async def test_relative_times_are_400_without_a_query(self):
        self.os_client.reset_mock()
        for path in (
            "/api/traffic/summary",
            "/api/alerts/count",
            "/api/dns/top-domains",
            "/api/threats/report",
            "/api/changelog",
        ):
            resp = await self.client.request("GET", f"{path}?from=now-5m&to=now")
            self.assertEqual(resp.status, 400, path)
            body = await resp.json()
            self.assertIn("from must be an ISO 8601 time", body["error"], path)
        self.assertEqual(self.os_client.method_calls, [])
        self.changelog.get_events.assert_not_called()

    @unittest_run_loop
    async def test_empty_from_still_uses_the_default_window(self):
        self.os_client.search.return_value = {
            "hits": {"total": {"value": 0}},
            "aggregations": {
                "total_orig_bytes": {"value": 0},
                "total_resp_bytes": {"value": 0},
                "total_orig_pkts": {"value": 0},
                "total_resp_pkts": {"value": 0},
                "top_protocol": {"buckets": []},
            },
        }
        resp = await self.client.request("GET", "/api/traffic/summary?from=&to=")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertAlmostEqual(_span(data["from"], data["to"]), DAY.total_seconds(), delta=5)


if __name__ == "__main__":
    unittest.main()
