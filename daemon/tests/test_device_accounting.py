"""NET-226: a device's traffic is both sides of its connections, its IPv6 by MAC included.

The evaluator fake runs the real queries over fixed documents. On the G11 a web server
behind a port forward read 720 connections and 168,900 B for an hour in which it took part
in 5,059 connections and 2,175,804 B: only the connections it started counted.
"""

from types import SimpleNamespace
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from api.bandwidth import register_bandwidth_routes
from api.devices import _category_basis, register_device_routes
from api.traffic import register_traffic_routes
from services.bandwidth_tracker import BandwidthTracker
from services.device_fingerprint import _OS_PATTERNS
from services.excluded_ips import build_lan_filter
from tests.fake_drill_opensearch import (
    AUTH,
    WINDOW,
    DrillOpenSearch,
    conn,
    make_app,
)

LAN = build_lan_filter([(192, 168, 1)])
SERVER, LAPTOP, ROUTER = "192.168.1.24", "192.168.1.30", "192.168.1.1"
M_SERVER, M_LAPTOP = "00:00:5e:00:53:24", "00:00:5e:00:53:30"
M_ROUTER, M_MODEM = "00:00:5e:00:53:01", "00:00:5e:00:53:fe"
NET_A, NET_B = "203.0.113.5", "203.0.113.9"


def _conns(n, src, dst, sent, got, **macs):
    """n conn records src -> dst, the originator sending `sent` and getting `got` bytes."""
    return [
        conn(src, dst, source__bytes=sent, destination__bytes=got, **macs)
        for _ in range(n)
    ]


DOCS = [
    # the server's own uploads (it started them)
    *_conns(
        3, SERVER, NET_A, 100, 200, source__mac=M_SERVER, destination__mac=M_ROUTER
    ),
    # visitors through a port forward: the server answers, so their 1,000 B are its upload
    *_conns(
        4, NET_B, SERVER, 50, 1000, source__mac=M_ROUTER, destination__mac=M_SERVER
    ),
    # LAN to LAN: counts for the laptop (started) and the server (answered)
    *_conns(
        3, LAPTOP, SERVER, 10, 500, source__mac=M_LAPTOP, destination__mac=M_SERVER
    ),
    # the router's own connections, to the ISP's next hop
    *_conns(3, ROUTER, NET_A, 20, 40, source__mac=M_ROUTER, destination__mac=M_MODEM),
    # the laptop's IPv6: mDNS, a download it started and one it answered (both global)
    *_conns(2, "fe80::30", "ff02::fb", 70, 0, source__mac=M_LAPTOP),
    *_conns(
        1,
        "2001:db8::30",
        "2001:db8:ffff::1",
        300,
        3000,
        source__mac=M_LAPTOP,
        destination__mac=M_ROUTER,
    ),
    *_conns(
        1,
        "2001:db8:ffff::9",
        "2001:db8::30",
        4000,
        40,
        source__mac=M_ROUTER,
        destination__mac=M_LAPTOP,
    ),
    # the router's link-local; its forwarded IPv6 above is the laptop's, not its own
    *_conns(2, "fe80::1", "ff02::1", 90, 0, source__mac=M_ROUTER),
]

# {ip: (connections, upload, download, ipv6 connections, left out, reason)}
EXPECTED = {
    # started 3 (300/600) + answered 4 (4,000/200) + answered 3 from the laptop (1,500/30)
    SERVER: (10, 5800, 830, 0, 0, None),
    # started 3 (30/1,500) + IPv6 4 by MAC: 2 x 70 + 300 + 40 up, 3,000 + 4,000 down
    LAPTOP: (7, 510, 8500, 4, 0, None),
    # started 3 (60/120) + link-local 2 (180 up); its 2 global records are forwarded traffic
    ROUTER: (5, 240, 120, 2, 2, "router"),
}


def _figures(row):
    return (
        row["connection_count"],
        row["upload_bytes"],
        row["download_bytes"],
        row["ipv6_connections"],
        row["ipv6_left_out"],
        row["ipv6_left_out_reason"],
    )


def _register(app, client):
    storage = SimpleNamespace(_client=client)
    app["storage"] = storage
    register_device_routes(app, storage)
    register_traffic_routes(app, storage)
    with patch("services.bandwidth_tracker._CAP_FILE", "/nonexistent/path"):
        register_bandwidth_routes(app, BandwidthTracker(client=client))


class AccountingCase(AioHTTPTestCase):
    docs: list = DOCS
    tamper = None

    async def get_application(self):
        self.os = DrillOpenSearch(self.docs, tamper=self.tamper)
        return make_app(self.os, _register, lan_filter=LAN)

    async def get(self, path):
        sep = "&" if "?" in path else "?"
        resp = await self.client.get(f"{path}{sep}{WINDOW}", headers=AUTH)
        return resp.status, await resp.json()


