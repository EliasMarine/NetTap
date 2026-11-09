"""
NetTap Daemon HTTP API Server

Provides aiohttp-based REST endpoints for storage status, SMART health,
ILM policy management, and system health checks. Every request except
``GET /api/health`` must carry the shared daemon token (see daemon_auth.py);
the web dashboard reaches the daemon only through its server-side proxy.

Endpoints:
    GET  /api/health             Liveness check
    GET  /api/storage/status     Full storage status
    GET  /api/storage/retention  Retention config only
    POST /api/storage/prune      Trigger manual prune cycle
    POST /api/storage/config     Save retention config + sync ILM
    GET  /api/smart/health       SMART drive health
    GET  /api/indices            OpenSearch index listing
    GET  /api/system/health      Combined system health
    POST /api/ilm/apply          Apply ILM policies
"""

import asyncio
import contextlib
import functools
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from aiohttp import web
from opensearchpy import OpenSearch

from storage.manager import StorageManager
from smart.monitor import SmartMonitor

# OLD CODE START — apply_ilm_policies (static file) is no longer used (CR-038)
# from storage.ilm import apply_ilm_policies, apply_ilm_policies_from_config
# OLD CODE END
from storage.ilm import apply_ilm_policies_from_config
from storage.ilm_generator import generate_ilm_policies
from storage.retention_config import RetentionConfigManager
from api.offload import in_thread, run_blocking
from api.error_replies import public_json, safe_error_middleware
from api.daemon_auth import (
    load_or_create_token,
    make_auth_middleware,
    DEFAULT_TOKEN_FILE,
)
from api.tshark import register_tshark_routes
from api.packets import register_packet_routes
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
from api.home_location import register_home_location_routes
from services.capture_config import load_capture_config
from services.excluded_ips import (
    load_excluded_ips,
    detect_and_build_lan_filter,
    detect_appliance_ip,
    with_appliance_ip,
)
from api.search import register_search_routes
from api.detection_packs import register_detection_pack_routes
from api.reports import register_report_routes
from api.bridge import register_bridge_routes
from api.updates import register_update_routes
from api.nic_discovery import register_nic_discovery_routes
from api.setup import register_setup_routes
from api.logs import register_log_routes
from api.opensearch_cluster import register_opensearch_cluster_routes
from api.logstash import register_logstash_routes
from api.lookup import register_lookup_routes
from api.tools import register_tools_routes
from api.capture import register_capture_routes
from api.dhcp_gateway import register_dhcp_gateway_routes
from api.devices_v2 import register_devices_v2_routes
from api.device_custom import register_device_custom_routes
from api.live import register_live_routes
from api.bandwidth import register_bandwidth_routes
from api.live_bandwidth import register_live_bandwidth_routes
from api.notifications_hub import register_notification_hub_routes
from api.changelog import register_changelog_routes
from api.certificates import register_certificate_routes
from api.dns import register_dns_routes
from api.iot import register_iot_routes
from api.lan_security import register_lan_security_routes
from api.suricata_rules import register_suricata_rules_routes
from api.mac_correlation import register_mac_correlation_routes
from api.pcap import register_pcap_routes
from api.capture_control import register_capture_control_routes
from api.backup import register_backup_routes
from api.threats import register_threat_routes
from api.network import register_network_routes
from api.drilldown_runner import lan_cidrs
from api.addresses import register_address_routes
from api.domains import register_domain_routes
from api.suricata_categories import register_suricata_category_routes
from services.pipeline_health import OVERALL as PIPELINE_OVERALL, PipelineHealth
from services.tshark_service import TSharkService
from services.capture_index import CaptureIndex
from services.packet_search import PacketSearchService
from services.cyberchef_service import CyberChefService
from services.geoip_service import GeoIPService
from services.risk_scoring import RiskScorer
from services.device_baseline import DeviceBaseline
from services.internet_health import InternetHealthMonitor
from services.investigation_store import InvestigationStore
from services.nl_search import NLSearchParser
from services.detection_packs import DetectionPackManager
from services.report_generator import ReportGenerator
from services.bridge_health import BridgeHealthMonitor
from services.bridge_manager import BridgeManager
from services.dns_recon_service import DnsReconService
from services.mac_lookup_service import MacLookupService
from services.network_diag_service import NetworkDiagService
from services.ssl_cert_service import SslCertService
from services.version_manager import VersionManager
from services.update_checker import UpdateChecker
from services.malcolm_upgrade import MalcolmUpgrade
from services.update_executor import UpdateExecutor
from services.device_registry import DeviceRegistry
from services.device_custom import DeviceCustomStore
from services.unifi_integration import UnifiIntegration
from services.live_connections import LiveConnectionTracker
from services.bandwidth_tracker import BandwidthTracker
from services.notification_hub import NotificationHub
from services.notification_dispatcher import AlertDispatcher
from services.changelog import ChangelogService
from services.cert_monitor import CertificateMonitor
from services.suricata_rules import SuricataRuleManager
from services.mac_correlator import MACCorrelator
from services.pcap_search import PcapSearchService
from services.config_backup import ConfigBackup
from services.capture_mode_stub import CaptureManagerStub

logger = logging.getLogger("nettap.api")

# NET-200: the largest request body (a config backup with photos); nginx and nettap-web match it
MAX_REQUEST_BYTES = 16 * 1024 * 1024


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


# OLD CODE START — CORS "*" let any web page on the LAN call the daemon from a
# browser. The browser never calls the daemon directly (everything goes through
# the SvelteKit proxy), and the daemon now requires a shared token (2026-10-29).
# @web.middleware
# async def cors_middleware(request: web.Request, handler) -> web.StreamResponse:
#     """Add CORS headers to every response for LAN-only dashboard access.
#
#     Allows all origins since the appliance runs on a private network
#     segment and the dashboard may be accessed from any local IP.
#     """
#     # Handle preflight OPTIONS requests
#     if request.method == "OPTIONS":
#         response = web.Response(status=204)
#     else:
#         try:
#             response = await handler(request)
#         except web.HTTPException as exc:
#             response = exc
#
#     response.headers["Access-Control-Allow-Origin"] = "*"
#     response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
#     response.headers["Access-Control-Allow-Headers"] = "Content-Type, Accept"
#     response.headers["Access-Control-Max-Age"] = "3600"
#
#     return response
# OLD CODE END


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
    return web.json_response(
        {
            "status": "ok",
            "uptime": round(uptime, 2),
        }
    )


