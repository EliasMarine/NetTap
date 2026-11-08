"""
NetTap Threat Intelligence API Routes

Registers endpoints for the /threats page: unified threat report,
beaconing detection, lateral movement, DNS anomalies, and
auto-investigations.
"""

import asyncio
import functools
import json
import logging
import os
from datetime import timedelta

from aiohttp import web

from api.offload import in_thread, run_blocking
from api.time_range import parse_time_range
from services.beacon_snapshots import WINDOWS as SNAPSHOT_WINDOWS
from services.beacon_snapshots import BeaconSnapshots
from storage.manager import StorageManager

logger = logging.getLogger("nettap.api.threats")

_DEFAULT_RANGE_HOURS = 24
NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")


def _parse_time_range(request: web.Request) -> tuple[str, str]:
    """'from'/'to' as ISO timestamps, defaulting to the last 24 hours; unreadable is a 400."""
    # OLD CODE START — 2026-11-02: an unreadable from/to (e.g. now-5m) silently became the
    # default window, so the Infrastructure page divided 24 h of events by 5 min
    # now = datetime.now(timezone.utc)
    # default_from = (now - timedelta(hours=_DEFAULT_RANGE_HOURS)).isoformat()
    # default_to = now.isoformat()
    # raw_from = request.query.get("from", "")
    # raw_to = request.query.get("to", "")
    # if raw_from:
    #     try:
    #         datetime.fromisoformat(raw_from.replace("Z", "+00:00"))
    #     except (ValueError, TypeError):
    #         raw_from = ""
    # if raw_to:
    #     try:
    #         datetime.fromisoformat(raw_to.replace("Z", "+00:00"))
    #     except (ValueError, TypeError):
    #         raw_to = ""
    # return (raw_from or default_from, raw_to or default_to)
    # OLD CODE END
    return parse_time_range(request, timedelta(hours=_DEFAULT_RANGE_HOURS))


def _get_client(request: web.Request):
    storage: StorageManager = request.app["storage"]
    return storage._client


def _snapshot_param(request: web.Request) -> str | None:
    """The `snapshot` window asked for (24h, 7d or 30d), or None; any other value is a 400.

    An explicit from/to is always computed live, so it wins over `snapshot`.
    """
    window = request.query.get("snapshot")
    if not window:
        return None
    if window not in SNAPSHOT_WINDOWS:
        raise web.HTTPBadRequest(
            text=json.dumps(
                {"error": f"snapshot must be one of {', '.join(SNAPSHOT_WINDOWS)}"}
            ),
            content_type="application/json",
        )
    if request.query.get("from") or request.query.get("to"):
        return None
    return window


def _snapshot_window(request: web.Request) -> tuple[str | None, tuple[str, str]]:
    """(snapshot window or None, the report's from/to). Without from/to a snapshot window is
    the last 24h/7d/30d up to now; the store may be off (NETTAP_BEACON_BACKGROUND=0)."""
    window = _snapshot_param(request)
    span = SNAPSHOT_WINDOWS[window] if window else timedelta(hours=_DEFAULT_RANGE_HOURS)
    return window, parse_time_range(request, span)


