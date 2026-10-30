"""
NetTap DHCP Gateway API Routes

Go-live endpoints for DHCP gateway capture mode. They act on the
DhcpGatewayManager stored at ``request.app["capture_manager"]`` and answer
409 when the configured capture mode is something else.

Endpoints (design doc 2026-10-30 §6.2):
    GET  /api/capture/dhcp/preflight  Checks that must pass before enabling
    POST /api/capture/dhcp/enable     Body {"confirm": true}; routing + DHCP on
    POST /api/capture/dhcp/disable    DHCP server off (routing stays)
    GET  /api/capture/dhcp/status     Routing / DHCP state, leases, issues

enable, disable and /api/setup/configure share one asyncio.Lock on the app,
so a mode switch can't run halfway through an enable.
"""

import asyncio
import logging

from aiohttp import web

from api.capture_control import restart_capture_containers
from services.capture_config import load_capture_config, write_env_file_if_changed
from services.dhcp_gateway import DhcpGatewayManager

logger = logging.getLogger("nettap.api.dhcp_gateway")

CAPTURE_LOCK_KEY = "capture_config_lock"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def ensure_capture_lock(app: web.Application) -> asyncio.Lock:
    """The lock shared by enable / disable / setup configure (created once)."""
    if CAPTURE_LOCK_KEY not in app:
        app[CAPTURE_LOCK_KEY] = asyncio.Lock()
    return app[CAPTURE_LOCK_KEY]


def _dhcp_manager(request: web.Request) -> DhcpGatewayManager | web.Response:
    """The DhcpGatewayManager, or a 409 response when another mode is configured."""
    cm = request.app.get("capture_manager")
    if isinstance(cm, DhcpGatewayManager):
        return cm
    mode = getattr(getattr(cm, "mode", None), "value", "unknown")
    return web.json_response(
        {
            "error": "DHCP gateway mode is not the configured capture mode "
            f"(current mode: {mode}). Choose it in the setup wizard first."
        },
        status=409,
    )


async def _apply_capture_env() -> dict:
    """Write capture.env from the saved config; restart capture only if it changed.

    A restart drops capture for a few seconds, so an unchanged file (the wizard
    already wrote it) skips it. Never raises: problems come back in "errors".
    """
    try:
        _, changed = write_env_file_if_changed(load_capture_config())
    except Exception as exc:
        logger.error("Could not write capture.env after enabling DHCP: %s", exc)
        return {"restarted": [], "errors": [f"Could not write capture.env: {exc}"]}
    if not changed:
        return {"restarted": [], "errors": []}
    return await restart_capture_containers()


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_dhcp_preflight(request: web.Request) -> web.Response:
    """GET /api/capture/dhcp/preflight — read-only checks before enabling."""
    mgr = _dhcp_manager(request)
    if isinstance(mgr, web.Response):
        return mgr
    try:
        return web.json_response(await mgr.preflight())
    except Exception as exc:
        logger.exception("DHCP gateway preflight failed")
        return web.json_response({"error": f"Preflight failed: {exc}"}, status=500)


async def handle_dhcp_enable(request: web.Request) -> web.Response:
    """POST /api/capture/dhcp/enable — body {"confirm": true}."""
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict) or body.get("confirm") is not True:
        return web.json_response(
            {"error": 'Enabling needs explicit confirmation: send {"confirm": true}.'},
            status=400,
        )

    async with ensure_capture_lock(request.app):
        # Read the manager under the lock: setup/configure may have swapped it
        mgr = _dhcp_manager(request)
        if isinstance(mgr, web.Response):
            return mgr
        try:
            ok, result = await mgr.enable()
        except Exception as exc:
            logger.exception("DHCP gateway enable raised")
            return web.json_response(
                {"error": f"Could not turn on DHCP gateway mode: {exc}"}, status=500
            )
        if not ok:
            # A refusal carries the failed checks; an apply failure doesn't
            status = 409 if "checks" in result else 500
            return web.json_response(result, status=status)
        capture_restart = await _apply_capture_env()
    return web.json_response({**result, "capture_restart": capture_restart})


async def handle_dhcp_disable(request: web.Request) -> web.Response:
    """POST /api/capture/dhcp/disable — stop the DHCP server, keep routing."""
    async with ensure_capture_lock(request.app):
        mgr = _dhcp_manager(request)
        if isinstance(mgr, web.Response):
            return mgr
        try:
            return web.json_response(await mgr.disable())
        except Exception as exc:
            logger.exception("DHCP gateway disable failed")
            return web.json_response(
                {"error": f"Could not turn off the DHCP server: {exc}"}, status=500
            )


async def handle_dhcp_status(request: web.Request) -> web.Response:
    """GET /api/capture/dhcp/status — routing / DHCP state, leases, issues."""
    mgr = _dhcp_manager(request)
    if isinstance(mgr, web.Response):
        return mgr
    try:
        return web.json_response(await mgr.status())
    except Exception as exc:
        logger.exception("DHCP gateway status failed")
        return web.json_response({"error": f"Status failed: {exc}"}, status=500)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_dhcp_gateway_routes(app: web.Application) -> None:
    """Register the DHCP gateway API routes and the shared capture lock."""
    ensure_capture_lock(app)
    app.router.add_get("/api/capture/dhcp/preflight", handle_dhcp_preflight)
    app.router.add_post("/api/capture/dhcp/enable", handle_dhcp_enable)
    app.router.add_post("/api/capture/dhcp/disable", handle_dhcp_disable)
    app.router.add_get("/api/capture/dhcp/status", handle_dhcp_status)
    logger.info("DHCP gateway API routes registered")
