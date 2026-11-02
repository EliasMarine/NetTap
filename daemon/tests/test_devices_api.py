"""
Tests for daemon/api/devices.py

All tests use mocks -- no OpenSearch connection required.
Tests cover device listing, detail, connections, sorting, pagination,
enrichment, and error handling.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from services.dns_analytics import DNS_LOOKUP_EXCLUSION

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.devices import register_device_routes
from storage.manager import StorageManager, RetentionConfig


def _alert_bodies(mock_search):
    """Search bodies that count Suricata alerts (filter has event.dataset == alert)."""
    bodies = []
    for c in mock_search.call_args_list:
        body = c.kwargs.get("body") or c[1].get("body")
        if {"term": {"event.dataset": "alert"}} in body["query"]["bool"].get("filter", []):
            bodies.append(body)
    return bodies


def _make_mock_storage():
    """Create a mock StorageManager with a mock OpenSearch client."""
    config = RetentionConfig()
    with patch.object(StorageManager, "_create_client") as mock_create:
        mock_client = MagicMock()
        mock_create.return_value = mock_client
        storage = StorageManager(config, "http://localhost:9200")
    return storage, mock_client


def _device_list_response(buckets=None):
    """Build a mock OpenSearch response for the device list aggregation."""
    if buckets is None:
        buckets = []
    return {"aggregations": {"devices": {"buckets": buckets}}}


def _empty_alert_response():
    """Build a mock empty alert count response."""
    return {"aggregations": {"by_ip": {"buckets": []}}}


def _device_bucket(
    ip,
    doc_count=100,
    total_bytes=50000,
    protocols=None,
    first_seen=None,
    last_seen=None,
    orig_bytes=None,
    resp_bytes=None,
):
    """Build a single device aggregation bucket."""
    if protocols is None:
        protocols = [{"key": "tcp", "doc_count": 80}, {"key": "udp", "doc_count": 20}]
    return {
        "key": ip,
        "doc_count": doc_count,
        "total_bytes": {"value": total_bytes},
        "protocols": {"buckets": protocols},
        "first_seen": {"value_as_string": first_seen or "2026-02-25T00:00:00.000Z"},
        "last_seen": {"value_as_string": last_seen or "2026-02-25T23:59:59.000Z"},
        "orig_bytes": {"value": orig_bytes},
        "resp_bytes": {"value": resp_bytes},
    }


class TestDeviceListHandler(AioHTTPTestCase):
    """Tests for GET /api/devices."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_device_routes(app, self.storage)
        return app

    def _setup_search_responses(
        self,
        device_response,
        alert_response=None,
        dhcp_response=None,
        conn_mac_response=None,
        dns_response=None,
        http_response=None,
        ssl_response=None,
    ):
        """Configure mock_client.search to return different responses per index.

        The device list handler makes multiple search calls:
        1. NETWORK_INDEX (event.provider=zeek, event.dataset=conn) for device aggregation
        2. NETWORK_INDEX (event.provider=suricata, event.dataset=alert) for alert counts
        3-N. fingerprint lookups (dhcp, conn, dns, http, ssl) per device
        """
        responses = []
        responses.append(device_response)
        if alert_response is not None:
            responses.append(alert_response)
        else:
            responses.append(_empty_alert_response())

        # For each device, fingerprint service makes up to 5 queries:
        # get_mac_for_ip: DHCP then conn
        # get_hostname_for_ip: DNS
        # get_os_hint: HTTP then SSL
        # We'll provide generic empty responses for fingerprint lookups
        empty_hits = {"hits": {"hits": []}}
        empty_aggs = {
            "aggregations": {
                "top_hostname": {"buckets": []},
                "top_ua": {"buckets": []},
                "top_ja3": {"buckets": []},
            }
        }

        # Add enough empty responses for fingerprint calls
        for _ in range(50):
            responses.append(empty_hits)
            responses.append(empty_aggs)

        self.mock_client.search.side_effect = responses

    @unittest_run_loop
    async def test_device_list_success(self):
        """Returns device list with aggregated stats."""
        self._setup_search_responses(
            _device_list_response(
                [
                    _device_bucket("192.168.1.100", doc_count=500, total_bytes=1500000),
                    _device_bucket("192.168.1.101", doc_count=300, total_bytes=800000),
                ]
            )
        )

        resp = await self.client.request("GET", "/api/devices")
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertIn("devices", data)
        self.assertEqual(len(data["devices"]), 2)
        self.assertEqual(data["devices"][0]["ip"], "192.168.1.100")
        self.assertEqual(data["devices"][0]["total_bytes"], 1500000)
        self.assertEqual(data["devices"][0]["connection_count"], 500)
        self.assertIn("protocols", data["devices"][0])
        self.assertIn("from", data)
        self.assertIn("to", data)
        self.assertIn("limit", data)

    @unittest_run_loop
    async def test_device_list_with_limit(self):
        """Limit parameter caps device count."""
        self._setup_search_responses(
            _device_list_response(
                [
                    _device_bucket("192.168.1.100"),
                    _device_bucket("192.168.1.101"),
                    _device_bucket("192.168.1.102"),
                ]
            )
        )

        resp = await self.client.request("GET", "/api/devices?limit=2")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["limit"], 2)
        self.assertLessEqual(len(data["devices"]), 2)

    @unittest_run_loop
    async def test_device_list_limit_capped_at_500(self):
        """Limit parameter is capped at 500."""
        self._setup_search_responses(_device_list_response([]))

        resp = await self.client.request("GET", "/api/devices?limit=1000")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["limit"], 500)

    @unittest_run_loop
    async def test_device_list_empty_results(self):
        """Empty device list returns empty array."""
        self._setup_search_responses(_device_list_response([]))

        resp = await self.client.request("GET", "/api/devices")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["devices"], [])

    @unittest_run_loop
    async def test_device_list_opensearch_error(self):
        """OpenSearch error returns 502."""
        from opensearchpy import ConnectionError as OSConnectionError

        self.mock_client.search.side_effect = OSConnectionError(
            "N/A", "Connection refused", Exception("refused")
        )

        resp = await self.client.request("GET", "/api/devices")
        self.assertEqual(resp.status, 502)
        data = await resp.json()
        self.assertIn("error", data)

    @unittest_run_loop
    async def test_device_list_requests_sent_and_received_sums(self):
        """The devices agg sums source.bytes (sent) and destination.bytes (received)."""
        self._setup_search_responses(_device_list_response([]))

        resp = await self.client.request("GET", "/api/devices")
        self.assertEqual(resp.status, 200)

        call_args = self.mock_client.search.call_args_list[0]
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        sub_aggs = body["aggs"]["devices"]["aggs"]
        self.assertEqual(sub_aggs["orig_bytes"], {"sum": {"field": "source.bytes"}})
        self.assertEqual(
            sub_aggs["resp_bytes"], {"sum": {"field": "destination.bytes"}}
        )

    @unittest_run_loop
    async def test_device_list_returns_sent_and_received_bytes(self):
        """orig/resp bytes map through exactly; missing or null sums become 0."""
        missing = _device_bucket("192.168.1.101")
        del missing["orig_bytes"]
        del missing["resp_bytes"]
        self._setup_search_responses(
            _device_list_response(
                [
                    _device_bucket(
                        "192.168.1.100",
                        total_bytes=99200,
                        orig_bytes=1200.0,
                        resp_bytes=98000.0,
                    ),
                    missing,
                    _device_bucket("192.168.1.102"),  # sums present but null
                ]
            )
        )

        resp = await self.client.request("GET", "/api/devices")
        self.assertEqual(resp.status, 200)
        devices = {d["ip"]: d for d in (await resp.json())["devices"]}

        self.assertEqual(devices["192.168.1.100"]["orig_bytes"], 1200)
        self.assertEqual(devices["192.168.1.100"]["resp_bytes"], 98000)
        for ip in ("192.168.1.101", "192.168.1.102"):
            self.assertEqual(devices[ip]["orig_bytes"], 0)
            self.assertEqual(devices[ip]["resp_bytes"], 0)

    @unittest_run_loop
    async def test_device_list_sort_by_connections(self):
        """Sort=connections passes _count sort to OpenSearch."""
        self._setup_search_responses(_device_list_response([]))

        resp = await self.client.request(
            "GET", "/api/devices?sort=connections&order=asc"
        )
        self.assertEqual(resp.status, 200)

        # Verify the aggregation sort was set correctly
        call_args = self.mock_client.search.call_args_list[0]
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        terms = body["aggs"]["devices"]["terms"]
        self.assertEqual(terms["order"], {"_count": "asc"})

    @unittest_run_loop
    async def test_device_list_sort_by_last_seen(self):
        """Sort=last_seen passes last_seen sort to OpenSearch."""
        self._setup_search_responses(_device_list_response([]))

        resp = await self.client.request("GET", "/api/devices?sort=last_seen")
        self.assertEqual(resp.status, 200)

        call_args = self.mock_client.search.call_args_list[0]
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        terms = body["aggs"]["devices"]["terms"]
        self.assertEqual(terms["order"], {"last_seen": "desc"})

    @unittest_run_loop
    async def test_device_list_invalid_sort_falls_back(self):
        """Invalid sort field falls back to bytes."""
        self._setup_search_responses(_device_list_response([]))

        resp = await self.client.request("GET", "/api/devices?sort=invalid_field")
        self.assertEqual(resp.status, 200)

        call_args = self.mock_client.search.call_args_list[0]
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        terms = body["aggs"]["devices"]["terms"]
        self.assertEqual(terms["order"], {"total_bytes": "desc"})

    @unittest_run_loop
    async def test_device_list_with_time_range(self):
        """Time range params are forwarded to the query."""
        self._setup_search_responses(_device_list_response([]))

        resp = await self.client.request(
            "GET", "/api/devices?from=2026-02-25T00:00:00Z&to=2026-02-26T00:00:00Z"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["from"], "2026-02-25T00:00:00Z")
        self.assertEqual(data["to"], "2026-02-26T00:00:00Z")

    @unittest_run_loop
    async def test_device_list_with_alert_counts(self):
        """Alert counts from Suricata events are merged into device records."""
        alert_response = {
            "aggregations": {
                "by_ip": {
                    "buckets": [
                        {"key": "192.168.1.100", "doc_count": 5},
                    ]
                }
            }
        }
        self._setup_search_responses(
            _device_list_response(
                [
                    _device_bucket("192.168.1.100"),
                    _device_bucket("192.168.1.101"),
                ]
            ),
            alert_response=alert_response,
        )

        resp = await self.client.request("GET", "/api/devices")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        # Find the device with alerts
        device_100 = next(d for d in data["devices"] if d["ip"] == "192.168.1.100")
        device_101 = next(d for d in data["devices"] if d["ip"] == "192.168.1.101")
        self.assertEqual(device_100["alert_count"], 5)
        self.assertEqual(device_101["alert_count"], 0)
        # Suricata engine events are sensor noise, not the device's alerts (#60)
        bodies = _alert_bodies(self.mock_client.search)
        self.assertEqual(len(bodies), 1)
        self.assertIn({"prefix": {"rule.name": "SURICATA "}}, bodies[0]["query"]["bool"]["must_not"])


