"""
Tests for the ASN-based get_category_stats() implementation.

Validates that OpenSearch ASN aggregation responses are correctly
mapped to traffic categories, aggregated, and sorted.
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.traffic_classifier import get_category_stats, CATEGORIES


def _mock_os_response(asn_buckets):
    return {
        "aggregations": {
            "asn_breakdown": {
                "buckets": [
                    {"key": name, "doc_count": count, "total_bytes": {"value": bytes_val}}
                    for name, count, bytes_val in asn_buckets
                ]
            }
        }
    }


class TestCategoryStats(unittest.TestCase):
    """Tests for ASN-based get_category_stats()."""

    def test_empty_response_returns_empty_list(self):
        client = MagicMock()
        client.search = MagicMock(return_value=_mock_os_response([]))

        result = asyncio.run(
            get_category_stats(client, "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
        )
        self.assertEqual(result, [])

    def test_single_asn_maps_to_category(self):
        client = MagicMock()
        client.search = MagicMock(return_value=_mock_os_response([
            ("AS2906 Netflix Inc", 1000, 5_000_000_000),
        ]))

        result = asyncio.run(
            get_category_stats(client, "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
        )
        streaming = next((c for c in result if c["name"] == "streaming"), None)
        self.assertIsNotNone(streaming)
        self.assertEqual(streaming["total_bytes"], 5_000_000_000)
        self.assertEqual(streaming["connection_count"], 1000)

    def test_multiple_asns_same_category_aggregate(self):
        client = MagicMock()
        client.search = MagicMock(return_value=_mock_os_response([
            ("AS2906 Netflix Inc", 500, 3_000_000_000),
            ("AS15169 Google LLC", 300, 2_000_000_000),
        ]))

        result = asyncio.run(
            get_category_stats(client, "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
        )
        streaming = next((c for c in result if c["name"] == "streaming"), None)
        self.assertIsNotNone(streaming)
        self.assertEqual(streaming["total_bytes"], 5_000_000_000)
        self.assertEqual(streaming["connection_count"], 800)

    def test_unknown_asn_goes_to_other(self):
        client = MagicMock()
        client.search = MagicMock(return_value=_mock_os_response([
            ("AS99999 Unknown ISP", 100, 500_000),
        ]))

        result = asyncio.run(
            get_category_stats(client, "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
        )
        other = next((c for c in result if c["name"] == "other"), None)
        self.assertIsNotNone(other)
        self.assertEqual(other["total_bytes"], 500_000)

    def test_results_sorted_by_bytes_descending(self):
        client = MagicMock()
        client.search = MagicMock(return_value=_mock_os_response([
            ("AS32934 Meta Platforms", 200, 1_000_000),
            ("AS2906 Netflix Inc", 500, 5_000_000),
        ]))

        result = asyncio.run(
            get_category_stats(client, "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
        )
        self.assertGreaterEqual(result[0]["total_bytes"], result[-1]["total_bytes"])

    def test_result_includes_top_services(self):
        client = MagicMock()
        client.search = MagicMock(return_value=_mock_os_response([
            ("AS2906 Netflix Inc", 500, 3_000_000_000),
            ("AS15169 Google LLC", 300, 2_000_000_000),
        ]))

        result = asyncio.run(
            get_category_stats(client, "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
        )
        streaming = next(c for c in result if c["name"] == "streaming")
        self.assertGreaterEqual(len(streaming["top_services"]), 1)
        self.assertEqual(streaming["top_services"][0]["name"], "Netflix Inc")

    def test_opensearch_error_returns_empty(self):
        client = MagicMock()
        client.search = MagicMock(side_effect=Exception("Connection refused"))

        result = asyncio.run(
            get_category_stats(client, "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
        )
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
