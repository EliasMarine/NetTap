"""
NetTap Daemon HTTP API Server

Provides aiohttp-based REST endpoints for storage status, SMART health,
ILM policy management, and system health checks. Designed for LAN-only
access from the NetTap web dashboard.

Endpoints:
    GET  /api/health             Liveness check
    GET  /api/storage/status     Full storage status
    GET  /api/storage/retention  Retention config only
    POST /api/storage/prune      Trigger manual prune cycle
    GET  /api/smart/health       SMART drive health
    GET  /api/indices            OpenSearch index listing
    GET  /api/system/health      Combined system health
    POST /api/ilm/apply          Apply ILM policies
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from aiohttp import web

from storage.manager import StorageManager
from smart.monitor import SmartMonitor
from storage.ilm import apply_ilm_policies
from api.tshark import register_tshark_routes
from api.cyberchef import register_cyberchef_routes
from api.traffic import register_traffic_routes
from api.alerts import register_alert_routes
from api.devices import register_device_routes
from api.geoip import register_geoip_routes
from api.risk import register_risk_routes
from api.baseline import register_baseline_routes
from api.health_monitor import register_health_monitor_routes
from api.investigations import register_investigation_routes
from api.settings import register_settings_routes
from api.search import register_search_routes
from api.detection_packs import register_detection_pack_routes
from api.reports import register_report_routes
from services.tshark_service import TSharkService
from services.cyberchef_service import CyberChefService
from services.geoip_service import GeoIPService
from services.risk_scoring import RiskScorer
from services.device_baseline import DeviceBaseline
from services.internet_health import InternetHealthMonitor
from services.investigation_store import InvestigationStore
from services.nl_search import NLSearchParser
from services.detection_packs import DetectionPackManager
from services.report_generator import ReportGenerator

logger = logging.getLogger("nettap.api")


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

@web.middleware
async def cors_middleware(request: web.Request, handler) -> web.StreamResponse:
    """Add CORS headers to every response for LAN-only dashboard access.

    Allows all origins since the appliance runs on a private network
    segment and the dashboard may be accessed from any local IP.
    """
    # Handle preflight OPTIONS requests
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            response = exc

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Accept"
    response.headers["Access-Control-Max-Age"] = "3600"

    return response


@web.middleware
async def logging_middleware(request: web.Request, handler) -> web.StreamResponse:
    """Log each request with method, path, status code, and duration."""
    start = time.monotonic()
    try:
        response = await handler(request)
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "%s %s -> %d (%.1fms)",
            request.method,
            request.path,
            response.status,
            duration_ms,
        )
        return response
    except web.HTTPException as exc:
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "%s %s -> %d (%.1fms)",
            request.method,
            request.path,
            exc.status,
            duration_ms,
        )
        raise
    except Exception:
        duration_ms = (time.monotonic() - start) * 1000
        logger.exception(
            "%s %s -> 500 (%.1fms)",
            request.method,
            request.path,
            duration_ms,
        )
        raise


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

async def handle_health(request: web.Request) -> web.Response:
    """GET /api/health -- Simple liveness check."""
    start_time: float = request.app["start_time"]
    uptime = time.monotonic() - start_time
    return web.json_response({
        "status": "ok",
        "uptime": round(uptime, 2),
    })


async def handle_storage_status(request: web.Request) -> web.Response:
    """GET /api/storage/status -- Full storage status from StorageManager."""
    try:
        storage: StorageManager = request.app["storage"]
        status = storage.get_status()
        return web.json_response(status)
    except Exception as exc:
        logger.exception("Error fetching storage status")
        return web.json_response(
            {"error": f"Failed to fetch storage status: {exc}"},
            status=500,
        )


async def handle_storage_retention(request: web.Request) -> web.Response:
    """GET /api/storage/retention -- Retention configuration only."""
    try:
        storage: StorageManager = request.app["storage"]
        status = storage.get_status()
        return web.json_response(status["retention"])
    except Exception as exc:
        logger.exception("Error fetching retention config")
        return web.json_response(
            {"error": f"Failed to fetch retention config: {exc}"},
            status=500,
        )


async def handle_storage_prune(request: web.Request) -> web.Response:
    """POST /api/storage/prune -- Trigger a manual prune/maintenance cycle."""
    try:
        storage: StorageManager = request.app["storage"]
        # Run the synchronous run_cycle in a thread to avoid blocking the
        # event loop (it performs disk I/O and OpenSearch HTTP calls).
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, storage.run_cycle)
        # Return current status after the prune cycle completes
        status = storage.get_status()
        return web.json_response({
            "result": "prune_cycle_complete",
            "storage_status": status,
        })
    except Exception as exc:
        logger.exception("Error during manual prune cycle")
        return web.json_response(
            {"error": f"Prune cycle failed: {exc}"},
            status=500,
        )


async def handle_smart_health(request: web.Request) -> web.Response:
    """GET /api/smart/health -- SMART drive health status."""
    try:
        smart: SmartMonitor = request.app["smart"]
        # Run the synchronous get_status in a thread (it shells out to smartctl)
        loop = asyncio.get_running_loop()
        status = await loop.run_in_executor(None, smart.get_status)
        return web.json_response(status)
    except Exception as exc:
        logger.exception("Error fetching SMART health")
        return web.json_response(
            {"error": f"Failed to fetch SMART health: {exc}"},
            status=500,
        )


async def handle_indices(request: web.Request) -> web.Response:
    """GET /api/indices -- List all tracked OpenSearch indices."""
    try:
        storage: StorageManager = request.app["storage"]
        loop = asyncio.get_running_loop()
        indices = await loop.run_in_executor(None, storage.list_indices)
        # Convert datetime objects to ISO strings for JSON serialization
        serializable = []
        for idx in indices:
            entry = dict(idx)
            parsed_date = entry.get("parsed_date")
            if parsed_date is not None:
                entry["parsed_date"] = parsed_date.isoformat()
            else:
                entry["parsed_date"] = None
            serializable.append(entry)
        return web.json_response({"indices": serializable, "count": len(serializable)})
    except Exception as exc:
        logger.exception("Error listing indices")
        return web.json_response(
            {"error": f"Failed to list indices: {exc}"},
            status=500,
        )


async def handle_system_health(request: web.Request) -> web.Response:
    """GET /api/system/health -- Combined system health check.

    Aggregates: daemon uptime, storage status, SMART health, and
    OpenSearch reachability into a single response.
    """
    start_time: float = request.app["start_time"]
    uptime = time.monotonic() - start_time
    opensearch_url: str = request.app["opensearch_url"]

    result: dict = {
        "uptime": round(uptime, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "storage": None,
        "smart": None,
        "opensearch_reachable": False,
        "healthy": True,  # Assume healthy until proven otherwise
    }

    # Storage status
    try:
        storage: StorageManager = request.app["storage"]
        loop = asyncio.get_running_loop()
        result["storage"] = await loop.run_in_executor(None, storage.get_status)
    except Exception as exc:
        logger.warning("System health: storage status unavailable: %s", exc)
        result["storage"] = {"error": str(exc)}
        result["healthy"] = False

    # SMART health
    try:
        smart: SmartMonitor = request.app["smart"]
        loop = asyncio.get_running_loop()
        smart_status = await loop.run_in_executor(None, smart.get_status)
        result["smart"] = smart_status
        if not smart_status.get("healthy", True):
            result["healthy"] = False
    except Exception as exc:
        logger.warning("System health: SMART status unavailable: %s", exc)
        result["smart"] = {"error": str(exc)}
        result["healthy"] = False

    # OpenSearch reachability
    try:
        storage_mgr: StorageManager = request.app["storage"]
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, storage_mgr._client.info)
        result["opensearch_reachable"] = True
    except Exception as exc:
        logger.warning("System health: OpenSearch unreachable: %s", exc)
        result["opensearch_reachable"] = False
        result["healthy"] = False

    return web.json_response(result)


async def handle_ilm_apply(request: web.Request) -> web.Response:
    """POST /api/ilm/apply -- Apply ILM policies to OpenSearch."""
    try:
        opensearch_url: str = request.app["opensearch_url"]
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None, apply_ilm_policies, opensearch_url
        )
        return web.json_response({
            "result": "ilm_policies_applied",
            "policies": results,
        })
    except Exception as exc:
        logger.exception("Error applying ILM policies")
        return web.json_response(
            {"error": f"Failed to apply ILM policies: {exc}"},
            status=500,
        )


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app(
    storage: StorageManager,
    smart: SmartMonitor,
    opensearch_url: str,
) -> web.Application:
    """Create and configure the aiohttp web application.

    Stores subsystem references in the app dict so route handlers can
    access them via ``request.app["storage"]`` etc.

    Args:
        storage: The StorageManager instance for disk/index operations.
        smart: The SmartMonitor instance for drive health checks.
        opensearch_url: Base URL of the OpenSearch cluster.

    Returns:
        Configured aiohttp.web.Application ready to be served.
    """
    app = web.Application(middlewares=[cors_middleware, logging_middleware])

    # Store subsystem references for handler access
    app["storage"] = storage
    app["smart"] = smart
    app["opensearch_url"] = opensearch_url
    app["start_time"] = time.monotonic()

    # Register routes
    app.router.add_get("/api/health", handle_health)
    app.router.add_get("/api/storage/status", handle_storage_status)
    app.router.add_get("/api/storage/retention", handle_storage_retention)
    app.router.add_post("/api/storage/prune", handle_storage_prune)
    app.router.add_get("/api/smart/health", handle_smart_health)
    app.router.add_get("/api/indices", handle_indices)
    app.router.add_get("/api/system/health", handle_system_health)
    app.router.add_post("/api/ilm/apply", handle_ilm_apply)

    # TShark integration (containerized packet analysis)
    pcap_dir = os.environ.get("PCAP_DIR", "/opt/nettap/pcap")
    tshark_service = TSharkService(pcap_base_dir=pcap_dir)
    register_tshark_routes(app, tshark_service)

    # CyberChef integration (containerized data analysis)
    cyberchef_url = os.environ.get("CYBERCHEF_URL", "http://nettap-cyberchef:8443")
    cyberchef_service = CyberChefService(base_url=cyberchef_url)
    register_cyberchef_routes(app, cyberchef_service)

    # Traffic analysis (OpenSearch zeek-* queries)
    register_traffic_routes(app, storage)

    # Alert management (OpenSearch suricata-* queries)
    register_alert_routes(app, storage)

    # Device inventory (OpenSearch zeek-*/suricata-* queries + fingerprinting)
    register_device_routes(app, storage)

    # GeoIP lookup (MaxMind GeoLite2 + fallback)
    geoip_db = os.environ.get("GEOIP_DB_PATH", "/opt/nettap/data/GeoLite2-City.mmdb")
    geoip_service = GeoIPService(db_path=geoip_db)
    register_geoip_routes(app, geoip_service)

    # Risk scoring (per-device 0-100 risk scores from telemetry)
    risk_scorer = RiskScorer()
    register_risk_routes(app, risk_scorer, storage)

    # Device baseline (known-device tracking + new device alerts)
    baseline_file = os.environ.get(
        "DEVICE_BASELINE_FILE", "/opt/nettap/data/device_baseline.json"
    )
    device_baseline = DeviceBaseline(baseline_file=baseline_file)
    register_baseline_routes(app, device_baseline)

    # Internet health monitoring
    internet_health = InternetHealthMonitor()
    register_health_monitor_routes(app, internet_health)

    # Investigation bookmarks/notes
    investigations_file = os.environ.get(
        "INVESTIGATIONS_FILE", "/opt/nettap/data/investigations.json"
    )
    investigation_store = InvestigationStore(store_file=investigations_file)
    register_investigation_routes(app, investigation_store)

    # Settings (API keys, env file management)
    env_file = os.environ.get("NETTAP_ENV_FILE", "/opt/nettap/.env")
    register_settings_routes(app, env_file=env_file)

    # Natural language search (query parser + OpenSearch execution)
    nl_search_parser = NLSearchParser()
    register_search_routes(app, nl_search_parser, storage)

    # Community detection packs (Suricata rule pack management)
    packs_dir = os.environ.get(
        "DETECTION_PACKS_DIR", "/opt/nettap/data/detection-packs"
    )
    detection_pack_manager = DetectionPackManager(packs_dir=packs_dir)
    register_detection_pack_routes(app, detection_pack_manager)

    # Scheduled reports (periodic network summary reports)
    reports_dir = os.environ.get("REPORTS_DIR", "/opt/nettap/data/reports")
    schedules_file = os.environ.get(
        "REPORT_SCHEDULES_FILE", "/opt/nettap/data/report_schedules.json"
    )
    report_generator = ReportGenerator(
        reports_dir=reports_dir, schedules_file=schedules_file
    )
    register_report_routes(app, report_generator)

    logger.info("API application created with %d routes", len(app.router.routes()))

    return app


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

async def start_api(
    storage: StorageManager,
    smart: SmartMonitor,
    opensearch_url: str,
    port: int = 8880,
    shutdown_event: asyncio.Event | None = None,
) -> web.AppRunner:
    """Start the HTTP API server and return the runner for cleanup.

    Creates the aiohttp application, sets up a TCP site on the given port
    (binding to all interfaces), and starts listening.

    Args:
        storage: The StorageManager instance.
        smart: The SmartMonitor instance.
        opensearch_url: Base URL of the OpenSearch cluster.
        port: TCP port to listen on (default 8880).
        shutdown_event: Optional asyncio.Event for coordinated shutdown.
            Currently unused but accepted for future graceful drain support.

    Returns:
        The aiohttp.web.AppRunner that must be cleaned up on shutdown
        via ``await runner.cleanup()``.
    """
    app = create_app(storage, smart, opensearch_url)
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger.info("HTTP API server listening on 0.0.0.0:%d", port)
    return runner
