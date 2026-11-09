"""
NetTap Live Connections API Routes

Registers endpoints for real-time connection monitoring.

Endpoints:
    GET /api/live/connections         Snapshot of active connections
    GET /api/live/rate                Current connection rate
    GET /api/live/dashboard           Consolidated dashboard payload (connections + aggs + alerts)
    GET /api/live/connection/detail   Detail for a specific src→dst pair (geo, alerts, history)
"""

import asyncio
import logging
import time

from aiohttp import web
from opensearchpy import OpenSearchException

from api.offload import in_thread, run_blocking
from services.geoip_service import GeoLookupFailed
from services.live_connections import LiveConnectionTracker

logger = logging.getLogger("nettap.api.live")

# A sample older than this is too stale to rate against; take a fresh pair instead
_MAX_SAMPLE_AGE_S = 60.0
_FIRST_SAMPLE_GAP_S = 1.0


class ThroughputSampler:
    """Bytes/sec on the capture interface, from its counters between two reads.

    Conn records credit a connection's bytes to its start time and arrive when it
    ends, so summing them under-reports live throughput (148 KB/s against a
    measured 301 KB/s on the G11). The NIC counters are the real line rate.
    """

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._last: tuple[float, int] | None = None

    async def _read(self, capture_manager) -> tuple[float, int]:
        stats = await capture_manager.get_stats()
        return self._clock(), stats.rx_bytes + stats.tx_bytes

    async def rate(self, capture_manager) -> float | None:
        """Bytes per second since the previous call, or None when unavailable."""
        if capture_manager is None:
            return None
        try:
            now = await self._read(capture_manager)
            last = self._last
            if last is None or now[0] - last[0] > _MAX_SAMPLE_AGE_S:
                await asyncio.sleep(_FIRST_SAMPLE_GAP_S)
                last, now = now, await self._read(capture_manager)
        except Exception as exc:
            logger.warning("Capture throughput unavailable: %s", exc)
            return None
        self._last = now
        elapsed, delta = now[0] - last[0], now[1] - last[1]
        if elapsed <= 0 or delta < 0:  # counter reset or wrap
            return None
        return delta / elapsed


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@in_thread
def handle_live_connections(request: web.Request) -> web.Response:
    """GET /api/live/connections?device=&proto=&country=&limit=100

    Returns a snapshot of recent active connections from the tracker.
    """
    tracker: LiveConnectionTracker = request.app["live_tracker"]

    device = request.query.get("device", "").strip() or None
    proto = request.query.get("proto", "").strip() or None
    country = request.query.get("country", "").strip() or None
    limit_str = request.query.get("limit", "100")
    try:
        limit = max(1, min(int(limit_str), 1000))
    except (ValueError, TypeError):
        limit = 100

    # Fetch fresh data from OpenSearch and update cache
    try:
        connections = tracker.fetch_from_opensearch(
            device=device,
            proto=proto,
            country=country,
            limit=limit,
        )
    except OpenSearchException as exc:
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    return web.json_response(
        {
            "connections": connections,
            "count": len(connections),
            "filters": {
                "device": device,
                "proto": proto,
                "country": country,
            },
        }
    )


async def handle_live_rate(request: web.Request) -> web.Response:
    """GET /api/live/rate

    Returns current connection rate (connections/sec over last 60s).
    """
    tracker: LiveConnectionTracker = request.app["live_tracker"]
    rate = tracker.get_connection_rate()
    return web.json_response(rate)


