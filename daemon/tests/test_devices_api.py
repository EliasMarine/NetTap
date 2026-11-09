"""
Tests for daemon/api/devices.py

All tests use mocks -- no OpenSearch connection required.
Tests cover device listing, detail, connections, sorting, pagination,
enrichment, and error handling.
"""

import os
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from services.dns_analytics import DNS_LOOKUP_EXCLUSION

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.devices import register_device_routes
from services.device_registry import DeviceRegistry
from services.excluded_ips import CONN_ACCOUNTING
from storage.manager import StorageManager, RetentionConfig


def _alert_bodies(mock_search):
    """Search bodies that count Suricata alerts (filter has event.dataset == alert)."""
    bodies = []
    for c in mock_search.call_args_list:
        body = c.kwargs.get("body") or c[1].get("body")
        if {"term": {"event.dataset": "alert"}} in body["query"]["bool"].get(
            "filter", []
        ):
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
    """A mock reply for the device search: the one composite page the list reads (slice 2b-3),
    in key order with no after_key, and the terms shape _route_device_searches routes from."""
    if buckets is None:
        buckets = []
    # OLD CODE START — slice 2b-3: the list read a terms aggregation
    # return {"aggregations": {"devices": {"buckets": buckets}}}
    # OLD CODE END
    page = [
        {**b, "key": {"ip": b["key"]}} for b in sorted(buckets, key=lambda b: b["key"])
    ]
    return {"aggregations": {"devices": {"buckets": buckets}, "all": {"buckets": page}}}


def _empty_alert_response():
    """Build a mock empty alert count response."""
    return {
        "aggregations": {
            "by_ip": {"ips": {"buckets": []}},
            "by_dst": {"ips": {"buckets": []}},
        }
    }


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
    # OLD CODE START — NET-226: the list summed total_bytes in Painless and orig/resp apart
    # return {
    #     "key": ip,
    #     "doc_count": doc_count,
    #     "total_bytes": {"value": total_bytes},
    #     "protocols": {"buckets": protocols},
    #     "first_seen": {"value_as_string": first_seen or "2026-02-25T00:00:00.000Z"},
    #     "last_seen": {"value_as_string": last_seen or "2026-02-25T23:59:59.000Z"},
    #     "orig_bytes": {"value": orig_bytes},
    #     "resp_bytes": {"value": resp_bytes},
    # }
    # OLD CODE END
    # The started side's upload/download sums; without a split all of total_bytes is upload
    return {
        "key": ip,
        "doc_count": doc_count,
        "protocols": {"buckets": protocols},
        "first_seen": {"value_as_string": first_seen or "2026-02-25T00:00:00.000Z"},
        "last_seen": {"value_as_string": last_seen or "2026-02-25T23:59:59.000Z"},
        "upload": {"value": total_bytes if orig_bytes is None else orig_bytes},
        "download": {"value": resp_bytes},
    }


def _no_answers(body):
    """Replies for the searches NET-226 added when nothing answered and nothing is IPv6."""
    aggs = body.get("aggs", {})
    if "answered" in aggs and "started" not in aggs:  # answered_by_ip
        return {"aggregations": {"answered": {"buckets": []}}}
    if "started" in aggs and "answered" in aggs and "macs" in aggs["started"]["aggs"]:
        return {  # ipv6_by_mac
            "aggregations": {
                "started": {"macs": {"buckets": []}},
                "answered": {"macs": {"buckets": []}},
            }
        }
    if "ips" in aggs:  # _ipv6_mac_of
        return {"aggregations": {"ips": {"buckets": []}}}
    return None


def _answering(replies):
    """search() side effect: the NET-226 searches find nothing (_no_answers); every other
    search takes the next of `replies` (raising it if it is an exception), or `replies` itself
    when it is one reply for every search."""
    queue = list(replies) if isinstance(replies, list) else None

    def _search(index=None, body=None, **_kwargs):
        answers = _no_answers(body or {})
        if answers:
            return answers
        if queue is None:
            return replies
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    return _search


