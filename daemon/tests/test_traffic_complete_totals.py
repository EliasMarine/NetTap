"""#96: traffic figures stay whole once a network passes a list's cap.

A fake OpenSearch answers each search from a list of documents, honouring the body's query,
size, sort and aggregations (terms with size/order/missing, composite paging, metrics), so a
figure derived from a capped list comes out short exactly as it would on a real cluster.
"""

import fnmatch
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.traffic import register_traffic_routes
from storage.manager import RetentionConfig, StorageManager


def _field(doc: dict, path: str):
    for part in path.split("."):
        if not isinstance(doc, dict) or part not in doc:
            return None
        doc = doc[part]
    return doc


def _matches(doc: dict, q: dict | None) -> bool:
    if not q or "match_all" in q or "range" in q:  # every fake doc is inside the window
        return True
    if "bool" in q:
        b = q["bool"]
        required = [*b.get("filter", []), *b.get("must", [])]
        should = b.get("should", [])
        need = b.get("minimum_should_match", 0 if required else 1)
        return (
            all(_matches(doc, c) for c in required)
            and not any(_matches(doc, c) for c in b.get("must_not", []))
            and sum(_matches(doc, c) for c in should) >= (need if should else 0)
        )
    (kind, spec), = q.items()
    (field, value), = spec.items()
    if kind == "term":
        return _field(doc, field) == value
    if kind == "terms":
        return _field(doc, field) in value
    if kind == "wildcard":
        return fnmatch.fnmatchcase(str(_field(doc, field) or ""), value)
    raise ValueError(f"fake OpenSearch has no {kind!r} query")


def _metric(docs: list[dict], agg: dict) -> dict:
    if "sum" in agg:
        spec = agg["sum"]
        if "script" in spec:  # every bytes script in traffic code is source + destination bytes
            assert "source.bytes" in spec["script"]["source"]
            assert "destination.bytes" in spec["script"]["source"]
            fields = ["source.bytes", "destination.bytes"]
        else:
            fields = [spec["field"]]
        return {"value": float(sum(_field(d, f) or 0 for d in docs for f in fields))}
    kind = "min" if "min" in agg else "max"
    values = [v for v in (_field(d, agg[kind]["field"]) for d in docs) if v is not None]
    if not values:
        return {"value": None}
    return {"value": 0.0, "value_as_string": (min if kind == "min" else max)(values)}


def _groups(docs: list[dict], field: str, missing=None) -> dict:
    out: dict = {}
    for d in docs:
        key = _field(d, field)
        key = missing if key is None else key
        if key is not None:
            out = {**out, key: [*out.get(key, []), d]}
    return out


def _bucket(key, docs: list[dict], sub: dict) -> dict:
    return {"key": key, "doc_count": len(docs), **_aggregate(docs, sub)}


def _terms(docs: list[dict], spec: dict, sub: dict) -> dict:
    groups = _groups(docs, spec["field"], spec.get("missing"))
    buckets = [_bucket(k, g, sub) for k, g in groups.items()]
    if spec.get("order"):
        (metric, _direction), = spec["order"].items()
        buckets = sorted(buckets, key=lambda b: -b[metric]["value"])
    else:
        buckets = sorted(buckets, key=lambda b: -b["doc_count"])
    size = spec.get("size", 10)
    return {
        "doc_count_error_upper_bound": 0,
        "sum_other_doc_count": sum(b["doc_count"] for b in buckets[size:]),
        "buckets": buckets[:size],
    }


def _composite(docs: list[dict], spec: dict, sub: dict) -> dict:
    (name, source), = spec["sources"][0].items()
    groups = _groups(docs, source["terms"]["field"])
    after = (spec.get("after") or {}).get(name)
    keys = [k for k in sorted(groups) if after is None or k > after][: spec["size"]]
    page = {"buckets": [_bucket({name: k}, groups[k], sub) for k in keys]}
    return {**page, "after_key": {name: keys[-1]}} if keys else page


