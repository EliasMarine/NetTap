"""
Unreadable from/to is a 400 everywhere, never the default window.

On the device the Infrastructure page sent from=now-5m, got 24 h of connections
back and showed 1,601 evt/s for a real rate of about 5/s.
"""

import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import (
    AioHTTPTestCase,
    TestClient,
    TestServer,
    unittest_run_loop,
)

from api.alerts import _ALLOWED_INTERVALS as ALERT_INTERVALS
from api.alerts import register_alert_routes
from api.changelog import _parse_time_range as changelog_time_range
from api.changelog import register_changelog_routes
from api.devices import register_device_routes
from api.devices_v2 import register_devices_v2_routes
from api.dns import register_dns_routes
from api.drilldown_runner import CHART_INTERVALS
from api.logs import _ALLOWED_INTERVALS as LOG_INTERVALS
from api.threats import register_threat_routes
from api.time_range import BUCKET_TABLE, parse_time_range
from api.traffic import register_traffic_routes
from services.device_registry import DeviceRegistry
from services.excluded_ips import build_lan_filter
from storage.manager import RetentionConfig, StorageManager
from storage.time_slots import interval_seconds, time_slots
from tests.fake_drill_opensearch import AUTH, DrillOpenSearch, make_app
from tests.test_devices_api import _answering

DAY = timedelta(hours=24)


def _request(params: dict) -> MagicMock:
    req = MagicMock()
    req.query = params
    return req


def _span(from_ts: str, to_ts: str) -> float:
    return (
        datetime.fromisoformat(to_ts) - datetime.fromisoformat(from_ts)
    ).total_seconds()


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
            parse_time_range(
                _request({"from": "2026-11-02T21:00:00Z", "to": "now"}), DAY
            )
        self.assertIn("to must be", json.loads(ctx.exception.text)["error"])

    def test_accepts_z_and_offset(self):
        req = _request(
            {"from": "2026-11-02T21:00:00Z", "to": "2026-11-02T21:05:00+00:00"}
        )
        self.assertEqual(
            parse_time_range(req, DAY),
            ("2026-11-02T21:00:00Z", "2026-11-02T21:05:00+00:00"),
        )

    def test_a_backwards_range_is_400(self):
        """#120: it went on to OpenSearch; the time slots can't be built for it."""
        with self.assertRaises(web.HTTPBadRequest) as ctx:
            parse_time_range(
                _request(
                    {"from": "2026-11-02T22:00:00Z", "to": "2026-11-02T23:00:00+02:00"}
                ),
                DAY,
            )
        self.assertEqual(
            json.loads(ctx.exception.text), {"error": "from must not be later than to"}
        )

    def test_a_time_without_a_zone_is_utc(self):
        req = _request({"from": "2026-11-02T21:00:00", "to": "2026-11-02T21:30:00Z"})
        self.assertEqual(
            parse_time_range(req, DAY), ("2026-11-02T21:00:00", "2026-11-02T21:30:00Z")
        )

    def test_a_utc_year_outside_1970_to_9998_is_400(self):
        """NET-275: year 9999 (a 3 h slot ends in year 10000) or 0001 at +14:00 (year 0 in
        UTC) passed, and time_slots raised after the device searches had run, a 500."""
        for ts in (
            "9999-12-31T23:59:59Z",
            "9999-01-01T00:00:00Z",
            "0001-01-01T00:00:00+14:00",
            "9999-12-31T23:59:59-14:00",
            "1969-12-31T23:59:59Z",
            "1970-01-01T00:30:00+01:00",  # 1969 in UTC
        ):
            for params in ({"from": ts, "to": ts}, {"to": ts}):
                with self.assertRaises(web.HTTPBadRequest, msg=(ts, params)) as ctx:
                    parse_time_range(_request(params), DAY)
                name = next(iter(params))
                self.assertEqual(
                    json.loads(ctx.exception.text),
                    {"error": f"{name} must be a time between 1970 and 9998"},
                    (ts, params),
                )

    def test_1970_and_9998_are_accepted(self):
        for from_ts, to_ts in (
            ("1970-01-01T00:00:00Z", "1970-01-01T00:00:00Z"),
            ("9998-12-31T23:59:59Z", "9998-12-31T23:59:59Z"),
            ("1970-01-01T00:00:00Z", "9998-12-31T23:59:59Z"),
            # judged by the UTC year: 9998-12-31T10:00Z and 1970-01-01T00:30Z
            ("9999-01-01T00:00:00+14:00", "9999-01-01T00:00:00+14:00"),
            ("1969-12-31T23:30:00-01:00", "1969-12-31T23:30:00-01:00"),
        ):
            req = _request({"from": from_ts, "to": to_ts})
            self.assertEqual(parse_time_range(req, DAY), (from_ts, to_ts))

    def test_the_longest_bucket_fits_in_the_top_year(self):
        """The 9998 bound's premise: the longest chart bucket's last slot of 9998 still ends
        inside datetime's year 9999 (time_slots raises otherwise)."""
        longest = max(
            ALERT_INTERVALS | LOG_INTERVALS | CHART_INTERVALS | BUCKET_TABLE,
            key=interval_seconds,
        )
        time_slots("9998-12-31T23:59:59Z", "9998-12-31T23:59:59Z", longest)

    def test_empty_and_absent_use_default_span(self):
        for params in ({}, {"from": "", "to": ""}):
            from_ts, to_ts = parse_time_range(_request(params), DAY)
            self.assertAlmostEqual(_span(from_ts, to_ts), DAY.total_seconds(), delta=5)

    def test_changelog_keeps_none_and_empty(self):
        self.assertEqual(changelog_time_range(_request({})), (None, None))
        self.assertEqual(
            changelog_time_range(_request({"from": "", "to": ""})), ("", "")
        )
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
        self.assertAlmostEqual(
            _span(data["from"], data["to"]), DAY.total_seconds(), delta=5
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("ts", ["9999-12-31T23:59:59Z", "0001-01-01T00:00:00+14:00"])
async def test_device_pages_refuse_an_extreme_year_before_searching(ts):
    """NET-275: the MAC and IP device routes searched, then time_slots raised on year 10000
    or year 0 and safe_error_middleware answered a generic 500 with a traceback."""
    registry_client = MagicMock()
    registry = DeviceRegistry(client=registry_client)
    registry_client.reset_mock()  # the index check at start-up is not a search
    # answered as on the device, so without the check the route gets as far as time_slots
    registry_client.get.return_value = {"_source": {"mac": "00:00:5E:00:53:30"}}
    registry_client.search.side_effect = _answering({"hits": {"total": {"value": 0}}})
    drill = DrillOpenSearch([])

    def register(app, client):
        app["storage"] = SimpleNamespace(_client=client)
        register_device_routes(app, app["storage"])
        register_devices_v2_routes(app, registry, MagicMock())

    app = make_app(drill, register, lan_filter=build_lan_filter([(192, 168, 1)]))
    async with TestClient(TestServer(app)) as client:
        for path in (
            "/api/devices/registry/00:00:5e:00:53:30/traffic",
            "/api/devices/192.168.1.30",
        ):
            resp = await client.get(path, params={"from": ts, "to": ts}, headers=AUTH)
            assert (resp.status, await resp.json()) == (
                400,
                {"error": "from must be a time between 1970 and 9998"},
            ), path
    assert registry_client.method_calls == []
    assert drill.bodies == []


if __name__ == "__main__":
    unittest.main()
