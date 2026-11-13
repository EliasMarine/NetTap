"""GET /api/local-services (NET-264): the mDNS and SSDP announcements seen, one row per sender.

The evaluator fake runs the real queries over documents shaped like the G11's Zeek records
(dns records carry no MAC or VLAN; the conn record with the same uid does), so the rows are
checked against the records behind them, not against canned replies.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from api import local_services
from api.local_services import register_local_service_routes
from storage.exact_terms import SearchTimedOut
from tests.fake_drill_opensearch import (
    AUTH,
    WINDOW,
    DrillOpenSearch,
    conn,
    dns,
    make_app,
)

GROUP4, GROUP6, SSDP_GROUP = "224.0.0.251", "ff02::fb", "239.255.255.250"
HUE, HUE6, M_HUE = "192.168.1.154", "fe80::200:5eff:fe00:5354", "00:00:5e:00:53:54"
ROUTER, M_ROUTER = "10.10.0.1", "00:00:5e:00:53:01"
ROUTER6 = "fe80::200:5eff:fe00:5301"  # the router's link-local, the same on every VLAN
LINK = "fe80::1"  # a sender with no conn record at all
QUERIER, TV, M_TV = "192.168.1.30", "192.168.1.70", "00:00:5e:00:53:70"
HUB = "hue bridge - 0a0b0c._hue._tcp.local"
HOMEKIT = "philips hue homekit._hap._tcp.local"
AIRPLAY = "living room._airplay._tcp.local"
PRINTER = "printer._ipp._tcp.local"
SCANNER = "scanner._uscan._tcp.local"
INCOMPLETE = "Couldn't read the network data: the local service search was incomplete."


def at(hm: str) -> str:
    return f"2026-11-05T{hm}.000Z"


def announce(src, uid, t, *names, dst=GROUP4, **fields):
    """An mDNS response as Zeek logs it: the answers are every record's rdata (service lists,
    host names, addresses, TXT and NSEC strings), the query the first name."""
    return dns(
        names[0],
        src=src,
        dst=dst,
        t=t,
        destination__port=5353,
        source__port=5353,
        zeek__uid=uid,
        zeek__dns__AA=True,
        zeek__dns__answers=[
            "TXT 25 bridgeid=0017880a0b0c TXT 14 modelid=BSB002",
            "_hue._tcp.local",
            "_printer._sub._http._tcp.local",
            *names,
            "0017880a0b0c.local",
            "192.168.1.154",
            f"NSEC {names[0]} {names[0]}",
        ],
        **fields,
    )


def flow(src, uid, t, mac, vlan=None, dst=GROUP4):
    """The conn record of one mDNS flow: Zeek writes it once the flow has gone idle."""
    return conn(
        src,
        dst,
        t,
        source__port=5353,
        destination__port=5353,
        zeek__uid=uid,
        source__mac=mac,
        log__file__path="conn.log",
        **({"network__vlan__id": [vlan]} if vlan else {}),
    )


DOCS = [
    # The Hue bridge, untagged: two closed flows over IPv4 and one over its link-local
    flow(HUE, "Chue1", at("10:00:00"), M_HUE),
    announce(HUE, "Chue1", at("10:00:30"), HUB, HOMEKIT),
    flow(HUE, "Chue2", at("11:00:00"), M_HUE),
    announce(HUE, "Chue2", at("11:00:30"), HUB, HOMEKIT),
    flow(HUE6, "Chue6", at("10:10:00"), M_HUE, dst=GROUP6),
    announce(HUE6, "Chue6", at("11:30:00"), HUB, dst=GROUP6),
    # The router re-sends the bridge's announcement on VLAN 2
    flow(ROUTER, "Crtr1", at("10:20:00"), M_ROUTER, "2"),
    announce(ROUTER, "Crtr1", at("10:20:30"), HUB),
    # Its link-local is seen untagged and on VLAN 2: the same IP and MAC, two senders
    flow(ROUTER6, "Crl0", at("10:30:00"), M_ROUTER, dst=GROUP6),
    announce(ROUTER6, "Crl0", at("10:30:10"), AIRPLAY, dst=GROUP6),
    flow(ROUTER6, "Crl2", at("10:31:00"), M_ROUTER, "2", dst=GROUP6),
    announce(ROUTER6, "Crl2", at("10:31:10"), AIRPLAY, dst=GROUP6),
    # ... and a third flow of it with no conn record: who sent it is not known
    announce(ROUTER6, "Crl9", at("10:45:00"), AIRPLAY, dst=GROUP6),
    # Two flows from one link-local address, neither with a conn record
    announce(LINK, "Cnj1", at("10:40:00"), PRINTER, dst=GROUP6),
    announce(LINK, "Cnj2", at("10:41:00"), PRINTER, dst=GROUP6),
    # A unicast exchange: the querier originated it and got the bridge's answer back
    flow(QUERIER, "Cuni", at("10:50:00"), "00:00:5e:00:53:30", dst=HUE),
    announce(QUERIER, "Cuni", at("10:50:01"), "spoofed._airplay._tcp.local", dst=HUE),
    # A question the bridge asked, which Zeek pairs with its own reply (every mDNS ID is 0)
    dns(
        AIRPLAY,
        src=HUE,
        dst=GROUP4,
        t=at("10:05:00"),
        destination__port=5353,
        source__port=5353,
        zeek__uid="Chue1",
        zeek__dns__answers=[HUB],
    ),
    # Browse domains and service lists are no services
    dns(
        "lb._dns-sd._udp.local",
        src=HUE,
        dst=GROUP4,
        t=at("10:00:31"),
        destination__port=5353,
        zeek__uid="Chue1",
        zeek__dns__answers=["local"],
    ),
    # Two flows of it that read the same on screen: same IP, instance and time
    announce(LINK, "Cdup1", at("10:42:00"), SCANNER, dst=GROUP6),
    announce(LINK, "Cdup2", at("10:42:00"), SCANNER, dst=GROUP6),
    # Outside the window
    announce(HUE, "Cold", "2026-11-04T10:00:00.000Z", "old._airplay._tcp.local"),
    # SSDP: a NOTIFY from port 1900, and an M-SEARCH from an ephemeral port
    conn(
        TV,
        SSDP_GROUP,
        at("10:55:00"),
        source__port=1900,
        destination__port=1900,
        source__mac=M_TV,
    ),
    conn(
        TV,
        SSDP_GROUP,
        at("11:55:00"),
        source__port=1900,
        destination__port=1900,
        source__mac=M_TV,
    ),
    conn(
        QUERIER,
        SSDP_GROUP,
        at("11:56:00"),
        source__port=50123,
        destination__port=1900,
        source__mac="00:00:5e:00:53:30",
    ),
]


class Owners:
    """device_custom: the owner renamed the TV."""

    def present(self, row: dict) -> dict:
        own = "Lounge TV" if row.get("mac") == M_TV else None
        return {**row, "custom_name": own, **({"hostname": own} if own else {})}


class Registry:
    NAMES = {
        M_HUE.upper(): "Hue bridge",
        M_ROUTER.upper(): "Router",
        M_TV.upper(): "tv",
    }

    def get_devices(self, macs: list[str]) -> dict:
        return {m.upper(): m.upper() for m in macs if m.upper() in self.NAMES}

    def get_name(self, device: str, own: bool = True) -> str:
        return self.NAMES[device]


def _register(app, client):
    app["device_custom"] = Owners()
    app["device_registry"] = Registry()
    register_local_service_routes(app, client)


class Case(AioHTTPTestCase):
    docs: list = DOCS
    tamper = None
    window = WINDOW

    async def get_application(self):
        self.os = DrillOpenSearch(self.docs, tamper=self.tamper)
        return make_app(self.os, _register)

    async def get(self, query: str | None = None) -> tuple[int, dict]:
        resp = await self.client.get(
            f"/api/local-services?{query or self.window}", headers=AUTH
        )
        return resp.status, await resp.json()

    async def rows(self) -> list[dict]:
        """The reply's rows without their ids, once every id is checked to be its own."""
        status, body = await self.get()
        self.assertEqual(status, 200, body)
        self.assertFalse(body["truncated"])
        ids = [r["id"] for r in body["rows"]]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{16}", i) for i in ids))
        return [{k: v for k, v in r.items() if k != "id"} for r in body["rows"]]


