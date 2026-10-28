"""
NetTap MAC Correlation API Routes

Registers endpoints for randomized MAC detection, behavioral fingerprinting,
merge suggestions, and device merging.

Endpoints:
    GET  /api/mac/randomized         Detected randomized MACs
    GET  /api/mac/fingerprint/{mac}  Behavioral fingerprint for a MAC
    GET  /api/mac/merge-suggestions  Merge candidates with confidence
    POST /api/mac/merge              Merge two devices
    GET  /api/mac/merge-history      Previous merges
    POST /api/mac/undo-merge         Undo a previous merge
"""

import logging
from datetime import datetime, timedelta, timezone

from aiohttp import web

from services.mac_correlator import MACCorrelator

logger = logging.getLogger("nettap.api.mac_correlation")

_DEFAULT_RANGE_HOURS = 24


def _parse_time_range(request: web.Request) -> tuple[str, str]:
    """Extract 'from' and 'to' query parameters as ISO timestamps."""
    now = datetime.now(timezone.utc)
    default_from = (now - timedelta(hours=_DEFAULT_RANGE_HOURS)).isoformat()
    default_to = now.isoformat()

    raw_from = request.query.get("from", "")
    raw_to = request.query.get("to", "")

    if raw_from:
        try:
            datetime.fromisoformat(raw_from.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raw_from = ""
    if raw_to:
        try:
            datetime.fromisoformat(raw_to.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raw_to = ""

    return (raw_from or default_from, raw_to or default_to)


async def handle_randomized_macs(request: web.Request) -> web.Response:
    """GET /api/mac/randomized?from=&to= — Detected randomized MACs."""
    from_ts, to_ts = _parse_time_range(request)
    correlator: MACCorrelator = request.app["mac_correlator"]

    try:
        macs = correlator.detect_randomized_macs(from_ts, to_ts)
    except Exception as exc:
        logger.error("Error detecting randomized MACs: %s", exc)
        return web.json_response(
            {"error": f"Failed to detect randomized MACs: {exc}"}, status=500
        )

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "count": len(macs),
        "randomized_macs": macs,
    })


async def handle_fingerprint(request: web.Request) -> web.Response:
    """GET /api/mac/fingerprint/{mac}?from=&to= — Behavioral fingerprint."""
    mac = request.match_info["mac"]
    from_ts, to_ts = _parse_time_range(request)
    correlator: MACCorrelator = request.app["mac_correlator"]

    try:
        fingerprint = correlator.get_behavioral_fingerprint(mac, from_ts, to_ts)
    except Exception as exc:
        logger.error("Error building fingerprint for %s: %s", mac, exc)
        return web.json_response(
            {"error": f"Failed to build fingerprint: {exc}"}, status=500
        )

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "fingerprint": fingerprint,
    })


async def handle_merge_suggestions(request: web.Request) -> web.Response:
    """GET /api/mac/merge-suggestions?from=&to= — Merge candidates."""
    from_ts, to_ts = _parse_time_range(request)
    correlator: MACCorrelator = request.app["mac_correlator"]

    try:
        suggestions = correlator.suggest_merges(from_ts, to_ts)
    except Exception as exc:
        logger.error("Error generating merge suggestions: %s", exc)
        return web.json_response(
            {"error": f"Failed to generate merge suggestions: {exc}"},
            status=500,
        )

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "count": len(suggestions),
        "suggestions": suggestions,
    })


async def handle_merge(request: web.Request) -> web.Response:
    """POST /api/mac/merge — Merge two devices.

    Body: {"mac_randomized": "...", "mac_real": "..."}
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Invalid JSON body"}, status=400
        )

    mac_randomized = body.get("mac_randomized", "").strip()
    mac_real = body.get("mac_real", "").strip()

    if not mac_randomized or not mac_real:
        return web.json_response(
            {"error": "Both mac_randomized and mac_real are required"},
            status=400,
        )

    correlator: MACCorrelator = request.app["mac_correlator"]

    try:
        record = correlator.merge_devices(mac_randomized, mac_real)
    except Exception as exc:
        logger.error("Error merging devices: %s", exc)
        return web.json_response(
            {"error": f"Failed to merge devices: {exc}"}, status=500
        )

    return web.json_response({
        "result": "merged",
        "merge": record,
    })


async def handle_merge_history(request: web.Request) -> web.Response:
    """GET /api/mac/merge-history — Previous merges."""
    correlator: MACCorrelator = request.app["mac_correlator"]
    history = correlator.get_merge_history()

    return web.json_response({
        "count": len(history),
        "merges": history,
    })


async def handle_undo_merge(request: web.Request) -> web.Response:
    """POST /api/mac/undo-merge — Undo a previous merge.

    Body: {"merge_id": "..."}
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Invalid JSON body"}, status=400
        )

    merge_id = body.get("merge_id", "").strip()
    if not merge_id:
        return web.json_response(
            {"error": "merge_id is required"}, status=400
        )

    correlator: MACCorrelator = request.app["mac_correlator"]
    success = correlator.undo_merge(merge_id)

    if not success:
        return web.json_response(
            {"error": f"Merge {merge_id} not found"}, status=404
        )

    return web.json_response({"result": "undone", "merge_id": merge_id})


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_mac_correlation_routes(
    app: web.Application, correlator: MACCorrelator
) -> None:
    """Register MAC correlation API routes."""
    app["mac_correlator"] = correlator

    app.router.add_get("/api/mac/randomized", handle_randomized_macs)
    app.router.add_get("/api/mac/fingerprint/{mac}", handle_fingerprint)
    app.router.add_get("/api/mac/merge-suggestions", handle_merge_suggestions)
    app.router.add_post("/api/mac/merge", handle_merge)
    app.router.add_get("/api/mac/merge-history", handle_merge_history)
    app.router.add_post("/api/mac/undo-merge", handle_undo_merge)

    logger.info("MAC correlation API routes registered (6 endpoints)")
