"""
NetTap Natural Language Search API Routes

Registers endpoints for natural language search queries against
OpenSearch indices. Converts human-readable queries into OpenSearch DSL.
"""

import logging

from aiohttp import web
from opensearchpy import OpenSearchException

from services.excluded_ips import build_excluded_ips_filter
from services.nl_search import NLSearchParser
from storage.manager import StorageManager

logger = logging.getLogger("nettap.api.search")


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_search(request: web.Request) -> web.Response:
    """GET /api/search?q={query}&size={size}

    Execute a natural language search query. The query is parsed into
    OpenSearch DSL and executed against the appropriate index.
    """
    parser: NLSearchParser = request.app["nl_search_parser"]
    storage: StorageManager = request.app["storage"]
    client = storage._client

    query_text = request.query.get("q", "").strip()
    size_raw = request.query.get("size", "50")
    try:
        size = max(1, min(500, int(size_raw)))
    except (ValueError, TypeError):
        size = 50

    parsed = parser.parse(query_text)
    parsed["size"] = size

    # Build the search body
    search_body = parsed["query"]
    search_body["size"] = parsed["size"]
    search_body["sort"] = parsed["sort"]

    # Inject excluded IPs filter into the parsed query's bool clause
    excluded = build_excluded_ips_filter(request.app.get("excluded_ips", []))
    if excluded:
        query_clause = search_body.get("query", {})
        if "bool" in query_clause:
            existing_must_not = query_clause["bool"].get("must_not", [])
            if isinstance(existing_must_not, dict):
                existing_must_not = [existing_must_not]
            query_clause["bool"]["must_not"] = existing_must_not + excluded
        elif "match_all" in query_clause:
            # Replace match_all with a bool query that has must_not
            search_body["query"] = {
                "bool": {
                    "must": [{"match_all": {}}],
                    "must_not": excluded,
                }
            }

    try:
        result = client.search(
            index=parsed["index"],
            body=search_body,
        )
    except OpenSearchException as exc:
        logger.error("OpenSearch search error: %s", exc)
        return web.json_response({"error": f"Search failed: {exc}"}, status=502)

    hits = result.get("hits", {})
    total = hits.get("total", {})
    total_count = total.get("value", 0) if isinstance(total, dict) else total
    documents = [hit.get("_source", {}) for hit in hits.get("hits", [])]

    return web.json_response(
        {
            "query": query_text,
            "description": parsed["description"],
            "index": parsed["index"],
            "total": total_count,
            "count": len(documents),
            "results": documents,
        }
    )


async def handle_search_suggest(request: web.Request) -> web.Response:
    """GET /api/search/suggest?q={partial}

    Return search suggestions based on partial input.
    """
    parser: NLSearchParser = request.app["nl_search_parser"]
    partial = request.query.get("q", "").strip()

    suggestions = parser.suggest(partial)

    return web.json_response(
        {
            "query": partial,
            "suggestions": suggestions,
        }
    )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_search_routes(
    app: web.Application,
    parser: NLSearchParser,
    storage_manager: StorageManager,
) -> None:
    """Register all natural language search API routes."""
    app["nl_search_parser"] = parser

    # Suggest must be registered before the main search to avoid
    # route conflicts (suggest is more specific path)
    app.router.add_get("/api/search/suggest", handle_search_suggest)
    app.router.add_get("/api/search", handle_search)
    logger.info("Search API routes registered (2 endpoints)")
