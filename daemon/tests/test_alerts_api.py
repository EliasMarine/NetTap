"""
Tests for daemon/api/alerts.py

All tests use mocks -- no OpenSearch connection required.
Tests cover query building, response formatting, error handling, and edge cases.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import sys

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.alerts import (
    register_alert_routes,
    _time_range_filter,
    _load_acks,
    _save_acks,
)
from storage.manager import StorageManager, RetentionConfig


def _make_mock_storage():
    """Create a mock StorageManager with a mock OpenSearch client."""
    config = RetentionConfig()
    with patch.object(StorageManager, "_create_client") as mock_create:
        mock_client = MagicMock()
        mock_create.return_value = mock_client
        storage = StorageManager(config, "http://localhost:9200")
    return storage, mock_client


class TestAlertTimeRangeFilter(unittest.TestCase):
    """Tests for alert-specific _time_range_filter helper."""

    def test_builds_correct_timestamp_range(self):
        result = _time_range_filter("2026-02-25T00:00:00Z", "2026-02-26T00:00:00Z")
        self.assertEqual(result["range"]["timestamp"]["gte"], "2026-02-25T00:00:00Z")
        self.assertEqual(result["range"]["timestamp"]["lte"], "2026-02-26T00:00:00Z")


class TestAckFileHelpers(unittest.TestCase):
    """Tests for _load_acks and _save_acks."""

    def test_load_nonexistent_file(self):
        """Loading a nonexistent ack file returns empty dict."""
        acks = _load_acks("/tmp/nettap-test-nonexistent.json")
        self.assertEqual(acks, {})

    def test_save_and_load_roundtrip(self):
        """Save and load should roundtrip correctly."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            tmp_path = f.name

        try:
            acks = {
                "alert-1": {
                    "acknowledged_at": "2026-02-26T12:00:00Z",
                    "acknowledged_by": "admin",
                }
            }
            _save_acks(acks, tmp_path)
            loaded = _load_acks(tmp_path)
            self.assertEqual(loaded, acks)
        finally:
            os.unlink(tmp_path)

    def test_load_corrupt_file(self):
        """Loading a corrupt JSON file returns empty dict."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json{{{")
            tmp_path = f.name

        try:
            acks = _load_acks(tmp_path)
            self.assertEqual(acks, {})
        finally:
            os.unlink(tmp_path)


class TestAlertsListHandler(AioHTTPTestCase):
    """Tests for GET /api/alerts."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        self.tmp_ack_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        self.tmp_ack_file.write("{}")
        self.tmp_ack_file.close()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        os.unlink(self.tmp_ack_file.name)

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        app["alert_ack_file"] = self.tmp_ack_file.name
        register_alert_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_alerts_list_success(self):
        """Successful alert list returns paginated data."""
        self.mock_client.search.return_value = {
            "hits": {
                "total": {"value": 42},
                "hits": [
                    {
                        "_id": "alert-1",
                        "_index": "suricata-alert-2026.02.25",
                        "_source": {
                            "timestamp": "2026-02-25T12:00:00Z",
                            "alert": {
                                "signature": "ET TROJAN Test",
                                "signature_id": 2001,
                                "severity": 1,
                                "category": "Trojan",
                            },
                            "src_ip": "192.168.1.100",
                            "dest_ip": "10.0.0.1",
                            "proto": "tcp",
                        },
                    }
                ],
            }
        }

        resp = await self.client.request("GET", "/api/alerts?page=1&size=50")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["total"], 42)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["size"], 50)
        self.assertEqual(len(data["alerts"]), 1)
        self.assertEqual(data["alerts"][0]["_id"], "alert-1")
        self.assertEqual(data["alerts"][0]["alert"]["signature"], "ET TROJAN Test")
        self.assertFalse(data["alerts"][0]["acknowledged"])

    @unittest_run_loop
    async def test_alerts_list_with_severity_filter(self):
        """Severity filter is included in query."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }

        resp = await self.client.request("GET", "/api/alerts?severity=1")
        self.assertEqual(resp.status, 200)

        call_args = self.mock_client.search.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        filters = body["query"]["bool"]["filter"]
        has_severity = any(
            "term" in f and "alert.severity" in f.get("term", {}) for f in filters
        )
        self.assertTrue(has_severity)

    @unittest_run_loop
    async def test_alerts_list_invalid_severity_ignored(self):
        """Invalid severity param is ignored (no filter)."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }

        resp = await self.client.request("GET", "/api/alerts?severity=abc")
        self.assertEqual(resp.status, 200)

        call_args = self.mock_client.search.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        filters = body["query"]["bool"]["filter"]
        # Should only have the time range filter
        self.assertEqual(len(filters), 1)

    @unittest_run_loop
    async def test_alerts_list_opensearch_error(self):
        """OpenSearch error returns 502."""
        from opensearchpy import ConnectionError as OSConnectionError

        self.mock_client.search.side_effect = OSConnectionError(
            "N/A", "Connection refused", Exception("refused")
        )

        resp = await self.client.request("GET", "/api/alerts")
        self.assertEqual(resp.status, 502)
        data = await resp.json()
        self.assertIn("error", data)

    @unittest_run_loop
    async def test_alerts_list_with_acknowledged(self):
        """Acknowledged alerts are annotated correctly."""
        # Write an ack to the file
        acks = {
            "alert-1": {
                "acknowledged_at": "2026-02-26T12:00:00Z",
                "acknowledged_by": "admin",
            }
        }
        with open(self.tmp_ack_file.name, "w") as f:
            json.dump(acks, f)

        self.mock_client.search.return_value = {
            "hits": {
                "total": {"value": 1},
                "hits": [
                    {
                        "_id": "alert-1",
                        "_index": "suricata-alert-2026.02.25",
                        "_source": {"timestamp": "2026-02-25T12:00:00Z"},
                    }
                ],
            }
        }

        resp = await self.client.request("GET", "/api/alerts")
        data = await resp.json()
        self.assertTrue(data["alerts"][0]["acknowledged"])
        self.assertEqual(data["alerts"][0]["acknowledged_at"], "2026-02-26T12:00:00Z")


