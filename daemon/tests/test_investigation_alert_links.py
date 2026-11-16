"""NET-308: linking an alert to an investigation records the alert's rule, read by the daemon.

POST /api/investigations (alert_ids) and POST /api/investigations/{id}/alerts look each alert
up once, among the Suricata alerts, and store its rule.name in alert_ids' companion map
alert_rules, so Alert response coverage survives the alert's index expiring. The evaluator
fake runs the real lookup over a set of documents.
"""

import asyncio
import os
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase
from opensearchpy import OpenSearchException

from api.alerts import _SURICATA_ALERT_FILTERS
from api.investigations import (
    MAX_ALERT_LINKS,
    RESOLVE_TIMEOUT_S,
    _alert_ids,
    register_investigation_routes,
)
from services.investigation_store import InvestigationStore
from tests.fake_drill_opensearch import DrillOpenSearch, alert, conn

DEVICE, B = "192.168.1.20", "93.184.216.34"


def _alert(doc_id: str, rule: str | None) -> dict:
    doc = alert(DEVICE, B, rule=rule, _id=doc_id)
    return {k: v for k, v in doc.items() if v is not None}  # None: no rule.name at all


DOCS = [
    _alert("a1", "ET SCAN Nmap"),
    _alert("a2", None),
    _alert("a3", ""),
    _alert("a4", "ET POLICY Telnet"),
    _alert("a5", ["ET MULTI first", "ET MULTI second"]),  # a multi-valued rule.name
    {**conn(DEVICE, B), "_id": "c1"},  # a conn record is not an alert
]


