"""
Tests for daemon/api/risk.py

All tests use mocks -- no OpenSearch or external dependencies required. The smart-alert findings
(get_smart_alerts) are patched; their own reads are tested in test_alert_intelligence.py.

NET-209: the score reads the device's own findings and its own last week (_history), and an
internet address is never a device.
"""

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import sys
import os

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from opensearchpy import OpenSearchException

from api.risk import register_risk_routes
from services.excluded_ips import RFC1918_CIDRS
from services.risk_scoring import RiskScorer
from services.threat_detection import NOT_INTERNET_CIDRS
from storage.snapshot_search import QueryFailed

# OLD CODE: the five-factor tests (byte-field sums, a network-wide connection baseline on the
# single device, the chunked alert counts by source IP, the port reads and the external share)
# went with those reads in NET-209; see `git show origin/main:daemon/tests/test_risk_api.py`

DAY = 86_400_000
MB, GB = 1000**2, 1000**3
RANGE = {"from": "2026-11-07T00:00:00Z", "to": "2026-11-08T00:00:00Z"}
INCOMPLETE = {"error": "The device search was incomplete"}
NOT_SCORED = "not scored without a high or critical alert"


def _ms(ts: str) -> int:
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)


def _make_mock_storage():
    """Create a mock StorageManager with a mock OpenSearch client."""
    storage = MagicMock()
    storage._client = MagicMock()
    return storage


def _group(signature, findings, reputation=False):
    """A smart-alert group: findings are (device, own traffic, alerts, severity)."""
    return {
        "signature": signature,
        "reputation": reputation,
        "findings": [
            {"device": d, "own": own, "count": n, "severity": sev}
            for d, own, n, sev in findings
        ],
    }


def _term(body, field):
    """The address a `term` filter on `field` pins the search to, if any."""
    return next(
        (
            c["term"][field]
            for c in body["query"]["bool"]["filter"]
            if field in c.get("term", {})
        ),
        None,
    )


def _risk_search(conns, opened=None, answered=None):
    """search() side effect that answers the risk endpoints' reads like OpenSearch.

    conns: each device's connections in the window. opened: per device, eight (connections,
    internet bytes) rows for the history ranges, the last being the window (default: nothing
    before the window, `conns` in it). answered: per device, eight byte totals it answered on
    connections an internet address opened.
    """
    opened = opened or {}
    answered = answered or {}

    def rows(ip):
        return opened.get(ip) or [(0, 0)] * 7 + [(conns.get(ip, 0), 0)]

    def history_bucket(ip, ranges, data):
        return {
            "key": {"ip": ip},
            "doc_count": sum(c for c, _ in data),
            "days": {
                "buckets": [
                    {
                        "key": r["key"],
                        "doc_count": c,
                        "internet": {"doc_count": 0, "bytes": {"value": b}},
                    }
                    for r, (c, b) in zip(ranges, data)
                ]
            },
        }

    def composite(body):
        agg = body["aggs"]["all"]
        field = agg["composite"]["sources"][0]["ip"]["terms"]["field"]
        if "days" in agg.get("aggs", {}):
            ranges = agg["aggs"]["days"]["date_range"]["ranges"]
            data = (
                {ip: rows(ip) for ip in {*conns, *opened}}
                if field == "source.ip"
                else {ip: [(0, b) for b in v] for ip, v in answered.items()}
            )
            only = _term(body, field)
            keys = sorted(ip for ip in data if only in (None, ip))
            make = lambda ip: history_bucket(ip, ranges, data[ip])  # noqa: E731
        else:
            keys = sorted(conns)
            make = lambda ip: {"key": {"ip": ip}, "doc_count": conns[ip]}  # noqa: E731
        after = (agg["composite"].get("after") or {}).get("ip")
        page = [ip for ip in keys if after is None or ip > after][
            : agg["composite"]["size"]
        ]
        return {
            "aggregations": {
                "all": {
                    "buckets": [make(ip) for ip in page],
                    **({"after_key": {"ip": page[-1]}} if page else {}),
                }
            }
        }

    def search(index=None, body=None, **_kwargs):
        if "all" in body.get("aggs", {}):
            return composite(body)
        # the single device's connection count
        total = conns.get(_term(body, "source.ip"), 0)
        return {"hits": {"total": {"value": total, "relation": "eq"}}}

    return search


