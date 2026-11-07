"""NET-160 slice 2b-2: a raw Suricata category's page, and the list each of its figures opens.

The evaluator fake runs the real queries over one fixed set of documents, so every figure on
GET /api/alerts/suricata/{name} is checked against the Alerts list (suricata_category= plus
the link's other filters) over the same data and the page's own window.
"""

import tempfile
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote

from aiohttp.test_utils import AioHTTPTestCase, make_mocked_request

from api import alerts, suricata_categories
from api.alerts import (
    _normalize_alert_source,
    register_alert_routes,
    valid_suricata_category,
)
from api.suricata_categories import register_suricata_category_routes
from services.live_connections import LiveConnectionTracker
from storage import snapshot_search
from tests.fake_drill_opensearch import (
    AUTH,
    FROM,
    TO,
    WINDOW,
    DrillOpenSearch,
    alert,
    conn,
    make_app,
)
from tests.test_daemon_auth import _make_full_app

L1, L2, L3 = "192.168.1.10", "192.168.1.20", "192.168.1.30"
R1, R2, R3 = "93.184.216.34", "93.184.216.35", "198.51.100.7"
MISC, PBT = "Misc activity", "Potentially Bad Traffic"
C2, C2_SPACED = (
    "Command_And_Control",
    "Command and Control",
)  # the tactic, spelt both ways
ODD = "Info Leak/Probe & C 50%"  # a "/", a "&" and a "%"
ONE, TWO = "ET POLICY one", "ET POLICY two"
EARLIER = "2026-11-04T10:00:00.000Z"  # outside WINDOW
# The page's tiles and the severity= each one links to
TILES = {"high": "1", "medium": "2", "low": "3", "info": "info"}


def _alert(doc_id, src, dst, rule, cats, sev=None, t="2026-11-05T10:30:00.000Z"):
    doc = alert(
        src,
        dst,
        rule=rule,
        t=t,
        _id=doc_id,
        rule__category=cats,
        suricata__alert__severity=sev,
    )
    return {k: v for k, v in doc.items() if v is not None}


DOCS = [
    _alert("m1", L1, R1, ONE, MISC, 3, t="2026-11-05T10:00:00.000Z"),  # a slot's start
    _alert("m2", L1, R1, ONE, MISC, 3, t="2026-11-05T11:30:00.000Z"),
    _alert("m3", L2, R2, None, MISC, 2, t="2026-11-05T09:59:59.999Z"),  # no rule.name
    _alert("m4", L2, R1, "", MISC, 1),  # an empty rule.name
    _alert(
        "m5", L1, L1, "Unknown", MISC
    ),  # same address both ends; a rule named Unknown
    _alert("m6", [L1, L2], R2, ONE, MISC, 3, t=FROM),  # multi-valued source, at `from`
    _alert("m7", L3, R3, TWO, MISC, 4, t=TO),  # a severity outside 1–3, at `to`
    _alert("m10", None, R1, ONE, MISC, 2),  # no source.ip
    _alert("m11", L3, None, TWO, MISC, 1),  # no destination.ip
    # in no count and no list: engine noise, outside the window, not an alert
    _alert("n1", L1, R1, "SURICATA STREAM pkt seen on wrong thread", MISC, 3),
    _alert("n2", L1, R1, ONE, MISC, 3, t=EARLIER),
    conn(L1, R1, _id="n3", rule__category=MISC),
    # [PBT, C2] and [C2]: PBT's page counts 1 alert also tagged C2, C2's own page counts 2
    _alert("p1", L1, R3, "ET MALWARE x", [PBT, C2], 1),
    _alert("p2", L2, R3, "ET MALWARE x", [C2], 2),
    _alert("p3", L1, R3, "ET MALWARE y", [PBT, C2_SPACED], 2),
    _alert("s1", L1, R1, "ET INFO z", ODD, 3),
    _alert("s2", L2, R1, "ET INFO z", ODD, 3),
    _alert("s3", L3, R1, TWO, ODD, 3),  # a rule seen under two categories
]
MISC_IDS = ["m1", "m10", "m11", "m2", "m3", "m4", "m5", "m6", "m7"]


