"""NET-185: a rule named "Unknown" and alerts with no rule name are two rows, each listed exactly.

The category's Top signatures merged them into one "Unknown" bar, so neither bar could open a
list holding its figure. The evaluator fake runs the real queries over one set of documents.
"""

from aiohttp.test_utils import AioHTTPTestCase

from api.alerts import _signature_filter
from tests.fake_drill_opensearch import AUTH, FROM, TO, DrillOpenSearch, alert, make_app
from tests.test_drill_exact_lists import _register

DEVICE, B = "192.168.1.20", "93.184.216.34"


def _alert(doc_id: str, rule: str | None) -> dict:
    doc = alert(DEVICE, B, rule=rule, _id=doc_id)
    return {k: v for k, v in doc.items() if v is not None}  # None: no rule.name at all


DOCS = [
    _alert("u1", "Unknown"),
    _alert("u2", "Unknown"),
    _alert("n1", None),
    _alert("n2", None),
    _alert("n3", None),
]


def test_the_filter_matches_each_case_exactly():
    missing = {"bool": {"must_not": {"exists": {"field": "rule.name"}}}}
    assert _signature_filter(["Unknown"]) == {
        "bool": {"should": [{"terms": {"rule.name": ["Unknown"]}}], "minimum_should_match": 1}
    }
    assert _signature_filter([None]) == {
        "bool": {"should": [{"terms": {"rule.name": []}}, missing], "minimum_should_match": 1}
    }
    assert _signature_filter(["b", None, "a"])["bool"]["should"][0] == {
        "terms": {"rule.name": ["a", "b"]}
    }


class TestUnknownAndNoRuleName(AioHTTPTestCase):
    async def get_application(self):
        return make_app(DrillOpenSearch(DOCS), _register)

    async def get(self, path, **params):
        resp = await self.client.get(path, params={"from": FROM, "to": TO, **params}, headers=AUTH)
        return resp.status, await resp.json()

    async def test_the_category_shows_two_rows_and_each_lists_its_figure(self):
        status, detail = await self.get("/api/alerts/categories/informational")
        self.assertEqual(status, 200, detail)
        rows = {s["signature"]: s["count"] for s in detail["top_signatures"]}
        self.assertEqual(rows, {"Unknown": 2, None: 3})
        self.assertEqual(detail["stats"]["total"], 5)
        # the links the bars carry, over the response's own window
        status, named = await self.get(
            "/api/alerts", signature="Unknown", **{"from": detail["from"], "to": detail["to"]}
        )
        self.assertEqual((status, named["total"]), (200, 2))
        status, unnamed = await self.get(
            "/api/alerts", no_rule_name="true", **{"from": detail["from"], "to": detail["to"]}
        )
        self.assertEqual((status, unnamed["total"]), (200, 3))
        self.assertEqual(sorted(a["_id"] for a in unnamed["alerts"]), ["n1", "n2", "n3"])

    async def test_the_category_list_still_holds_both(self):
        status, body = await self.get("/api/alerts", category="informational")
        self.assertEqual((status, body["total"]), (200, 5))

    async def test_anything_but_true_or_false_is_a_400(self):
        for value in ("maybe", ""):
            status, body = await self.get("/api/alerts", no_rule_name=value)
            self.assertEqual(status, 400, (value, body))
        status, body = await self.get("/api/alerts", no_rule_name="false")
        self.assertEqual((status, body["total"]), (200, 5))
