"""
NetTap device customisation routes: the owner's own name and picture for a device (NET-200).

    PUT    /api/devices/registry/{mac}/name      {"name": str}            → {"device"}
    DELETE /api/devices/registry/{mac}/name                               → {"device"}
    PUT    /api/devices/registry/{mac}/picture   {"icon"} | {"image"}     → {"device"}
    DELETE /api/devices/registry/{mac}/picture                            → {"device"}
    GET    /api/devices/registry/{mac}/picture?v=<hash>                   → the photo bytes

A PUT needs the device in the registry; a DELETE works for any valid MAC, so an owner can
clean up after a device has left. Every reply is the device as the registry list shows it.
"""

import json
import logging
import re

from aiohttp import web
from opensearchpy import OpenSearchException

from api.offload import run_blocking
from services.device_custom import DeviceCustomStore, StoreUnavailable, normalize_mac
from services.device_registry import DeviceRegistry

logger = logging.getLogger("nettap.api.device_custom")

_HASH_RE = re.compile(r"^[0-9a-f]{16}$")
_PICTURE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "private, max-age=31536000, immutable",
    "Content-Security-Policy": "default-src 'none'",
}
_NO_STORE = {"Cache-Control": "no-store"}


class _NotFound(Exception):
    """The MAC isn't in the device registry."""


def _error(message: str, status: int, headers: dict | None = None) -> web.Response:
    return web.json_response({"error": message}, status=status, headers=headers)


def _apply(request: web.Request, mac: str, change, need_device: bool) -> dict:
    """Run `change(store, mac)` and return the device reply. Runs on the route pool.

    The device is read once, before the change, so a saved change never answers with an error.
    """
    registry: DeviceRegistry = request.app["device_registry"]
    store: DeviceCustomStore = request.app["device_custom"]
    try:
        device = registry.get_device(mac)
    except OpenSearchException:
        if need_device:
            raise
        device = None  # clearing works while OpenSearch is down
    if need_device and device is None:
        raise _NotFound()
    change(store, mac)
    return registry.with_names(device or {"mac": mac, "ips": [], "hostnames": []})


async def _run(request: web.Request, change, need_device: bool) -> web.Response:
    """The shared reply logic: MAC check, the change, and every failure as plain English."""
    try:
        mac = normalize_mac(request.match_info["mac"])
    except ValueError as exc:
        return _error(str(exc), 400)
    try:
        device = await run_blocking(_apply, request, mac, change, need_device)
    except _NotFound:
        return _error(f"Device not found: {mac}", 404)
    except ValueError as exc:
        return _error(str(exc), 400)
    except StoreUnavailable as exc:
        logger.error("Device customisation for %s refused: %s", mac, exc)
        return _error(
            "Device names and pictures can't be saved: their file is unreadable.", 503
        )
    except OpenSearchException as exc:
        logger.error("OpenSearch error customising %s: %s", mac, exc)
        return _error(f"OpenSearch query failed: {exc}", 502)
    except OSError as exc:
        logger.error("Couldn't save the customisation for %s: %s", mac, exc)
        return _error("Couldn't save the change: the device's storage failed.", 500)
    return web.json_response({"device": device})


async def _body(request: web.Request) -> dict:
    """The JSON object body, or ValueError."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("The request body must be JSON.") from None
    if not isinstance(body, dict):
        raise ValueError("The request body must be a JSON object.")
    return body


async def handle_set_name(request: web.Request) -> web.Response:
    try:
        name = (await _body(request)).get("name")
    except ValueError as exc:
        return _error(str(exc), 400)
    return await _run(request, lambda store, mac: store.set_name(mac, name), True)


async def handle_clear_name(request: web.Request) -> web.Response:
    return await _run(request, lambda store, mac: store.clear_name(mac), False)


async def handle_set_picture(request: web.Request) -> web.Response:
    try:
        body = await _body(request)
    except ValueError as exc:
        return _error(str(exc), 400)
    keys = set(body) & {"icon", "image"}
    if len(keys) != 1 or len(body) != 1:
        return _error('Send exactly one of "icon" or "image".', 400)
    if "icon" in body:
        icon = body["icon"]
        return await _run(request, lambda store, mac: store.set_icon(mac, icon), True)
    image = body["image"]
    return await _run(request, lambda store, mac: store.set_photo(mac, image), True)


async def handle_clear_picture(request: web.Request) -> web.Response:
    return await _run(request, lambda store, mac: store.clear_picture(mac), False)


async def handle_get_picture(request: web.Request) -> web.Response:
    """The photo, only under its own ?v=<hash>; anything else is a 404 nobody may cache."""
    store: DeviceCustomStore = request.app["device_custom"]
    try:
        mac = normalize_mac(request.match_info["mac"])
    except ValueError as exc:
        return _error(str(exc), 400, _NO_STORE)
    wanted = request.query.get("v", "")
    if not _HASH_RE.match(wanted):
        return _error("Picture version missing or malformed.", 404, _NO_STORE)
    got = await run_blocking(store.photo, mac)
    if got is None or got[2] != wanted:
        return _error("No such picture.", 404, _NO_STORE)
    data, mime, _ = got
    return web.Response(body=data, content_type=mime, headers=_PICTURE_HEADERS)


def register_device_custom_routes(
    app: web.Application, store: DeviceCustomStore
) -> None:
    """Register the owner's name and picture routes (needs app["device_registry"])."""
    app["device_custom"] = store
    base = "/api/devices/registry/{mac}"
    app.router.add_put(f"{base}/name", handle_set_name)
    app.router.add_delete(f"{base}/name", handle_clear_name)
    app.router.add_put(f"{base}/picture", handle_set_picture)
    app.router.add_delete(f"{base}/picture", handle_clear_picture)
    app.router.add_get(f"{base}/picture", handle_get_picture)