def _aggregate(docs: list[dict], aggs: dict) -> dict:
    out = {}
    for name, agg in aggs.items():
        sub = agg.get("aggs", {})
        if "terms" in agg:
            out[name] = _terms(docs, agg["terms"], sub)
        elif "composite" in agg:
            out[name] = _composite(docs, agg["composite"], sub)
        elif "date_histogram" in agg:  # one bucket per distinct @timestamp
            groups = _groups(docs, "@timestamp")
            out[name] = {"buckets": [{**_bucket(k, groups[k], sub), "key_as_string": k} for k in sorted(groups)]}
        else:
            out[name] = _metric(docs, agg)
    return out


def fake_search(docs: list[dict]):
    """A search() over `docs`, for MagicMock.side_effect."""

    def search(index: str, body: dict) -> dict:
        matched = [d for d in docs if _matches(d, body.get("query"))]
        sort = (body.get("sort") or [{"@timestamp": {"order": "asc"}}])[0]["@timestamp"]["order"]
        rows = sorted(matched, key=lambda d: d.get("@timestamp", ""), reverse=sort == "desc")
        total = len(matched) if body.get("track_total_hits") else min(len(matched), 10_000)
        return {
            "hits": {
                "total": {"value": total},
                "hits": [{"_id": str(i), "_source": d} for i, d in enumerate(rows[: body.get("size", 10)])],
            },
            "aggregations": _aggregate(matched, body.get("aggs", {})),
        }

    return search


def _conn(src: str, dst: str, asn: str | None, src_bytes: int, dst_bytes: int, **extra) -> dict:
    doc = {
        "@timestamp": "2026-11-01T12:00:00.000Z",
        "event": {"provider": "zeek", "dataset": "conn"},
        "source": {"ip": src, "bytes": src_bytes},
        "destination": {"ip": dst, "bytes": dst_bytes},
        "network": {"transport": "tcp"},
    }
    if asn:
        doc["destination"]["as"] = {"full": asn}
    return {**doc, **extra}


class _FakeOpenSearchCase(AioHTTPTestCase):
    """Traffic routes over a fake OpenSearch holding DOCS."""

    DOCS: list[dict] = []

    async def get_application(self):
        self.mock_client = MagicMock()
        self.mock_client.search.side_effect = fake_search(self.DOCS)
        with patch.object(StorageManager, "_create_client", return_value=self.mock_client):
            storage = StorageManager(RetentionConfig(), "http://localhost:9200")
        app = web.Application()
        app["storage"] = storage
        register_traffic_routes(app, storage)
        return app

    async def _get(self, path: str) -> dict:
        resp = await self.client.request(
            "GET", f"{path}{'&' if '?' in path else '?'}from=2026-11-01T00:00:00Z&to=2026-11-02T00:00:00Z"
        )
        self.assertEqual(resp.status, 200, path)
        return await resp.json()


def _pair_history(count: int) -> list[dict]:
    """`count` laptop -> DNS server connections, one a minute from midnight; the newest is UDP."""
    return [
        {
            "@timestamp": f"2026-11-01T{i // 60:02d}:{i % 60:02d}:00.000Z",
            "event": {"provider": "zeek", "dataset": "conn"},
            "source": {"ip": "192.168.1.50", "bytes": 100},
            "destination": {"ip": "192.168.1.1", "bytes": 300},
            "network": {"transport": "udp" if i == count - 1 else "tcp"},
        }
        for i in range(count)
    ]


class TestRelatedConnectionsWholeWindow(_FakeOpenSearchCase):
    """The Connection drawer's pair summary counts every connection, not the 200 rows listed."""

    DOCS = _pair_history(250)

    @unittest_run_loop
    async def test_summary_covers_all_250_connections(self):
        data = await self._get("/api/traffic/connections/related?src_ip=192.168.1.50&dst_ip=192.168.1.1")

        self.assertEqual(data["total_connections"], 250)  # was 200
        self.assertEqual(data["total_bytes"], 250 * 400)  # was 80,000
        self.assertEqual(data["protocols"], ["tcp", "udp"])  # the newest (UDP) row was cut
        self.assertEqual(data["first_seen"], "2026-11-01T00:00:00.000Z")
        self.assertEqual(data["last_seen"], "2026-11-01T04:09:00.000Z")  # was 03:19
        # the listed rows stay capped, newest first
        self.assertEqual(len(data["connections"]), 200)
        self.assertEqual(data["connections"][0]["@timestamp"], "2026-11-01T04:09:00.000Z")