class TestBothSides(AccountingCase):
    async def test_the_device_list_counts_both_sides_and_ipv6_by_mac(self):
        status, body = await self.get("/api/devices")
        self.assertEqual(status, 200, body)
        rows = {d["ip"]: d for d in body["devices"]}
        self.assertEqual({ip: _figures(rows[ip]) for ip in EXPECTED}, EXPECTED)
        for ip, (_, up, down, *_rest) in EXPECTED.items():
            self.assertEqual(rows[ip]["total_bytes"], up + down, ip)
        # membership is unchanged: an internet visitor is never a device
        self.assertEqual(set(rows), set(EXPECTED))

    async def test_the_device_page_matches_its_row(self):
        for ip, expected in EXPECTED.items():
            status, body = await self.get(f"/api/devices/{ip}")
            self.assertEqual(status, 200, body)
            device = body["device"]
            self.assertEqual(_figures(device), expected, ip)
            series = device["bandwidth_series"]
            self.assertEqual(
                (
                    sum(p["upload_bytes"] for p in series),
                    sum(p["download_bytes"] for p in series),
                ),
                expected[1:3],
                ip,
            )

    async def test_bandwidth_devices_use_the_same_figures(self):
        status, body = await self.get("/api/bandwidth/devices")
        self.assertEqual(status, 200, body)
        rows = body["devices"]
        self.assertEqual([r["ip"] for r in rows], [LAPTOP, SERVER, ROUTER])
        everything = sum(up + down for _, up, down, *_ in EXPECTED.values())
        for row in rows:
            _, up, down, *_rest = EXPECTED[row["ip"]]
            self.assertEqual(
                (row["upload_bytes"], row["download_bytes"]), (up, down), row["ip"]
            )
            self.assertEqual(
                row["percent_of_total"], round((up + down) / everything * 100, 1)
            )


class TestSharedMac(AccountingCase):
    """Two addresses on one MAC, as busy as each other: the IPv6 goes to one row, the same
    one on the list and on both device pages, never to both."""

    SECOND = "192.168.1.31"
    docs = [
        *DOCS,
        *_conns(
            3, SECOND, NET_A, 10, 10, source__mac=M_LAPTOP, destination__mac=M_ROUTER
        ),
    ]

    async def test_the_lower_address_keeps_the_ipv6_everywhere(self):
        status, body = await self.get("/api/devices")
        self.assertEqual(status, 200, body)
        rows = {d["ip"]: _figures(d) for d in body["devices"]}
        self.assertEqual(rows[LAPTOP], EXPECTED[LAPTOP])
        self.assertEqual(rows[self.SECOND], (3, 30, 30, 0, 0, None))
        for ip in (LAPTOP, self.SECOND):
            status, body = await self.get(f"/api/devices/{ip}")
            self.assertEqual(_figures(body["device"]), rows[ip], ip)


class TestASecondRouter(AccountingCase):
    """A router that takes 1 internet-bound frame in the window is a gateway like the main one."""

    ROUTER2, M_ROUTER2 = "192.168.1.2", "00:00:5e:00:53:02"
    docs = [
        *DOCS,
        *_conns(
            1, SERVER, NET_A, 1, 1, source__mac=M_SERVER, destination__mac=M_ROUTER2
        ),
        *_conns(
            3, ROUTER2, LAPTOP, 1, 1, source__mac=M_ROUTER2, destination__mac=M_LAPTOP
        ),
        *_conns(
            1,
            "2001:db8:ffff::5",
            "2001:db8::30",
            500,
            5,
            source__mac=M_ROUTER2,
            destination__mac=M_LAPTOP,
        ),
    ]

    async def test_its_forwarded_ipv6_goes_to_the_device_not_to_it(self):
        status, body = await self.get("/api/devices")
        self.assertEqual(status, 200, body)
        rows = {d["ip"]: d for d in body["devices"]}
        router2 = rows[self.ROUTER2]
        self.assertEqual(
            (router2["ipv6_connections"], router2["ipv6_left_out"]), (0, 1)
        )
        self.assertEqual(router2["ipv6_left_out_reason"], "router")
        self.assertEqual(rows[LAPTOP]["ipv6_connections"], 5)


