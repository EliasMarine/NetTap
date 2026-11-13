"""NET-182: a box with no arkime_sessions3-* index yet shows zeros, not "incomplete".

With no index matching the pattern, OpenSearch answers `_shards.total` 0, hits.total 0 and no
`aggregations` key (seen on the G11, 2026-11-07 and 2026-11-12). The daemon's client gives that
reply the aggregations an empty index would answer, so every checked read takes the empty path.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase
from opensearchpy import OpenSearch

from api.devices import _DEVICE_AGGS, _lan_device_buckets, register_device_routes
from api.risk import register_risk_routes
from api.traffic import register_traffic_routes
from services.alert_intelligence import _all_composite_buckets
from services.excluded_ips import build_lan_filter
from services.risk_scoring import RiskScorer
from storage.exact_terms import (
    ExactTermsOpenSearch,
    empty_aggregations,
    with_empty_aggregations,
)
from tests.fake_drill_opensearch import AUTH, FROM, TO, WINDOW, make_app

LAN = build_lan_filter([(192, 168, 1)])

# The G11's answer to a search of a pattern with no index (2026-11-12)
NO_INDEX = {
    "took": 0,
    "timed_out": False,
    "_shards": {"total": 0, "successful": 0, "skipped": 0, "failed": 0},
    "hits": {"total": {"value": 0, "relation": "eq"}, "max_score": 0.0, "hits": []},
}

# A request with each kind, and the G11's answer to it over a window with no records (2026-11-12)
G11_AGGS = {
    "t": {
        "terms": {"field": "source.ip", "size": 5},
        "aggs": {"s": {"sum": {"field": "source.bytes"}}},
    },
    "mt": {
        "multi_terms": {"terms": [{"field": "source.ip"}, {"field": "destination.ip"}]}
    },
    "c": {
        "composite": {"size": 10, "sources": [{"ip": {"terms": {"field": "source.ip"}}}]}
    },
    "f": {
        "filter": {"term": {"network.transport": "tcp"}},
        "aggs": {
            "inner": {"terms": {"field": "source.ip"}},
            "b": {"sum": {"field": "source.bytes"}},
            "ff": {"filter": {"exists": {"field": "source.mac"}}},
        },
    },
    "fk": {
        "filters": {
            "filters": {
                "a": {"term": {"network.transport": "tcp"}},
                "b": {"term": {"network.transport": "udp"}},
            }
        },
        "aggs": {"m": {"max": {"field": "@timestamp"}}},
    },
    "fl": {"filters": {"filters": [{"term": {"network.transport": "tcp"}}]}},
    "mi": {"missing": {"field": "rule.name"}},
    "su": {"sum": {"field": "source.bytes"}},
    "vc": {"value_count": {"field": "source.ip"}},
    "ca": {"cardinality": {"field": "source.ip"}},
    "mx": {"max": {"field": "@timestamp"}},
    "mn": {"min": {"field": "@timestamp"}},
    "av": {"avg": {"field": "source.bytes"}},
    "th": {"top_hits": {"size": 1}},
    "st": {"stats": {"field": "source.bytes"}},
}
_TERMS = {"buckets": [], "doc_count_error_upper_bound": 0, "sum_other_doc_count": 0}
G11_EMPTY = {
    "av": {"value": None},
    "c": {"buckets": []},
    "ca": {"value": 0},
    "f": {"b": {"value": 0.0}, "doc_count": 0, "ff": {"doc_count": 0}, "inner": _TERMS},
    "fk": {
        "buckets": {
            "a": {"doc_count": 0, "m": {"value": None}},
            "b": {"doc_count": 0, "m": {"value": None}},
        }
    },
    "fl": {"buckets": [{"doc_count": 0}]},
    "mi": {"doc_count": 0},
    "mn": {"value": None},
    "mt": _TERMS,
    "mx": {"value": None},
    "st": {"avg": None, "count": 0, "max": None, "min": None, "sum": 0.0},
    "su": {"value": 0.0},
    "t": _TERMS,
    "th": {
        "hits": {"hits": [], "max_score": None, "total": {"relation": "eq", "value": 0}}
    },
    "vc": {"value": 0},
}


def test_the_empty_answer_is_what_opensearch_answers_over_no_records():
    assert empty_aggregations(G11_AGGS) == G11_EMPTY


def test_a_kind_without_a_known_empty_answer_gives_none():
    slots = {"date_range": {"field": "@timestamp", "ranges": [{"from": 0, "to": 1}]}}
    later_page = {"composite": {**G11_AGGS["c"]["composite"], "after": {"ip": "10.0.0.1"}}}
    other = {"filters": {"filters": {"a": {"match_all": {}}}, "other_bucket": True}}
    for agg in (
        slots,
        {"date_histogram": {"field": "@timestamp", "fixed_interval": "1h"}},
        later_page,
        other,
        {"filter": {"match_all": {}}, "aggs": {"slots": slots}},  # inside a single bucket
    ):
        assert empty_aggregations({"x": agg}) is None, agg


def test_only_a_reply_from_no_index_gains_aggregations():
    body = {"size": 0, "aggs": G11_AGGS}
    assert with_empty_aggregations(NO_INDEX, body) == {
        **NO_INDEX,
        "aggregations": G11_EMPTY,
    }
    one_shard = {**NO_INDEX, "_shards": {**NO_INDEX["_shards"], "total": 1}}
    assert with_empty_aggregations(one_shard, body) is one_shard  # still incomplete
    unknown = {"aggs": {"slots": {"date_histogram": {"field": "@timestamp"}}}}
    assert with_empty_aggregations(NO_INDEX, unknown) is NO_INDEX
    assert with_empty_aggregations(NO_INDEX, {"size": 0}) is NO_INDEX
    first = with_empty_aggregations(NO_INDEX, body)
    first["aggregations"]["t"]["buckets"].append("changed by a caller")
    assert with_empty_aggregations(NO_INDEX, body)["aggregations"]["t"] == _TERMS


def _no_index_search(self, body=None, **kwargs):
    return dict(NO_INDEX)


def _no_index_msearch(self, body=None, **kwargs):
    return {"responses": [dict(NO_INDEX) for _ in body[1::2]]}


def _no_index_count(self, body=None, **kwargs):
    return {"count": 0, "_shards": NO_INDEX["_shards"]}


def _no_index_client() -> ExactTermsOpenSearch:
    """The daemon's client class; its transport is replaced by _no_index_* while patched."""
    return ExactTermsOpenSearch.__new__(ExactTermsOpenSearch)


