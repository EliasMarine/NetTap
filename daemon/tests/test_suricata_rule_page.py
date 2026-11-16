"""The rule page: GET /api/alerts/rule/{name}, keyed by the exact rule name.

The evaluator fake runs the real queries over one fixed set of documents, so every figure is
checked against the Alerts list (signature= plus the link's other filters) over the same data and
the page's own window. Facts are per SID; an address row is exact whatever the discovery cap.
"""

import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote

from aiohttp.test_utils import AioHTTPTestCase, make_mocked_request

from api import suricata_rule
from api.alerts import register_alert_routes
from api.suricata_rule import register_suricata_rule_routes, valid_rule_name
from services import rule_explainer as rx
from storage import snapshot_search
from tests.fake_drill_opensearch import (
    AUTH,
    WINDOW,
    DrillOpenSearch,
    alert,
    make_app,
)
from tests.test_daemon_auth import _make_full_app

L1, L2, L3 = "192.168.1.10", "192.168.1.20", "192.168.1.30"
R1, R2 = "93.184.216.34", "198.51.100.7"
V6 = "2001:db8::5"
EARLIER = "2026-11-04T10:00:00.000Z"  # outside WINDOW

DROP = "ET DROP Dshield Block Listed Source group 1"
STUN = "ET INFO Session Traversal Utilities for NAT (STUN Binding Request)"
SPLIT = "ET POLICY split across both lists"
SHARED = "ET EXPLOIT one name, two rules"
EMOTET = "ET MALWARE Win32/Emotet Activity"  # SID 2024792 is in data/suricata_descriptions.json
CRED = "ET POLICY Outgoing Basic Auth Base64 HTTP Password detected unencrypted"
CRED_ALL = "ET INFO Cleartext Password sent"
CRED_MANY = "ET INFO Cleartext Password many rules"
OWN = "NETTAP my own rule"
ODD = "ET INFO A/B & C 50%"
CUTOFF = "ET SCAN cutoff"


def _alert(
    doc_id,
    src,
    dst,
    rule,
    sid=None,
    sev=2,
    et=None,
    t="2026-11-05T10:30:00.000Z",
    **more,
):
    doc = alert(
        src,
        dst,
        rule=rule,
        t=t,
        _id=doc_id,
        rule__id=sid,
        suricata__alert__severity=sev,
        suricata__alert__metadata__signature_severity=et,
        **more,
    )
    return {k: v for k, v in doc.items() if v is not None}