class TestNoGatewayKnown(AccountingCase):
    """No internet-bound IPv4 in the window: no MAC can be cleared as not a router."""

    docs = [
        *_conns(
            3, LAPTOP, SERVER, 10, 500, source__mac=M_LAPTOP, destination__mac=M_SERVER
        ),
        *_conns(
            3, SERVER, LAPTOP, 5, 5, source__mac=M_SERVER, destination__mac=M_LAPTOP
        ),
        *_conns(
            2,
            "fd00::30",
            "fd00::24",
            7,
            9,
            source__mac=M_LAPTOP,
            destination__mac=M_SERVER,
        ),
        *_conns(1, "fe80::30", "ff02::fb", 70, 0, source__mac=M_LAPTOP),
    ]

    async def test_only_link_local_folds_and_the_rest_is_reported(self):
        status, body = await self.get("/api/devices")
        self.assertEqual(status, 200, body)
        rows = {d["ip"]: _figures(d) for d in body["devices"]}
        # started 3 (30/1,500), answered 3 (15/15), link-local 1 (70 up); 2 ULA left out
        self.assertEqual(
            rows[LAPTOP], (3 + 3 + 1, 30 + 15 + 70, 1500 + 15, 1, 2, "no_gateway")
        )
        self.assertEqual(rows[SERVER], (3 + 3, 15 + 1500, 15 + 30, 0, 2, "no_gateway"))


def _drop(agg_name):
    def tamper(body, reply):
        if agg_name in body.get("aggs", {}):
            return {**reply, "aggregations": {}}
        return reply

    return tamper


def _failed_next_hop_check(body, reply):
    if body.get("terminate_after"):
        return {"error": {"type": "search_phase_execution_exception"}, "status": 500}
    return reply


class TestPartialAnsweredSide(AccountingCase):
    tamper = staticmethod(_drop("answered"))

    async def test_a_partial_answered_side_is_502_not_a_smaller_figure(self):
        for path in ("/api/devices", "/api/bandwidth/devices"):
            status, body = await self.get(path)
            self.assertEqual(status, 502, path)
            self.assertIn("error", body)


class TestFailedNextHopCheck(AccountingCase):
    tamper = staticmethod(_failed_next_hop_check)

    async def test_an_unanswered_gateway_check_is_502(self):
        for path in ("/api/devices", f"/api/devices/{LAPTOP}", "/api/traffic/summary"):
            status, _ = await self.get(path)
            self.assertEqual(status, 502, path)


class TestNetworkDirection(AccountingCase):
    """B-d: upload is what leaves your devices for the internet, whoever opened the connection."""

    # the server's 300 + 4,000, the router's 60, the laptop's IPv6 300 + 40
    UPLOAD = 300 + 4000 + 60 + 300 + 40
    DOWNLOAD = 600 + 200 + 120 + 3000 + 4000
    # LAN to LAN (30 + 1,500) and multicast (140 + 180)
    LOCAL = 30 + 1500 + 140 + 180

    async def test_the_summary_reads_from_the_lan_side(self):
        status, body = await self.get("/api/traffic/summary")
        self.assertEqual(status, 200, body)
        self.assertEqual(
            (body["upload_bytes"], body["download_bytes"], body["local_bytes"]),
            (self.UPLOAD, self.DOWNLOAD, self.LOCAL),
        )
        # the originator's sums are unchanged, and the parts add up to them
        self.assertEqual(body["total_bytes"], self.UPLOAD + self.DOWNLOAD + self.LOCAL)

    async def test_daily_and_the_bandwidth_series_add_up_the_same(self):
        status, body = await self.get("/api/bandwidth/daily")
        self.assertEqual(status, 200, body)
        days = body["daily"]
        status, series = await self.get("/api/traffic/bandwidth")
        self.assertEqual(status, 200, series)
        for points in (days, series["series"]):
            self.assertEqual(
                tuple(
                    sum(p[k] for p in points)
                    for k in ("upload_bytes", "download_bytes", "local_bytes")
                ),
                (self.UPLOAD, self.DOWNLOAD, self.LOCAL),
            )


class TestGuessesSayWhatTheyRestOn:
    """B-h (DEV-7/8/9): a type or OS shown as a guess, with its basis."""

    def test_the_basis_follows_the_category_order(self):
        assert _category_basis(None, None, None) is None
        assert _category_basis("Linux", "Living-Room-Roku", None) == "name"
        assert _category_basis("iOS", "myphone", None) == "os"
        assert _category_basis(None, "office-printer", None) == "name"
        assert _category_basis(None, None, "Sonos, Inc.") == "vendor"

    @staticmethod
    def _os(ua):
        return next((name for p, name in _OS_PATTERNS if p.search(ua)), None)

    def test_specific_platforms_win_over_the_os_they_embed(self):
        tizen = "Mozilla/5.0 (SMART-TV; Linux; Tizen 6.0) AppleWebKit/537.36"
        xbox = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; Xbox; Xbox One) Edge/44"
        assert self._os(tizen) == "Smart TV"
        assert self._os(xbox) == "Xbox"
        assert self._os("Mozilla/5.0 (Windows NT 10.0; Win64; x64)") == "Windows 10/11"
