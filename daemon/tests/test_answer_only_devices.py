"""NET-226 follow-up: a LAN device that only answers connections is a device.

A NAS or a media server answers the laptop and never starts a connection of its own, so the
device list, the count, the registry and risk never showed it. The evaluator fake runs the
real queries over fixed documents.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from aiohttp.test_utils import AioHTTPTestCase

from api import devices
from api.bandwidth import register_bandwidth_routes
from api.devices import _lan_device_buckets, register_device_routes
from api.devices_v2 import _conn_device_aggs, _register_conn_devices
from api.risk import register_risk_routes
from services.bandwidth_tracker import BandwidthTracker
from services.excluded_ips import build_lan_filter
from services.risk_scoring import RiskScorer
from storage.snapshot_search import QueryFailed
from tests.fake_drill_opensearch import (
    AUTH,
    FROM,
    TO,
    WINDOW,
    DrillOpenSearch,
    conn,
    make_app,
)

LAN = build_lan_filter([(192, 168, 1)])
LAPTOP, NAS, PHONE = "192.168.1.30", "192.168.1.40", "192.168.1.60"
M_LAPTOP, M_NAS, M_PHONE = "00:00:5e:00:53:30", "00:00:5e:00:53:40", "00:00:5e:00:53:60"
M_ROUTER = "00:00:5e:00:53:01"
NET_A = "203.0.113.5"


def _at(minute: int) -> str:
    return f"2026-11-05T10:{minute:02d}:00.000Z"


def _laptop_out(n=3):
    """The laptop's own internet traffic, through the router: it is a device, the router a gateway."""
    return [
        conn(
            LAPTOP,
            NET_A,
            _at(0),
            source__bytes=10,
            destination__bytes=20,
            destination__packets=1,
            source__mac=M_LAPTOP,
            destination__mac=M_ROUTER,
        )
        for _ in range(n)
    ]


def _to_nas(n, minute, packets=2, dst=NAS, mac=M_NAS):
    """The laptop opens n connections to `dst`; with packets 0 nothing answered."""
    return [
        conn(
            LAPTOP,
            dst,
            _at(minute + i),
            source__bytes=5,
            destination__bytes=1000 if packets else 0,
            destination__packets=packets,
            source__mac=M_LAPTOP,
            destination__mac=mac,
            network__transport="tcp",
        )
        for i in range(n)
    ]


# The NAS answers 4 connections (10:10-10:13); later probes of it (10:40) got no answer, and
# a scan of five empty addresses got none either
NAS_DOCS = [
    *_laptop_out(),
    *_to_nas(4, 10),
    *_to_nas(3, 40, packets=0),
    *(
        d
        for i in range(5)
        for d in _to_nas(3, 20, packets=0, dst=f"192.168.1.{100 + i}")
    ),
]


def _register(app, client):
    storage = SimpleNamespace(_client=client)
    app["storage"] = storage
    register_device_routes(app, storage)
    register_risk_routes(app, RiskScorer(), storage)
    with patch("services.bandwidth_tracker._CAP_FILE", "/nonexistent/path"):
        register_bandwidth_routes(app, BandwidthTracker(client=client))


class Case(AioHTTPTestCase):
    docs: list = NAS_DOCS
    lan = LAN
    tamper = None

    async def get_application(self):
        self.os = DrillOpenSearch(self.docs, tamper=self.tamper)
        return make_app(self.os, _register, lan_filter=self.lan)

    async def get(self, path, window=WINDOW):
        sep = "&" if "?" in path else "?"
        resp = await self.client.get(f"{path}{sep}{window}", headers=AUTH)
        return resp.status, await resp.json()