def _register(app, client):
    storage = SimpleNamespace(_client=client)
    app["storage"] = storage
    register_alert_routes(app, storage)
    register_suricata_category_routes(app, client)


def _path(name: str) -> str:
    return f"/api/alerts/suricata/{quote(name, safe='')}"


class CategoryCase(AioHTTPTestCase):
    docs: list = DOCS

    async def get_application(self):
        self.os = DrillOpenSearch(list(self.docs))
        return make_app(self.os, _register)

    async def page(self, name, query=WINDOW, status=200):
        resp = await self.client.get(f"{_path(name)}?{query}", headers=AUTH)
        self.assertEqual(resp.status, status, await resp.text())
        return await resp.json()

    async def listed(self, page, **params):
        """(total, ids) of the Alerts list over the page's own window."""
        query = {**params, "from": page["from"], "to": page["to"], "size": "200"}
        resp = await self.client.get("/api/alerts", params=query, headers=AUTH)
        self.assertEqual(resp.status, 200, await resp.text())
        body = await resp.json()
        return body["total"], sorted(a["_id"] for a in body["alerts"])


class TestEveryFigureOpensItsCount(CategoryCase):
    async def test_the_total_and_each_severity_tile(self):
        page = await self.page(MISC)
        self.assertEqual(page["total"], 9)
        self.assertEqual(await self.listed(page, suricata_category=MISC), (9, MISC_IDS))
        self.assertEqual(
            page["severity"], {"high": 2, "medium": 2, "low": 3, "info": 2}
        )
        expected = {
            "high": ["m11", "m4"],
            "medium": ["m10", "m3"],
            "low": ["m1", "m2", "m6"],
            "info": ["m5", "m7"],  # no severity, and a 4
        }
        for tile, code in TILES.items():
            listed = await self.listed(page, suricata_category=MISC, severity=code)
            self.assertEqual(listed, (page["severity"][tile], expected[tile]), tile)

    async def test_every_named_rule(self):
        page = await self.page(MISC)
        rules = page["rules"]
        self.assertEqual(
            [(r["rule_name"], r["count"]) for r in rules["rows"]],
            [(ONE, 4), (TWO, 2), ("", 1), ("Unknown", 1), (None, 1)],
        )  # null, "", a literal "Unknown" and named rules stay apart
        self.assertEqual(rules["rows"][0]["last_seen"], "2026-11-05T11:30:00.000Z")
        self.assertEqual((rules["distinct"], rules["examined"]), (5, 5))
        self.assertTrue(rules["complete"])
        expected = {
            ONE: ["m1", "m10", "m2", "m6"],
            TWO: ["m11", "m7"],
            "Unknown": ["m5"],
        }
        for row in rules["rows"]:
            if not row[
                "rule_name"
            ]:  # null and "" get no link: the list can't filter them
                continue
            listed = await self.listed(
                page, suricata_category=MISC, signature=row["rule_name"]
            )
            self.assertEqual(listed, (row["count"], expected[row["rule_name"]]))

    async def test_every_source_and_target(self):
        page = await self.page(MISC)
        sources, targets = page["sources"], page["targets"]
        # m6's two sources count once each; m5 is L1's source and its target, never summed
        self.assertEqual(
            [(r["ip"], r["count"]) for r in sources["rows"]],
            [(L1, 4), (L2, 3), (L3, 2)],
        )
        self.assertEqual(
            [(r["ip"], r["count"]) for r in targets["rows"]],
            [(R1, 4), (R2, 2), (L1, 1), (R3, 1)],
        )
        self.assertEqual((sources["missing"], targets["missing"]), (1, 1))
        self.assertEqual((sources["distinct"], targets["distinct"]), (3, 4))
        for side, param in ((sources, "src"), (targets, "dst")):
            self.assertTrue(side["complete"])
            for row in side["rows"]:
                total, ids = await self.listed(
                    page, suricata_category=MISC, **{param: row["ip"]}
                )
                self.assertEqual(total, row["count"], (param, row["ip"]))
                self.assertEqual(len(ids), total)

    async def test_also_tagged_counts_the_alerts_carrying_both(self):
        pbt = await self.page(PBT)
        self.assertEqual(pbt["total"], 2)
        also = pbt["also_tagged"]
        self.assertEqual(
            [(r["category"], r["count"]) for r in also["rows"]],
            [(C2_SPACED, 1), (C2, 1)],
        )
        self.assertEqual((also["distinct"], also["complete"]), (2, True))
        # The count is p1 alone; C2's own page counts p1 and p2, so the count is no link to it
        c2 = await self.page(C2)
        self.assertEqual(c2["total"], 2)
        self.assertEqual(await self.listed(c2, suricata_category=C2), (2, ["p1", "p2"]))
        self.assertEqual([r["category"] for r in c2["also_tagged"]["rows"]], [PBT])
        self.assertEqual((await self.page(MISC))["also_tagged"]["rows"], [])

    async def test_a_name_with_a_slash_ampersand_and_percent(self):
        page = await self.page(ODD)
        self.assertEqual((page["name"], page["total"]), (ODD, 3))
        self.assertEqual(
            await self.listed(page, suricata_category=ODD), (3, ["s1", "s2", "s3"])
        )

    async def test_each_timeline_slot_equals_a_range_count_of_its_bounds(self):
        page = await self.page(MISC)
        slots = page["timeline"]
        self.assertEqual(len(slots), 13)  # 00:00 to the slot holding `to`, hourly
        self.assertEqual(sum(s["n"] for s in slots), page["total"])
        for slot in slots:
            start = datetime.fromisoformat(slot["t"].replace("Z", "+00:00"))
            end = start + timedelta(hours=1)
            bounds = {"gte": slot["t"], "lt": end.isoformat()}
            self.assertEqual(slot["n"], self._count_misc(bounds), slot["t"])
        by_start = {s["t"][11:16]: s["n"] for s in slots}
        # `from`, 09:59:59.999, a slot's own start and `to` each land in their own slot
        self.assertEqual(
            {k: n for k, n in by_start.items() if n},
            {"00:00": 1, "09:00": 1, "10:00": 5, "11:00": 1, "12:00": 1},
        )

    def _count_misc(self, bounds: dict) -> int:
        """Written apart from the endpoint: MISC alerts in the window and in `bounds`."""
        query = {
            "bool": {
                "filter": [
                    {"range": {"@timestamp": {"gte": FROM, "lte": TO}}},
                    {"range": {"@timestamp": bounds}},
                    {"term": {"event.provider": "suricata"}},
                    {"term": {"event.dataset": "alert"}},
                    {"term": {"rule.category": MISC}},
                ],
                "must_not": [{"prefix": {"rule.name": "SURICATA "}}],
            }
        }
        body = {"size": 0, "track_total_hits": True, "query": query}
        return self.os.search(body, index="arkime_sessions3-*")["hits"]["total"][
            "value"
        ]

    async def test_the_page_counts_with_the_lists_own_query(self):
        page = await self.page(MISC)
        page_query = self.os.bodies[0]["query"]
        await self.listed(page, suricata_category=MISC)
        self.assertEqual(self.os.bodies[-1]["query"], page_query)

    async def test_one_snapshot_a_later_record_shows_only_in_a_later_list(self):
        late = _alert("late", L1, R1, ONE, MISC, 3)

        def tamper(body, reply):
            if "pit" in body and late not in self.os.docs:
                self.os.docs.append(late)  # indexed once the snapshot is open
            return reply

        self.os.tamper = tamper
        page = await self.page(MISC)
        self.assertEqual((page["total"], page["sources"]["rows"][0]["count"]), (9, 4))
        self.assertEqual(sum(page["severity"].values()), 9)
        self.assertEqual(len({b["pit"]["id"] for b in self.os.bodies}), 1)
        self.assertEqual(
            await self.listed(page, suricata_category=MISC),
            (10, sorted([*MISC_IDS, "late"])),
        )