def _kind(body):
    agg = body.get("aggs", {}).get("all")
    if agg is None:
        return "single_conn"
    return "history" if "days" in agg.get("aggs", {}) else "devices"


def _spoil(answer, which: str, change):
    """`answer` with one kind of reply ("devices", "history", "single_conn") changed."""

    def search(index=None, body=None, **kwargs):
        reply = answer(index=index, body=body, **kwargs)
        return change(reply) if _kind(body) == which else reply

    return search


def _timed_out(reply):
    return {**reply, "timed_out": True}


def _shard_failed(reply):
    return {**reply, "_shards": {"total": 2, "successful": 1, "failed": 1}}


def _a_day_renamed(reply):
    """Eight ranges, but one under a key that was never asked for (a 500 before, not a 502)."""
    page = reply["aggregations"]["all"]
    return {
        "aggregations": {
            "all": {
                **page,
                "buckets": [
                    {
                        **b,
                        "days": {
                            "buckets": [*b["days"]["buckets"][:-1], {**b["days"]["buckets"][-1], "key": "x"}]
                        },
                    }
                    for b in page["buckets"]
                ],
            }
        }
    }


def _a_day_missing(reply):
    page = reply["aggregations"]["all"]
    return {
        "aggregations": {
            "all": {
                **page,
                "buckets": [
                    {**b, "days": {"buckets": b["days"]["buckets"][:-1]}}
                    for b in page["buckets"]
                ],
            }
        }
    }


def _factor(device, name):
    return next(f for f in device["factors"] if f["name"] == name)


class _RiskCase(AioHTTPTestCase):
    """An app with the risk routes, a mock OpenSearch client and patched smart alerts."""

    LAN_FILTER: dict | None = None
    EXCLUDED: list[str] | None = None

    def setUp(self):
        self.mock_storage = _make_mock_storage()
        self.risk_scorer = RiskScorer()
        smart = patch("api.risk.get_smart_alerts", return_value=[])
        self.smart = smart.start()
        self.addCleanup(smart.stop)
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.mock_storage
        if self.LAN_FILTER is not None:
            app["lan_filter"] = self.LAN_FILTER
        if self.EXCLUDED is not None:
            app["excluded_ips"] = self.EXCLUDED
        register_risk_routes(app, self.risk_scorer, self.mock_storage)
        return app

    def answer(self, conns, **kwargs):
        self.mock_storage._client.search.side_effect = _risk_search(conns, **kwargs)

    async def get(self, path, params=None):
        resp = await self.client.request("GET", path, params=params)
        return resp.status, await resp.json()

    def bodies(self):
        return [c.kwargs["body"] for c in self.mock_storage._client.search.call_args_list]


