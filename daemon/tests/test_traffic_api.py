"""
Tests for daemon/api/traffic.py

All tests use mocks -- no OpenSearch connection required.
Tests cover query building, response formatting, error handling, and edge cases.
"""

import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime

import sys
import os

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.traffic import (
    register_traffic_routes,
    _parse_time_range,
    _parse_int_param,
    _time_range_filter,
    NETWORK_INDEX,
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


def _protocols_reply(
    services=(),
    quic=0,
    ssl_only=0,
    unlabelled=0,
    icmp=0,
    one_way=0,
    **aggs,
):
    """A complete /api/traffic/protocols search reply; aggs overrides or adds aggregations."""
    return {
        "timed_out": False,
        "_shards": {"total": 1, "successful": 1, "failed": 0},
        "aggregations": {
            "by_proto": {"buckets": []},
            "by_service": {
                "buckets": [{"key": k, "doc_count": n} for k, n in services]
            },
            "encryption": {"doc_count": 0, "encrypted": {"doc_count": 0}},
            "dns_plain": {"doc_count": 0},
            "dns_over_tls": {"doc_count": 0},
            "quic": {"doc_count": quic},
            "ssl_only": {"doc_count": ssl_only},
            "unlabelled": {
                "doc_count": unlabelled,
                "icmp": {"doc_count": icmp},
                "one_way": {"doc_count": one_way},
            },
            **aggs,
        },
    }


class TestParseTimeRange(unittest.TestCase):
    """Tests for _parse_time_range helper."""

    def _make_request(self, params: dict) -> MagicMock:
        """Create a mock request with given query params."""
        mock_req = MagicMock()
        mock_req.query = params
        return mock_req

    def test_defaults_to_last_24h(self):
        """When no params given, defaults to a 24h range."""
        req = self._make_request({})
        from_ts, to_ts = _parse_time_range(req)
        # Both should be valid ISO timestamps
        from_dt = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
        to_dt = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
        self.assertAlmostEqual((to_dt - from_dt).total_seconds(), 24 * 3600, delta=5)

    def test_valid_params_preserved(self):
        """Valid ISO timestamps should be passed through."""
        req = self._make_request(
            {
                "from": "2026-02-25T00:00:00+00:00",
                "to": "2026-02-26T00:00:00+00:00",
            }
        )
        from_ts, to_ts = _parse_time_range(req)
        self.assertEqual(from_ts, "2026-02-25T00:00:00+00:00")
        self.assertEqual(to_ts, "2026-02-26T00:00:00+00:00")

    # OLD CODE START — 2026-11-02: an unreadable bound is now a 400, not the default window
    # def test_invalid_from_falls_back_to_default(self):
    #     """Invalid from param should fall back to default."""
    #     req = self._make_request(
    #         {"from": "not-a-date", "to": "2026-02-26T00:00:00+00:00"}
    #     )
    #     from_ts, to_ts = _parse_time_range(req)
    #     self.assertNotEqual(from_ts, "not-a-date")
    #     self.assertEqual(to_ts, "2026-02-26T00:00:00+00:00")
    #
    # def test_invalid_to_falls_back_to_default(self):
    #     """Invalid to param should fall back to default."""
    #     req = self._make_request({"from": "2026-02-25T00:00:00+00:00", "to": "garbage"})
    #     from_ts, to_ts = _parse_time_range(req)
    #     self.assertEqual(from_ts, "2026-02-25T00:00:00+00:00")
    #     self.assertNotEqual(to_ts, "garbage")
    # OLD CODE END

    def test_invalid_from_is_rejected(self):
        """An unreadable from is a 400, not the last 24 hours."""
        req = self._make_request(
            {"from": "not-a-date", "to": "2026-02-26T00:00:00+00:00"}
        )
        with self.assertRaises(web.HTTPBadRequest) as ctx:
            _parse_time_range(req)
        self.assertIn("from must be an ISO 8601 time", ctx.exception.text)

    def test_invalid_to_is_rejected(self):
        """An unreadable to is a 400, not now."""
        req = self._make_request({"from": "2026-02-25T00:00:00+00:00", "to": "garbage"})
        with self.assertRaises(web.HTTPBadRequest) as ctx:
            _parse_time_range(req)
        self.assertIn("to must be an ISO 8601 time", ctx.exception.text)


class TestParseIntParam(unittest.TestCase):
    """Tests for _parse_int_param helper."""

    def test_valid_int(self):
        req = MagicMock()
        req.query = {"limit": "15"}
        self.assertEqual(_parse_int_param(req, "limit", 20), 15)

    def test_missing_returns_default(self):
        req = MagicMock()
        req.query = {}
        self.assertEqual(_parse_int_param(req, "limit", 20), 20)

    def test_invalid_returns_default(self):
        req = MagicMock()
        req.query = {"limit": "abc"}
        self.assertEqual(_parse_int_param(req, "limit", 20), 20)

    def test_zero_returns_one(self):
        """Zero or negative should be clamped to 1."""
        req = MagicMock()
        req.query = {"limit": "0"}
        self.assertEqual(_parse_int_param(req, "limit", 20), 1)


class TestTimeRangeFilter(unittest.TestCase):
    """Tests for _time_range_filter helper."""

    def test_builds_correct_range(self):
        result = _time_range_filter("2026-02-25T00:00:00Z", "2026-02-26T00:00:00Z")
        self.assertEqual(result["range"]["@timestamp"]["gte"], "2026-02-25T00:00:00Z")
        self.assertEqual(result["range"]["@timestamp"]["lte"], "2026-02-26T00:00:00Z")
        self.assertEqual(
            result["range"]["@timestamp"]["format"], "strict_date_optional_time"
        )


class TestTrafficSummaryHandler(AioHTTPTestCase):
    """Tests for GET /api/traffic/summary."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_traffic_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_summary_success(self):
        """Successful summary query returns aggregated data."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 1500}},
            "aggregations": {
                "total_orig_bytes": {"value": 1000000},
                "total_resp_bytes": {"value": 2000000},
                "total_orig_pkts": {"value": 5000},
                "total_resp_pkts": {"value": 8000},
                "top_protocol": {"buckets": [{"key": "tcp", "doc_count": 1200}]},
            },
        }

        resp = await self.client.request("GET", "/api/traffic/summary")
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertEqual(data["total_bytes"], 3000000)
        self.assertEqual(data["orig_bytes"], 1000000)
        self.assertEqual(data["resp_bytes"], 2000000)
        self.assertEqual(data["packet_count"], 13000)
        self.assertEqual(data["connection_count"], 1500)
        self.assertEqual(data["top_protocol"], "tcp")

        # Verify search was called with NETWORK_INDEX
        self.mock_client.search.assert_called_once()
        call_kwargs = self.mock_client.search.call_args
        self.assertEqual(
            call_kwargs.kwargs.get("index")
            or call_kwargs[1].get(
                "index", call_kwargs[0][0] if call_kwargs[0] else None
            ),
            NETWORK_INDEX,
        )

    @unittest_run_loop
    async def test_summary_with_time_params(self):
        """Time range params are forwarded to the query."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}},
            "aggregations": {
                "total_orig_bytes": {"value": 0},
                "total_resp_bytes": {"value": 0},
                "total_orig_pkts": {"value": 0},
                "total_resp_pkts": {"value": 0},
                "top_protocol": {"buckets": []},
            },
        }

        resp = await self.client.request(
            "GET",
            "/api/traffic/summary?from=2026-02-25T00:00:00Z&to=2026-02-26T00:00:00Z",
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["from"], "2026-02-25T00:00:00Z")
        self.assertEqual(data["to"], "2026-02-26T00:00:00Z")
        self.assertEqual(data["top_protocol"], "unknown")

    @unittest_run_loop
    async def test_summary_opensearch_error(self):
        """OpenSearch connection error returns 502."""
        from opensearchpy import ConnectionError as OSConnectionError

        self.mock_client.search.side_effect = OSConnectionError(
            "N/A", "Connection refused", Exception("refused")
        )

        resp = await self.client.request("GET", "/api/traffic/summary")
        self.assertEqual(resp.status, 502)
        data = await resp.json()
        self.assertIn("error", data)

    @unittest_run_loop
    async def test_summary_empty_results(self):
        """Empty results return zero counts."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}},
            "aggregations": {
                "total_orig_bytes": {"value": None},
                "total_resp_bytes": {"value": None},
                "total_orig_pkts": {"value": None},
                "total_resp_pkts": {"value": None},
                "top_protocol": {"buckets": []},
            },
        }

        resp = await self.client.request("GET", "/api/traffic/summary")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["total_bytes"], 0)
        self.assertEqual(data["packet_count"], 0)
        self.assertEqual(data["connection_count"], 0)
        self.assertEqual(data["top_protocol"], "unknown")