class NoIndex:
    """OpenSearch answering as it does before the first arkime_sessions3-* index exists."""

    def setUp(self):
        super().setUp()
        for name, fake in (
            ("search", _no_index_search),
            ("msearch", _no_index_msearch),
            ("count", _no_index_count),
        ):
            patcher = patch.object(OpenSearch, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)


class TestTheClient(NoIndex, unittest.TestCase):
    def test_a_search_of_no_index_answers_the_empty_aggregations(self):
        reply = _no_index_client().search(index="arkime_sessions3-*", body={"aggs": G11_AGGS})
        assert reply["aggregations"] == G11_EMPTY

    def test_the_device_read_finds_no_device_instead_of_failing(self):
        app = {"lan_filter": LAN, "excluded_ips": []}
        buckets = _lan_device_buckets(
            _no_index_client(), app, FROM, TO, aggs=_DEVICE_AGGS, what="device list"
        )
        assert buckets == []

    def test_smart_alerts_find_no_group_instead_of_failing(self):
        query = {
            "size": 0,
            "aggs": {
                "grouped": {
                    "composite": {
                        "size": 100,
                        "sources": [{"sig": {"terms": {"field": "rule.name"}}}],
                    }
                }
            },
        }
        assert _all_composite_buckets(_no_index_client(), query) == []


def _register(app, client):
    storage = SimpleNamespace(_client=client)
    app["storage"] = storage
    register_device_routes(app, storage)
    register_risk_routes(app, RiskScorer(), storage)
    register_traffic_routes(app, storage)


class TestPagesOnAFreshBox(NoIndex, AioHTTPTestCase):
    async def get_application(self):
        return make_app(_no_index_client(), _register, lan_filter=LAN)

    async def get(self, path):
        sep = "&" if "?" in path else "?"
        resp = await self.client.get(f"{path}{sep}{WINDOW}", headers=AUTH)
        return resp.status, await resp.json()

    async def test_the_device_list_is_empty(self):
        status, body = await self.get("/api/devices")
        assert (status, body["devices"]) == (200, []), body

    async def test_the_device_count_is_zero(self):
        status, body = await self.get("/api/devices/count")
        assert (status, body["count"]) == (200, 0), body

    async def test_risk_scores_are_an_empty_list(self):
        status, body = await self.get("/api/risk/scores")
        assert status == 200, body

    async def test_one_devices_score_is_not_found(self):
        status, body = await self.get("/api/risk/scores/192.168.1.20")
        assert status == 404, body

    async def test_home_protocols_are_empty(self):
        status, body = await self.get("/api/traffic/protocols")
        assert status == 200, body
        assert body["protocols"] == [] and body["services"] == []
