"""
Tests for daemon/services/bandwidth_tracker.py

All tests use mocks -- no OpenSearch connection required.
Tests cover monthly aggregation, projection math, per-device, and heatmap.
"""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from services.bandwidth_tracker import BandwidthTracker


class TestBandwidthTrackerNoClient(unittest.TestCase):
    """Tests for BandwidthTracker without an OpenSearch client."""

    def setUp(self):
        """Create a tracker with no client."""
        with patch("services.bandwidth_tracker._CAP_FILE", "/nonexistent/path"):
            self.tracker = BandwidthTracker(client=None)

    def test_monthly_usage_no_client(self):
        """Should return zeros when no client is configured."""
        result = self.tracker.get_monthly_usage(2026, 3)
        self.assertEqual(result["year"], 2026)
        self.assertEqual(result["month"], 3)
        self.assertEqual(result["total_bytes"], 0)

    def test_daily_usage_no_client(self):
        """Should return empty list when no client is configured."""
        result = self.tracker.get_daily_usage(
            "2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z"
        )
        self.assertEqual(result, [])

    def test_per_device_usage_no_client(self):
        """Should return empty list when no client is configured."""
        result = self.tracker.get_per_device_usage(
            "2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z"
        )
        self.assertEqual(result, [])

    def test_heatmap_no_client(self):
        """Should return zero-filled 7x24 matrix when no client is configured."""
        result = self.tracker.get_hourly_heatmap(
            "2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z"
        )
        self.assertEqual(len(result), 7)
        self.assertTrue(all(len(row) == 24 for row in result))
        self.assertTrue(all(v == 0 for row in result for v in row))

    def test_get_cap_default(self):
        """Default cap should be 0 (disabled)."""
        cap = self.tracker.get_cap()
        self.assertEqual(cap["monthly_cap_bytes"], 0)
        self.assertFalse(cap["enabled"])

    def test_save_and_get_cap(
        self,
    ):
        """Saving cap should update in-memory value."""
        with patch("services.bandwidth_tracker._CAP_FILE", "/tmp/test_bw_cap.json"):
            self.tracker.save_cap(1024 * 1024 * 1024 * 1200)  # 1200 GB
            cap = self.tracker.get_cap()
            self.assertGreater(cap["monthly_cap_bytes"], 0)
            self.assertTrue(cap["enabled"])
            self.assertAlmostEqual(cap["monthly_cap_gb"], 1200.0, places=0)
            # Cleanup
            Path("/tmp/test_bw_cap.json").unlink(missing_ok=True)

    def test_save_cap_negative(self):
        """Saving negative cap should clamp to 0."""
        with patch("services.bandwidth_tracker._CAP_FILE", "/tmp/test_bw_cap_neg.json"):
            self.tracker.save_cap(-100)
            self.assertEqual(self.tracker._monthly_cap_bytes, 0)
            Path("/tmp/test_bw_cap_neg.json").unlink(missing_ok=True)


