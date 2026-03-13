"""
Tests for device detail v2 endpoints in daemon/api/devices.py

Covers the three new endpoints:
- GET /api/devices/{ip}/categories
- GET /api/devices/{ip}/alerts
- GET /api/devices/{ip}/ports

All tests use mocks -- no OpenSearch connection required.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.devices import register_device_routes
from storage.manager import StorageManager, RetentionConfig


def _make_mock_storage():
    """Create a mock StorageManager with a mock OpenSearch client."""
    config = RetentionConfig()
    with patch.object(StorageManager, "_create_client") as mock_create:
        mock_client = MagicMock()
        mock_create.return_value = mock_client
        storage = StorageManager(config, "http://localhost:9200")
    return storage, mock_client


# ---------------------------------------------------------------------------
# Categories endpoint tests
# ---------------------------------------------------------------------------


class TestDeviceCategoriesHandler(AioHTTPTestCase):
    """Tests for GET /api/devices/{ip}/categories."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_device_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_device_categories_returns_data(self):
        """Mock ASN buckets are classified into categories correctly."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "asn_breakdown": {
                    "buckets": [
                        {
                            "key": "AS2906 Netflix Inc",
                            "doc_count": 100,
                            "total_bytes": {"value": 5000000},
                        },
                        {
                            "key": "AS15169 Google LLC",
                            "doc_count": 200,
                            "total_bytes": {"value": 3000000},
                        },
                        {
                            "key": "AS32934 Facebook, Inc.",
                            "doc_count": 50,
                            "total_bytes": {"value": 1000000},
                        },
                        {
                            "key": "AS99999 Unknown Corp",
                            "doc_count": 10,
                            "total_bytes": {"value": 100000},
                        },
                    ]
                }
            }
        }

        resp = await self.client.request("GET", "/api/devices/192.168.1.100/categories")
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertEqual(data["ip"], "192.168.1.100")
        self.assertIn("from", data)
        self.assertIn("to", data)
        self.assertIn("categories", data)

        categories = data["categories"]
        # Netflix + Google should both be streaming (Google maps to streaming
        # because "Google" key in ASN_CATEGORY_MAP maps to "streaming")
        cat_names = {c["name"] for c in categories}
        self.assertIn("streaming", cat_names)
        self.assertIn("social", cat_names)
        self.assertIn("other", cat_names)

        # Streaming should have the most bytes (Netflix 5M + Google 3M = 8M)
        streaming = next(c for c in categories if c["name"] == "streaming")
        self.assertEqual(streaming["total_bytes"], 8000000)
        self.assertEqual(streaming["connection_count"], 300)
        self.assertEqual(streaming["label"], "Streaming")

        # Social should have Facebook's data
        social = next(c for c in categories if c["name"] == "social")
        self.assertEqual(social["total_bytes"], 1000000)

        # Unknown Corp should be "other"
        other = next(c for c in categories if c["name"] == "other")
        self.assertEqual(other["total_bytes"], 100000)

    @unittest_run_loop
    async def test_device_categories_empty(self):
        """Empty ASN buckets return empty categories list."""
        self.mock_client.search.return_value = {
            "aggregations": {"asn_breakdown": {"buckets": []}}
        }

        resp = await self.client.request("GET", "/api/devices/10.0.0.1/categories")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["categories"], [])

    @unittest_run_loop
    async def test_device_categories_opensearch_error(self):
        """OpenSearch error returns 502."""
        from opensearchpy import ConnectionError as OSConnectionError

        self.mock_client.search.side_effect = OSConnectionError(
            "N/A", "Connection refused", Exception("refused")
        )

        resp = await self.client.request("GET", "/api/devices/192.168.1.1/categories")
        self.assertEqual(resp.status, 502)
        data = await resp.json()
        self.assertIn("error", data)

    @unittest_run_loop
    async def test_device_categories_sorted_by_bytes(self):
        """Categories are sorted descending by total_bytes."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "asn_breakdown": {
                    "buckets": [
                        {
                            "key": "AS32934 Facebook, Inc.",
                            "doc_count": 10,
                            "total_bytes": {"value": 100},
                        },
                        {
                            "key": "AS2906 Netflix Inc",
                            "doc_count": 50,
                            "total_bytes": {"value": 5000},
                        },
                    ]
                }
            }
        }

        resp = await self.client.request("GET", "/api/devices/192.168.1.100/categories")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        categories = data["categories"]
        self.assertEqual(len(categories), 2)
        # Streaming (Netflix) should be first since it has more bytes
        self.assertEqual(categories[0]["name"], "streaming")
        self.assertEqual(categories[1]["name"], "social")


