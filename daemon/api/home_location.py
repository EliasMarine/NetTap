"""
NetTap Home Location API Routes

Where the network is, for the Live page's globe (Settings › Network location).

Endpoints:
    GET    /api/settings/home-location             The saved location, or null
    PUT    /api/settings/home-location             Save {lat, lon, label}
    DELETE /api/settings/home-location             Forget it
    POST   /api/settings/home-location/wan-lookup  A suggestion from the WAN address; not saved
"""

import asyncio
import json
import logging
import unicodedata

import aiohttp
from aiohttp import web

from api.error_replies import public_json

from services.home_location import (
    MAX_LABEL,
    clear_home,
    load_home,
    parse_home,
    save_home,
)

logger = logging.getLogger("nettap.api.home_location")

# Answers with the caller's public address and its city, region, country and "lat,lon". The
# daemon has no GeoLite2 database, and the capture never sees the WAN address, so only an
# outside service can place it. Called only when the user presses the button.
WAN_LOOKUP_URL = "https://ipinfo.io/json"
_WAN_TIMEOUT_S = 5
_WAN_MAX_BYTES = 16 * 1024


async def fetch_wan_geo():
    """The outside service's JSON reply, size- and time-capped. Raises on any failure."""
    timeout = aiohttp.ClientTimeout(total=_WAN_TIMEOUT_S)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # No redirects: ipinfo answers /json directly, and the daemon (host network) must never be
        # sent on to a LAN address
        async with session.get(
            WAN_LOOKUP_URL,
            headers={"Accept": "application/json"},
            allow_redirects=False,
        ) as resp:
            if resp.status != 200:
                raise ValueError(f"the lookup service answered HTTP {resp.status}")
            body = b""
            async for chunk in resp.content.iter_chunked(4096):
                body += chunk
                if len(body) > _WAN_MAX_BYTES:
                    raise ValueError("the lookup service's reply was too large")
    return json.loads(body)


def wan_suggestion(data) -> dict:
    """{lat, lon, label} from the lookup service's reply, which is untrusted. ValueError if unusable."""
    if not isinstance(data, dict):
        raise ValueError("the reply wasn't a JSON object")
    loc = data.get("loc")
    if not isinstance(loc, str) or loc.count(",") != 1:
        raise ValueError("the reply had no location")
    try:
        lat, lon = (float(part) for part in loc.split(","))
    except ValueError:
        raise ValueError("the reply's location wasn't two numbers") from None
    # Drop control characters an odd reply might carry, rather than refuse the whole lookup; per
    # part, so a part that was only control characters leaves no stray comma
    parts = [
        "".join(ch for ch in p if not unicodedata.category(ch).startswith("C")).strip()
        for p in (data.get(k) for k in ("city", "region", "country"))
        if isinstance(p, str)
    ]
    label = ", ".join(p for p in parts if p)
    return parse_home({"lat": lat, "lon": lon, "label": label[:MAX_LABEL]})


def _plain_reason(exc: Exception) -> str:
    """Why the lookup failed, in words the Settings page can show."""
    if isinstance(exc, asyncio.TimeoutError):
        return f"the lookup service didn't answer within {_WAN_TIMEOUT_S} seconds"
    if isinstance(exc, aiohttp.ClientError):
        return "the lookup service couldn't be reached"
    if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
        return "the reply wasn't JSON"
    if isinstance(exc, ValueError):
        return str(exc)
    return "something unexpected went wrong"


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_get_home_location(request: web.Request) -> web.Response:
    """GET /api/settings/home-location → {"home": {lat, lon, label} | null}"""
    return web.json_response({"home": load_home()})


async def handle_put_home_location(request: web.Request) -> web.Response:
    """PUT /api/settings/home-location with {lat, lon, label}"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    try:
        home = parse_home(body)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    try:
        save_home(home)
    except OSError as exc:
        logger.error("Couldn't save the home location: %s", exc)
        return public_json({"error": "Couldn't save the location"}, status=500)
    return web.json_response({"home": home})


async def handle_delete_home_location(request: web.Request) -> web.Response:
    """DELETE /api/settings/home-location"""
    try:
        clear_home()
    except OSError as exc:
        logger.error("Couldn't clear the home location: %s", exc)
        return public_json({"error": "Couldn't clear the location"}, status=500)
    return web.json_response({"home": None})


async def handle_wan_lookup(request: web.Request) -> web.Response:
    """POST /api/settings/home-location/wan-lookup → {"suggestion": {lat, lon, label}}, not saved."""
    try:
        suggestion = wan_suggestion(await fetch_wan_geo())
    except Exception as exc:  # network, timeout, bad JSON, unusable reply: one message
        reason = _plain_reason(exc)
        # The type only: an undecodable reply's error carries the whole body, the public IP with it
        logger.warning(
            "WAN location lookup failed: %s (%s)", reason, type(exc).__name__
        )
        return public_json(
            {
                "error": f"Couldn't look up your WAN location: {reason}. "
                "Enter the coordinates by hand."
            },
            status=502,
        )
    return web.json_response({"suggestion": suggestion})


def register_home_location_routes(app: web.Application) -> None:
    app.router.add_get("/api/settings/home-location", handle_get_home_location)
    app.router.add_put("/api/settings/home-location", handle_put_home_location)
    app.router.add_delete("/api/settings/home-location", handle_delete_home_location)
    app.router.add_post("/api/settings/home-location/wan-lookup", handle_wan_lookup)
    logger.info("Home location API routes registered (4 endpoints)")
