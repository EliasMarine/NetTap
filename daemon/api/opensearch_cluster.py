"""
NetTap OpenSearch Cluster API Routes

Provides cluster health, index listing, shard allocation, and template
information from the local OpenSearch instance.
"""

import asyncio
import logging

from aiohttp import web
from opensearchpy import OpenSearchException

from storage.manager import StorageManager

logger = logging.getLogger("nettap.api.opensearch_cluster")


async def handle_cluster_health(request: web.Request) -> web.Response:
    """GET /api/opensearch/cluster — Cluster health + stats."""
    storage: StorageManager = request.app["storage"]
    try:
        loop = asyncio.get_running_loop()
        health = await loop.run_in_executor(None, storage._client.cluster.health)
        stats = await loop.run_in_executor(None, lambda: storage._client.cluster.stats())
        return web.json_response({
            **health,
            "total_indices": stats.get("indices", {}).get("count", 0),
            "total_docs": stats.get("indices", {}).get("docs", {}).get("count", 0),
            "total_size_bytes": stats.get("indices", {}).get("store", {}).get("size_in_bytes", 0),
        })
    except OpenSearchException as exc:
        logger.exception("Failed to get cluster health")
        return web.json_response({"error": str(exc)}, status=500)


async def handle_indices(request: web.Request) -> web.Response:
    """GET /api/opensearch/indices — Index list with details."""
    storage: StorageManager = request.app["storage"]
    try:
        loop = asyncio.get_running_loop()
        raw_indices = await loop.run_in_executor(
            None,
            lambda: storage._client.cat.indices(
                format="json",
                h="index,health,status,docs.count,store.size,pri.store.size,creation.date.string",
                s="index",
            )
        )
        # Normalize dot-notation keys to underscore for frontend compatibility
        indices = []
        for idx in (raw_indices or []):
            indices.append({
                "index": idx.get("index", ""),
                "health": idx.get("health", ""),
                "status": idx.get("status", ""),
                "docs_count": idx.get("docs.count", ""),
                "store_size": idx.get("store.size", ""),
                "pri_store_size": idx.get("pri.store.size", ""),
                "creation_date": idx.get("creation.date.string", ""),
            })
        return web.json_response({"indices": indices, "count": len(indices)})
    except OpenSearchException as exc:
        logger.exception("Failed to list indices")
        return web.json_response({"error": str(exc)}, status=500)


async def handle_shards(request: web.Request) -> web.Response:
    """GET /api/opensearch/shards — Shard allocation details."""
    storage: StorageManager = request.app["storage"]
    try:
        loop = asyncio.get_running_loop()
        shards = await loop.run_in_executor(
            None,
            lambda: storage._client.cat.shards(
                format="json",
                h="index,shard,prirep,state,docs,store,node",
                s="index,shard",
            )
        )
        return web.json_response({"shards": shards or [], "count": len(shards or [])})
    except OpenSearchException as exc:
        logger.exception("Failed to list shards")
        return web.json_response({"error": str(exc)}, status=500)


async def handle_templates(request: web.Request) -> web.Response:
    """GET /api/opensearch/templates — Index template list."""
    storage: StorageManager = request.app["storage"]
    try:
        loop = asyncio.get_running_loop()
        templates = await loop.run_in_executor(
            None,
            lambda: storage._client.cat.templates(
                format="json",
                h="name,index_patterns,order,version",
                s="name",
            )
        )
        return web.json_response({"templates": templates or [], "count": len(templates or [])})
    except OpenSearchException as exc:
        logger.exception("Failed to list templates")
        return web.json_response({"error": str(exc)}, status=500)


def register_opensearch_cluster_routes(app: web.Application, storage: StorageManager) -> None:
    app["storage"] = storage
    app.router.add_get("/api/opensearch/cluster", handle_cluster_health)
    app.router.add_get("/api/opensearch/indices", handle_indices)
    app.router.add_get("/api/opensearch/shards", handle_shards)
    app.router.add_get("/api/opensearch/templates", handle_templates)
    logger.info("OpenSearch cluster API routes registered (4 endpoints)")
