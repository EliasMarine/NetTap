"""
NetTap OpenSearch Cluster API Routes

Provides cluster health, index listing, shard allocation, and template
information from the local OpenSearch instance.
"""

import logging

from aiohttp import web
from opensearchpy import OpenSearchException

from api.offload import run_blocking
from storage.manager import StorageManager

logger = logging.getLogger("nettap.api.opensearch_cluster")


async def handle_cluster_health(request: web.Request) -> web.Response:
    """GET /api/opensearch/cluster — Cluster health + stats."""
    storage: StorageManager = request.app["storage"]
    try:
        # OLD CODE: loop.run_in_executor(None, …), asyncio's default pool (PR #200 review)
        health = await run_blocking(storage._client.cluster.health)
        stats = await run_blocking(lambda: storage._client.cluster.stats())
        return web.json_response(
            {
                **health,
                "total_indices": stats.get("indices", {}).get("count", 0),
                "total_docs": stats.get("indices", {}).get("docs", {}).get("count", 0),
                "total_size_bytes": stats.get("indices", {})
                .get("store", {})
                .get("size_in_bytes", 0),
            }
        )
    except OpenSearchException as exc:
        logger.exception("Failed to get cluster health")
        return web.json_response({"error": str(exc)}, status=500)


def _byte_count(value: object) -> int | None:
    """A `_cat` size asked for with bytes=b: digits only. Anything else is unknown (None)."""
    text = str(value).strip() if value is not None else ""
    # OLD CODE: return int(text) if text.isdigit() else None (isdigit passes "²", which int() rejects)
    return int(text) if text.isdecimal() else None


async def handle_indices(request: web.Request) -> web.Response:
    """GET /api/opensearch/indices — Index list with details."""
    storage: StorageManager = request.app["storage"]
    try:
        # OLD CODE: loop.run_in_executor(None, …), asyncio's default pool (PR #200 review)
        raw_indices = await run_blocking(
            # NET-166: bytes="b" asks for exact byte counts; the default "512kb"/"1.2gb" text is
            # base 1,024 and already rounded, so the page couldn't show it in decimal units honestly
            lambda: storage._client.cat.indices(
                format="json",
                h="index,health,status,docs.count,store.size,pri.store.size,creation.date.string",
                s="index",
                bytes="b",
            ),
        )
        # Normalize dot-notation keys to underscore for frontend compatibility
        indices = []
        for idx in raw_indices or []:
            indices.append(
                {
                    "index": idx.get("index", ""),
                    "health": idx.get("health", ""),
                    "status": idx.get("status", ""),
                    "docs_count": idx.get("docs.count", ""),
                    # OLD CODE: "store_size": idx.get("store.size", ""), (NET-166: OpenSearch's text)
                    # OLD CODE: "pri_store_size": idx.get("pri.store.size", ""),
                    "store_size": _byte_count(idx.get("store.size")),
                    "pri_store_size": _byte_count(idx.get("pri.store.size")),
                    "creation_date": idx.get("creation.date.string", ""),
                }
            )
        return web.json_response({"indices": indices, "count": len(indices)})
    except OpenSearchException as exc:
        logger.exception("Failed to list indices")
        return web.json_response({"error": str(exc)}, status=500)


async def handle_shards(request: web.Request) -> web.Response:
    """GET /api/opensearch/shards — Shard allocation details."""
    storage: StorageManager = request.app["storage"]
    try:
        # OLD CODE: loop.run_in_executor(None, …), asyncio's default pool (PR #200 review)
        shards = await run_blocking(
            lambda: storage._client.cat.shards(
                format="json",
                h="index,shard,prirep,state,docs,store,node",
                s="index,shard",
            ),
        )
        return web.json_response({"shards": shards or [], "count": len(shards or [])})
    except OpenSearchException as exc:
        logger.exception("Failed to list shards")
        return web.json_response({"error": str(exc)}, status=500)


async def handle_templates(request: web.Request) -> web.Response:
    """GET /api/opensearch/templates — Index template list."""
    storage: StorageManager = request.app["storage"]
    try:
        # OLD CODE: loop.run_in_executor(None, …), asyncio's default pool (PR #200 review)
        templates = await run_blocking(
            lambda: storage._client.cat.templates(
                format="json",
                h="name,index_patterns,order,version",
                s="name",
            ),
        )
        return web.json_response(
            {"templates": templates or [], "count": len(templates or [])}
        )
    except OpenSearchException as exc:
        logger.exception("Failed to list templates")
        return web.json_response({"error": str(exc)}, status=500)


def register_opensearch_cluster_routes(
    app: web.Application, storage: StorageManager
) -> None:
    app["storage"] = storage
    app.router.add_get("/api/opensearch/cluster", handle_cluster_health)
    app.router.add_get("/api/opensearch/indices", handle_indices)
    app.router.add_get("/api/opensearch/shards", handle_shards)
    app.router.add_get("/api/opensearch/templates", handle_templates)
    logger.info("OpenSearch cluster API routes registered (4 endpoints)")