CAP = "Capped"


class TestCappedEnumeration(CategoryCase):
    docs = [
        _alert(f"c{i}", src, R1, rule, CAP, 3)
        for i, (src, rule) in enumerate(
            [
                ("10.0.0.1", "r1"),
                ("10.0.0.2", "r2"),
                ("10.0.0.3", "r3"),  # the busiest address and rule, last in key order
                ("10.0.0.3", "r3"),
                ("10.0.0.3", "r3"),
                (None, "r3"),
            ]
        )
    ]

    async def test_a_capped_list_is_the_busiest_read_with_no_distinct_count(self):
        with (
            patch.object(snapshot_search, "GROUP_PAGE", 2),
            patch.object(suricata_categories, "LIST_CAP", 2),
        ):
            page = await self.page(CAP)
        self.assertEqual(page["total"], 6)
        for part, key in (("sources", "ip"), ("rules", "rule_name")):
            found = page[part]
            self.assertEqual(
                (found["complete"], found["distinct"], found["examined"]),
                (False, None, 2),
                part,
            )
            self.assertNotIn(
                "10.0.0.3" if key == "ip" else "r3", [r[key] for r in found["rows"]]
            )
        self.assertEqual(page["sources"]["missing"], 1)  # exact even when capped
        self.assertEqual(
            (page["targets"]["complete"], page["targets"]["distinct"]), (True, 1)
        )