def _find(rows, instance, **sender):
    return [
        r
        for r in rows
        if r["instance"] == instance
        and all(r["sender"][k] == v for k, v in sender.items())
    ]


class TestAnnouncements(Case):
    async def test_a_sender_seen_as_one_mac_and_vlan_gets_one_row_per_service(self):
        rows = await self.rows()
        hub = _find(rows, "hue bridge - 0a0b0c", mac=M_HUE)
        # IPv4 and link-local flows of one MAC, untagged, merge; the newest gives the IP
        self.assertEqual(
            hub,
            [
                {
                    "protocol": "mdns",
                    "service_type": "_hue._tcp",
                    "instance": "hue bridge - 0a0b0c",
                    "sender": {
                        "ip": HUE6,
                        "mac": M_HUE,
                        "name": "Hue bridge",
                        "vlan": None,
                        "vlan_state": "untagged",
                    },
                    "last_seen": at("11:30:00"),
                }
            ],
        )
        homekit = _find(rows, "philips hue homekit", mac=M_HUE)
        self.assertEqual(
            [(r["sender"]["ip"], r["last_seen"]) for r in homekit],
            [(HUE, at("11:00:30"))],
        )

    async def test_a_reflected_announcement_is_the_reflectors_row(self):
        rows = await self.rows()
        by_router = _find(rows, "hue bridge - 0a0b0c", ip=ROUTER)
        self.assertEqual(len(by_router), 1)
        self.assertEqual(
            by_router[0]["sender"],
            {
                "ip": ROUTER,
                "mac": M_ROUTER,
                "name": "Router",
                "vlan": "2",
                "vlan_state": "tagged",
            },
        )

    async def test_one_address_on_two_vlans_stays_two_senders(self):
        rows = await self.rows()
        seen = sorted(
            (r["sender"]["vlan_state"], r["sender"]["vlan"], r["sender"]["mac"])
            for r in _find(rows, "living room", ip=ROUTER6)
        )
        # both joined (untagged, VLAN 2), and the flow with no conn record on its own
        self.assertEqual(
            seen,
            [
                ("tagged", "2", M_ROUTER),
                ("unknown", None, None),
                ("untagged", None, M_ROUTER),
            ],
        )

    async def test_flows_with_no_conn_record_keep_their_ip_and_are_never_merged(self):
        rows = await self.rows()
        printers = _find(rows, "printer")
        self.assertEqual(
            sorted(r["last_seen"] for r in printers), [at("10:40:00"), at("10:41:00")]
        )
        for r in printers:
            self.assertEqual(
                r["sender"],
                {
                    "ip": LINK,
                    "mac": None,
                    "name": None,
                    "vlan": None,
                    "vlan_state": "unknown",
                },
            )

    async def test_two_flows_that_read_the_same_keep_their_own_ids(self):
        """Unresolved flows are kept apart by uid, which the reply leaves out: the id tells
        the page's table their rows apart."""
        _, body = await self.get()
        twins = [r for r in body["rows"] if r["instance"] == "scanner"]
        self.assertEqual(len(twins), 2)
        self.assertNotEqual(twins[0]["id"], twins[1]["id"])
        strip = [{k: v for k, v in r.items() if k != "id"} for r in twins]
        self.assertEqual(strip[0], strip[1])
        # the same request gives the same ids
        _, again = await self.get()
        self.assertEqual(
            {r["id"] for r in again["rows"]}, {r["id"] for r in body["rows"]}
        )

    async def test_a_question_the_sender_asked_is_not_its_announcement(self):
        """A multicast reply has no question section (RFC 6762 §6): zeek.dns.query is what the
        sender asked, so another device's instance there gives the sender no row."""
        rows = await self.rows()
        self.assertEqual(_find(rows, "living room", ip=HUE), [])
        self.assertEqual(_find(rows, "living room", mac=M_HUE), [])
        self.assertEqual(len(_find(rows, "hue bridge - 0a0b0c", mac=M_HUE)), 1)

    async def test_a_unicast_exchange_never_names_the_querier(self):
        rows = await self.rows()
        self.assertEqual([r for r in rows if r["sender"]["ip"] == QUERIER], [])
        self.assertEqual(_find(rows, "spoofed"), [])

    async def test_only_service_instances_in_the_window_are_rows(self):
        rows = await self.rows()
        mdns = {
            (r["service_type"], r["instance"]) for r in rows if r["protocol"] == "mdns"
        }
        self.assertEqual(
            mdns,
            {
                ("_hue._tcp", "hue bridge - 0a0b0c"),
                ("_hap._tcp", "philips hue homekit"),
                ("_airplay._tcp", "living room"),
                ("_ipp._tcp", "printer"),
                ("_uscan._tcp", "scanner"),
            },
        )

    async def test_ssdp_rows_are_notify_senders_named_by_mac(self):
        rows = await self.rows()
        ssdp = [r for r in rows if r["protocol"] == "ssdp"]
        self.assertEqual(
            ssdp,
            [
                {
                    "protocol": "ssdp",
                    "service_type": None,
                    "instance": None,
                    "sender": {
                        "ip": TV,
                        "mac": M_TV,
                        "name": "Lounge TV",
                        "vlan": None,
                        "vlan_state": "untagged",
                    },
                    "last_seen": at("11:55:00"),
                }
            ],
        )

    async def test_rows_are_newest_first_and_every_read_has_the_budget(self):
        _, body = await self.get()
        seen = [r["last_seen"] for r in body["rows"]]
        self.assertEqual(seen, sorted(seen, reverse=True))
        self.assertTrue(self.os.budgets)
        self.assertTrue(all(b is not None for b in self.os.budgets))
        self.assertEqual(
            (body["from"], body["to"]), ("2026-11-05T00:00:00Z", "2026-11-05T12:00:00Z")
        )

    # OLD CODE START — NET-264 review: a cap of 2 also cut the reads, so they said truncated too
    # async def test_a_long_list_is_cut_and_says_so(self):
    #     with patch.object(local_services, "LIST_CAP", 2):
    #         status, body = await self.get()
    #     self.assertEqual(status, 200)
    #     self.assertTrue(body["truncated"])
    #     self.assertEqual(len(body["rows"]), 2)
    # OLD CODE END
    async def test_a_long_list_is_cut_and_says_so(self):
        whole = await self.rows()
        reads = Reads()
        with patch.object(local_services, "LIST_CAP", 6), reads.patch():
            status, body = await self.get()
        self.assertEqual(status, 200)
        # every read is whole: only the row cut says truncated
        self.assertTrue(reads.log)
        self.assertTrue(all(done for _, done in reads.log), reads.log)
        self.assertGreater(len(whole), 6)
        self.assertTrue(body["truncated"])
        self.assertEqual(
            [r["last_seen"] for r in body["rows"]], [r["last_seen"] for r in whole[:6]]
        )

    async def test_a_capped_sender_list_joins_every_uid(self):
        """Past the cap an address's second (MAC, VLAN) may be unread, so no address is
        taken as one sender: every flow is joined by its uid."""
        with patch.object(local_services, "LIST_CAP", 1):
            status, body = await self.get()
        self.assertEqual(status, 200)
        self.assertTrue(body["truncated"])
        (per_flow,) = [
            b
            for b in self.os.bodies
            if [*b["aggs"]["all"]["composite"]["sources"][0]] == ["uid"]
            and "a" in b["aggs"]["all"].get("aggs", {})
        ]
        self.assertEqual(
            per_flow["query"]["bool"]["should"][0],
            {"bool": {"must_not": [{"terms": {"source.ip": []}}]}},
        )


