"""The Threats page's drill-downs: one beaconing pair, and one device's failed DNS lookups.

The fake evaluates the real queries over raw conn/ssl/dns/alert documents, so every figure is
checked against the documents. Both endpoints read their detector's records, so a device
excluded in Settings is counted and the reply says it is excluded.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from api.threat_drilldowns import register_threat_drilldown_routes
from services.threat_detection import _beacon_confidence
from storage import snapshot_search
from tests.fake_drill_opensearch import (
    AUTH,
    WINDOW,
    DrillOpenSearch,
    alert,
    conn,
    dns,
    epoch_ms,
    iso,
    make_app,
    ssl_session,
)

DEVICE, OTHER, EXCLUDED = "192.168.1.20", "192.168.1.30", "192.168.1.99"
SERVER = "93.184.216.34"  # an internet address, so the threat intel cache keeps it
T0 = epoch_ms("2026-11-05T01:00:00Z")  # on a 10 s slot boundary
PAIR = f"device={DEVICE}&server={SERVER}&port=443&{WINDOW}"
SD = "lb._dns-sd._udp.0.1.168.192.in-addr.arpa"  # the G11's case: DNS service discovery
GENERATED = [
    "kq3z8wxv1m7tbn5r6yhp.com",
    "xj4w9qpz2l8vmb6c3kfr.com",
    "p7tq2zx9wm4kvb8c1hrn.net",
    "bz5x8qw3jm7tl2vk9pcr.org",
]


def call(seconds: float, src: str = DEVICE, dst: str = SERVER, port: int = 443) -> dict:
    """A TLS connection `seconds` after T0."""
    return conn(
        src,
        dst,
        t=iso(T0 + seconds * 1000),
        destination__port=port,
        network__transport="tcp",
        network__protocol="ssl",
    )


def every(seconds: int, count: int, **kw) -> list[dict]:
    return [call(5 + k * seconds, **kw) for k in range(count)]


def failed(name: str, src: str = DEVICE, minute: int = 0, **kw) -> dict:
    return dns(
        name,
        src=src,
        t=iso(T0 + minute * 60_000),
        zeek__dns__rcode_name="NXDOMAIN",
        **kw,
    )


class DrillCase(AioHTTPTestCase):
    docs: list = []

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self._tmp.name) / "ti.json"
        patcher = patch("services.threat_intel._TI_CACHE_PATH", self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        super().setUp()

    async def get_application(self):
        self.os = DrillOpenSearch(list(self.docs))
        return make_app(
            self.os, register_threat_drilldown_routes, excluded_ips=[EXCLUDED]
        )

    async def get(self, path: str, status: int = 200) -> dict:
        resp = await self.client.get(path, headers=AUTH)
        self.assertEqual(resp.status, status, await resp.text())
        return await resp.json()

    async def pair(self, query: str = PAIR, status: int = 200) -> dict:
        return await self.get(f"/api/threats/beaconing/pair?{query}", status)

    async def failures(self, ip: str = DEVICE, status: int = 200) -> dict:
        return await self.get(f"/api/threats/failed-lookups/{ip}?{WINDOW}", status)


class TestValidation(DrillCase):
    async def test_bad_input_is_a_400_and_no_search_runs(self):
        for query in (
            f"device=abc&server={SERVER}&port=443&{WINDOW}",
            f"device={DEVICE}&port=443&{WINDOW}",
            f"device={DEVICE}&server={SERVER}&port=70000&{WINDOW}",
            f"device={DEVICE}&server={SERVER}&port=-1&{WINDOW}",
            f"device={DEVICE}&server={SERVER}&port=443x&{WINDOW}",
            f"device={DEVICE}&server={SERVER}&{WINDOW}",
            f"device={DEVICE}&server={SERVER}&port=443&to=yesterday",
        ):
            self.assertIn("error", await self.pair(query, status=400), query)
        self.assertIn("error", await self.failures("not-an-ip", status=400))
        resp = await self.client.get(
            f"/api/threats/failed-lookups/{DEVICE}?to=yesterday", headers=AUTH
        )
        self.assertEqual(resp.status, 400)
        self.assertEqual(self.os.bodies, [])

    async def test_the_routes_need_the_token(self):
        for path in (
            f"/api/threats/beaconing/pair?{PAIR}",
            f"/api/threats/failed-lookups/{DEVICE}",
        ):
            self.assertEqual((await self.client.get(path)).status, 401)


class TestPeriodicPair(DrillCase):
    docs = [
        *every(60, 30),
        *every(60, 30, src=OTHER),  # another device
        *every(60, 30, port=80),  # another port
        {
            **ssl_session("api.example.com", server=SERVER, client=DEVICE),
            "destination.port": 443,
        },
        {
            **ssl_session("API.example.com.", server=SERVER, client=DEVICE),
            "destination.port": 443,
        },
        {
            **ssl_session("other.example.com", server=SERVER, client=DEVICE),
            "destination.port": 8443,
        },
        dns("api.example.com", src=DEVICE, zeek__dns__answers=[SERVER, "198.51.100.1"]),
        dns("x.example.com", src=OTHER, zeek__dns__answers=[SERVER]),
        dns("other.example.com", src=DEVICE, zeek__dns__answers=["198.51.100.2"]),
    ]

    async def test_the_pair_is_timed_with_the_scans_rule(self):
        body = await self.pair()
        self.assertEqual(body["connections"], 30)
        self.assertEqual(
            body["timing"],
            {
                "status": "periodic",
                "slots": 30,
                "mean_gap_seconds": 60.0,
                "jitter": 0.0,
                "beacon": {
                    "interval_seconds": 60.0,
                    "jitter_coefficient": 0.0,
                    "confidence": _beacon_confidence(0.0, 30, 60.0),
                },
                "gaps": [{"seconds": 60, "count": 29}],
            },
        )
        self.assertEqual(sum(p["n"] for p in body["timeline"]), 30)
        self.assertEqual(body["first_seen"], iso(T0 + 5_000))
        self.assertEqual(body["last_seen"], iso(T0 + 5_000 + 29 * 60_000))
        self.assertEqual(body["transports"], [{"name": "tcp", "connections": 30}])
        self.assertEqual(body["services"], [{"name": "ssl", "connections": 30}])
        self.assertEqual(
            (body["device"], body["server"], body["port"]), (DEVICE, SERVER, 443)
        )
        self.assertFalse(body["device_excluded"])
        self.assertIn("interval", body)

    async def test_names_are_this_devices_own_for_this_server(self):
        body = await self.pair()
        # two spellings of one TLS name are one row; another port's session isn't counted
        self.assertEqual(
            body["tls_names"], [{"name": "api.example.com", "sessions": 2}]
        )
        self.assertTrue(body["tls_complete"])
        self.assertEqual(body["dns_names"], [{"name": "api.example.com", "lookups": 1}])
        self.assertTrue(body["dns_complete"])

    async def test_an_unlisted_server(self):
        self.assertEqual(
            (await self.pair())["threat_intel"],
            {"matched": False, "feeds": [], "indicators": 0, "in_window": False},
        )

    async def test_a_listed_server_names_its_feed(self):
        self.cache.write_text(
            json.dumps({"version": 2, "ip_feeds": {"et_compromised": [SERVER]}})
        )
        ti = (await self.pair())["threat_intel"]
        self.assertTrue(ti["matched"])
        self.assertEqual(ti["feeds"][0]["feed"], "et_compromised")

    async def test_too_many_slots_to_read_claims_nothing(self):
        with (
            patch("api.threat_drilldowns.TIMING_CAP", 2),
            patch.object(snapshot_search, "GROUP_PAGE", 2),
        ):
            timing = (await self.pair())["timing"]
        self.assertEqual(timing["status"], "capped")
        self.assertIsNone(timing["beacon"])
        self.assertIsNone(timing["mean_gap_seconds"])
        self.assertEqual(timing["gaps"], [])


class TestUnclearTiming(DrillCase):
    docs = [
        *every(60, 9),  # nine calls, perfectly regular
        # 100 calls packed into 9 distinct 10 s slots, a minute apart
        *[call(6_000 + (i % 9) * 60 + (i // 9) * 0.5, port=8443) for i in range(100)],
        # enough calls, uneven gaps
        *[
            call(s, port=22)
            for s in (0, 60, 360, 420, 720, 780, 1080, 1140, 1440, 1500, 1800, 1860)
        ],
    ]

    async def test_nine_regular_calls_are_too_few_not_irregular(self):
        body = await self.pair()
        self.assertEqual(body["connections"], 9)
        self.assertEqual(body["timing"]["status"], "too_few")
        self.assertIsNone(body["timing"]["beacon"])
        self.assertEqual(body["timing"]["mean_gap_seconds"], 60.0)

    async def test_many_calls_in_few_slots_are_too_few(self):
        body = await self.pair(f"device={DEVICE}&server={SERVER}&port=8443&{WINDOW}")
        self.assertEqual(body["connections"], 100)
        self.assertEqual(body["timing"]["status"], "too_few")
        self.assertEqual(body["timing"]["slots"], 9)

    async def test_uneven_gaps_are_irregular(self):
        body = await self.pair(f"device={DEVICE}&server={SERVER}&port=22&{WINDOW}")
        timing = body["timing"]
        self.assertEqual(timing["status"], "irregular")
        self.assertIsNone(timing["beacon"])
        self.assertEqual(timing["mean_gap_seconds"], 169.1)
        self.assertGreater(timing["jitter"], 0.15)


class TestBlocklistAndExclusions(DrillCase):
    docs = [
        *every(60, 12, src=EXCLUDED),
        # listing alerts between two internet hosts name neither; more pairs than the patched cap
        *[
            alert(SERVER, peer, rule="ET DROP Dshield Block Listed Source")
            for peer in ("1.1.1.1", "8.8.8.8", "9.9.9.9")
        ],
    ]

    async def test_an_excluded_device_is_counted_and_says_so(self):
        body = await self.pair(f"device={EXCLUDED}&server={SERVER}&port=443&{WINDOW}")
        self.assertEqual(body["connections"], 12)
        self.assertTrue(body["device_excluded"])

    async def test_alerts_that_couldnt_all_be_checked_are_not_checked(self):
        with (
            patch("api.addresses.LIST_CAP", 2),
            patch.object(snapshot_search, "GROUP_PAGE", 2),
        ):
            body = await self.pair(
                f"device={EXCLUDED}&server={SERVER}&port=443&{WINDOW}"
            )
        self.assertIsNone(body["threat_intel"])


class TestFailedLookups(DrillCase):
    docs = [
        *[failed(SD, minute=m) for m in range(6)],
        failed(GENERATED[0], minute=10),
        failed(GENERATED[0], minute=20),
        failed("foo.arpa", minute=30),
        failed("printer", minute=40),
        *[
            dns(
                "example.com",
                src=DEVICE,
                t=iso(T0 + m * 60_000),
                zeek__dns__rcode_name="NOERROR",
            )
            for m in range(4)
        ],
        # left out as the detector leaves it out: mDNS to a local multicast address
        failed("x.local", destination__ip="224.0.0.251", destination__port=5353),
        failed("other.test", src=OTHER),  # another device
        failed(SD, src=EXCLUDED),
    ]

    async def test_the_failures_their_names_and_kinds(self):
        body = await self.failures()
        self.assertEqual((body["lookups"], body["failed"]), (14, 10))
        self.assertEqual(
            body["rcodes"],
            [{"rcode": "NXDOMAIN", "lookups": 10}, {"rcode": "NOERROR", "lookups": 4}],
        )
        self.assertEqual(
            [(r["name"], r["lookups"], r["kind"]) for r in body["failed_names"]],
            [
                (SD, 6, "service_discovery"),
                (GENERATED[0], 2, "generated"),
                (
                    "foo.arpa",
                    1,
                    "other",
                ),  # skipped by the checks: other, never an error
                ("printer", 1, "bare"),
            ],
        )
        self.assertEqual(body["failed_names"][0]["last_seen"], iso(T0 + 5 * 60_000))
        self.assertEqual(
            body["kinds"],
            [
                {"kind": "service_discovery", "names": 1, "lookups": 6},
                {"kind": "generated", "names": 1, "lookups": 2},
                {"kind": "bare", "names": 1, "lookups": 1},
                {"kind": "other", "names": 1, "lookups": 1},
            ],
        )
        self.assertEqual(body["generated_names"], 1)
        self.assertEqual(body["failed_names_read"], 4)
        self.assertTrue(body["failed_names_complete"])
        self.assertEqual(sum(p["n"] for p in body["timeline"]), 14)
        self.assertEqual(sum(p["failed"] for p in body["timeline"]), 10)
        self.assertFalse(body["excluded"])
        self.assertIn("interval", body)

    async def test_an_excluded_device_is_counted_and_says_so(self):
        body = await self.failures(EXCLUDED)
        self.assertEqual(body["failed"], 1)
        self.assertTrue(body["excluded"])


class TestFailedNamesCoverage(DrillCase):
    docs = [
        failed("aaa.example"),
        failed("bbb.example"),
        *[failed("zzz.example", minute=m) for m in range(50)],  # the busiest sorts last
    ]

    async def test_a_capped_read_says_so_and_can_miss_a_busy_name(self):
        with (
            patch("api.threat_drilldowns.LIST_CAP", 2),
            patch.object(snapshot_search, "GROUP_PAGE", 2),
        ):
            body = await self.failures()
        self.assertFalse(body["failed_names_complete"])
        self.assertEqual(body["failed_names_read"], 2)
        self.assertNotIn("zzz.example", [r["name"] for r in body["failed_names"]])
        self.assertEqual(body["failed"], 52)  # the totals never depend on the list


class TestFailedNamesBeyondTheList(DrillCase):
    docs = [
        *[failed(f"n{i:03d}.test", minute=m) for i in range(101) for m in range(2)],
        *[failed(name) for name in GENERATED],
    ]

    async def test_kinds_count_every_name_read_not_only_those_listed(self):
        body = await self.failures()
        self.assertTrue(body["failed_names_complete"])
        self.assertEqual(body["failed_names_read"], 105)
        self.assertEqual(len(body["failed_names"]), 100)
        self.assertNotIn("generated", [r["kind"] for r in body["failed_names"]])
        self.assertEqual(body["generated_names"], 4)
        self.assertIn({"kind": "local", "names": 101, "lookups": 202}, body["kinds"])
        self.assertIn({"kind": "generated", "names": 4, "lookups": 4}, body["kinds"])
