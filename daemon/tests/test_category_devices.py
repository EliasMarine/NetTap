"""
Tests for get_category_devices() — per-device bandwidth breakdown
for a given traffic category.

Validates device aggregation, sorting, field presence, and handling
of unknown categories.
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.traffic_classifier import get_category_devices


def _mock_device_response(device_buckets):
    return {
        "aggregations": {
            "devices": {
                "buckets": [
                    {"key": ip, "doc_count": conns,
                     "total_bytes": {"value": total},
                     "download_bytes": {"value": dl},
                     "upload_bytes": {"value": ul}}
                    for ip, conns, total, dl, ul in device_buckets
                ]
            }
        }
    }


class TestCategoryDevices(unittest.TestCase):
    """Tests for get_category_devices()."""

    def test_returns_devices_sorted_by_bytes(self):
        client = MagicMock()
        client.search = MagicMock(return_value=_mock_device_response([
            ("192.168.1.10", 100, 5_000_000, 4_500_000, 500_000),
            ("192.168.1.20", 200, 8_000_000, 7_000_000, 1_000_000),
        ]))

        result = asyncio.run(
            get_category_devices(client, "streaming", "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["ip"], "192.168.1.20")
        self.assertEqual(result[0]["total_bytes"], 8_000_000)

    def test_unknown_category_returns_empty(self):
        client = MagicMock()
        client.search = MagicMock(return_value=_mock_device_response([]))

        result = asyncio.run(
            get_category_devices(client, "nonexistent", "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
        )
        self.assertEqual(result, [])

    def test_device_fields_present(self):
        client = MagicMock()
        client.search = MagicMock(return_value=_mock_device_response([
            ("192.168.1.10", 50, 1_000_000, 800_000, 200_000),
        ]))

        result = asyncio.run(
            get_category_devices(client, "streaming", "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
        )
        device = result[0]
        self.assertIn("ip", device)
        self.assertIn("total_bytes", device)
        self.assertIn("download_bytes", device)
        self.assertIn("upload_bytes", device)
        self.assertIn("connections", device)

    def test_opensearch_error_returns_empty(self):
        client = MagicMock()
        client.search = MagicMock(side_effect=Exception("Connection refused"))

        result = asyncio.run(
            get_category_devices(client, "streaming", "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
        )
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