class TestTopTalkersHandler(AioHTTPTestCase):
    """Tests for GET /api/traffic/top-talkers."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_traffic_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_top_talkers_success(self):
        """Successful top talkers query returns IP list."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "top_sources": {
                    "buckets": [
                        {
                            "key": "192.168.1.100",
                            "doc_count": 500,
                            "total_bytes": {"value": 1500000},
                        },
                        {
                            "key": "192.168.1.101",
                            "doc_count": 300,
                            "total_bytes": {"value": 800000},
                        },
                    ]
                }
            }
        }

        resp = await self.client.request("GET", "/api/traffic/top-talkers?limit=5")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["limit"], 5)
        self.assertEqual(len(data["top_talkers"]), 2)
        self.assertEqual(data["top_talkers"][0]["ip"], "192.168.1.100")
        self.assertEqual(data["top_talkers"][0]["total_bytes"], 1500000)

    @unittest_run_loop
    async def test_top_talkers_empty(self):
        """Empty results return empty list."""
        self.mock_client.search.return_value = {
            "aggregations": {"top_sources": {"buckets": []}}
        }

        resp = await self.client.request("GET", "/api/traffic/top-talkers")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["top_talkers"], [])


class TestTopDestinationsHandler(AioHTTPTestCase):
    """Tests for GET /api/traffic/top-destinations."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_traffic_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_top_destinations_success(self):
        """Successful top destinations query returns IP list."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "top_destinations": {
                    "buckets": [
                        {
                            "key": "8.8.8.8",
                            "doc_count": 1000,
                            "total_bytes": {"value": 5000000},
                        },
                    ]
                }
            }
        }

        resp = await self.client.request(
            "GET", "/api/traffic/top-destinations?limit=10"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(len(data["top_destinations"]), 1)
        self.assertEqual(data["top_destinations"][0]["ip"], "8.8.8.8")


class TestProtocolsHandler(AioHTTPTestCase):
    """Tests for GET /api/traffic/protocols."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_traffic_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_protocols_success(self):
        """Returns protocol and service distribution."""
        self.mock_client.search.return_value = _protocols_reply(
            services=[("dns", 1500), ("http", 1000)],
            by_proto={
                "buckets": [
                    {"key": "tcp", "doc_count": 5000},
                    {"key": "udp", "doc_count": 2000},
                ]
            },
        )

        resp = await self.client.request("GET", "/api/traffic/protocols")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(len(data["protocols"]), 2)
        self.assertEqual(data["protocols"][0]["name"], "tcp")
        self.assertEqual(data["protocols"][0]["count"], 5000)
        self.assertEqual(len(data["services"]), 2)
        self.assertEqual(data["services"][0]["name"], "dns")

    @unittest_run_loop
    async def test_protocols_encryption_and_dns_use_the_iot_rule(self):
        """#86: Security Posture's cards used service names only: QUIC and unparsed TLS on 443
        counted as plaintext, pings and discovery sat in the denominator (G11: 19%), and DNS
        could never rise above 0% (Zeek has no dns_over_tls service; DoT is ssl on 853)."""
        from services.iot_monitor import ENCRYPTED_CONN_FILTER, LOCAL_CHATTER_EXCLUSION

        self.mock_client.search.return_value = _protocols_reply(
            encryption={"doc_count": 200, "encrypted": {"doc_count": 120}},
            dns_plain={"doc_count": 90},
            dns_over_tls={"doc_count": 10},
        )
        resp = await self.client.request("GET", "/api/traffic/protocols")
        data = await resp.json()
        self.assertEqual(data["encryption"], {"eligible": 200, "encrypted": 120})
        self.assertEqual(data["dns"], {"plain": 90, "over_tls": 10})

        aggs = self.mock_client.search.call_args.kwargs["body"]["aggs"]
        must_not = aggs["encryption"]["filter"]["bool"]["must_not"]
        for clause in LOCAL_CHATTER_EXCLUSION:
            self.assertIn(clause, must_not)
        self.assertIn({"terms": {"network.protocol": ["stun"]}}, must_not)
        self.assertEqual(
            aggs["encryption"]["aggs"]["encrypted"]["filter"], ENCRYPTED_CONN_FILTER
        )
        self.assertEqual(
            aggs["dns_over_tls"], {"filter": {"term": {"destination.port": 853}}}
        )


class TestProtocolsUnidentified(AioHTTPTestCase):
    """NET-219: Unidentified split by what was observed, and QUIC counted once."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_traffic_routes(app, self.storage)
        return app

    async def _get(self, reply):
        self.mock_client.search.return_value = reply
        resp = await self.client.request("GET", "/api/traffic/protocols")
        return resp.status, await resp.json()

    def _aggs(self):
        return self.mock_client.search.call_args.kwargs["body"]["aggs"]

    @unittest_run_loop
    async def test_the_unknown_count_is_split_and_the_remainder_is_conversations(self):
        status, data = await self._get(
            _protocols_reply(
                services=[("unknown", 999), ("dns", 50)],
                unlabelled=1000,
                icmp=100,
                one_way=700,
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            data["unidentified"], {"conversations": 200, "one_way": 700, "icmp": 100}
        )
        # services keeps its meaning (Compliance adds it up), with the exact count
        self.assertEqual(
            data["services"],
            [{"name": "unknown", "count": 1000}, {"name": "dns", "count": 50}],
        )

    @unittest_run_loop
    async def test_quic_and_ssl_take_the_exact_counts_and_the_list_is_resorted(self):
        # the ssl bucket counted QUIC too; quic fell outside the returned buckets
        _, data = await self._get(
            _protocols_reply(
                services=[("ssl", 900), ("dns", 400), ("http", 100)],
                quic=600,
                ssl_only=300,
            )
        )
        self.assertEqual(
            data["services"],
            [
                {"name": "quic", "count": 600},
                {"name": "dns", "count": 400},
                {"name": "ssl", "count": 300},
                {"name": "http", "count": 100},
            ],
        )

    @unittest_run_loop
    async def test_a_short_ssl_bucket_is_replaced_and_zero_entries_are_dropped(self):
        _, data = await self._get(
            _protocols_reply(
                services=[("ssl", 10), ("quic", 5), ("unknown", 3)],
                quic=40,
                ssl_only=0,
                unlabelled=0,
            )
        )
        self.assertEqual(data["services"], [{"name": "quic", "count": 40}])

    @unittest_run_loop
    async def test_incomplete_searches_are_502_never_zeros(self):
        timed_out = {**_protocols_reply(), "timed_out": True}
        shards = {**_protocols_reply(), "_shards": {"total": 2, "failed": 1}}
        missing = _protocols_reply()
        del missing["aggregations"]["unlabelled"]
        for reply in (timed_out, shards, missing):
            status, data = await self._get(reply)
            self.assertEqual(status, 502)
            self.assertEqual(data, {"error": "The protocol search was incomplete"})

    @unittest_run_loop
    async def test_the_query_has_the_exact_filters(self):
        await self._get(_protocols_reply())
        aggs = self._aggs()
        icmp = {"terms": {"network.transport": ["icmp", "icmp6", "ipv6-icmp"]}}
        self.assertEqual(
            aggs["quic"], {"filter": {"term": {"network.protocol": "quic"}}}
        )
        self.assertEqual(
            aggs["ssl_only"]["filter"]["bool"],
            {
                "filter": [{"term": {"network.protocol": "ssl"}}],
                "must_not": [{"term": {"network.protocol": "quic"}}],
            },
        )
        unlabelled = aggs["unlabelled"]
        self.assertEqual(
            unlabelled["filter"],
            {"bool": {"must_not": [{"exists": {"field": "network.protocol"}}]}},
        )
        self.assertEqual(unlabelled["aggs"]["icmp"], {"filter": icmp})
        # a conversation needs payload both ways; anything else that isn't ICMP is one way,
        # including a record with a counter missing (always one-sided on the G11)
        self.assertEqual(
            unlabelled["aggs"]["one_way"],
            {
                "filter": {
                    "bool": {
                        "must_not": [
                            icmp,
                            {
                                "bool": {
                                    "filter": [
                                        {"range": {"zeek.conn.orig_bytes": {"gt": 0}}},
                                        {"range": {"zeek.conn.resp_bytes": {"gt": 0}}},
                                    ]
                                }
                            },
                        ]
                    }
                }
            },
        )


class TestBandwidthHandler(AioHTTPTestCase):
    """Tests for GET /api/traffic/bandwidth."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_traffic_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_bandwidth_success(self):
        """Returns time-series bandwidth data."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "bandwidth_over_time": {
                    "buckets": [
                        {
                            "key": 1740441600000,
                            "key_as_string": "2026-02-25T00:00:00.000Z",
                            "doc_count": 100,
                            "orig_bytes": {"value": 50000},
                            "resp_bytes": {"value": 80000},
                        },
                        {
                            "key": 1740441900000,
                            "key_as_string": "2026-02-25T00:05:00.000Z",
                            "doc_count": 150,
                            "orig_bytes": {"value": 60000},
                            "resp_bytes": {"value": 90000},
                        },
                    ]
                }
            }
        }

        resp = await self.client.request("GET", "/api/traffic/bandwidth?interval=5m")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["interval"], "5m")
        self.assertEqual(len(data["series"]), 2)
        self.assertEqual(data["series"][0]["total_bytes"], 130000)
        self.assertEqual(data["series"][0]["connections"], 100)

    @unittest_run_loop
    async def test_bandwidth_invalid_interval(self):
        """Invalid interval falls back to 5m."""
        self.mock_client.search.return_value = {
            "aggregations": {"bandwidth_over_time": {"buckets": []}}
        }

        resp = await self.client.request("GET", "/api/traffic/bandwidth?interval=99x")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["interval"], "5m")


