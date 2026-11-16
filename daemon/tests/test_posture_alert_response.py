"""NET-308: GET /api/posture/alert-response, the Alert response score's input.

The high-severity rules among the counted alerts (top-signatures' own exact scan), and which of
them an investigation open during the window links an alert of, read from the rule stored at
link time. The evaluator fake runs the real queries over one set of documents.
"""

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase
from opensearchpy import OpenSearchException

from api.alerts import ET_ACTIVITY_CLAUSE, alert_query
from api.investigations import register_investigation_routes
from api.posture import register_posture_routes
from services.investigation_store import InvestigationStore
from storage.exact_terms import PartialResultsError
from storage.snapshot_search import QueryFailed
from tests.fake_drill_opensearch import AUTH, FROM, TO, DrillOpenSearch, alert

DEVICE, B = "192.168.1.20", "93.184.216.34"
EARLY = "2026-11-01T00:00:00+00:00"


def _alert(doc_id, rule, severity=1, **fields):
    doc = alert(
        DEVICE, B, rule=rule, _id=doc_id, suricata__alert__severity=severity, **fields
    )
    return {k: v for k, v in doc.items() if v is not None}  # None: no rule.name at all


DOCS = [
    *(_alert(f"n{i}", "ET SCAN Nmap") for i in range(3)),
    *(_alert(f"t{i}", "ET POLICY Telnet") for i in range(2)),
    _alert("u1", None),
    _alert("e1", ""),
    *(_alert(f"m{i}", "ET INFO Medium", severity=2) for i in range(4)),
    # mostly medium, so its primary severity is 2: not scored here
    *(_alert(f"x{i}", "ET MIXED", severity=s) for i, s in enumerate((2, 2, 1))),
    # ET rates it informational: activity, never counted
    _alert(
        "i1",
        "ET INFO Session",
        suricata__alert__metadata__signature_severity="Informational",
    ),
    _alert("s1", "SURICATA STREAM bad"),  # an engine event
]


class AlertResponseTestCase(AioHTTPTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = InvestigationStore(os.path.join(self.dir.name, "inv.json"))
        self.os = DrillOpenSearch(DOCS)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.dir.cleanup()

    async def get_application(self):
        from tests.fake_drill_opensearch import make_app

        def register(app, client):
            app["storage"] = SimpleNamespace(_client=client)
            register_posture_routes(app)
            register_investigation_routes(app, self.store)

        return make_app(self.os, register)

    def investigation(self, rules=None, ids=None, status="open", updated=EARLY):
        inv = self.store.create(
            title="x", alert_ids=ids if ids is not None else list(rules or {})
        )
        inv.alert_rules = dict(rules or {})
        inv.status, inv.created_at, inv.updated_at = status, EARLY, updated
        return inv

    async def get(self, **params):
        resp = await self.client.get(
            "/api/posture/alert-response",
            params={"from": FROM, "to": TO, **params},
            headers=AUTH,
        )
        return resp.status, await resp.json()


class TestAlertResponse(AlertResponseTestCase):
    async def test_the_groups_and_their_coverage(self):
        # open, and its alert has since expired: the stored rule still covers Nmap
        self.investigation({"gone": "ET SCAN Nmap"})
        # closed before the window: covers nothing
        self.investigation({"t0": "ET POLICY Telnet"}, status="closed", updated=EARLY)
        self.investigation({"y": "ET OTHER"})  # another rule marks no group
        self.investigation({"u1": None})  # no rule name: only its own group, never ""
        self.investigation(ids=["old1"])  # linked before NET-308: unresolved
        self.investigation(ids=[1, "a"])  # malformed: skipped
        status, data = await self.get()
        self.assertEqual(status, 200, data)
        self.assertEqual(
            (data["category"], data["from"], data["to"]), ("alert-response", FROM, TO)
        )
        self.assertEqual((data["needing"], data["investigated"]), (4, 2))
        # the ones without an investigation first, then the busiest
        self.assertEqual(
            data["groups"],
            [
                {"rule": "ET POLICY Telnet", "count": 2, "investigated": False},
                {"rule": "", "count": 1, "investigated": False},
                {"rule": "ET SCAN Nmap", "count": 3, "investigated": True},
                {"rule": None, "count": 1, "investigated": True},
            ],
        )
        self.assertEqual(
            data["investigations"],
            {"open_during": 5, "linked_alerts": 4, "unresolved_links": 1, "skipped": 1},
        )

    async def test_only_the_counted_alerts_are_read_and_no_link_is_looked_up(self):
        status, _ = await self.get()
        self.assertEqual(status, 200)
        queries = [b["query"] for b in self.os.bodies if "query" in b]
        self.assertTrue(queries)
        for query in queries:
            self.assertEqual(query, alert_query(FROM, TO))
            self.assertIn(ET_ACTIVITY_CLAUSE, query["bool"]["must_not"])
            self.assertNotIn("ids", str(query))

    async def test_nothing_high_gives_an_empty_list(self):
        self.os.docs = [d for d in DOCS if d["_id"].startswith("m")]
        status, data = await self.get()
        self.assertEqual(status, 200)
        self.assertEqual(
            (data["needing"], data["investigated"], data["groups"]), (0, 0, [])
        )

    async def test_an_incomplete_scan_is_a_502(self):
        with patch("api.posture._every_key", return_value=([], False)):
            status, data = await self.get()
        self.assertEqual(status, 502)
        self.assertEqual(data, {"error": "The alert search was incomplete"})

    async def test_each_search_failure_is_a_502_with_fixed_text(self):
        for exc, error in (
            (OpenSearchException("secret detail"), "The alert search failed"),
            (QueryFailed("timed out"), "The alert search was incomplete"),
            (PartialResultsError("capped"), "The alert search was incomplete"),
        ):
            with patch("api.posture._every_key", side_effect=exc):
                status, data = await self.get()
            self.assertEqual((status, data), (502, {"error": error}), type(exc))

    async def test_an_unreadable_from_is_a_400(self):
        status, _ = await self.get(**{"from": "now-1d"})
        self.assertEqual(status, 400)
        self.assertEqual(self.os.bodies, [])

    async def test_a_relinked_alert_counts_and_leaves_the_unresolved_count(self):
        inv = self.investigation(ids=["n1"])  # unresolved
        _, before = await self.get()
        self.assertEqual(before["investigations"]["unresolved_links"], 1)
        resp = await self.client.post(
            f"/api/investigations/{inv.id}/alerts",
            json={"alert_id": "n1"},
            headers=AUTH,
        )
        self.assertEqual(resp.status, 200, await resp.text())
        _, after = await self.get()
        self.assertEqual(after["investigations"]["unresolved_links"], 0)
        nmap = next(g for g in after["groups"] if g["rule"] == "ET SCAN Nmap")
        self.assertTrue(nmap["investigated"])