def _detail_body(search_mock):
    """The device detail's main search (NET-226: it is no longer the first)."""
    return next(
        c.kwargs["body"]
        for c in search_mock.call_args_list
        if "bandwidth_series" in c.kwargs["body"].get("aggs", {})
    )


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
        # OLD CODE START — NET-226: replies in call order; the list now also reads the answered
        # side and IPv6, so each search is answered by its shape instead
        # responses = [device_response, alert_response or _empty_alert_response(),
        #              *([empty_hits, empty_aggs] * 50)]
        # self.mock_client.search.side_effect = responses
        # OLD CODE END
        alerts = (
            alert_response if alert_response is not None else _empty_alert_response()
        )
        empty = {
            "hits": {"hits": []},
            "aggregations": {
                "top_hostname": {"buckets": []},
                "top_ua": {"buckets": []},
                "top_ja3": {"buckets": []},
            },
        }

        def _search(index=None, body=None, **_kwargs):
            aggs = (body or {}).get("aggs", {})
            if "all" in aggs:
                return device_response
            if "by_ip" in aggs:
                if isinstance(alerts, Exception):
                    raise alerts
                return alerts
            return _no_answers(body or {}) or empty

        self.mock_client.search.side_effect = _search

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
    async def test_failed_alert_count_is_502_not_zero_alerts(self):
        """#96: a failed alert-count query listed every device with 0 alerts."""
        from opensearchpy import OpenSearchException

        self._setup_search_responses(
            _device_list_response([_device_bucket("192.168.1.100")]),
            alert_response=OpenSearchException("timeout"),
        )

        resp = await self.client.request("GET", "/api/devices")
        self.assertEqual(resp.status, 502)
        self.assertIn("error", await resp.json())

    @unittest_run_loop
    async def test_device_list_requests_sent_and_received_sums(self):
        """The devices agg sums source.bytes (sent) and destination.bytes (received)."""
        self._setup_search_responses(_device_list_response([]))

        resp = await self.client.request("GET", "/api/devices")
        self.assertEqual(resp.status, 200)

        call_args = self.mock_client.search.call_args_list[0]
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        # OLD CODE START — slice 2b-3: the list's terms aggregation
        # sub_aggs = body["aggs"]["devices"]["aggs"]
        # OLD CODE END
        sub_aggs = body["aggs"]["all"]["aggs"]
        # OLD CODE START — NET-226: orig/resp sums; on the started side they are upload/download
        # self.assertEqual(sub_aggs["orig_bytes"], {"sum": {"field": "source.bytes"}})
        # self.assertEqual(
        #     sub_aggs["resp_bytes"], {"sum": {"field": "destination.bytes"}}
        # )
        # OLD CODE END
        self.assertEqual(
            sub_aggs["upload"], {"sum": {"field": "source.bytes", "missing": 0}}
        )
        self.assertEqual(
            sub_aggs["download"],
            {"sum": {"field": "destination.bytes", "missing": 0}},
        )

    @unittest_run_loop
    async def test_device_list_returns_sent_and_received_bytes(self):
        """Upload/download map through exactly; missing or null sums become 0."""
        missing = _device_bucket("192.168.1.101")
        # OLD CODE START — NET-226: orig/resp are upload/download now
        # del missing["orig_bytes"]
        # del missing["resp_bytes"]
        # OLD CODE END
        del missing["upload"]
        del missing["download"]
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

        # OLD CODE START — NET-226: orig/resp are upload/download now
        # self.assertEqual(devices["192.168.1.100"]["orig_bytes"], 1200)
        # self.assertEqual(devices["192.168.1.100"]["resp_bytes"], 98000)
        # for ip in ("192.168.1.101", "192.168.1.102"):
        #     self.assertEqual(devices[ip]["orig_bytes"], 0)
        #     self.assertEqual(devices[ip]["resp_bytes"], 0)
        # OLD CODE END
        self.assertEqual(devices["192.168.1.100"]["upload_bytes"], 1200)
        self.assertEqual(devices["192.168.1.100"]["download_bytes"], 98000)
        self.assertEqual(devices["192.168.1.100"]["total_bytes"], 99200)
        self.assertEqual(devices["192.168.1.101"]["upload_bytes"], 0)
        self.assertEqual(devices["192.168.1.101"]["download_bytes"], 0)
        # sums present but null
        self.assertEqual(devices["192.168.1.102"]["download_bytes"], 0)

    # OLD CODE START — slice 2b-3: these checked the terms aggregation's `order`; every sort is
    # ranked in Python over every device now, so the tests check the listed order instead
    # async def test_device_list_sort_by_connections(self):
    #     ... terms = body["aggs"]["devices"]["terms"]
    #     self.assertEqual(terms["order"], {"_count": "asc"})
    # async def test_device_list_sort_by_last_seen(self):
    #     ... self.assertEqual(terms["order"], {"last_seen": "desc"})
    # async def test_device_list_invalid_sort_falls_back(self):
    #     ... self.assertEqual(terms["order"], {"total_bytes": "desc"})
    # OLD CODE END
    async def _order(self, query, buckets):
        self._setup_search_responses(_device_list_response(buckets))
        resp = await self.client.request("GET", "/api/devices" + query)
        self.assertEqual(resp.status, 200)
        return [d["ip"] for d in (await resp.json())["devices"]]

    @unittest_run_loop
    async def test_device_list_sort_by_connections(self):
        """Sort=connections&order=asc lists the fewest records first."""
        listed = await self._order(
            "?sort=connections&order=asc",
            [
                _device_bucket("192.168.1.1", doc_count=50),
                _device_bucket("192.168.1.2", doc_count=5),
                _device_bucket("192.168.1.3", doc_count=20),
            ],
        )
        self.assertEqual(listed, ["192.168.1.2", "192.168.1.3", "192.168.1.1"])

    @unittest_run_loop
    async def test_device_list_sort_by_last_seen(self):
        """Sort=last_seen lists the newest record first."""
        newest = {**_device_bucket("192.168.1.1"), "last_seen": {"value": 3_000}}
        oldest = {**_device_bucket("192.168.1.2"), "last_seen": {"value": 1_000}}
        middle = {**_device_bucket("192.168.1.3"), "last_seen": {"value": 2_000}}
        listed = await self._order("?sort=last_seen", [oldest, newest, middle])
        self.assertEqual(listed, ["192.168.1.1", "192.168.1.3", "192.168.1.2"])

    @unittest_run_loop
    async def test_device_list_invalid_sort_falls_back(self):
        """Invalid sort field falls back to bytes, largest first."""
        listed = await self._order(
            "?sort=invalid_field",
            [
                _device_bucket("192.168.1.1", total_bytes=10),
                _device_bucket("192.168.1.2", total_bytes=30),
                _device_bucket("192.168.1.3", total_bytes=20),
            ],
        )
        self.assertEqual(listed, ["192.168.1.2", "192.168.1.3", "192.168.1.1"])

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
                    "ips": {"buckets": [{"key": "192.168.1.100", "doc_count": 5}]}
                },
                "by_dst": {"ips": {"buckets": []}},
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
        self.assertIn(
            {"prefix": {"rule.name": "SURICATA "}},
            bodies[0]["query"]["bool"]["must_not"],
        )

    @unittest_run_loop
    async def test_device_list_counts_alerts_on_traffic_to_the_device(self):
        """An alert on traffic to a device counts, as on its detail page (D4)."""
        alert_response = {
            "aggregations": {
                "by_ip": {
                    "ips": {"buckets": [{"key": "192.168.1.100", "doc_count": 2}]}
                },
                "by_dst": {
                    "ips": {
                        "buckets": [
                            {"key": "192.168.1.100", "doc_count": 3},
                            {"key": "192.168.1.101", "doc_count": 4},
                        ]
                    }
                },
            }
        }
        self._setup_search_responses(
            _device_list_response(
                [_device_bucket("192.168.1.100"), _device_bucket("192.168.1.101")]
            ),
            alert_response=alert_response,
        )

        resp = await self.client.request("GET", "/api/devices")
        data = await resp.json()
        counts = {d["ip"]: d["alert_count"] for d in data["devices"]}
        self.assertEqual(counts, {"192.168.1.100": 5, "192.168.1.101": 4})
        # One query asks for both sides, each side bucketed only within this chunk
        (body,) = _alert_bodies(self.mock_client.search)
        either = {
            "bool": {
                "should": [
                    {"terms": {"source.ip": ["192.168.1.100", "192.168.1.101"]}},
                    {"terms": {"destination.ip": ["192.168.1.100", "192.168.1.101"]}},
                ],
                "minimum_should_match": 1,
            }
        }
        self.assertIn(either, body["query"]["bool"]["filter"])
        self.assertEqual(
            body["aggs"]["by_dst"]["filter"],
            {"terms": {"destination.ip": ["192.168.1.100", "192.168.1.101"]}},
        )


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

        # OLD CODE START — NET-226: the detail now also asks who owns the device's IPv6 first
        # self.mock_client.search.side_effect = responses
        # OLD CODE END
        self.mock_client.search.side_effect = _answering(responses)
        return responses

    @unittest_run_loop
    async def test_device_detail_success(self):
        """Returns full device detail with aggregations."""
        self._setup_detail_responses(
            {
                "hits": {"total": {"value": 500}},
                # NET-226: both IP byte counts, and the started side's breakdowns
                "aggregations": {
                    "src": {"value": 1000000},
                    "dst": {"value": 500000},
                    "started": {
                        "protocols": {"buckets": [{"key": "tcp", "doc_count": 400}]},
                        "first_seen": {"value_as_string": "2026-02-25T00:00:00.000Z"},
                        "last_seen": {"value_as_string": "2026-02-25T23:59:59.000Z"},
                        "top_destinations": {
                            "buckets": [
                                {
                                    "key": "8.8.8.8",
                                    "doc_count": 50,
                                    "src": {"value": 200000},
                                },
                                {
                                    "key": "1.1.1.1",
                                    "doc_count": 30,
                                    "src": {"value": 100000},
                                },
                            ]
                        },
                    },
                    "bandwidth_series": {
                        "buckets": [
                            {
                                "key_as_string": "2026-02-25T00:00:00.000Z",
                                "doc_count": 10,
                                "src": {"value": 5000},
                            },
                            {
                                "key_as_string": "2026-02-25T00:05:00.000Z",
                                "doc_count": 15,
                                "src": {"value": 7000},
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
                "src": {"value": 5000},
                "started": {
                    "protocols": {"buckets": []},
                    "first_seen": {"value_as_string": "2026-02-25T12:00:00.000Z"},
                    "last_seen": {"value_as_string": "2026-02-25T12:30:00.000Z"},
                    "top_destinations": {"buckets": []},
                },
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

        self.mock_client.search.side_effect = _answering(responses)

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
        self.assertIn(
            {"prefix": {"rule.name": "SURICATA "}},
            alert_bodies[0]["query"]["bool"]["must_not"],
        )  # (#60)
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
                    "src": {"value": 0},
                    "started": {
                        "protocols": {"buckets": []},
                        "first_seen": {"value_as_string": ""},
                        "last_seen": {"value_as_string": ""},
                        "top_destinations": {"buckets": []},
                    },
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
    async def test_an_internet_address_is_not_a_device(self):
        """NET-209: an internet scanner opened as a device page (Ubiquiti, Windows, risk 58).

        The 404 comes before any search or fingerprint, so nothing about it is looked up.
        """
        with patch("api.devices._get_fingerprint") as fingerprint:
            resp = await self.client.request("GET", "/api/devices/91.92.40.12")
            self.assertEqual(resp.status, 404)
            self.assertEqual(
                await resp.json(), {"error": "91.92.40.12 is not on your network"}
            )
        self.mock_client.search.assert_not_called()
        fingerprint.assert_not_called()

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

    @unittest_run_loop
    async def test_failed_dns_or_alert_lookup_is_502_not_none(self):
        """#96: a failed DNS or alert lookup showed no DNS queries or 0 alerts."""
        from opensearchpy import OpenSearchException

        conn = {
            "hits": {"total": {"value": 5}},
            "aggregations": {"src": {"value": 100}},
        }
        for failing in ("dns", "alerts"):
            responses = self._setup_detail_responses(conn)
            responses[1 if failing == "dns" else 2] = OpenSearchException("timeout")
            self.mock_client.search.side_effect = _answering(responses)

            resp = await self.client.request("GET", "/api/devices/192.168.1.1")
            self.assertEqual(resp.status, 502, failing)
            self.assertIn("error", await resp.json())


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
    async def test_connections_sort_by_any_column(self):
        """#140: Recent Connections were always newest first; each column sorts server-side."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }
        expected = {
            "time": [{"@timestamp": {"order": "asc"}}],
            "duration": [
                {"length": {"order": "asc", "missing": "_last"}},
                {"@timestamp": {"order": "desc"}},
            ],
            "destination": [
                {"destination.ip": {"order": "asc", "missing": "_last"}},
                {"destination.port": {"order": "asc", "missing": "_last"}},
                {"@timestamp": {"order": "desc"}},
            ],
        }
        for key, sort in expected.items():
            resp = await self.client.request(
                "GET", f"/api/devices/192.168.1.100/connections?sort={key}&order=asc"
            )
            self.assertEqual(resp.status, 200)
            body = self.mock_client.search.call_args.kwargs["body"]
            self.assertEqual(body["sort"], sort)

    @unittest_run_loop
    async def test_connections_default_sort_is_newest_first(self):
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }
        resp = await self.client.request(
            "GET", "/api/devices/192.168.1.100/connections"
        )
        self.assertEqual(resp.status, 200)
        body = self.mock_client.search.call_args.kwargs["body"]
        self.assertEqual(body["sort"], [{"@timestamp": {"order": "desc"}}])

    @unittest_run_loop
    async def test_connections_unknown_sort_is_refused(self):
        for query in ("sort=_id", "sort=time&order=sideways"):
            resp = await self.client.request(
                "GET", f"/api/devices/192.168.1.100/connections?{query}"
            )
            self.assertEqual(resp.status, 400)
        self.mock_client.search.assert_not_called()

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
    async def test_rows_carry_the_direction_from_the_device_side(self):
        """NET-158: inbound rows showed the device's upload as DL; each row says which way."""
        self.mock_client.search.return_value = {
            "hits": {
                "total": {"value": 2},
                "hits": [
                    {
                        "_id": "out",
                        "_source": {
                            "source": {"ip": "192.168.1.100"},
                            "destination": {"ip": "8.8.8.8"},
                        },
                    },
                    {
                        "_id": "in",
                        "_source": {
                            "source": {"ip": "192.168.1.7"},
                            "destination": {"ip": "192.168.1.100"},
                        },
                    },
                ],
            }
        }
        resp = await self.client.request(
            "GET", "/api/devices/192.168.1.100/connections"
        )
        rows = (await resp.json())["connections"]
        self.assertEqual(
            [(r["_id"], r["direction"]) for r in rows], [("out", "out"), ("in", "in")]
        )

    @unittest_run_loop
    async def test_dl_ul_and_direction_sort_on_the_device_side_on_every_page(self):
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }
        for key, picks in (
            ("dl", "'destination.bytes' : 'source.bytes'"),
            ("ul", "'source.bytes' : 'destination.bytes'"),
            ("direction", "? 1 : 0"),
        ):
            resp = await self.client.request(
                "GET",
                f"/api/devices/192.168.1.100/connections?sort={key}&order=desc&page=2&size=25",
            )
            self.assertEqual(resp.status, 200)
            body = self.mock_client.search.call_args.kwargs["body"]
            script = body["sort"][0]["_script"]
            self.assertEqual(script["order"], "desc")
            self.assertEqual(script["script"]["params"], {"ip": "192.168.1.100"})
            self.assertIn(picks, script["script"]["source"])
            self.assertEqual(body["sort"][1], {"@timestamp": {"order": "desc"}})
            self.assertEqual(body["from"], 25)

    def test_the_connections_page_keeps_source_destination_sorts(self):
        from api.devices import _connection_sort

        self.assertEqual(
            _connection_sort("dl", "asc")[0],
            {"destination.bytes": {"order": "asc", "missing": "_last"}},
        )

    @unittest_run_loop
    async def test_protocol_filter_reaches_the_query(self):
        """NET-158: the filter hid rows of one page; the total and pager counted every protocol."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }
        await self.client.request(
            "GET", "/api/devices/192.168.1.100/connections?proto=udp"
        )
        body = self.mock_client.search.call_args.kwargs["body"]
        self.assertIn(
            {"term": {"network.transport": "udp"}}, body["query"]["bool"]["filter"]
        )

        self.mock_client.search.reset_mock()
        resp = await self.client.request(
            "GET", "/api/devices/192.168.1.100/connections?proto=gre"
        )
        self.assertEqual(resp.status, 400)
        self.mock_client.search.assert_not_called()

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


def _composite_page(buckets, composite):
    """One page of a composite aggregation over terms-style `buckets` keyed by IP, in key order."""
    after = (composite.get("after") or {}).get("ip")
    rest = [
        b
        for b in sorted(buckets, key=lambda b: b["key"])
        if after is None or b["key"] > after
    ]
    page = [{**b, "key": {"ip": b["key"]}} for b in rest[: composite["size"]]]
    return {
        "aggregations": {
            "all": {"buckets": page, **({"after_key": page[-1]["key"]} if page else {})}
        }
    }


def _route_device_searches(device_response, alerts=None):
    """search() side effect: like OpenSearch, the device terms agg gets the top `size` buckets
    with min_doc_count, a composite every bucket page by page, the alert count `alerts`
    ({ip: count}) for the IPs asked; the rest empty."""
    buckets = device_response["aggregations"]["devices"]["buckets"]

    def _search(index=None, body=None, **_kwargs):
        aggs = (body or {}).get("aggs", {})
        if "by_ip" in aggs and alerts:
            asked = aggs["by_ip"]["filter"]["terms"]["source.ip"]
            hits = [
                {"key": ip, "doc_count": n} for ip, n in alerts.items() if ip in asked
            ]
            return {
                "aggregations": {
                    "by_ip": {"ips": {"buckets": hits}},
                    "by_dst": {"ips": {"buckets": []}},
                }
            }
        if "devices" in aggs:
            terms = aggs["devices"]["terms"]
            kept = [
                b for b in buckets if b["doc_count"] >= terms.get("min_doc_count", 1)
            ]
            return {"aggregations": {"devices": {"buckets": kept[: terms["size"]]}}}
        if "all" in aggs:
            return _composite_page(buckets, aggs["all"]["composite"])
        answers = _no_answers(body or {})  # NET-226: answered side, IPv6, IPv6 owner
        if answers:
            return answers
        return {
            "hits": {"hits": []},
            "aggregations": {
                "by_ip": {"ips": {"buckets": []}},
                "by_dst": {"ips": {"buckets": []}},
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
        # OLD CODE: self.assertIn({"term": {"event.dataset": "conn"}}, ...) (F1: final records only)
        self.assertIn(CONN_ACCOUNTING, bool_query["filter"])
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
        # OLD CODE START — #96: the count is a composite now and applies the threshold itself
        # for body in (list_body, count_body):
        #     terms = body["aggs"]["devices"]["terms"]
        #     self.assertEqual(terms["field"], "source.ip")
        #     self.assertEqual(terms["min_doc_count"], devices._MIN_CONNECTIONS)
        # OLD CODE END
        # OLD CODE START — slice 2b-3: the list was a terms aggregation with min_doc_count
        # terms = list_body["aggs"]["devices"]["terms"]
        # self.assertEqual(terms["field"], "source.ip")
        # self.assertEqual(terms["min_doc_count"], devices._MIN_CONNECTIONS)
        # OLD CODE END
        # Both are the same composite now; _lan_device_buckets applies the threshold to both
        for body in (list_body, count_body):
            sources = body["aggs"]["all"]["composite"]["sources"]
            self.assertEqual(sources, [{"ip": {"terms": {"field": "source.ip"}}}])

    @unittest_run_loop
    async def test_count_drops_ips_under_min_connections(self):
        buckets = [
            _device_bucket("192.168.1.10", doc_count=3),
            _device_bucket("192.168.1.11", doc_count=2),
        ]
        self.mock_client.search.side_effect = _route_device_searches(
            _device_list_response(buckets)
        )

        resp = await self.client.request("GET", "/api/devices/count" + self._RANGE)

        self.assertEqual((await resp.json())["count"], 1)

    @unittest_run_loop
    async def test_count_is_exact_past_500_devices(self):
        """#96: the count kept the top 500 IPs; 30 days of DHCP churn on a bigger network passes that."""
        buckets = [
            _device_bucket(f"192.168.{i // 200}.{i % 200 + 1}", doc_count=5)
            for i in range(1200)
        ]
        self.mock_client.search.side_effect = _route_device_searches(
            _device_list_response(buckets)
        )

        resp = await self.client.request("GET", "/api/devices/count" + self._RANGE)

        self.assertEqual(resp.status, 200)
        self.assertEqual((await resp.json())["count"], 1200)
        self.assertEqual(
            self.mock_client.search.call_count, 2
        )  # a full page of 1,000 and the short last one

    @unittest_run_loop
    async def test_active_since_counts_listed_devices_by_their_newest_record(self):
        """NET-158: "Online now" counted a 5-minute range (3 records in it); the table calls a
        listed device Online on its newest record, so the count now uses that rule."""

        def seen(ip, doc_count, at):
            ms = datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp() * 1000
            return {
                **_device_bucket(ip, doc_count=doc_count),
                "last_seen": {"value": ms, "value_as_string": at},
            }

        buckets = [
            seen(
                "192.168.1.10", 40, "2026-02-25T23:59:00Z"
            ),  # one record in the last 5 min
            seen("192.168.1.11", 40, "2026-02-25T23:50:00Z"),  # idle
            seen("192.168.1.12", 2, "2026-02-25T23:59:30Z"),  # not a listed device
        ]
        self.mock_client.search.side_effect = _route_device_searches(
            _device_list_response(buckets)
        )

        resp = await self.client.request(
            "GET",
            "/api/devices/count" + self._RANGE + "&active_since=2026-02-25T23:55:00Z",
        )

        self.assertEqual(resp.status, 200)
        self.assertEqual((await resp.json())["count"], 1)
        aggs = self._bodies()[0]["aggs"]["all"]["aggs"]
        self.assertEqual(aggs["last_seen"], {"max": {"field": "@timestamp"}})

    @unittest_run_loop
    async def test_unreadable_active_since_is_400(self):
        resp = await self.client.request(
            "GET", "/api/devices/count" + self._RANGE + "&active_since=now-5m"
        )
        self.assertEqual(resp.status, 400)


class TestDeviceListAlertSort(AioHTTPTestCase):
    """#96: sort=alerts ranks every device, not the top 2 x limit by bytes."""

    # Ten busy devices, then a quiet one with the most alerts
    BUCKETS = [
        *(
            _device_bucket(f"192.168.1.{i}", total_bytes=1_000_000 - i)
            for i in range(10, 20)
        ),
        _device_bucket("192.168.1.50", total_bytes=10),
    ]
    ALERTS = {"192.168.1.50": 7, "192.168.1.11": 2}

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_device_routes(app, self.storage)
        return app

    async def _listed(self, query):
        self.mock_client.search.side_effect = _route_device_searches(
            _device_list_response(self.BUCKETS), self.ALERTS
        )
        resp = await self.client.request("GET", "/api/devices" + query)
        self.assertEqual(resp.status, 200)
        return [(d["ip"], d["alert_count"]) for d in (await resp.json())["devices"]]

    @unittest_run_loop
    async def test_most_alerts_first_from_every_device(self):
        # The top 4 by bytes left 192.168.1.50 out
        listed = await self._listed("?sort=alerts&limit=2")
        self.assertEqual(listed, [("192.168.1.50", 7), ("192.168.1.11", 2)])

    @unittest_run_loop
    async def test_alert_counts_are_asked_in_chunks_of_ips(self):
        """Past index.max_terms_count (65,536) IPs one terms filter fails; chunks don't."""
        with patch("api.devices._ALERT_IP_CHUNK", 4):
            listed = await self._listed("?sort=alerts&limit=2")
        self.assertEqual(listed, [("192.168.1.50", 7), ("192.168.1.11", 2)])
        chunks = [
            b["aggs"]["by_ip"]["filter"]["terms"]["source.ip"]
            for b in _alert_bodies(self.mock_client.search)
        ]
        self.assertEqual([len(c) for c in chunks], [4, 4, 3])

    @unittest_run_loop
    async def test_fewest_alerts_first_bytes_breaks_ties(self):
        listed = await self._listed("?sort=alerts&order=asc&limit=2")
        self.assertEqual(listed, [("192.168.1.10", 0), ("192.168.1.12", 0)])


class TestDeviceListOneReading(AioHTTPTestCase):
    """Slice 2b-3: the Devices page's list, Total devices and Online now come from one reading,
    with the same devices as GET /api/devices/count."""

    _RANGE = "?from=2026-02-25T00:00:00Z&to=2026-02-26T00:00:00Z"

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_device_routes(app, self.storage)
        return app

    async def _get(self, path, buckets, alerts=None, search=None):
        self.mock_client.search.side_effect = search or _route_device_searches(
            _device_list_response(buckets), alerts
        )
        resp = await self.client.request("GET", path)
        return resp.status, await resp.json()

    @unittest_run_loop
    async def test_every_sort_lists_the_devices_the_count_counts(self):
        buckets = [
            _device_bucket("192.168.1.10", doc_count=40, total_bytes=500),
            _device_bucket("192.168.1.11", doc_count=3, total_bytes=900),  # exactly 3
            _device_bucket("192.168.1.12", doc_count=2, total_bytes=99_999),  # under 3
            _device_bucket("192.168.1.255", doc_count=50),  # broadcast, not a device
            _device_bucket("192.168.1.13", doc_count=7, total_bytes=100),
        ]
        _, counted = await self._get("/api/devices/count" + self._RANGE, buckets)
        for sort in ("bytes", "connections", "last_seen", "first_seen", "alerts"):
            for order in ("desc", "asc"):
                status, data = await self._get(
                    f"/api/devices{self._RANGE}&sort={sort}&order={order}", buckets
                )
                self.assertEqual(status, 200, sort)
                ips = {d["ip"] for d in data["devices"]}
                self.assertEqual(
                    ips, {"192.168.1.10", "192.168.1.11", "192.168.1.13"}, sort
                )
                self.assertEqual(data["total"], counted["count"], sort)

    @unittest_run_loop
    async def test_total_counts_every_device_across_pages_before_the_cut(self):
        buckets = [
            _device_bucket(f"192.168.{i // 200}.{i % 200 + 1}", doc_count=5)
            for i in range(1200)
        ]
        _, counted = await self._get("/api/devices/count" + self._RANGE, buckets)
        self.assertEqual(counted["count"], 1200)
        for sort in ("bytes", "connections", "last_seen", "first_seen", "alerts"):
            status, data = await self._get(
                f"/api/devices{self._RANGE}&limit=500&sort={sort}", buckets
            )
            self.assertEqual(status, 200, sort)
            self.assertEqual(len(data["devices"]), 500, sort)
            self.assertEqual(data["total"], 1200, sort)

    @unittest_run_loop
    async def test_online_total_counts_every_device_not_only_the_listed_ones(self):
        now_ms = 1_772_020_800_000
        seen = [
            {**_device_bucket(f"192.168.1.{i}"), "last_seen": {"value": float(now_ms)}}
            for i in (1, 2, 3)
        ]
        with patch("api.devices.time") as clock:
            clock.time_ns.return_value = now_ms * 1_000_000
            _, data = await self._get("/api/devices" + self._RANGE + "&limit=1", seen)
        self.assertEqual(len(data["devices"]), 1)
        self.assertEqual(data["online_total"], 3)

    @unittest_run_loop
    async def test_first_seen_sorts_by_the_first_record(self):
        def first(ip, ms):
            return {**_device_bucket(ip), "first_seen": {"value": float(ms)}}

        buckets = [
            first("192.168.1.1", 2_000),
            first("192.168.1.2", 3_000),
            first("192.168.1.3", 1_000),
        ]
        _, data = await self._get(
            "/api/devices" + self._RANGE + "&sort=first_seen&order=asc", buckets
        )
        self.assertEqual(
            [d["ip"] for d in data["devices"]],
            ["192.168.1.3", "192.168.1.1", "192.168.1.2"],
        )

    @unittest_run_loop
    async def test_a_skipped_address_never_takes_a_listed_slot(self):
        buckets = [
            _device_bucket("192.168.1.255", total_bytes=9_999_999),  # broadcast
            _device_bucket("192.168.1.7", total_bytes=10),
        ]
        _, data = await self._get("/api/devices" + self._RANGE + "&limit=1", buckets)
        self.assertEqual([d["ip"] for d in data["devices"]], ["192.168.1.7"])
        self.assertEqual(data["total"], 1)

    @unittest_run_loop
    async def test_ties_break_by_bytes_then_ip_in_numeric_order(self):
        buckets = [
            _device_bucket("192.168.1.10", doc_count=9, total_bytes=100),
            _device_bucket("192.168.1.9", doc_count=9, total_bytes=100),
            _device_bucket("192.168.1.2", doc_count=9, total_bytes=500),
        ]
        _, data = await self._get(
            "/api/devices" + self._RANGE + "&sort=connections", buckets
        )
        self.assertEqual(
            [d["ip"] for d in data["devices"]],
            ["192.168.1.2", "192.168.1.9", "192.168.1.10"],
        )

    @unittest_run_loop
    async def test_a_non_alert_sort_asks_alert_counts_for_the_listed_devices_only(self):
        buckets = [
            _device_bucket(f"192.168.1.{i}", total_bytes=i * 10) for i in range(1, 6)
        ]
        _, data = await self._get(
            "/api/devices" + self._RANGE + "&limit=2", buckets, {"192.168.1.5": 1}
        )
        self.assertEqual(
            [d["ip"] for d in data["devices"]], ["192.168.1.5", "192.168.1.4"]
        )
        (body,) = _alert_bodies(self.mock_client.search)
        self.assertEqual(
            body["aggs"]["by_ip"]["filter"]["terms"]["source.ip"],
            ["192.168.1.5", "192.168.1.4"],
        )

    @unittest_run_loop
    async def test_online_cutoff_is_whole_milliseconds_with_the_boundary_counted(self):
        # 2026-02-25T12:00:00.123456Z on the daemon's clock
        noon = datetime.fromisoformat("2026-02-25T12:00:00+00:00")
        now_ns = int(noon.timestamp()) * 10**9 + 123_456_000
        cutoff_ms = (now_ns // 1_000_000) - 5 * 60 * 1000

        def seen(ip, ms):
            return {**_device_bucket(ip), "last_seen": {"value": float(ms)}}

        buckets = [
            seen("192.168.1.10", cutoff_ms),  # exactly the cutoff: online
            seen("192.168.1.11", cutoff_ms - 1),  # a millisecond older: not
            seen("192.168.1.12", cutoff_ms + 60_000),
        ]
        with patch("api.devices.time") as clock:
            clock.time_ns.return_value = now_ns
            _, data = await self._get("/api/devices" + self._RANGE, buckets)
        self.assertEqual(data["as_of"], "2026-02-25T12:00:00.123Z")
        self.assertEqual(data["online_since"], "2026-02-25T11:55:00.123Z")
        self.assertEqual(data["online_total"], 2)
        self.assertEqual(data["total"], 3)

    async def _incomplete(self, path, bad_reply, stage):
        """search(): the device composite answers, then `stage` ('devices' or 'alerts') is bad."""
        good = _route_device_searches(
            _device_list_response([_device_bucket("192.168.1.10")])
        )

        def _search(index=None, body=None, **kw):
            aggs = (body or {}).get("aggs", {})
            if (stage == "devices" and "all" in aggs) or (
                stage == "alerts" and "by_ip" in aggs
            ):
                return bad_reply
            return good(index=index, body=body, **kw)

        return await self._get(path, [], search=_search)

    @unittest_run_loop
    async def test_an_incomplete_device_search_is_502_for_the_list_and_the_count(self):
        page = _device_list_response([_device_bucket("192.168.1.10")])
        for bad in (
            {**page, "timed_out": True},
            {**page, "_shards": {"total": 8, "failed": 1}},
            {"aggregations": {}},
        ):
            for path in ("/api/devices", "/api/devices/count"):
                status, data = await self._incomplete(
                    path + self._RANGE, bad, "devices"
                )
                self.assertEqual(status, 502, (path, bad))
                self.assertEqual(data, {"error": "The device search was incomplete"})

    @unittest_run_loop
    async def test_a_read_stopped_at_the_cap_is_502_not_a_smaller_figure(self):
        """PR #191 review: past the cap the list and count read a partial set as every device."""
        buckets = [
            _device_bucket(f"192.168.{i // 200}.{i % 200 + 1}", doc_count=5)
            for i in range(1200)
        ]
        with patch("api.devices._DEVICE_CAP", 1000):
            for path in ("/api/devices", "/api/devices/count"):
                status, data = await self._get(path + self._RANGE, buckets)
                self.assertEqual(status, 502, path)
                self.assertEqual(data, {"error": "The device search was incomplete"})

    @unittest_run_loop
    async def test_an_incomplete_alert_count_is_502_not_zero_alerts(self):
        whole = {
            "aggregations": {
                "by_ip": {"ips": {"buckets": []}},
                "by_dst": {"ips": {"buckets": []}},
            }
        }
        for bad in (
            {**whole, "timed_out": True},
            {**whole, "_shards": {"total": 8, "failed": 2}},
            {"aggregations": {"by_ip": {"ips": {"buckets": []}}}},
            {"aggregations": {"by_ip": {"ips": {"buckets": []}}, "by_dst": {}}},
        ):
            for sort in ("bytes", "alerts"):
                status, data = await self._incomplete(
                    f"/api/devices{self._RANGE}&sort={sort}", bad, "alerts"
                )
                self.assertEqual(status, 502, (sort, bad))
                self.assertEqual(data, {"error": "The device search was incomplete"})


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

    # OLD CODE START — 2026-11-02: an unreadable bound is now a 400, not the default window
    # @unittest_run_loop
    # async def test_invalid_time_range_falls_back(self):
    #     """Invalid time range parameters fall back to defaults."""
    #     self.mock_client.search.return_value = {
    #         "hits": {"total": {"value": 0}, "hits": []}
    #     }
    #
    #     resp = await self.client.request(
    #         "GET", "/api/devices/192.168.1.1/connections?from=bad-date&to=also-bad"
    #     )
    #     self.assertEqual(resp.status, 200)
    #     data = await resp.json()
    #     # Should have defaulted to valid ISO timestamps
    #     self.assertNotEqual(data["from"], "bad-date")
    #     self.assertNotEqual(data["to"], "also-bad")
    # OLD CODE END

    @unittest_run_loop
    async def test_invalid_time_range_is_rejected(self):
        """Unreadable from/to is a 400 and nothing is queried."""
        resp = await self.client.request(
            "GET", "/api/devices/192.168.1.1/connections?from=bad-date&to=also-bad"
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("from must be an ISO 8601 time", data["error"])
        self.mock_client.search.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class TestDeviceCategoryFallbacks:
    """#26: the vendor (and phone/computer hostnames) decide when OS and hostname hints don't."""

    def test_single_purpose_vendor(self):
        from api.devices import _device_category

        assert (
            _device_category(None, "001788483c07.local", "Philips Lighting (Hue)")
            == "iot"
        )
        assert _device_category(None, None, "Ubiquiti Inc") == "infrastructure"
        assert (
            _device_category(None, None, "Proxmox Server Solutions GmbH") == "computer"
        )
        assert (
            _device_category(None, None, "Apple, Inc.") == "unknown"
        )  # makes phones and computers
        assert (
            _device_category(None, None, "Arcadyan Corporation") == "unknown"
        )  # routers and TV Wi-Fi
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
        for host in (
            "nintendo-switch",
            "xbox-one",
            "PlayStation-5",
            "ps5-living",
            "Roku-Ultra",
            "LGwebOSTV",
        ):
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


class TestDeviceTotalsPast10000(AioHTTPTestCase):
    """#84: hits.total stops at 10,000 unless the query sets track_total_hits.

    On the G11 the router's detail page read 10,000 connections (the device list: 48,158) and
    192.168.1.202's alerts total read 10,000 (the device list: 15,360).
    """

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 48158}, "hits": []},
            "aggregations": {},
        }
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_device_routes(app, self.storage)
        return app

    def _bodies(self):
        return [
            c.kwargs.get("body") or c[1].get("body")
            for c in self.mock_client.search.call_args_list
        ]

    @unittest_run_loop
    async def test_detail_counts_connections_and_alerts_exactly(self):
        self.mock_client.search.side_effect = _answering(
            self.mock_client.search.return_value
        )
        resp = await self.client.request("GET", "/api/devices/192.168.1.1")
        self.assertEqual(resp.status, 200)
        self.assertIs(
            _detail_body(self.mock_client.search).get("track_total_hits"), True
        )
        alert_bodies = _alert_bodies(self.mock_client.search)
        self.assertTrue(alert_bodies)
        self.assertTrue(all(b.get("track_total_hits") is True for b in alert_bodies))

    @unittest_run_loop
    async def test_connections_total_is_exact(self):
        resp = await self.client.request("GET", "/api/devices/192.168.1.1/connections")
        self.assertEqual(resp.status, 200)
        self.assertIs(self._bodies()[0].get("track_total_hits"), True)
        self.assertEqual((await resp.json())["total"], 48158)

    @unittest_run_loop
    async def test_alerts_total_is_exact(self):
        resp = await self.client.request("GET", "/api/devices/192.168.1.202/alerts")
        self.assertEqual(resp.status, 200)
        self.assertIs(self._bodies()[0].get("track_total_hits"), True)

    @unittest_run_loop
    async def test_connections_pages_stop_at_the_result_window(self):
        """#85: OpenSearch returns nothing past 10,000 results, so page 201 of 50 was empty."""
        resp = await self.client.request(
            "GET", "/api/devices/192.168.1.1/connections?size=50"
        )
        data = await resp.json()
        self.assertEqual(data["total"], 48158)
        self.assertEqual(data["total_pages"], 200)


class TestDeviceTopServicesByBytes(AioHTTPTestCase):
    """#96: top_services took the 10 ASNs with the most connections, then sorted them by bytes."""

    # Eleven chatty ASNs with little data, and one video service with few, huge flows
    # NET-226: a service's bytes are both IP byte counts (src + dst), ordered by network.bytes
    ASNS = [
        *(
            {
                "key": f"AS{100 + i} Chatty {i}",
                "doc_count": 500 - i,
                "src": {"value": 1_000 + i},
                "order_bytes": {"value": 1_000 + i},
            }
            for i in range(11)
        ),
        {
            "key": "AS2906 Netflix Inc",
            "doc_count": 4,
            "src": {"value": 1_000},
            "dst": {"value": 8_999_999_000},
            "order_bytes": {"value": 9_000_000_000},
        },
    ]

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_device_routes(app, self.storage)
        return app

    def _search(self, index=None, body=None, **_kwargs):
        """The detail search answers top_services like OpenSearch: its order, its size."""
        answers = _no_answers(body or {})
        if answers:
            return answers
        # OLD CODE START — NET-226: top_services moved under the started side, ordered by order_bytes
        # terms = ((body or {}).get("aggs", {}).get("top_services") or {}).get("terms")
        # OLD CODE END
        started = ((body or {}).get("aggs", {}).get("started") or {}).get("aggs", {})
        terms = (started.get("top_services") or {}).get("terms")
        if not terms:
            return {"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}}
        by_bytes = terms.get("order") == {"order_bytes": "desc"}
        ranked = sorted(
            self.ASNS,
            key=lambda b: -(b["order_bytes"]["value"] if by_bytes else b["doc_count"]),
        )
        return {
            "hits": {"total": {"value": 6000}, "hits": []},
            "aggregations": {
                "started": {"top_services": {"buckets": ranked[: terms["size"]]}}
            },
        }

    @unittest_run_loop
    async def test_top_services_are_the_top_10_by_bytes(self):
        self.mock_client.search.side_effect = self._search

        resp = await self.client.request("GET", "/api/devices/192.168.1.44")

        services = (await resp.json())["device"]["top_services"]
        self.assertEqual(
            services[0],
            {"name": "Netflix Inc", "bytes": 9_000_000_000, "connections": 4},
        )
        self.assertEqual(len(services), 10)
        self.assertEqual(
            [s["name"] for s in services[1:]], [f"Chatty {i}" for i in range(10, 1, -1)]
        )


class TestDeviceBandwidthInterval(AioHTTPTestCase):
    """#87: Device detail's 7d/30d buttons now work; 30 days at 5 minutes was 8,640 buckets."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []},
            "aggregations": {},
        }
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_device_routes(app, self.storage)
        return app

    async def _interval(self, from_ts):
        self.mock_client.search.reset_mock()
        self.mock_client.search.side_effect = _answering(
            self.mock_client.search.return_value
        )
        resp = await self.client.request(
            "GET",
            "/api/devices/192.168.1.1",
            params={"from": from_ts, "to": "2026-11-02T00:00:00Z"},
        )
        self.assertEqual(resp.status, 200)
        body = _detail_body(self.mock_client.search)
        # OLD CODE START — #120: the series was a date_histogram
        # return body["aggs"]["bandwidth_series"]["date_histogram"]["fixed_interval"]
        # OLD CODE END
        first = body["aggs"]["bandwidth_series"]["date_range"]["ranges"][0]
        span = datetime.fromisoformat(
            first["to"].replace("Z", "+00:00")
        ) - datetime.fromisoformat(first["from"].replace("Z", "+00:00"))
        return {300: "5m", 3600: "1h", 10800: "3h"}[int(span.total_seconds())]

    @unittest_run_loop
    async def test_interval_scales_with_the_range(self):
        self.assertEqual(
            await self._interval("2026-11-01T00:00:00Z"), "5m"
        )  # 24 h: 288 points
        self.assertEqual(await self._interval("2026-10-26T00:00:00Z"), "1h")  # 7 d: 168
        self.assertEqual(
            await self._interval("2026-10-03T00:00:00Z"), "3h"
        )  # 30 d: 240


class TestDeviceTermsAreExact(AioHTTPTestCase):
    """#90: a terms top-N only counts exactly when each shard returns every term.

    On the G11 a device's top destinations, ports and DNS lookups read low (106 for 112),
    categories left out every ASN past the 200th (679 connections for 192.168.1.205), and
    unique destinations was a cardinality estimate (2,390 for 2,391).
    """

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        dests = [
            {
                "key": f"10.0.{i // 256}.{i % 256}",
                "doc_count": 100 - i % 90,
                "bytes": {"value": 10},
            }
            for i in range(25)
        ]
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 2000}, "hits": []},
            "aggregations": {
                "unique_destinations": {"value": 24},  # the estimate, one short
                "top_destinations": {"buckets": dests, "sum_other_doc_count": 0},
            },
        }
        # NET-226: the detail reads destinations under the started side
        self.mock_client.search.return_value["aggregations"]["started"] = (
            self.mock_client.search.return_value["aggregations"]
        )
        self.mock_client.search.side_effect = _answering(
            self.mock_client.search.return_value
        )
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_device_routes(app, self.storage)
        return app

    def _terms(self, body):
        found = {}

        def walk(aggs):
            for name, agg in (aggs or {}).items():
                if "terms" in agg:
                    found[name] = agg["terms"]
                walk(agg.get("aggs"))

        walk(body.get("aggs"))
        return found

    def _bodies(self):
        return [
            c.kwargs.get("body") or c[1].get("body")
            for c in self.mock_client.search.call_args_list
        ]

    @unittest_run_loop
    async def test_detail_counts_every_destination(self):
        resp = await self.client.request("GET", "/api/devices/192.168.1.44")
        device = (await resp.json())["device"]
        self.assertEqual(device["unique_destinations"], 25)
        self.assertEqual(len(device["top_destinations"]), 20)
        terms = self._terms(_detail_body(self.mock_client.search))
        self.assertGreaterEqual(terms["top_destinations"]["size"], 10_000)
        self.assertGreaterEqual(terms["top_services"]["shard_size"], 10_000)
        dns = [
            t
            for b in self._bodies()
            for n, t in self._terms(b).items()
            if n == "dns_queries"
        ]
        self.assertGreaterEqual(dns[0]["shard_size"], 10_000)

    @unittest_run_loop
    async def test_unique_destinations_falls_back_past_the_list(self):
        self.mock_client.search.return_value["aggregations"]["top_destinations"][
            "sum_other_doc_count"
        ] = 5
        resp = await self.client.request("GET", "/api/devices/192.168.1.44")
        self.assertEqual((await resp.json())["device"]["unique_destinations"], 24)

    @unittest_run_loop
    async def test_categories_and_ports_read_every_term(self):
        await self.client.request("GET", "/api/devices/192.168.1.205/categories")
        await self.client.request("GET", "/api/devices/192.168.1.205/ports")
        categories, ports = (self._terms(b) for b in self._bodies())
        self.assertGreaterEqual(categories["asn_breakdown"]["size"], 10_000)
        self.assertGreaterEqual(ports["top_ports"]["shard_size"], 10_000)


def _registry_with(devices: dict) -> DeviceRegistry:
    """A real DeviceRegistry whose index holds these {MAC: doc} devices."""
    client = MagicMock()
    client.indices.exists.return_value = True
    client.mget.side_effect = lambda index, body: {
        "docs": [
            {
                "_id": i,
                "found": i in devices,
                **({"_source": devices[i]} if i in devices else {}),
            }
            for i in body["ids"]
        ]
    }
    client.get.side_effect = lambda index, id: {"_source": devices[id]}
    return DeviceRegistry(client=client)


STUDIO = {
    "mac": "BC:89:C1:E1:8A:D6",
    "hostnames": ["EliasMacStudio"],
    "manufacturer": "Apple, Inc.",
    "enrichment_sources": {"dhcp": {"hostname": "EliasMacStudio"}},
}


class TestDeviceNamesMatchHome(AioHTTPTestCase):
    """#130: Devices named a Mac after another Mac's mDNS records; Home used the registry."""

    async def get_application(self):
        self.storage, self.mock_client = _make_mock_storage()
        app = web.Application()
        app["storage"] = self.storage
        app["device_registry"] = _registry_with({"BC:89:C1:E1:8A:D6": STUDIO})
        register_device_routes(app, self.storage)
        return app

    def _lookups(self, dns_name: str, mac: str = "bc:89:c1:e1:8a:d6") -> dict:
        dhcp = {"hits": {"hits": [{"_source": {"source": {"mac": mac}}}]}}
        dns = {"aggregations": {"top_hostname": {"buckets": [{"key": dns_name}]}}}
        return {"responses": [dhcp, {"aggregations": {}}, dns, {"aggregations": {}}]}

    @unittest_run_loop
    async def test_the_list_uses_the_registry_name_for_the_mac(self):
        self.mock_client.search.side_effect = _answering(
            [
                _device_list_response([_device_bucket("192.168.1.188")]),
                _empty_alert_response(),
            ]
            + [{"hits": {"hits": []}}] * 10
        )
        self.mock_client.msearch.return_value = self._lookups(
            "sarabouzeid-fgwk3p497k.local"
        )
        resp = await self.client.request("GET", "/api/devices")
        assert resp.status == 200
        (device,) = (await resp.json())["devices"]
        assert device["hostname"] == "EliasMacStudio"

    @unittest_run_loop
    async def test_a_device_the_registry_doesnt_know_keeps_its_dns_name(self):
        self.mock_client.search.side_effect = _answering(
            [
                _device_list_response([_device_bucket("192.168.1.60")]),
                _empty_alert_response(),
            ]
            + [{"hits": {"hits": []}}] * 10
        )
        self.mock_client.msearch.return_value = self._lookups(
            "nas.local", mac="00:11:32:aa:bb:cc"
        )
        resp = await self.client.request("GET", "/api/devices")
        (device,) = (await resp.json())["devices"]
        assert device["hostname"] == "nas.local"

    @unittest_run_loop
    async def test_device_detail_uses_the_registry_name_too(self):
        conn = {
            "hits": {"total": {"value": 10}},
            "aggregations": {
                "src": {"value": 5000},
                "started": {
                    "protocols": {"buckets": []},
                    "first_seen": {"value_as_string": "2026-02-25T12:00:00.000Z"},
                    "last_seen": {"value_as_string": "2026-02-25T12:30:00.000Z"},
                    "top_destinations": {"buckets": []},
                },
                "bandwidth_series": {"buckets": []},
            },
        }
        dhcp = {
            "hits": {"hits": [{"_source": {"source": {"mac": "bc:89:c1:e1:8a:d6"}}}]}
        }
        dns_name = {
            "aggregations": {
                "top_hostname": {"buckets": [{"key": "sarabouzeid-fgwk3p497k.local"}]}
            }
        }
        self.mock_client.search.side_effect = _answering(
            [
                conn,
                {"aggregations": {"dns_queries": {"buckets": []}}},
                {"hits": {"total": {"value": 0}}},
                dhcp,
                dns_name,
            ]
            + [{"hits": {"hits": []}}, {"aggregations": {}}] * 20
        )
        resp = await self.client.request("GET", "/api/devices/192.168.1.188")
        assert resp.status == 200
        assert (await resp.json())["device"]["hostname"] == "EliasMacStudio"