class TestConnectionsHandler(AioHTTPTestCase):
    """Tests for GET /api/traffic/connections."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_traffic_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_connections_success(self):
        """Returns paginated connection list."""
        self.mock_client.search.return_value = {
            "hits": {
                "total": {"value": 250},
                "hits": [
                    {
                        "_id": "doc1",
                        "_index": "zeek-conn-2026.02.25",
                        "_source": {
                            "@timestamp": "2026-02-25T12:00:00Z",
                            "network.transport": "tcp",
                            "source.ip": "192.168.1.100",
                            "destination.ip": "8.8.8.8",
                        },
                    },
                ],
            }
        }

        resp = await self.client.request(
            "GET", "/api/traffic/connections?page=1&size=50"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["total"], 250)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["size"], 50)
        self.assertEqual(data["total_pages"], 5)
        self.assertEqual(len(data["connections"]), 1)
        self.assertEqual(data["connections"][0]["_id"], "doc1")
        self.assertEqual(data["connections"][0]["network.transport"], "tcp")

    @unittest_run_loop
    async def test_connections_with_search(self):
        """Search query is forwarded to OpenSearch query_string."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }

        resp = await self.client.request("GET", "/api/traffic/connections?q=dns")
        self.assertEqual(resp.status, 200)

        # Verify the query_string was used
        call_args = self.mock_client.search.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        must = body["query"]["bool"]["must"]
        self.assertTrue(any("query_string" in clause for clause in must))

    @unittest_run_loop
    async def test_connections_total_counts_past_10000(self):
        """total and total_pages are shown; OpenSearch stops at 10,000 unless asked."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }
        resp = await self.client.request("GET", "/api/traffic/connections")
        self.assertEqual(resp.status, 200)
        body = self.mock_client.search.call_args.kwargs["body"]
        self.assertIs(body["track_total_hits"], True)

    @unittest_run_loop
    async def test_connections_pages_stop_at_the_result_window(self):
        """#85: OpenSearch returns nothing past 10,000 results, so later pages came back empty."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 600000}, "hits": []}
        }
        resp = await self.client.request("GET", "/api/traffic/connections?size=50")
        data = await resp.json()
        self.assertEqual(data["total"], 600000)
        self.assertEqual(data["total_pages"], 200)

    @unittest_run_loop
    async def test_connections_sort_and_state_reach_opensearch(self):
        """#145: the page sorted and filtered only the 50 rows it had; the query does both now."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }
        resp = await self.client.request(
            "GET", "/api/traffic/connections?sort=source&order=asc&state=rejected"
        )
        self.assertEqual(resp.status, 200)
        body = self.mock_client.search.call_args.kwargs["body"]
        self.assertEqual(
            body["sort"],
            [
                {"source.ip": {"order": "asc", "missing": "_last"}},
                {"source.port": {"order": "asc", "missing": "_last"}},
                {"@timestamp": {"order": "desc"}},
            ],
        )
        self.assertIn(
            {"terms": {"zeek.conn.conn_state": ["REJ", "RSTR", "RSTO"]}},
            body["query"]["bool"]["filter"],
        )

    @unittest_run_loop
    async def test_connections_default_is_newest_first_unfiltered(self):
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }
        await self.client.request("GET", "/api/traffic/connections")
        body = self.mock_client.search.call_args.kwargs["body"]
        self.assertEqual(body["sort"], [{"@timestamp": {"order": "desc"}}])
        self.assertFalse(any("terms" in f for f in body["query"]["bool"]["filter"]))

    @unittest_run_loop
    async def test_connections_refuses_unknown_sort_order_or_state(self):
        for query in ("sort=bogus", "order=up", "state=weird"):
            resp = await self.client.request("GET", f"/api/traffic/connections?{query}")
            self.assertEqual(resp.status, 400, query)
        self.mock_client.search.assert_not_called()

    @unittest_run_loop
    async def test_connections_size_capped(self):
        """Page size is capped at 200."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }

        resp = await self.client.request("GET", "/api/traffic/connections?size=500")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["size"], 200)

    @unittest_run_loop
    async def test_connections_opensearch_error(self):
        """OpenSearch error returns 502."""
        from opensearchpy import ConnectionError as OSConnectionError

        self.mock_client.search.side_effect = OSConnectionError(
            "N/A", "Connection refused", Exception("refused")
        )

        resp = await self.client.request("GET", "/api/traffic/connections")
        self.assertEqual(resp.status, 502)


