"""GET /api/addresses/{ip} (NET-160): every figure exact for its window, or flagged.

The fake evaluates the real queries over raw conn/ssl/alert documents, so each count below
is checked against the documents, not against a canned reply.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from api.addresses import register_address_routes
from services.excluded_ips import build_lan_filter
from storage import snapshot_search
from tests.fake_drill_opensearch import (
    AUTH,
    WINDOW,
    DrillOpenSearch,
    alert,
    conn,
    make_app,
    ssl_session,
)

ADDR = "93.184.216.34"
PHONE, LAPTOP = "192.168.1.20", "192.168.1.30"


def outbound(client_ip, sent=None, received=None, **kw):
    """A LAN device opening a connection to ADDR; bytes only when measured."""
    fields = {"source__bytes": sent, "destination__bytes": received}
    return conn(
        client_ip, ADDR, **{k: v for k, v in fields.items() if v is not None}, **kw
    )


class AddressCase(AioHTTPTestCase):
    docs: list = []

    async def get_application(self):
        self.os = DrillOpenSearch(list(self.docs))
        return make_app(
            self.os,
            register_address_routes,
            lan_filter=build_lan_filter([(192, 168, 1)]),
            excluded_ips=[PHONE],
        )

    async def figures(self, ip=ADDR, query=WINDOW, status=200):
        resp = await self.client.get(f"/api/addresses/{ip}?{query}", headers=AUTH)
        self.assertEqual(resp.status, status, await resp.text())
        return await resp.json()


class TestValidation(AddressCase):
    async def test_a_bad_ip_or_window_is_a_400_and_no_search_runs(self):
        for ip, query in (
            ("not-an-ip", WINDOW),
            ("10.0.0.0%2F8", WINDOW),
            (ADDR, "from=now-5m"),
            (ADDR, "from=2026-11-05T12:00:00Z&to=2026-11-05T00:00:00Z"),
        ):
            body = await self.figures(ip, query, status=400)
            self.assertIn("error", body)
        self.assertEqual(self.os.bodies, [])

    async def test_the_route_needs_the_token(self):
        resp = await self.client.get(f"/api/addresses/{ADDR}")
        self.assertEqual(resp.status, 401)


class TestTotalsAndBytes(AddressCase):
    docs = [
        outbound(PHONE, sent=100, received=1000),
        outbound(LAPTOP, sent=0, received=0),  # measured, really 0
        outbound(LAPTOP),  # not measured at all
        conn(ADDR, PHONE, source__bytes=7, destination__bytes=70),  # it opened this one
        conn(ADDR, ADDR, source__bytes=5, destination__bytes=50),  # to itself: once
        conn("8.8.8.8", "1.1.1.1", source__bytes=999),  # unrelated
        outbound(PHONE, sent=1, t="2026-11-04T10:00:00.000Z"),  # outside the window
    ]

    async def test_bytes_go_the_right_way_and_coverage_is_counted(self):
        body = await self.figures()
        self.assertEqual(body["connections"], 5)
        # to it: what peers sent on their connections, what it was sent on its own, self once
        self.assertEqual(
            body["bytes_to"],
            {
                "total": 100 + 0 + 70 + 5,
                "measured": 4,
                "connections": 5,
                "partial": True,
            },
        )
        self.assertEqual(
            body["bytes_from"],
            {
                "total": 1000 + 0 + 7 + 50,
                "measured": 4,
                "connections": 5,
                "partial": True,
            },
        )
        self.assertEqual(body["first_seen"], "2026-11-05T10:00:00.000Z")
        self.assertEqual(sum(slot["n"] for slot in body["timeline"]), 5)

    async def test_an_excluded_device_still_counts_on_both_sides(self):
        body = await self.figures()
        (phone,) = [p for p in body["peers"] if p["ip"] == PHONE]
        self.assertEqual(
            phone["connections"], 2
        )  # one each way, though PHONE is excluded
        self.assertEqual((phone["bytes_to"], phone["bytes_from"]), (100 + 70, 1000 + 7))
        self.assertTrue(phone["lan"])
        self.assertFalse(phone["bytes_partial"])

    async def test_peers_add_up_to_the_connections_and_self_is_once(self):
        body = await self.figures()
        self.assertTrue(body["peers_complete"])
        self.assertEqual(sum(p["connections"] for p in body["peers"]), 5)
        (me,) = [p for p in body["peers"] if p["ip"] == ADDR]
        self.assertEqual(
            (me["connections"], me["bytes_to"], me["bytes_from"]), (1, 5, 50)
        )
        (laptop,) = [p for p in body["peers"] if p["ip"] == LAPTOP]
        self.assertTrue(laptop["bytes_partial"])  # one of its two was never measured
        self.assertFalse(body["lan"])

    async def test_every_search_uses_one_snapshot_and_both_sides(self):
        await self.figures()
        self.assertEqual({b["pit"]["id"] for b in self.os.bodies}, {"pit-0"})
        self.assertEqual(self.os.closed, ["pit-0"])
        totals = self.os.bodies[0]
        self.assertEqual(
            totals["aggs"]["to_it"]["filter"], {"term": {"destination.ip": ADDR}}
        )
        self.assertEqual(
            totals["aggs"]["from_it"]["filter"]["bool"]["must_not"],
            [{"term": {"destination.ip": ADDR}}],
        )
        self.assertNotIn("must_not", totals["query"]["bool"])  # no excluded-IP filter


class TestNothingMeasured(AddressCase):
    docs = [outbound(PHONE), outbound(LAPTOP)]

    async def test_no_byte_field_is_not_measured_rather_than_zero_traffic(self):
        body = await self.figures()
        self.assertEqual(
            body["bytes_to"],
            {"total": 0, "measured": 0, "connections": 2, "partial": True},
        )


class TestNoRecords(AddressCase):
    docs = []

    async def test_an_unseen_address_is_empty_not_an_error(self):
        body = await self.figures("2001:db8::1")
        self.assertEqual(body["ip"], "2001:db8::1")
        self.assertEqual((body["connections"], body["first_seen"]), (0, None))
        self.assertFalse(body["bytes_to"]["partial"])
        self.assertEqual(
            (body["peers"], body["ports"], body["tls_names"]), ([], [], [])
        )
        self.assertEqual(body["alerts"], 0)


class TestListsAndCaps(AddressCase):
    docs = [
        outbound(
            f"192.168.1.{i}",
            destination__port=443,
            network__transport="tcp",
            network__protocol="ssl",
        )
        for i in range(1, 6)
    ] + [outbound(PHONE, destination__port=80, network__transport="tcp")]

    async def test_ports_include_a_missing_service(self):
        body = await self.figures()
        self.assertTrue(body["ports_complete"])
        self.assertEqual(
            body["ports"],
            [
                {"port": 443, "transport": "tcp", "service": "ssl", "connections": 5},
                {"port": 80, "transport": "tcp", "service": None, "connections": 1},
            ],
        )

    async def test_a_capped_peer_list_says_it_is_incomplete(self):
        with (
            patch.object(snapshot_search, "GROUP_PAGE", 2),
            patch.object(snapshot_search, "MAX_GROUP_BUCKETS", 2),
        ):
            body = await self.figures()
        self.assertFalse(body["peers_complete"])
        self.assertEqual(body["connections"], 6)  # the totals never depend on the list


class TestTlsAndAlerts(AddressCase):
    docs = [
        ssl_session("example.com", server=ADDR),
        ssl_session("example.com", server=ADDR, status=None),
        ssl_session(None, server=ADDR),
        ssl_session("other.com", server="1.1.1.1"),
        alert(PHONE, ADDR),
        alert(ADDR, PHONE),
        alert(PHONE, ADDR, rule="SURICATA STREAM noise"),  # engine noise, not counted
        alert(PHONE, "1.1.1.1"),
    ]

    async def test_names_it_served_with_their_validation(self):
        body = await self.figures()
        self.assertTrue(body["tls_complete"])
        self.assertEqual(
            body["tls_names"],
            [
                {
                    "name": "example.com",
                    "sessions": 2,
                    "statuses": {"ok": 1, "unchecked": 1},
                },
                {"name": None, "sessions": 1, "statuses": {"ok": 1}},
            ],
        )

    async def test_alerts_count_either_side_without_engine_noise(self):
        body = await self.figures()
        self.assertEqual(body["alerts"], 2)


class TestThreatIntel(AddressCase):
    docs = []

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self._tmp.name) / "ti.json"
        patcher = patch("services.threat_intel._TI_CACHE_PATH", self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        super().setUp()

    def write(self, feeds):
        self.cache.write_text(json.dumps({"version": 2, "ip_feeds": feeds}))

    async def test_no_indicators_is_not_checked(self):
        self.assertIsNone((await self.figures())["threat_intel"])
        self.write({"et_compromised": []})
        self.assertIsNone((await self.figures())["threat_intel"])

    async def test_loaded_indicators_without_this_address_are_no_match(self):
        self.write({"et_compromised": ["1.2.3.4", "5.6.7.8"]})
        ti = (await self.figures())["threat_intel"]
        self.assertEqual(ti, {"matched": False, "feeds": [], "indicators": 2})

    async def test_a_listed_address_names_its_feed(self):
        self.write({"et_compromised": [ADDR]})
        ti = (await self.figures())["threat_intel"]
        self.assertTrue(ti["matched"])
        self.assertEqual(ti["feeds"][0]["feed"], "et_compromised")