class TestValidation(CategoryCase):
    async def test_a_bad_name_is_a_400_and_nothing_is_searched(self):
        for name in ("   ", "x" * 1025):
            body = await self.page(name, status=400)
            self.assertEqual(body, {"error": "That isn't a Suricata category name."})
        resp = await self.client.get("/api/alerts/suricata/", headers=AUTH)
        self.assertEqual(resp.status, 404)  # an empty name never reaches the page
        self.assertEqual(self.os.bodies, [])
        self.assertEqual((await self.page("x" * 1024))["total"], 0)

    async def test_a_bad_window_is_a_400_with_its_own_message(self):
        body = await self.page(MISC, "to=yesterday", status=400)
        self.assertIn("to must be an ISO 8601 time", body["error"])
        long = "from=1900-01-01T00:00:00Z&to=2026-11-05T00:00:00Z"
        body = await self.page(MISC, long, status=400)
        self.assertIn("too long", body["error"])
        self.assertEqual(self.os.bodies, [])

    async def test_the_list_refuses_a_bad_suricata_category(self):
        for bad in ("", "   ", "x" * 1025):
            resp = await self.client.get(
                "/api/alerts", params={"suricata_category": bad}, headers=AUTH
            )
            self.assertEqual(resp.status, 400, bad)
            self.assertEqual(
                await resp.json(),
                {"error": "suricata_category must be 1–1024 characters"},
            )
        self.assertEqual(self.os.bodies, [])

    async def test_a_slash_reaches_the_page_encoded_or_not(self):
        for path in ("/api/alerts/suricata/a/b", "/api/alerts/suricata/a%2Fb"):
            resp = await self.client.get(f"{path}?{WINDOW}", headers=AUTH)
            self.assertEqual(resp.status, 200, path)
            self.assertEqual((await resp.json())["name"], "a/b", path)

    async def test_the_route_needs_the_token(self):
        self.assertEqual((await self.client.get(_path(MISC))).status, 401)


def _broken(kind: str, pit: bool):
    """A tamper that breaks the PIT searches (pit=True) or the index searches."""

    def tamper(body, reply):
        if ("pit" in body) != pit:
            return reply
        if kind == "timed_out":
            return {**reply, "timed_out": True}
        if kind == "shard":
            return {**reply, "_shards": {"total": 2, "failed": 1}}
        if kind == "no_aggs":
            return {k: v for k, v in reply.items() if k != "aggregations"}
        return {**reply, "hits": {"hits": reply["hits"]["hits"]}}  # no total

    return tamper


