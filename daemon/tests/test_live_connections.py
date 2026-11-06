"""
Tests for daemon/services/live_connections.py

All tests use mocks -- no OpenSearch connection required.
Tests cover tracker logic, filtering, rate calculation, and OpenSearch integration.
"""

import unittest
from unittest.mock import MagicMock

from services.excluded_ips import build_lan_filter, lan_subnets_of
from services.live_connections import (
    RATE_WINDOW_SECONDS,
    LiveConnectionTracker,
    connection_direction,
)


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
        tracker._connections.append(
            _make_connection(source_ip="192.168.1.102", dest_ip="192.168.1.100")
        )

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
        tracker._connections = tracker._connections.__class__(
            maxlen=5
        )  # Use small maxlen for test
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

    def test_format_connection_reads_malcolm_epoch_ms_times(self):
        """#144: Malcolm 26.x writes event.start/end as epoch-ms text; they read 0 s before."""
        tracker = LiveConnectionTracker()
        source = _make_opensearch_hit()
        source["event"] = {"start": "1793683365306", "end": "1793683365561"}
        self.assertAlmostEqual(tracker._format_connection(source)["duration"], 0.255)

    def test_format_connection_prefers_length(self):
        """#144: `length` (ms) is on every record and is what the device page sorts by."""
        tracker = LiveConnectionTracker()
        source = _make_opensearch_hit()
        source["length"] = 21313625
        self.assertAlmostEqual(
            tracker._format_connection(source)["duration"], 21313.625
        )

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
        has_device_filter = any("bool" in f and "should" in f["bool"] for f in filters)
        self.assertTrue(has_device_filter)

    def test_fetch_from_opensearch_error_raises(self):
        """#96: a failure raised nothing and served the old cache as live connections."""
        from opensearchpy import OpenSearchException

        mock_client = MagicMock()
        mock_client.search.side_effect = OpenSearchException("connection error")

        tracker = LiveConnectionTracker(client=mock_client)
        tracker._connections.append(_make_connection())

        with self.assertRaises(OpenSearchException):
            tracker.fetch_from_opensearch()

    def test_fetch_without_client(self):
        """Fetch without client should return cached connections."""
        tracker = LiveConnectionTracker()
        tracker._connections.append(_make_connection())
        conns = tracker.fetch_from_opensearch()
        self.assertEqual(len(conns), 1)

    def test_connections_returned_newest_first(self):
        """get_active_connections should return newest first."""
        tracker = LiveConnectionTracker()
        tracker._connections.append(
            _make_connection(timestamp="2026-03-08T10:00:00Z", source_ip="10.0.0.1")
        )
        tracker._connections.append(
            _make_connection(timestamp="2026-03-08T11:00:00Z", source_ip="10.0.0.2")
        )

        conns = tracker.get_active_connections()
        # Newest (last added) should come first due to reversed()
        self.assertEqual(conns[0]["source_ip"], "10.0.0.2")
        self.assertEqual(conns[1]["source_ip"], "10.0.0.1")


