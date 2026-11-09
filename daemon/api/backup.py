"""
NetTap Backup API Routes

Registers endpoints for config export, import, and validation.

Endpoints:
    GET  /api/backup/export    Download config JSON
    POST /api/backup/import    Upload + validate + apply config
                               (?apply_capture=1 also restores the capture mode)
    POST /api/backup/validate  Validate without applying

A9: the capture mode and the retention settings go through the same paths as the
setup wizard and Settings › Retention, and the running daemon reloads what it
keeps in memory, so a restore takes effect at once and says what it skipped.
"""

import json
import logging
from dataclasses import replace

from aiohttp import web

from api.dhcp_gateway import ensure_capture_lock
from api.offload import run_blocking
from api.setup import _apply_configuration, _build_capture_config
from services.capture_config import capture_config_exists, load_capture_config
from services.capture_manager import CaptureMode
from services.config_backup import ConfigBackup, capture_section
from services.excluded_ips import load_excluded_ips

logger = logging.getLogger("nettap.api.backup")


async def handle_export(request: web.Request) -> web.Response:
    """GET /api/backup/export — Download config JSON."""
    backup: ConfigBackup = request.app["config_backup"]

    try:
        # OLD CODE: config = backup.export_config() (NET-200: photos are read and hashed now, off the loop)
        config = await run_blocking(backup.export_config)
    except Exception as exc:
        logger.error("Error exporting config: %s", exc)
        return web.json_response({"error": f"Config export failed: {exc}"}, status=500)

    return web.json_response(config)


async def handle_import(request: web.Request) -> web.Response:
    """POST /api/backup/import — Upload + validate + apply config.

    Body: JSON config object (as exported by /api/backup/export).
    """
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    backup: ConfigBackup = request.app["config_backup"]

    try:
        # OLD CODE: result = backup.import_config(data) (NET-200: photo writes and fsyncs, off the loop)
        result = await run_blocking(backup.import_config, data)
        if result.get("skipped") is not None:  # validated: the live sections follow
            sections = data.get("sections", {})
            _reload_running_state(request.app, result["applied"])
            await _restore_retention(request.app, sections, result)
            await _restore_capture(
                request.app,
                backup,
                sections,
                result,
                request.query.get("apply_capture") == "1",
            )
            result["success"] = not result["errors"]
    except Exception as exc:
        logger.error("Error importing config: %s", exc)
        return web.json_response({"error": f"Config import failed: {exc}"}, status=500)

    status = 200 if result["success"] else 400
    return web.json_response(result, status=status)


def _reload_running_state(app: web.Application, applied: list[str]) -> None:
    """A9: what the daemon holds in memory, so restored files take effect without a restart."""
    if "excluded_ips" in applied:
        ips = load_excluded_ips(app.get("excluded_ips_file"))
        # the box's own IP is excluded at runtime only (create_app), so it isn't in the file
        appliance = app.get("appliance_ip")
        app["excluded_ips"] = (
            [*ips, appliance] if appliance and appliance not in ips else ips
        )
    if "bandwidth_cap" in applied and "bandwidth_tracker" in app:
        app["bandwidth_tracker"]._load_cap()
    notifications = {"notification_channels", "notification_rules"}
    if notifications & set(applied) and "notification_hub" in app:
        app["notification_hub"]._load_config()


async def _restore_retention(
    app: web.Application, sections: dict, result: dict
) -> None:
    """Through POST /api/storage/config's path: save, hot-reload, ILM (A9)."""
    if "storage_retention" not in sections:
        return
    values = sections["storage_retention"]
    if not values:
        result["skipped"].append(
            {
                "section": "storage_retention",
                "reason": "This backup has no retention settings (made before they were backed up)",
            }
        )
        return
    from api.server import save_retention_config  # server imports this module

    if not isinstance(values, dict):
        status, payload = 400, {"error": "not a JSON object"}
    else:
        status, payload = await save_retention_config(app, values)
    if status != 200:
        result["errors"].append(
            f"Retention settings not restored: {payload.get('error', status)}"
        )
        return
    result["applied"].append("storage_retention")
    if not payload.get("ilm_applied"):
        result["warnings"].append(
            "Retention settings restored; OpenSearch hasn't taken them yet, "
            "so NetTap keeps trying"
        )


def _skip(result: dict, reason: str) -> None:
    result["skipped"].append({"section": "capture_mode_config", "reason": reason})


async def _restore_capture(
    app: web.Application,
    backup: ConfigBackup,
    sections: dict,
    result: dict,
    confirmed: bool,
) -> None:
    """Through the setup wizard's path (its checks, container restarts), only when confirmed."""
    if "capture_mode_config" not in sections:
        return
    raw = sections["capture_mode_config"]
    wanted = capture_section(raw)
    if not raw:
        return _skip(
            result, "This backup has no capture mode (made before it was backed up)"
        )
    if not wanted:
        result["errors"].append(
            "Capture mode not restored: this backup's mode isn't valid"
        )
        return
    if wanted == await run_blocking(backup.current_capture):
        return _skip(result, "Already the current capture mode")
    if not confirmed:
        return _skip(
            result,
            "Not applied: restoring it restarts capture, and that wasn't confirmed",
        )
    try:
        cfg = _build_capture_config(wanted)  # validates interface names and the subnet
    except (ValueError, TypeError) as exc:
        result["errors"].append(f"Capture mode not restored: {exc}")
        return
    if capture_config_exists():
        # keep the box's PCAP rotation size (setup's INI), so the INI and capture.env agree
        cfg = replace(cfg, pcap_rotate_mb=load_capture_config().pcap_rotate_mb)
    # only validated values reach the files setup writes (never the backup's own)
    body = capture_section(
        {
            "capture_mode": cfg.mode.value,
            "capture_interface": cfg.interface,
            "management_interface": cfg.management,
            "wan_interface": cfg.wan_interface,
            "lan_interface": cfg.lan_interface,
            "dhcp_subnet": cfg.dhcp_subnet,
        }
    )
    async with ensure_capture_lock(app):
        response = await _apply_configuration(app, body, cfg)
    payload = json.loads(response.text)
    if response.status >= 400:
        result["errors"].append(f"Capture mode not restored: {payload.get('error')}")
        return
    restart_errors = payload.get("capture_restart", {}).get("errors", [])
    if restart_errors:
        result["errors"].append(
            "Capture mode saved, but the capture containers didn't restart: "
            f"{'; '.join(restart_errors)}. They use it when they next start."
        )
        return
    result["applied"].append("capture_mode_config")
    result["warnings"].extend(payload.get("warnings", []))
    if cfg.mode != CaptureMode.MIRROR:
        result["warnings"].append(
            f"The capture mode is now {cfg.mode.value.replace('_', ' ')}: "
            "open Go Live to finish switching."
        )


async def handle_validate(request: web.Request) -> web.Response:
    """POST /api/backup/validate — Validate without applying.

    Body: JSON config object.
    """
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    backup: ConfigBackup = request.app["config_backup"]

    try:
        validation = backup.validate_import(data)
    except Exception as exc:
        logger.error("Error validating config: %s", exc)
        return web.json_response(
            {"error": f"Config validation failed: {exc}"}, status=500
        )

    return web.json_response(validation)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_backup_routes(app: web.Application, backup: ConfigBackup) -> None:
    """Register backup API routes."""
    app["config_backup"] = backup

    app.router.add_get("/api/backup/export", handle_export)
    app.router.add_post("/api/backup/import", handle_import)
    app.router.add_post("/api/backup/validate", handle_validate)

    logger.info("Backup API routes registered (3 endpoints)")
