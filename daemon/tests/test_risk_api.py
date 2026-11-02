"""
Tests for daemon/api/risk.py

All tests use mocks -- no OpenSearch or external dependencies required.
Tests cover the risk scoring API endpoints using AioHTTPTestCase.
"""

import unittest
from unittest.mock import MagicMock

import sys
import os

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.risk import register_risk_routes
from services.risk_scoring import RiskScorer


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
    storage = MagicMock()
    storage._client = MagicMock()
    return storage


def _make_conn_search_result(buckets=None, total=0):
    """Build a mock OpenSearch connection search result: the last page of the device composite."""
    if buckets is None:
        buckets = []
    return {
        "hits": {"total": {"value": total}},
        "aggregations": {
            # OLD CODE START — #96: the device list was a terms aggregation
            # "devices": {"buckets": buckets},
            # OLD CODE END
            "all": {"buckets": [{**b, "key": {"ip": b["key"]}} for b in buckets]},
            # OLD CODE START — replaced 2026-11-01: the handler no longer asks for conn_stats (it 400'd on _doc_count)
            # "conn_stats": {"count": len(buckets), "avg": 100.0, "std_deviation": 50.0},
            # OLD CODE END
        },
    }


def _make_device_bucket(
    ip, doc_count=100, orig_bytes=1000, resp_bytes=9000, ports=None
):
    """Build a device aggregation bucket for mock data."""
    port_buckets = [{"key": p} for p in (ports or [80, 443])]
    return {
        "key": ip,
        "doc_count": doc_count,
        "total_orig_bytes": {"value": orig_bytes},
        "total_resp_bytes": {"value": resp_bytes},
        "ports_used": {"buckets": port_buckets},
        "external_conns": {"doc_count": int(doc_count * 0.3)},
    }


def _make_alert_search_result(ip_counts=None):
    """Build a mock Suricata alert search result."""
    buckets = []
    if ip_counts:
        for ip, count in ip_counts.items():
            buckets.append({"key": ip, "doc_count": count})
    return {
        "hits": {"total": {"value": sum(c for c in (ip_counts or {}).values())}},
        "aggregations": {"by_ip": {"buckets": buckets}},
    }


def _make_single_conn_result(total=100, orig_bytes=1000, resp_bytes=9000, ports=None):
    """Build a mock OpenSearch result for a single-device query."""
    port_buckets = [{"key": p} for p in (ports or [80, 443])]
    return {
        "hits": {"total": {"value": total}},
        "aggregations": {
            "total_orig_bytes": {"value": orig_bytes},
            "total_resp_bytes": {"value": resp_bytes},
            "ports_used": {"buckets": port_buckets},
            "external_conns": {"doc_count": 30},
        },
    }


def _make_network_stats_result(buckets=None):
    """Build a mock network stats aggregation result."""
    if buckets is None:
        buckets = [
            {"key": "192.168.1.1", "doc_count": 100},
            {"key": "192.168.1.2", "doc_count": 200},
        ]
    return {
        "hits": {"total": {"value": 300}},
        # OLD CODE START — #96: the baseline was a terms aggregation
        # "aggregations": {"devices": {"buckets": buckets}},
        # OLD CODE END
        "aggregations": {"all": {"buckets": [{**b, "key": {"ip": b["key"]}} for b in buckets]}},
    }


def _make_single_alert_result(total=0):
    """Build a mock single-device alert count result."""
    return {
        "hits": {"total": {"value": total}},
    }