class TestLiveDashboardQueries(unittest.TestCase):
    """Query shapes for fetch_dashboard_data's two searches."""

    def _run_dashboard(self, alert_keys=()):
        client = MagicMock()
        conn_result = {
            "hits": {
                "total": {"value": 1},
                "hits": [{"_source": _make_opensearch_hit("10.0.0.5", "1.2.3.4")}],
            },
            "aggregations": {},
        }
        alert_result = {
            "aggregations": {
                "alert_pairs": {"buckets": [{"key": k} for k in alert_keys]}
            }
        }
        client.search.side_effect = [conn_result, alert_result]
        result = LiveConnectionTracker(client=client).fetch_dashboard_data()
        bodies = [c.kwargs["body"] for c in client.search.call_args_list]
        return result, bodies

    def test_alert_pair_script_reads_ip_fields(self):
        """Malcolm maps the IPs as ip fields with no .keyword sub-field (Chain 24)."""
        _, (_, alert_body) = self._run_dashboard()
        script = alert_body["aggs"]["alert_pairs"]["terms"]["script"]["source"]
        self.assertIn("doc['source.ip']", script)
        self.assertIn("doc['destination.ip']", script)
        self.assertNotIn(".keyword", script)

    def test_alert_pair_flags_matching_connection(self):
        result, _ = self._run_dashboard(alert_keys=["1.2.3.4>10.0.0.5"])
        self.assertTrue(result["connections"][0]["has_alert"])

    def test_top_talkers_ordered_by_total_bytes(self):
        """Top talkers rank by bytes, not by doc count plus bucket_sort."""
        _, (conn_body, _) = self._run_dashboard()
        # OLD CODE START — 2026-11-06 (O11): the terms agg moved under the LAN filter
        # agg = conn_body["aggs"]["top_talkers"]
        # OLD CODE END
        agg = conn_body["aggs"]["top_talkers"]["aggs"]["ips"]
        self.assertEqual(agg["terms"]["order"], {"total_bytes": "desc"})
        self.assertIn("total_bytes", agg["aggs"])
        self.assertNotIn("bucket_sort", agg["aggs"])

    def test_active_devices_counts_lan_sources_only(self):
        """79 "devices" for 38 on the G11: each device's IPv6 link-local counted too."""
        client = MagicMock()
        client.search.side_effect = [
            {
                "hits": {"total": {"value": 1690}, "hits": []},
                "aggregations": {
                    "active_devices": {"doc_count": 900, "n": {"value": 38}}
                },
            },
            {"aggregations": {"alert_pairs": {"buckets": []}}},
        ]
        lan = {"terms": {"source.ip": ["192.168.1.0/24"]}}
        result = LiveConnectionTracker(client=client).fetch_dashboard_data(
            lan_filter=lan
        )
        agg = client.search.call_args_list[0].kwargs["body"]["aggs"]["active_devices"]
        self.assertEqual(agg["filter"], lan)
        self.assertEqual(result["stats"]["active_devices"], 38)
        self.assertEqual(result["stats"]["connections_in_window"], 1690)


LAN = [(192, 168, 1)]


class TestConnectionDirection(unittest.TestCase):
    """O2: direction from the LAN subnets, in the plan's order, not from dest_port < 1024."""

    def test_special_addresses_are_local(self):
        for src, dst in [
            ("192.168.1.20", "224.0.0.251"),  # mDNS
            ("0.0.0.0", "255.255.255.255"),  # DHCP discover
            ("203.0.113.9", "192.168.1.255"),  # subnet broadcast, not "in"
            ("169.254.10.2", "192.168.1.5"),  # link-local
            ("127.0.0.1", "8.8.8.8"),  # loopback
            ("fe80::1", "ff02::fb"),  # IPv6 link-local to mDNS
        ]:
            self.assertEqual(connection_direction(src, dst, LAN), "local", (src, dst))

    def test_lan_to_lan_is_local(self):
        self.assertEqual(
            connection_direction("192.168.1.20", "192.168.1.30", LAN), "local"
        )

    def test_out_and_in_ignore_the_port(self):
        # a LAN device to a WireGuard port above 1024 read "IN" under the port guess
        self.assertEqual(
            connection_direction("192.168.1.20", "93.184.216.34", LAN), "out"
        )
        self.assertEqual(
            connection_direction("93.184.216.34", "192.168.1.20", LAN), "in"
        )

    def test_isp_private_and_cgnat_ends_are_unknown(self):
        self.assertEqual(
            connection_direction("10.181.2.3", "192.168.1.20", LAN), "unknown"
        )
        self.assertEqual(
            connection_direction("192.168.1.20", "100.64.0.1", LAN), "unknown"
        )

    def test_ipv6_outside_the_ipv4_lan_rule_is_unknown(self):
        self.assertEqual(
            connection_direction("2a00:1450:4001::5", "2606:4700::1111", LAN), "unknown"
        )

    def test_no_detected_subnets_falls_back_to_rfc1918(self):
        self.assertEqual(connection_direction("10.0.0.5", "8.8.8.8", []), "out")

    def test_unreadable_address_is_unknown(self):
        self.assertEqual(connection_direction("", "8.8.8.8", LAN), "unknown")

    def test_lan_filter_carries_its_subnets(self):
        self.assertEqual(
            lan_subnets_of(build_lan_filter([(10, -1, -1), (192, 168, 1)])),
            [(10, -1, -1), (192, 168, 1)],
        )
        self.assertEqual(lan_subnets_of(build_lan_filter([])), [])
        self.assertEqual(lan_subnets_of({"terms": {"source.ip": []}}), [])

    def test_dashboard_rows_carry_the_direction(self):
        client = MagicMock()
        inbound = _make_opensearch_hit("93.184.216.34", "192.168.1.100", dest_port=22)
        client.search.side_effect = [
            {
                "hits": {
                    "total": {"value": 2},
                    "hits": [
                        {"_source": _make_opensearch_hit(dest_port=51820)},
                        {"_source": inbound},
                    ],
                },
                "aggregations": {},
            },
            {"aggregations": {"alert_pairs": {"buckets": []}}},
        ]
        result = LiveConnectionTracker(client=client).fetch_dashboard_data(
            lan_filter=build_lan_filter(LAN)
        )
        self.assertEqual([c["direction"] for c in result["connections"]], ["out", "in"])


