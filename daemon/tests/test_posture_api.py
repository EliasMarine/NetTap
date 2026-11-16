"""
Tests for daemon/api/posture.py (GET /api/posture/{category}).

All OpenSearch calls are mocked. The posture category pages explain the Encryption, DNS security
and Patch currency scores; these tests hold the base query to /api/traffic/protocols', the device
lists to LAN sources with a bound, and the advice inputs to fixed filters.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from opensearchpy import OpenSearchException

from api.posture import (
    DEVICE_ROWS,
    PRIVATE_LOCAL,
    PUBLIC,
    UNKNOWN,
    logs_query,
    register_posture_routes,
    scope,
)
from api.traffic import DNS_PLAIN, register_traffic_routes
from services.excluded_ips import PAYLOAD_BOTH, build_excluded_ips_filter
from services.iot_monitor import (
    ENCRYPTED_PORTS,
    ENCRYPTED_PROTOCOLS,
    ICMP_TRANSPORTS,
    LOCAL_SERVICE_PORTS,
    MULTICAST_BROADCAST,
)
from storage.manager import RetentionConfig, StorageManager

LAN_FILTER = {"terms": {"source.ip": ["192.168.1.0/24"]}}


def _make_mock_storage():
    config = RetentionConfig()
    with patch.object(StorageManager, "_create_client") as mock_create:
        mock_client = MagicMock()
        mock_create.return_value = mock_client
        storage = StorageManager(config, "http://localhost:9200")
    return storage, mock_client


def _reply(**aggs):
    return {
        "timed_out": False,
        "_shards": {"total": 1, "successful": 1, "failed": 0},
        "aggregations": aggs,
    }


def _buckets(*pairs, other=0, **sub):
    """terms buckets from (key, count) pairs; sub maps key -> extra bucket fields."""
    return {
        "sum_other_doc_count": other,
        "buckets": [
            {"key": k, "doc_count": n, **sub.get(str(k), {})} for k, n in pairs
        ],
    }


def _all_terms(node, found=None):
    """Every terms aggregation body in a query tree."""
    found = [] if found is None else found
    if isinstance(node, dict):
        if (
            "terms" in node
            and isinstance(node["terms"], dict)
            and "field" in node["terms"]
        ):
            found.append(node["terms"])
        for v in node.values():
            _all_terms(v, found)
    elif isinstance(node, list):
        for v in node:
            _all_terms(v, found)
    return found


class PostureTestCase(AioHTTPTestCase):
    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        app["lan_filter"] = LAN_FILTER
        app["excluded_ips"] = ["192.168.1.199"]
        register_posture_routes(app)
        register_traffic_routes(app, self.storage)
        return app

    def body(self, call=0):
        return self.mock_client.search.call_args_list[call].kwargs["body"]


class TestRoute(PostureTestCase):
    @unittest_run_loop
    async def test_unknown_category_is_a_404_that_never_echoes_the_input(self):
        resp = await self.client.request("GET", "/api/posture/%3Cscript%3E")
        self.assertEqual(resp.status, 404)
        self.assertEqual(await resp.json(), {"error": "Unknown posture category"})
        self.mock_client.search.assert_not_called()

    # OLD CODE START — NET-308: alert-response has its own route now (TestAlertResponse)
    # @unittest_run_loop
    # async def test_the_categories_without_traffic_detail_are_404(self):
    #     resp = await self.client.request("GET", "/api/posture/alert-response")
    #     self.assertEqual(resp.status, 404)
    # OLD CODE END
    @unittest_run_loop
    async def test_the_categories_without_traffic_detail_are_404(self):
        resp = await self.client.request("GET", "/api/posture/network-segmentation")
        self.assertEqual(resp.status, 404)

    @unittest_run_loop
    async def test_unreadable_from_is_a_400(self):
        resp = await self.client.request("GET", "/api/posture/encryption?from=now-5m")
        self.assertEqual(resp.status, 400)
        self.mock_client.search.assert_not_called()

    @unittest_run_loop
    async def test_opensearch_error_is_a_502_with_fixed_text(self):
        self.mock_client.search.side_effect = OpenSearchException("secret detail")
        resp = await self.client.request("GET", "/api/posture/encryption")
        self.assertEqual(resp.status, 502)
        self.assertEqual(await resp.json(), {"error": "The posture search failed"})

    @unittest_run_loop
    async def test_failed_shards_are_a_502(self):
        reply = _reply(eligible={"doc_count": 0})
        reply["_shards"]["failed"] = 1
        self.mock_client.search.return_value = reply
        resp = await self.client.request("GET", "/api/posture/encryption")
        self.assertEqual(resp.status, 502)
        self.assertEqual(
            await resp.json(), {"error": "The posture search was incomplete"}
        )

    @unittest_run_loop
    # OLD CODE: async def test_base_query_and_filters_equal_the_protocols_endpoint(self):
    # (NET-308: the filters are one definition each in api/traffic.py, so only the query is checked)
    async def test_base_query_equals_the_protocols_endpoint(self):
        """The totals here must equal the score's inputs, so the query that feeds them must match."""
        self.mock_client.search.return_value = _reply(eligible={"doc_count": 0})
        await self.client.request(
            "GET",
            "/api/posture/encryption?from=2026-11-01T00:00:00Z&to=2026-11-02T00:00:00Z",
        )
        posture = self.body()
        self.mock_client.search.reset_mock()
        self.mock_client.search.return_value = {
            **_reply(
                by_proto={"buckets": []},
                by_service={"buckets": []},
                # OLD CODE: encryption={"doc_count": 0, "encrypted": {"doc_count": 0}}, (NET-308)
                encryption={
                    "doc_count": 0,
                    "both": {"doc_count": 0, "encrypted": {"doc_count": 0}},
                },
                dns_plain={"doc_count": 0, "private_local": {"doc_count": 0}},
                dns_over_tls={"doc_count": 0, "private_local": {"doc_count": 0}},
                legacy={"doc_count": 0},
                connections={"doc_count": 0},
                quic={"doc_count": 0},
                ssl_only={"doc_count": 0},
                unlabelled={
                    "doc_count": 0,
                    "icmp": {"doc_count": 0},
                    "one_way": {"doc_count": 0},
                },
            )
        }
        await self.client.request(
            "GET",
            "/api/traffic/protocols?from=2026-11-01T00:00:00Z&to=2026-11-02T00:00:00Z",
        )
        protocols = self.body()
        self.assertEqual(posture["query"], protocols["query"])
        # OLD CODE START — NET-308: held posture's copies of the filters equal to protocols' own
        # self.assertEqual(ELIGIBLE, protocols["aggs"]["encryption"]["filter"])
        # self.assertEqual(DNS_PLAIN, protocols["aggs"]["dns_plain"]["filter"])
        # self.assertEqual(
        #     {"term": {"destination.port": 853}},
        #     protocols["aggs"]["dns_over_tls"]["filter"],
        # )
        # OLD CODE END