class TestFailures(CategoryCase):
    async def test_an_incomplete_list_search_is_a_502_not_a_smaller_list(self):
        for kind in ("timed_out", "shard", "no_total"):
            self.os.tamper = _broken(kind, pit=False)
            resp = await self.client.get(
                "/api/alerts", params={"suricata_category": MISC}, headers=AUTH
            )
            self.assertEqual(resp.status, 502, kind)
            self.assertEqual(
                await resp.json(), {"error": "The alert search was incomplete"}
            )

    async def test_the_page_is_a_503_when_too_slow_and_a_502_when_a_shard_fails(self):
        self.os.tamper = _broken("timed_out", pit=True)
        body = await self.page(MISC, status=503)
        self.assertIn("took too long", body["error"])
        self.os.tamper = _broken("shard", pit=True)
        body = await self.page(MISC, status=502)
        self.assertIn("shard(s) failed", body["error"])

    async def test_severity_tiles_that_dont_add_up_fail_the_page(self):
        self.os.docs.append(_alert("x", L1, R1, ONE, MISC, [1, 2]))
        body = await self.page(MISC, status=502)
        self.assertIn("don't add up", body["error"])


class TestTopListsOpenTheirCounts(CategoryCase):
    """The Alerts page's Top signatures and top IP cards: every row equals the list it opens."""

    async def top(self, path, **params):
        query = {"from": FROM, "to": TO, **params}
        resp = await self.client.get(path, params=query, headers=AUTH)
        self.assertEqual(resp.status, 200, await resp.text())
        return await resp.json()

    async def test_every_signature_row_equals_its_signature_list(self):
        top = await self.top("/api/alerts/top-signatures", limit="100")
        self.assertEqual((top["complete"], top["examined"]), (True, 8))
        self.assertEqual(
            [(s["signature"], s["count"], s["severity"]) for s in top["signatures"]],
            [
                (ONE, 4, 3),
                (TWO, 3, 1),  # a 4, a 1 and a 3: the lowest key wins the tie, as before
                ("ET INFO z", 2, 3),
                ("ET MALWARE x", 2, 1),
                ("", 1, 1),
                ("ET MALWARE y", 1, 2),
                ("Unknown", 1, 3),  # no severity: low, as before
                (None, 1, 2),  # no rule.name, apart from "" and a rule named Unknown
            ],
        )
        for row in top["signatures"]:
            if row["signature"]:  # the list can't filter a null or "" name
                listed = await self.listed(top, signature=row["signature"])
                self.assertEqual(listed[0], row["count"], row["signature"])

    async def test_every_ip_row_equals_its_src_or_dst_list(self):
        expected = {
            "src": [(L1, 7), (L2, 5), (L3, 3)],  # m6's two sources count once each
            "dest": [(R1, 7), (R3, 4), (R2, 2), (L1, 1)],
        }
        for direction, param in (("src", "src"), ("dest", "dst")):
            top = await self.top("/api/alerts/top-ips", direction=direction, limit="50")
            self.assertEqual(
                (top["complete"], top["examined"]), (True, len(expected[direction]))
            )
            rows = [(r["ip"], r["count"]) for r in top["ips"]]
            self.assertEqual(rows, expected[direction])
            for ip, count in rows:
                listed = await self.listed(top, **{param: ip})
                self.assertEqual(listed[0], count, (direction, ip))
            top = await self.top("/api/alerts/top-ips", direction=direction, limit="2")
            self.assertEqual([(r["ip"], r["count"]) for r in top["ips"]], rows[:2])

    async def test_a_capped_top_list_says_so(self):
        with (
            patch.object(alerts, "_TOP_PAGE", 2),
            patch.object(alerts, "_TOP_CAP", 2),
        ):
            sigs = await self.top("/api/alerts/top-signatures")
            ips = await self.top("/api/alerts/top-ips", direction="src")
        self.assertEqual((sigs["complete"], sigs["examined"]), (False, 2))
        self.assertNotIn(ONE, [s["signature"] for s in sigs["signatures"]])
        self.assertEqual((ips["complete"], ips["examined"]), (False, 2))
        self.assertNotIn(L3, [r["ip"] for r in ips["ips"]])

    async def test_an_incomplete_search_is_a_502_not_a_shorter_list(self):
        for kind in ("timed_out", "shard", "no_aggs"):
            self.os.tamper = _broken(kind, pit=False)
            for path in ("/api/alerts/top-signatures", "/api/alerts/top-ips"):
                resp = await self.client.get(path, headers=AUTH)
                self.assertEqual(resp.status, 502, (kind, path))
                self.assertEqual(
                    await resp.json(), {"error": "The alert search was incomplete"}
                )


