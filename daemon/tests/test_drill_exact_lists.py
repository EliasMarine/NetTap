"""NET-160 slice 2b-1: a count's link opens a list holding exactly that count.

The evaluator fake runs the real queries over one fixed set of documents, so each count and
its linked list are checked against the same data: a smart alert's ×N against the Alerts list
filtered to its signature, source and destination (plus the device on a device page), and
Home's Connections against Log Explorer's conn search with the summary's excluded sources.
"""

from types import SimpleNamespace

from aiohttp.test_utils import AioHTTPTestCase

from api.alerts import register_alert_routes
from api.logs import register_log_routes
from api.traffic import register_traffic_routes
from services.excluded_ips import parse_single_ip
from tests.fake_drill_opensearch import (
    AUTH,
    FROM,
    TO,
    WINDOW,
    DrillOpenSearch,
    alert,
    conn,
    dns,
    make_app,
)

DEVICE, A = "192.168.1.20", "192.168.1.30"
B, C = "93.184.216.34", "93.184.216.35"
V6_SRC, V6_DST = "2001:db8::20", "2001:db8::1"
# S2 has a "/", as real ET names do (Win32/…): a term on rule.name matches it as text
S1, S2, S3 = "ET SCAN First rule", "ET MALWARE Win32/Second CnC", "ET SCAN Third rule"
EARLIER = "2026-11-04T10:00:00.000Z"  # outside WINDOW


def _alert(doc_id, src, dst, rule, **fields):
    doc = alert(src, dst, rule=rule, _id=doc_id, **fields)
    return {k: v for k, v in doc.items() if v is not None}


ALERTS = [
    _alert("d1", DEVICE, B, S1),
    _alert("d2", DEVICE, B, S1, t="2026-11-05T11:00:00.000Z"),
    _alert("d3", DEVICE, C, S1),  # the neighbouring pair
    _alert("d4", DEVICE, B, S2),  # a second signature on the same pair
    _alert(
        "d5", DEVICE, B, S3, alert__signature="A shown name"
    ),  # display != rule.name
    _alert("d6", DEVICE, B, "", alert__signature="Looks normal"),  # empty rule.name
    _alert("d7", [DEVICE, A], B, S1),  # multi-valued source
    _alert("d8", DEVICE, None, S1),  # no destination.ip
    _alert("d9", A, B, S1),  # A → B, never the device
    _alert("d10", V6_SRC, V6_DST, S1),  # an IPv6 pair
    _alert("d11", A, C, S1),
    # in neither count nor list: outside the window, an engine event, not an alert
    _alert("n1", DEVICE, B, S1, t=EARLIER),
    _alert("n2", DEVICE, B, "SURICATA STREAM pkt seen on wrong thread"),
    conn(DEVICE, B, _id="n3", rule__name=S1),
]


def _register(app, client):
    storage = SimpleNamespace(_client=client)
    app["storage"] = storage
    register_alert_routes(app, storage)
    register_traffic_routes(app, storage)
    register_log_routes(app, storage)


class DrillCase(AioHTTPTestCase):
    docs: list = []
    excluded: list = []

    async def get_application(self):
        self.os = DrillOpenSearch(self.docs)
        return make_app(self.os, _register, excluded_ips=self.excluded)

    async def get(self, path, params=None):
        resp = await self.client.get(path, params=params, headers=AUTH)
        return resp.status, await resp.json()


class TestSmartAlertLinks(DrillCase):
    docs = ALERTS

    async def _groups(self, device=None):
        params = {"from": FROM, "to": TO, **({"device_ip": device} if device else {})}
        status, body = await self.get("/api/alerts/smart", params)
        self.assertEqual(status, 200)
        return body

    async def _listed(self, params):
        status, body = await self.get("/api/alerts", {**params, "size": "200"})
        self.assertEqual(status, 200)
        return body["total"], sorted(a["_id"] for a in body["alerts"])

    async def _check_links(self, reply, expected, narrow):
        """Every linkable group's list holds its count and exactly its documents."""
        keys = [tuple(g["key"].values()) for g in reply["alerts"]]
        linkable = {
            k: g["count"] for k, g in zip(keys, reply["alerts"]) if all(k)
        }  # null or empty key parts get no link
        self.assertEqual(linkable, {k: len(ids) for k, ids in expected.items()})
        for (rule, src, dst), ids in expected.items():
            # the parameters alertsHrefForSignature writes, over the response's own window
            params = {
                "signature": rule,
                "src": src,
                "dst": dst,
                "from": reply["from"],
                "to": reply["to"],
                **narrow,
            }
            self.assertEqual(await self._listed(params), (len(ids), sorted(ids)))

    async def test_every_device_group_link_lists_exactly_its_count(self):
        reply = await self._groups(DEVICE)
        expected = {
            (S1, DEVICE, B): ["d1", "d2", "d7"],
            (S1, A, B): ["d7"],  # the multi-valued source; d9 never involves the device
            (S1, DEVICE, C): ["d3"],
            (S2, DEVICE, B): ["d4"],
            (S3, DEVICE, B): ["d5"],
        }
        await self._check_links(reply, expected, {"ip": DEVICE})
        unlinked = {tuple(g["key"].values()) for g in reply["alerts"]} - set(expected)
        self.assertEqual(unlinked, {("", DEVICE, B), (S1, DEVICE, None)})

    async def test_every_home_group_link_lists_exactly_its_count(self):
        reply = await self._groups()
        expected = {
            (S1, DEVICE, B): ["d1", "d2", "d7"],
            (S1, A, B): ["d7", "d9"],
            (S1, DEVICE, C): ["d3"],
            (S1, A, C): ["d11"],
            (S2, DEVICE, B): ["d4"],
            (S3, DEVICE, B): ["d5"],
            (S1, V6_SRC, V6_DST): ["d10"],
        }
        await self._check_links(reply, expected, {})
        unlinked = {tuple(g["key"].values()) for g in reply["alerts"]} - set(expected)
        self.assertEqual(unlinked, {("", DEVICE, B), (S1, DEVICE, None)})

    async def test_the_key_is_the_buckets_own_values_not_the_displayed_signature(self):
        reply = await self._groups(DEVICE)
        shown = {g["signature"]: g["key"] for g in reply["alerts"]}
        self.assertEqual(
            shown["A shown name"],
            {"rule_name": S3, "source_ip": DEVICE, "destination_ip": B},
        )
        self.assertEqual(shown["Looks normal"]["rule_name"], "")
        no_dst = [g for g in reply["alerts"] if g["key"]["destination_ip"] is None]
        self.assertEqual(
            [g["key"] for g in no_dst],
            [{"rule_name": S1, "source_ip": DEVICE, "destination_ip": None}],
        )