class TestDeviceDetailHandler(AioHTTPTestCase):
    """Tests for GET /api/devices/{ip}."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_device_routes(app, self.storage)
        return app

    def _setup_detail_responses(
        self, conn_response, dns_response=None, alert_response=None
    ):
        """Configure mock search responses for device detail.

        Calls:
        1. NETWORK_INDEX with zeek conn filter (main agg)
        2. NETWORK_INDEX with zeek dns filter (dns queries)
        3. NETWORK_INDEX with suricata alert filter (alert count)
        4-N. fingerprint calls
        """
        responses = [conn_response]

        if dns_response is not None:
            responses.append(dns_response)
        else:
            responses.append({"aggregations": {"dns_queries": {"buckets": []}}})

        if alert_response is not None:
            responses.append(alert_response)
        else:
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
    async def test_device_detail_success(self):
        """Returns full device detail with aggregations."""
        self._setup_detail_responses(
            {
                "hits": {"total": {"value": 500}},
                "aggregations": {
                    "total_bytes": {"value": 1500000},
                    "protocols": {"buckets": [{"key": "tcp", "doc_count": 400}]},
                    "first_seen": {"value_as_string": "2026-02-25T00:00:00.000Z"},
                    "last_seen": {"value_as_string": "2026-02-25T23:59:59.000Z"},
                    "top_destinations": {
                        "buckets": [
                            {
                                "key": "8.8.8.8",
                                "doc_count": 50,
                                "bytes": {"value": 200000},
                            },
                            {
                                "key": "1.1.1.1",
                                "doc_count": 30,
                                "bytes": {"value": 100000},
                            },
                        ]
                    },
                    "bandwidth_series": {
                        "buckets": [
                            {
                                "key_as_string": "2026-02-25T00:00:00.000Z",
                                "doc_count": 10,
                                "bytes": {"value": 5000},
                            },
                            {
                                "key_as_string": "2026-02-25T00:05:00.000Z",
                                "doc_count": 15,
                                "bytes": {"value": 7000},
                            },
                        ]
                    },
                },
            }
        )

        resp = await self.client.request("GET", "/api/devices/192.168.1.100")
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        device = data["device"]
        self.assertEqual(device["ip"], "192.168.1.100")
        self.assertEqual(device["total_bytes"], 1500000)
        self.assertEqual(device["connection_count"], 500)
        self.assertEqual(len(device["top_destinations"]), 2)
        self.assertEqual(device["top_destinations"][0]["ip"], "8.8.8.8")
        self.assertEqual(len(device["bandwidth_series"]), 2)
        self.assertIn("protocols", device)
        self.assertIn("dns_queries", device)
        self.assertIn("alert_count", device)
        self.assertIn("mac", device)
        self.assertIn("hostname", device)
        self.assertIn("manufacturer", device)
        self.assertIn("os_hint", device)

    @unittest_run_loop
    async def test_device_detail_with_enrichment(self):
        """Fingerprint enrichment data is included in the response."""
        # Main conn response
        conn_resp = {
            "hits": {"total": {"value": 10}},
            "aggregations": {
                "total_bytes": {"value": 5000},
                "protocols": {"buckets": []},
                "first_seen": {"value_as_string": "2026-02-25T12:00:00.000Z"},
                "last_seen": {"value_as_string": "2026-02-25T12:30:00.000Z"},
                "top_destinations": {"buckets": []},
                "bandwidth_series": {"buckets": []},
            },
        }
        # DNS query response
        dns_resp = {
            "aggregations": {
                "dns_queries": {"buckets": [{"key": "example.com", "doc_count": 5}]}
            }
        }
        # Alert response
        alert_resp = {"hits": {"total": {"value": 2}}}
        # Fingerprint: DHCP returns MAC
        dhcp_resp = {
            "hits": {"hits": [{"_source": {"source": {"mac": "00:03:93:11:22:33"}}}]}
        }
        # Fingerprint: DNS hostname
        hostname_resp = {
            "aggregations": {
                "top_hostname": {"buckets": [{"key": "myphone.local", "doc_count": 3}]}
            }
        }
        # Fingerprint: HTTP User-Agent
        ua_resp = {
            "aggregations": {
                "top_ua": {
                    "buckets": [
                        {
                            "key": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit/605.1.15",
                            "doc_count": 20,
                        }
                    ]
                }
            }
        }

        responses = [
            conn_resp,
            dns_resp,
            alert_resp,
            dhcp_resp,  # get_mac_for_ip: DHCP
            hostname_resp,  # get_hostname_for_ip: DNS
            ua_resp,  # get_os_hint: HTTP
        ]
        # Add extra empty responses for any additional calls
        for _ in range(20):
            responses.append({"hits": {"hits": []}})
            responses.append({"aggregations": {}})

        self.mock_client.search.side_effect = responses

        resp = await self.client.request("GET", "/api/devices/192.168.1.50")
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        device = data["device"]
        self.assertEqual(device["mac"], "00:03:93:11:22:33")
        self.assertEqual(device["hostname"], "myphone.local")
        self.assertEqual(device["os_hint"], "iOS")
        self.assertEqual(device["alert_count"], 2)
        alert_bodies = _alert_bodies(self.mock_client.search)
        self.assertEqual(len(alert_bodies), 1)
        self.assertIn({"prefix": {"rule.name": "SURICATA "}}, alert_bodies[0]["query"]["bool"]["must_not"])  # (#60)
        self.assertEqual(len(device["dns_queries"]), 1)
        self.assertEqual(device["dns_queries"][0]["domain"], "example.com")
        # Malcolm's own pcap-monitor lookups are not the device's DNS
        dns_bodies = [
            c.kwargs["body"]
            for c in self.mock_client.search.call_args_list
            if "dns_queries" in c.kwargs["body"].get("aggs", {})
        ]
        self.assertEqual(len(dns_bodies), 1)
        self.assertIn(
            {"term": {"zeek.dns.query": "pcap-monitor"}},
            dns_bodies[0]["query"]["bool"]["must_not"],
        )
        # nor are its mDNS announcements
        self.assertIn(
            DNS_LOOKUP_EXCLUSION[1],
            dns_bodies[0]["query"]["bool"]["must_not"],
        )

    @unittest_run_loop
    async def test_device_detail_not_found_returns_empty(self):
        """Non-existent device IP returns empty device data (not 404)."""
        self._setup_detail_responses(
            {
                "hits": {"total": {"value": 0}},
                "aggregations": {
                    "total_bytes": {"value": 0},
                    "protocols": {"buckets": []},
                    "first_seen": {"value_as_string": ""},
                    "last_seen": {"value_as_string": ""},
                    "top_destinations": {"buckets": []},
                    "bandwidth_series": {"buckets": []},
                },
            }
        )

        resp = await self.client.request("GET", "/api/devices/10.99.99.99")
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        device = data["device"]
        self.assertEqual(device["ip"], "10.99.99.99")
        self.assertEqual(device["total_bytes"], 0)
        self.assertEqual(device["connection_count"], 0)
        self.assertEqual(device["top_destinations"], [])
        self.assertEqual(device["bandwidth_series"], [])

    @unittest_run_loop
    async def test_device_detail_opensearch_error(self):
        """OpenSearch error returns 502."""
        from opensearchpy import ConnectionError as OSConnectionError

        self.mock_client.search.side_effect = OSConnectionError(
            "N/A", "Connection refused", Exception("refused")
        )

        resp = await self.client.request("GET", "/api/devices/192.168.1.1")
        self.assertEqual(resp.status, 502)
        data = await resp.json()
        self.assertIn("error", data)


class TestDeviceConnectionsHandler(AioHTTPTestCase):
    """Tests for GET /api/devices/{ip}/connections."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_device_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_connections_success(self):
        """Returns paginated connections for a device."""
        self.mock_client.search.return_value = {
            "hits": {
                "total": {"value": 150},
                "hits": [
                    {
                        "_id": "conn1",
                        "_index": "zeek-conn-2026.02.25",
                        "_source": {
                            "@timestamp": "2026-02-25T12:00:00Z",
                            "network.transport": "tcp",
                            "source.ip": "192.168.1.100",
                            "destination.ip": "8.8.8.8",
                            "client.bytes": 1000,
                            "server.bytes": 5000,
                        },
                    },
                    {
                        "_id": "conn2",
                        "_index": "zeek-conn-2026.02.25",
                        "_source": {
                            "@timestamp": "2026-02-25T12:01:00Z",
                            "network.transport": "udp",
                            "source.ip": "192.168.1.100",
                            "destination.ip": "1.1.1.1",
                            "client.bytes": 200,
                            "server.bytes": 800,
                        },
                    },
                ],
            }
        }

        resp = await self.client.request(
            "GET", "/api/devices/192.168.1.100/connections?page=1&size=50"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertEqual(data["ip"], "192.168.1.100")
        self.assertEqual(data["total"], 150)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["size"], 50)
        self.assertEqual(data["total_pages"], 3)
        self.assertEqual(len(data["connections"]), 2)
        self.assertEqual(data["connections"][0]["_id"], "conn1")
        self.assertEqual(data["connections"][0]["network.transport"], "tcp")

    @unittest_run_loop
    async def test_connections_empty(self):
        """Empty connections return empty list with zero total."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }

        resp = await self.client.request("GET", "/api/devices/10.0.0.99/connections")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["connections"], [])
        self.assertEqual(data["total_pages"], 0)

    @unittest_run_loop
    async def test_connections_pagination(self):
        """Page and size parameters calculate correct offset."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 200}, "hits": []}
        }

        resp = await self.client.request(
            "GET", "/api/devices/192.168.1.100/connections?page=3&size=25"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["page"], 3)
        self.assertEqual(data["size"], 25)

        # Verify the offset passed to OpenSearch
        call_args = self.mock_client.search.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        self.assertEqual(body["from"], 50)  # (3-1) * 25 = 50
        self.assertEqual(body["size"], 25)

    @unittest_run_loop
    async def test_connections_size_capped(self):
        """Page size is capped at 200."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }

        resp = await self.client.request(
            "GET", "/api/devices/192.168.1.100/connections?size=500"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["size"], 200)

    @unittest_run_loop
    async def test_connections_includes_both_directions(self):
        """Query matches connections where device is source OR destination."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }

        await self.client.request("GET", "/api/devices/192.168.1.100/connections")

        call_args = self.mock_client.search.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        bool_filter = body["query"]["bool"]["filter"]

        # Find the should clause
        should_clause = None
        for f in bool_filter:
            if "bool" in f and "should" in f["bool"]:
                should_clause = f["bool"]["should"]
                break

        self.assertIsNotNone(
            should_clause, "Should clause for bidirectional matching not found"
        )
        self.assertEqual(len(should_clause), 2)

    @unittest_run_loop
    async def test_connections_opensearch_error(self):
        """OpenSearch error returns 502."""
        from opensearchpy import ConnectionError as OSConnectionError

        self.mock_client.search.side_effect = OSConnectionError(
            "N/A", "Connection refused", Exception("refused")
        )

        resp = await self.client.request(
            "GET", "/api/devices/192.168.1.100/connections"
        )
        self.assertEqual(resp.status, 502)
        data = await resp.json()
        self.assertIn("error", data)


