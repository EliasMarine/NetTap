"""GET /api/moment/devices (NET-249): the busiest devices in a window and what each talked to.

The evaluator fake runs the real queries over fixed documents, so the ranking is checked
against /api/devices itself and the breakdown against the records behind it.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from aiohttp.test_utils import AioHTTPTestCase
from opensearchpy import ConnectionError as OpenSearchConnectionError
from opensearchpy import ConnectionTimeout

from api import devices, drilldown_runner, moment
from api.devices import register_device_routes
from api.dns import register_dns_routes
from api.moment import register_moment_routes
from api.traffic import _ZEEK_CONN_FILTERS
from services.dns_analytics import _ZEEK_DNS_FILTERS, DNS_LOOKUP_EXCLUSION
from services.excluded_ips import CONN_ACCOUNTING, build_lan_filter
from storage.exact_terms import PartialResultsError, SearchTimedOut
from storage.snapshot_search import Budget
from tests.fake_drill_opensearch import (
    AUTH,
    FROM,
    WINDOW,
    DrillOpenSearch,
    conn,
    dns,
    make_app,
)

LAN = build_lan_filter([(192, 168, 1)])
EXCLUDED = ["192.168.1.2"]
LAPTOP, NAS = "192.168.1.30", "192.168.1.40"
# three small devices, each named by one of the device list's later name sources
PHONE, TV, CAM = "192.168.1.60", "192.168.1.70", "192.168.1.80"
ALL = [LAPTOP, NAS, PHONE, TV, CAM]  # largest first; the three small ones tie, by IP
M_LAPTOP, M_NAS, M_ROUTER = (
    "00:00:5e:00:53:30",
    "00:00:5e:00:53:40",
    "00:00:5e:00:53:01",
)
# the phone's connections carry its Wi-Fi MAC; DHCP gave its own: the list shows that one
M_PHONE, M_PHONE_WIFI, M_TV, M_CAM = (
    "00:00:5E:00:53:60",
    "00:00:5E:00:53:61",
    "00:00:5E:00:53:70",
    "00:00:5E:00:53:80",
)
NET_A, NET_B, NET_C = "203.0.113.5", "198.51.100.7", "192.0.2.80"
# The reply's fields per device, as the web half builds against them (no local_bytes)
INCOMPLETE = "Couldn't read the network data: the device search was incomplete."
FIELDS = {
    "ip",
    "name",
    "mac",
    "total_bytes",
    "upload_bytes",
    "download_bytes",
    "connection_count",
    "ipv6_left_out",
    "ipv6_left_out_reason",
    "destinations",
    "domains",
    "apps",
}


def _started(
    dst,
    n,
    minute,
    sent,
    got,
    protocol,
    mac=M_ROUTER,
    src=LAPTOP,
    own=M_LAPTOP,
    **fields,
):
    """n connections `src` (the laptop) opened to `dst`, each answered."""
    return [
        conn(
            src,
            dst,
            f"2026-11-05T10:{minute + i:02d}:00.000Z",
            source__bytes=sent,
            destination__bytes=got,
            network__bytes=sent + got,
            destination__packets=1,
            network__protocol=protocol,
            source__mac=own,
            destination__mac=mac,
            **fields,
        )
        for i in range(n)
    ]


DOCS = [
    *_started(NET_A, 3, 0, 100, 900, "ssl"),  # 3,000 bytes
    *_started(NET_B, 2, 5, 50, 50, "http"),
    # a conn record carrying a DNS name is still no lookup
    *_started(NET_B, 1, 8, 50, 50, "http", zeek__dns__query="conn-only.example"),
    # one Zeek gave no service label: an app all the same
    *_started(NET_C, 1, 9, 100, 400, None),
    # the NAS only answers: 4,020 bytes, and it starts nothing
    *_started(NAS, 4, 10, 5, 1000, "smb", mac=M_NAS),
    dns("example.com", src=LAPTOP),
    dns("example.com", src=LAPTOP),
    dns("other.org", src=LAPTOP),
    dns("pcap-monitor", src=LAPTOP),  # Malcolm's own health check
    dns("printer.local", src=LAPTOP, dst="224.0.0.251", destination__port=5353),
    *_started(NET_A, 3, 20, 10, 10, "ssl", src=PHONE, own=M_PHONE_WIFI),
    *_started(NET_A, 3, 20, 10, 10, "ssl", src=TV, own=M_TV),
    *_started(NET_A, 3, 20, 10, 10, "ssl", src=CAM, own=M_CAM),
    # what the fingerprint reads: the phone's DHCP MAC, and the TV's name in a DNS answer
    {
        "@timestamp": "2026-11-05T10:30:00.000Z",
        "source.ip": PHONE,
        "dhcp.id": "1",
        "source.mac": M_PHONE,
    },
    {
        "@timestamp": "2026-11-05T10:30:00.000Z",
        "source.ip": TV,
        "destination.ip": "192.168.1.1",
        "network.protocol": "dns",
        "dns.ip": TV,
        "dns.host": "living-room-tv",
    },
]


def _is_breakdown(body: dict) -> bool:
    return "include" in body.get("aggs", {}).get("ips", {}).get("terms", {})


class Owners:
    """device_custom with one owner's name, on the laptop's MAC."""

    def present(self, row: dict) -> dict:
        if row.get("mac") != M_LAPTOP:
            return {**row, "custom_name": None}
        return {**row, "custom_name": "Study laptop", "hostname": "Study laptop"}


class Registry:
    """device_registry: the phone's DHCP MAC has a name; the camera's is a service name."""

    NAMES = {M_PHONE: "Kitchen phone", M_CAM: "Cam._hap._tcp.local"}

    def get_devices(self, macs: list[str]) -> dict:
        # keyed by the normalized MAC, as DeviceRegistry.get_devices answers
        return {m.upper(): m.upper() for m in macs if m.upper() in self.NAMES}

    def get_name(self, device: str, own: bool = True) -> str:
        return self.NAMES[device]


def _register(app, client):
    storage = SimpleNamespace(_client=client)
    app["storage"] = storage
    app["device_custom"] = Owners()
    app["device_registry"] = Registry()
    # a UniFi alias on the NAS: the list's second name source, so both pages read it alike
    app["unifi_integration"] = SimpleNamespace(
        is_configured=True,
        get_device_alias=lambda mac: "Media NAS" if mac == M_NAS else None,
        get_client_name_by_ip=lambda _ip: None,
    )
    register_device_routes(app, storage)
    register_dns_routes(app, storage)
    register_moment_routes(app, client)


class Case(AioHTTPTestCase):
    docs: list = DOCS
    tamper = None

    async def get_application(self):
        self.os = DrillOpenSearch(self.docs, tamper=self.tamper)
        self.changelog = MagicMock()
        self.changelog.log_event.return_value = {"_id": "a"}
        app = make_app(self.os, _register, lan_filter=LAN, excluded_ips=EXCLUDED)
        app["changelog_service"] = self.changelog
        return app

    async def get(self, path: str) -> tuple[int, dict]:
        sep = "&" if "?" in path else "?"
        resp = await self.client.get(f"{path}{sep}{WINDOW}", headers=AUTH)
        return resp.status, await resp.json()

    def breakdown(self) -> list[dict]:
        """The breakdown msearch's two bodies (started, looked up), as sent."""
        return [b for b in self.os.bodies if _is_breakdown(b)]