class TestAlertListFilters(DrillCase):
    docs = ALERTS

    async def test_signature_src_and_dst_each_add_an_exact_term(self):
        status, _ = await self.get(
            "/api/alerts", {"signature": S1, "src": A, "dst": B, **_window()}
        )
        self.assertEqual(status, 200)
        clauses = self.os.bodies[-1]["query"]["bool"]["filter"]
        for clause in (
            {"term": {"rule.name": S1}},
            {"term": {"source.ip": A}},
            {"term": {"destination.ip": B}},
        ):
            self.assertIn(clause, clauses)

    async def test_a_bad_address_is_a_400_and_nothing_is_searched(self):
        for name in ("ip", "src", "dst"):
            for bad in ("1.2.3", "10.0.0.0/8", "host", "fe80::1%eth0"):
                status, body = await self.get("/api/alerts", {name: bad})
                self.assertEqual(status, 400, (name, bad))
                self.assertIn("ip, src and dst", body["error"])
        self.assertEqual(self.os.bodies, [])

    async def test_ipv6_is_matched_in_its_canonical_form(self):
        status, body = await self.get(
            "/api/alerts", {"src": "2001:DB8::20", "dst": "2001:0db8::1", **_window()}
        )
        self.assertEqual((status, body["total"]), (200, 1))
        clauses = self.os.bodies[-1]["query"]["bool"]["filter"]
        self.assertIn({"term": {"source.ip": V6_SRC}}, clauses)
        self.assertIn({"term": {"destination.ip": V6_DST}}, clauses)


def test_scoped_ipv6_is_not_one_address():
    assert parse_single_ip("fe80::1%eth0") is None
    assert parse_single_ip('fe80::1%" OR *:* OR "') is None
    assert parse_single_ip("fe80::1") == "fe80::1"


def _window():
    return dict(pair.split("=") for pair in WINDOW.split("&"))


E4, E6 = "192.168.1.199", "2001:db8::199"
CONNS = [
    conn(E4, B, _id="c1"),  # excluded IPv4 source
    conn(E6, V6_DST, _id="c2"),  # excluded IPv6 source
    conn(DEVICE, B, _id="c3"),
    conn(A, E4, _id="c4"),  # an excluded address as the destination stays in
    dns("example.com", src=DEVICE, _id="c5"),  # not a conn record
    conn(DEVICE, B, t=EARLIER, _id="c6"),  # outside the window
]


class ConnectionsCase(DrillCase):
    docs = CONNS

    async def _summary_then_list(self):
        status, summary = await self.get("/api/traffic/summary", _window())
        self.assertEqual(status, 200)
        params = {"log_type": "zeek.conn", "size": "500", **_window()}
        if summary["excluded_ips"]:
            params["exclude_src"] = ",".join(summary["excluded_ips"])
        status, found = await self.get("/api/logs/search", params)
        self.assertEqual(status, 200)
        return summary, found


class TestConnectionsLink(ConnectionsCase):
    # stored as typed: a CIDR from before validation, and an IPv6 in capitals
    excluded = [E4, "2001:DB8::199", "10.0.0.0/8"]

    async def test_the_log_search_holds_exactly_the_connections_count(self):
        summary, found = await self._summary_then_list()
        self.assertEqual(summary["excluded_ips"], [E4, E6])
        self.assertEqual(found["total"], summary["connection_count"])
        self.assertEqual(sorted(h["_id"] for h in found["hits"]), ["c3", "c4"])

    async def test_the_reported_list_is_the_one_the_count_left_out(self):
        summary, _ = await self._summary_then_list()
        summary_body = next(b for b in self.os.bodies if "aggs" in b)
        self.assertEqual(
            summary_body["query"]["bool"]["must_not"],
            [{"terms": {"source.ip": summary["excluded_ips"]}}],
        )

    async def test_a_bad_exclude_src_entry_is_a_400_and_nothing_is_searched(self):
        for bad in ("10.0.0.0/8", "host", f"{E4},1.2.3", "fe80::1%eth0"):
            status, body = await self.get("/api/logs/search", {"exclude_src": bad})
            self.assertEqual(status, 400, bad)
            self.assertIn("exclude_src", body["error"])
        self.assertEqual(self.os.bodies, [])


class TestConnectionsLinkWithManyExclusions(ConnectionsCase):
    # 51 distinct addresses: the search takes them all, as the count does
    excluded = [E4, E6] + [f"10.9.0.{n}" for n in range(1, 50)]

    async def test_every_exclusion_is_taken_and_the_totals_still_match(self):
        summary, found = await self._summary_then_list()
        self.assertEqual(len(summary["excluded_ips"]), 51)
        self.assertEqual(found["total"], summary["connection_count"])
        self.assertEqual(sorted(h["_id"] for h in found["hits"]), ["c3", "c4"])