DOCS = [
    # DROP: L1 is a target three times and both ends once; an IPv6 source; one alert has no
    # destination, one has neither address
    _alert(
        "d1",
        R1,
        L1,
        DROP,
        2402000,
        et=["Major"],
        rule__category=["Misc Attack"],
        t="2026-11-05T09:00:00.000Z",
    ),
    _alert("d2", R1, L1, DROP, 2402000, et=["Major"]),
    _alert("d3", R2, L2, DROP, 2402000, et=["Major"]),
    _alert("d4", L1, L1, DROP, 2402000, et=["Major"]),
    _alert("d5", V6, L1, DROP, 2402000, et=["Major"], t="2026-11-05T11:00:00.000Z"),
    _alert("d6", R1, None, DROP, 2402000, et=["Major"]),
    _alert("d7", None, None, DROP, 2402000, et=["Major"]),
    _alert("d8", R1, L1, DROP, 2402000, et=["Major"], t=EARLIER),  # outside the window
    # STUN: ET rates it informational, so only the activity list holds it
    _alert("a1", L2, R1, STUN, 2016149, sev=3, et=["Informational"]),
    _alert("a2", L2, R1, STUN, 2016149, sev=3, et=["Informational"]),
    # SPLIT: one counted alert, one activity alert
    _alert("s1", L3, R2, SPLIT, 2000010, et=["Minor"]),
    _alert("s2", L3, R2, SPLIT, 2000010, et=["Informational"]),
    # SHARED: one name under two SIDs whose facts disagree
    _alert(
        "x1",
        R1,
        L1,
        SHARED,
        2000001,
        sev=1,
        et=["Major"],
        threat__technique__id=["T1190"],
        threat__technique__name=["Exploit Public-Facing Application"],
        vulnerability__id=["CVE-2021-41773"],
        tags=["CISA_KEV"],
        rule__category=["Attempted Administrator Privilege Gain"],
    ),
    _alert(
        "x2",
        R2,
        L1,
        SHARED,
        2000002,
        sev=1,
        et=["Minor"],
        threat__technique__id=["T1083", "X1"],
        threat__technique__name=["File and Directory Discovery"],
        vulnerability__id=["CVE-12"],
    ),
    _alert(
        "x3", R2, L1, SHARED, 2000002, sev=1, et=["Minor"], t="2026-11-05T11:30:00.000Z"
    ),
    # EMOTET: one curated SID
    _alert("e1", L2, R1, EMOTET, 2024792, sev=1, et=["Major"]),
    # CRED: credential SID (Informational, counted), Major SID (counted), mixed SID (activity)
    _alert("c1", L1, R1, CRED, 2006380, et=["Informational"]),
    _alert("c2", L1, R1, CRED, 2006381, et=["Major"]),
    _alert("c3", L1, R1, CRED, 2006382, et=["Informational", "Major"]),
    # CRED_ALL: every SID a credential
    _alert("k1", L1, R1, CRED_ALL, 2006390, et=["Informational"]),
    _alert("k2", L2, R1, CRED_ALL, 2006391, et=["Informational"]),
    # OWN: a rule in the owner range
    _alert("o1", L1, R1, OWN, 1000001),
    # ODD: a "/", a "&" and a "%"
    _alert("z1", L1, R1, ODD, 2000020),
    # CUTOFF: L1 alerts only itself 3 times (6 by source + destination), L2 is 5 ordinary targets
    *[_alert(f"u{i}", L1, L1, CUTOFF, 2000030) for i in range(3)],
    *[_alert(f"v{i}", R1, L2, CUTOFF, 2000030) for i in range(5)],
    # engine noise is in no list
    _alert("n1", L1, R1, "SURICATA STREAM pkt seen on wrong thread", 2210000),
]
# CRED_MANY: ten credential SIDs with two alerts each hide an eleventh, Major one with one alert
for i in range(10):
    DOCS += [
        _alert(f"m{i}{j}", L1, R1, CRED_MANY, 2007000 + i, et=["Informational"])
        for j in range(2)
    ]
DOCS.append(_alert("m99", L1, R1, CRED_MANY, 2007099, et=["Major"]))


def _register(app, client):
    storage = SimpleNamespace(_client=client)
    app["storage"] = storage
    register_alert_routes(app, storage)
    register_suricata_rule_routes(app, client)


def _path(name: str) -> str:
    return f"/api/alerts/rule/{quote(name, safe='')}"


class RuleCase(AioHTTPTestCase):
    async def get_application(self):
        self.os = DrillOpenSearch(list(DOCS))
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