# ---------------------------------------------------------------------------
# Alerts endpoint tests
# ---------------------------------------------------------------------------


class TestDeviceAlertsHandler(AioHTTPTestCase):
    """Tests for GET /api/devices/{ip}/alerts."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_device_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_device_alerts_returns_data(self):
        """Mock alert hits are parsed and returned with correct fields."""
        self.mock_client.search.return_value = {
            "hits": {
                "total": {"value": 3},
                "hits": [
                    {
                        "_source": {
                            "@timestamp": "2026-03-12T10:00:00Z",
                            "source": {"ip": "192.168.1.100", "port": 54321},
                            "destination": {"ip": "10.0.0.5", "port": 80},
                            "suricata": {
                                "eve": {
                                    "alert": {
                                        "severity": 1,
                                        "signature": "ET MALWARE Bad Traffic",
                                        "category": "A Network Trojan was Detected",
                                        "signature_id": 2001219,
                                    }
                                }
                            },
                        }
                    },
                    {
                        "_source": {
                            "@timestamp": "2026-03-12T09:30:00Z",
                            "source": {"ip": "192.168.1.100", "port": 12345},
                            "destination": {"ip": "8.8.8.8", "port": 443},
                            "alert": {
                                "severity": 2,
                                "signature": "ET INFO Observed DNS Query for Suspicious TLD",
                                "category": "Potentially Bad Traffic",
                                "signature_id": 2027863,
                            },
                        }
                    },
                ],
            }
        }

        resp = await self.client.request("GET", "/api/devices/192.168.1.100/alerts")
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertEqual(data["ip"], "192.168.1.100")
        self.assertEqual(data["total"], 3)
        self.assertIn("from", data)
        self.assertIn("to", data)
        self.assertEqual(len(data["alerts"]), 2)

        # First alert — parsed from suricata.eve.alert
        alert0 = data["alerts"][0]
        self.assertEqual(alert0["timestamp"], "2026-03-12T10:00:00Z")
        self.assertEqual(alert0["severity"], 1)
        self.assertEqual(alert0["signature"], "ET MALWARE Bad Traffic")
        self.assertEqual(alert0["category"], "A Network Trojan was Detected")
        self.assertEqual(alert0["signature_id"], 2001219)
        self.assertEqual(alert0["source_ip"], "192.168.1.100")
        self.assertEqual(alert0["destination_ip"], "10.0.0.5")
        self.assertEqual(alert0["source_port"], 54321)
        self.assertEqual(alert0["destination_port"], 80)

        # Second alert — parsed from top-level alert field (fallback)
        alert1 = data["alerts"][1]
        self.assertEqual(alert1["severity"], 2)
        self.assertEqual(alert1["signature"], "ET INFO Observed DNS Query for Suspicious TLD")
        self.assertEqual(alert1["signature_id"], 2027863)

    @unittest_run_loop
    async def test_device_alerts_empty(self):
        """No alerts return empty list."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }

        resp = await self.client.request("GET", "/api/devices/10.0.0.1/alerts")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["alerts"], [])

    @unittest_run_loop
    async def test_device_alerts_limit_param(self):
        """Limit parameter is passed to OpenSearch query size."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }

        await self.client.request("GET", "/api/devices/192.168.1.100/alerts?limit=5")

        call_args = self.mock_client.search.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        self.assertEqual(body["size"], 5)

    @unittest_run_loop
    async def test_device_alerts_opensearch_error(self):
        """OpenSearch error returns 502."""
        from opensearchpy import ConnectionError as OSConnectionError

        self.mock_client.search.side_effect = OSConnectionError(
            "N/A", "Connection refused", Exception("refused")
        )

        resp = await self.client.request("GET", "/api/devices/192.168.1.1/alerts")
        self.assertEqual(resp.status, 502)
        data = await resp.json()
        self.assertIn("error", data)

    @unittest_run_loop
    async def test_device_alerts_matches_both_directions(self):
        """Query matches alerts where device is source OR destination."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }

        await self.client.request("GET", "/api/devices/192.168.1.100/alerts")

        call_args = self.mock_client.search.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        bool_filter = body["query"]["bool"]["filter"]

        # Find the should clause for bidirectional IP matching
        should_clause = None
        for f in bool_filter:
            if "bool" in f and "should" in f["bool"]:
                should_clause = f["bool"]["should"]
                break

        self.assertIsNotNone(
            should_clause, "Should clause for bidirectional matching not found"
        )
        ips = [s["term"].get("source.ip") or s["term"].get("destination.ip") for s in should_clause]
        self.assertIn("192.168.1.100", ips)


