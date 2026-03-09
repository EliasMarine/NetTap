"""
Tests for daemon/services/changelog.py

Covers event logging, querying, filtering, and event type listing.
All tests use mocked OpenSearch — no external dependencies required.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.changelog import ChangelogService, CHANGELOG_EVENT_TYPES


class TestChangelogServiceLogEvent(unittest.TestCase):
    """Tests for ChangelogService.log_event()."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.mock_client.index.return_value = {"_id": "test-doc-id"}
        self.service = ChangelogService(client=self.mock_client)

    def test_log_event_basic(self):
        """log_event() indexes a document and returns it with _id."""
        doc = self.service.log_event(
            event_type="device_joined",
            title="New device detected",
            description="MAC AA:BB:CC:DD:EE:FF joined the network",
            metadata={"mac": "AA:BB:CC:DD:EE:FF", "ip": "192.168.1.100"},
        )
        self.assertEqual(doc["_id"], "test-doc-id")
        self.assertEqual(doc["event_type"], "device_joined")
        self.assertEqual(doc["title"], "New device detected")
        self.assertIn("@timestamp", doc)
        self.assertEqual(doc["metadata"]["mac"], "AA:BB:CC:DD:EE:FF")

    def test_log_event_calls_opensearch_index(self):
        """log_event() calls client.index with correct index pattern."""
        self.service.log_event("alert_triggered", "Test Alert")
        self.mock_client.index.assert_called_once()
        call_kwargs = self.mock_client.index.call_args
        self.assertTrue(call_kwargs[1]["index"].startswith("nettap-changelog-"))

    def test_log_event_default_metadata(self):
        """log_event() defaults metadata to empty dict."""
        doc = self.service.log_event("config_changed", "Config Updated")
        self.assertEqual(doc["metadata"], {})

    def test_log_event_opensearch_error(self):
        """log_event() handles OpenSearch errors gracefully."""
        from opensearchpy import OpenSearchException

        self.mock_client.index.side_effect = OpenSearchException("connection refused")
        doc = self.service.log_event("storage_pruned", "Pruned old indices")
        self.assertEqual(doc["_id"], "")
        self.assertEqual(doc["event_type"], "storage_pruned")


class TestChangelogServiceGetEvents(unittest.TestCase):
    """Tests for ChangelogService.get_events()."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.service = ChangelogService(client=self.mock_client)

    def test_get_events_returns_parsed_hits(self):
        """get_events() parses OpenSearch hits into event dicts."""
        self.mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_id": "evt-1",
                        "_source": {
                            "@timestamp": "2026-03-08T10:00:00Z",
                            "event_type": "device_joined",
                            "title": "New device",
                            "description": "MAC joined",
                            "metadata": {},
                        },
                    },
                    {
                        "_id": "evt-2",
                        "_source": {
                            "@timestamp": "2026-03-08T09:00:00Z",
                            "event_type": "alert_triggered",
                            "title": "Malware alert",
                            "description": "ET MALWARE detected",
                            "metadata": {"sid": 12345},
                        },
                    },
                ]
            }
        }

        events = self.service.get_events()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["_id"], "evt-1")
        self.assertEqual(events[0]["event_type"], "device_joined")
        self.assertEqual(events[1]["metadata"]["sid"], 12345)

    def test_get_events_with_type_filter(self):
        """get_events() passes event_types filter to OpenSearch."""
        self.mock_client.search.return_value = {"hits": {"hits": []}}

        self.service.get_events(event_types=["alert_triggered", "anomaly"])
        call_body = self.mock_client.search.call_args[1]["body"]
        filters = call_body["query"]["bool"]["filter"]

        terms_filter = [f for f in filters if "terms" in f]
        self.assertEqual(len(terms_filter), 1)
        self.assertEqual(
            terms_filter[0]["terms"]["event_type"],
            ["alert_triggered", "anomaly"],
        )

    def test_get_events_with_time_range(self):
        """get_events() passes time range filter to OpenSearch."""
        self.mock_client.search.return_value = {"hits": {"hits": []}}

        self.service.get_events(
            from_ts="2026-03-01T00:00:00Z",
            to_ts="2026-03-08T00:00:00Z",
        )
        call_body = self.mock_client.search.call_args[1]["body"]
        filters = call_body["query"]["bool"]["filter"]

        range_filter = [f for f in filters if "range" in f]
        self.assertEqual(len(range_filter), 1)
        self.assertEqual(
            range_filter[0]["range"]["@timestamp"]["gte"], "2026-03-01T00:00:00Z"
        )

    def test_get_events_limits_size(self):
        """get_events() caps limit at 1000."""
        self.mock_client.search.return_value = {"hits": {"hits": []}}
        self.service.get_events(limit=5000)
        call_body = self.mock_client.search.call_args[1]["body"]
        self.assertEqual(call_body["size"], 1000)

    def test_get_events_opensearch_error(self):
        """get_events() returns empty list on OpenSearch error."""
        from opensearchpy import OpenSearchException

        self.mock_client.search.side_effect = OpenSearchException("timeout")
        events = self.service.get_events()
        self.assertEqual(events, [])

    def test_get_events_default_time_range(self):
        """get_events() uses 7-day default when no range provided."""
        self.mock_client.search.return_value = {"hits": {"hits": []}}
        self.service.get_events()
        self.mock_client.search.assert_called_once()


class TestChangelogServiceGetEventTypes(unittest.TestCase):
    """Tests for ChangelogService.get_event_types()."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.service = ChangelogService(client=self.mock_client)

    def test_get_event_types_from_aggregation(self):
        """get_event_types() returns types from OpenSearch aggregation."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "event_types": {
                    "buckets": [
                        {"key": "device_joined", "doc_count": 10},
                        {"key": "alert_triggered", "doc_count": 5},
                    ]
                }
            }
        }

        types = self.service.get_event_types()
        self.assertEqual(types, ["device_joined", "alert_triggered"])

    def test_get_event_types_fallback_to_static(self):
        """get_event_types() falls back to static list on empty aggregation."""
        self.mock_client.search.return_value = {
            "aggregations": {"event_types": {"buckets": []}}
        }

        types = self.service.get_event_types()
        self.assertEqual(types, sorted(CHANGELOG_EVENT_TYPES))

    def test_get_event_types_opensearch_error(self):
        """get_event_types() returns static list on OpenSearch error."""
        from opensearchpy import OpenSearchException

        self.mock_client.search.side_effect = OpenSearchException("timeout")
        types = self.service.get_event_types()
        self.assertEqual(types, sorted(CHANGELOG_EVENT_TYPES))


if __name__ == "__main__":
    unittest.main()