@in_thread
def handle_storage_status(request: web.Request) -> web.Response:
    """GET /api/storage/status -- Full storage status from StorageManager."""
    try:
        storage: StorageManager = request.app["storage"]
        status = storage.get_status()
        # #96: the saved retention isn't in OpenSearch yet, so ILM isn't in sync,
        # however long ago an earlier apply succeeded
        if "ilm_sync" in request.app and not _ilm_in_sync(request.app):
            task = request.app.get("_ilm_retry_task")
            status["ilm_status"] = {
                **status["ilm_status"],
                "synced": False,
                # OLD CODE: "pending_retry": task is not None and not task.done(), (A15: hid
                # the storage manager's own startup retry)
                "pending_retry": status["ilm_status"].get("pending_retry", False)
                or (task is not None and not task.done()),
            }
        return web.json_response(status)
    except Exception as exc:
        logger.exception("Error fetching storage status")
        return web.json_response(
            {"error": f"Failed to fetch storage status: {exc}"},
            status=500,
        )


@in_thread
def handle_storage_retention(request: web.Request) -> web.Response:
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


@in_thread
def handle_storage_prune(request: web.Request) -> web.Response:
    """POST /api/storage/prune -- Trigger a manual prune/maintenance cycle."""
    try:
        storage: StorageManager = request.app["storage"]
        # OLD CODE START — PR 2 (reliability): get_status() below ran on the loop after it
        # # Run the synchronous run_cycle in a thread to avoid blocking the
        # # event loop (it performs disk I/O and OpenSearch HTTP calls).
        # loop = asyncio.get_running_loop()
        # await loop.run_in_executor(None, storage.run_cycle)
        # OLD CODE END
        # The whole handler runs in a worker thread (disk I/O and OpenSearch calls)
        storage.run_cycle()
        # Return current status after the prune cycle completes
        status = storage.get_status()
        return web.json_response(
            {
                "result": "prune_cycle_complete",
                "storage_status": status,
            }
        )
    except Exception as exc:
        logger.exception("Error during manual prune cycle")
        return web.json_response(
            {"error": f"Prune cycle failed: {exc}"},
            status=500,
        )


async def handle_cleanup_preview(request: web.Request) -> web.Response:
    """POST /api/storage/cleanup/preview -- Preview what would be deleted."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    older_than_days = body.get("older_than_days")
    if (
        not isinstance(older_than_days, int)
        or older_than_days < 1
        or older_than_days > 3650
    ):
        return web.json_response(
            {"error": "older_than_days must be an integer between 1 and 3650"},
            status=400,
        )

    try:
        storage: StorageManager = request.app["storage"]
        # OLD CODE START — PR #200 review: asyncio's default pool, which must stay free for
        # the drill-downs and health checks
        # loop = asyncio.get_running_loop()
        # preview = await loop.run_in_executor(
        #     None, storage.preview_cleanup, older_than_days
        # )
        # OLD CODE END
        preview = await run_blocking(storage.preview_cleanup, older_than_days)
        return web.json_response(preview)
    except Exception as exc:
        logger.exception("Error previewing cleanup")
        return web.json_response(
            {"error": f"Failed to preview cleanup: {exc}"},
            status=500,
        )


async def handle_cleanup_execute(request: web.Request) -> web.Response:
    """POST /api/storage/cleanup/execute -- Execute manual data cleanup."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    older_than_days = body.get("older_than_days")
    if (
        not isinstance(older_than_days, int)
        or older_than_days < 1
        or older_than_days > 3650
    ):
        return web.json_response(
            {"error": "older_than_days must be an integer between 1 and 3650"},
            status=400,
        )

    try:
        storage: StorageManager = request.app["storage"]
        # OLD CODE START — PR #200 review: asyncio's default pool, which must stay free for
        # the drill-downs and health checks
        # loop = asyncio.get_running_loop()
        # result = await loop.run_in_executor(
        #     None, storage.execute_cleanup, older_than_days
        # )
        # OLD CODE END
        result = await run_blocking(storage.execute_cleanup, older_than_days)

        # Log to changelog if available
        try:
            changelog: ChangelogService = request.app.get("changelog_service")
            if changelog is None:
                # Find it from the registered services
                for key, val in request.app.items():
                    if isinstance(val, ChangelogService):
                        changelog = val
                        break
            if changelog:
                # OLD CODE START — 2026-11-01: the dict went in as the third positional
                # argument, which is log_event's description string, not its metadata
                # await loop.run_in_executor(None, changelog.log_event, "storage_pruned",
                #     f"Manual cleanup: ...", {...})
                # OLD CODE END
                # OLD CODE START — PR #200 review: asyncio's default pool, which must stay free for
                # the drill-downs and health checks
                # await loop.run_in_executor(
                #     None,
                # OLD CODE END
                await run_blocking(
                    functools.partial(
                        changelog.log_event,
                        "storage_pruned",
                        f"Manual cleanup: deleted data older than {older_than_days} days",
                        metadata={
                            "older_than_days": older_than_days,
                            "deleted_indices": result["deleted_indices"],
                            "deleted_pcap_files": result["deleted_pcap_files"],
                            "freed_bytes": result["freed_bytes_estimate"],
                            "cutoff_date": result["cutoff_date"],
                            "trigger": "manual",
                        },
                    ),
                )
        except Exception:
            logger.warning("Failed to log cleanup to changelog", exc_info=True)

        return web.json_response(result)
    except RuntimeError as exc:
        # Lock contention — auto-prune is running
        return web.json_response({"error": str(exc)}, status=409)
    except Exception as exc:
        logger.exception("Error executing cleanup")
        return web.json_response(
            {"error": f"Cleanup failed: {exc}"},
            status=500,
        )


async def handle_smart_health(request: web.Request) -> web.Response:
    """GET /api/smart/health -- SMART drive health status."""
    try:
        smart: SmartMonitor = request.app["smart"]
        # OLD CODE START — PR #200 review: asyncio's default pool, which must stay free for
        # the drill-downs and health checks
        # # Run the synchronous get_status in a thread (it shells out to smartctl)
        # loop = asyncio.get_running_loop()
        # status = await loop.run_in_executor(None, smart.get_status)
        # OLD CODE END
        # Run the synchronous get_status in a thread (it shells out to smartctl)
        status = await run_blocking(smart.get_status)
        return web.json_response(status)
    except Exception as exc:
        logger.exception("Error fetching SMART health")
        return web.json_response(
            {"error": f"Failed to fetch SMART health: {exc}"},
            status=500,
        )