def _past_500_asns() -> list[dict]:
    """600 busy unclassified ASNs (2 connections each) and one quiet Netflix ASN (1 connection)."""
    busy = [
        _conn("192.168.1.10", f"203.0.113.{n % 250}", f"AS{64_000 + n} Hosting Org {n}", 400, 600)
        for n in range(600)
        for _ in range(2)
    ]
    return [*busy, _conn("192.168.1.11", "198.51.100.7", "AS2906 Netflix Inc", 400, 600)]


class TestCategoriesPast500Asns(_FakeOpenSearchCase):
    """Home's category bars count every ASN, not the 500 with the most connections."""

    DOCS = _past_500_asns()

    @unittest_run_loop
    async def test_every_asn_reaches_its_category(self):
        cats = {c["name"]: c for c in (await self._get("/api/traffic/categories"))["categories"]}

        self.assertIn("streaming", cats)  # the 601st ASN was dropped
        self.assertEqual(cats["streaming"]["total_bytes"], 1_000)
        self.assertEqual(cats["streaming"]["connection_count"], 1)
        self.assertEqual(cats["other"]["connection_count"], 1_200)  # was 1,000
        self.assertEqual(sum(c["total_bytes"] for c in cats.values()), 1_201_000)


def _office_streaming() -> list[dict]:
    """60 devices on Netflix: 50 light ones (2 x 1 kB) and 10 heavy ones (1 x 10 kB)."""
    light = [
        _conn(f"10.0.0.{n}", "198.51.100.7", "AS2906 Netflix Inc", 100, 900)
        for n in range(50)
        for _ in range(2)
    ]
    heavy = [_conn(f"10.0.1.{n}", "198.51.100.7", "AS2906 Netflix Inc", 1_000, 9_000) for n in range(10)]
    return [*light, *heavy]


class TestCategoryDetailPast50Devices(_FakeOpenSearchCase):
    """/traffic/[category] totals and shares cover every device, not the 50 listed."""

    DOCS = _office_streaming()

    @unittest_run_loop
    async def test_totals_and_shares_cover_all_60_devices(self):
        data = await self._get("/api/traffic/categories/streaming")

        self.assertEqual(data["device_count"], 60)  # was 50
        self.assertEqual(data["total_bytes"], 200_000)  # was 100,000
        self.assertEqual(data["connection_count"], 110)  # was 100
        self.assertEqual(len(data["devices"]), 50)  # the list stays top 50, now by bytes
        self.assertEqual(data["devices"][0]["total_bytes"], 10_000)  # heavy devices were missing
        self.assertEqual(data["devices"][0]["percent"], 5.0)
        self.assertEqual(data["devices"][-1]["percent"], 1.0)  # was 2.0


def _sankey_flows() -> list[dict]:
    """Two busy devices: many small connections to two ASNs, one 1 kB download from a third."""
    per_device = [
        *[("AS2 Many Small", 10)] * 5,
        *[("AS3 Spread Org", 10)] * 3,
        ("AS1 Big Transfer", 1_000),
    ]
    busy = [
        _conn(src, "198.51.100.1", asn, 0, size)
        for src in ("10.0.0.1", "10.0.0.2")
        for asn, size in per_device
    ]
    return [*busy, _conn("10.0.0.3", "198.51.100.1", "AS2 Many Small", 0, 5)]


class TestSankeyDestinationTotals(_FakeOpenSearchCase):
    """Sankey destination nodes are the shown sources' full bytes to each destination."""

    DOCS = _sankey_flows()

    @unittest_run_loop
    async def test_destination_nodes_rank_and_sum_by_bytes(self):
        data = await self._get("/api/traffic/connections/sankey?limit=2")

        self.assertEqual([s["id"] for s in data["nodes"]["sources"]], ["10.0.0.1", "10.0.0.2"])
        dests = [(d["id"], d["value"]) for d in data["nodes"]["destinations"]]
        # was [("AS2 Many Small", 100), ("AS3 Spread Org", 60)]: each device's top 2 by connections
        self.assertEqual(dests, [("AS1 Big Transfer", 2_000), ("AS2 Many Small", 100)])
        links = {(link["source"], link["target"]): link["value"] for link in data["links"]}
        self.assertEqual(links[("tcp", "AS1 Big Transfer")], 2_000)
        self.assertEqual(links[("tcp", "AS2 Many Small")], 100)  # the 3rd device is not shown
        self.assertNotIn(("tcp", "AS3 Spread Org"), links)


