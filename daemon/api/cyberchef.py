"""
NetTap CyberChef API Routes

Registers CyberChef-related endpoints with the aiohttp application.
"""

import logging
from aiohttp import web

from services.cyberchef_service import CyberChefService

logger = logging.getLogger("nettap.api.cyberchef")


async def handle_cyberchef_status(request: web.Request) -> web.Response:
    """GET /api/cyberchef/status — CyberChef container status."""
    cyberchef: CyberChefService = request.app["cyberchef"]
    try:
        status = await cyberchef.is_available()
        return web.json_response(status)
    except Exception as exc:
        logger.exception("Failed to check CyberChef status")
        return web.json_response({"error": str(exc)}, status=500)


async def handle_cyberchef_recipes(request: web.Request) -> web.Response:
    """GET /api/cyberchef/recipes?category=decode — List pre-built recipes."""
    category = request.query.get("category", "")
    cyberchef: CyberChefService = request.app["cyberchef"]
    try:
        recipes = cyberchef.get_recipes(category)
        return web.json_response({"recipes": recipes, "count": len(recipes)})
    except Exception as exc:
        logger.exception("Failed to get recipes")
        return web.json_response({"error": str(exc)}, status=500)


async def handle_cyberchef_url(request: web.Request) -> web.Response:
    """POST /api/cyberchef/url — Build a CyberChef URL with recipe and input data."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    cyberchef: CyberChefService = request.app["cyberchef"]
    recipe_fragment = body.get("recipe_fragment", "")
    input_data = body.get("input_data", "")

    if not recipe_fragment:
        return web.json_response({"error": "recipe_fragment is required"}, status=400)

    try:
        url = cyberchef.build_recipe_url(recipe_fragment, input_data)
        return web.json_response({"url": url})
    except Exception as exc:
        logger.exception("Failed to build CyberChef URL")
        return web.json_response({"error": str(exc)}, status=500)


def register_cyberchef_routes(
    app: web.Application, cyberchef: CyberChefService
) -> None:
    """Register CyberChef API routes on the aiohttp application."""
    app["cyberchef"] = cyberchef
    app.router.add_get("/api/cyberchef/status", handle_cyberchef_status)
    app.router.add_get("/api/cyberchef/recipes", handle_cyberchef_recipes)
    app.router.add_post("/api/cyberchef/url", handle_cyberchef_url)
    logger.info("CyberChef API routes registered (3 endpoints)")
