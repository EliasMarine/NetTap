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
        result = self.tracker.get_daily_usage("2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z")
        self.assertEqual(result, [])

    def test_per_device_usage_no_client(self):
        """Should return empty list when no client is configured."""
        result = self.tracker.get_per_device_usage("2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z")
        self.assertEqual(result, [])

    def test_heatmap_no_client(self):
        """Should return zero-filled 7x24 matrix when no client is configured."""
        result = self.tracker.get_hourly_heatmap("2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z")
        self.assertEqual(len(result), 7)
        self.assertTrue(all(len(row) == 24 for row in result))
        self.assertTrue(all(v == 0 for row in result for v in row))

    def test_get_cap_default(self):
        """Default cap should be 0 (disabled)."""
        cap = self.tracker.get_cap()
        self.assertEqual(cap["monthly_cap_bytes"], 0)
        self.assertFalse(cap["enabled"])

    def test_save_and_get_cap(self, ):
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

    def test_monthly_usage_opensearch_error(self):
        """Should return zeros on OpenSearch error."""
        from opensearchpy import OpenSearchException
        self.mock_client.search.side_effect = OpenSearchException("timeout")

        result = self.tracker.get_monthly_usage(2026, 3)
        self.assertEqual(result["total_bytes"], 0)

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

        result = self.tracker.get_daily_usage("2026-03-01T00:00:00Z", "2026-03-02T23:59:59Z")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["date"], "2026-03-01")
        self.assertEqual(result[0]["total_bytes"], 3000)
        self.assertEqual(result[1]["total_bytes"], 4000)

    def test_per_device_usage(self):
        """Should parse per-device buckets from OpenSearch."""
        self.mock_client.search.return_value = {
            "aggregations": {
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
                }
            }
        }

        result = self.tracker.get_per_device_usage("2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["ip"], "192.168.1.100")
        self.assertEqual(result[0]["total_bytes"], 30000)
        self.assertEqual(result[0]["connection_count"], 500)
        # Percent should add up to ~100
        total_pct = sum(d["percent_of_total"] for d in result)
        self.assertAlmostEqual(total_pct, 100.0, places=0)

    def test_per_device_usage_opensearch_error(self):
        """Should return empty list on OpenSearch error."""
        from opensearchpy import OpenSearchException
        self.mock_client.search.side_effect = OpenSearchException("timeout")

        result = self.tracker.get_per_device_usage("2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z")
        self.assertEqual(result, [])

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

        result = self.tracker.get_hourly_heatmap("2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z")
        self.assertEqual(len(result), 7)
        # Monday (index 0), hour 9 should have data
        self.assertEqual(result[0][9], 3000)
        # Monday, hour 17
        self.assertEqual(result[0][17], 7000)
        # Friday (index 4), hour 12
        self.assertEqual(result[4][12], 1000)
        # All other cells should be 0
        self.assertEqual(result[2][0], 0)  # Wednesday midnight

    def test_hourly_heatmap_opensearch_error(self):
        """Should return zero-filled matrix on OpenSearch error."""
        from opensearchpy import OpenSearchException
        self.mock_client.search.side_effect = OpenSearchException("timeout")

        result = self.tracker.get_hourly_heatmap("2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z")
        self.assertEqual(len(result), 7)
        self.assertTrue(all(v == 0 for row in result for v in row))


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


if __name__ == "__main__":
    unittest.main()