class TestAlertCountHandler(AioHTTPTestCase):
    """Tests for GET /api/alerts/count."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_alert_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_count_success(self):
        """Returns severity breakdown."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 100}},
            "aggregations": {
                "by_severity": {
                    "buckets": [
                        {"key": 1, "doc_count": 10},
                        {"key": 2, "doc_count": 30},
                        {"key": 3, "doc_count": 60},
                    ]
                }
            },
        }

        resp = await self.client.request("GET", "/api/alerts/count")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["counts"]["total"], 100)
        self.assertEqual(data["counts"]["high"], 10)
        self.assertEqual(data["counts"]["medium"], 30)
        self.assertEqual(data["counts"]["low"], 60)

    @unittest_run_loop
    async def test_count_empty(self):
        """Zero alerts returns all-zero counts."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}},
            "aggregations": {"by_severity": {"buckets": []}},
        }

        resp = await self.client.request("GET", "/api/alerts/count")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["counts"]["total"], 0)
        self.assertEqual(data["counts"]["high"], 0)
        self.assertEqual(data["counts"]["medium"], 0)
        self.assertEqual(data["counts"]["low"], 0)

    @unittest_run_loop
    async def test_count_opensearch_error(self):
        """OpenSearch error returns 502."""
        from opensearchpy import ConnectionError as OSConnectionError

        self.mock_client.search.side_effect = OSConnectionError(
            "N/A", "Connection refused", Exception("refused")
        )

        resp = await self.client.request("GET", "/api/alerts/count")
        self.assertEqual(resp.status, 502)


class TestAlertDetailHandler(AioHTTPTestCase):
    """Tests for GET /api/alerts/{id}."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_alert_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_detail_success(self):
        """Returns single alert detail."""
        self.mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_id": "alert-123",
                        "_index": "suricata-alert-2026.02.25",
                        "_source": {
                            "timestamp": "2026-02-25T12:00:00Z",
                            "alert": {
                                "signature": "ET SCAN Test",
                                "severity": 2,
                            },
                            "src_ip": "10.0.0.1",
                            "dest_ip": "192.168.1.1",
                        },
                    }
                ]
            }
        }

        resp = await self.client.request("GET", "/api/alerts/alert-123")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["alert"]["_id"], "alert-123")
        self.assertEqual(data["alert"]["alert"]["severity"], 2)

    @unittest_run_loop
    async def test_detail_not_found(self):
        """Non-existent alert returns 404."""
        self.mock_client.search.return_value = {"hits": {"hits": []}}

        resp = await self.client.request("GET", "/api/alerts/nonexistent")
        self.assertEqual(resp.status, 404)
        data = await resp.json()
        self.assertIn("error", data)

    @unittest_run_loop
    async def test_detail_opensearch_error(self):
        """OpenSearch error returns 502."""
        from opensearchpy import ConnectionError as OSConnectionError

        self.mock_client.search.side_effect = OSConnectionError(
            "N/A", "Connection refused", Exception("refused")
        )

        resp = await self.client.request("GET", "/api/alerts/alert-123")
        self.assertEqual(resp.status, 502)


class TestAlertAcknowledgeHandler(AioHTTPTestCase):
    """Tests for POST /api/alerts/{id}/acknowledge."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        self.tmp_ack_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        self.tmp_ack_file.write("{}")
        self.tmp_ack_file.close()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        os.unlink(self.tmp_ack_file.name)

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        app["alert_ack_file"] = self.tmp_ack_file.name
        register_alert_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_acknowledge_success(self):
        """Acknowledging an alert stores it in the ack file."""
        resp = await self.client.request(
            "POST",
            "/api/alerts/alert-456/acknowledge",
            json={"acknowledged_by": "testuser"},
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["result"], "acknowledged")
        self.assertEqual(data["alert_id"], "alert-456")
        self.assertEqual(data["acknowledged_by"], "testuser")
        self.assertIn("acknowledged_at", data)

        # Verify the ack was persisted
        with open(self.tmp_ack_file.name) as f:
            acks = json.load(f)
        self.assertIn("alert-456", acks)
        self.assertEqual(acks["alert-456"]["acknowledged_by"], "testuser")

    @unittest_run_loop
    async def test_acknowledge_no_body(self):
        """Acknowledging without body uses default 'admin'."""
        resp = await self.client.request(
            "POST",
            "/api/alerts/alert-789/acknowledge",
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["acknowledged_by"], "admin")

    @unittest_run_loop
    async def test_acknowledge_idempotent(self):
        """Acknowledging the same alert twice overwrites the first."""
        await self.client.request(
            "POST",
            "/api/alerts/alert-100/acknowledge",
            json={"acknowledged_by": "user1"},
        )
        resp = await self.client.request(
            "POST",
            "/api/alerts/alert-100/acknowledge",
            json={"acknowledged_by": "user2"},
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["acknowledged_by"], "user2")

        with open(self.tmp_ack_file.name) as f:
            acks = json.load(f)
        self.assertEqual(acks["alert-100"]["acknowledged_by"], "user2")


if __name__ == "__main__":
    unittest.main()