class TestAnswerOnlyNas(Case):
    async def test_the_list_shows_it_with_both_sides(self):
        status, body = await self.get("/api/devices")
        self.assertEqual(status, 200, body)
        rows = {d["ip"]: d for d in body["devices"]}
        # the scanned empty addresses are no devices
        self.assertEqual(set(rows), {LAPTOP, NAS})
        nas = rows[NAS]
        # 4 answered (4,000 up, 20 down) and 3 attempts at it (15 down), as for any device
        self.assertEqual(
            (nas["connection_count"], nas["upload_bytes"], nas["download_bytes"]),
            (7, 4000, 35),
        )
        self.assertEqual((nas["mac"], nas["protocols"]), (M_NAS, ["tcp"]))
        # its newest answered record, not the unanswered probes after it
        self.assertEqual(nas["last_seen"], _at(13))
        self.assertEqual(nas["first_seen"], _at(10))

    async def test_the_count_and_bandwidth_devices_agree(self):
        status, body = await self.get("/api/devices/count")
        self.assertEqual((status, body["count"]), (200, 2))
        status, body = await self.get("/api/bandwidth/devices")
        self.assertEqual(status, 200, body)
        nas = next(r for r in body["devices"] if r["ip"] == NAS)
        self.assertEqual((nas["upload_bytes"], nas["download_bytes"]), (4000, 35))

    async def test_its_page_matches_its_row(self):
        _, listed = await self.get("/api/devices")
        row = next(d for d in listed["devices"] if d["ip"] == NAS)
        status, body = await self.get(f"/api/devices/{NAS}")
        self.assertEqual(status, 200, body)
        page = body["device"]
        keys = (
            "connection_count",
            "upload_bytes",
            "download_bytes",
            "first_seen",
            "last_seen",
            "mac",
            "protocols",
        )
        self.assertEqual({k: page[k] for k in keys}, {k: row[k] for k in keys})

    async def test_online_counts_its_answers_not_the_probes(self):
        # the laptop probes it until 10:42; after its last answer (10:13) only the laptop counts
        status, body = await self.get(
            "/api/devices/count?active_since=2026-11-05T10:14:00Z"
        )
        self.assertEqual((status, body["count"]), (200, 1))
        status, body = await self.get(
            "/api/devices/count?active_since=2026-11-05T10:13:00Z"
        )
        self.assertEqual((status, body["count"]), (200, 2))

    async def test_risk_scores_it_without_it_in_the_baseline(self):
        status, body = await self.get("/api/risk/scores")
        self.assertEqual(status, 200, body)
        rows = {d["ip"]: d for d in body["devices"]}
        self.assertEqual(rows[NAS]["connection_count"], 0)
        # the laptop's 3 + 4 + 3 + 15 opened connections alone
        self.assertEqual(body["network_avg_connections"], 25)

    def test_the_registry_keys_it_by_its_own_mac(self):
        buckets = _lan_device_buckets(
            self.os,
            {"lan_filter": LAN, "excluded_ips": []},
            FROM,
            TO,
            aggs=_conn_device_aggs(),
            what="registry",
        )
        registry = MagicMock()
        self.assertEqual(
            _register_conn_devices(registry, buckets), {LAPTOP: M_LAPTOP, NAS: M_NAS}
        )
        nas = next(
            c.kwargs
            for c in registry.register_device.call_args_list
            if c.kwargs["ip"] == NAS
        )
        self.assertEqual(nas["seen_at"], "2026-11-05T10:13:00+00:00")

    def test_a_scan_bigger_than_the_cap_is_no_device_and_no_failure(self):
        # 5 scanned addresses and 1 answering device, with a cap of 2 IPs per read
        with patch.object(devices, "_DEVICE_CAP", 2):
            buckets = _lan_device_buckets(
                self.os,
                {"lan_filter": LAN, "excluded_ips": []},
                FROM,
                TO,
                page_size=1,
                what="cap",
            )
        self.assertEqual({b["key"] for b in buckets}, {LAPTOP, NAS})