class TestMomentDevices(Case):
    async def test_the_ranking_and_totals_are_the_device_lists(self):
        status, body = await self.get("/api/moment/devices")
        self.assertEqual(status, 200, body)
        _, listed = await self.get("/api/devices?sort=bytes&limit=10")
        self.assertEqual([d["ip"] for d in body["devices"]], ALL)
        self.assertEqual(body["total_devices"], listed["total"])
        for got, row in zip(body["devices"], listed["devices"], strict=True):
            self.assertEqual(set(got), FIELDS)
            for field in FIELDS & set(row):
                if field not in ("destinations", "domains", "apps"):
                    self.assertEqual(got[field], row[field], field)
            self.assertEqual(
                got["name"],
                row.get("custom_name") or row.get("unifi_name") or row["hostname"],
            )
        # owner, UniFi, registry, hostname, and a registry service name left out
        self.assertEqual(
            [d["name"] for d in body["devices"]],
            ["Study laptop", "Media NAS", "Kitchen phone", "living-room-tv", None],
        )
        self.assertEqual(
            body["devices"][2]["mac"], M_PHONE
        )  # DHCP's, not the Wi-Fi one
        self.assertEqual((body["from"], body["to"]), (listed["from"], listed["to"]))

    async def test_what_a_device_started_ranks_by_bytes(self):
        _, body = await self.get("/api/moment/devices")
        laptop = body["devices"][0]
        self.assertEqual(
            laptop["destinations"],
            [
                {"ip": NAS, "bytes": 4020, "connections": 4},
                {"ip": NET_A, "bytes": 3000, "connections": 3},
                {"ip": NET_C, "bytes": 500, "connections": 1},
                {"ip": NET_B, "bytes": 300, "connections": 3},
            ],
        )
        self.assertEqual(
            laptop["apps"],
            [
                {"protocol": "smb", "bytes": 4020, "connections": 4},
                {"protocol": "ssl", "bytes": 3000, "connections": 3},
                {"protocol": "unknown", "bytes": 500, "connections": 1},
                {"protocol": "http", "bytes": 300, "connections": 3},
            ],
        )

    async def test_domains_are_its_lookups_without_noise_or_conn_records(self):
        _, body = await self.get("/api/moment/devices")
        self.assertEqual(
            body["devices"][0]["domains"],
            [
                {"domain": "example.com", "count": 2},
                {"domain": "other.org", "count": 1},
            ],
        )

    async def test_an_answer_only_device_keeps_its_row_with_empty_lists(self):
        _, body = await self.get("/api/moment/devices")
        nas = body["devices"][1]
        self.assertEqual(nas["ip"], NAS)
        self.assertGreater(nas["total_bytes"], 0)
        self.assertEqual(
            (nas["destinations"], nas["domains"], nas["apps"]), ([], [], [])
        )

    async def test_each_search_carries_its_own_predicate(self):
        await self.get("/api/moment/devices")
        started, looked_up = self.breakdown()
        query = started["query"]["bool"]
        self.assertEqual(query["filter"][0]["range"]["@timestamp"]["gte"], FROM)
        self.assertEqual(query["filter"][1:], _ZEEK_CONN_FILTERS)
        self.assertEqual(query["must_not"], [{"terms": {"source.ip": EXCLUDED}}])
        terms = started["aggs"]["ips"]["terms"]
        self.assertEqual((terms["include"], terms["size"]), (ALL, 5))

        query = looked_up["query"]["bool"]
        self.assertEqual(query["filter"][1:], _ZEEK_DNS_FILTERS)
        self.assertNotIn(CONN_ACCOUNTING, query["filter"])
        self.assertEqual(
            query["must_not"],
            [*DNS_LOOKUP_EXCLUSION, {"terms": {"source.ip": EXCLUDED}}],
        )
        self.assertEqual(looked_up["aggs"]["ips"]["terms"]["include"], ALL)

    async def test_every_read_carries_the_requests_budget(self):
        await self.get("/api/moment/devices")
        self.assertTrue(self.os.budgets)
        self.assertTrue(all(isinstance(b, Budget) for b in self.os.budgets))
        self.assertEqual(len({id(b) for b in self.os.budgets}), 1)  # one per request
        breakdown = [
            budget
            for body, budget in zip(self.os.bodies, self.os.budgets, strict=True)
            if _is_breakdown(body)
        ]
        self.assertEqual(len(breakdown), 2)

    async def test_limit_cuts_the_list_but_not_the_total(self):
        status, body = await self.get("/api/moment/devices?limit=1")
        self.assertEqual(status, 200, body)
        self.assertEqual(
            ([d["ip"] for d in body["devices"]], body["total_devices"]), ([LAPTOP], 5)
        )
        self.assertEqual(
            self.breakdown()[0]["aggs"]["ips"]["terms"]["include"], [LAPTOP]
        )

    async def test_a_limit_outside_1_to_25_is_a_400(self):
        for bad in ("0", "26", "-1", "2.5", "ten"):
            status, body = await self.get(f"/api/moment/devices?limit={bad}")
            self.assertEqual(status, 400, bad)
            self.assertIn("1 to 25", body["error"])
        self.assertEqual((await self.get("/api/moment/devices?limit=25"))[0], 200)