class TestRiskScoresEndpoint(AioHTTPTestCase):
    """Tests for GET /api/risk/scores."""

    def setUp(self):
        self.mock_storage = _make_mock_storage()
        self.risk_scorer = RiskScorer()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.mock_storage
        register_risk_routes(app, self.risk_scorer, self.mock_storage)
        return app

    @unittest_run_loop
    async def test_scores_empty_result(self):
        """GET /api/risk/scores with no data returns empty device list."""
        self.mock_storage._client.search.return_value = _make_conn_search_result()
        resp = await self.client.request("GET", "/api/risk/scores")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["device_count"], 0)
        self.assertEqual(data["devices"], [])

    @unittest_run_loop
    async def test_scores_with_devices(self):
        """GET /api/risk/scores returns scored devices."""
        buckets = [
            _make_device_bucket("192.168.1.10", doc_count=100),
            _make_device_bucket("192.168.1.20", doc_count=200),
        ]
        conn_result = _make_conn_search_result(buckets=buckets, total=300)
        alert_result = _make_alert_search_result({"192.168.1.10": 5})

        self.mock_storage._client.search.side_effect = [conn_result, alert_result]

        resp = await self.client.request("GET", "/api/risk/scores")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["device_count"], 2)
        self.assertIsInstance(data["devices"], list)
        # Devices should be sorted by score descending
        if len(data["devices"]) >= 2:
            self.assertGreaterEqual(
                data["devices"][0]["score"], data["devices"][1]["score"]
            )
        # Suricata engine events are sensor noise, not the device's alerts (#60)
        bodies = _alert_bodies(self.mock_storage._client.search)
        self.assertEqual(len(bodies), 1)
        self.assertIn({"prefix": {"rule.name": "SURICATA "}}, bodies[0]["query"]["bool"]["must_not"])

    @unittest_run_loop
    async def test_scores_contain_required_fields(self):
        """Response should contain from, to, device_count, devices."""
        self.mock_storage._client.search.return_value = _make_conn_search_result()
        resp = await self.client.request("GET", "/api/risk/scores")
        data = await resp.json()
        self.assertIn("from", data)
        self.assertIn("to", data)
        self.assertIn("device_count", data)
        self.assertIn("devices", data)
        self.assertIn("network_avg_connections", data)
        self.assertIn("network_stddev_connections", data)

    @unittest_run_loop
    async def test_scores_opensearch_error(self):
        """OpenSearch failure returns 502."""
        from opensearchpy import OpenSearchException

        self.mock_storage._client.search.side_effect = OpenSearchException("timeout")
        resp = await self.client.request("GET", "/api/risk/scores")
        self.assertEqual(resp.status, 502)
        data = await resp.json()
        self.assertIn("error", data)

    @unittest_run_loop
    async def test_scores_device_has_score_and_level(self):
        """Each device in the response should have score and level."""
        buckets = [_make_device_bucket("192.168.1.10")]
        conn_result = _make_conn_search_result(buckets=buckets, total=100)
        alert_result = _make_alert_search_result({})

        self.mock_storage._client.search.side_effect = [conn_result, alert_result]

        resp = await self.client.request("GET", "/api/risk/scores")
        data = await resp.json()
        self.assertEqual(data["device_count"], 1)
        device = data["devices"][0]
        self.assertIn("score", device)
        self.assertIn("level", device)
        self.assertIn("factors", device)
        self.assertIn("ip", device)

    @unittest_run_loop
    async def test_scores_with_limit_param(self):
        """The limit query parameter should be accepted."""
        self.mock_storage._client.search.return_value = _make_conn_search_result()
        resp = await self.client.request("GET", "/api/risk/scores?limit=10")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_scores_alert_query_failure_graceful(self):
        """If alert query fails, scoring should still succeed (0 alerts)."""
        from opensearchpy import OpenSearchException

        buckets = [_make_device_bucket("192.168.1.10")]
        conn_result = _make_conn_search_result(buckets=buckets, total=100)

        self.mock_storage._client.search.side_effect = [
            conn_result,
            OpenSearchException("alert index missing"),
        ]

        resp = await self.client.request("GET", "/api/risk/scores")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["device_count"], 1)

    @unittest_run_loop
    async def test_scores_query_never_aggregates_doc_count(self):
        """No aggregation may target _doc_count: OpenSearch rejects it with a 400."""
        self.mock_storage._client.search.return_value = _make_conn_search_result()
        resp = await self.client.request("GET", "/api/risk/scores")
        self.assertEqual(resp.status, 200)

        def fields(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "field":
                        yield value
                    yield from fields(value)
            elif isinstance(node, list):
                for item in node:
                    yield from fields(item)

        conn_query = self.mock_storage._client.search.call_args_list[0].kwargs["body"]
        self.assertNotIn("_doc_count", list(fields(conn_query["aggs"])))

    @unittest_run_loop
    async def test_scores_network_stats_from_buckets(self):
        """Mean and population stddev come from the per-device bucket counts."""
        buckets = [
            _make_device_bucket("192.168.1.10", doc_count=100),
            _make_device_bucket("192.168.1.20", doc_count=200),
            _make_device_bucket("192.168.1.30", doc_count=600),
        ]
        self.mock_storage._client.search.side_effect = [
            _make_conn_search_result(buckets=buckets, total=900),
            _make_alert_search_result({}),
        ]
        resp = await self.client.request("GET", "/api/risk/scores")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["network_avg_connections"], 300.0)
        # sqrt(((100-300)^2 + (200-300)^2 + (600-300)^2) / 3) = 216.02
        self.assertEqual(data["network_stddev_connections"], 216.02)


