"""5xx replies without internals (release audit B-p, NET-229 / NET-237).

Many handlers answer a failure with ``{"error": f"...: {exc}"}`` or ``str(exc)``, so the browser saw
OpenSearch URLs, host:port pairs, Docker messages and exception reprs. Replies written for the user
are marked at the source with ``public_json`` and pass untouched. This middleware is the one place
that handles the rest:

- an unmarked JSON reply with status >= 500 (a message built from an exception) answers ``GENERIC``
  plus its bool, number and null fields; strings, lists and objects are dropped, and the original
  reply is logged;
- an unhandled exception is logged with its traceback and answers a JSON 500 with ``GENERIC``.

4xx replies (validation messages written for the user) and non-JSON replies pass untouched. A
hand-written 5xx message must use ``public_json``; ``tests/test_error_replies.py`` fails if it doesn't.
"""

from __future__ import annotations

import json
import logging

from aiohttp import web

logger = logging.getLogger("nettap.api")

GENERIC = "Something went wrong; the daemon log has the details."
_PUBLIC = "nettap_public"


def public_json(data, *, status: int = 200, headers=None) -> web.Response:
    """A JSON reply written for the user: the middleware never rewrites it, even on a 5xx."""
    response = web.json_response(data, status=status, headers=headers)
    response[_PUBLIC] = True
    return response


def _safe_body(payload: dict) -> dict:
    """GENERIC and the scalar fields: what an exception-built 5xx may show."""
    scalars = {
        key: value
        for key, value in payload.items()
        if key != "error" and (value is None or isinstance(value, (bool, int, float)))
    }
    return {**scalars, "error": GENERIC}


@web.middleware
async def safe_error_middleware(request: web.Request, handler) -> web.StreamResponse:
    try:
        response = await handler(request)
    except web.HTTPException:
        raise
    except Exception:
        logger.exception("%s %s -> unhandled error", request.method, request.path)
        return web.json_response({"error": GENERIC}, status=500)
    if (
        response.status < 500
        or not isinstance(response, web.Response)
        or response.get(_PUBLIC)
        or response.content_type != "application/json"
    ):
        return response
    try:
        payload = json.loads(response.body)
    except (TypeError, ValueError):
        return response
    if not isinstance(payload, dict):
        return response
    body = _safe_body(payload)
    if body != payload:
        logger.warning(
            "%s %s -> %d, reply cut to safe fields; it was: %s",
            request.method,
            request.path,
            response.status,
            json.dumps(payload)[:4000],
        )
        response.text = json.dumps(body)
    return response


# OLD CODE START — NET-229 follow-up: a global allowlist of strings turned deliberate 5xx replies
# (notification test, DHCP gateway, rule update, updates) into GENERIC; replies are marked at the
# source with public_json instead
# from __future__ import annotations
#
# import json
# import logging
# import re
#
# from aiohttp import web
#
# from api.certificates import _BIG, _SLOW, _UNAVAILABLE
# from api.certificates import _BUSY as _CERT_BUSY
# from api.drilldown_runner import _BROKEN, _BUSY, _SLOW as _DRILL_SLOW
# from api.offload import LOOKUPS_BUSY
# from services.packet_search import BUSY as PACKET_BUSY
# from services.packet_search import OOM
#
# logger = logging.getLogger("nettap.api")
#
# GENERIC = "Something went wrong; the daemon log has the details."
#
# # What packet_search._raise_unfinished puts in "{what} failed." and "{what} took longer than ..."
# _PACKET_JOBS = (
#     "Checking the filter",
#     "Listing fields",
#     "The search",
#     "Reading this packet",
#     "The download",
# )
#
# PLAIN_5XX = frozenset(
#     {
#         # daemon/api route literals
#         "The alert search was incomplete",
#         "The device search was incomplete",
#         "The protocol search was incomplete",
#         "Bridge manager not available",
#         "Couldn't save the location",
#         "Couldn't clear the location",
#         "Couldn't save the setting",
#         "Couldn't save the change: the device's storage failed.",
#         "Device names and pictures can't be saved: their file is unreadable.",
#         "Logstash monitoring API unreachable",
#         "Retention config manager not initialised",
#         "Couldn't read your rules.",
#         "Couldn't save your rules. Check the daemon log.",
#         "Couldn't change the ET Pro code. Nothing was changed.",
#         # module constants
#         _BUSY,
#         _DRILL_SLOW,
#         _BROKEN,
#         _UNAVAILABLE,
#         _CERT_BUSY,
#         _SLOW,
#         _BIG,
#         LOOKUPS_BUSY,
#         LOOKUP_FAILED["error"],  # api/geoip.py (NET-237)
#         PACKET_BUSY,
#         OOM,
#         # services/packet_search.py
#         "The packet reader printed too much.",
#         "The packet reader didn't stop in time.",
#         *(f"{job} failed." for job in _PACKET_JOBS),
#         *(
#             f"{job} took longer than the time allowed. Try again."
#             for job in _PACKET_JOBS
#         ),
#         # services/suricata_rules.py live status (502 when Suricata can't be read)
#         "Suricata has no rules file yet.",
#         "Could not read Suricata's rule count.",
#         "Could not reach the Suricata container.",
#         "Could not read Suricata's rules.",
#     }
# )
#
# # api/home_location.py: its own reasons are plain words; anything with ':', '(', '/' or a quote
# # at a word start (another library's ValueError) doesn't match
# _PLAIN_5XX_PATTERN = re.compile(
#     r"Couldn't look up your WAN location: [A-Za-z0-9 ]+(?:'[a-z]+[A-Za-z0-9 ]*)*\. "
#     r"Enter the coordinates by hand\."
# )
#
#
# def is_plain(message: str) -> bool:
#     """True for a hand-written 5xx message that is safe to show as it is."""
#     return message in PLAIN_5XX or _PLAIN_5XX_PATTERN.fullmatch(message) is not None
#
#
# def _safe_body(payload: dict) -> dict:
#     """The reply the client may see: a known message (or GENERIC) and the scalar fields."""
#     body = {
#         key: value
#         for key, value in payload.items()
#         if key != "error" and (value is None or isinstance(value, (bool, int, float)))
#     }
#     if "error" in payload or body != payload:
#         message = payload.get("error")
#         body["error"] = (
#             message if isinstance(message, str) and is_plain(message) else GENERIC
#         )
#     return body
#
#
# @web.middleware
# async def safe_error_middleware(request: web.Request, handler) -> web.StreamResponse:
#     response = await handler(request)
#     if (
#         response.status < 500
#         or not isinstance(response, web.Response)
#         or response.content_type != "application/json"
#     ):
#         return response
#     try:
#         payload = json.loads(response.body)
#     except (TypeError, ValueError):
#         return response
#     if not isinstance(payload, dict):
#         return response
#     body = _safe_body(payload)
#     if body != payload:
#         logger.warning(
#             "%s %s -> %d, reply cut to safe fields; it was: %s",
#             request.method,
#             request.path,
#             response.status,
#             json.dumps(payload)[:4000],
#         )
#         response.text = json.dumps(body)
#     return response
# OLD CODE END