class TestNoDevices(Case):
    docs: list = []

    async def test_an_empty_window_is_an_empty_list_with_no_breakdown(self):
        status, body = await self.get("/api/moment/devices")
        self.assertEqual(status, 200, body)
        self.assertEqual((body["devices"], body["total_devices"]), ([], 0))
        self.assertEqual(self.breakdown(), [])


def _row(n: int, **fields) -> dict:
    """A device as _accounted_devices gives it."""
    return {
        "key": f"192.168.1.{100 + n}",
        "mac": None,
        "doc_count": 3,
        "total_bytes": 1000 - n,
        "upload_bytes": 100,
        "download_bytes": 900 - n,
        "connection_count": 3,
        "ipv6_connections": 0,
        "ipv6_left_out": 0,
        "ipv6_left_out_reason": None,
        **fields,
    }


class TestAccountedRows(Case):
    """_accounted_devices stood in for, so its fields can be set."""

    async def test_ipv6_left_out_and_its_reason_pass_through(self):
        rows = [
            _row(1, ipv6_left_out=5, ipv6_left_out_reason="router"),
            _row(2, ipv6_left_out=7, ipv6_left_out_reason="no_gateway"),
        ]
        with patch.object(moment, "_accounted_devices", return_value=rows):
            _, body = await self.get("/api/moment/devices")
        self.assertEqual(
            [(d["ipv6_left_out"], d["ipv6_left_out_reason"]) for d in body["devices"]],
            [(5, "router"), (7, "no_gateway")],
        )
        self.assertNotIn("ipv6_connections", body["devices"][0])

    async def test_ten_by_default_largest_first(self):
        rows = [_row(n) for n in range(12)]
        with patch.object(moment, "_accounted_devices", return_value=rows[::-1]):
            _, body = await self.get("/api/moment/devices")
        self.assertEqual(body["total_devices"], 12)
        self.assertEqual(
            [d["ip"] for d in body["devices"]], [r["key"] for r in rows[:10]]
        )


