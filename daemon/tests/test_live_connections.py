"""
Tests for daemon/services/live_connections.py

All tests use mocks -- no OpenSearch connection required.
Tests cover tracker logic, filtering, rate calculation, and OpenSearch integration.
"""

import unittest
from unittest.mock import MagicMock

from services.live_connections import LiveConnectionTracker, RATE_WINDOW_SECONDS


def _make_connection(
    source_ip="192.168.1.100",
    dest_ip="93.184.216.34",
    protocol="tcp",
    dest_port=443,
    source_port=54321,
    country="US",
    bytes_val=1024,
    duration=1.5,
    timestamp="2026-03-08T10:00:00Z",
):
    """Create a formatted connection dict for testing."""
    return {
        "timestamp": timestamp,
        "source_ip": source_ip,
        "source_port": source_port,
        "dest_ip": dest_ip,
        "dest_port": dest_port,
        "protocol": protocol,
        "service": "https",
        "bytes": bytes_val,
        "duration": duration,
        "country": country,
        "country_name": "United States",
        "device_name": "",
    }


def _make_opensearch_hit(
    source_ip="192.168.1.100",
    dest_ip="93.184.216.34",
    protocol="tcp",
    dest_port=443,
    source_port=54321,
    country="US",
    timestamp="2026-03-08T10:00:00Z",
):
    """Create a fake OpenSearch hit _source."""
    return {
        "@timestamp": timestamp,
        "source": {"ip": source_ip, "port": source_port, "bytes": 512},
        "destination": {
            "ip": dest_ip,
            "port": dest_port,
            "bytes": 512,
            "geo": {"country_iso_code": country, "country_name": "United States"},
        },
        "client": {"bytes": 512},
        "server": {"bytes": 512},
        "network": {"transport": protocol, "protocol": "https"},
        "event": {
            "provider": "zeek",
            "dataset": "conn",
            "start": "2026-03-08T10:00:00Z",
            "end": "2026-03-08T10:00:01.500Z",
        },
    }