class TestRiskScoreSingleEndpoint(AioHTTPTestCase):
    """Tests for GET /api/risk/scores/{ip}."""

    def setUp(self):
        self.mock_storage = _make_mock_storage()
        self.risk_scorer = RiskScorer()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.mock_storage
        register_risk_routes(app, self.risk_scorer, self.mock_storage)
        return app

    @unittest_run_loop
    async def test_single_device_score(self):
        """GET /api/risk/scores/192.168.1.10 returns score for device."""
        conn_result = _make_single_conn_result(total=100)
        network_result = _make_network_stats_result()
        alert_result = _make_single_alert_result(total=3)

        self.mock_storage._client.search.side_effect = [
            conn_result,
            network_result,
            alert_result,
        ]

        resp = await self.client.request("GET", "/api/risk/scores/192.168.1.10")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["ip"], "192.168.1.10")
        self.assertIn("score", data)
        self.assertIn("level", data)
        self.assertIn("factors", data)
        bodies = _alert_bodies(self.mock_storage._client.search)
        self.assertEqual(len(bodies), 1)
        self.assertIn({"prefix": {"rule.name": "SURICATA "}}, bodies[0]["query"]["bool"]["must_not"])  # (#60)

    @unittest_run_loop
    async def test_single_device_not_found(self):
        """GET /api/risk/scores/{ip} returns 404 for unknown device."""
        conn_result = {
            "hits": {"total": {"value": 0}},
            "aggregations": {
                "total_orig_bytes": {"value": 0},
                "total_resp_bytes": {"value": 0},
                "ports_used": {"buckets": []},
                "external_conns": {"doc_count": 0},
            },
        }
        self.mock_storage._client.search.return_value = conn_result
        resp = await self.client.request("GET", "/api/risk/scores/10.0.0.99")
        self.assertEqual(resp.status, 404)

    @unittest_run_loop
    async def test_single_device_opensearch_error(self):
        """OpenSearch failure returns 502 for single device."""
        from opensearchpy import OpenSearchException

        self.mock_storage._client.search.side_effect = OpenSearchException("error")
        resp = await self.client.request("GET", "/api/risk/scores/192.168.1.10")
        self.assertEqual(resp.status, 502)

    @unittest_run_loop
    async def test_single_device_has_from_to(self):
        """Response should include from and to timestamps."""
        conn_result = _make_single_conn_result(total=100)
        network_result = _make_network_stats_result()
        alert_result = _make_single_alert_result(total=0)

        self.mock_storage._client.search.side_effect = [
            conn_result,
            network_result,
            alert_result,
        ]

        resp = await self.client.request("GET", "/api/risk/scores/192.168.1.10")
        data = await resp.json()
        self.assertIn("from", data)
        self.assertIn("to", data)

    @unittest_run_loop
    async def test_single_device_connection_count(self):
        """Response should include connection_count."""
        conn_result = _make_single_conn_result(total=150)
        network_result = _make_network_stats_result()
        alert_result = _make_single_alert_result(total=0)

        self.mock_storage._client.search.side_effect = [
            conn_result,
            network_result,
            alert_result,
        ]

        resp = await self.client.request("GET", "/api/risk/scores/192.168.1.10")
        data = await resp.json()
        self.assertEqual(data["connection_count"], 150)

    @unittest_run_loop
    async def test_single_device_alert_count_in_response(self):
        """Response should include the device's alert_count."""
        conn_result = _make_single_conn_result(total=100)
        network_result = _make_network_stats_result()
        alert_result = _make_single_alert_result(total=7)

        self.mock_storage._client.search.side_effect = [
            conn_result,
            network_result,
            alert_result,
        ]

        resp = await self.client.request("GET", "/api/risk/scores/192.168.1.10")
        data = await resp.json()
        self.assertEqual(data["alert_count"], 7)

    @unittest_run_loop
    async def test_single_device_factors_list(self):
        """Factors list should contain 5 entries."""
        conn_result = _make_single_conn_result(total=100)
        network_result = _make_network_stats_result()
        alert_result = _make_single_alert_result(total=0)

        self.mock_storage._client.search.side_effect = [
            conn_result,
            network_result,
            alert_result,
        ]

        resp = await self.client.request("GET", "/api/risk/scores/192.168.1.10")
        data = await resp.json()
        self.assertEqual(len(data["factors"]), 5)

    @unittest_run_loop
    async def test_single_device_network_query_failure_graceful(self):
        """If network stats query fails, scoring still works."""
        from opensearchpy import OpenSearchException

        conn_result = _make_single_conn_result(total=100)
        alert_result = _make_single_alert_result(total=0)

        self.mock_storage._client.search.side_effect = [
            conn_result,
            OpenSearchException("network query failed"),
            alert_result,
        ]

        resp = await self.client.request("GET", "/api/risk/scores/192.168.1.10")
        self.assertEqual(resp.status, 200)