def _route_device_searches(device_response):
    """search() side effect: the device terms agg gets device_response, the rest empty."""

    def _search(index=None, body=None, **_kwargs):
        if "devices" in (body or {}).get("aggs", {}):
            return device_response
        return {
            "hits": {"hits": []},
            "aggregations": {
                "by_ip": {"buckets": []},
                "top_hostname": {"buckets": []},
                "top_ua": {"buckets": []},
            },
        }

    return _search


class TestDeviceCountHandler(AioHTTPTestCase):
    """Tests for GET /api/devices/count agreeing with GET /api/devices."""

    _RANGE = "?from=2026-02-25T00:00:00Z&to=2026-02-26T00:00:00Z"

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        app["lan_filter"] = {"terms": {"source.ip": ["192.168.1.0/24"]}}
        app["excluded_ips"] = ["192.168.1.77"]
        register_device_routes(app, self.storage)
        return app

    def _bodies(self):
        return [c.kwargs["body"] for c in self.mock_client.search.call_args_list]

    @unittest_run_loop
    async def test_count_equals_device_list_length(self):
        """Count returns exactly as many devices as the list for the same buckets."""
        buckets = [
            _device_bucket("192.168.1.10", doc_count=40),
            _device_bucket("192.168.1.11", doc_count=3),
            _device_bucket("192.168.1.255", doc_count=50),
            _device_bucket("192.168.1.0", doc_count=50),
            _device_bucket("224.0.0.251", doc_count=50),
        ]
        self.mock_client.search.side_effect = _route_device_searches(
            _device_list_response(buckets)
        )

        list_resp = await self.client.request("GET", "/api/devices" + self._RANGE)
        count_resp = await self.client.request(
            "GET", "/api/devices/count" + self._RANGE
        )

        devices = (await list_resp.json())["devices"]
        data = await count_resp.json()
        self.assertEqual(len(devices), 2)
        self.assertEqual(data["count"], len(devices))
        self.assertEqual(set(data), {"from", "to", "count"})

    @unittest_run_loop
    async def test_count_uses_same_filters_as_list(self):
        """Count and list send the identical bool query (range, conn, LAN, excluded)."""
        self.mock_client.search.side_effect = _route_device_searches(
            _device_list_response([])
        )

        await self.client.request("GET", "/api/devices" + self._RANGE)
        await self.client.request("GET", "/api/devices/count" + self._RANGE)

        list_body, count_body = self._bodies()
        self.assertEqual(count_body["query"], list_body["query"])
        bool_query = count_body["query"]["bool"]
        self.assertIn({"term": {"event.dataset": "conn"}}, bool_query["filter"])
        self.assertIn(
            {"terms": {"source.ip": ["192.168.1.0/24"]}}, bool_query["filter"]
        )
        self.assertIn(
            {"terms": {"source.ip": ["192.168.1.77"]}}, bool_query["must_not"]
        )

    @unittest_run_loop
    async def test_list_and_count_share_min_connections(self):
        """Both endpoints use the module _MIN_CONNECTIONS threshold, now 3."""
        from api import devices

        self.assertEqual(devices._MIN_CONNECTIONS, 3)
        self.mock_client.search.side_effect = _route_device_searches(
            _device_list_response([])
        )

        await self.client.request("GET", "/api/devices" + self._RANGE)
        await self.client.request("GET", "/api/devices/count" + self._RANGE)

        list_body, count_body = self._bodies()
        for body in (list_body, count_body):
            terms = body["aggs"]["devices"]["terms"]
            self.assertEqual(terms["field"], "source.ip")
            self.assertEqual(terms["min_doc_count"], devices._MIN_CONNECTIONS)


