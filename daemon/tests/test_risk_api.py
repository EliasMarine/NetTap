"""
Tests for daemon/api/risk.py

All tests use mocks -- no OpenSearch or external dependencies required.
Tests cover the risk scoring API endpoints using AioHTTPTestCase.
"""

import unittest
from unittest.mock import MagicMock, patch

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
        if {"term": {"event.dataset": "alert"}} in body["query"]["bool"].get(
            "filter", []
        ):
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
        "ports_used": {"ports": {"buckets": port_buckets}},
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
            "ports_used": {"ports": {"buckets": port_buckets}},
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
        "aggregations": {
            "all": {"buckets": [{**b, "key": {"ip": b["key"]}} for b in buckets]}
        },
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
        self.assertIn(
            {"prefix": {"rule.name": "SURICATA "}},
            bodies[0]["query"]["bool"]["must_not"],
        )

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
    async def test_scores_alert_query_failure_is_an_error(self):
        """#96: a failed alert count scored every device as having no alerts; now a 502."""
        from opensearchpy import OpenSearchException

        buckets = [_make_device_bucket("192.168.1.10")]
        conn_result = _make_conn_search_result(buckets=buckets, total=100)

        self.mock_storage._client.search.side_effect = [
            conn_result,
            OpenSearchException("alert index missing"),
        ]

        resp = await self.client.request("GET", "/api/risk/scores")
        self.assertEqual(resp.status, 502)

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
        self.assertIn(
            {"prefix": {"rule.name": "SURICATA "}},
            bodies[0]["query"]["bool"]["must_not"],
        )  # (#60)

    @unittest_run_loop
    async def test_single_device_not_found(self):
        """GET /api/risk/scores/{ip} returns 404 for unknown device."""
        conn_result = {
            "hits": {"total": {"value": 0}},
            "aggregations": {
                "total_orig_bytes": {"value": 0},
                "total_resp_bytes": {"value": 0},
                "ports_used": {"ports": {"buckets": []}},
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
    async def test_single_device_network_query_failure_is_an_error(self):
        """#96: a failed baseline scored the device against 0 +/- 0; now a 502."""
        from opensearchpy import OpenSearchException

        conn_result = _make_single_conn_result(total=100)
        alert_result = _make_single_alert_result(total=0)

        self.mock_storage._client.search.side_effect = [
            conn_result,
            OpenSearchException("network query failed"),
            alert_result,
        ]

        resp = await self.client.request("GET", "/api/risk/scores/192.168.1.10")
        self.assertEqual(resp.status, 502)

    @unittest_run_loop
    async def test_single_device_alert_query_failure_is_an_error(self):
        """#96: a failed alert count scored the device as having no alerts; now a 502."""
        from opensearchpy import OpenSearchException

        def search(index=None, body=None, **_kwargs):
            if {"term": {"event.dataset": "alert"}} in body["query"]["bool"]["filter"]:
                raise OpenSearchException("alert query failed")
            if "all" in body.get("aggs", {}):
                return {"aggregations": {"all": {"buckets": []}}}
            return _make_single_conn_result(total=100)

        self.mock_storage._client.search.side_effect = search
        resp = await self.client.request("GET", "/api/risk/scores/192.168.1.10")
        self.assertEqual(resp.status, 502)


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
            busiest = sorted(conns, key=lambda ip: -conns[ip])[
                : aggs["devices"]["terms"]["size"]
            ]
            return {
                "hits": {"total": {"value": 0}},
                "aggregations": {
                    "devices": {"buckets": [bucket(ip) for ip in busiest]}
                },
            }
        if "all" in aggs:
            composite = aggs["all"]["composite"]
            after = (composite.get("after") or {}).get("ip")
            page = [ip for ip in sorted(conns) if after is None or ip > after][
                : composite["size"]
            ]
            return {
                "aggregations": {
                    "all": {
                        "buckets": [{**bucket(ip), "key": {"ip": ip}} for ip in page],
                        **({"after_key": {"ip": page[-1]}} if page else {}),
                    }
                }
            }
        if "by_ip" in aggs:
            return _make_alert_search_result(
                {ip: n for ip, n in alerts.items() if ip in conns}
            )
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

        data = await (
            await self.client.request("GET", "/api/risk/scores/192.168.1.1")
        ).json()

        anomaly = next(f for f in data["factors"] if f["name"] == "connection_anomaly")
        # 100 conns vs 85 +/- 33.5 is normal; from the busiest 500 (stddev 0) it was "insufficient data"
        self.assertEqual(
            anomaly["description"], "Connection count within normal range (100 conns)"
        )

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
        self.assertEqual(
            {d["ip"] for d in data["devices"]},
            {f"192.168.1.{i + 1}" for i in range(150)},
        )

    @unittest_run_loop
    async def test_limit_takes_the_highest_scores_of_every_device(self):
        """A quiet device with many alerts ranks first; the list used to score only the busiest."""
        self.mock_storage._client.search.side_effect = _risk_search(
            self.CONNS, {"192.168.9.7": 20}
        )

        data = await (
            await self.client.request("GET", "/api/risk/scores?limit=1")
        ).json()

        self.assertEqual([d["ip"] for d in data["devices"]], ["192.168.9.7"])

    @unittest_run_loop
    async def test_alert_counts_are_asked_in_chunks_that_cover_every_device(self):
        """#96: one terms filter of every IP fails past 65,536 devices (index.max_terms_count)."""
        answer = _risk_search(self.CONNS, {"192.168.9.7": 20})
        asked: list[list[str]] = []

        def search(index=None, body=None, **kwargs):
            if "by_ip" in body.get("aggs", {}):
                ips = next(
                    f["terms"]["source.ip"]
                    for f in body["query"]["bool"]["filter"]
                    if "terms" in f
                )
                asked.append(ips)
                reply = answer(index=index, body=body, **kwargs)
                buckets = reply["aggregations"]["by_ip"]["buckets"]
                return {
                    **reply,
                    "aggregations": {
                        "by_ip": {"buckets": [b for b in buckets if b["key"] in ips]}
                    },
                }
            return answer(index=index, body=body, **kwargs)

        self.mock_storage._client.search.side_effect = search
        with patch("api.risk._ALERT_IP_CHUNK", 250):
            data = await (
                await self.client.request("GET", "/api/risk/scores?limit=1")
            ).json()

        self.assertEqual([len(ips) for ips in asked], [250, 250, 100])
        self.assertEqual(sorted(ip for ips in asked for ip in ips), sorted(self.CONNS))
        self.assertEqual([d["ip"] for d in data["devices"]], ["192.168.9.7"])


def _port_search(ports_by_ip: dict[str, dict[int, int]]):
    """search() side effect over each IP's destination-port connection counts.

    ports_used is the top 50 by count with sum_other_doc_count, like OpenSearch; the
    (ip, port) composite has every port outside the must_not port list for the IPs asked.
    """

    def ports_used(ports):
        top = sorted(ports, key=lambda port: -ports[port])[:50]
        # the terms list sits inside the non-ICMP filter (NET-158)
        return {
            "ports": {
                "buckets": [{"key": port, "doc_count": ports[port]} for port in top],
                "sum_other_doc_count": sum(
                    n for port, n in ports.items() if port not in top
                ),
            }
        }

    def device(ip, key):
        ports = ports_by_ip[ip]
        return {
            **_make_device_bucket(ip, doc_count=sum(ports.values())),
            "key": key,
            "ports_used": ports_used(ports),
        }

    def composite_page(body):
        composite = body["aggs"]["all"]["composite"]
        names = [next(iter(source)) for source in composite["sources"]]
        bool_query = body["query"]["bool"]
        if names == ["ip"]:
            keys = [{"ip": ip} for ip in sorted(ports_by_ip)]
            make = lambda key: device(key["ip"], key)  # noqa: E731
        else:
            ips = [
                c["terms"]["source.ip"]
                for c in bool_query["filter"]
                if "source.ip" in c.get("terms", {})
            ][-1]
            safe = [
                c["terms"]["destination.port"]
                for c in bool_query["must_not"]
                if "destination.port" in c.get("terms", {})
            ][0]
            keys = [
                {"ip": ip, "port": port}
                for ip in sorted(ips)
                for port in sorted(ports_by_ip[ip])
                if port not in safe
            ]
            make = lambda key: {  # noqa: E731
                "key": key,
                "doc_count": ports_by_ip[key["ip"]][key["port"]],
            }
        after = composite.get("after")
        start = keys.index(after) + 1 if after else 0
        page = keys[start : start + composite["size"]]
        return {
            "aggregations": {
                "all": {
                    "buckets": [make(k) for k in page],
                    **({"after_key": page[-1]} if page else {}),
                }
            }
        }

    def search(index=None, body=None, **_kwargs):
        aggs = body.get("aggs", {})
        if "all" in aggs:
            return composite_page(body)
        if "by_ip" in aggs:
            return _make_alert_search_result({})
        filters = body["query"]["bool"]["filter"]
        if {"term": {"event.dataset": "alert"}} in filters:
            return _make_single_alert_result(total=0)
        ip = next(
            c["term"]["source.ip"] for c in filters if "source.ip" in c.get("term", {})
        )
        ports = ports_by_ip[ip]
        single = _make_single_conn_result(total=sum(ports.values()))
        return {
            **single,
            "aggregations": {**single["aggregations"], "ports_used": ports_used(ports)},
        }

    return search


class TestRiskPortsAreComplete(AioHTTPTestCase):
    """#96: the scorer sees every port a device used outside the safe ports, not the top 50."""

    # A console: 443 plus 59 game ports at 10 connections each, and one connection to 4444
    CONSOLE = {443: 500, **{20_000 + i: 10 for i in range(59)}, 4444: 1}
    # A torrent host: 70 peer ports, none on the suspicious list
    TORRENT = {443: 500, **{40_000 + i: 10 for i in range(70)}}
    PORTS = {
        "192.168.1.20": CONSOLE,
        "192.168.1.30": TORRENT,
        "192.168.1.40": {443: 100, 53: 20},
    }

    def setUp(self):
        self.mock_storage = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.mock_storage
        register_risk_routes(app, RiskScorer(), self.mock_storage)
        return app

    def _port_factor(self, device):
        return next(f for f in device["factors"] if f["name"] == "suspicious_ports")

    @unittest_run_loop
    async def test_list_sees_a_rare_suspicious_port(self):
        self.mock_storage._client.search.side_effect = _port_search(self.PORTS)

        data = await (await self.client.request("GET", "/api/risk/scores")).json()

        by_ip = {d["ip"]: self._port_factor(d) for d in data["devices"]}
        # The top 50 left 4444 out: 8 points and "49 unusual port(s) detected"
        self.assertEqual(by_ip["192.168.1.20"]["score"], 15)
        self.assertEqual(
            by_ip["192.168.1.20"]["description"], "Known suspicious ports used: 4444"
        )
        self.assertEqual(
            by_ip["192.168.1.30"]["description"], "70 unusual port(s) detected"
        )
        self.assertEqual(
            by_ip["192.168.1.40"]["description"], "Only common protocols/ports used"
        )
        # Only the two devices whose list was cut short are read in full
        port_bodies = [
            c.kwargs["body"]
            for c in self.mock_storage._client.search.call_args_list
            if len(
                c.kwargs["body"]
                .get("aggs", {})
                .get("all", {})
                .get("composite", {})
                .get("sources", [])
            )
            == 2
        ]
        self.assertIn(
            {"terms": {"source.ip": ["192.168.1.20", "192.168.1.30"]}},
            port_bodies[0]["query"]["bool"]["filter"],
        )

    @unittest_run_loop
    async def test_single_sees_a_rare_suspicious_port(self):
        self.mock_storage._client.search.side_effect = _port_search(self.PORTS)

        data = await (
            await self.client.request("GET", "/api/risk/scores/192.168.1.20")
        ).json()

        self.assertEqual(
            self._port_factor(data)["description"], "Known suspicious ports used: 4444"
        )


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


class TestRiskFactorScope(unittest.TestCase):
    """NET-158: "external" is the internet only, and ICMP codes are not ports."""

    def test_external_leaves_out_every_non_internet_address(self):
        from api.risk import _device_score_aggs

        [clause] = _device_score_aggs()["external_conns"]["filter"]["bool"]["must_not"]
        excluded = set(clause["terms"]["destination.ip"])
        # multicast (mDNS 224.0.0.251, ff02::fb), broadcast, link-local, IPv6 private
        for cidr in (
            "224.0.0.0/4",
            "ff00::/8",
            "255.255.255.255/32",
            "169.254.0.0/16",
            "fe80::/10",
            "fc00::/7",
        ):
            self.assertIn(cidr, excluded)

    def test_ports_leave_out_icmp_on_the_list_and_the_single_device(self):
        from api.risk import _device_score_aggs, _build_device_stats

        icmp = {"terms": {"network.transport": ["icmp", "icmp6", "ipv6-icmp"]}}
        ports = _device_score_aggs()["ports_used"]
        self.assertEqual(ports["filter"], {"bool": {"must_not": [icmp]}})
        self.assertEqual(ports["aggs"]["ports"]["terms"]["field"], "destination.port")
        bucket = {"doc_count": 3, "ports_used": {"ports": {"buckets": [{"key": 443}]}}}
        self.assertEqual(
            _build_device_stats("10.0.0.2", bucket, 0, 0, 0)["ports_used"], [443]
        )


if __name__ == "__main__":
    unittest.main()


INCOMPLETE = {"error": "The device search was incomplete"}


def _spoil(answer, which: str, change):
    """`answer` (a _risk_search side effect) with one kind of reply changed by `change`."""

    def kind(body):
        aggs = body.get("aggs", {})
        if "all" in aggs:
            sources = aggs["all"]["composite"]["sources"]
            return "ports" if len(sources) == 2 else "devices"
        if "by_ip" in aggs:
            return "alerts"
        is_alert = {"term": {"event.dataset": "alert"}} in body["query"]["bool"][
            "filter"
        ]
        return "single_alert" if is_alert else "single_conn"

    def search(index=None, body=None, **kwargs):
        reply = answer(index=index, body=body, **kwargs)
        return change(reply) if kind(body) == which else reply

    return search


def _timed_out(reply):
    return {**reply, "timed_out": True}


def _shard_failed(reply):
    return {**reply, "_shards": {"total": 2, "successful": 1, "failed": 1}}


class TestRiskReadsAreChecked(AioHTTPTestCase):
    """Follow-up to PR #191: a partial read is a 502, never a lower score."""

    CONNS = {f"192.168.1.{i + 1}": 50 for i in range(5)}

    def setUp(self):
        self.mock_storage = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.mock_storage
        register_risk_routes(app, RiskScorer(), self.mock_storage)
        return app

    async def _get(self, path, which, change, conns=None):
        self.mock_storage._client.search.side_effect = _spoil(
            _risk_search(conns or self.CONNS), which, change
        )
        resp = await self.client.request("GET", path)
        return resp.status, await resp.json()

    @unittest_run_loop
    async def test_list_fails_when_a_device_page_timed_out(self):
        self.assertEqual(
            await self._get("/api/risk/scores", "devices", _timed_out),
            (502, INCOMPLETE),
        )

    @unittest_run_loop
    async def test_list_fails_when_an_alert_chunk_lost_a_shard(self):
        self.assertEqual(
            await self._get("/api/risk/scores", "alerts", _shard_failed),
            (502, INCOMPLETE),
        )

    @unittest_run_loop
    async def test_list_fails_when_an_alert_reply_has_no_bucket_list(self):
        def no_buckets(reply):
            return {**reply, "aggregations": {"by_ip": {}}}

        self.assertEqual(
            await self._get("/api/risk/scores", "alerts", no_buckets),
            (502, INCOMPLETE),
        )

    @unittest_run_loop
    async def test_list_fails_when_the_port_read_lost_a_shard(self):
        # a device whose top-50 port list was cut short sends the list to the port read
        cut = _make_device_bucket("192.168.1.1", doc_count=50)
        cut["ports_used"]["ports"]["sum_other_doc_count"] = 3

        def answer(index=None, body=None, **kwargs):
            if (
                len(
                    body.get("aggs", {})
                    .get("all", {})
                    .get("composite", {})
                    .get("sources", [])
                )
                == 2
            ):
                return _shard_failed({"aggregations": {"all": {"buckets": []}}})
            reply = _risk_search(self.CONNS)(index=index, body=body, **kwargs)
            if "all" in body.get("aggs", {}):
                buckets = reply["aggregations"]["all"]["buckets"]
                reply["aggregations"]["all"]["buckets"] = [
                    {**cut, "key": b["key"]} if b["key"]["ip"] == "192.168.1.1" else b
                    for b in buckets
                ]
            return reply

        self.mock_storage._client.search.side_effect = answer
        resp = await self.client.request("GET", "/api/risk/scores")
        self.assertEqual((resp.status, await resp.json()), (502, INCOMPLETE))

    @unittest_run_loop
    async def test_single_fails_when_its_connection_search_timed_out(self):
        self.assertEqual(
            await self._get("/api/risk/scores/192.168.1.1", "single_conn", _timed_out),
            (502, INCOMPLETE),
        )

    @unittest_run_loop
    async def test_single_fails_on_a_lower_bound_alert_total(self):
        def lower_bound(reply):
            return {**reply, "hits": {"total": {"value": 10000, "relation": "gte"}}}

        self.assertEqual(
            await self._get(
                "/api/risk/scores/192.168.1.1", "single_alert", lower_bound
            ),
            (502, INCOMPLETE),
        )

    @unittest_run_loop
    async def test_single_fails_when_a_baseline_page_lost_a_shard(self):
        self.assertEqual(
            await self._get("/api/risk/scores/192.168.1.1", "devices", _shard_failed),
            (502, INCOMPLETE),
        )

    @unittest_run_loop
    async def test_single_fails_when_its_port_read_lost_a_shard(self):
        def cut_short(reply):
            ports = reply["aggregations"]["ports_used"]["ports"]
            return {
                **reply,
                "aggregations": {
                    **reply["aggregations"],
                    "ports_used": {"ports": {**ports, "sum_other_doc_count": 3}},
                },
            }

        answer = _spoil(_risk_search(self.CONNS), "single_conn", cut_short)
        self.mock_storage._client.search.side_effect = _spoil(
            answer, "ports", _shard_failed
        )
        resp = await self.client.request("GET", "/api/risk/scores/192.168.1.1")
        self.assertEqual((resp.status, await resp.json()), (502, INCOMPLETE))

    @unittest_run_loop
    async def test_complete_replies_still_score(self):
        self.assertEqual(
            (await self._get("/api/risk/scores", "none", _timed_out))[0], 200
        )
        status, data = await self._get(
            "/api/risk/scores/192.168.1.1", "none", _timed_out
        )
        self.assertEqual((status, data["connection_count"]), (200, 100))