class TestRiskQueryConsistency(AioHTTPTestCase):
    """Both endpoints read the same byte fields and score against the same population."""

    LAN_FILTER = {"term": {"network.direction": "lan-test-marker"}}
    RANGE = {"from": "2026-10-31T00:00:00Z", "to": "2026-11-01T00:00:00Z"}

    def setUp(self):
        self.mock_storage = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.mock_storage
        app["lan_filter"] = self.LAN_FILTER
        app["excluded_ips"] = ["192.168.1.1"]
        register_risk_routes(app, RiskScorer(), self.mock_storage)
        return app

    def _bodies(self):
        return [
            c.kwargs["body"] for c in self.mock_storage._client.search.call_args_list
        ]

    def _assert_zeek_byte_fields(self, aggs):
        # Arkime's client/server.bytes are inflated; traffic.py uses these instead
        self.assertEqual(
            aggs["total_orig_bytes"], {"sum": {"field": "source.bytes", "missing": 0}}
        )
        self.assertEqual(
            aggs["total_resp_bytes"],
            {"sum": {"field": "destination.bytes", "missing": 0}},
        )

    @unittest_run_loop
    async def test_list_endpoint_byte_fields(self):
        self.mock_storage._client.search.return_value = _make_conn_search_result()
        resp = await self.client.request("GET", "/api/risk/scores")
        self.assertEqual(resp.status, 200)
        # OLD CODE START — #96: the device list was a terms aggregation
        # self._assert_zeek_byte_fields(self._bodies()[0]["aggs"]["devices"]["aggs"])
        # OLD CODE END
        self._assert_zeek_byte_fields(self._bodies()[0]["aggs"]["all"]["aggs"])

    @unittest_run_loop
    async def test_single_endpoint_byte_fields(self):
        self.mock_storage._client.search.side_effect = [
            _make_single_conn_result(total=100),
            _make_network_stats_result(),
            _make_single_alert_result(total=0),
        ]
        resp = await self.client.request("GET", "/api/risk/scores/192.168.1.10")
        self.assertEqual(resp.status, 200)
        self._assert_zeek_byte_fields(self._bodies()[0]["aggs"])

    @unittest_run_loop
    async def test_single_baseline_matches_list_population(self):
        self.mock_storage._client.search.return_value = _make_conn_search_result()
        await self.client.request("GET", "/api/risk/scores", params=self.RANGE)
        list_bool = self._bodies()[0]["query"]["bool"]

        self.mock_storage._client.search.reset_mock(return_value=True)
        self.mock_storage._client.search.side_effect = [
            _make_single_conn_result(total=100),
            _make_network_stats_result(),
            _make_single_alert_result(total=0),
        ]
        resp = await self.client.request(
            "GET", "/api/risk/scores/192.168.1.10", params=self.RANGE
        )
        self.assertEqual(resp.status, 200)
        baseline_bool = self._bodies()[1]["query"]["bool"]

        self.assertIn(self.LAN_FILTER, baseline_bool["filter"])
        self.assertEqual(
            baseline_bool["must_not"], [{"terms": {"source.ip": ["192.168.1.1"]}}]
        )
        self.assertEqual(baseline_bool, list_bool)


    @unittest_run_loop
    async def test_single_counts_past_10000(self):
        """#83: without track_total_hits, hits.total stops at 10,000 (busy devices read 10,000)."""
        self.mock_storage._client.search.side_effect = [
            _make_single_conn_result(total=34401),
            _make_network_stats_result(),
            _make_single_alert_result(total=0),
        ]
        resp = await self.client.request("GET", "/api/risk/scores/192.168.1.188")
        self.assertEqual(resp.status, 200)
        conn_body, _, alert_body = self._bodies()
        self.assertIs(conn_body.get("track_total_hits"), True)
        self.assertIs(alert_body.get("track_total_hits"), True)

    @unittest_run_loop
    async def test_list_baseline_covers_more_devices_than_it_lists(self):
        """#83: the list's baseline came from the top `limit` devices; the single view's from 500."""
        buckets = [
            _make_device_bucket("192.168.1.10", doc_count=600),
            _make_device_bucket("192.168.1.20", doc_count=200),
            _make_device_bucket("192.168.1.30", doc_count=100),
        ]
        self.mock_storage._client.search.side_effect = [
            _make_conn_search_result(buckets=buckets, total=900),
            _make_alert_search_result({}),
        ]
        resp = await self.client.request("GET", "/api/risk/scores?limit=1")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual([d["ip"] for d in data["devices"]], ["192.168.1.10"])
        self.assertEqual(data["network_avg_connections"], 300.0)
        # OLD CODE START — #96: the baseline is every device now, not a terms list of 500
        # self.assertEqual(self._bodies()[0]["aggs"]["devices"]["terms"]["size"], 500)
        # OLD CODE END