async def handle_smart_diagnostics(request: web.Request) -> web.Response:
    """GET /api/smart/diagnostics -- SMART self-test diagnostics."""
    try:
        smart: SmartMonitor = request.app["smart"]
        # OLD CODE START — PR #200 review: asyncio's default pool, which must stay free for
        # the drill-downs and health checks
        # loop = asyncio.get_running_loop()
        # diagnostics = await loop.run_in_executor(None, smart.get_diagnostics)
        # OLD CODE END
        diagnostics = await run_blocking(smart.get_diagnostics)
        return web.json_response(diagnostics)
    except Exception as exc:
        logger.exception("Error fetching SMART diagnostics")
        return web.json_response(
            {"error": f"Failed to fetch SMART diagnostics: {exc}"},
            status=500,
        )


async def handle_smart_test(request: web.Request) -> web.Response:
    """POST /api/smart/test -- Trigger on-demand SMART check with fresh results."""
    try:
        smart: SmartMonitor = request.app["smart"]
        # OLD CODE START — PR #200 review: asyncio's default pool, which must stay free for
        # the drill-downs and health checks
        # loop = asyncio.get_running_loop()
        # # Run self-test for diagnostics
        # diagnostics = await loop.run_in_executor(None, smart.run_self_test)
        # # Also get fresh metrics
        # status = await loop.run_in_executor(None, smart.get_status)
        # OLD CODE END
        # Run self-test for diagnostics
        diagnostics = await run_blocking(smart.run_self_test)
        # Also get fresh metrics
        status = await run_blocking(smart.get_status)
        return web.json_response(
            {
                "diagnostics": diagnostics,
                "health": status,
            }
        )
    except Exception as exc:
        logger.exception("Error running SMART test")
        return web.json_response(
            {"error": f"SMART test failed: {exc}"},
            status=500,
        )


async def handle_indices(request: web.Request) -> web.Response:
    """GET /api/indices -- List all tracked OpenSearch indices."""
    try:
        storage: StorageManager = request.app["storage"]
        # OLD CODE START — PR #200 review: asyncio's default pool, which must stay free for
        # the drill-downs and health checks
        # loop = asyncio.get_running_loop()
        # indices = await loop.run_in_executor(None, storage.list_indices)
        # OLD CODE END
        indices = await run_blocking(storage.list_indices)
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


def _host_uptime_seconds() -> float | None:
    """Machine uptime; /proc/uptime isn't namespaced, so the container sees the host's."""
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _aggregate_health(failed: bool, unknown: bool) -> str:
    """S5: a known failure is a problem; otherwise any check that couldn't run makes it incomplete."""
    if failed:
        return "problem"
    return "incomplete" if unknown else "healthy"