class TestAnsweredAndStarted(Case):
    """2 started + 3 answered: a device, listed once, owning no IPv6 (the device page's rule)."""

    docs = [
        *_laptop_out(),
        *[
            conn(
                PHONE,
                NET_A,
                _at(1),
                source__bytes=7,
                destination__bytes=9,
                source__mac=M_PHONE,
                destination__mac=M_ROUTER,
            )
            for _ in range(2)
        ],
        *_to_nas(3, 10, dst=PHONE, mac=M_PHONE),
        *[
            conn(
                "2001:db8::60",
                "2001:db8:ffff::1",
                _at(5),
                source__bytes=300,
                destination__bytes=3000,
                source__mac=M_PHONE,
                destination__mac=M_ROUTER,
            )
            for _ in range(3)
        ],
    ]

    async def test_listed_once_without_ipv6_and_its_page_agrees(self):
        status, body = await self.get("/api/devices")
        self.assertEqual(status, 200, body)
        phones = [d for d in body["devices"] if d["ip"] == PHONE]
        self.assertEqual(len(phones), 1)
        row = phones[0]
        # started 2 (14/18) + answered 3 (3,000/15); its IPv6 is nobody's
        self.assertEqual(
            (row["connection_count"], row["upload_bytes"], row["download_bytes"]),
            (5, 3014, 33),
        )
        self.assertEqual(row["ipv6_connections"], 0)
        self.assertEqual((row["first_seen"], row["last_seen"]), (_at(1), _at(12)))
        status, body = await self.get(f"/api/devices/{PHONE}")
        page = body["device"]
        for key in ("connection_count", "upload_bytes", "download_bytes", "last_seen"):
            self.assertEqual(page[key], row[key], key)


class TestRoutedAnswers(Case):
    """Review: a NAS answering only a client on another subnet, captured on the router's trunk.
    Zeek keeps the first leg's MACs, client to router, so the NAS's destination.mac is the
    router's; that MAC must not become the NAS's."""

    CLIENT = "192.168.2.50"
    lan = build_lan_filter([(192, 168, 1), (192, 168, 2)])
    docs = [
        *_laptop_out(),
        *[
            conn(
                "192.168.2.50",
                NAS,
                _at(10 + i),
                source__bytes=5,
                destination__bytes=1000,
                destination__packets=2,
                source__mac="00:00:5e:00:53:50",
                destination__mac=M_ROUTER,
            )
            for i in range(4)
        ],
    ]

    async def test_the_list_and_the_page_show_no_router_mac(self):
        _, listed = await self.get("/api/devices")
        nas = next(d for d in listed["devices"] if d["ip"] == NAS)
        self.assertIsNone(nas["mac"])
        _, body = await self.get(f"/api/devices/{NAS}")
        self.assertIsNone(body["device"]["mac"])

    def test_the_registry_does_not_file_it_under_the_router(self):
        buckets = _lan_device_buckets(
            self.os,
            {"lan_filter": self.lan, "excluded_ips": []},
            FROM,
            TO,
            aggs=_conn_device_aggs(),
            what="registry",
        )
        self.assertEqual(
            _register_conn_devices(MagicMock(), buckets),
            {LAPTOP: M_LAPTOP, self.CLIENT: "00:00:5e:00:53:50"},
        )


class TestMostlyRoutedAnswers(TestRoutedAnswers):
    """Delta review: the NAS answers 4 routed flows and 2 on-link ones from the laptop. The
    router's MAC is its most common answered-to MAC, but its own MAC is the one to keep."""

    docs = [*TestRoutedAnswers.docs, *_to_nas(2, 30)]

    async def test_the_list_and_the_page_show_no_router_mac(self):
        _, listed = await self.get("/api/devices")
        nas = next(d for d in listed["devices"] if d["ip"] == NAS)
        self.assertEqual(nas["mac"], M_NAS)
        _, body = await self.get(f"/api/devices/{NAS}")
        self.assertEqual(body["device"]["mac"], M_NAS)

    def test_the_registry_does_not_file_it_under_the_router(self):
        buckets = _lan_device_buckets(
            self.os,
            {"lan_filter": self.lan, "excluded_ips": []},
            FROM,
            TO,
            aggs=_conn_device_aggs(),
            what="registry",
        )
        self.assertEqual(
            _register_conn_devices(MagicMock(), buckets),
            {LAPTOP: M_LAPTOP, self.CLIENT: "00:00:5e:00:53:50", NAS: M_NAS},
        )