class TestFailures(Case):
    async def test_a_capped_device_read_is_a_502_and_says_why_on_the_changelog(self):
        real = devices.all_buckets

        def one_per_page(*args, **kwargs):
            return real(*args, **{**kwargs, "page_size": 1})

        with (
            patch.object(devices, "_DEVICE_CAP", 1),
            patch.object(devices, "_cap_event_next_at", 0.0),
            patch.object(devices, "all_buckets", one_per_page),
        ):
            status, body = await self.get("/api/moment/devices")
        # /api/devices' words for the same cap; the log has "stopped at 1 IPs"
        self.assertEqual((status, body["error"]), (502, INCOMPLETE))
        [(event_type, *_, metadata)] = [
            c.args for c in self.changelog.log_event.call_args_list
        ]
        self.assertEqual(event_type, "device_cap_reached")
        self.assertEqual(metadata, {"limit": 1, "search": "moment devices"})
        self.assertEqual(self.breakdown(), [])

    async def test_a_partial_ranking_is_the_written_502(self):
        failure = PartialResultsError("1 shard(s) failed on arkime_sessions3-*")
        with patch.object(moment, "_accounted_devices", side_effect=failure):
            status, body = await self.get("/api/moment/devices")
        self.assertEqual((status, body["error"]), (502, INCOMPLETE))

    async def test_an_unreachable_opensearch_is_a_502_without_its_text(self):
        failure = OpenSearchConnectionError(
            "N/A", "https://localhost:9200 refused", None
        )
        with patch.object(moment, "_accounted_devices", side_effect=failure):
            status, body = await self.get("/api/moment/devices")
        self.assertEqual(
            (status, body["error"]),
            (502, "Couldn't read the network data: the device search failed."),
        )

    async def test_a_breakdown_reply_short_of_a_search_is_a_502(self):
        real = self.os.msearch

        def one_short(body, **kwargs):
            reply = real(body, **kwargs)
            if not _is_breakdown(body[1]):
                return reply
            return {"responses": reply["responses"][:1]}

        with patch.object(self.os, "msearch", one_short):
            status, body = await self.get("/api/moment/devices")
        self.assertEqual((status, body["error"]), (502, INCOMPLETE))

    async def test_a_spent_budget_after_the_ranking_is_a_503_with_no_breakdown(self):
        now = {"t": 0.0}

        def ranking(*_args, **_kwargs):
            now["t"] += drilldown_runner.BUDGET_SECONDS + 1  # the ranking used it all
            return [_row(1)]

        names = MagicMock()
        with (
            patch.object(
                drilldown_runner, "Budget", lambda s: Budget(s, clock=lambda: now["t"])
            ),
            patch.object(moment, "_accounted_devices", ranking),
            patch.object(moment, "_names", names),
        ):
            status, body = await self.get("/api/moment/devices")
        self.assertEqual(status, 503, body)
        self.assertIn("too long", body["error"])
        names.assert_not_called()
        self.assertEqual(self.breakdown(), [])

    async def test_with_both_slots_held_no_work_starts_and_it_is_busy(self):
        slots = self.app["drill_slots"]
        await slots.acquire()
        await slots.acquire()
        ranking = MagicMock(return_value=[])
        try:
            with (
                patch.object(drilldown_runner, "BUDGET_SECONDS", 0.1),
                patch.object(moment, "_accounted_devices", ranking),
            ):
                status, body = await self.get("/api/moment/devices")
        finally:
            slots.release()
            slots.release()
        self.assertEqual(status, 503, body)
        self.assertIn("try again", body["error"])
        ranking.assert_not_called()