async def handle_system_health(request: web.Request) -> web.Response:
    """GET /api/system/health -- Combined system health check.

    Aggregates: daemon uptime, storage status, SMART health, OpenSearch
    reachability and whether current data is arriving (F2) into a single response.
    """
    # F2: started first, so its 5 s budget overlaps the checks below
    pipeline = asyncio.ensure_future(request.app["pipeline_health"].get())
    start_time: float = request.app["start_time"]
    uptime = time.monotonic() - start_time
    # OLD CODE START — opensearch_url was fetched but never used (F841)
    # opensearch_url: str = request.app["opensearch_url"]
    # OLD CODE END

    # OLD CODE START — replaced 2026-11-01: the System page shows "uptime" as the
    # machine's, but this was the daemon's (minutes after any redeploy).
    # result: dict = {
    #     "uptime": round(uptime, 2),
    # OLD CODE END
    result: dict = {
        "uptime": round(_host_uptime_seconds() or uptime, 2),
        "daemon_uptime": round(uptime, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "storage": None,
        "smart": None,
        "opensearch_reachable": False,
        "healthy": True,  # Assume healthy until proven otherwise
    }
    # OLD CODE START — 2026-11-06 (S5): one boolean, so a check that couldn't run (SMART
    # unreadable: healthy None, `not None` is True) read the same as a failed one: "Degraded"
    # (each `result["healthy"] = False` below is now a `failed` or `unknown` flag)
    # OLD CODE END
    failed = False  # a check ran and found a problem
    unknown = False  # a check couldn't run, so health isn't fully known

    # Storage status
    try:
        storage: StorageManager = request.app["storage"]
        # OLD CODE START — PR #200 review: asyncio's default pool, which must stay free for
        # the drill-downs and health checks
        # loop = asyncio.get_running_loop()
        # result["storage"] = await loop.run_in_executor(None, storage.get_status)
        # OLD CODE END
        result["storage"] = await run_blocking(storage.get_status)
    except Exception as exc:
        logger.warning("System health: storage status unavailable: %s", exc)
        # OLD CODE: result["storage"] = {"error": str(exc)} (NET-229: an OpenSearch client error, URL included)
        result["storage"] = {"error": "Storage status couldn't be read."}
        unknown = True

    # SMART health
    try:
        smart: SmartMonitor = request.app["smart"]
        # OLD CODE START — PR #200 review: asyncio's default pool, which must stay free for
        # the drill-downs and health checks
        # loop = asyncio.get_running_loop()
        # smart_status = await loop.run_in_executor(None, smart.get_status)
        # OLD CODE END
        smart_status = await run_blocking(smart.get_status)
        result["smart"] = smart_status
        # healthy: None means the drive couldn't be read (#96), not that it failed
        if smart_status.get("healthy") is False:
            failed = True
        elif smart_status.get("healthy") is None:
            unknown = True
    except Exception as exc:
        logger.warning("System health: SMART status unavailable: %s", exc)
        # OLD CODE: result["smart"] = {"error": str(exc)} (NET-229: exception text)
        result["smart"] = {"error": "Drive health couldn't be read."}
        unknown = True

    # OpenSearch reachability
    try:
        storage_mgr: StorageManager = request.app["storage"]
        # OLD CODE START — PR #200 review: asyncio's default pool, which must stay free for
        # the drill-downs and health checks
        # loop = asyncio.get_running_loop()
        # await loop.run_in_executor(None, storage_mgr._client.info)
        # OLD CODE END
        await run_blocking(storage_mgr._client.info)
        result["opensearch_reachable"] = True
    except Exception as exc:
        logger.warning("System health: OpenSearch unreachable: %s", exc)
        result["opensearch_reachable"] = False
        failed = True

    # F2: with only the checks above, stopped sensors or nothing new indexed still read healthy
    result["pipeline"] = await pipeline
    effect = PIPELINE_OVERALL[result["pipeline"]["state"]]
    failed = failed or effect == "problem"
    unknown = unknown or effect == "incomplete"

    result["status"] = _aggregate_health(failed, unknown)
    # True, False, or None when incomplete: the same tri-state as SMART's healthy
    result["healthy"] = {"healthy": True, "problem": False}.get(result["status"])
    return web.json_response(result)


async def handle_ilm_apply(request: web.Request) -> web.Response:
    """POST /api/ilm/apply -- Apply ILM policies to OpenSearch."""
    try:
        # OLD CODE START — applied the static ilm-policy.json (fixed days, no
        # auth, not in the daemon image), overwriting the user's retention (CR-038).
        # opensearch_url: str = request.app["opensearch_url"]
        # loop = asyncio.get_running_loop()
        # results = await loop.run_in_executor(None, apply_ilm_policies, opensearch_url)
        # OLD CODE END
        # OLD CODE START — PR #200 review: asyncio's default pool, which must stay free for
        # the drill-downs and health checks
        # loop = asyncio.get_running_loop()
        # results = await loop.run_in_executor(None, _apply_current_ilm, request.app)
        # OLD CODE END
        results = await run_blocking(_apply_current_ilm, request.app)
        return web.json_response(
            {
                "result": "ilm_policies_applied",
                "policies": results,
            }
        )
    except Exception as exc:
        logger.exception("Error applying ILM policies")
        return web.json_response(
            {"error": f"Failed to apply ILM policies: {exc}"},
            status=500,
        )


# ---------------------------------------------------------------------------
# Background ILM retry (used when OpenSearch is down during config save)
# ---------------------------------------------------------------------------


# OLD CODE START — the retry kept the policies of the save that scheduled it,
# so after a later successful save it could reapply older (shorter) retention.
# Saves were not serialized either, so two could apply out of order (2026-10-29)
# async def _ilm_retry_background(
#     app: web.Application,
#     config_manager: RetentionConfigManager,
#     opensearch_url: str,
#     policies: dict[str, dict],
#     http_auth: tuple[str, str] | None,
#     max_retries: int = 20,
#     base_delay: float = 30.0,
# ) -> None:
#     """Retry ILM policy application with exponential backoff.
#
#     Called as a background ``asyncio.Task`` when ``handle_storage_config``
#     fails to apply ILM policies because OpenSearch is temporarily
#     unavailable. Retries up to *max_retries* times with exponential
#     backoff capped at 10 minutes.
#
#     On success, calls ``config_manager.mark_ilm_applied()`` to persist
#     the result in ``retention.json``.
#     """
#     loop = asyncio.get_running_loop()
#
#     for attempt in range(1, max_retries + 1):
#         delay = min(base_delay * (2 ** (attempt - 1)), 600)  # cap at 10 min
#         await asyncio.sleep(delay)
#         try:
#             results = await loop.run_in_executor(
#                 None,
#                 lambda: apply_ilm_policies_from_config(
#                     opensearch_url, policies, http_auth=http_auth
#                 ),
#             )
#             config_manager.mark_ilm_applied(results)
#             logger.info("ILM retry succeeded on attempt %d", attempt)
#             app["_ilm_retry_task"] = None
#             return
#         except Exception as exc:
#             logger.warning(
#                 "ILM retry attempt %d/%d failed: %s", attempt, max_retries, exc
#             )
#
#     logger.error("ILM retry exhausted %d attempts", max_retries)
#     app["_ilm_retry_task"] = None
# OLD CODE END


@dataclass
class IlmSyncState:
    """Which retention-config revision the OpenSearch ILM policies reflect.

    Every config save bumps ``config_revision`` on the event loop.
    ``applied_revision`` is the newest revision whose policies were applied.
    ``lock`` is taken inside the executor thread, so applications never
    overlap, and a running one is never cancelled.
    """

    lock: threading.Lock = field(default_factory=threading.Lock)
    config_revision: int = 0
    applied_revision: int = 0


class IlmApplyError(Exception):
    """OpenSearch answered, but at least one policy came back as an error."""

    def __init__(self, results: dict[str, str]):
        failed = {k: v for k, v in results.items() if str(v).startswith("error")}
        super().__init__(f"ILM policies failed: {failed}")
        self.results = results


def _apply_latest_ilm(app: web.Application) -> dict[str, str] | None:
    """Apply ILM for the newest saved config; skip if it is already applied.

    Runs in an executor thread and is shared by config saves and the retry.
    A save queued behind a newer one therefore applies the newest config or
    skips: a request's own (older) policy snapshot is never applied.

    Returns:
        The per-policy results, or None if an equal-or-newer revision is
        already applied.

    Raises:
        IlmApplyError: If any policy result is ``"error: ..."``.
        Exception: If OpenSearch is unreachable.
    """
    state: IlmSyncState = app["ilm_sync"]
    with state.lock:
        # Read the revision before the config: a save stores its config and
        # then bumps the revision, so the config read below is at least this new.
        revision = state.config_revision
        if state.applied_revision >= revision:
            return None
        config_manager: RetentionConfigManager = app["retention_config_manager"]
        policies = generate_ilm_policies(config_manager.get_config())
        # OLD CODE START — A15: a failure left the last success on the health card
        # results = apply_ilm_policies_from_config(
        #     app["opensearch_url"], policies, http_auth=app.get("http_auth")
        # )
        # if any(str(status).startswith("error") for status in results.values()):
        #     raise IlmApplyError(results)
        # OLD CODE END
        try:
            results = apply_ilm_policies_from_config(
                app["opensearch_url"], policies, http_auth=app.get("http_auth")
            )
            if any(str(status).startswith("error") for status in results.values()):
                raise IlmApplyError(results)
        except Exception as exc:
            # recorded in memory first; a failed file write mustn't hide the real error
            with contextlib.suppress(OSError):
                config_manager.mark_ilm_failed(str(exc))
            raise
        config_manager.mark_ilm_applied(results)
        state.applied_revision = revision
        return results


def _apply_current_ilm(app: web.Application) -> dict[str, str]:
    """Apply ILM for the current retention config, even if already applied.

    Holds the same lock as ``_apply_latest_ilm`` so a concurrent save is
    never overwritten with an older config.
    """
    with app["ilm_sync"].lock:
        policies = generate_ilm_policies(app["storage"].config)
        return apply_ilm_policies_from_config(
            app["opensearch_url"], policies, http_auth=app.get("http_auth")
        )


def _ilm_in_sync(app: web.Application) -> bool:
    state: IlmSyncState = app["ilm_sync"]
    return state.applied_revision >= state.config_revision


async def _ilm_retry_background(
    app: web.Application,
    max_retries: int = 20,
    base_delay: float = 30.0,
) -> None:
    """Retry ILM application with exponential backoff until it is in sync.

    Called as a background ``asyncio.Task`` when a config save could not
    apply its ILM policies. Each attempt sleeps (backoff capped at 10
    minutes), then runs ``_apply_latest_ilm``, which applies the *current*
    config or skips if it is already applied. It never reapplies the
    policies of the save that scheduled it.
    """
    loop = asyncio.get_running_loop()

    for attempt in range(1, max_retries + 1):
        delay = min(base_delay * (2 ** (attempt - 1)), 600)  # cap at 10 min
        await asyncio.sleep(delay)
        try:
            await loop.run_in_executor(None, _apply_latest_ilm, app)
        except Exception as exc:
            logger.warning(
                "ILM retry attempt %d/%d failed: %s", attempt, max_retries, exc
            )
            continue
        # A newer save may have landed meanwhile; keep going until it is applied.
        if _ilm_in_sync(app):
            logger.info("ILM retry succeeded on attempt %d", attempt)
            app["_ilm_retry_task"] = None
            return

    logger.error("ILM retry exhausted %d attempts", max_retries)
    app["_ilm_retry_task"] = None


def _schedule_ilm_retry(app: web.Application) -> None:
    """Start the single background retry task unless one is already pending."""
    existing_task = app.get("_ilm_retry_task")
    if existing_task is None or existing_task.done():
        app["_ilm_retry_task"] = asyncio.create_task(
            _ilm_retry_background(app), name="ilm-retry"
        )


# ---------------------------------------------------------------------------
# Storage config handler (retention settings + ILM sync)
# ---------------------------------------------------------------------------


async def handle_storage_config(request: web.Request) -> web.Response:
    """POST /api/storage/config -- Save retention config and sync ILM policies.

    Expects a JSON body with retention and threshold values::

        {
            "hot_days": 90,
            "warm_days": 180,
            "cold_days": 30,
            "disk_threshold_percent": 80,
            "emergency_threshold_percent": 90
        }

    Validates, persists to ``retention.json``, syncs to ``.env``, generates
    ILM policies from the new config, and applies them to OpenSearch. If
    OpenSearch is unreachable, the config is still saved and a background
    retry task is scheduled.
    """
    # --- Check that config manager is available ---
    if "retention_config_manager" not in request.app:
        return public_json(
            {"error": "Retention config manager not initialised"}, status=503
        )

    # --- Parse JSON body ---
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    # A9: the rest moved to save_retention_config, which a backup restore uses too
    status, payload = await save_retention_config(request.app, body)
    # NET-229 follow-up: its 5xx is the hand-written 'not initialised' line
    return public_json(payload, status=status)


async def save_retention_config(app: web.Application, body: dict) -> tuple[int, dict]:
    """Save retention settings, hot-reload them and sync ILM: (HTTP status, response body).

    Shared by POST /api/storage/config and the backup restore (A9).
    """
    if "retention_config_manager" not in app:
        return 503, {"error": "Retention config manager not initialised"}

    # --- Validate and save config ---
    config_manager: RetentionConfigManager = app["retention_config_manager"]
    try:
        new_config = config_manager.save(body)
    # TypeError/AttributeError: a restored file can hold any JSON, not just a request body
    except (ValueError, TypeError, AttributeError) as exc:
        return 400, {"error": str(exc)}

    # --- Hot-reload StorageManager config ---
    storage: StorageManager = app["storage"]
    storage.config = new_config

    # OLD CODE START — applied this request's own snapshot without ordering, and
    # an "error: ..." result counted as success (2026-10-29)
    # # --- Generate and apply ILM policies ---
    # policies = generate_ilm_policies(new_config)
    # opensearch_url: str = request.app["opensearch_url"]
    # http_auth: tuple[str, str] | None = request.app.get("http_auth")
    #
    # try:
    #     loop = asyncio.get_running_loop()
    #     results = await loop.run_in_executor(
    #         None,
    #         lambda: apply_ilm_policies_from_config(
    #             opensearch_url, policies, http_auth=http_auth
    #         ),
    #     )
    #     config_manager.mark_ilm_applied(results)
    #     return web.json_response(
    #         {
    #             "saved": True,
    #             "ilm_applied": True,
    #             "ilm_results": results,
    #             "config": {
    #                 "hot_days": new_config.hot_days,
    #                 "warm_days": new_config.warm_days,
    #                 "cold_days": new_config.cold_days,
    #                 "disk_threshold_percent": round(new_config.disk_threshold * 100),
    #                 "emergency_threshold_percent": round(
    #                     new_config.emergency_threshold * 100
    #                 ),
    #             },
    #         }
    #     )
    # except Exception as exc:
    #     # OpenSearch is down — config is saved, schedule background retry
    #     logger.warning(
    #         "ILM application failed after config save, scheduling retry: %s", exc
    #     )
    #     existing_task = request.app.get("_ilm_retry_task")
    #     if existing_task is None or existing_task.done():
    #         request.app["_ilm_retry_task"] = asyncio.create_task(
    #             _ilm_retry_background(
    #                 request.app, config_manager, opensearch_url, policies, http_auth
    #             ),
    #             name="ilm-retry",
    #         )
    #     return web.json_response(
    #         {
    #             "saved": True,
    #             "ilm_applied": False,
    #             "ilm_retry_scheduled": True,
    #             "ilm_error": str(exc),
    #             "config": {
    #                 "hot_days": new_config.hot_days,
    #                 "warm_days": new_config.warm_days,
    #                 "cold_days": new_config.cold_days,
    #                 "disk_threshold_percent": round(new_config.disk_threshold * 100),
    #                 "emergency_threshold_percent": round(
    #                     new_config.emergency_threshold * 100
    #                 ),
    #             },
    #         }
    #     )
    # OLD CODE END

    # --- Apply ILM for the newest config (serialized, revision-aware) ---
    state: IlmSyncState = app["ilm_sync"]
    state.config_revision += 1
    revision = state.config_revision
    results, ilm_error = await _run_ilm_worker(app)
    config_summary = {
        "hot_days": new_config.hot_days,
        "warm_days": new_config.warm_days,
        "cold_days": new_config.cold_days,
        "disk_threshold_percent": round(new_config.disk_threshold * 100),
        "emergency_threshold_percent": round(new_config.emergency_threshold * 100),
    }

    # Applied for this save if this revision, or a newer one, is in OpenSearch.
    if state.applied_revision >= revision:
        return 200, {
            "saved": True,
            "ilm_applied": True,
            "ilm_results": results or {},
            "config": config_summary,
        }

    # OpenSearch is down or rejected a policy — config is saved, retry later
    ilm_error = ilm_error or "ILM policies not applied yet"
    logger.warning(
        "ILM application failed after config save, scheduling retry: %s", ilm_error
    )
    _schedule_ilm_retry(app)
    return 200, {
        "saved": True,
        "ilm_applied": False,
        "ilm_retry_scheduled": True,
        "ilm_error": ilm_error,
        "config": config_summary,
    }


async def _run_ilm_worker(
    app: web.Application,
) -> tuple[dict[str, str] | None, str | None]:
    """Run ``_apply_latest_ilm`` on the route pool; return (results, error)."""
    # OLD CODE START — PR #200 review: asyncio's default pool, which must stay free for
    # the drill-downs and health checks
    # loop = asyncio.get_running_loop()
    # try:
    #     return await loop.run_in_executor(None, _apply_latest_ilm, app), None
    # OLD CODE END
    try:
        return await run_blocking(_apply_latest_ilm, app), None
    except Exception as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def _load_daemon_token() -> str | None:
    """Load the shared API token, or None so the API fails closed."""
    path = os.environ.get("DAEMON_TOKEN_FILE", DEFAULT_TOKEN_FILE)
    try:
        return load_or_create_token(path)
    except OSError as exc:
        logger.error(
            "Daemon API token unavailable at %s (%s); rejecting all API requests "
            "except /api/health until it can be created",
            path,
            exc,
        )
        return None


def _management_interface() -> str:
    """The management NIC from the capture config, or "" if it can't be read."""
    try:
        return load_capture_config().management
    except Exception as exc:  # a broken capture config must not stop the API starting
        logger.warning(
            "Could not read the management NIC from the capture config: %s", exc
        )
        return ""


def create_app(
    storage: StorageManager,
    smart: SmartMonitor,
    opensearch_url: str,
    retention_config_manager: RetentionConfigManager | None = None,
    http_auth: tuple[str, str] | None = None,
) -> web.Application:
    """Create and configure the aiohttp web application.

    Stores subsystem references in the app dict so route handlers can
    access them via ``request.app["storage"]`` etc.

    Args:
        storage: The StorageManager instance for disk/index operations.
        smart: The SmartMonitor instance for drive health checks.
        opensearch_url: Base URL of the OpenSearch cluster.
        retention_config_manager: Optional RetentionConfigManager for the
            ``POST /api/storage/config`` endpoint. If None, the endpoint
            will return 503 (not yet initialised).
        http_auth: Optional (username, password) tuple for OpenSearch
            authentication, passed through to ILM policy application.

    Returns:
        Configured aiohttp.web.Application ready to be served.
    """
    # OLD CODE START — CORS middleware removed, token auth added (2026-10-29)
    # app = web.Application(middlewares=[cors_middleware, logging_middleware])
    # OLD CODE END
    # Auth runs first so unauthenticated requests never reach any handler.
    # OLD CODE START — NET-200: aiohttp's default 1 MiB body cap refused a backup holding photos
    # app = web.Application(
    #     middlewares=[make_auth_middleware(_load_daemon_token()), logging_middleware]
    # )
    # OLD CODE END
    # OLD CODE START — NET-229 (B-p): 5xx replies carried exception text, stderr and internal URLs
    # app = web.Application(
    #     middlewares=[make_auth_middleware(_load_daemon_token()), logging_middleware],
    #     # Matches nginx and nettap-web (BODY_SIZE_LIMIT): photos ≤ 8 MiB in all, base64 in a backup
    #     client_max_size=MAX_REQUEST_BYTES,
    # )
    # OLD CODE END
    app = web.Application(
        middlewares=[
            make_auth_middleware(_load_daemon_token()),
            logging_middleware,
            safe_error_middleware,  # innermost: cuts a 5xx reply to safe fields (api/error_replies.py)
        ],
        # Matches nginx and nettap-web (BODY_SIZE_LIMIT): photos ≤ 8 MiB in all, base64 in a backup
        client_max_size=MAX_REQUEST_BYTES,
    )

    # Store subsystem references for handler access
    app["storage"] = storage
    app["smart"] = smart
    app["opensearch_url"] = opensearch_url
    app["http_auth"] = http_auth
    app["start_time"] = time.monotonic()
    # F2: its own client, 3 s and no retries, so the probe stays inside its 5 s budget
    app["pipeline_health"] = PipelineHealth(
        OpenSearch(**storage.client_kwargs(timeout=3, max_retries=0)), app["start_time"]
    )
    if retention_config_manager is not None:
        app["retention_config_manager"] = retention_config_manager
    # OLD CODE: app["ilm_sync"] = IlmSyncState() (A15: startup verification ran outside it)
    app["ilm_sync"] = IlmSyncState(lock=storage.ilm_lock)

    # Register routes
    app.router.add_get("/api/health", handle_health)
    app.router.add_get("/api/storage/status", handle_storage_status)
    app.router.add_get("/api/storage/retention", handle_storage_retention)
    app.router.add_post("/api/storage/prune", handle_storage_prune)
    app.router.add_post("/api/storage/cleanup/preview", handle_cleanup_preview)
    app.router.add_post("/api/storage/cleanup/execute", handle_cleanup_execute)
    app.router.add_get("/api/smart/health", handle_smart_health)
    app.router.add_get("/api/smart/diagnostics", handle_smart_diagnostics)
    app.router.add_post("/api/smart/test", handle_smart_test)
    app.router.add_get("/api/indices", handle_indices)
    app.router.add_get("/api/system/health", handle_system_health)
    app.router.add_post("/api/ilm/apply", handle_ilm_apply)
    app.router.add_post("/api/storage/config", handle_storage_config)

    # TShark integration (containerized packet analysis)
    pcap_dir = os.environ.get("PCAP_DIR", "/opt/nettap/pcap")
    tshark_service = TSharkService(pcap_base_dir=pcap_dir)
    register_tshark_routes(app, tshark_service)

    # Packet analysis (NET-188): shares TShark's two reader slots
    capture_index = CaptureIndex(
        pcap_dir,
        os.environ.get("PACKET_INDEX_FILE", "/opt/nettap/data/packet-index.json"),
        tshark_service.semaphore,
    )
    register_packet_routes(
        app,
        PacketSearchService(
            pcap_dir,
            capture_index,
            tshark_service.semaphore,
            tshark_service.get_version,
        ),
        capture_index,
    )

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

    # GeoIP lookup (MaxMind GeoLite2 + OpenSearch enrichment + fallback)
    geoip_db = os.environ.get("GEOIP_DB_PATH", "/opt/nettap/data/GeoLite2-City.mmdb")
    geoip_service = GeoIPService(db_path=geoip_db, opensearch_client=storage._client)
    register_geoip_routes(app, geoip_service)

    # IP lookup tools (WHOIS + DNS)
    register_lookup_routes(app)

    # Network tools (DNS Recon, MAC Lookup, Ping, Traceroute, SSL Cert)
    dns_recon = DnsReconService()
    # OLD CODE START — #26: no OpenSearch, so only the 208 bundled prefixes were known
    # mac_lookup = MacLookupService()
    # OLD CODE END
    mac_lookup = MacLookupService(opensearch_client=storage._client)
    network_diag = NetworkDiagService()
    ssl_cert = SslCertService()
    register_tools_routes(app, dns_recon, mac_lookup, network_diag, ssl_cert)

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

    # Settings (API keys, env file management, excluded IPs)
    # OLD CODE START — was /opt/nettap/.env which is in the read-only container layer (2026-03-05)
    # env_file = os.environ.get("NETTAP_ENV_FILE", "/opt/nettap/.env")
    # OLD CODE END
    env_file = os.environ.get("NETTAP_ENV_FILE", "/opt/nettap/data/.env")
    excluded_ips_file = os.environ.get(
        "EXCLUDED_IPS_FILE", "/opt/nettap/data/excluded_ips.json"
    )
    app["excluded_ips_file"] = excluded_ips_file
    app["excluded_ips"] = load_excluded_ips(excluded_ips_file)
    logger.info("Loaded %d excluded IPs", len(app["excluded_ips"]))

    # Auto-detect and exclude appliance management IP
    # OLD CODE START — #79: the detected IP was saved into the owner's list, so a wrong one
    # (the .env.example placeholder) stayed excluded after the detection was fixed
    # appliance_ip = detect_appliance_ip()
    # if appliance_ip and appliance_ip not in app["excluded_ips"]:
    #     app["excluded_ips"].append(appliance_ip)
    #     save_excluded_ips(app["excluded_ips"], excluded_ips_file)
    #     logger.info("Auto-excluded appliance management IP: %s", appliance_ip)
    # OLD CODE END
    appliance_ip = detect_appliance_ip(_management_interface())
    # A9: kept so a backup restore can add it back when it reloads the owner's list
    app["appliance_ip"] = appliance_ip
    if appliance_ip and appliance_ip not in app["excluded_ips"]:
        # Runtime only: detected again at every start, never written into the owner's list
        # OLD CODE: app["excluded_ips"] = [*app["excluded_ips"], appliance_ip] (one rule now)
        app["excluded_ips"] = with_appliance_ip(app["excluded_ips"], appliance_ip)
        logger.info("Auto-excluded appliance management IP: %s", appliance_ip)
    elif not appliance_ip:
        logger.warning(
            "Appliance management IP not found; NetTap's own traffic is counted"
        )

    # Auto-detect LAN subnets from OpenSearch traffic data
    # Priority: LAN_SUBNETS env var > auto-detect from traffic > RFC1918 fallback
    app["lan_filter"] = detect_and_build_lan_filter(storage._client)
    logger.info("LAN filter initialized")
    register_settings_routes(app, env_file=env_file)
    register_home_location_routes(app)

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

    # Bridge health monitoring (inline tap bridge state + NIC carrier)
    bridge_name = os.environ.get("BRIDGE_NAME", "br0")
    wan_iface = os.environ.get("WAN_IFACE", "eth0")
    lan_iface = os.environ.get("LAN_IFACE", "eth1")
    bridge_health = BridgeHealthMonitor(
        bridge_name=bridge_name, wan_iface=wan_iface, lan_iface=lan_iface
    )

    # Bridge manager (create/teardown/readiness — writes to mounted host dirs)
    bridge_manager = BridgeManager(
        bridge_name=bridge_name,
        netplan_dir=os.environ.get("HOST_NETPLAN_DIR", ""),
        systemd_dir=os.environ.get("HOST_SYSTEMD_DIR", ""),
        sysctl_dir=os.environ.get("HOST_SYSCTL_DIR", ""),
    )
    register_bridge_routes(app, bridge_health, bridge_manager)

    # Software update system (version inventory + update checker + executor)
    compose_file = os.environ.get(
        "COMPOSE_FILE", "/opt/nettap/docker/docker-compose.yml"
    )
    backup_dir = os.environ.get("BACKUP_DIR", "/opt/nettap/backups")
    github_repo = os.environ.get("GITHUB_REPO", "EliasMarine/NetTap")

    version_manager = VersionManager(compose_file=compose_file)
    update_checker = UpdateChecker(github_repo=github_repo)
    # OLD CODE START — the Malcolm update needs the OpenSearch client to see records arrive
    # update_executor = UpdateExecutor(compose_file=compose_file, backup_dir=backup_dir)
    # OLD CODE END
    update_executor = UpdateExecutor(
        compose_file=compose_file,
        backup_dir=backup_dir,
        malcolm_upgrade=MalcolmUpgrade(client=storage._client),
    )

    # Wire up cross-service references
    update_checker.set_version_manager(version_manager)
    update_executor.set_version_manager(version_manager)
    update_executor.set_update_checker(update_checker)

    register_update_routes(app, version_manager, update_checker, update_executor)

    # NIC discovery (setup wizard interface detection from host sysfs)
    register_nic_discovery_routes(app)

    # Setup wizard configuration (capture mode + .env writer)
    register_setup_routes(app)

    # Log search API (generic Zeek/Suricata log browser)
    register_log_routes(app, storage)

    # OpenSearch cluster visibility (health, indices, shards, templates)
    register_opensearch_cluster_routes(app, storage)

    # Logstash monitoring (pipeline stats, JVM, throughput)
    register_logstash_routes(app)

    # Capture mode API (mode-agnostic bridge/mirror endpoints)
    # OLD CODE START — capture_manager was never set, causing 503 on /api/capture/* (2026-03-11)
    # register_capture_routes(app)   # registered without a capture_manager in the app dict
    # OLD CODE END
    # Provide a stub CaptureManager so endpoints work immediately. The daemon's
    # run() coroutine will replace this with the real BridgeCaptureAdapter or
    # MirrorManager once it finishes initialising the capture pipeline.
    if "capture_manager" not in app:
        app["capture_manager"] = CaptureManagerStub()
    register_capture_routes(app)

    # DHCP gateway go-live (preflight / enable / disable / status)
    register_dhcp_gateway_routes(app)

    # Device Registry v2 (MAC-keyed device inventory + UniFi integration)
    # The changelog is built first so the registry can log each new device to it
    changelog_service = ChangelogService(client=storage._client)
    # OLD CODE START — 2026-11-01: the registry now logs new devices to the changelog
    # device_registry = DeviceRegistry(client=storage._client)
    # OLD CODE END
    # NET-200: the owner's names and pictures; built first so the registry, IoT and backup share it
    device_custom = DeviceCustomStore()
    # OLD CODE START — NET-200: no owner names
    # device_registry = DeviceRegistry(
    #     client=storage._client, changelog=changelog_service
    # )
    # OLD CODE END
    device_registry = DeviceRegistry(
        client=storage._client, changelog=changelog_service, custom=device_custom
    )
    unifi_integration = UnifiIntegration()
    if unifi_integration.load_config():
        logger.info("UniFi integration restored from saved config")
    register_devices_v2_routes(app, device_registry, unifi_integration)
    register_device_custom_routes(app, device_custom)

    # Live connection tracking (real-time connection monitor)
    live_tracker = LiveConnectionTracker(client=storage._client)
    register_live_routes(app, live_tracker)

    # Bandwidth tracking (monthly/daily usage, data cap, heatmap)
    bandwidth_tracker = BandwidthTracker(client=storage._client)
    register_bandwidth_routes(app, bandwidth_tracker)

    # Live bandwidth per device: kernel byte counters on the capture interface (NET-205)
    register_live_bandwidth_routes(app)

    # Notification hub (multi-channel notifications + routing rules)
    notification_config = os.environ.get(
        "NOTIFICATION_CONFIG", "/opt/nettap/data/notifications.json"
    )
    notification_hub = NotificationHub(config_path=notification_config)
    register_notification_hub_routes(app, notification_hub)
    # NET-224: alerts reach the channels from here, with or without a browser open
    alert_dispatcher = AlertDispatcher(
        notification_hub,
        storage._client,
        lambda: lan_cidrs(app),
        os.path.join(
            os.path.dirname(notification_config), "notification-dispatch.json"
        ),
    )
    app.cleanup_ctx.append(alert_dispatcher.ctx)

    # Changelog (network event audit log)
    # OLD CODE START — 2026-11-01: built above, before the device registry, which logs new devices to it
    # changelog_service = ChangelogService(client=storage._client)
    # OLD CODE END
    app["changelog_service"] = changelog_service
    register_changelog_routes(app, changelog_service)

    # Certificate monitor (TLS certificate tracking from Zeek SSL logs)
    # OLD CODE START — NET-154: the shared client retries timeouts 3x, so one certificate pass
    # could outlive the web proxy's timeout and keep loading OpenSearch after the page gave up
    # cert_monitor = CertificateMonitor(client=storage._client)
    # OLD CODE END
    cert_monitor = CertificateMonitor(
        client=OpenSearch(
            **storage.client_kwargs(max_retries=0, retry_on_timeout=False)
        )
    )
    register_certificate_routes(app, cert_monitor)

    # DNS analytics (domain stats, NXDOMAIN, tunneling detection)
    register_dns_routes(app, storage)

    # IoT device monitoring (classification, baselines, anomaly detection)
    register_iot_routes(app, storage)

    # LAN security (ARP spoofing, rogue DHCP, IP conflicts)
    register_lan_security_routes(app, storage)

    # Suricata rule source management (update-sources.yaml + docker exec)
    suricata_sources_config = os.environ.get(
        "SURICATA_SOURCES_CONFIG",
        os.path.join(
            os.path.dirname(__file__), "../config/suricata/update-sources.yaml"
        ),
    )
    suricata_rule_manager = SuricataRuleManager(sources_config=suricata_sources_config)
    register_suricata_rules_routes(app, suricata_rule_manager)

    # MAC correlation (randomized MAC detection + device merging)
    mac_merge_file = os.environ.get(
        "MAC_MERGE_FILE", "/opt/nettap/data/mac_merges.json"
    )
    mac_correlator = MACCorrelator(client=storage._client, merge_file=mac_merge_file)
    register_mac_correlation_routes(app, mac_correlator)

    # PCAP search (file listing, BPF filter search, preview, download)
    pcap_search_dir = os.environ.get("PCAP_DIR", "/opt/nettap/pcap")
    # OLD CODE START — NET-188: its own semaphore let 4 readers run on the 1-CPU container
    # pcap_search_service = PcapSearchService(pcap_dir=pcap_search_dir)
    # OLD CODE END
    pcap_search_service = PcapSearchService(
        pcap_dir=pcap_search_dir, semaphore=tshark_service.semaphore
    )
    register_pcap_routes(app, pcap_search_service)

    # Capture control (PCAP collection on/off + file size config)
    register_capture_control_routes(app, env_file=env_file)

    # Config backup/restore (export/import all settings)
    # OLD CODE: config_backup = ConfigBackup() (NET-200: names and pictures are backed up)
    # OLD CODE: config_backup = ConfigBackup(device_custom=device_custom) (NET-224: notifications restore through the hub)
    config_backup = ConfigBackup(
        device_custom=device_custom, notification_hub=notification_hub
    )
    register_backup_routes(app, config_backup)

    # Threat Intelligence (unified report, beaconing, lateral movement, DNS anomalies, TI)
    register_threat_routes(app, storage)

    # Drill-down pages (NET-160): an address, a domain, a Suricata category, and the LAN rule
    # the web links by.
    # A client without retries, as for certificates, so a request can't outlive its budget
    drill_client = OpenSearch(
        **storage.client_kwargs(max_retries=0, retry_on_timeout=False)
    )
    register_network_routes(app)
    register_address_routes(app, drill_client)
    register_domain_routes(app, drill_client)
    register_suricata_category_routes(app, drill_client)

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
    retention_config_manager: RetentionConfigManager | None = None,
    http_auth: tuple[str, str] | None = None,
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
        retention_config_manager: Optional RetentionConfigManager for the
            ``POST /api/storage/config`` endpoint.
        http_auth: Optional (username, password) tuple for OpenSearch auth.

    Returns:
        The aiohttp.web.AppRunner that must be cleaned up on shutdown
        via ``await runner.cleanup()``.
    """
    app = create_app(
        storage,
        smart,
        opensearch_url,
        retention_config_manager=retention_config_manager,
        http_auth=http_auth,
    )
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger.info("HTTP API server listening on 0.0.0.0:%d", port)
    return runner