class TestRiskScoresEndpoint(_RiskCase):
    """Tests for GET /api/risk/scores."""

    @unittest_run_loop
    async def test_scores_empty_result(self):
        self.answer({})
        status, data = await self.get("/api/risk/scores")
        self.assertEqual(status, 200)
        self.assertEqual(data["device_count"], 0)
        self.assertEqual(data["devices"], [])

    @unittest_run_loop
    async def test_scores_with_devices(self):
        """Devices come highest score first."""
        self.answer({"192.168.1.10": 100, "192.168.1.20": 200})
        self.smart.return_value = [
            _group("ET MALWARE x", [("192.168.1.10", True, 5, 2)])
        ]
        status, data = await self.get("/api/risk/scores")
        self.assertEqual(status, 200)
        self.assertEqual(data["device_count"], 2)
        self.assertEqual(
            [(d["ip"], d["score"]) for d in data["devices"]],
            [("192.168.1.10", 25), ("192.168.1.20", 0)],
        )

    @unittest_run_loop
    async def test_scores_contain_required_fields(self):
        self.answer({})
        _, data = await self.get("/api/risk/scores")
        for key in (
            "from",
            "to",
            "device_count",
            "devices",
            "network_avg_connections",
            "network_stddev_connections",
        ):
            self.assertIn(key, data)

    @unittest_run_loop
    async def test_scores_opensearch_error(self):
        self.mock_storage._client.search.side_effect = OpenSearchException("timeout")
        status, data = await self.get("/api/risk/scores")
        self.assertEqual(status, 502)
        self.assertIn("error", data)

    @unittest_run_loop
    async def test_scores_device_has_score_level_and_three_factors(self):
        self.answer({"192.168.1.10": 100})
        _, data = await self.get("/api/risk/scores")
        device = data["devices"][0]
        for key in ("ip", "score", "level", "factors", "alert_count"):
            self.assertIn(key, device)
        self.assertEqual(
            [f["name"] for f in device["factors"]],
            ["alert_count", "connection_anomaly", "upload_spike"],
        )

    @unittest_run_loop
    async def test_scores_with_limit_param(self):
        self.answer({})
        status, _ = await self.get("/api/risk/scores?limit=10")
        self.assertEqual(status, 200)

    @unittest_run_loop
    async def test_a_failed_alert_read_is_an_error(self):
        """#96: a failed alert read scored every device as having no alerts; now a 502."""
        self.answer({"192.168.1.10": 100})
        self.smart.side_effect = OpenSearchException("alert index missing")
        status, _ = await self.get("/api/risk/scores")
        self.assertEqual(status, 502)

    @unittest_run_loop
    async def test_scores_query_never_aggregates_doc_count(self):
        """No aggregation may target _doc_count: OpenSearch rejects it with a 400."""
        self.answer({"192.168.1.10": 100})
        status, _ = await self.get("/api/risk/scores")
        self.assertEqual(status, 200)

        def fields(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "field":
                        yield value
                    yield from fields(value)
            elif isinstance(node, list):
                for item in node:
                    yield from fields(item)

        for body in self.bodies():
            self.assertNotIn("_doc_count", list(fields(body.get("aggs", {}))))

    @unittest_run_loop
    async def test_scores_network_stats_from_buckets(self):
        """Mean and population stddev come from the per-device connection counts."""
        self.answer({"192.168.1.10": 100, "192.168.1.20": 200, "192.168.1.30": 600})
        _, data = await self.get("/api/risk/scores")
        self.assertEqual(data["network_avg_connections"], 300.0)
        # sqrt(((100-300)^2 + (200-300)^2 + (600-300)^2) / 3) = 216.02
        self.assertEqual(data["network_stddev_connections"], 216.02)


class TestRiskAlertsAreTheDevicesOwn(_RiskCase):
    """NET-209: the alerts factor reads only findings in the device's own traffic."""

    GROUPS = [
        _group("ET MALWARE A", [("192.168.1.10", True, 3, 1)]),
        # the same signature toward another address: one signature, its alerts add up
        _group("ET MALWARE A", [("192.168.1.10", True, 4, 2)]),
        _group("ET POLICY D", [("192.168.1.10", True, 2, 4)]),
        # an internet scanner's attempt against .10: not .10's traffic
        _group("ET EXPLOIT B", [("192.168.1.10", False, 50, 1)]),
        # a blocklisted scanner's hits .10 never started (demoted to 5)
        _group("ET DROP C", [("192.168.1.10", False, 40, 5)], reputation=True),
        # an own finding demoted to activity never counts
        _group("ET Q", [("192.168.1.10", True, 9, 5)]),
        _group("ET SCAN F", [("192.168.1.20", True, 1, 3)]),
    ]

    @unittest_run_loop
    async def test_only_own_findings_below_activity_count(self):
        self.answer({"192.168.1.10": 100, "192.168.1.20": 100})
        self.smart.return_value = self.GROUPS
        _, data = await self.get("/api/risk/scores")
        by_ip = {d["ip"]: d for d in data["devices"]}

        ten = _factor(by_ip["192.168.1.10"], "alert_count")
        self.assertEqual(ten["score"], 50)  # A critical (50) + D low (1), capped
        self.assertEqual(
            ten["description"],
            "2 signatures in its own traffic (9 alerts), worst critical",
        )
        self.assertEqual(by_ip["192.168.1.10"]["alert_count"], 9)
        self.assertEqual(
            (by_ip["192.168.1.20"]["score"], by_ip["192.168.1.20"]["alert_count"]),
            (5, 1),
        )

    @unittest_run_loop
    async def test_findings_are_asked_without_activity_on_the_lan_rule(self):
        """ET INFO activity never reaches the factor: it is not asked for."""
        self.answer({"192.168.1.10": 100})
        await self.get("/api/risk/scores")
        kwargs = self.smart.call_args.kwargs
        self.assertEqual(
            {k: kwargs[k] for k in ("device_ip", "include_info", "limit", "lan_cidrs")},
            {
                "device_ip": None,
                "include_info": False,
                "limit": None,
                "lan_cidrs": RFC1918_CIDRS,
            },
        )

    @unittest_run_loop
    async def test_the_single_device_reads_its_own_findings_only(self):
        self.answer({"192.168.1.10": 100})
        self.smart.return_value = self.GROUPS
        status, data = await self.get("/api/risk/scores/192.168.1.10")
        self.assertEqual(status, 200)
        self.assertEqual(data["alert_count"], 9)
        self.assertEqual(self.smart.call_args.kwargs["device_ip"], "192.168.1.10")


class TestRiskScoreSingleEndpoint(_RiskCase):
    """Tests for GET /api/risk/scores/{ip}."""

    @unittest_run_loop
    async def test_single_device_score(self):
        self.answer({"192.168.1.10": 100})
        status, data = await self.get("/api/risk/scores/192.168.1.10")
        self.assertEqual(status, 200)
        self.assertEqual(data["ip"], "192.168.1.10")
        for key in ("score", "level", "factors", "from", "to"):
            self.assertIn(key, data)
        self.assertEqual(len(data["factors"]), 3)

    @unittest_run_loop
    async def test_single_device_not_found(self):
        """A LAN address with no connections in the window is a 404."""
        self.answer({})
        status, _ = await self.get("/api/risk/scores/10.0.0.99")
        self.assertEqual(status, 404)

    @unittest_run_loop
    async def test_an_internet_address_is_not_a_device(self):
        """NET-209: 91.92.40.12, an internet scanner, read as a device with risk 58."""
        self.answer({"91.92.40.12": 33})
        status, data = await self.get("/api/risk/scores/91.92.40.12")
        self.assertEqual(
            (status, data), (404, {"error": "91.92.40.12 is not on your network"})
        )
        self.mock_storage._client.search.assert_not_called()
        self.smart.assert_not_called()

    @unittest_run_loop
    async def test_single_device_opensearch_error(self):
        self.mock_storage._client.search.side_effect = OpenSearchException("error")
        status, _ = await self.get("/api/risk/scores/192.168.1.10")
        self.assertEqual(status, 502)

    @unittest_run_loop
    async def test_single_device_connection_count(self):
        self.answer({"192.168.1.10": 150})
        _, data = await self.get("/api/risk/scores/192.168.1.10")
        self.assertEqual(data["connection_count"], 150)

    @unittest_run_loop
    async def test_single_counts_past_10000(self):
        """#83: without track_total_hits, hits.total stops at 10,000 (busy devices read 10,000)."""
        self.answer({"192.168.1.188": 34401})
        _, data = await self.get("/api/risk/scores/192.168.1.188")
        self.assertEqual(data["connection_count"], 34401)
        conn_body = next(b for b in self.bodies() if _kind(b) == "single_conn")
        self.assertIs(conn_body.get("track_total_hits"), True)

    @unittest_run_loop
    async def test_a_failed_alert_read_is_an_error(self):
        self.answer({"192.168.1.10": 100})
        self.smart.side_effect = OpenSearchException("alert query failed")
        status, _ = await self.get("/api/risk/scores/192.168.1.10")
        self.assertEqual(status, 502)


class TestRiskHistory(_RiskCase):
    """Each device against its own last week: explicit ranges aligned to `from` (rule 11)."""

    LAN_FILTER = {"terms": {"source.ip": ["192.168.1.0/24"]}}
    EXCLUDED = ["192.168.1.1"]

    def history_bodies(self):
        bodies = [b for b in self.bodies() if _kind(b) == "history"]
        field = lambda b: b["aggs"]["all"]["composite"]["sources"][0]["ip"]["terms"][  # noqa: E731
            "field"
        ]
        return {field(b): b for b in bodies}

    @unittest_run_loop
    async def test_seven_days_then_the_window(self):
        self.answer({"192.168.1.10": 100})
        _, data = await self.get("/api/risk/scores", RANGE)
        start, end = _ms(data["from"]), _ms(data["to"])
        expected = [
            {"key": str(i), "from": start - (7 - i) * DAY, "to": start - (6 - i) * DAY}
            for i in range(7)
        ] + [{"key": "7", "from": start, "to": end + 1}]
        for body in self.history_bodies().values():
            self.assertEqual(
                body["aggs"]["all"]["aggs"]["days"]["date_range"]["ranges"], expected
            )
            [window] = [
                c["range"]["@timestamp"]
                for c in body["query"]["bool"]["filter"]
                if "range" in c
            ]
            self.assertEqual(_ms(window["gte"]), start - 7 * DAY)

    @unittest_run_loop
    async def test_the_opener_side_is_the_device_lists_population(self):
        self.answer({"192.168.1.10": 100})
        await self.get("/api/risk/scores", RANGE)
        devices = next(b for b in self.bodies() if _kind(b) == "devices")
        opened = self.history_bodies()["source.ip"]

        def without_range(bool_query):
            return [c for c in bool_query["filter"] if "range" not in c]

        self.assertIn(self.LAN_FILTER, opened["query"]["bool"]["filter"])
        self.assertEqual(
            without_range(opened["query"]["bool"]),
            without_range(devices["query"]["bool"]),
        )
        self.assertEqual(
            opened["query"]["bool"]["must_not"],
            [{"terms": {"source.ip": ["192.168.1.1"]}}],
        )
        days = opened["aggs"]["all"]["aggs"]["days"]["aggs"]["internet"]
        self.assertEqual(
            days["filter"],
            {"bool": {"must_not": [{"terms": {"destination.ip": NOT_INTERNET_CIDRS}}]}},
        )
        self.assertEqual(
            days["aggs"]["bytes"], {"sum": {"field": "source.bytes", "missing": 0}}
        )

    @unittest_run_loop
    async def test_the_answering_side_is_internet_opened_connections_to_the_lan(self):
        self.answer({"192.168.1.10": 100})
        await self.get("/api/risk/scores", RANGE)
        answered = self.history_bodies()["destination.ip"]
        self.assertIn(
            {"terms": {"destination.ip": ["192.168.1.0/24"]}},
            answered["query"]["bool"]["filter"],
        )
        self.assertEqual(
            answered["query"]["bool"]["must_not"],
            [{"terms": {"source.ip": NOT_INTERNET_CIDRS}}],
        )
        days = answered["aggs"]["all"]["aggs"]["days"]["aggs"]["internet"]
        self.assertEqual(days["filter"], {"match_all": {}})
        self.assertEqual(
            days["aggs"]["bytes"], {"sum": {"field": "destination.bytes", "missing": 0}}
        )

    @unittest_run_loop
    async def test_the_single_device_reads_its_own_history(self):
        self.answer({"192.168.1.10": 100})
        status, _ = await self.get("/api/risk/scores/192.168.1.10", RANGE)
        self.assertEqual(status, 200)
        bodies = self.history_bodies()
        self.assertEqual(_term(bodies["source.ip"], "source.ip"), "192.168.1.10")
        self.assertEqual(
            _term(bodies["destination.ip"], "destination.ip"), "192.168.1.10"
        )

    @unittest_run_loop
    async def test_the_lan_rule_decides_what_is_a_device(self):
        """With LAN subnets set, another private range is not this network."""
        self.answer({"192.168.2.5": 100})
        status, data = await self.get("/api/risk/scores/192.168.2.5")
        self.assertEqual(
            (status, data), (404, {"error": "192.168.2.5 is not on your network"})
        )


class TestRiskVolumeFactors(_RiskCase):
    """Upload counts in both roles, and volume scores only with a high or critical own alert."""

    SERVER = "192.168.1.24"
    # 500 connections and 100 MB to the internet a day; the window: 5,000 and 50 MB opened
    OPENED = {SERVER: [(500, 100 * MB)] * 7 + [(5000, 50 * MB)]}
    # ...and 1.95 GB answered to internet-opened connections (a port-forwarded server)
    ANSWERED = {SERVER: [0] * 7 + [1950 * MB]}

    def answer_server(self):
        self.answer({self.SERVER: 5000}, opened=self.OPENED, answered=self.ANSWERED)

    @unittest_run_loop
    async def test_answered_bytes_add_to_the_window_upload(self):
        self.answer_server()
        self.smart.return_value = [_group("ET MALWARE x", [(self.SERVER, True, 3, 2)])]
        _, data = await self.get(f"/api/risk/scores/{self.SERVER}")
        upload = _factor(data, "upload_spike")
        # 50 MB alone is under the 100 MB floor; with the answered 1.95 GB it is 2 GB, 20×
        self.assertEqual(
            (upload["score"], upload["description"]),
            (25, "Sent 2.0 GB to the internet, 20.0× its usual"),
        )
        self.assertEqual(_factor(data, "connection_anomaly")["score"], 25)
        self.assertEqual((data["score"], data["level"]), (75, "critical"))

    @unittest_run_loop
    async def test_policy_and_reputation_alerts_do_not_unlock_volume(self):
        self.answer_server()
        self.smart.return_value = [
            _group("ET POLICY x", [(self.SERVER, True, 2, 4)]),
            _group("ET DROP y", [(self.SERVER, True, 1, 3)], reputation=True),
            # a reputation hit is never corroboration, whatever its severity
            _group("ET CINS z", [(self.SERVER, True, 1, 2)], reputation=True),
        ]
        _, data = await self.get("/api/risk/scores")
        [device] = data["devices"]
        for name in ("connection_anomaly", "upload_spike"):
            factor = _factor(device, name)
            self.assertEqual(factor["score"], 0)
            self.assertTrue(factor["description"].endswith(NOT_SCORED), factor)

    @unittest_run_loop
    async def test_an_attempt_against_it_does_not_unlock_volume(self):
        self.answer_server()
        self.smart.return_value = [
            _group("ET EXPLOIT x", [(self.SERVER, False, 9, 1)])
        ]
        _, data = await self.get("/api/risk/scores")
        self.assertEqual(data["devices"][0]["score"], 0)


class TestRiskCoversEveryDevice(_RiskCase):
    """#96: the list and its statistics cover every device the device list can show."""

    # 500 busy devices and 100 quiet ones
    CONNS = {
        **{f"192.168.{i // 200 + 1}.{i % 200 + 1}": 100 for i in range(500)},
        **{f"192.168.9.{i + 1}": 10 for i in range(100)},
    }

    @unittest_run_loop
    async def test_list_statistics_are_every_device(self):
        self.answer(self.CONNS)
        _, data = await self.get("/api/risk/scores")
        # (500 * 100 + 100 * 10) / 600 = 85; the busiest 500 alone read 100 with stddev 0
        self.assertEqual(data["network_avg_connections"], 85.0)
        self.assertEqual(data["network_stddev_connections"], 33.54)

    @unittest_run_loop
    async def test_list_has_every_device_and_only_devices(self):
        """Compliance compares this list with /api/devices/count: same population, all of it."""
        conns = {
            **{f"192.168.1.{i + 1}": 50 for i in range(150)},
            "192.168.2.1": 2,  # under _MIN_CONNECTIONS: not a device on the device list
            "192.168.2.255": 50,  # broadcast: skipped by the device list
        }
        self.answer(conns)
        _, data = await self.get("/api/risk/scores")
        self.assertEqual(data["device_count"], 150)
        self.assertEqual(
            {d["ip"] for d in data["devices"]},
            {f"192.168.1.{i + 1}" for i in range(150)},
        )

    @unittest_run_loop
    async def test_limit_takes_the_highest_scores_of_every_device(self):
        """A quiet device with a critical alert of its own ranks first."""
        self.answer(self.CONNS)
        self.smart.return_value = [
            _group("ET MALWARE x", [("192.168.9.7", True, 20, 1)])
        ]
        _, data = await self.get("/api/risk/scores?limit=1")
        self.assertEqual([d["ip"] for d in data["devices"]], ["192.168.9.7"])


class TestRiskRouteRegistration(_RiskCase):
    """Tests for route registration."""

    @unittest_run_loop
    async def test_risk_scorer_stored_on_app(self):
        self.assertIs(self.app["risk_scorer"], self.risk_scorer)

    @unittest_run_loop
    async def test_scores_route_exists(self):
        self.answer({})
        status, _ = await self.get("/api/risk/scores")
        self.assertNotEqual(status, 404)

    @unittest_run_loop
    async def test_single_score_route_exists(self):
        # a LAN address: fails with 502, not 404
        self.mock_storage._client.search.side_effect = OpenSearchException("test")
        status, _ = await self.get("/api/risk/scores/192.168.1.4")
        self.assertEqual(status, 502)


class TestRiskReadsAreChecked(_RiskCase):
    """Follow-up to PR #191: a partial read is a 502, never a lower score."""

    CONNS = {f"192.168.1.{i + 1}": 50 for i in range(5)}

    async def spoiled(self, path, which, change):
        self.mock_storage._client.search.side_effect = _spoil(
            _risk_search(self.CONNS), which, change
        )
        return await self.get(path)

    @unittest_run_loop
    async def test_list_fails_when_a_device_page_timed_out(self):
        self.assertEqual(
            await self.spoiled("/api/risk/scores", "devices", _timed_out),
            (502, INCOMPLETE),
        )

    @unittest_run_loop
    async def test_fails_when_a_history_page_lost_a_shard(self):
        for path in ("/api/risk/scores", "/api/risk/scores/192.168.1.1"):
            with self.subTest(path=path):
                self.assertEqual(
                    await self.spoiled(path, "history", _shard_failed),
                    (502, INCOMPLETE),
                )

    @unittest_run_loop
    async def test_fails_when_a_day_range_is_missing(self):
        for path in ("/api/risk/scores", "/api/risk/scores/192.168.1.1"):
            with self.subTest(path=path):
                self.assertEqual(
                    await self.spoiled(path, "history", _a_day_missing),
                    (502, INCOMPLETE),
                )

    @unittest_run_loop
    async def test_fails_when_a_day_range_comes_back_under_another_key(self):
        for path in ("/api/risk/scores", "/api/risk/scores/192.168.1.1"):
            with self.subTest(path=path):
                self.assertEqual(
                    await self.spoiled(path, "history", _a_day_renamed),
                    (502, INCOMPLETE),
                )

    @unittest_run_loop
    async def test_fails_when_the_findings_are_incomplete(self):
        self.smart.side_effect = QueryFailed("smart alerts: malformed page")
        for path in ("/api/risk/scores", "/api/risk/scores/192.168.1.1"):
            with self.subTest(path=path):
                self.assertEqual(
                    await self.spoiled(path, "none", _timed_out), (502, INCOMPLETE)
                )

    @unittest_run_loop
    async def test_single_fails_when_its_connection_search_timed_out(self):
        self.assertEqual(
            await self.spoiled("/api/risk/scores/192.168.1.1", "single_conn", _timed_out),
            (502, INCOMPLETE),
        )

    @unittest_run_loop
    async def test_single_fails_on_a_lower_bound_connection_total(self):
        def lower_bound(reply):
            return {**reply, "hits": {"total": {"value": 10000, "relation": "gte"}}}

        self.assertEqual(
            await self.spoiled("/api/risk/scores/192.168.1.1", "single_conn", lower_bound),
            (502, INCOMPLETE),
        )

    @unittest_run_loop
    async def test_complete_replies_still_score(self):
        status, _ = await self.spoiled("/api/risk/scores", "none", _timed_out)
        self.assertEqual(status, 200)
        status, data = await self.spoiled(
            "/api/risk/scores/192.168.1.1", "none", _timed_out
        )
        self.assertEqual((status, data["connection_count"]), (200, 50))


if __name__ == "__main__":
    unittest.main()