class TestDeviceTimeRange(AioHTTPTestCase):
    """Tests for time range parameter parsing in device endpoints."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_device_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_valid_time_range_preserved(self):
        """Valid from/to parameters are preserved in the response."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }

        resp = await self.client.request(
            "GET",
            "/api/devices/192.168.1.1/connections"
            "?from=2026-02-25T00:00:00Z&to=2026-02-26T00:00:00Z",
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["from"], "2026-02-25T00:00:00Z")
        self.assertEqual(data["to"], "2026-02-26T00:00:00Z")

    @unittest_run_loop
    async def test_invalid_time_range_falls_back(self):
        """Invalid time range parameters fall back to defaults."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }

        resp = await self.client.request(
            "GET", "/api/devices/192.168.1.1/connections?from=bad-date&to=also-bad"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        # Should have defaulted to valid ISO timestamps
        self.assertNotEqual(data["from"], "bad-date")
        self.assertNotEqual(data["to"], "also-bad")


if __name__ == "__main__":
    unittest.main()


class TestDeviceCategoryFallbacks:
    """#26: the vendor (and phone/computer hostnames) decide when OS and hostname hints don't."""

    def test_single_purpose_vendor(self):
        from api.devices import _device_category

        assert _device_category(None, "001788483c07.local", "Philips Lighting (Hue)") == "iot"
        assert _device_category(None, None, "Ubiquiti Inc") == "infrastructure"
        assert _device_category(None, None, "Proxmox Server Solutions GmbH") == "computer"
        assert _device_category(None, None, "Apple, Inc.") == "unknown"  # makes phones and computers
        assert _device_category(None, None, "Arcadyan Corporation") == "unknown"  # routers and TV Wi-Fi
        assert _device_category(None, None, None) == "unknown"

    def test_os_and_hostname_still_win(self):
        from api.devices import _device_category

        assert _device_category("Android", None, "Ubiquiti Inc") == "phone"
        # the fingerprint's real labels (#21 found these never matched)
        assert _device_category("Windows 10/11", None, None) == "computer"
        assert _device_category("Windows 8.1", None, None) == "computer"
        assert _device_category("Xbox", None, None) == "media"

    def test_console_and_streamer_hostnames_are_media(self):
        from api.devices import _device_category

        # "nintendo-switch" used to hit the IoT hint "switch"
        for host in ("nintendo-switch", "xbox-one", "PlayStation-5", "ps5-living", "Roku-Ultra", "LGwebOSTV"):
            assert _device_category(None, host, None) == "media", host
        assert _device_category("Linux", "chromecast-ultra", None) == "media"
        # the IoT and infrastructure hostname rules still apply
        assert _device_category(None, "smart-plug-2", None) == "iot"
        assert _device_category(None, "unifi-ap-lite", None) == "infrastructure"
        assert _device_category(None, "living-room-smart-plug", "Ubiquiti Inc") == "iot"

    def test_phone_and_computer_hostnames(self):
        from api.devices import _device_category

        assert _device_category(None, "ipad-2.local", None) == "phone"
        assert _device_category(None, "saras-macbook-air-2.local", None) == "computer"
        assert _device_category(None, "elias-mac-studio.local", None) == "computer"