class TestLiveConnectionTracker(unittest.TestCase):
    """Tests for LiveConnectionTracker."""

    def test_init_empty(self):
        """Tracker starts with no connections."""
        tracker = LiveConnectionTracker()
        conns = tracker.get_active_connections()
        self.assertEqual(conns, [])

    def test_get_connection_rate_empty(self):
        """Rate should be zero with no data."""
        tracker = LiveConnectionTracker()
        rate = tracker.get_connection_rate()
        self.assertEqual(rate["connections_per_second"], 0)
        self.assertEqual(rate["total_in_window"], 0)
        self.assertEqual(rate["window_seconds"], RATE_WINDOW_SECONDS)

    def test_record_rate(self):
        """Recording connections should update rate."""
        tracker = LiveConnectionTracker()
        tracker._record_rate(30)
        rate = tracker.get_connection_rate()
        self.assertEqual(rate["total_in_window"], 30)
        self.assertGreater(rate["connections_per_second"], 0)

    def test_get_active_connections_limit(self):
        """Limit parameter should cap results."""
        tracker = LiveConnectionTracker()
        for i in range(20):
            tracker._connections.append(_make_connection(source_ip=f"192.168.1.{i}"))
        conns = tracker.get_active_connections(limit=5)
        self.assertEqual(len(conns), 5)

    def test_filter_by_device(self):
        """Filtering by device IP should only return matching connections."""
        tracker = LiveConnectionTracker()
        tracker._connections.append(_make_connection(source_ip="192.168.1.100"))
        tracker._connections.append(_make_connection(source_ip="192.168.1.101"))
        tracker._connections.append(_make_connection(source_ip="192.168.1.102", dest_ip="192.168.1.100"))

        conns = tracker.get_active_connections(device="192.168.1.100")
        self.assertEqual(len(conns), 2)  # matches source and dest

    def test_filter_by_protocol(self):
        """Filtering by protocol should only return matching connections."""
        tracker = LiveConnectionTracker()
        tracker._connections.append(_make_connection(protocol="tcp"))
        tracker._connections.append(_make_connection(protocol="udp"))
        tracker._connections.append(_make_connection(protocol="tcp"))

        conns = tracker.get_active_connections(proto="udp")
        self.assertEqual(len(conns), 1)
        self.assertEqual(conns[0]["protocol"], "udp")

    def test_filter_by_country(self):
        """Filtering by country should only return matching connections."""
        tracker = LiveConnectionTracker()
        tracker._connections.append(_make_connection(country="US"))
        tracker._connections.append(_make_connection(country="DE"))

        conns = tracker.get_active_connections(country="DE")
        self.assertEqual(len(conns), 1)
        self.assertEqual(conns[0]["country"], "DE")

    def test_filter_by_port_range(self):
        """Filtering by port range should only return matching connections."""
        tracker = LiveConnectionTracker()
        tracker._connections.append(_make_connection(dest_port=80))
        tracker._connections.append(_make_connection(dest_port=443))
        tracker._connections.append(_make_connection(dest_port=8080))

        conns = tracker.get_active_connections(port_min=400, port_max=500)
        self.assertEqual(len(conns), 1)
        self.assertEqual(conns[0]["dest_port"], 443)

    def test_max_connections_rotation(self):
        """Connections should rotate when exceeding MAX_CONNECTIONS."""
        tracker = LiveConnectionTracker()
        tracker._connections = tracker._connections.__class__(maxlen=5)  # Use small maxlen for test
        for i in range(10):
            tracker._connections.append(_make_connection(source_ip=f"10.0.0.{i}"))
        self.assertEqual(len(tracker._connections), 5)
        # Oldest should be gone
        ips = [c["source_ip"] for c in tracker._connections]
        self.assertNotIn("10.0.0.0", ips)
        self.assertIn("10.0.0.9", ips)

    def test_format_connection(self):
        """Format connection should extract all fields correctly."""
        tracker = LiveConnectionTracker()
        source = _make_opensearch_hit()
        conn = tracker._format_connection(source)

        self.assertEqual(conn["source_ip"], "192.168.1.100")
        self.assertEqual(conn["dest_ip"], "93.184.216.34")
        self.assertEqual(conn["protocol"], "tcp")
        self.assertEqual(conn["dest_port"], 443)
        self.assertEqual(conn["country"], "US")
        self.assertGreater(conn["bytes"], 0)
        self.assertGreater(conn["duration"], 0)

    def test_format_connection_missing_fields(self):
        """Format connection should handle missing fields gracefully."""
        tracker = LiveConnectionTracker()
        conn = tracker._format_connection({})
        self.assertEqual(conn["source_ip"], "")
        self.assertEqual(conn["dest_ip"], "")
        self.assertEqual(conn["protocol"], "")
        self.assertEqual(conn["bytes"], 0)
        self.assertEqual(conn["duration"], 0)

    def test_fetch_from_opensearch_success(self):
        """Fetch should parse OpenSearch response correctly."""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {"_source": _make_opensearch_hit(source_ip="10.0.0.1")},
                    {"_source": _make_opensearch_hit(source_ip="10.0.0.2")},
                ]
            }
        }
        tracker = LiveConnectionTracker(client=mock_client)
        conns = tracker.fetch_from_opensearch(limit=10)

        self.assertEqual(len(conns), 2)
        self.assertEqual(conns[0]["source_ip"], "10.0.0.1")
        self.assertEqual(conns[1]["source_ip"], "10.0.0.2")
        mock_client.search.assert_called_once()

    def test_fetch_from_opensearch_with_device_filter(self):
        """Fetch with device filter should include device in query."""
        mock_client = MagicMock()
        mock_client.search.return_value = {"hits": {"hits": []}}
        tracker = LiveConnectionTracker(client=mock_client)
        tracker.fetch_from_opensearch(device="192.168.1.100")

        call_args = mock_client.search.call_args
        body = call_args[1]["body"] if "body" in call_args[1] else call_args[0][1]
        # Should have device filter in the bool query
        filters = body["query"]["bool"]["filter"]
        has_device_filter = any(
            "bool" in f and "should" in f["bool"]
            for f in filters
        )
        self.assertTrue(has_device_filter)

    def test_fetch_from_opensearch_error(self):
        """Fetch should fall back to cache on OpenSearch error."""
        from opensearchpy import OpenSearchException

        mock_client = MagicMock()
        mock_client.search.side_effect = OpenSearchException("connection error")

        tracker = LiveConnectionTracker(client=mock_client)
        tracker._connections.append(_make_connection())

        conns = tracker.fetch_from_opensearch()
        # Should return cached data
        self.assertEqual(len(conns), 1)

    def test_fetch_without_client(self):
        """Fetch without client should return cached connections."""
        tracker = LiveConnectionTracker()
        tracker._connections.append(_make_connection())
        conns = tracker.fetch_from_opensearch()
        self.assertEqual(len(conns), 1)

    def test_connections_returned_newest_first(self):
        """get_active_connections should return newest first."""
        tracker = LiveConnectionTracker()
        tracker._connections.append(_make_connection(timestamp="2026-03-08T10:00:00Z", source_ip="10.0.0.1"))
        tracker._connections.append(_make_connection(timestamp="2026-03-08T11:00:00Z", source_ip="10.0.0.2"))

        conns = tracker.get_active_connections()
        # Newest (last added) should come first due to reversed()
        self.assertEqual(conns[0]["source_ip"], "10.0.0.2")
        self.assertEqual(conns[1]["source_ip"], "10.0.0.1")


if __name__ == "__main__":
    unittest.main()