# ---------------------------------------------------------------------------
# Ports endpoint tests
# ---------------------------------------------------------------------------


class TestDevicePortsHandler(AioHTTPTestCase):
    """Tests for GET /api/devices/{ip}/ports."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_device_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_device_ports_returns_data(self):
        """Mock port buckets are returned with service names and suspicious flags."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "top_ports": {
                    "buckets": [
                        {"key": 443, "doc_count": 500},
                        {"key": 80, "doc_count": 200},
                        {"key": 53, "doc_count": 150},
                        {"key": 22, "doc_count": 50},
                        {"key": 4444, "doc_count": 5},
                        {"key": 31337, "doc_count": 2},
                        {"key": 9999, "doc_count": 1},
                    ]
                }
            }
        }

        resp = await self.client.request("GET", "/api/devices/192.168.1.100/ports")
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertEqual(data["ip"], "192.168.1.100")
        self.assertIn("from", data)
        self.assertIn("to", data)
        self.assertEqual(len(data["ports"]), 7)

        # Verify known service names
        port_443 = next(p for p in data["ports"] if p["port"] == 443)
        self.assertEqual(port_443["service"], "HTTPS")
        self.assertEqual(port_443["connections"], 500)
        self.assertFalse(port_443["suspicious"])

        port_80 = next(p for p in data["ports"] if p["port"] == 80)
        self.assertEqual(port_80["service"], "HTTP")
        self.assertFalse(port_80["suspicious"])

        port_53 = next(p for p in data["ports"] if p["port"] == 53)
        self.assertEqual(port_53["service"], "DNS")

        port_22 = next(p for p in data["ports"] if p["port"] == 22)
        self.assertEqual(port_22["service"], "SSH")

        # Verify suspicious port flags
        port_4444 = next(p for p in data["ports"] if p["port"] == 4444)
        self.assertTrue(port_4444["suspicious"])
        self.assertEqual(port_4444["service"], "Unknown")

        port_31337 = next(p for p in data["ports"] if p["port"] == 31337)
        self.assertTrue(port_31337["suspicious"])

        port_9999 = next(p for p in data["ports"] if p["port"] == 9999)
        self.assertTrue(port_9999["suspicious"])

    @unittest_run_loop
    async def test_device_ports_empty(self):
        """No port data returns empty list."""
        self.mock_client.search.return_value = {
            "aggregations": {"top_ports": {"buckets": []}}
        }

        resp = await self.client.request("GET", "/api/devices/10.0.0.1/ports")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["ports"], [])

    @unittest_run_loop
    async def test_device_ports_opensearch_error(self):
        """OpenSearch error returns 502."""
        from opensearchpy import ConnectionError as OSConnectionError

        self.mock_client.search.side_effect = OSConnectionError(
            "N/A", "Connection refused", Exception("refused")
        )

        resp = await self.client.request("GET", "/api/devices/192.168.1.1/ports")
        self.assertEqual(resp.status, 502)
        data = await resp.json()
        self.assertIn("error", data)

    @unittest_run_loop
    async def test_device_ports_unknown_port_service(self):
        """Ports not in PORT_NAMES map get 'Unknown' service name."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "top_ports": {
                    "buckets": [
                        {"key": 12345, "doc_count": 10},
                        {"key": 54321, "doc_count": 5},
                    ]
                }
            }
        }

        resp = await self.client.request("GET", "/api/devices/192.168.1.100/ports")
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        for port in data["ports"]:
            if port["port"] == 54321:
                self.assertEqual(port["service"], "Unknown")
                self.assertFalse(port["suspicious"])
            elif port["port"] == 12345:
                self.assertEqual(port["service"], "Unknown")
                self.assertTrue(port["suspicious"])


# ---------------------------------------------------------------------------
# Device detail v2 field additions tests
# ---------------------------------------------------------------------------


class TestDeviceDetailV2Fields(AioHTTPTestCase):
    """Tests for new fields added to GET /api/devices/{ip} in v2."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_device_routes(app, self.storage)
        return app

    def _setup_detail_responses(self, conn_response):
        """Configure mock search responses for device detail."""
        responses = [conn_response]
        # DNS queries response
        responses.append({"aggregations": {"dns_queries": {"buckets": []}}})
        # Alert count response
        responses.append({"hits": {"total": {"value": 0}}})
        # Fingerprint empty responses
        empty_hits = {"hits": {"hits": []}}
        empty_aggs = {
            "aggregations": {
                "top_hostname": {"buckets": []},
                "top_ua": {"buckets": []},
                "top_ja3": {"buckets": []},
            }
        }
        for _ in range(20):
            responses.append(empty_hits)
            responses.append(empty_aggs)
        self.mock_client.search.side_effect = responses

    @unittest_run_loop
    async def test_detail_includes_orig_resp_bytes(self):
        """Device detail includes orig_bytes and resp_bytes fields."""
        self._setup_detail_responses({
            "hits": {"total": {"value": 100}},
            "aggregations": {
                "total_bytes": {"value": 3000000},
                "total_orig_bytes": {"value": 1000000},
                "total_resp_bytes": {"value": 2000000},
                "unique_destinations": {"value": 42},
                "top_services": {"buckets": []},
                "protocols": {"buckets": [{"key": "tcp", "doc_count": 90}]},
                "first_seen": {"value_as_string": "2026-03-12T00:00:00.000Z"},
                "last_seen": {"value_as_string": "2026-03-12T23:59:59.000Z"},
                "top_destinations": {"buckets": []},
                "bandwidth_series": {"buckets": []},
            },
        })

        resp = await self.client.request("GET", "/api/devices/192.168.1.100")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        device = data["device"]

        self.assertEqual(device["orig_bytes"], 1000000)
        self.assertEqual(device["resp_bytes"], 2000000)

    @unittest_run_loop
    async def test_detail_includes_unique_destinations(self):
        """Device detail includes unique_destinations count."""
        self._setup_detail_responses({
            "hits": {"total": {"value": 50}},
            "aggregations": {
                "total_bytes": {"value": 500000},
                "total_orig_bytes": {"value": 200000},
                "total_resp_bytes": {"value": 300000},
                "unique_destinations": {"value": 25},
                "top_services": {"buckets": []},
                "protocols": {"buckets": []},
                "first_seen": {"value_as_string": "2026-03-12T00:00:00.000Z"},
                "last_seen": {"value_as_string": "2026-03-12T23:59:59.000Z"},
                "top_destinations": {"buckets": []},
                "bandwidth_series": {"buckets": []},
            },
        })

        resp = await self.client.request("GET", "/api/devices/192.168.1.100")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["device"]["unique_destinations"], 25)

    @unittest_run_loop
    async def test_detail_includes_top_services(self):
        """Device detail includes top_services with merged ASN names."""
        self._setup_detail_responses({
            "hits": {"total": {"value": 200}},
            "aggregations": {
                "total_bytes": {"value": 1000000},
                "total_orig_bytes": {"value": 400000},
                "total_resp_bytes": {"value": 600000},
                "unique_destinations": {"value": 15},
                "top_services": {
                    "buckets": [
                        {
                            "key": "AS16509 Amazon.com, Inc.",
                            "doc_count": 80,
                            "bytes": {"value": 500000},
                        },
                        {
                            "key": "AS14618 Amazon.com, Inc.",
                            "doc_count": 40,
                            "bytes": {"value": 200000},
                        },
                        {
                            "key": "AS2906 Netflix Inc",
                            "doc_count": 60,
                            "bytes": {"value": 300000},
                        },
                    ]
                },
                "protocols": {"buckets": []},
                "first_seen": {"value_as_string": "2026-03-12T00:00:00.000Z"},
                "last_seen": {"value_as_string": "2026-03-12T23:59:59.000Z"},
                "top_destinations": {"buckets": []},
                "bandwidth_series": {"buckets": []},
            },
        })

        resp = await self.client.request("GET", "/api/devices/192.168.1.100")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        services = data["device"]["top_services"]

        # Amazon.com, Inc. should be merged from two ASN buckets
        self.assertEqual(len(services), 2)

        # Sorted by bytes descending: Amazon (700k) then Netflix (300k)
        self.assertEqual(services[0]["name"], "Amazon.com, Inc.")
        self.assertEqual(services[0]["bytes"], 700000)
        self.assertEqual(services[0]["connections"], 120)  # 80 + 40

        self.assertEqual(services[1]["name"], "Netflix Inc")
        self.assertEqual(services[1]["bytes"], 300000)
        self.assertEqual(services[1]["connections"], 60)

    @unittest_run_loop
    async def test_detail_bandwidth_includes_dl_ul(self):
        """Bandwidth series items include download_bytes and upload_bytes."""
        self._setup_detail_responses({
            "hits": {"total": {"value": 100}},
            "aggregations": {
                "total_bytes": {"value": 500000},
                "total_orig_bytes": {"value": 200000},
                "total_resp_bytes": {"value": 300000},
                "unique_destinations": {"value": 10},
                "top_services": {"buckets": []},
                "protocols": {"buckets": []},
                "first_seen": {"value_as_string": "2026-03-12T00:00:00.000Z"},
                "last_seen": {"value_as_string": "2026-03-12T23:59:59.000Z"},
                "top_destinations": {"buckets": []},
                "bandwidth_series": {
                    "buckets": [
                        {
                            "key_as_string": "2026-03-12T00:00:00.000Z",
                            "doc_count": 10,
                            "bytes": {"value": 5000},
                            "download_bytes": {"value": 3000},
                            "upload_bytes": {"value": 2000},
                        },
                        {
                            "key_as_string": "2026-03-12T00:05:00.000Z",
                            "doc_count": 15,
                            "bytes": {"value": 8000},
                            "download_bytes": {"value": 6000},
                            "upload_bytes": {"value": 2000},
                        },
                    ]
                },
            },
        })

        resp = await self.client.request("GET", "/api/devices/192.168.1.100")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        bw = data["device"]["bandwidth_series"]

        self.assertEqual(len(bw), 2)
        self.assertEqual(bw[0]["bytes"], 5000)
        self.assertEqual(bw[0]["download_bytes"], 3000)
        self.assertEqual(bw[0]["upload_bytes"], 2000)
        self.assertEqual(bw[1]["download_bytes"], 6000)
        self.assertEqual(bw[1]["upload_bytes"], 2000)


if __name__ == "__main__":
    unittest.main()