def _risk_search(conns: dict[str, int], alerts: dict[str, int] | None = None):
    """search() side effect that answers like OpenSearch over per-IP connection counts.

    A terms list returns the busiest `size` IPs, a composite every IP page by page in key
    order, the alert query each IP's alert count.
    """
    alerts = alerts or {}

    def bucket(ip):
        return _make_device_bucket(ip, doc_count=conns[ip])

    def search(index=None, body=None, **_kwargs):
        aggs = body.get("aggs", {})
        if "devices" in aggs:
            busiest = sorted(conns, key=lambda ip: -conns[ip])[: aggs["devices"]["terms"]["size"]]
            return {"hits": {"total": {"value": 0}}, "aggregations": {"devices": {"buckets": [bucket(ip) for ip in busiest]}}}
        if "all" in aggs:
            composite = aggs["all"]["composite"]
            after = (composite.get("after") or {}).get("ip")
            page = [ip for ip in sorted(conns) if after is None or ip > after][: composite["size"]]
            return {"aggregations": {"all": {"buckets": [{**bucket(ip), "key": {"ip": ip}} for ip in page],
                                             **({"after_key": {"ip": page[-1]}} if page else {})}}}
        if "by_ip" in aggs:
            return _make_alert_search_result({ip: n for ip, n in alerts.items() if ip in conns})
        # The single device's own connection and alert searches
        if {"term": {"event.dataset": "alert"}} in body["query"]["bool"]["filter"]:
            return _make_single_alert_result(total=0)
        return _make_single_conn_result(total=100)

    return search