async def handle_live_dashboard(request: web.Request) -> web.Response:
    """GET /api/live/dashboard?device=&proto=&country=&limit=100

    Returns the consolidated live dashboard payload: connections with
    geo/ASN fields, stats ribbon data, protocol distribution, top talkers,
    and geo arcs for map visualization. Alert cross-referencing flags
    connections involved in Suricata alerts.

    GeoIP fallback: connections missing lat/lon are enriched via the
    GeoIPService (MaxMind / well-known IPs / OpenSearch lookup).
    """
    tracker: LiveConnectionTracker = request.app["live_tracker"]

    device = request.query.get("device", "").strip() or None
    proto = request.query.get("proto", "").strip() or None
    country = request.query.get("country", "").strip() or None
    limit_str = request.query.get("limit", "100")
    try:
        limit = max(1, min(int(limit_str), 1000))
    except (ValueError, TypeError):
        limit = 100

    # Exclude appliance IPs from live monitor queries
    excluded_ips = request.app.get("excluded_ips", [])

    geoip = request.app.get("geoip")

    def fetch_and_enrich() -> dict:
        data = tracker.fetch_dashboard_data(
            device=device,
            proto=proto,
            country=country,
            limit=limit,
            excluded_ips=excluded_ips,
            lan_filter=request.app.get("lan_filter"),
        )
        # GeoIP fallback enrichment: fill in missing lat/lon for connections
        # that OpenSearch didn't have geo data for (it can query OpenSearch too).
        if geoip:
            _enrich_connections_geoip(data.get("connections", []), geoip)
        return data

    # OLD CODE START — PR 2 (reliability): the GeoIP fallback ran on the loop after the fetch
    # # Run the synchronous OpenSearch queries in a thread executor to avoid
    # # blocking the event loop (matches server.py pattern).
    # loop = asyncio.get_running_loop()
    # try:
    #     dashboard = await loop.run_in_executor(
    #         None,
    #         lambda: tracker.fetch_dashboard_data(
    #             device=device,
    #             proto=proto,
    #             country=country,
    #             limit=limit,
    #             excluded_ips=excluded_ips,
    #             lan_filter=request.app.get("lan_filter"),
    #         ),
    #     )
    # except Exception as exc:
    #     logger.error("Error fetching live dashboard data: %s", exc)
    #     return web.json_response(
    #         {"error": f"Dashboard query failed: {exc}"}, status=502
    #     )
    #
    # # GeoIP fallback enrichment: fill in missing lat/lon for connections
    # # that OpenSearch didn't have geo data for.
    # geoip = request.app.get("geoip")
    # if geoip:
    #     _enrich_connections_geoip(dashboard.get("connections", []), geoip)
    # OLD CODE END
    try:
        dashboard = await run_blocking(fetch_and_enrich)
    except Exception as exc:
        logger.error("Error fetching live dashboard data: %s", exc)
        return web.json_response(
            {"error": f"Dashboard query failed: {exc}"}, status=502
        )

    sampler: ThroughputSampler = request.app["live_throughput"]
    # OLD CODE START — 2026-11-06 (O7): a filtered request (the Live page's side cards) took a
    # sample too, so the unfiltered poll rated the line over the milliseconds between the two
    # line_rate = await sampler.rate(request.app.get("capture_manager"))
    # OLD CODE END
    # The line rate can't be filtered; a filtered request keeps its own conn-record figure
    filtered = device or proto or country
    line_rate = (
        None if filtered else await sampler.rate(request.app.get("capture_manager"))
    )
    if line_rate is not None:
        stats = {
            **dashboard.get("stats", {}),
            "bandwidth_bytes_per_second": round(line_rate, 2),
        }
        dashboard = {**dashboard, "stats": stats}

    return web.json_response(dashboard)


