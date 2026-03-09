"""
NetTap Backup API Routes

Registers endpoints for config export, import, and validation.

Endpoints:
    GET  /api/backup/export    Download config JSON
    POST /api/backup/import    Upload + validate + apply config
    POST /api/backup/validate  Validate without applying
"""

import logging

from aiohttp import web

from services.config_backup import ConfigBackup

logger = logging.getLogger("nettap.api.backup")


async def handle_export(request: web.Request) -> web.Response:
    """GET /api/backup/export — Download config JSON."""
    backup: ConfigBackup = request.app["config_backup"]

    try:
        config = backup.export_config()
    except Exception as exc:
        logger.error("Error exporting config: %s", exc)
        return web.json_response(
            {"error": f"Config export failed: {exc}"}, status=500
        )

    return web.json_response(config)


async def handle_import(request: web.Request) -> web.Response:
    """POST /api/backup/import — Upload + validate + apply config.

    Body: JSON config object (as exported by /api/backup/export).
    """
    try:
        data = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Invalid JSON body"}, status=400
        )

    backup: ConfigBackup = request.app["config_backup"]

    try:
        result = backup.import_config(data)
    except Exception as exc:
        logger.error("Error importing config: %s", exc)
        return web.json_response(
            {"error": f"Config import failed: {exc}"}, status=500
        )

    status = 200 if result["success"] else 400
    return web.json_response(result, status=status)


async def handle_validate(request: web.Request) -> web.Response:
    """POST /api/backup/validate — Validate without applying.

    Body: JSON config object.
    """
    try:
        data = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Invalid JSON body"}, status=400
        )

    backup: ConfigBackup = request.app["config_backup"]

    try:
        validation = backup.validate_import(data)
    except Exception as exc:
        logger.error("Error validating config: %s", exc)
        return web.json_response(
            {"error": f"Config validation failed: {exc}"}, status=500
        )

    return web.json_response(validation)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_backup_routes(
    app: web.Application, backup: ConfigBackup
) -> None:
    """Register backup API routes."""
    app["config_backup"] = backup

    app.router.add_get("/api/backup/export", handle_export)
    app.router.add_post("/api/backup/import", handle_import)
    app.router.add_post("/api/backup/validate", handle_validate)

    logger.info("Backup API routes registered (3 endpoints)")
