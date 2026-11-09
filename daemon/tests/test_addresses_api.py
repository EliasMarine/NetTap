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
        # OLD CODE START — NET-160 review: the address is no longer its own peer
        # self.assertEqual(sum(p["connections"] for p in body["peers"]), 5)
        # (me,) = [p for p in body["peers"] if p["ip"] == ADDR]
        # self.assertEqual(
        #     (me["connections"], me["bytes_to"], me["bytes_from"]), (1, 5, 50)
        # )
        # OLD CODE END
        # Every connection but the one to itself, which stays in the totals only
        self.assertEqual(sum(p["connections"] for p in body["peers"]), 5 - 1)
        self.assertNotIn(ADDR, [p["ip"] for p in body["peers"]])
        self.assertEqual(body["connections"], 5)
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
        # OLD CODE START — NET-160 review: one row per port, its services listed
        # self.assertEqual(
        #     body["ports"],
        #     [
        #         {"port": 443, "transport": "tcp", "service": "ssl", "connections": 5},
        #         {"port": 80, "transport": "tcp", "service": None, "connections": 1},
        #     ],
        # )
        # OLD CODE END
        self.assertEqual(
            body["ports"],
            [
                {
                    "port": 443,
                    "transport": "tcp",
                    "services": ["ssl"],
                    "connections": 5,
                },
                {"port": 80, "transport": "tcp", "services": [], "connections": 1},
            ],
        )

    async def test_a_capped_peer_list_says_it_is_incomplete(self):
        # OLD CODE START — NET-160 review: the drill-down lists stop at LIST_CAP
        # with (
        #     patch.object(snapshot_search, "GROUP_PAGE", 2),
        #     patch.object(snapshot_search, "MAX_GROUP_BUCKETS", 2),
        # ):
        # OLD CODE END
        with (
            patch.object(snapshot_search, "GROUP_PAGE", 2),
            patch("api.addresses.LIST_CAP", 2),
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
        # OLD CODE START — NET-160 review: the window's own alerts are checked too, so an
        # empty cache is "no listing alert and nothing cached", not "not checked"
        # self.assertIsNone((await self.figures())["threat_intel"])
        # self.write({"et_compromised": []})
        # self.assertIsNone((await self.figures())["threat_intel"])
        # OLD CODE END
        # OLD CODE: unlisted = {"matched": False, "feeds": [], "indicators": 0} (NET-228: + in_window)
        unlisted = {"matched": False, "feeds": [], "indicators": 0, "in_window": False}
        self.assertEqual((await self.figures())["threat_intel"], unlisted)
        self.write({"et_compromised": []})
        self.assertEqual((await self.figures())["threat_intel"], unlisted)

    async def test_loaded_indicators_without_this_address_are_no_match(self):
        self.write({"et_compromised": ["1.2.3.4", "5.6.7.8"]})
        ti = (await self.figures())["threat_intel"]
        # OLD CODE: …{"matched": False, "feeds": [], "indicators": 2}) (NET-228: + in_window)
        self.assertEqual(
            ti, {"matched": False, "feeds": [], "indicators": 2, "in_window": False}
        )

    async def test_a_listed_address_names_its_feed(self):
        self.write({"et_compromised": [ADDR]})
        ti = (await self.figures())["threat_intel"]
        self.assertTrue(ti["matched"])
        self.assertEqual(ti["feeds"][0]["feed"], "et_compromised")


def test_a_peer_with_no_byte_count_reads_not_measured_not_zero():
    from api.addresses import _peer_row

    # parts are (connections, to, to_n, from, from_n, last): two sessions, none measured
    row = _peer_row("192.0.2.7", [(2, 0, 0, 0, 0, None)], lambda _ip: False)
    assert (row["bytes_to"], row["bytes_from"], row["bytes_partial"]) == (
        None,
        None,
        True,
    )
    # one direction measured on one of two sessions: a lower bound, still a number
    row = _peer_row("192.0.2.7", [(2, 40, 1, 0, 0, None)], lambda _ip: False)
    assert (row["bytes_to"], row["bytes_from"], row["bytes_partial"]) == (
        40,
        None,
        True,
    )


# ---------------------------------------------------------------------------
# NET-160 review
# ---------------------------------------------------------------------------


class TestPortServices(AddressCase):
    docs = [
        # one UDP/443 connection Zeek logged with two services
        outbound(
            PHONE,
            destination__port=443,
            network__transport="udp",
            network__protocol=["quic", "ssl"],
        ),
        outbound(
            LAPTOP,
            destination__port=443,
            network__transport="udp",
            network__protocol="quic",
        ),
        outbound(
            LAPTOP,
            destination__port=443,
            network__transport="tcp",
            network__protocol="ssl",
        ),
    ]

    async def test_a_connection_with_two_services_counts_once(self):
        body = await self.figures()
        self.assertEqual(sum(p["connections"] for p in body["ports"]), 3)
        self.assertEqual(
            body["ports"][0],
            {
                "port": 443,
                "transport": "udp",
                "services": ["quic", "ssl"],
                "connections": 2,
            },
        )
        self.assertEqual(body["ports"][1]["services"], ["ssl"])


class TestTlsNameSpellings(AddressCase):
    docs = [
        ssl_session("Example.com", server=ADDR),
        ssl_session("example.com.", server=ADDR, status="self signed certificate"),
        ssl_session("example.com", server=ADDR),
        ssl_session("not a host!", server=ADDR),
        ssl_session(None, server=ADDR),
    ]

    async def test_spellings_of_one_name_are_one_row(self):
        rows = {r["name"]: r for r in (await self.figures())["tls_names"]}
        self.assertEqual(set(rows), {"example.com", "not a host!", None})
        self.assertEqual(rows["example.com"]["sessions"], 3)
        self.assertEqual(
            rows["example.com"]["statuses"], {"ok": 2, "self signed certificate": 1}
        )
        self.assertEqual(rows[None]["sessions"], 1)


LISTING = "ET COMPROMISED Known Compromised or Hostile Host Traffic group 7"


class TestListingAlerts(AddressCase):
    """The Threats page learns an indicator from a listing-rule alert's one internet
    endpoint (I7); the address page applies the same rule to its own window."""

    docs = [
        alert(PHONE, ADDR, rule=LISTING),  # ADDR is the listed host
        alert(
            "198.51.100.7", "203.0.113.5", rule=LISTING
        ),  # two internet ends: neither
        alert(
            "203.0.113.9", PHONE, rule=LISTING, t="2026-11-04T10:00:00.000Z"
        ),  # earlier
    ]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        patcher = patch(
            "services.threat_intel._TI_CACHE_PATH", Path(self._tmp.name) / "ti.json"
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        super().setUp()

    async def test_a_listing_alert_in_the_window_matches_without_a_cache(self):
        ti = (await self.figures())["threat_intel"]
        self.assertEqual(ti["matched"], True)
        self.assertEqual(ti["indicators"], 0)
        self.assertIs(ti["in_window"], True)  # NET-228: when it was listed
        self.assertEqual(
            ti["feeds"],
            [
                {
                    "feed": "et_compromised",
                    # OLD CODE: "label": "ET Compromised IPs", (NET-228: NetTap fills it from rules)
                    "label": "Suricata blocklist rules",
                    "indicator": ADDR,
                    "type": "ip",
                }
            ],
        )

    async def test_the_lan_side_or_an_ambiguous_alert_is_not_listed(self):
        for ip in (PHONE, "198.51.100.7", "203.0.113.9"):
            self.assertFalse((await self.figures(ip))["threat_intel"]["matched"], ip)

    async def test_a_cached_and_an_alerted_match_list_the_feed_once(self):
        Path(self._tmp.name, "ti.json").write_text(
            json.dumps({"version": 2, "ip_feeds": {"et_compromised": [ADDR]}})
        )
        ti = (await self.figures())["threat_intel"]
        self.assertEqual([f["feed"] for f in ti["feeds"]], ["et_compromised"])

    async def test_a_cached_match_named_only_before_this_window_says_so(self):
        """NET-228: the cache keeps no date, so the page can say only "an earlier scan"."""
        Path(self._tmp.name, "ti.json").write_text(
            json.dumps(
                {"version": 2, "ip_feeds": {"et_compromised": ["185.220.101.9"]}}
            )
        )
        ti = (await self.figures("185.220.101.9"))["threat_intel"]
        self.assertEqual((ti["matched"], ti["in_window"]), (True, False))

    async def test_a_cached_match_when_the_window_couldnt_be_checked_is_unknown(self):
        Path(self._tmp.name, "ti.json").write_text(
            json.dumps(
                {"version": 2, "ip_feeds": {"et_compromised": ["185.220.101.9"]}}
            )
        )
        with patch("api.addresses._listed_by_alerts", return_value=None):
            ti = (await self.figures("185.220.101.9"))["threat_intel"]
        self.assertEqual(ti["matched"], True)
        self.assertIsNone(ti["in_window"])

    async def test_alerts_too_many_to_check_and_no_match_is_not_checked(self):
        with (
            patch.object(snapshot_search, "GROUP_PAGE", 1),
            patch("api.addresses.LIST_CAP", 1),
        ):
            ti = (await self.figures("198.51.100.7"))["threat_intel"]
        self.assertIsNone(ti)


class TestBudgetFitsTheProxy(AddressCase):
    """A reply must land before the web proxy's 30 s (web/src/routes/api/[...path]/+server.ts)."""

    docs = [outbound(PHONE, sent=1, received=1)]

    def test_the_worst_case_ends_within_budget_plus_last_search_plus_pit_close(self):
        from api import drilldown_runner
        from api.addresses import address_figures
        from storage.snapshot_search import PIT_CLOSE_SECONDS, Budget, TooSlow

        clock = [0.0]

        class Slow:  # every call runs to just under its own timeout
            def __init__(self, inner):
                self.inner = inner

            def __getattr__(self, name):
                call = getattr(self.inner, name)

                def timed(*args, request_timeout=0, **kw):
                    clock[0] += request_timeout - 0.001
                    return call(*args, **kw)

                return timed

        budget = Budget(drilldown_runner.BUDGET_SECONDS, clock=lambda: clock[0])
        client = Slow(DrillOpenSearch(list(self.docs)))
        slots = {"date_range": {"field": "@timestamp", "ranges": []}}
        try:
            address_figures(
                client,
                ADDR,
                "2026-11-05T00:00:00Z",
                "2026-11-05T12:00:00Z",
                slots,
                lambda _ip: False,
                budget,
            )
        except TooSlow:
            pass
        worst = drilldown_runner.BUDGET_SECONDS + 1 + PIT_CLOSE_SECONDS
        self.assertLessEqual(clock[0], worst)
        self.assertLessEqual(worst, 30 - 3)  # room to encode and cross the proxy