REAL_ALL_BUCKETS = local_services.all_buckets


class Reads:
    """all_buckets, logging each read's (what, complete?); `short` = (what, nth) cuts the nth
    read of `what` short before its first page, as a cap would."""

    def __init__(self, short: tuple[str, int] | None = None) -> None:
        self.short, self.log = short, []

    def __call__(self, *args, **kw):
        nth = sum(w == kw["what"] for w, _ in self.log)
        if (kw["what"], nth) == self.short:
            buckets, done = [], False
        else:
            buckets, done = REAL_ALL_BUCKETS(*args, **kw)
        self.log.append((kw["what"], done))
        return buckets, done

    def patch(self):
        return patch.object(local_services, "all_buckets", self)


NOW = datetime.now(timezone.utc)


def ago(minutes: float) -> str:
    when = NOW - timedelta(minutes=minutes)
    return when.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _page_buckets(body: dict) -> int:
    """The most buckets one page of a composite body can answer: its size times one per
    bucket and one per name each terms list may hold."""
    agg = body["aggs"]["all"]
    lists = sum(
        a["terms"]["size"] for a in agg.get("aggs", {}).values() if "terms" in a
    )
    return agg["composite"]["size"] * (1 + lists)


class TestPageSizes(Case):
    async def test_no_page_asks_for_more_buckets_than_a_reply_may_hold(self):
        await self.rows()
        self.assertTrue(self.os.bodies)
        for body in self.os.bodies:
            self.assertLessEqual(_page_buckets(body), local_services.PAGE_BUCKETS, body)
        lists = {
            body["aggs"]["all"]["aggs"]["a"]["terms"]["size"]
            for body in self.os.bodies
            if "a" in body["aggs"]["all"].get("aggs", {})
        }
        self.assertEqual(
            lists, {local_services.NAMES_PER_SENDER, local_services.NAMES_PER_FLOW}
        )

    async def test_one_bucket_pages_give_the_same_rows(self):
        whole = await self.rows()
        with patch.object(
            local_services, "PAGE_BUCKETS", local_services.NAMES_PER_FLOW + 1
        ):
            paged = await self.rows()
        self.assertEqual(paged, whole)

    async def test_the_names_reads_stop_at_their_budget(self):
        def per_flow_pages() -> int:
            return sum(
                [*b["aggs"]["all"]["composite"]["sources"][0]] == ["uid"]
                and "a" in b["aggs"]["all"].get("aggs", {})
                for b in self.os.bodies
            )

        one_flow_a_page = patch.object(
            local_services, "PAGE_BUCKETS", local_services.NAMES_PER_FLOW + 1
        )
        with one_flow_a_page:
            _, whole = await self.get()
        self.assertFalse(whole["truncated"])
        unbounded = per_flow_pages()
        self.assertGreater(unbounded, 1)

        with one_flow_a_page, patch.object(local_services, "NAMES_READ", 1):
            status, body = await self.get()
        self.assertEqual(status, 200)
        self.assertTrue(body["truncated"])
        # the first page passes the budget, so no second one is asked for
        self.assertEqual(per_flow_pages() - unbounded, 1)