async def handle_threat_report(request: web.Request) -> web.Response:
    """GET /api/threats/report?from=&to= or ?snapshot=24h|7d|30d — Unified threat report.

    With `snapshot=` (NET-192 PR 3) beaconing comes from the background scan, with its state in
    `beaconing_snapshot`; the other checks run live over the same window.
    """
    # OLD CODE START — NET-192 PR 3: ?snapshot= reads beaconing from the background scan
    # from_ts, to_ts = _parse_time_range(request)
    # OLD CODE END
    window, (from_ts, to_ts) = _snapshot_window(request)
    store: BeaconSnapshots | None = request.app.get("beacon_snapshots")
    snapshot = store is not None and window is not None
    client = _get_client(request)
    excluded_ips_list = request.app.get("excluded_ips", [])

    from api.drilldown_runner import lan_cidrs
    from services.investigation import generate_threat_report

    # Rows and state from one moment: a scan that publishes during the multi-second report
    # must not label the earlier (empty) rows "ready"
    beacons = store.beacons(window) if snapshot else None
    snap = store.snapshot(window) if snapshot else None
    try:
        # OLD CODE START — #139: the report's OpenSearch calls block, so on the request loop
        # they held up every other request for 8-13 s (the top bar said "Can't reach NetTap")
        # report = await generate_threat_report(
        #     client, from_ts, to_ts, excluded_ips=excluded_ips_list
        # )
        # OLD CODE END
        # OLD CODE START — PR #200 review: asyncio's default pool, which must stay free for
        # the drill-downs and health checks
        # report = await asyncio.to_thread(
        #     asyncio.run,
        #     generate_threat_report(
        #         client, from_ts, to_ts, excluded_ips=excluded_ips_list
        #     ),
        # )
        # OLD CODE END
        # OLD CODE START — NET-192 PR 3: beaconing from the background scan with ?snapshot=
        # report = await run_blocking(
        #     asyncio.run,
        #     generate_threat_report(
        #         client, from_ts, to_ts, excluded_ips=excluded_ips_list
        #     ),
        # )
        # OLD CODE END
        report = await run_blocking(
            asyncio.run,
            generate_threat_report(
                client,
                from_ts,
                to_ts,
                excluded_ips=excluded_ips_list,
                beaconing=beacons,
                lan_cidrs=lan_cidrs(request.app),
            ),
        )
    except Exception as exc:
        logger.error("Threat report generation failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    if snap is not None:
        report = {**report, "beaconing_snapshot": snap}
    return web.json_response({"from": from_ts, "to": to_ts, **report})


async def handle_beaconing(request: web.Request) -> web.Response:
    """GET /api/threats/beaconing?from=&to= or ?snapshot=24h|7d|30d (the background scan)."""
    # OLD CODE START — NET-192 PR 3: ?snapshot= answers from the background scan
    # from_ts, to_ts = _parse_time_range(request)
    # OLD CODE END
    window, (from_ts, to_ts) = _snapshot_window(request)
    store: BeaconSnapshots | None = request.app.get("beacon_snapshots")
    if store is not None and window is not None:
        snap = store.snapshot(window)
        beacons = store.beacons(window)
        return web.json_response(
            {
                "from": snap["from"],
                "to": snap["to"],
                "beacons": beacons,
                "total": len(beacons),
                # only a complete scan is ever published
                "complete": snap["last_success_at"] is not None,
                "beaconing_snapshot": snap,
            }
        )
    client = _get_client(request)
    excluded_ips_list = request.app.get("excluded_ips", [])

    from services.threat_detection import detect_beaconing

    try:
        # OLD CODE START — #139: 5-6 s of blocking OpenSearch calls on the request loop
        # beacons, complete = detect_beaconing(
        #     client, from_ts, to_ts, excluded_ips=excluded_ips_list
        # )
        # OLD CODE END
        # OLD CODE START — PR #200 review: asyncio's default pool, which must stay free for
        # the drill-downs and health checks
        # beacons, complete = await asyncio.to_thread(
        #     detect_beaconing, client, from_ts, to_ts, excluded_ips=excluded_ips_list
        # )
        # OLD CODE END
        beacons, complete = await run_blocking(
            functools.partial(
                detect_beaconing, client, from_ts, to_ts, excluded_ips=excluded_ips_list
            )
        )
    except Exception as exc:
        logger.error("Beaconing detection failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "beacons": beacons,
            "total": len(beacons),
            "complete": complete,
        }
    )


@in_thread
def handle_lateral_movement(request: web.Request) -> web.Response:
    """GET /api/threats/lateral?from=&to="""
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)
    excluded_ips_list = request.app.get("excluded_ips", [])

    from services.threat_detection import detect_lateral_movement

    try:
        movements, complete = detect_lateral_movement(
            client, from_ts, to_ts, excluded_ips=excluded_ips_list
        )
    except Exception as exc:
        logger.error("Lateral movement detection failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "movements": movements,
            "total": len(movements),
            "complete": complete,
        }
    )