class TestRouteTable(AioHTTPTestCase):
    """The daemon's own router: the page and every other /api/alerts/... route keep theirs."""

    async def get_application(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        return _make_full_app(self._tmp.name)

    async def _resolve(self, path, method="GET"):
        found = await self.app.router.resolve(
            make_mocked_request(method, path, app=self.app)
        )
        return getattr(found.handler, "__name__", None), dict(found)

    async def test_each_path_reaches_its_own_handler(self):
        page = "handle_suricata_category"
        cases = [
            ("/api/alerts/suricata/Misc%20activity", page, {"name": MISC}),
            ("/api/alerts/suricata/a/b", page, {"name": "a/b"}),
            ("/api/alerts/suricata/a%2Fb", page, {"name": "a/b"}),
            ("/api/alerts/suricata/smart", page, {"name": "smart"}),
            ("/api/alerts/smart", "handle_smart_alerts", {}),
            ("/api/alerts/smart/summary", "handle_smart_alert_summary", {}),
            ("/api/alerts/count", "handle_alerts_count", {}),
            ("/api/alerts/timeline", "handle_alerts_timeline", {}),
            (
                "/api/alerts/categories/exploit",
                "handle_alert_category_detail",
                {"category": "exploit"},
            ),
            (
                "/api/alerts/categories/exploit/timeline",
                "handle_alert_category_timeline",
                {"category": "exploit"},
            ),
            ("/api/alerts/abc123", "handle_alert_detail", {"id": "abc123"}),
        ]
        for path, handler, info in cases:
            self.assertEqual(await self._resolve(path), (handler, info), path)
        self.assertEqual(
            await self._resolve("/api/alerts/abc123/acknowledge", "POST"),
            ("handle_alert_acknowledge", {"id": "abc123"}),
        )


def test_valid_suricata_category():
    assert valid_suricata_category("Misc activity") == "Misc activity"
    assert valid_suricata_category(" padded ") == " padded "  # as stored, never trimmed
    assert valid_suricata_category("x" * 1024) == "x" * 1024
    for bad in ("", " ", "\t\n", "x" * 1025, None, 3, ["Misc activity"]):
        assert valid_suricata_category(bad) is None, bad


def test_severity_clauses_are_the_lists():
    assert alerts.severity_clauses("1") == (
        [{"term": {"suricata.alert.severity": 1}}],
        [],
    )
    assert alerts.severity_clauses("info") == (
        [],
        [{"terms": {"suricata.alert.severity": [1, 2, 3]}}],
    )
    for ignored in ("", "4", "high"):
        assert alerts.severity_clauses(ignored) == ([], [])


def test_rule_category_holds_the_stored_values():
    def shown(source):
        return _normalize_alert_source(source)["alert"]

    for read in (shown, LiveConnectionTracker()._parse_alert_entry):
        assert read({"rule": {"name": "ET x", "category": MISC}})["rule_category"] == [
            MISC
        ]
        both = read({"rule": {"name": "ET x", "category": [PBT, C2]}})
        assert (both["category"], both["rule_category"]) == (PBT, [PBT, C2])
        missing = read({"rule": {"name": "ET x"}, "alert": {"category": "Shown"}})
        assert (missing["category"], missing["rule_category"]) == ("Shown", [])
        blank = read({"rule": {"name": "ET x", "category": ["", "  ", MISC]}})
        assert blank["rule_category"] == [MISC]  # only values a page exists for
