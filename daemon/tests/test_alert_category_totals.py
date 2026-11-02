"""#96: alert category figures count every signature and every IP, not a top list.

The fake below answers the old (terms, capped like OpenSearch) and the new (composite, paged)
query shapes from one list of alert docs, so each test fails on the capped code.
"""

import asyncio
import json
import os
import sys
from collections import Counter
from unittest.mock import MagicMock

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.alerts import (  # noqa: E402
    handle_alert_category_detail,
    handle_alert_category_timeline,
    handle_alerts_categories,
)

_HOUR = "2026-11-01T10:00:00.000Z"


def _doc(sig: str, src: str = "203.0.113.1", dst: str = "192.168.1.10", sev: int = 2) -> dict:
    return {"sig": sig, "src": src, "dst": dst, "sev": sev}


def _top(counter: Counter, size: int) -> list[dict]:
    return [{"key": k, "doc_count": c} for k, c in counter.most_common(size)]


def _sig_aggs(docs: list[dict], aggs: dict) -> dict:
    """The per-signature sub-aggregations the category handlers ask for."""
    out: dict = {"doc_count": len(docs)}
    if "by_severity" in aggs:
        out["by_severity"] = {"buckets": _top(Counter(d["sev"] for d in docs), 5)}
    if "over_time" in aggs:
        out["over_time"] = {"buckets": [{"key_as_string": _HOUR, "doc_count": len(docs)}]}
    for name, field in (("by_src_ip", "src"), ("by_dst_ip", "dst")):
        if name in aggs:
            size = aggs[name]["terms"]["size"]
            out[name] = {"buckets": _top(Counter(d[field] for d in docs), size)}
    if "latest" in aggs:
        out["latest"] = {"value_as_string": _HOUR}
    return out


def _names(signature_filter: dict) -> set[str]:
    return set(signature_filter["bool"]["should"][0]["terms"]["rule.name"])


def _composite_page(keys: list, comp: dict, bucket) -> dict:
    after = comp.get("after")
    start = 0 if after is None else keys.index(next(iter(after.values()))) + 1
    page = keys[start : start + comp["size"]]
    name = next(iter(comp["sources"][0]))
    reply: dict = {"buckets": [{"key": {name: k}, **bucket(k)} for k in page]}
    if page:
        reply["after_key"] = {name: page[-1]}
    return {"aggregations": {"all": reply}}


def _timeline(docs: list[dict], body: dict) -> dict:
    over_time = body["aggs"]["over_time"]
    sub_aggs = over_time.get("aggs", {})
    if "by_signature" in sub_aggs:  # old shape: top signatures per time bucket
        size = sub_aggs["by_signature"]["terms"]["size"]
        sigs = _top(Counter(d["sig"] for d in docs), size)
        bucket = {"key_as_string": _HOUR, "doc_count": len(docs), "by_signature": {"buckets": sigs}}
        return {"aggregations": {"over_time": {"buckets": [bucket]}}}
    names = _names(body["query"]["bool"]["filter"][1])
    mine = [d for d in docs if d["sig"] in names]
    bucket: dict = {"key_as_string": _HOUR, "doc_count": len(mine)}
    if "by_sub" in sub_aggs:
        per_sub = sub_aggs["by_sub"]["filters"]["filters"]
        bucket["by_sub"] = {
            "buckets": {s: {"doc_count": sum(d["sig"] in _names(f) for d in mine)} for s, f in per_sub.items()}
        }
    return {"aggregations": {"over_time": {"buckets": [bucket]}}}


def _fake_client(docs: list[dict]) -> MagicMock:
    def search(index, body):
        aggs = body["aggs"]
        if "by_signature" in aggs:  # old shape: a capped terms list
            terms = aggs["by_signature"]
            top = Counter(d["sig"] for d in docs).most_common(terms["terms"]["size"])
            buckets = [
                {"key": n, **_sig_aggs([d for d in docs if d["sig"] == n], terms.get("aggs", {}))}
                for n, _ in top
            ]
            return {"aggregations": {"by_signature": {"buckets": buckets}}}
        if "over_time" in aggs:
            return _timeline(docs, body)
        comp = aggs["all"]["composite"]
        sub = aggs["all"].get("aggs") or {}
        if "sig" in comp["sources"][0]:
            keys = sorted({d["sig"] for d in docs})
            return _composite_page(keys, comp, lambda k: _sig_aggs([d for d in docs if d["sig"] == k], sub))
        raise AssertionError(f"unexpected query {json.dumps(body)[:200]}")

    client = MagicMock()
    client.search.side_effect = search
    return client


def _get(handler, client, path: str, category: str | None = None) -> dict:
    app = web.Application()
    app["storage"] = MagicMock(_client=client)
    match_info = {"category": category} if category else {}
    req = make_mocked_request("GET", path, app=app, match_info=match_info)
    resp = asyncio.run(handler(req))
    assert resp.status == 200, resp.text
    return json.loads(resp.text)


# 600 scan signatures firing once each, behind one busy trojan: past a 500-signature list
_MANY_SIGNATURES = [_doc(f"ET SCAN Probe {n:03d}") for n in range(600)] + [
    _doc("ET TROJAN Zeus") for _ in range(1000)
]


def test_categories_count_every_signature():
    body = _get(handle_alerts_categories, _fake_client(_MANY_SIGNATURES), "/api/alerts/categories")
    by_id = {c["id"]: c for c in body["categories"]}

    assert by_id["reconnaissance"]["count"] == 600  # was 499
    assert sum(by_id["reconnaissance"]["severity_breakdown"].values()) == 600
    assert sum(p["count"] for p in by_id["reconnaissance"]["sparkline"]) == 600
    assert by_id["malware_c2"]["count"] == 1000


def test_category_detail_total_counts_every_signature():
    client = _fake_client(_MANY_SIGNATURES)
    body = _get(handle_alert_category_detail, client, "/api/alerts/categories/reconnaissance", "reconnaissance")

    assert body["stats"]["total"] == 600  # was 499
    assert sum(body["severity_breakdown"].values()) == 600
    assert body["sub_categories"] == [{"id": "port_scan", "label": body["sub_categories"][0]["label"], "count": 600}]


def test_category_timeline_totals_every_signature_in_a_bucket():
    """60 scan signatures in one hour: the old 50-per-bucket list read 100 of 120."""
    docs = [_doc(f"ET SCAN Probe {n:03d}") for n in range(60) for _ in range(2)] + [
        _doc("ET TROJAN Zeus") for _ in range(500)
    ]
    body = _get(
        handle_alert_category_timeline,
        _fake_client(docs),
        "/api/alerts/categories/reconnaissance/timeline",
        "reconnaissance",
    )

    assert [p["total"] for p in body["series"]] == [120]
    assert body["series"][0]["sub_categories"] == {"port_scan": 120}


def test_timeline_of_a_quiet_category_is_all_zeros():
    body = _get(
        handle_alert_category_timeline,
        _fake_client([_doc("ET TROJAN Zeus")]),
        "/api/alerts/categories/reconnaissance/timeline",
        "reconnaissance",
    )

    assert [p["total"] for p in body["series"]] == [0]
    assert body["series"][0]["sub_categories"] == {}