class TestDualStackActivity(Case):
    """A device's newest record is IPv6: its page reads the list's IPv4 activity, as the list."""

    docs = [
        *_laptop_out(),
        conn(
            "2001:db8::30",
            "2001:db8:ffff::1",
            _at(50),
            source__bytes=1,
            destination__bytes=1,
            source__mac=M_LAPTOP,
            destination__mac=M_ROUTER,
        ),
    ]

    async def test_the_page_and_the_list_say_the_same_last_seen(self):
        _, listed = await self.get("/api/devices")
        (row,) = listed["devices"]
        self.assertEqual(row["ipv6_connections"], 1)
        _, body = await self.get(f"/api/devices/{LAPTOP}")
        self.assertEqual(body["device"]["last_seen"], row["last_seen"])
        self.assertEqual(row["last_seen"], _at(0))


OTHER_VLAN = "192.168.2.40"


class TestAnotherVlan(Case):
    """A responder-only VLAN is in the LAN rule only when LAN_SUBNETS lists it."""

    docs = [*_laptop_out(), *_to_nas(4, 10, dst=OTHER_VLAN)]
    listed = {LAPTOP}

    async def test_listed_only_when_the_lan_rule_has_its_subnet(self):
        _, body = await self.get("/api/devices")
        self.assertEqual({d["ip"] for d in body["devices"]}, self.listed)


class TestAnotherVlanConfigured(TestAnotherVlan):
    lan = build_lan_filter([(192, 168, 1), (192, 168, 2)])
    listed = {LAPTOP, OTHER_VLAN}

    async def test_its_page_counts_the_connections_with_another_subnet(self):
        # review L10: the page says bytes may count twice only for these (4, on both sides)
        for ip in (LAPTOP, OTHER_VLAN):
            status, body = await self.get(f"/api/devices/{ip}")
            self.assertEqual(status, 200, body)
            self.assertEqual(body["device"]["inter_vlan_connections"], 4, ip)


class TestOneSubnet(Case):
    async def test_no_connection_is_with_another_subnet(self):
        _, body = await self.get(f"/api/devices/{NAS}")
        self.assertEqual(body["device"]["inter_vlan_connections"], 0)


def _drop_responders(body, reply):
    """The answering side's composite comes back without its aggregation."""
    sources = (
        (body.get("aggs", {}).get("all") or {}).get("composite", {}).get("sources")
    )
    if sources and sources[0]["ip"]["terms"]["field"] == "destination.ip":
        return {**reply, "aggregations": {}}
    return reply


def _lose_an_answerer(body, reply):
    """The answer-only devices' read leaves one out."""
    ips = body.get("aggs", {}).get("ips")
    if ips and ips["terms"]["field"] == "destination.ip":
        return {**reply, "aggregations": {"ips": {"buckets": []}}}
    return reply


class TestPartialResponders(Case):
    tamper = staticmethod(_drop_responders)

    async def test_is_502_not_fewer_devices(self):
        for path in ("/api/devices", "/api/devices/count", "/api/risk/scores"):
            status, _ = await self.get(path)
            self.assertEqual(status, 502, path)


class TestMissingAnswerer(Case):
    tamper = staticmethod(_lose_an_answerer)

    async def test_is_502_not_a_device_without_its_figures(self):
        status, _ = await self.get("/api/devices")
        self.assertEqual(status, 502)
        with self.assertRaises(QueryFailed):
            _lan_device_buckets(
                self.os,
                {"lan_filter": LAN, "excluded_ips": []},
                FROM,
                TO,
                aggs=_conn_device_aggs(),
                what="registry",
            )
