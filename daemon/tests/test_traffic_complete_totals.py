"""#96: traffic figures stay whole once a network passes a list's cap.

A fake OpenSearch answers each search from a list of documents, honouring the body's size,
sort and aggregations, so a figure derived from a capped list comes out short.
"""

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


def _metric(docs: list[dict], agg: dict) -> dict:
    if "sum" in agg:
        return {"value": float(sum(_field(d, agg["sum"]["field"]) or 0 for d in docs))}
    kind = "min" if "min" in agg else "max"
    values = [_field(d, agg[kind]["field"]) for d in docs]
    values = [v for v in values if v is not None]
    if not values:
        return {"value": None}
    return {"value": 0.0, "value_as_string": (min if kind == "min" else max)(values)}


def _terms(docs: list[dict], agg: dict) -> dict:
    counts: dict = {}
    for d in docs:
        key = _field(d, agg["terms"]["field"])
        if key is not None:
            counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    size = agg["terms"].get("size", 10)
    return {
        "buckets": [{"key": k, "doc_count": n} for k, n in ranked[:size]],
        "sum_other_doc_count": sum(n for _, n in ranked[size:]),
    }


def fake_hits_search(docs: list[dict]):
    """A search() over `docs` that honours size, @timestamp sort, track_total_hits and flat aggs."""

    def search(index: str, body: dict) -> dict:
        sort = (body.get("sort") or [{"@timestamp": {"order": "asc"}}])[0]["@timestamp"]["order"]
        rows = sorted(docs, key=lambda d: d["@timestamp"], reverse=sort == "desc")
        total = len(docs) if body.get("track_total_hits") else min(len(docs), 10_000)
        aggs = {
            name: _terms(docs, agg) if "terms" in agg else _metric(docs, agg)
            for name, agg in body.get("aggs", {}).items()
        }
        return {
            "hits": {
                "total": {"value": total},
                "hits": [{"_id": str(i), "_source": d} for i, d in enumerate(rows[: body.get("size", 10)])],
            },
            "aggregations": aggs,
        }

    return search


def _app(client: MagicMock) -> web.Application:
    with patch.object(StorageManager, "_create_client", return_value=client):
        storage = StorageManager(RetentionConfig(), "http://localhost:9200")
    app = web.Application()
    app["storage"] = storage
    register_traffic_routes(app, storage)
    return app


def _pair_history(count: int) -> list[dict]:
    """`count` laptop -> DNS server connections, one a minute from midnight; the newest is UDP."""
    return [
        {
            "@timestamp": f"2026-11-01T{i // 60:02d}:{i % 60:02d}:00.000Z",
            "source": {"ip": "192.168.1.50", "bytes": 100},
            "destination": {"ip": "192.168.1.1", "bytes": 300},
            "network": {"transport": "udp" if i == count - 1 else "tcp"},
        }
        for i in range(count)
    ]


class TestRelatedConnectionsWholeWindow(AioHTTPTestCase):
    """The Connection drawer's pair summary counts every connection, not the 200 rows listed."""

    async def get_application(self):
        self.mock_client = MagicMock()
        self.mock_client.search.side_effect = fake_hits_search(_pair_history(250))
        return _app(self.mock_client)

    @unittest_run_loop
    async def test_summary_covers_all_250_connections(self):
        resp = await self.client.request(
            "GET",
            "/api/traffic/connections/related?src_ip=192.168.1.50&dst_ip=192.168.1.1"
            "&from=2026-11-01T00:00:00Z&to=2026-11-02T00:00:00Z",
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertEqual(data["total_connections"], 250)  # was 200
        self.assertEqual(data["total_bytes"], 250 * 400)  # was 80,000
        self.assertEqual(data["protocols"], ["tcp", "udp"])  # the newest (UDP) row was cut
        self.assertEqual(data["first_seen"], "2026-11-01T00:00:00.000Z")
        self.assertEqual(data["last_seen"], "2026-11-01T04:09:00.000Z")  # was 03:19
        # the listed rows stay capped, newest first
        self.assertEqual(len(data["connections"]), 200)
        self.assertEqual(data["connections"][0]["@timestamp"], "2026-11-01T04:09:00.000Z")