def _home_vs_detail() -> list[dict]:
    """A Netflix ASN spelled in capitals, a RingCentral ASN that also holds the IoT substring
    "Ring", and a real IoT ASN: each must sit in exactly the category Home's bar puts it in."""
    return [
        _conn("10.0.0.1", "198.51.100.1", "AS2906 NETFLIX INC", 100, 900),  # Home: streaming
        _conn("10.0.0.2", "198.51.100.2", "AS2906 Netflix Inc", 300, 2_700),  # streaming
        _conn("10.0.0.3", "198.51.100.3", "AS19700 RingCentral, Inc.", 200, 1_800),  # communication
        _conn("10.0.0.4", "198.51.100.4", "AS64600 Ring LLC", 50, 450),  # iot
    ]


class TestCategoryDetailMatchesHome(_FakeOpenSearchCase):
    """A category's detail page and bandwidth chart hold exactly its Home bar (#96)."""

    DOCS = _home_vs_detail()

    @unittest_run_loop
    async def test_detail_and_chart_totals_equal_the_home_bar(self):
        home = {c["name"]: c for c in (await self._get("/api/traffic/categories"))["categories"]}
        self.assertEqual(home["streaming"]["total_bytes"], 4_000)
        self.assertEqual(home["communication"]["total_bytes"], 2_000)
        self.assertEqual(home["iot"]["total_bytes"], 500)

        for name in ("streaming", "communication", "iot"):
            detail = await self._get(f"/api/traffic/categories/{name}")
            # was streaming 3,000 (capitals missed) and iot 2,500 (RingCentral counted twice)
            self.assertEqual(detail["total_bytes"], home[name]["total_bytes"], name)
            self.assertEqual(detail["connection_count"], home[name]["connection_count"], name)
            chart = await self._get(f"/api/traffic/categories/{name}/bandwidth")
            self.assertEqual(sum(b["total_bytes"] for b in chart["series"]), home[name]["total_bytes"], name)

    @unittest_run_loop
    async def test_services_are_the_home_bars_services(self):
        home = {c["name"]: c for c in (await self._get("/api/traffic/categories"))["categories"]}
        detail = await self._get("/api/traffic/categories/streaming")
        self.assertEqual(
            [(s["name"], s["bytes"]) for s in detail["services"]],
            [(s["name"], s["bytes"]) for s in home["streaming"]["top_services"]],
        )
        iot = await self._get("/api/traffic/categories/iot")
        self.assertEqual([s["name"] for s in iot["services"]], ["Ring LLC"])  # not RingCentral


def _many_small_streams() -> list[dict]:
    """Ten streaming ASNs with 2 small connections each, and one ASN with 1 large download."""
    small = [
        _conn("10.0.0.1", f"198.51.100.{n}", f"AS{65_000 + n} Spotify Edge {n}", 10, 90)
        for n in range(10)
        for _ in range(2)
    ]
    return [*small, _conn("10.0.0.2", "198.51.100.99", "AS2906 Netflix Inc", 1_000, 49_000)]


class TestCategoryTopServicesByBytes(_FakeOpenSearchCase):
    """Top services are ranked by bytes over every ASN, not the 10 with most connections."""

    DOCS = _many_small_streams()

    @unittest_run_loop
    async def test_high_byte_service_with_few_connections_is_listed(self):
        detail = await self._get("/api/traffic/categories/streaming")

        self.assertEqual(detail["services"][0], {"name": "Netflix Inc", "bytes": 50_000, "connections": 1})
        self.assertEqual(len(detail["services"]), 10)
        home = {c["name"]: c for c in (await self._get("/api/traffic/categories"))["categories"]}
        self.assertEqual(
            [(s["name"], s["bytes"]) for s in detail["services"]],
            [(s["name"], s["bytes"]) for s in home["streaming"]["top_services"]],
        )