class TestEncryption(PostureTestCase):
    def search_reply(self):
        # NET-308: every figure is the scored set, connections with data both ways
        return _reply(
            eligible={
                "doc_count": 1400,
                "both": {
                    "doc_count": 1000,
                    "encrypted": {"doc_count": 150},
                    "unencrypted": {
                        "doc_count": 850,
                        "private_local": {"doc_count": 30},
                        "risky": {
                            "buckets": {
                                "telnet": {"doc_count": 2},
                                "ftp": {"doc_count": 0},
                                "http": {"doc_count": 27},
                            }
                        },
                        "services": _buckets(("unknown", 800), ("http", 27), other=23),
                        "devices": {
                            "doc_count": 840,
                            "rows": _buckets(
                                ("192.168.1.205", 797),
                                other=43,
                                **{
                                    "192.168.1.205": {
                                        "private_local": {"doc_count": 0},
                                        "services": _buckets(
                                            ("unknown", 790), ("http", 7)
                                        ),
                                        "ports": _buckets((6881, 210), (51413, 40)),
                                    }
                                },
                            ),
                        },
                    },
                },
            }
        )

    @unittest_run_loop
    async def test_reply_maps_every_figure(self):
        self.mock_client.search.return_value = self.search_reply()
        resp = await self.client.request("GET", "/api/posture/encryption")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["category"], "encryption")
        self.assertEqual(data["excluded_ips"], ["192.168.1.199"])
        self.assertEqual((data["eligible"], data["encrypted"]), (1000, 150))
        un = data["unencrypted"]
        # OLD CODE: (un["total"], un["payload_both"], un["private_local"]), (850, 45, 30) (NET-308)
        self.assertNotIn("payload_both", un)
        self.assertEqual((un["total"], un["private_local"]), (850, 30))
        self.assertEqual(
            un["services"],
            [{"name": "unknown", "count": 800}, {"name": "http", "count": 27}],
        )
        self.assertEqual(un["services_other"], 23)
        self.assertEqual(un["risky"]["telnet"]["count"], 2)
        self.assertEqual(un["risky"]["telnet"]["logs_query"], logs_query("telnet"))
        self.assertEqual(un["risky"]["ftp"]["count"], 0)
        self.assertEqual(data["devices"]["lan"], 840)
        self.assertEqual(data["devices"]["other"], 43)
        self.assertEqual(
            data["devices"]["rows"],
            [
                {
                    "ip": "192.168.1.205",
                    "connections": 797,
                    "private_local": 0,
                    "services": [
                        {"name": "unknown", "count": 790},
                        {"name": "http", "count": 7},
                    ],
                    "ports": [
                        {"port": 6881, "count": 210},
                        {"port": 51413, "count": 40},
                    ],
                }
            ],
        )

    @unittest_run_loop
    async def test_query_shape(self):
        """Devices are LAN sources only; every list is bounded; the advice reads fixed filters."""
        self.mock_client.search.return_value = self.search_reply()
        await self.client.request("GET", "/api/posture/encryption")
        body = self.body()
        self.assertEqual(body["size"], 0)
        self.assertEqual(
            body["query"]["bool"]["must_not"],
            build_excluded_ips_filter(["192.168.1.199"]),
        )
        self.assertNotEqual(body["query"]["bool"]["must_not"], [])
        # OLD CODE: un = body["aggs"]["eligible"]["aggs"]["unencrypted"] (NET-308: under both)
        both = body["aggs"]["eligible"]["aggs"]["both"]
        self.assertIs(both["filter"], PAYLOAD_BOTH)
        un = both["aggs"]["unencrypted"]
        self.assertEqual(un["aggs"]["devices"]["filter"], LAN_FILTER)
        self.assertEqual(
            un["aggs"]["devices"]["aggs"]["rows"]["terms"]["size"], DEVICE_ROWS
        )
        self.assertEqual(un["aggs"]["private_local"]["filter"], PRIVATE_LOCAL)
        risky = un["aggs"]["risky"]["filters"]["filters"]
        self.assertEqual(set(risky), {"telnet", "ftp", "http"})
        self.assertIn(
            {"term": {"destination.port": 23}}, risky["telnet"]["bool"]["should"]
        )
        for terms in _all_terms(body):
            self.assertIn("size", terms)

    @unittest_run_loop
    async def test_empty_buckets_give_empty_lists(self):
        self.mock_client.search.return_value = _reply(eligible={"doc_count": 0})
        data = await (
            await self.client.request("GET", "/api/posture/encryption")
        ).json()
        self.assertEqual(data["unencrypted"]["total"], 0)
        self.assertEqual(data["unencrypted"]["services"], [])
        self.assertEqual(data["devices"], {"lan": 0, "other": 0, "rows": []})