class LinkTestCase(AioHTTPTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = InvestigationStore(os.path.join(self.dir.name, "inv.json"))
        self.os = DrillOpenSearch(DOCS)
        self.search = MagicMock(wraps=self.os.search)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.dir.cleanup()

    async def get_application(self):
        app = web.Application()
        app["storage"] = SimpleNamespace(_client=SimpleNamespace(search=self.search))
        register_investigation_routes(app, self.store)
        return app

    async def post(self, path: str, body) -> tuple[int, dict]:
        resp = await self.client.post(path, json=body)
        return resp.status, await resp.json()


class TestCreateWithAlerts(LinkTestCase):
    async def test_the_rules_are_read_once_and_stored(self):
        status, data = await self.post(
            "/api/investigations",
            {"title": "Scan", "alert_ids": ["a1", "a2", "a3", "a1"]},
        )
        self.assertEqual(status, 201, data)
        self.assertEqual(data["alert_ids"], ["a1", "a2", "a3"])
        # no rule name and an empty one are two different groups, as on the Alerts list
        self.assertEqual(
            data["alert_rules"], {"a1": "ET SCAN Nmap", "a2": None, "a3": ""}
        )
        self.search.assert_called_once()
        kwargs = self.search.call_args.kwargs
        self.assertEqual(kwargs["request_timeout"], RESOLVE_TIMEOUT_S)
        self.assertEqual(
            kwargs["body"]["query"]["bool"]["filter"],
            [{"ids": {"values": ["a1", "a2", "a3"]}}, *_SURICATA_ALERT_FILTERS],
        )
        self.assertEqual(kwargs["body"]["_source"], ["rule.name"])
        self.assertEqual(kwargs["body"]["size"], 3)

    async def test_an_id_that_isnt_an_alert_is_a_400_and_nothing_is_stored(self):
        for ids in (["a1", "nope"], ["c1"]):
            status, data = await self.post(
                "/api/investigations", {"title": "x", "alert_ids": ids}
            )
            self.assertEqual(status, 400)
            self.assertEqual(data, {"error": "An alert to link wasn't found"})
        self.assertEqual(self.store.list_all(), [])

    async def test_an_opensearch_error_is_a_502_and_nothing_is_stored(self):
        self.search.side_effect = OpenSearchException("secret detail")
        status, data = await self.post(
            "/api/investigations", {"title": "x", "alert_ids": ["a1"]}
        )
        self.assertEqual(status, 502)
        self.assertEqual(data, {"error": "The alert lookup failed"})
        self.assertEqual(self.store.list_all(), [])

    async def test_failed_shards_are_a_502(self):
        self.search.side_effect = lambda **kw: {
            **self.os.search(**kw),
            "_shards": {"total": 2, "failed": 1},
        }
        status, _ = await self.post(
            "/api/investigations", {"title": "x", "alert_ids": ["a1"]}
        )
        self.assertEqual(status, 502)
        self.assertEqual(self.store.list_all(), [])

    async def test_malformed_alert_ids_are_a_400_without_a_lookup(self):
        for bad in (
            "a1",
            {"a": 1},
            [{}],
            ["a1", 1],
            [""],
            ["   "],
            [f"id{i}" for i in range(MAX_ALERT_LINKS + 1)],
            ["x" * 257],
        ):
            status, _ = await self.post(
                "/api/investigations", {"title": "x", "alert_ids": bad}
            )
            self.assertEqual(status, 400, bad)
        self.search.assert_not_called()
        self.assertEqual(self.store.list_all(), [])

    async def test_a_multi_valued_rule_name_keeps_its_first_name(self):
        status, data = await self.post(
            "/api/investigations", {"title": "x", "alert_ids": ["a5"]}
        )
        self.assertEqual(status, 201, data)
        self.assertEqual(data["alert_rules"], {"a5": "ET MULTI first"})

    def test_the_cap_is_checked_before_any_entry_is_read(self):
        """Security review LOW-3: a 16 MiB list was read entry by entry before the cap."""
        with patch("api.investigations._alert_id") as each:
            self.assertIsNone(_alert_ids(["a1"] * (MAX_ALERT_LINKS + 1)))
        each.assert_not_called()
        self.assertEqual(_alert_ids(["a1"] * MAX_ALERT_LINKS), ["a1"])

    async def test_without_alerts_opensearch_is_never_asked(self):
        """R2-1: the Investigations form sends no alert_ids; it must work with OpenSearch down."""
        self.search.side_effect = OpenSearchException("down")
        for body in (
            {"title": "x"},
            {"title": "x", "alert_ids": None},
            {"title": "x", "alert_ids": []},
        ):
            status, data = await self.post("/api/investigations", body)
            self.assertEqual(status, 201, body)
            self.assertEqual((data["alert_ids"], data["alert_rules"]), ([], {}))
        self.search.assert_not_called()


class TestLinkAlert(LinkTestCase):
    def setUp(self):
        super().setUp()
        self.inv = self.store.create(title="Case")
        self.path = f"/api/investigations/{self.inv.id}/alerts"

    async def test_the_link_records_the_rule(self):
        status, data = await self.post(self.path, {"alert_id": "a4"})
        self.assertEqual((status, data), (200, {"result": "linked", "alert_id": "a4"}))
        self.assertEqual(
            self.store.get(self.inv.id).alert_rules, {"a4": "ET POLICY Telnet"}
        )
        self.assertEqual(
            self.search.call_args.kwargs["request_timeout"], RESOLVE_TIMEOUT_S
        )

    async def test_an_unknown_alert_is_a_404_and_links_nothing(self):
        status, data = await self.post(self.path, {"alert_id": "nope"})
        self.assertEqual((status, data), (404, {"error": "Alert not found"}))
        self.assertEqual(self.store.get(self.inv.id).alert_ids, [])

    async def test_an_opensearch_error_is_a_502_and_links_nothing(self):
        self.search.side_effect = OpenSearchException("secret detail")
        status, data = await self.post(self.path, {"alert_id": "a1"})
        self.assertEqual((status, data), (502, {"error": "The alert lookup failed"}))
        self.assertEqual(self.store.get(self.inv.id).alert_ids, [])

    async def test_a_malformed_alert_id_is_a_400_not_a_500(self):
        for bad in (1, None, "", "  ", "x" * 257, ["a1"], {"id": "a1"}):
            status, _ = await self.post(self.path, {"alert_id": bad})
            self.assertEqual(status, 400, bad)
        self.search.assert_not_called()

    async def test_an_unknown_investigation_is_a_404_without_a_lookup(self):
        status, _ = await self.post(
            "/api/investigations/nope/alerts", {"alert_id": "a1"}
        )
        self.assertEqual(status, 404)
        self.search.assert_not_called()

    async def test_the_101st_link_is_a_400_but_a_relink_is_not_capped(self):
        ids = ["a1", *(f"old{i}" for i in range(MAX_ALERT_LINKS - 1))]
        inv = self.store.create(title="Full", alert_ids=ids)
        path = f"/api/investigations/{inv.id}/alerts"
        status, _ = await self.post(path, {"alert_id": "a4"})
        self.assertEqual(status, 400)
        status, _ = await self.post(path, {"alert_id": "a1"})  # already linked
        self.assertEqual(status, 200)
        self.assertEqual(len(self.store.get(inv.id).alert_ids), MAX_ALERT_LINKS)

    async def test_two_links_at_once_cant_both_pass_the_cap(self):
        """NET-308 review: one slot left and two links in flight; the store checks as it adds."""
        inv = self.store.create(
            title="Nearly full",
            alert_ids=[f"old{i}" for i in range(MAX_ALERT_LINKS - 1)],
        )
        path = f"/api/investigations/{inv.id}/alerts"
        results = await asyncio.gather(
            self.post(path, {"alert_id": "a1"}), self.post(path, {"alert_id": "a4"})
        )
        self.assertEqual(sorted(status for status, _ in results), [200, 400])
        refused = next(data for status, data in results if status == 400)
        self.assertEqual(
            refused, {"error": "An investigation links at most 100 alerts"}
        )
        self.assertEqual(len(self.store.get(inv.id).alert_ids), MAX_ALERT_LINKS)

    async def test_relinking_a_resolved_alert_needs_no_lookup(self):
        """Its index may have expired: the stored rule answers, not a 404."""
        inv = self.store.create(
            title="Old", alert_ids=["gone"], alert_rules={"gone": "ET SCAN Nmap"}
        )
        status, data = await self.post(
            f"/api/investigations/{inv.id}/alerts", {"alert_id": "gone"}
        )
        self.assertEqual(
            (status, data), (200, {"result": "linked", "alert_id": "gone"})
        )
        self.search.assert_not_called()

    async def test_relinking_an_unresolved_link_fills_its_rule_once(self):
        """A link made before NET-308 has no rule; linking it again resolves it, no duplicate."""
        inv = self.store.create(title="Old", alert_ids=["a1"])
        self.assertEqual(inv.alert_rules, {})
        status, _ = await self.post(
            f"/api/investigations/{inv.id}/alerts", {"alert_id": "a1"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.store.get(inv.id).alert_ids, ["a1"])
        self.assertEqual(self.store.get(inv.id).alert_rules, {"a1": "ET SCAN Nmap"})

    async def test_unlink_removes_the_rule(self):
        await self.post(self.path, {"alert_id": "a1"})
        resp = await self.client.delete(f"{self.path}/a1")
        self.assertEqual(resp.status, 200)
        inv = self.store.get(self.inv.id)
        self.assertEqual((inv.alert_ids, inv.alert_rules), ([], {}))