def _dashboard_with(aggregations, total=0, hits=()):
    client = MagicMock()
    client.search.side_effect = [
        {
            "hits": {"total": {"value": total}, "hits": [{"_source": h} for h in hits]},
            "aggregations": aggregations,
        },
        {"aggregations": {"alert_pairs": {"buckets": []}}},
    ]
    lan = build_lan_filter(LAN)
    result = LiveConnectionTracker(client=client).fetch_dashboard_data(lan_filter=lan)
    return result, client.search.call_args_list[0].kwargs["body"], lan


def _located(lat, lon):
    source = {"destination": {"geo": {"location": {"lat": lat, "lon": lon}}}}
    return {"hits": {"hits": [{"_source": source}]}}


class TestLiveDashboardFigures(unittest.TestCase):
    def test_map_counts_come_from_the_country_buckets(self):
        """O3: NL has 12 connections but only 5 in its listed city; the dot said 5."""
        cities = [
            {
                "key": "Amsterdam",
                "doc_count": 5,
                "country_code": {"buckets": [{"key": "NL"}]},
                "location": _located(52.37, 4.9),
            },
            {
                "key": "Frankfurt",
                "doc_count": 3,
                "country_code": {"buckets": [{"key": "DE"}]},
                "location": _located(50.11, 8.68),
            },
        ]
        countries = [
            {
                "key": "NL",
                "doc_count": 12,
                "country_name": {"buckets": [{"key": "Netherlands"}]},
                "top_city": {"buckets": [{"key": "Amsterdam"}]},
                "total_bytes": {"value": 1200},
                "location": _located(51.9, 4.5),  # Rotterdam, the newest record
            },
            {
                "key": "DE",
                "doc_count": 3,
                "country_name": {"buckets": [{"key": "Germany"}]},
                "top_city": {"buckets": [{"key": "Frankfurt"}]},
                "total_bytes": {"value": 300},
                "location": _located(50.11, 8.68),
            },
            {
                "key": "JP",
                "doc_count": 2,
                "country_name": {"buckets": [{"key": "Japan"}]},
                "top_city": {"buckets": []},
                "total_bytes": {"value": 200},
                "location": _located(35.68, 139.69),
            },
        ]
        result, _, _ = _dashboard_with(
            {
                "geo_destinations": {"buckets": cities},
                "geo_countries": {"buckets": countries},
            }
        )
        arcs = {a["country_code"]: a for a in result["geo_arcs"]}
        self.assertEqual(len(result["geo_arcs"]), 3)  # one per country
        self.assertEqual(
            {cc: a["count"] for cc, a in arcs.items()}, {"NL": 12, "DE": 3, "JP": 2}
        )
        self.assertEqual((arcs["NL"]["lat"], arcs["NL"]["lon"]), (52.37, 4.9))
        self.assertEqual(arcs["NL"]["bytes"], 1200)
        self.assertEqual((arcs["JP"]["lat"], arcs["JP"]["lon"]), (35.68, 139.69))

    def test_protocol_counts_partition_the_window(self):
        """O6: counts, not percentages; other and unknown complete the split."""
        result, body, _ = _dashboard_with(
            {
                "protocols": {
                    "sum_other_doc_count": 1,
                    "buckets": [
                        {"key": "tcp", "doc_count": 70},
                        {"key": "udp", "doc_count": 20},
                        {"key": "icmp", "doc_count": 3},
                        {"key": "ipv6-icmp", "doc_count": 2},
                    ],
                },
                "protocols_missing": {"doc_count": 4},
            },
            total=100,
        )
        self.assertEqual(
            body["aggs"]["protocols_missing"],
            {"missing": {"field": "network.transport"}},
        )
        self.assertEqual(
            result["protocols"],
            {"tcp": 70, "udp": 20, "icmp": 3, "other": 3, "unknown": 4},
        )
        self.assertEqual(
            sum(result["protocols"].values()), result["stats"]["connections_in_window"]
        )

    def test_top_talkers_are_lan_sources_only(self):
        """O11: internet hosts and an ISP's gateway ranked among the "devices"."""
        result, body, lan = _dashboard_with(
            {
                "top_talkers": {
                    "doc_count": 9,
                    "ips": {
                        "buckets": [
                            {
                                "key": "192.168.1.20",
                                "doc_count": 7,
                                "total_bytes": {"value": 9000},
                            }
                        ]
                    },
                }
            }
        )
        self.assertEqual(body["aggs"]["top_talkers"]["filter"], lan)
        self.assertEqual(
            result["top_talkers"],
            [{"ip": "192.168.1.20", "bytes": 9000, "connections": 7}],
        )

    def test_feed_bytes_use_the_talkers_byte_basis(self):
        """O11: rows summed payload bytes (client/server); talkers sum source + destination."""
        hit = _make_opensearch_hit()
        hit["source"]["bytes"], hit["destination"]["bytes"] = 1500, 9000
        hit["client"]["bytes"], hit["server"]["bytes"] = 1000, 8000
        self.assertEqual(
            LiveConnectionTracker()._format_connection(hit)["bytes"], 10_500
        )