class TestFiguresOpenTheirLists(RuleCase):
    async def test_the_total_severity_and_timeline(self):
        page = await self.page(DROP)
        self.assertEqual(page["total"], 7)
        self.assertEqual(
            await self.listed(page, signature=DROP),
            (7, ["d1", "d2", "d3", "d4", "d5", "d6", "d7"]),
        )
        self.assertEqual(
            page["severity"], {"high": 0, "medium": 7, "low": 0, "info": 0}
        )
        self.assertEqual(sum(p["n"] for p in page["timeline"]), 7)
        self.assertEqual((page["counted_total"], page["activity_total"]), (7, 0))
        self.assertEqual(page["first_seen"], "2026-11-05T09:00:00.000Z")
        self.assertEqual(page["last_seen"], "2026-11-05T11:00:00.000Z")
        self.assertFalse(page["activity"])

    async def test_each_address_row_equals_its_ip_list(self):
        # one address per exact-count search, so every row's figures come from its own batch
        with patch.object(suricata_rule, "EXACT_BATCH", 1):
            page = await self.page(DROP)
        devices = {r["ip"]: r for r in page["devices"]["rows"]}
        # d4 is L1 at both ends: one alert in the list, once as source and once as target
        self.assertEqual(
            devices[L1],
            {
                "ip": L1,
                "as_source": 1,
                "as_target": 4,
                "alerts": 4,
                "first_seen": "2026-11-05T09:00:00.000Z",
                "last_seen": "2026-11-05T11:00:00.000Z",
            },
        )
        self.assertEqual((devices[L2]["as_target"], devices[L2]["alerts"]), (1, 1))
        self.assertEqual([r["ip"] for r in page["remotes"]["rows"]], [R1, R2])
        self.assertEqual(page["remotes"]["rows"][0]["as_source"], 3)
        self.assertEqual([r["ip"] for r in page["unplaced"]["rows"]], [V6])
        for group in ("devices", "remotes", "unplaced"):
            self.assertTrue(page[group]["complete"])
            # OLD CODE: self.assertEqual(page[group]["picked_by"], "source_plus_destination") (the field went)
            for row in page[group]["rows"]:
                total, _ = await self.listed(page, signature=DROP, ip=row["ip"])
                self.assertEqual(total, row["alerts"], (group, row["ip"]))
        self.assertEqual(
            [page[g]["distinct"] for g in ("devices", "remotes", "unplaced")], [2, 2, 1]
        )
        self.assertEqual(page["missing_address"], 1)

    async def test_a_capped_discovery_misses_addresses_never_shortens_a_row(self):
        with (
            patch.object(snapshot_search, "GROUP_PAGE", 1),
            patch.object(suricata_rule, "LIST_CAP", 1),
        ):
            page = await self.page(DROP)
        for group in ("devices", "remotes", "unplaced"):
            self.assertFalse(page[group]["complete"])
            self.assertIsNone(page[group]["distinct"])
            for row in page[group]["rows"]:
                total, _ = await self.listed(page, signature=DROP, ip=row["ip"])
                self.assertEqual(total, row["alerts"], (group, row["ip"]))
                self.assertEqual(
                    (row["as_source"], row["as_target"]),
                    (
                        (await self.listed(page, signature=DROP, src=row["ip"]))[0],
                        (await self.listed(page, signature=DROP, dst=row["ip"]))[0],
                    ),
                )

    async def test_the_shown_rows_are_a_bounded_selection_by_source_plus_destination(
        self,
    ):
        with patch.dict(suricata_rule.SHOWN, {"devices": 1}):
            page = await self.page(CUTOFF)
        devices = page["devices"]
        # L1's 3 self-alerts weigh 6 against L2's 5 ordinary ones: the documented pick, not the busiest
        self.assertEqual([(r["ip"], r["alerts"]) for r in devices["rows"]], [(L1, 3)])
        # OLD CODE: …((devices["distinct"], devices["picked_by"]), (2, "source_plus_destination")) (the field went)
        self.assertEqual(devices["distinct"], 2)
        self.assertEqual((await self.listed(page, signature=CUTOFF, ip=L1))[0], 3)

    async def test_the_counted_and_activity_lists(self):
        counted = await self.page(STUN)
        self.assertEqual(
            (counted["total"], counted["counted_total"], counted["activity_total"]),
            (0, 0, 2),
        )
        activity = await self.page(STUN, f"{WINDOW}&activity=true")
        self.assertTrue(activity["activity"])
        self.assertEqual(activity["total"], 2)
        self.assertEqual(
            await self.listed(activity, signature=STUN, activity="true"),
            (2, ["a1", "a2"]),
        )
        split = await self.page(SPLIT)
        self.assertEqual((split["counted_total"], split["activity_total"]), (1, 1))
        self.assertEqual(await self.listed(split, signature=SPLIT), (1, ["s1"]))