class TestLogsQuery(unittest.TestCase):
    def test_telnet_holds_its_clause_and_every_exclusion(self):
        q = logs_query("telnet")
        self.assertTrue(
            q.startswith('(network.protocol:("telnet") OR destination.port:(23))')
        )
        for port in [*LOCAL_SERVICE_PORTS, *ENCRYPTED_PORTS]:
            self.assertIn(str(port), q)
        for value in [
            *ICMP_TRANSPORTS,
            *MULTICAST_BROADCAST,
            *ENCRYPTED_PROTOCOLS,
            "stun",
        ]:
            self.assertIn(f'"{value}"', q)
        self.assertEqual(q.count(" AND NOT "), 6)
        # NET-308: the link lists the scored records, those with data both ways
        self.assertTrue(
            q.endswith(" AND zeek.conn.orig_bytes:>0 AND zeek.conn.resp_bytes:>0")
        )

    def test_http_has_no_port_clause(self):
        self.assertTrue(
            logs_query("http").startswith('network.protocol:("http") AND NOT')
        )


class TestScope(unittest.TestCase):
    def test_scopes(self):
        self.assertEqual(scope("192.168.1.174"), "private_local")
        self.assertEqual(scope("fd00::53"), "private_local")  # IPv6 ULA
        self.assertEqual(scope("fe80::1"), "private_local")
        # private but outside a configured 192.168.1.0/24 LAN (a VPN): still only "private or local-scope"
        self.assertEqual(scope("10.8.0.1"), "private_local")
        self.assertEqual(scope("100.64.1.1"), "unknown")
        self.assertEqual(scope("not an ip"), "unknown")
        self.assertEqual(scope("8.8.8.8"), "public")
        self.assertEqual(scope("2606:4700:4700::1111"), "public")