class TestBandwidthTrackerWithClient(unittest.TestCase):
    """Tests for BandwidthTracker with a mocked OpenSearch client."""

    def setUp(self):
        """Create a tracker with a mock client."""
        self.mock_client = MagicMock()
        with patch("services.bandwidth_tracker._CAP_FILE", "/nonexistent/path"):
            self.tracker = BandwidthTracker(client=self.mock_client)

    def test_monthly_usage(self):
        """Should parse monthly usage from OpenSearch aggregation."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "orig_bytes": {"value": 500_000_000},
                "resp_bytes": {"value": 300_000_000},
            }
        }

        result = self.tracker.get_monthly_usage(2026, 3)
        self.assertEqual(result["total_bytes"], 800_000_000)
        self.assertEqual(result["orig_bytes"], 500_000_000)
        self.assertEqual(result["resp_bytes"], 300_000_000)
        self.mock_client.search.assert_called_once()

    def test_monthly_usage_opensearch_error_raises(self):
        """A failed query raises (#96): 0 bytes would read as an idle month."""
        from opensearchpy import OpenSearchException

        self.mock_client.search.side_effect = OpenSearchException("timeout")

        with self.assertRaises(OpenSearchException):
            self.tracker.get_monthly_usage(2026, 3)

    def test_daily_usage_opensearch_error_raises(self):
        """A failed query raises (#96): [] would read as no traffic on any day."""
        from opensearchpy import OpenSearchException

        self.mock_client.search.side_effect = OpenSearchException("timeout")

        with self.assertRaises(OpenSearchException):
            self.tracker.get_daily_usage("2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z")

    def test_daily_usage(self):
        """Should parse daily buckets from OpenSearch."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "daily": {
                    "buckets": [
                        {
                            "key_as_string": "2026-03-01",
                            "doc_count": 100,
                            "orig_bytes": {"value": 1000},
                            "resp_bytes": {"value": 2000},
                        },
                        {
                            "key_as_string": "2026-03-02",
                            "doc_count": 150,
                            "orig_bytes": {"value": 1500},
                            "resp_bytes": {"value": 2500},
                        },
                    ]
                }
            }
        }

        result = self.tracker.get_daily_usage(
            "2026-03-01T00:00:00Z", "2026-03-02T23:59:59Z"
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["date"], "2026-03-01")
        self.assertEqual(result[0]["total_bytes"], 3000)
        self.assertEqual(result[1]["total_bytes"], 4000)

    def test_per_device_usage(self):
        """Should parse per-device buckets from OpenSearch."""
        self.mock_client.search.return_value = {
            "aggregations": {
                # all LAN traffic in range (here: just these two devices)
                "orig_bytes": {"value": 15000},
                "resp_bytes": {"value": 35000},
                "by_device": {
                    "buckets": [
                        {
                            "key": "192.168.1.100",
                            "doc_count": 500,
                            "orig_bytes": {"value": 10000},
                            "resp_bytes": {"value": 20000},
                        },
                        {
                            "key": "192.168.1.101",
                            "doc_count": 300,
                            "orig_bytes": {"value": 5000},
                            "resp_bytes": {"value": 15000},
                        },
                    ]
                },
            }
        }

        result = self.tracker.get_per_device_usage(
            "2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z"
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["ip"], "192.168.1.100")
        self.assertEqual(result[0]["total_bytes"], 30000)
        self.assertEqual(result[0]["connection_count"], 500)
        # Percent should add up to ~100
        total_pct = sum(d["percent_of_total"] for d in result)
        self.assertAlmostEqual(total_pct, 100.0, places=0)

    def test_per_device_usage_lan_only_ordered_by_bytes(self):
        """NetTap itself (6.9 MB, 26K conns) outranked a 22.7 GB device; internet hosts listed."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "orig_bytes": {"value": 600},
                "resp_bytes": {"value": 400},
                "by_device": {
                    "buckets": [
                        {
                            "key": "192.168.1.188",
                            "doc_count": 3,
                            "orig_bytes": {"value": 100},
                            "resp_bytes": {"value": 150},
                        }
                    ]
                },
            }
        }
        lan = {"terms": {"source.ip": ["192.168.1.0/24"]}}
        result = self.tracker.get_per_device_usage(
            "2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z", lan_filter=lan
        )
        body = self.mock_client.search.call_args.kwargs["body"]
        self.assertIn(lan, body["query"]["bool"]["filter"])
        terms = body["aggs"]["by_device"]["terms"]
        self.assertEqual(terms["order"], {"total_bytes": "desc"})
        self.assertNotIn("bucket_sort", body["aggs"]["by_device"]["aggs"])
        # share of ALL LAN traffic (1000), not of the returned rows (250)
        self.assertEqual(result[0]["percent_of_total"], 25.0)

    def test_per_device_usage_defaults_to_rfc1918_sources(self):
        from services.excluded_ips import RFC1918_SOURCE_FILTER

        self.mock_client.search.return_value = {"aggregations": {}}
        self.tracker.get_per_device_usage(
            "2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z"
        )
        body = self.mock_client.search.call_args.kwargs["body"]
        self.assertIn(RFC1918_SOURCE_FILTER, body["query"]["bool"]["filter"])

    def test_per_device_usage_opensearch_error_raises(self):
        """A failed query raises (#96): [] would read as no device using bandwidth."""
        from opensearchpy import OpenSearchException

        self.mock_client.search.side_effect = OpenSearchException("timeout")

        with self.assertRaises(OpenSearchException):
            self.tracker.get_per_device_usage(
                "2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z"
            )

    def test_projected_monthly(self):
        """Projection should extrapolate based on current usage and days elapsed."""
        # Mock get_monthly_usage
        self.mock_client.search.return_value = {
            "aggregations": {
                "orig_bytes": {"value": 500_000_000_000},  # 500 GB
                "resp_bytes": {"value": 0},
            }
        }

        with patch("services.bandwidth_tracker.datetime") as mock_dt:
            # Pretend it's March 15, 2026 at noon
            mock_now = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
            mock_dt.now.return_value = mock_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            mock_dt.fromisoformat = datetime.fromisoformat

            result = self.tracker.get_projected_monthly(2026, 3)

        self.assertEqual(result["current_bytes"], 500_000_000_000)
        self.assertGreater(result["projected_bytes"], 500_000_000_000)
        self.assertEqual(result["days_in_month"], 31)

    def test_projected_monthly_with_cap(self):
        """Projection should include cap info when cap is set."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "orig_bytes": {"value": 900_000_000_000},  # 900 GB
                "resp_bytes": {"value": 0},
            }
        }
        self.tracker._monthly_cap_bytes = 1000 * 1024**3  # 1000 GB cap

        with patch("services.bandwidth_tracker.datetime") as mock_dt:
            mock_now = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
            mock_dt.now.return_value = mock_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            mock_dt.fromisoformat = datetime.fromisoformat

            result = self.tracker.get_projected_monthly(2026, 3)

        self.assertIn("cap_bytes", result)
        self.assertGreater(result["cap_bytes"], 0)
        self.assertGreater(result["usage_percent"], 0)
        self.assertTrue(result["exceeds_cap"])

    def test_projected_monthly_no_cap(self):
        """Projection without cap should report exceeds_cap as False."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "orig_bytes": {"value": 100_000},
                "resp_bytes": {"value": 0},
            }
        }
        self.tracker._monthly_cap_bytes = 0

        with patch("services.bandwidth_tracker.datetime") as mock_dt:
            mock_now = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
            mock_dt.now.return_value = mock_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            mock_dt.fromisoformat = datetime.fromisoformat

            result = self.tracker.get_projected_monthly(2026, 3)

        self.assertFalse(result["exceeds_cap"])

    def test_hourly_heatmap(self):
        """Should parse heatmap from OpenSearch aggregation."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "by_day_of_week": {
                    "buckets": [
                        {
                            "key": "1",  # Monday
                            "by_hour": {
                                "buckets": [
                                    {
                                        "key": "9",
                                        "orig_bytes": {"value": 1000},
                                        "resp_bytes": {"value": 2000},
                                    },
                                    {
                                        "key": "17",
                                        "orig_bytes": {"value": 3000},
                                        "resp_bytes": {"value": 4000},
                                    },
                                ]
                            },
                        },
                        {
                            "key": "5",  # Friday
                            "by_hour": {
                                "buckets": [
                                    {
                                        "key": "12",
                                        "orig_bytes": {"value": 500},
                                        "resp_bytes": {"value": 500},
                                    },
                                ]
                            },
                        },
                    ]
                }
            }
        }

        result = self.tracker.get_hourly_heatmap(
            "2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z"
        )
        self.assertEqual(len(result), 7)
        # Monday (index 0), hour 9 should have data
        self.assertEqual(result[0][9], 3000)
        # Monday, hour 17
        self.assertEqual(result[0][17], 7000)
        # Friday (index 4), hour 12
        self.assertEqual(result[4][12], 1000)
        # All other cells should be 0
        self.assertEqual(result[2][0], 0)  # Wednesday midnight

    def test_hourly_heatmap_opensearch_error_raises(self):
        """A failed query raises (#96): an all-zero matrix would read as a quiet week."""
        from opensearchpy import OpenSearchException

        self.mock_client.search.side_effect = OpenSearchException("timeout")

        with self.assertRaises(OpenSearchException):
            self.tracker.get_hourly_heatmap(
                "2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z"
            )


class TestBandwidthCapFile(unittest.TestCase):
    """Tests for cap file loading and saving."""

    def test_load_cap_from_file(self):
        """Should load cap from JSON file."""
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"monthly_cap_bytes": 1288490188800}, f)
            cap_file = f.name

        with patch("services.bandwidth_tracker._CAP_FILE", cap_file):
            tracker = BandwidthTracker(client=None)
            self.assertEqual(tracker._monthly_cap_bytes, 1288490188800)

        Path(cap_file).unlink(missing_ok=True)

    def test_load_cap_missing_file(self):
        """Should default to 0 when file is missing."""
        with patch("services.bandwidth_tracker._CAP_FILE", "/nonexistent/path"):
            tracker = BandwidthTracker(client=None)
            self.assertEqual(tracker._monthly_cap_bytes, 0)

    def test_load_cap_invalid_json(self):
        """Should default to 0 when file contains invalid JSON."""
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json")
            cap_file = f.name

        with patch("services.bandwidth_tracker._CAP_FILE", cap_file):
            tracker = BandwidthTracker(client=None)
            self.assertEqual(tracker._monthly_cap_bytes, 0)

        Path(cap_file).unlink(missing_ok=True)