@in_thread
def handle_dns_anomalies(request: web.Request) -> web.Response:
    """GET /api/threats/dns-anomalies?from=&to="""
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)
    excluded_ips_list = request.app.get("excluded_ips", [])

    from services.threat_detection import analyze_dns_anomalies

    try:
        anomalies = analyze_dns_anomalies(
            client, from_ts, to_ts, excluded_ips=excluded_ips_list
        )
    except Exception as exc:
        logger.error("DNS anomaly analysis failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response({"from": from_ts, "to": to_ts, **anomalies})


@in_thread
def handle_threat_intel(request: web.Request) -> web.Response:
    """GET /api/threats/intel?from=&to= — Populate TI from Suricata + return matches."""
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)
    excluded_ips_list = request.app.get("excluded_ips", [])

    from services.threat_intel import CACHE_LOCK, ThreatIntelService

    ti = ThreatIntelService()
    # OLD CODE START — PR 2 review: the lock was held through the OpenSearch scan (up to 30 s
    # a page), so the address drill-down waited on it with one of its two slots
    # # One load -> populate -> save at a time (another request, or the address drill-down)
    # with CACHE_LOCK:
    #     ti.load_cache()
    #
    #     # Bootstrap from Suricata data
    #     try:
    #         new_count = ti.populate_from_suricata(
    #             client, from_ts, to_ts, excluded_ips=excluded_ips_list
    #         )
    #     except Exception as exc:
    #         # load_cache already wrote back its purge, so the old entries stay gone (I7)
    #         logger.error("Threat intel refresh from Suricata failed: %s", exc)
    #         return web.json_response({"error": str(exc)}, status=500)
    # OLD CODE END
    # Bootstrap from Suricata data: the scan reads OpenSearch only, so no lock
    try:
        seen = ti.scan_suricata(client, from_ts, to_ts, excluded_ips=excluded_ips_list)
    except Exception as exc:
        # The load still writes back its purge, so the old entries stay gone (I7)
        with CACHE_LOCK:
            ti.load_cache()
        logger.error("Threat intel refresh from Suricata failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)
    # One load -> merge -> save at a time (another request, or the address drill-down)
    with CACHE_LOCK:
        ti.load_cache()
        new_count = ti.merge_seen(seen)
    # OLD CODE START — I7: every indicator ever cached, shown under the selected window's label
    # feeds = ti.get_all_matches()
    # OLD CODE END
    feeds = ti.get_all_matches(within=ti.seen_in_window)

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "new_indicators": new_count,
            "feeds": feeds,
            "total_indicators": sum(f["indicator_count"] for f in feeds.values()),
        }
    )


def register_threat_routes(
    app: web.Application, storage_manager: StorageManager
) -> None:
    app.router.add_get("/api/threats/report", handle_threat_report)
    app.router.add_get("/api/threats/beaconing", handle_beaconing)
    app.router.add_get("/api/threats/lateral", handle_lateral_movement)
    app.router.add_get("/api/threats/dns-anomalies", handle_dns_anomalies)
    app.router.add_get("/api/threats/intel", handle_threat_intel)
    logger.info("Threat Intelligence API routes registered (5 endpoints)")

    # NET-192 PR 3: beaconing for the 24h/7d/30d pills, refreshed in the background
    if os.environ.get("NETTAP_BEACON_BACKGROUND", "1") == "0":
        logger.info("Background beaconing is off; snapshot= requests are computed live")
        return
    from services.threat_detection import detect_beaconing

    store = BeaconSnapshots(
        functools.partial(detect_beaconing, storage_manager._client)
    )
    app["beacon_snapshots"] = store

    async def start(_app: web.Application) -> None:
        store.start()

    async def stop(_app: web.Application) -> None:
        await store.stop()

    app.on_startup.append(start)
    app.on_cleanup.append(stop)