class TestRiskCoversEveryDevice(AioHTTPTestCase):
    """#96: the baseline and the list cover every device the device list can show."""

    def setUp(self):
        self.mock_storage = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.mock_storage
        register_risk_routes(app, RiskScorer(), self.mock_storage)
        return app

    # 500 busy devices and 100 quiet ones: the busiest 500 left the quiet ones out of the baseline
    CONNS = {
        **{f"192.168.{i // 200 + 1}.{i % 200 + 1}": 100 for i in range(500)},
        **{f"192.168.9.{i + 1}": 10 for i in range(100)},
    }

    @unittest_run_loop
    async def test_list_baseline_is_every_device(self):
        self.mock_storage._client.search.side_effect = _risk_search(self.CONNS)

        data = await (await self.client.request("GET", "/api/risk/scores")).json()

        # (500 * 100 + 100 * 10) / 600 = 85; the busiest 500 alone read 100 with stddev 0
        self.assertEqual(data["network_avg_connections"], 85.0)
        self.assertEqual(data["network_stddev_connections"], 33.54)

    @unittest_run_loop
    async def test_single_baseline_is_every_device(self):
        self.mock_storage._client.search.side_effect = _risk_search(self.CONNS)

        data = await (await self.client.request("GET", "/api/risk/scores/192.168.1.1")).json()

        anomaly = next(f for f in data["factors"] if f["name"] == "connection_anomaly")
        # 100 conns vs 85 +/- 33.5 is normal; from the busiest 500 (stddev 0) it was "insufficient data"
        self.assertEqual(anomaly["description"], "Connection count within normal range (100 conns)")

    @unittest_run_loop
    async def test_list_has_every_device_and_only_devices(self):
        """Compliance compares this list with /api/devices/count: same population, all of it."""
        conns = {
            **{f"192.168.1.{i + 1}": 50 for i in range(150)},
            "192.168.2.1": 2,  # under _MIN_CONNECTIONS: not a device on the device list
            "192.168.2.255": 50,  # broadcast: skipped by the device list
        }
        self.mock_storage._client.search.side_effect = _risk_search(conns)

        data = await (await self.client.request("GET", "/api/risk/scores")).json()

        self.assertEqual(data["device_count"], 150)
        self.assertEqual({d["ip"] for d in data["devices"]}, {f"192.168.1.{i + 1}" for i in range(150)})

    @unittest_run_loop
    async def test_limit_takes_the_highest_scores_of_every_device(self):
        """A quiet device with many alerts ranks first; the list used to score only the busiest."""
        self.mock_storage._client.search.side_effect = _risk_search(self.CONNS, {"192.168.9.7": 20})

        data = await (await self.client.request("GET", "/api/risk/scores?limit=1")).json()

        self.assertEqual([d["ip"] for d in data["devices"]], ["192.168.9.7"])


class TestRiskRouteRegistration(AioHTTPTestCase):
    """Tests for route registration."""

    def setUp(self):
        self.mock_storage = _make_mock_storage()
        self.risk_scorer = RiskScorer()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.mock_storage
        register_risk_routes(app, self.risk_scorer, self.mock_storage)
        return app

    @unittest_run_loop
    async def test_risk_scorer_stored_on_app(self):
        """The RiskScorer should be stored on the app dict."""
        self.assertIs(self.app["risk_scorer"], self.risk_scorer)

    @unittest_run_loop
    async def test_scores_route_exists(self):
        """The /api/risk/scores route should be registered."""
        self.mock_storage._client.search.return_value = _make_conn_search_result()
        resp = await self.client.request("GET", "/api/risk/scores")
        self.assertNotEqual(resp.status, 404)

    @unittest_run_loop
    async def test_single_score_route_exists(self):
        """The /api/risk/scores/{ip} route should be registered."""
        from opensearchpy import OpenSearchException

        # Will fail with 502 but not 404
        self.mock_storage._client.search.side_effect = OpenSearchException("test")
        resp = await self.client.request("GET", "/api/risk/scores/1.2.3.4")
        self.assertNotEqual(resp.status, 404)


if __name__ == "__main__":
    unittest.main()
