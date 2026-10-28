"""
NetTap Logstash Monitoring API Routes

Queries the Logstash monitoring API (port 9600) to report pipeline
status, throughput, JVM stats, and errors.
"""

import logging
import os

import aiohttp as aiohttp_client
from aiohttp import web

logger = logging.getLogger("nettap.api.logstash")

LOGSTASH_API_URL = os.environ.get("LOGSTASH_API_URL", "http://logstash:9600")


async def _fetch_logstash_api(path: str = "/_node/stats") -> dict | None:
    """Fetch data from Logstash's monitoring API. Returns None on failure."""
    url = f"{LOGSTASH_API_URL}{path}"
    try:
        async with aiohttp_client.ClientSession() as session:
            async with session.get(url, timeout=aiohttp_client.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning("Logstash API returned %d for %s", resp.status, path)
                return None
    except Exception as exc:
        logger.warning("Logstash API unreachable at %s: %s", url, exc)
        return None


async def handle_logstash_stats(request: web.Request) -> web.Response:
    """GET /api/logstash/stats — Logstash node stats (JVM, CPU, pipelines)."""
    data = await _fetch_logstash_api("/_node/stats")
    if data is None:
        return web.json_response(
            {"error": "Logstash monitoring API unreachable", "available": False},
            status=502,
        )
    return web.json_response({
        "available": True,
        "jvm": data.get("jvm", {}),
        "process": data.get("process", {}),
        "pipelines": data.get("pipelines", {}),
        "events": data.get("events", {}),
    })


async def handle_logstash_pipelines(request: web.Request) -> web.Response:
    """GET /api/logstash/pipelines — Per-pipeline breakdown."""
    data = await _fetch_logstash_api("/_node/stats/pipelines")
    if data is None:
        return web.json_response(
            {"error": "Logstash monitoring API unreachable", "available": False},
            status=502,
        )
    pipelines = data.get("pipelines", {})
    result = []
    for name, stats in pipelines.items():
        events = stats.get("events", {})
        result.append({
            "id": name,
            "events": {
                "in": events.get("in", 0),
                "out": events.get("out", 0),
                "filtered": events.get("filtered", 0),
                "duration_ms": events.get("duration_in_millis", 0),
            },
            "plugins": stats.get("plugins", {}),
            "reloads": stats.get("reloads", {}),
        })
    return web.json_response({"pipelines": result, "count": len(result)})


def register_logstash_routes(app: web.Application) -> None:
    app.router.add_get("/api/logstash/stats", handle_logstash_stats)
    app.router.add_get("/api/logstash/pipelines", handle_logstash_pipelines)
    logger.info("Logstash monitoring API routes registered (2 endpoints)")