class TestRuleFacts(RuleCase):
    async def test_two_sids_keep_their_own_facts(self):
        page = await self.page(SHARED)
        rules = {r["sid"]: r for r in page["rules"]}
        self.assertEqual(list(rules), ["2000002", "2000001"])  # most alerts first
        one, two = rules["2000001"], rules["2000002"]
        self.assertEqual(
            one["techniques"],
            [{"id": "T1190", "name": "Exploit Public-Facing Application"}],
        )
        self.assertEqual(
            (one["cves"], one["cisa_kev"], one["et_ratings"]),
            (["CVE-2021-41773"], True, ["Major"]),
        )
        self.assertEqual(one["categories"], ["Attempted Administrator Privilege Gain"])
        # the newest x2/x3 alert is x3, which carries no metadata: nothing is borrowed from x2 or x1
        self.assertEqual(
            (two["techniques"], two["cves"], two["cisa_kev"]), ([], [], False)
        )
        self.assertEqual(two["alerts"], 2)
        self.assertTrue(page["rules_complete"])
        # the page explains the name, not either SID
        self.assertEqual(page["explanation"]["family"], "exploit")
        self.assertEqual(page["explanation"], rx.explain_name(SHARED, 1))
        self.assertNotIn(
            "https://nvd.nist.gov/vuln/detail/CVE-2021-41773",
            [link["url"] for link in page["learn_more"]],
        )
        self.assertIn(
            "https://nvd.nist.gov/vuln/detail/CVE-2021-41773",
            [link["url"] for link in one["learn_more"]],
        )

    async def test_invalid_ids_are_dropped(self):
        self.os.docs = [d for d in DOCS if d["_id"] != "x3"]
        page = await self.page(SHARED)
        two = next(r for r in page["rules"] if r["sid"] == "2000002")
        # ids and names no longer line up once X1 is dropped, so names are not guessed
        self.assertEqual(two["techniques"], [{"id": "T1083", "name": None}])
        self.assertEqual(two["cves"], [])

    async def test_names_pair_with_their_ids_before_bad_ids_go(self):
        self.os.docs = [
            *DOCS,
            _alert(
                "p1",
                L1,
                R1,
                "ET INFO paired names",
                2000050,
                threat__technique__id=["X1", "T1071", "", "T1572"],
                threat__technique__name=[
                    "Bad",
                    "Application Layer Protocol",
                    "Blank",
                    "Protocol Tunneling",
                ],
            ),
        ]
        page = await self.page("ET INFO paired names")
        self.assertEqual(
            page["rules"][0]["techniques"],
            [
                {"id": "T1071", "name": "Application Layer Protocol"},
                {"id": "T1572", "name": "Protocol Tunneling"},
            ],
        )

    async def test_a_curated_text_filed_under_another_rule_is_not_used(self):
        # data/suricata_descriptions.json files Bitcoin mining under 2016149, which is STUN
        page = await self.page(STUN, f"{WINDOW}&activity=true")
        self.assertEqual(page["rules"][0]["sid"], "2016149")
        self.assertIsNone(page["rules"][0]["advice"])
        self.assertEqual(page["explanation"], rx.explain_name(STUN, 3))
        self.assertNotIn("mining", str(page).lower())

    async def test_one_credential_sid_explains_the_page_as_a_credential(self):
        name = "ET POLICY Outgoing Basic Auth Base64 HTTP Password detected unencrypted (one)"
        self.os.docs = [
            *DOCS,
            _alert("c9", L1, R1, name, 2006399, et=["Informational"]),
        ]
        # NetTap counts a secret in the clear, whatever ET's rating
        page = await self.page(name)
        self.assertEqual([r["credential"] for r in page["rules"]], [True])
        # the name alone says "policy"; the one SID's credential advice says what it is
        self.assertEqual(rx.explain_name(name, 2)["family"], "policy")
        self.assertEqual(page["explanation"], rx.credential_advice())

    async def test_a_repeated_attack_id_is_listed_once(self):
        # two techniques under one tactic: Malcolm repeats the tactic, and the page keys on the id
        self.os.docs = [
            *DOCS,
            _alert(
                "t1",
                L1,
                R1,
                "ET INFO two techniques",
                2000040,
                threat__technique__id=["T1071", "T1572"],
                threat__technique__name=[
                    "Application Layer Protocol",
                    "Protocol Tunneling",
                ],
                threat__tactic__id=["TA0011", "TA0011"],
                threat__tactic__name=["Command and Control", "Command and Control"],
            ),
        ]
        page = await self.page("ET INFO two techniques")
        rule = page["rules"][0]
        self.assertEqual(
            rule["tactics"], [{"id": "TA0011", "name": "Command and Control"}]
        )
        self.assertEqual([t["id"] for t in rule["techniques"]], ["T1071", "T1572"])

    async def test_one_curated_sid_explains_the_page(self):
        page = await self.page(EMOTET)
        self.assertEqual(page["rules"][0]["sid"], "2024792")
        advice = page["rules"][0]["advice"]
        self.assertIn("Emotet", advice["what"])
        self.assertEqual(page["explanation"], {"family": "malware", **advice})

    async def test_credential_advice_follows_each_sids_et_ratings(self):
        counted = await self.page(CRED)
        rules = {r["sid"]: r["credential"] for r in counted["rules"]}
        self.assertEqual(rules, {"2006380": True, "2006381": False})
        self.assertEqual(
            counted["explanation"]["family"], "policy"
        )  # the SIDs disagree
        activity = await self.page(CRED, f"{WINDOW}&activity=true")
        self.assertEqual(
            [(r["sid"], r["credential"]) for r in activity["rules"]],
            [("2006382", False)],
        )
        every = await self.page(CRED_ALL)
        self.assertTrue(all(r["credential"] for r in every["rules"]))
        self.assertEqual(every["explanation"], rx.credential_advice())

    async def test_agreement_needs_every_sid(self):
        page = await self.page(CRED_MANY)
        self.assertEqual(len(page["rules"]), 10)
        self.assertTrue(all(r["credential"] for r in page["rules"]))
        self.assertFalse(page["rules_complete"])  # the Major SID was left out
        self.assertEqual(page["explanation"]["family"], "info")

    async def test_an_own_rule_and_alerts_without_a_sid(self):
        own = await self.page(OWN)
        self.assertEqual(own["explanation"], rx.own_rule())
        self.os.docs = [*DOCS, _alert("o2", L1, R1, OWN)]
        mixed = await self.page(OWN)
        self.assertEqual(mixed["no_sid"], 1)
        self.assertEqual(
            mixed["explanation"]["family"], "unknown"
        )  # one SID no longer speaks for all

    async def test_a_dbl_rule_links_its_list(self):
        self.os.docs = [
            *DOCS,
            _alert(
                "b1",
                L2,
                R1,
                "IPFire DBL [Phishing] Blocked DNS Query",
                12001200,
                sev=1,
                suricata__alert__metadata__dbl=["phishing.dbl.ipfire.org"],
            ),
        ]
        page = await self.page("IPFire DBL [Phishing] Blocked DNS Query")
        self.assertEqual(page["rules"][0]["dbl_lists"], ["phishing"])
        self.assertEqual(
            page["learn_more"][0]["url"], "https://www.ipfire.org/dbl/lists/phishing"
        )
        self.assertIn("did not block it", page["explanation"]["risk"])