class TestOpenFlows(Case):
    """A flow announced in the last minutes has no conn record yet: its own row, even from an
    address otherwise seen as one sender."""

    docs = [
        flow(HUE, "Cdone", ago(50), M_HUE),
        announce(HUE, "Cdone", ago(49), HUB),
        announce(HUE, "Copen", ago(40), HUB),
        announce(HUE, "Copen", ago(2), HUB),
    ]
    window = f"from={ago(60)}&to={ago(-1)}"

    async def test_an_open_flow_is_not_merged_into_the_known_sender(self):
        rows = await self.rows()
        self.assertEqual(
            sorted(
                (r["sender"]["vlan_state"], r["sender"]["mac"] or "", r["last_seen"])
                for r in rows
            ),
            [("unknown", "", ago(2)), ("untagged", M_HUE, ago(49))],
        )
        self.assertTrue(all(r["sender"]["ip"] == HUE for r in rows))

    READS = [
        ("the open mDNS flows", 0),
        ("the mDNS connections", 0),  # the open flows' conn records
        ("the mDNS senders", 0),
        ("the mDNS names per sender", 0),
        ("the mDNS names per flow", 0),
        ("the mDNS connections", 1),  # the per-flow uids' conn records
        ("the SSDP senders", 0),
    ]

    async def test_any_read_cut_short_says_truncated(self):
        whole = Reads()
        with whole.patch():
            await self.rows()
        for what, nth in self.READS:  # each read below happens here
            self.assertGreater(sum(w == what for w, _ in whole.log), nth, what)
        for short in self.READS:
            with self.subTest(short), Reads(short).patch():
                status, body = await self.get()
                self.assertEqual(status, 200)
                self.assertTrue(body["truncated"])

    async def test_a_cut_open_flows_list_joins_every_uid(self):
        """Past its cap the open flows read may miss a flow: then no address is taken as one
        sender, or that flow's names would go to the known one."""
        with Reads(("the open mDNS flows", 0)).patch():
            _, body = await self.get()
        self.assertTrue(body["truncated"])
        self.assertEqual(
            sorted(r["sender"]["vlan_state"] for r in body["rows"]),
            ["unknown", "untagged"],
        )


