"""
NetTap watched devices route (NET-331, plan §2.6).

    GET /api/devices/watched  → {"check": {...}, "devices": [{mac, name, after_min, state,
                                                               seen_at, since}]}

The list is the details store's watches merged with the watched-devices job's state, read off
the loop. A damaged details store is a fixed 503; an unreadable state file is check.error.

Also builds the job's capture-health reader: the capture manager lives on the app loop, so the
job thread asks it there, within HEALTH_TIMEOUT_S.
"""

import asyncio
import logging
from collections.abc import Callable

from aiohttp import web

from api.error_replies import public_json
from api.offload import run_blocking
from services.device_custom import StoreUnavailable
from services.watched_devices import WatchedDevices

logger = logging.getLogger("nettap.api.devices_watched")

HEALTH_TIMEOUT_S = 5
STORE_UNREADABLE = (
    "Watched devices can't be listed: the device details file is unreadable."
)


async def handle_watched(request: web.Request) -> web.Response:
    watcher: WatchedDevices = request.app["watched_devices"]
    try:
        body = await run_blocking(watcher.view)
    except StoreUnavailable as exc:
        logger.error("Watched devices list refused: %s", exc)
        return public_json({"error": STORE_UNREADABLE}, status=503)
    return web.json_response(body)


def capture_health_reader(app: web.Application) -> Callable[[], dict]:
    """A callable for the job thread: app["capture_manager"].get_health() as a dict.

    It runs on the app loop, captured at start-up. The manager is looked up at each call,
    since setup can replace it. Raises when the loop isn't running yet or the call takes
    longer than HEALTH_TIMEOUT_S (the job then skips with "mode").
    """
    loops: list[asyncio.AbstractEventLoop] = []

    async def keep_loop(_app: web.Application) -> None:
        loops.append(asyncio.get_running_loop())

    app.on_startup.append(keep_loop)

    def read() -> dict:
        if not loops:
            raise RuntimeError("the app loop hasn't started")
        future = asyncio.run_coroutine_threadsafe(
            app["capture_manager"].get_health(), loops[-1]
        )
        try:
            return future.result(HEALTH_TIMEOUT_S).to_dict()
        except TimeoutError:
            future.cancel()
            raise

    return read


def register_watched_devices_routes(
    app: web.Application, watcher: WatchedDevices
) -> None:
    app["watched_devices"] = watcher
    app.router.add_get("/api/devices/watched", handle_watched)