class TestRequests(RuleCase):
    async def test_a_name_with_a_slash_ampersand_and_percent(self):
        page = await self.page(ODD)
        self.assertEqual((page["name"], page["total"]), (ODD, 1))
        self.assertEqual(await self.listed(page, signature=ODD), (1, ["z1"]))
        # the "/" sent encoded and as is
        for path in (_path(ODD), "/api/alerts/rule/ET%20INFO%20A/B%20%26%20C%2050%25"):
            resp = await self.client.get(f"{path}?{WINDOW}", headers=AUTH)
            self.assertEqual(resp.status, 200, path)
            self.assertEqual((await resp.json())["name"], ODD, path)

    async def test_bad_requests_are_400s_before_any_search(self):
        for name in ("   ", "x" * 1025):
            body = await self.page(name, status=400)
            self.assertEqual(body, {"error": "That isn't a rule name."})
        body = await self.page(DROP, f"{WINDOW}&activity=maybe", status=400)
        self.assertEqual(body, {"error": "activity must be true or false"})
        await self.page(
            DROP, "from=1970-01-01T00:00:00Z&to=2026-11-05T00:00:00Z", status=400
        )
        self.assertEqual(self.os.bodies, [])

    async def test_the_route_needs_the_token(self):
        self.assertEqual((await self.client.get(_path(DROP))).status, 401)

    async def test_severity_tiles_that_dont_add_up_fail_the_page(self):
        self.os.docs = [*DOCS, _alert("y", L1, R1, DROP, 2402000, sev=[1, 2])]
        body = await self.page(DROP, status=502)
        self.assertIn("don't add up", body["error"])


class TestRouteTable(AioHTTPTestCase):
    """The daemon's own router: the rule page and the alert routes beside it keep theirs."""

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
        page = "handle_suricata_rule"
        cases = [
            ("/api/alerts/rule/ET%20INFO%20x", page, {"name": "ET INFO x"}),
            ("/api/alerts/rule/a/b", page, {"name": "a/b"}),
            ("/api/alerts/rule/a%2Fb", page, {"name": "a/b"}),
            ("/api/alerts/rule/acknowledge", page, {"name": "acknowledge"}),
            (
                "/api/alerts/suricata/Misc%20activity",
                "handle_suricata_category",
                {"name": "Misc activity"},
            ),
            ("/api/alerts/rule", "handle_alert_detail", {"id": "rule"}),
        ]
        for path, handler, info in cases:
            self.assertEqual(await self._resolve(path), (handler, info), path)


def test_valid_rule_name():
    assert valid_rule_name("ET INFO x") == "ET INFO x"
    assert (
        valid_rule_name(" padded ") == " padded "
    )  # exactly as given, as the list matches it
    assert [valid_rule_name(v) for v in ("", "  ", "x" * 1025, None, 5)] == [None] * 5
    assert valid_rule_name("x" * 1024) == "x" * 1024