class TestFlowStartedBeforeWindow(Case):
    """A conn record is stamped when its flow starts: one 10 minutes before `from`, on a second
    VLAN, still shows the address is two senders."""

    docs = [
        flow(TV, "Cv2", at("01:00:00"), M_TV, "2"),
        announce(TV, "Cv2", at("01:00:30"), PRINTER),
        flow(TV, "Cv40", "2026-11-04T23:50:00.000Z", M_TV, "40"),
        announce(TV, "Cv40", at("00:05:00"), PRINTER),
    ]

    async def test_its_vlan_is_its_own_row(self):
        rows = await self.rows()
        self.assertEqual(
            sorted(
                (r["sender"]["vlan"], r["last_seen"]) for r in _find(rows, "printer")
            ),
            [("2", at("01:00:30")), ("40", at("00:05:00"))],
        )


class TestSendersWithoutMac(Case):
    """Two senders whose conn records carry no MAC are told apart by their IP."""

    docs = [
        flow(HUE, "Cm1", at("10:00:00"), None),
        announce(HUE, "Cm1", at("10:00:30"), PRINTER),
        flow(TV, "Cm2", at("10:01:00"), None),
        announce(TV, "Cm2", at("10:01:30"), PRINTER),
    ]

    async def test_each_is_its_own_row(self):
        rows = await self.rows()
        self.assertEqual(
            sorted((r["sender"]["ip"], r["sender"]["vlan_state"]) for r in rows),
            [(HUE, "untagged"), (TV, "untagged")],
        )