class TestDns(PostureTestCase):
    def search_one(self, resolvers=None):
        return _reply(
            plain={
                "doc_count": 500,
                "private_local": {"doc_count": 300},
                "unknown": {"doc_count": 5},
                "public": {
                    "doc_count": 195,
                    "devices": {
                        "doc_count": 190,
                        "rows": _buckets(
                            ("10.10.0.164", 120),
                            other=70,
                            **{
                                "10.10.0.164": {
                                    "resolvers": _buckets(
                                        ("8.8.8.8", 120),
                                        **{
                                            "8.8.8.8": {
                                                "org": _buckets(
                                                    ("AS15169 Google LLC", 120)
                                                )
                                            }
                                        },
                                    )
                                }
                            },
                        ),
                    },
                },
                "resolvers": resolvers
                or _buckets(
                    ("192.168.1.174", 250),
                    ("8.8.8.8", 120),
                    ("fd00::53", 50),
                    **{"8.8.8.8": {"org": _buckets(("AS15169 Google LLC", 120))}},
                ),
            },
            # OLD CODE: over_tls={"doc_count": 200, "resolvers": _buckets(("9.9.9.9", 200))}, (NET-308)
            over_tls={
                "doc_count": 200,
                "private_local": {"doc_count": 30},
                "resolvers": _buckets(("9.9.9.9", 200)),
            },
        )

    @unittest_run_loop
    async def test_local_resolvers_get_their_own_upstream_counts(self):
        """A resolver's upstream comes from its own filter, never from a device top-10 list
        (192.168.1.174 is in no device list here), and an IPv6 ULA resolver counts as local."""
        self.mock_client.search.side_effect = [
            self.search_one(),
            _reply(
                upstream={
                    "buckets": {
                        "192.168.1.174": {
                            "doc_count": 2400,
                            "plain_public": {"doc_count": 40},
                            "dot": {"doc_count": 1400},
                        },
                        "fd00::53": {
                            "doc_count": 0,
                            "plain_public": {"doc_count": 0},
                            "dot": {"doc_count": 0},
                        },
                    }
                }
            ),
        ]
        resp = await self.client.request("GET", "/api/posture/dns-security")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual((data["plain"], data["over_tls"]), (500, 200))
        self.assertEqual(
            data["plain_scope"], {"private_local": 300, "unknown": 5, "public": 195}
        )
        # NET-308 review: the DoT the score leaves out, so 500 - 300 and 200 - 30 are its figures
        self.assertEqual(data["over_tls_scope"], {"private_local": 30})
        by_ip = {r["ip"]: r for r in data["resolvers"]["plain"]}
        self.assertEqual(by_ip["192.168.1.174"]["scope"], "private_local")
        self.assertEqual(
            by_ip["192.168.1.174"]["upstream"], {"plain_public": 40, "dot": 1400}
        )
        self.assertEqual(by_ip["fd00::53"]["upstream"], {"plain_public": 0, "dot": 0})
        self.assertEqual(
            by_ip["8.8.8.8"],
            {
                "ip": "8.8.8.8",
                "count": 120,
                "org": "AS15169 Google LLC",
                "scope": "public",
                "upstream": None,
            },
        )
        self.assertEqual(
            data["resolvers"]["over_tls"],
            [{"ip": "9.9.9.9", "count": 200, "org": None, "scope": "public"}],
        )
        self.assertEqual(
            data["public_devices"],
            {
                "lan": 190,
                "other": 70,
                "rows": [
                    {
                        "ip": "10.10.0.164",
                        "count": 120,
                        "resolvers": [
                            {"ip": "8.8.8.8", "count": 120, "org": "AS15169 Google LLC"}
                        ],
                    }
                ],
            },
        )
        second = self.body(1)["aggs"]["upstream"]
        self.assertEqual(
            set(second["filters"]["filters"]), {"192.168.1.174", "fd00::53"}
        )
        self.assertEqual(
            second["filters"]["filters"]["fd00::53"],
            {"term": {"source.ip": "fd00::53"}},
        )
        self.assertEqual(
            second["aggs"]["plain_public"]["filter"],
            {"bool": {"filter": [DNS_PLAIN, PUBLIC]}},
        )

    @unittest_run_loop
    async def test_no_second_search_without_a_local_resolver(self):
        self.mock_client.search.return_value = self.search_one(
            resolvers=_buckets(("8.8.8.8", 120))
        )
        data = await (
            await self.client.request("GET", "/api/posture/dns-security")
        ).json()
        self.assertEqual(self.mock_client.search.call_count, 1)
        self.assertIsNone(data["resolvers"]["plain"][0]["upstream"])

    @unittest_run_loop
    async def test_scope_filters_are_disjoint_and_exact(self):
        self.mock_client.search.return_value = self.search_one(
            resolvers=_buckets(("8.8.8.8", 1))
        )
        await self.client.request("GET", "/api/posture/dns-security")
        plain = self.body()["aggs"]["plain"]["aggs"]
        self.assertEqual(plain["private_local"]["filter"], PRIVATE_LOCAL)
        over_tls = self.body()["aggs"]["over_tls"]["aggs"]
        self.assertEqual(over_tls["private_local"]["filter"], PRIVATE_LOCAL)
        self.assertEqual(plain["unknown"]["filter"], UNKNOWN)
        self.assertEqual(
            plain["public"]["filter"], {"bool": {"must_not": [PRIVATE_LOCAL, UNKNOWN]}}
        )
        self.assertIn("fc00::/7", PRIVATE_LOCAL["terms"]["destination.ip"])
        for terms in _all_terms(self.body()):
            self.assertIn("size", terms)

    @unittest_run_loop
    async def test_failed_second_search_is_a_502(self):
        failed = _reply(upstream={"buckets": {}})
        failed["timed_out"] = True
        self.mock_client.search.side_effect = [self.search_one(), failed]
        resp = await self.client.request("GET", "/api/posture/dns-security")
        self.assertEqual(resp.status, 502)