class TestConnectionsIpFilter(AioHTTPTestCase):
    """NET-160: ?ip= is one address on either side, a structured filter apart from q."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_traffic_routes(app, self.storage)
        return app

    def _query(self) -> dict:
        return self.mock_client.search.call_args.kwargs["body"]["query"]

    @staticmethod
    def _record(**fields) -> dict:
        return {
            "@timestamp": "2026-11-05T10:00:00Z",
            "event.provider": "zeek",
            "event.dataset": "conn",
            **fields,
        }

    async def test_the_address_matches_either_side_and_no_other_field(self):
        from tests.fake_drill_opensearch import matches

        for sent, ip in (
            ("192.168.1.20", "192.168.1.20"),
            ("2001:DB8::1", "2001:db8::1"),  # IPv6, canonical
        ):
            resp = await self.client.get(
                "/api/traffic/connections?from=2026-11-05T00:00:00Z"
                f"&to=2026-11-05T12:00:00Z&ip={sent}"
            )
            self.assertEqual(resp.status, 200)
            query = self._query()
            self.assertTrue(matches(self._record(**{"source.ip": ip}), query))
            self.assertTrue(matches(self._record(**{"destination.ip": ip}), query))
            self.assertFalse(matches(self._record(**{"related.ip": ip}), query))
            self.assertFalse(matches(self._record(**{"source.ip": "10.9.9.9"}), query))
            self.assertEqual(query["bool"]["must"], [{"match_all": {}}])

    async def test_ip_combines_with_q_paging_and_sort(self):
        resp = await self.client.get(
            "/api/traffic/connections?ip=10.0.0.5&q=dns&page=2&size=10&sort=source&order=asc"
        )
        self.assertEqual(resp.status, 200)
        body = self.mock_client.search.call_args.kwargs["body"]
        self.assertEqual((body["from"], body["size"]), (10, 10))
        self.assertIn("query_string", body["query"]["bool"]["must"][0])
        self.assertNotIn(
            "10.0.0.5", body["query"]["bool"]["must"][0]["query_string"]["query"]
        )
        self.assertEqual(
            body["sort"][0], {"source.ip": {"order": "asc", "missing": "_last"}}
        )

    async def test_a_bad_address_is_a_400(self):
        for bad in ("not-an-ip", "10.0.0.0/8", "fe80::1%25eth0"):
            resp = await self.client.get(f"/api/traffic/connections?ip={bad}")
            self.assertEqual(resp.status, 400, bad)
        self.mock_client.search.assert_not_called()


class TestTopByBytesOrdering(AioHTTPTestCase):
    """Top-N-by-bytes aggs must rank buckets by bytes, not by doc count."""

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
        register_traffic_routes(app, self.storage)
        return app

    def _agg(self, name: str) -> dict:
        for call in self.mock_client.search.call_args_list:
            aggs = call.kwargs["body"].get("aggs", {})
            if name in aggs:
                return aggs[name]
        self.fail(f"no search built the {name!r} aggregation")

    @unittest_run_loop
    async def test_top_by_bytes_aggs_order_terms_by_total_bytes(self):
        cases = [
            ("/api/traffic/top-talkers", "top_sources"),
            ("/api/traffic/top-destinations", "top_destinations"),
            ("/api/traffic/connections/stats", "top_sources"),
            ("/api/traffic/connections/stats", "top_destinations"),
            ("/api/traffic/connections/sankey", "by_source"),
        ]
        for path, agg_name in cases:
            self.mock_client.search.reset_mock()
            resp = await self.client.request("GET", path)
            self.assertEqual(resp.status, 200, path)

            agg = self._agg(agg_name)
            self.assertEqual(agg["terms"].get("order"), {"total_bytes": "desc"}, path)
            self.assertIn("total_bytes", agg["aggs"], path)
            self.assertNotIn("bucket_sort", agg["aggs"], path)


def _byte_fields(aggs: dict) -> set[str]:
    """Collect every *.bytes field summed anywhere in an aggs tree."""
    found: set[str] = set()
    for value in aggs.values():
        if not isinstance(value, dict):
            continue
        field = value.get("sum", {}).get("field", "")
        if field.endswith(".bytes"):
            found.add(field)
        found |= _byte_fields(value.get("aggs", {}))
    return found


class TestBandwidthFiltersMatch(AioHTTPTestCase):
    """Summary, bandwidth series and /api/bandwidth/* must count the same bytes.

    On the G11 the monthly total (1.004 GB) and the 24 h summary (1.077 GB)
    disagreed with all data from the same day.
    """

    EXCLUDED = ["192.168.1.2"]

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
        app["excluded_ips"] = self.EXCLUDED
        register_traffic_routes(app, self.storage)
        return app

    async def _api_body(self, path: str) -> dict:
        self.mock_client.search.reset_mock()
        resp = await self.client.request("GET", path)
        self.assertEqual(resp.status, 200, path)
        return self.mock_client.search.call_args.kwargs["body"]

    def _tracker_bodies(self) -> list[dict]:
        from services.bandwidth_tracker import BandwidthTracker

        client = MagicMock()
        client.search.return_value = {"aggregations": {}}
        tracker = BandwidthTracker(client)
        tracker.get_monthly_usage(2026, 11, excluded_ips=self.EXCLUDED)
        tracker.get_daily_usage(
            "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z", excluded_ips=self.EXCLUDED
        )
        return [c.kwargs["body"] for c in client.search.call_args_list]

    @unittest_run_loop
    async def test_same_exclusions_and_byte_fields(self):
        bodies = {
            "summary": await self._api_body("/api/traffic/summary"),
            "series": await self._api_body("/api/traffic/bandwidth"),
        }
        monthly, daily = self._tracker_bodies()
        bodies["monthly"] = monthly
        bodies["daily"] = daily

        expected_must_not = [{"terms": {"source.ip": self.EXCLUDED}}]
        for name, body in bodies.items():
            self.assertEqual(
                body["query"]["bool"].get("must_not"), expected_must_not, name
            )
            self.assertEqual(
                _byte_fields(body["aggs"]),
                {"source.bytes", "destination.bytes"},
                name,
            )

    @unittest_run_loop
    async def test_protocol_counts_leave_out_what_the_connection_count_leaves_out(self):
        # Home's protocol total (516K) sat beside "Connections (24h)" (477K) on the G11
        summary = await self._api_body("/api/traffic/summary")
        self.mock_client.search.return_value = _protocols_reply()
        protocols = await self._api_body("/api/traffic/protocols")

        self.assertEqual(
            protocols["query"]["bool"].get("must_not"),
            summary["query"]["bool"]["must_not"],
        )


if __name__ == "__main__":
    unittest.main()