class TestTruncatedNames(Case):
    @staticmethod
    def tamper(body, reply):
        for b in reply.get("aggregations", {}).get("all", {}).get("buckets", []):
            if "a" in b:
                b["a"]["sum_other_doc_count"] = 1
        return reply

    async def test_a_sender_with_more_names_than_the_list_says_truncated(self):
        status, body = await self.get()
        self.assertEqual(status, 200)
        self.assertTrue(body["truncated"])


class TestFailures(Case):
    async def test_bad_windows_are_400s(self):
        for query, words in [
            ("from=2026-11-01T00:00:00Z&to=2026-11-08T00:00:01Z", "at most 7 days"),
            ("from=2026-11-05T12:00:00Z&to=2026-11-05T00:00:00Z", "later than"),
            ("from=yesterday", "ISO 8601"),
        ]:
            status, body = await self.get(query)
            self.assertEqual(status, 400, query)
            self.assertIn(words, body["error"])
        self.assertEqual(self.os.bodies, [])

    async def test_seven_days_is_allowed(self):
        status, _ = await self.get("from=2026-11-01T00:00:00Z&to=2026-11-08T00:00:00Z")
        self.assertEqual(status, 200)


class TestPartialReply(Case):
    @staticmethod
    def tamper(body, reply):
        return {**reply, "_shards": {"total": 2, "failed": 1}}

    async def test_a_partial_read_is_a_502_never_fewer_rows(self):
        status, body = await self.get()
        self.assertEqual((status, body), (502, {"error": INCOMPLETE}))