class TestBandwidthApiQueryFailure(AioHTTPTestCase):
    """#96: every /api/bandwidth reader answers 502 when its query fails, never zeros."""

    async def get_application(self):
        from opensearchpy import OpenSearchException

        from api.bandwidth import register_bandwidth_routes

        self.mock_client = MagicMock()
        self.mock_client.search.side_effect = OpenSearchException("timeout")
        with patch("services.bandwidth_tracker._CAP_FILE", "/nonexistent/path"):
            tracker = BandwidthTracker(client=self.mock_client)
        app = web.Application()
        register_bandwidth_routes(app, tracker)
        return app

    async def test_every_reader_answers_502(self):
        for path in ("monthly", "daily", "devices", "heatmap", "cap"):
            resp = await self.client.request("GET", f"/api/bandwidth/{path}")
            self.assertEqual(resp.status, 502, path)
            self.assertIn("error", await resp.json())


class TestHeatmapScriptsAndTimeZone(AioHTTPTestCase):
    """The heatmap counts in the viewer's zone with java.time getters OpenSearch 3.x still has."""

    async def get_application(self):
        from api.bandwidth import register_bandwidth_routes

        self.mock_client = MagicMock()
        self.mock_client.search.return_value = {"aggregations": {"by_day_of_week": {"buckets": []}}}
        with patch("services.bandwidth_tracker._CAP_FILE", "/nonexistent/path"):
            tracker = BandwidthTracker(client=self.mock_client)
        app = web.Application()
        register_bandwidth_routes(app, tracker)
        return app

    def _scripts(self) -> list[dict]:
        day = self.mock_client.search.call_args.kwargs["body"]["aggs"]["by_day_of_week"]
        return [day["terms"]["script"], day["aggs"]["by_hour"]["terms"]["script"]]

    async def test_scripts_use_java_time_not_joda_getters(self):
        """'.dayOfWeek' / '.hourOfDay' failed the data shard on OpenSearch 3.x: an empty heatmap."""
        resp = await self.client.request("GET", "/api/bandwidth/heatmap")
        self.assertEqual(resp.status, 200)
        day, hour = self._scripts()
        for script in (day, hour):
            self.assertNotIn(".dayOfWeek", script["source"])
            self.assertNotIn(".hourOfDay", script["source"])
        self.assertTrue(day["source"].endswith(".getDayOfWeek().getValue()"))  # 1=Mon..7=Sun
        self.assertTrue(hour["source"].endswith(".getHour()"))

    async def test_viewer_zone_reaches_the_scripts_and_is_echoed(self):
        resp = await self.client.request("GET", "/api/bandwidth/heatmap?tz=America/Los_Angeles")
        self.assertEqual(resp.status, 200)
        self.assertEqual((await resp.json())["tz"], "America/Los_Angeles")
        for script in self._scripts():
            self.assertEqual(script["params"], {"tz": "America/Los_Angeles"})
            self.assertIn("withZoneSameInstant(ZoneId.of(params.tz))", script["source"])

    async def test_zone_defaults_to_utc(self):
        resp = await self.client.request("GET", "/api/bandwidth/heatmap")
        self.assertEqual((await resp.json())["tz"], "UTC")
        self.assertEqual(self._scripts()[0]["params"], {"tz": "UTC"})

    async def test_unknown_zone_is_400(self):
        for tz in ("Mars/Olympus_Mons", "../etc/passwd"):
            resp = await self.client.request("GET", f"/api/bandwidth/heatmap?tz={tz}")
            self.assertEqual(resp.status, 400, tz)
            self.assertIn("error", await resp.json())
        self.mock_client.search.assert_not_called()


if __name__ == "__main__":
    unittest.main()