def _breakdown_fails(error=None, **reply_fields):
    """A tamper that breaks only the breakdown's searches: raises `error`, or changes the reply."""

    def tamper(body, reply):
        if not _is_breakdown(body):
            return reply
        if error is not None:
            raise error
        return {**reply, **reply_fields}

    return tamper


class TestBreakdownTimedOut(Case):
    # what the daemon's client raises for a timed-out search (storage/exact_terms.py)
    tamper = staticmethod(_breakdown_fails(SearchTimedOut("the search timed out")))

    async def test_is_the_written_502_incomplete(self):
        status, body = await self.get("/api/moment/devices")
        self.assertEqual(status, 502, body)
        self.assertIn("incomplete", body["error"])


class TestBreakdownShardFailed(Case):
    tamper = staticmethod(_breakdown_fails(_shards={"total": 2, "failed": 1}))

    async def test_is_a_502_never_shorter_lists(self):
        with self.assertLogs("nettap.api.moment", "WARNING") as logs:
            status, body = await self.get("/api/moment/devices")
        self.assertEqual((status, body["error"]), (502, INCOMPLETE))
        self.assertIn("shard(s) failed", logs.output[0])  # the reason, in the log only


class TestBreakdownOutOfTime(Case):
    # the no-retry client gave the read what was left of the budget, and it ran out
    tamper = staticmethod(
        _breakdown_fails(ConnectionTimeout("TIMEOUT", "read timed out", None))
    )

    async def test_is_a_503_too_slow_not_a_failure(self):
        status, body = await self.get("/api/moment/devices")
        self.assertEqual(status, 503, body)
        self.assertIn("took too long", body["error"])