class TestPatch(PostureTestCase):
    @unittest_run_loop
    async def test_reply_and_query(self):
        self.mock_client.search.return_value = _reply(
            legacy={
                "doc_count": 27500,
                "services": _buckets(
                    ("http", 27494),
                    ("telnet", 6),
                    **{
                        "http": {
                            "devices": {
                                "doc_count": 27000,
                                "rows": _buckets(
                                    ("192.168.1.138", 7000),
                                    other=20000,
                                    **{
                                        "192.168.1.138": {
                                            "ports": _buckets((8080, 7000)),
                                            "destinations": _buckets(
                                                ("192.168.1.1", 7000)
                                            ),
                                        }
                                    },
                                ),
                            }
                        }
                    },
                ),
            }
        )
        resp = await self.client.request("GET", "/api/posture/patch-currency")
        data = await resp.json()
        self.assertEqual(data["unique_connections"], 27500)
        self.assertEqual([p["name"] for p in data["protocols"]], ["http", "telnet"])
        http = data["protocols"][0]
        self.assertEqual(http["devices"]["other"], 20000)
        self.assertEqual(
            http["devices"]["rows"][0],
            {
                "ip": "192.168.1.138",
                "connections": 7000,
                "ports": [{"port": 8080, "count": 7000}],
                "destinations": [{"ip": "192.168.1.1", "count": 7000}],
            },
        )
        self.assertEqual(
            data["protocols"][1]["devices"], {"lan": 0, "other": 0, "rows": []}
        )
        services = self.body()["aggs"]["legacy"]["aggs"]["services"]["terms"]
        self.assertEqual(services["include"], ["http", "ftp", "telnet", "pop3", "imap"])
        self.assertEqual(services["size"], 5)


if __name__ == "__main__":
    unittest.main()