class TestLiveQueryFailures(unittest.TestCase):
    """#96: a failed live query raises; the handlers answer 502 instead of zeros or "no alert"."""

    def _client(self, *results):
        client = MagicMock()
        client.search.side_effect = list(results)
        return client

    def test_dashboard_connections_failure_raises(self):
        """Was an all-zero dashboard: 0 devices, 0 bytes/s, no connections."""
        from opensearchpy import OpenSearchException

        client = self._client(OpenSearchException("timeout"))
        with self.assertRaises(OpenSearchException):
            LiveConnectionTracker(client=client).fetch_dashboard_data()

    def test_dashboard_alert_failure_raises(self):
        """Was every connection shown without its alert flag."""
        from opensearchpy import OpenSearchException

        conns = {"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}}
        client = self._client(conns, OpenSearchException("timeout"))
        with self.assertRaises(OpenSearchException):
            LiveConnectionTracker(client=client).fetch_dashboard_data()

    def test_detail_failure_raises(self):
        """Was a drawer reading 0 alerts or 0 connections for a pair it never checked."""
        from opensearchpy import OpenSearchException

        ok = {"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}}
        for failing in range(3):  # session, alerts, history
            results = [ok, ok, ok]
            results[failing] = OpenSearchException("timeout")
            client = self._client(*results)
            with self.assertRaises(OpenSearchException, msg=failing):
                LiveConnectionTracker(client=client).fetch_connection_detail(
                    src_ip="10.0.0.5", dst_ip="1.2.3.4"
                )

    def test_connections_endpoint_answers_502(self):
        import asyncio

        from aiohttp import web
        from aiohttp.test_utils import make_mocked_request
        from opensearchpy import OpenSearchException

        from api.live import handle_live_connections

        app = web.Application()
        app["live_tracker"] = LiveConnectionTracker(
            client=self._client(OpenSearchException("timeout"))
        )
        resp = asyncio.run(
            handle_live_connections(
                make_mocked_request("GET", "/api/live/connections", app=app)
            )
        )
        self.assertEqual(resp.status, 502)


if __name__ == "__main__":
    unittest.main()
