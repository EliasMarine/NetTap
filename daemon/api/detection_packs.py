"""
NetTap Detection Packs API Routes

Registers REST endpoints for managing community detection rule packs.
Supports listing, installing, uninstalling, enabling, disabling,
checking for updates, and viewing statistics.
"""

import logging

from aiohttp import web

from services.detection_packs import DetectionPackManager

logger = logging.getLogger("nettap.api.detection_packs")


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

async def handle_list_packs(request: web.Request) -> web.Response:
    """GET /api/detection-packs

    List all installed detection packs.
    """
    manager: DetectionPackManager = request.app["detection_pack_manager"]
    packs = manager.list_packs()
    return web.json_response({
        "packs": [p.to_dict() for p in packs],
        "count": len(packs),
    })


async def handle_get_pack(request: web.Request) -> web.Response:
    """GET /api/detection-packs/{id}

    Get details for a specific detection pack.
    """
    manager: DetectionPackManager = request.app["detection_pack_manager"]
    pack_id = request.match_info["id"]

    pack = manager.get_pack(pack_id)
    if pack is None:
        return web.json_response(
            {"error": f"Detection pack '{pack_id}' not found"},
            status=404,
        )

    return web.json_response(pack.to_dict())


async def handle_install_pack(request: web.Request) -> web.Response:
    """POST /api/detection-packs/{id}/install

    Install a builtin detection pack.
    """
    manager: DetectionPackManager = request.app["detection_pack_manager"]
    pack_id = request.match_info["id"]

    try:
        pack = manager.install_pack(pack_id)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    return web.json_response(pack.to_dict(), status=201)


async def handle_uninstall_pack(request: web.Request) -> web.Response:
    """DELETE /api/detection-packs/{id}

    Uninstall a detection pack.
    """
    manager: DetectionPackManager = request.app["detection_pack_manager"]
    pack_id = request.match_info["id"]

    if manager.uninstall_pack(pack_id):
        return web.json_response({"result": "uninstalled", "id": pack_id})
    return web.json_response(
        {"error": f"Detection pack '{pack_id}' not found"},
        status=404,
    )


async def handle_enable_pack(request: web.Request) -> web.Response:
    """POST /api/detection-packs/{id}/enable

    Enable a detection pack (rules will be loaded by Suricata).
    """
    manager: DetectionPackManager = request.app["detection_pack_manager"]
    pack_id = request.match_info["id"]

    if manager.enable_pack(pack_id):
        pack = manager.get_pack(pack_id)
        return web.json_response(pack.to_dict())
    return web.json_response(
        {"error": f"Detection pack '{pack_id}' not found"},
        status=404,
    )


async def handle_disable_pack(request: web.Request) -> web.Response:
    """POST /api/detection-packs/{id}/disable

    Disable a detection pack without uninstalling.
    """
    manager: DetectionPackManager = request.app["detection_pack_manager"]
    pack_id = request.match_info["id"]

    if manager.disable_pack(pack_id):
        pack = manager.get_pack(pack_id)
        return web.json_response(pack.to_dict())
    return web.json_response(
        {"error": f"Detection pack '{pack_id}' not found"},
        status=404,
    )


async def handle_check_updates(request: web.Request) -> web.Response:
    """GET /api/detection-packs/updates

    Check which packs have updates available.
    """
    manager: DetectionPackManager = request.app["detection_pack_manager"]
    updates = manager.check_updates()
    return web.json_response({
        "updates": updates,
        "count": len(updates),
    })


async def handle_pack_stats(request: web.Request) -> web.Response:
    """GET /api/detection-packs/stats

    Return detection pack statistics.
    """
    manager: DetectionPackManager = request.app["detection_pack_manager"]
    return web.json_response(manager.get_stats())


async def handle_available_packs(request: web.Request) -> web.Response:
    """GET /api/detection-packs/available

    List all available builtin packs with installation status.
    """
    manager: DetectionPackManager = request.app["detection_pack_manager"]
    available = manager.get_available_packs()
    return web.json_response({
        "packs": available,
        "count": len(available),
    })


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_detection_pack_routes(
    app: web.Application,
    manager: DetectionPackManager,
) -> None:
    """Register all detection pack API routes on the given aiohttp application."""
    app["detection_pack_manager"] = manager

    # Static routes must be registered before parameterized routes
    app.router.add_get("/api/detection-packs/updates", handle_check_updates)
    app.router.add_get("/api/detection-packs/stats", handle_pack_stats)
    app.router.add_get("/api/detection-packs/available", handle_available_packs)

    app.router.add_get("/api/detection-packs", handle_list_packs)
    app.router.add_get("/api/detection-packs/{id}", handle_get_pack)
    app.router.add_post("/api/detection-packs/{id}/install", handle_install_pack)
    app.router.add_delete("/api/detection-packs/{id}", handle_uninstall_pack)
    app.router.add_post("/api/detection-packs/{id}/enable", handle_enable_pack)
    app.router.add_post("/api/detection-packs/{id}/disable", handle_disable_pack)
    logger.info("Detection pack API routes registered (9 endpoints)")
