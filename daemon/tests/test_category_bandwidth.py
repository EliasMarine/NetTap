"""
Tests for get_category_bandwidth() -- time-series bandwidth data
filtered to a specific traffic category's ASN set.

Validates time-series output shape, field presence, handling of
unknown categories, and OpenSearch error resilience.
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.traffic_classifier import get_category_bandwidth


def _mock_bandwidth_response(time_buckets):
    """Build a mock OpenSearch response for a date_histogram aggregation.

    Each entry in *time_buckets* is a tuple of
    (key_as_string, doc_count, download_bytes, upload_bytes).
    """
    return {
        "aggregations": {
            "bandwidth_over_time": {
                "buckets": [
                    {
                        "key_as_string": ts,
                        "key": idx,
                        "doc_count": conns,
                        "download_bytes": {"value": dl},
                        "upload_bytes": {"value": ul},
                    }
                    for idx, (ts, conns, dl, ul) in enumerate(time_buckets)
                ]
            }
        }
    }


class TestCategoryBandwidth(unittest.TestCase):
    """Tests for get_category_bandwidth()."""

    def test_returns_time_series_data(self):
        client = MagicMock()
        client.search = MagicMock(return_value=_mock_bandwidth_response([
            ("2026-03-01T00:00:00Z", 10, 1_000_000, 200_000),
            ("2026-03-01T00:15:00Z", 20, 2_000_000, 400_000),
            ("2026-03-01T00:30:00Z", 15, 1_500_000, 300_000),
        ]))

        result = asyncio.run(
            get_category_bandwidth(
                client, "streaming",
                "2026-03-01T00:00:00Z", "2026-03-01T01:00:00Z",
            )
        )
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["download_bytes"], 1_000_000)
        self.assertEqual(result[0]["upload_bytes"], 200_000)
        self.assertEqual(result[0]["total_bytes"], 1_200_000)
        self.assertEqual(result[1]["connections"], 20)

    def test_unknown_category_returns_empty(self):
        client = MagicMock()
        # Should never be called because the category has no ASN mappings
        client.search = MagicMock(return_value=_mock_bandwidth_response([]))

        result = asyncio.run(
            get_category_bandwidth(
                client, "nonexistent",
                "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z",
            )
        )
        self.assertEqual(result, [])
        client.search.assert_not_called()

    def test_opensearch_error_returns_empty(self):
        client = MagicMock()
        client.search = MagicMock(side_effect=Exception("Connection refused"))

        result = asyncio.run(
            get_category_bandwidth(
                client, "streaming",
                "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z",
            )
        )
        self.assertEqual(result, [])

    def test_series_includes_all_fields(self):
        client = MagicMock()
        client.search = MagicMock(return_value=_mock_bandwidth_response([
            ("2026-03-01T00:00:00Z", 5, 500_000, 100_000),
        ]))

        result = asyncio.run(
            get_category_bandwidth(
                client, "streaming",
                "2026-03-01T00:00:00Z", "2026-03-01T01:00:00Z",
            )
        )
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertIn("timestamp", item)
        self.assertIn("download_bytes", item)
        self.assertIn("upload_bytes", item)
        self.assertIn("total_bytes", item)
        self.assertIn("connections", item)
        self.assertEqual(item["timestamp"], "2026-03-01T00:00:00Z")
        self.assertEqual(item["total_bytes"], 600_000)
        self.assertEqual(item["connections"], 5)


if __name__ == "__main__":
    unittest.main()