@in_thread
def handle_live_connection_detail(request: web.Request) -> web.Response:
    """GET /api/live/connection/detail?src=&dst=&port=&geo=

    Returns detailed information for a specific source→destination pair:
    - geo: Full GeoIP + ASN info for `geo` (the row's geo_ip: src or dst; default dst)
    - alerts: Related Suricata alerts (last 24h)
    - history: Connection timeline with byte volumes (last 24h)
    """
    tracker: LiveConnectionTracker = request.app["live_tracker"]

    src = request.query.get("src", "").strip()
    dst = request.query.get("dst", "").strip()
    port_str = request.query.get("port", "").strip()

    if not src or not dst:
        return web.json_response(
            {"error": "Both 'src' and 'dst' query parameters are required"},
            status=400,
        )

    geo_ip = request.query.get("geo", "").strip() or dst
    if geo_ip not in (src, dst):
        return web.json_response(
            {"error": "'geo' must be the 'src' or the 'dst' address"},
            status=400,
        )

    dst_port: int | None = None
    if port_str:
        try:
            dst_port = int(port_str)
        except (ValueError, TypeError):
            pass

    # OLD CODE START — PR 2 (reliability): the GeoIP fallback below still ran on the loop
    # # Run queries in thread executor
    # loop = asyncio.get_running_loop()
    # try:
    #     detail = await loop.run_in_executor(
    #         None,
    #         lambda: tracker.fetch_connection_detail(
    #             src_ip=src,
    #             dst_ip=dst,
    #             dst_port=dst_port,
    #         ),
    #     )
    # OLD CODE END
    # The whole handler runs in a worker thread (OpenSearch queries, then the GeoIP fallback)
    # OLD CODE START — 2026-11-07 (live globe): always located the destination
    # try:
    #     detail = tracker.fetch_connection_detail(
    #         src_ip=src,
    #         dst_ip=dst,
    #         dst_port=dst_port,
    #     )
    # OLD CODE END
    try:
        detail = tracker.fetch_connection_detail(
            src_ip=src,
            dst_ip=dst,
            dst_port=dst_port,
            geo_ip=geo_ip,
        )
    except Exception as exc:
        logger.error("Error fetching connection detail: %s", exc)
        return web.json_response({"error": f"Detail query failed: {exc}"}, status=502)

    # GeoIP fallback: if OpenSearch had no geo data for the located end
    geo = detail.get("geo", {})
    if geo and not geo.get("lat") and not geo.get("lon"):
        geoip = request.app.get("geoip")
        if geoip:
            # OLD CODE START — 2026-11-07 (live globe): the destination when the detail had no ip
            # target_ip = geo.get("ip") or dst
            # OLD CODE END
            target_ip = geo.get("ip") or geo_ip
            # OLD CODE: result = geoip.lookup(target_ip) (NET-237: it raises when OpenSearch fails)
            try:
                result = geoip.lookup(target_ip)
            except GeoLookupFailed:
                result = None  # the detail stands without the fallback; the service logged it
            if result and not result.is_private:
                geo["country"] = result.country or geo.get("country", "")
                geo["country_code"] = result.country_code or geo.get("country_code", "")
                geo["city"] = result.city or geo.get("city", "")
                geo["lat"] = result.latitude
                geo["lon"] = result.longitude
                geo["asn"] = result.asn or geo.get("asn")
                geo["organization"] = result.organization or geo.get("organization", "")
                # NET-237: anycast has no one place, whichever path located it
                if result.anycast:
                    geo.update(anycast=True, city="", lat=None, lon=None)

    return web.json_response(detail)


# ---------------------------------------------------------------------------
# GeoIP fallback helper
# ---------------------------------------------------------------------------


def _enrich_connections_geoip(connections: list[dict], geoip) -> None:
    """Enrich connections that are missing geo coordinates via GeoIPService.

    Modifies connection dicts in-place. Only enriches connections where
    dest_lat/dest_lon are None (OpenSearch had no geo data). It looks up one end
    only, the row's own place (geo_ip), so the fields never mix two addresses;
    with no geo_ip, the source of an inbound row, else the destination.
    """
    for conn in connections:
        if conn.get("dest_lat") is not None and conn.get("dest_lon") is not None:
            continue

        # OLD CODE START — 2026-11-07 (live globe): always the destination, even when the row's
        # other fields came from its source
        # dest_ip = conn.get("dest_ip", "")
        # if not dest_ip:
        #     continue
        #
        # try:
        #     result = geoip.lookup(dest_ip)
        # except Exception:
        #     continue
        # OLD CODE END
        target = conn.get("geo_ip") or (
            conn.get("source_ip", "")
            if conn.get("direction") == "in"
            else conn.get("dest_ip", "")
        )
        if not target:
            continue

        try:
            result = geoip.lookup(target)
        except Exception:
            continue

        if result and not result.is_private:
            conn["geo_ip"] = target  # whatever is filled below belongs to this address
            if result.latitude is not None and result.longitude is not None:
                conn["dest_lat"] = result.latitude
                conn["dest_lon"] = result.longitude
            if result.city and not conn.get("dest_city"):
                conn["dest_city"] = result.city
            if result.country_code and not conn.get("country"):
                conn["country"] = result.country_code
            if result.country and not conn.get("country_name"):
                conn["country_name"] = result.country
            if result.asn and not conn.get("dest_asn"):
                conn["dest_asn"] = result.asn
            if result.organization and not conn.get("dest_org"):
                conn["dest_org"] = result.organization
            # NET-237: anycast has no one place, whichever path located it
            if result.anycast:
                conn.update(anycast=True, dest_city="", dest_lat=None, dest_lon=None)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_live_routes(
    app: web.Application,
    tracker: LiveConnectionTracker,
) -> None:
    """Register live connection API routes on the aiohttp application."""
    app["live_tracker"] = tracker
    app["live_throughput"] = ThroughputSampler()

    app.router.add_get("/api/live/connections", handle_live_connections)
    app.router.add_get("/api/live/rate", handle_live_rate)
    app.router.add_get("/api/live/dashboard", handle_live_dashboard)
    app.router.add_get("/api/live/connection/detail", handle_live_connection_detail)

    logger.info("Live connections API routes registered (4 endpoints)")