# OLD CODE START — NET-264 review: a timed_out reply never reaches here (the client raises)
# class TestTimedOut(Case):
#     @staticmethod
#     def tamper(body, reply):
#         return {**reply, "timed_out": True}
#
#     async def test_a_timed_out_read_says_try_a_shorter_range(self):
#         status, body = await self.get()
#         self.assertEqual(status, 503)
#         self.assertIn("took too long", body["error"])
# OLD CODE END
class TestTimedOut(Case):
    # what the daemon's client raises for a timed-out search (storage/exact_terms.py), as in
    # test_moment_api.py
    @staticmethod
    def tamper(body, reply):
        raise SearchTimedOut("the search timed out")

    async def test_is_the_written_502_incomplete(self):
        status, body = await self.get()
        self.assertEqual((status, body), (502, {"error": INCOMPLETE}))


def test_a_g11_names_reply_reads_as_service_instances():
    """The per-sender names read, as the G11 answered it for the router's reflections."""
    path = Path(__file__).parent / "fixtures" / "local_services_names_g11.json"
    (bucket,) = json.loads(path.read_text())["aggregations"]["all"]["buckets"]
    names, complete = local_services._instances(bucket)
    assert complete
    assert (
        names[("_raop._tcp", "020000000004@living room")] == "2026-11-13T19:07:07.840Z"
    )
    assert names[("_sleep-proxy._udp", "70-35-60-63.1 living room")]
    assert names[("_hue._tcp", "hue bridge - 0a0b0c")] == "2026-11-13T19:24:54.052Z"
    # the router asked for this one: it is in its query list only, so it is no row of its own
    assert ("_srpl-tls._tcp", "living room") not in names
    # every name the answers listed is one instance
    assert len(names) == len({b["key"] for b in bucket["a"]["buckets"]})


def test_record_strings_are_not_instances():
    """Zeek's rdata strings can end like an instance: the names read's exclude drops them, and
    Python drops the rest that aren't services."""
    for rdata in (f"NSEC {HUB} {HOMEKIT}", "TXT 9 md=BSB002 x._hap._tcp.local"):
        assert re.fullmatch(local_services._RDATA_RX, rdata)
    assert not re.fullmatch(local_services._RDATA_RX, HUB)
    bucket = {
        "a": {
            "sum_other_doc_count": 0,
            "buckets": [
                {"key": k, "last": {"value": 1794597894052.0}}
                for k in ("_services._dns-sd._udp.local", "lb._dns-sd._udp.local", HUB)
            ],
        },
    }
    names, _ = local_services._instances(bucket)
    assert list(names) == [("_hue._tcp", "hue bridge - 0a0b0c")]
