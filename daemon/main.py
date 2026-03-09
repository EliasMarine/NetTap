"""
NetTap Daemon — Entry point

Runs the storage manager and SMART monitor on a periodic async schedule
with graceful signal-based shutdown support.

Phase 2 rewrite: async architecture, signal handling, env-var config,
and aiohttp HTTP health/status API (task 2.10).
"""

# ---------------------------------------------------------------------------
# OLD CODE START — Original synchronous daemon (Phase 1 scaffold)
# Replaced by async implementation with signal handling, comprehensive
# env-var parsing, and graceful shutdown coordination.
# ---------------------------------------------------------------------------
# import os
# import time
# import logging
#
# from storage.manager import StorageManager, RetentionConfig
# from smart.monitor import SmartMonitor
#
# logging.basicConfig(
#     level=logging.INFO,
#     format="[NetTap] %(asctime)s %(levelname)s %(name)s: %(message)s",
# )
# logger = logging.getLogger("nettap")
#
# STORAGE_CHECK_INTERVAL = 300   # 5 minutes
# SMART_CHECK_INTERVAL = 3600    # 1 hour
#
#
# def main():
#     config = RetentionConfig(
#         hot_days=int(os.environ.get("RETENTION_HOT", 90)),
#         warm_days=int(os.environ.get("RETENTION_WARM", 180)),
#         cold_days=int(os.environ.get("RETENTION_COLD", 30)),
#         disk_threshold=int(os.environ.get("DISK_THRESHOLD_PERCENT", 80)) / 100,
#     )
#     opensearch_url = os.environ.get("OPENSEARCH_URL", "http://localhost:9200")
#
#     storage = StorageManager(config, opensearch_url)
#     smart = SmartMonitor()
#
#     logger.info("NetTap daemon started")
#     last_smart_check = 0
#
#     while True:
#         storage.run_cycle()
#
#         now = time.monotonic()
#         if now - last_smart_check >= SMART_CHECK_INTERVAL:
#             smart.check_health()
#             last_smart_check = now
#
#         time.sleep(STORAGE_CHECK_INTERVAL)
#
#
# if __name__ == "__main__":
#     main()
# ---------------------------------------------------------------------------
# OLD CODE END
# ---------------------------------------------------------------------------

import asyncio
import os
import signal
import logging
import sys
from typing import Any

from storage.manager import StorageManager, RetentionConfig
from smart.monitor import SmartMonitor, auto_detect_device
from services.bridge_health import BridgeHealthMonitor
from services.capture_config import load_capture_config
from services.capture_manager import CaptureManager, CaptureMode
from services.bridge_capture_adapter import BridgeCaptureAdapter
from services.bridge_manager import BridgeManager
from services.mirror_manager import MirrorManager
from api.server import start_api

logger = logging.getLogger("nettap")


# ---------------------------------------------------------------------------
# Environment variable parsing
# ---------------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    """Read an integer from an environment variable with a fallback default."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "Invalid integer for %s=%r; using default %d", name, raw, default
        )
        return default


def _env_float(name: str, default: float) -> float:
    """Read a float from an environment variable with a fallback default."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "Invalid float for %s=%r; using default %.2f", name, raw, default
        )
        return default


def _env_str(name: str, default: str) -> str:
    """Read a string from an environment variable with a fallback default."""
    return os.environ.get(name, default)


def _parse_curlrc_credentials(config_file: str) -> tuple[str, str] | None:
    """Parse OpenSearch credentials from a Malcolm curlrc file.

    Malcolm stores credentials in curlrc format, e.g.::

        user = "malcolm_internal:xNa4p..."

    or::

        user: "username:password"

    Args:
        config_file: Path to the curlrc file (e.g.,
            ``/var/local/curlrc/.opensearch.primary.curlrc``).

    Returns:
        Tuple of (username, password) if parsed successfully, None otherwise.
    """
    if not config_file:
        return None

    try:
        with open(config_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Match patterns: user = "u:p", user: "u:p", user "u:p",
                # --user "u:p", -u "u:p"
                if "user" in line.lower():
                    # Extract the value after user/--user/-u and separators
                    # Remove leading keyword and separators
                    for prefix in ("--user", "-u", "user"):
                        if line.lower().startswith(prefix):
                            rest = line[len(prefix):].strip()
                            # Remove = or : separator
                            if rest.startswith(("=", ":")):
                                rest = rest[1:].strip()
                            # Remove surrounding quotes
                            rest = rest.strip('"').strip("'")
                            # Split on first colon: username:password
                            if ":" in rest:
                                username, password = rest.split(":", 1)
                                return (username, password)
                            break
    except FileNotFoundError:
        logger.warning("Curlrc file not found: %s", config_file)
    except (OSError, PermissionError) as exc:
        logger.warning("Cannot read curlrc file %s: %s", config_file, exc)

    return None


def load_config() -> dict[str, Any]:
    """Parse all daemon configuration from environment variables.

    Returns a dict with all config values for easy logging and passing
    to subsystems.

    Supported env vars (with defaults):
      RETENTION_HOT              90     (days)
      RETENTION_WARM             180    (days)
      RETENTION_COLD             30     (days)
      DISK_THRESHOLD_PERCENT     80     (percent, converted to 0.0-1.0)
      EMERGENCY_THRESHOLD_PERCENT 90    (percent, converted to 0.0-1.0)
      OPENSEARCH_URL             http://localhost:9200
      SMART_DEVICE               /dev/nvme0n1
      STORAGE_CHECK_INTERVAL     300    (seconds)
      SMART_CHECK_INTERVAL       3600   (seconds)
      API_PORT                   8880
      LOG_LEVEL                  INFO
    """
    return {
        "retention_hot": _env_int("RETENTION_HOT", 90),
        "retention_warm": _env_int("RETENTION_WARM", 180),
        "retention_cold": _env_int("RETENTION_COLD", 30),
        "disk_threshold": _env_int("DISK_THRESHOLD_PERCENT", 80) / 100.0,
        "emergency_threshold": _env_int("EMERGENCY_THRESHOLD_PERCENT", 90) / 100.0,
        "opensearch_url": _env_str("OPENSEARCH_URL", "http://localhost:9200"),
        "smart_device": _env_str("SMART_DEVICE", "") or auto_detect_device(),
        "storage_check_interval": _env_int("STORAGE_CHECK_INTERVAL", 300),
        "smart_check_interval": _env_int("SMART_CHECK_INTERVAL", 3600),
        "bridge_check_interval": _env_int("BRIDGE_CHECK_INTERVAL", 30),
        "api_port": _env_int("API_PORT", 8880),
        "log_level": _env_str("LOG_LEVEL", "INFO").upper(),
    }


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def configure_logging(level_name: str) -> None:
    """Configure root logging with the NetTap format and the given level."""
    numeric_level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="[NetTap] %(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


# ---------------------------------------------------------------------------
# Async monitoring loops
# ---------------------------------------------------------------------------


async def storage_loop(
    storage: StorageManager,
    interval: int,
    shutdown_event: asyncio.Event,
) -> None:
    """Periodically run the storage manager's maintenance cycle.

    Exits cleanly when *shutdown_event* is set.
    """
    logger.info("Storage monitor loop started (interval=%ds)", interval)
    while not shutdown_event.is_set():
        try:
            storage.run_cycle()
        except Exception:
            logger.exception("Unhandled error in storage cycle")

        # Wait for the interval OR until shutdown is requested
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
            # If we get here, shutdown was requested
            break
        except asyncio.TimeoutError:
            # Normal timeout — loop again
            pass

    logger.info("Storage monitor loop stopped")


async def smart_loop(
    smart: SmartMonitor,
    interval: int,
    shutdown_event: asyncio.Event,
) -> None:
    """Periodically run SMART health checks.

    Exits cleanly when *shutdown_event* is set.
    """
    logger.info("SMART monitor loop started (interval=%ds)", interval)
    while not shutdown_event.is_set():
        try:
            smart.check_health()
        except Exception:
            logger.exception("Unhandled error in SMART check")

        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass

    logger.info("SMART monitor loop stopped")


async def bridge_loop(
    bridge_health: BridgeHealthMonitor,
    interval: int,
    shutdown_event: asyncio.Event,
) -> None:
    """Periodically run bridge health checks.

    Exits cleanly when *shutdown_event* is set.
    """
    logger.info("Bridge health loop started (interval=%ds)", interval)
    while not shutdown_event.is_set():
        try:
            await bridge_health.check_health()
        except Exception:
            logger.exception("Unhandled error in bridge health check")

        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass

    logger.info("Bridge health loop stopped")


async def capture_health_loop(
    capture_mgr: CaptureManager,
    interval: int,
    shutdown_event: asyncio.Event,
) -> None:
    """Periodically run capture health checks for any CaptureManager.

    Used in mirror mode (and potentially other future modes) where
    bridge_loop is not applicable. Calls capture_mgr.get_health()
    and logs the status.

    Exits cleanly when *shutdown_event* is set.
    """
    mode_name = capture_mgr.mode.value
    logger.info(
        "Capture health loop started (mode=%s, interval=%ds)", mode_name, interval
    )
    while not shutdown_event.is_set():
        try:
            health = await capture_mgr.get_health()
            if health.status != "normal":
                logger.warning(
                    "Capture health [%s]: status=%s issues=%s",
                    mode_name,
                    health.status,
                    health.issues,
                )
            else:
                logger.debug(
                    "Capture health [%s]: status=%s interface=%s",
                    mode_name,
                    health.status,
                    health.capture_interface,
                )
        except Exception:
            logger.exception("Unhandled error in capture health check")

        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass

    logger.info("Capture health loop stopped")


# ---------------------------------------------------------------------------
# Main async entry point
# ---------------------------------------------------------------------------


async def async_main() -> None:
    """Async entry point: parse config, wire up subsystems, run loops."""

    # --- Configuration ---
    cfg = load_config()
    configure_logging(cfg["log_level"])

    # --- Log startup config summary ---
    logger.info("=" * 60)
    logger.info("NetTap daemon starting")
    logger.info("=" * 60)
    logger.info("  OpenSearch URL:         %s", cfg["opensearch_url"])
    logger.info(
        "  Retention (hot/warm/cold): %d / %d / %d days",
        cfg["retention_hot"],
        cfg["retention_warm"],
        cfg["retention_cold"],
    )
    logger.info("  Disk threshold:         %.0f%%", cfg["disk_threshold"] * 100)
    logger.info("  Emergency threshold:    %.0f%%", cfg["emergency_threshold"] * 100)
    logger.info("  Storage check interval: %ds", cfg["storage_check_interval"])
    logger.info("  SMART check interval:   %ds", cfg["smart_check_interval"])
    logger.info("  Bridge check interval:  %ds", cfg["bridge_check_interval"])
    logger.info("  SMART device:           %s", cfg["smart_device"])
    logger.info("  API port:               %d", cfg["api_port"])
    logger.info("  Log level:              %s", cfg["log_level"])
    logger.info("=" * 60)

    # --- Parse OpenSearch credentials from curlrc ---
    creds_file = os.environ.get("OPENSEARCH_CREDS_CONFIG_FILE", "")
    http_auth = _parse_curlrc_credentials(creds_file)
    if http_auth:
        logger.info(
            "  OpenSearch auth:        loaded from %s (user=%s)",
            creds_file,
            http_auth[0],
        )
    else:
        logger.warning(
            "  OpenSearch auth:        NO CREDENTIALS — queries may fail with 403. "
            "Set OPENSEARCH_CREDS_CONFIG_FILE or mount curlrc in the container."
        )

    # --- Build subsystems ---
    retention_config = RetentionConfig(
        hot_days=cfg["retention_hot"],
        warm_days=cfg["retention_warm"],
        cold_days=cfg["retention_cold"],
        disk_threshold=cfg["disk_threshold"],
        emergency_threshold=cfg["emergency_threshold"],
    )

    storage = StorageManager(retention_config, cfg["opensearch_url"], http_auth=http_auth)
    smart = SmartMonitor(device=cfg["smart_device"])

    # --- Shutdown coordination ---
    shutdown_event = asyncio.Event()

    def _signal_handler(sig: signal.Signals) -> None:
        sig_name = sig.name if hasattr(sig, "name") else str(sig)
        logger.info("Received %s — initiating graceful shutdown", sig_name)
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler, sig)

    # --- Start HTTP health API ---
    api_runner = await start_api(
        storage,
        smart,
        cfg["opensearch_url"],
        port=cfg["api_port"],
        shutdown_event=shutdown_event,
    )

    # --- Load capture mode configuration ---
    capture_cfg = load_capture_config()
    logger.info("=" * 60)
    logger.info("  Capture mode:           %s", capture_cfg.mode.value)
    if capture_cfg.mode == CaptureMode.MIRROR:
        logger.info("  Mirror interface:       %s", capture_cfg.interface)
        logger.info("  Management interface:   %s", capture_cfg.management or "(not set)")
    else:
        logger.info("  Bridge name:            %s", capture_cfg.bridge_name)
        logger.info("  WAN interface:          %s", capture_cfg.wan_interface)
        logger.info("  LAN interface:          %s", capture_cfg.lan_interface)
    logger.info("=" * 60)

    # --- Initialize capture manager based on mode ---
    capture_manager: CaptureManager | None = None

    if capture_cfg.mode == CaptureMode.BRIDGE:
        # Bridge mode: wrap existing BridgeManager + BridgeHealthMonitor
        bridge_name = capture_cfg.bridge_name
        wan_iface = capture_cfg.wan_interface
        lan_iface = capture_cfg.lan_interface

        bridge_health = BridgeHealthMonitor(
            bridge_name=bridge_name, wan_iface=wan_iface, lan_iface=lan_iface
        )
        bridge_manager = BridgeManager(
            bridge_name=bridge_name,
            netplan_dir=os.environ.get("HOST_NETPLAN_DIR", ""),
            systemd_dir=os.environ.get("HOST_SYSTEMD_DIR", ""),
            sysctl_dir=os.environ.get("HOST_SYSCTL_DIR", ""),
        )
        capture_manager = BridgeCaptureAdapter(
            bridge_manager=bridge_manager,
            bridge_health=bridge_health,
            wan_iface=wan_iface,
            lan_iface=lan_iface,
            bridge_name=bridge_name,
        )
        logger.info("Capture manager: BridgeCaptureAdapter (bridge mode)")

    elif capture_cfg.mode == CaptureMode.MIRROR:
        # Mirror mode: create MirrorManager and configure the NIC
        mirror_manager = MirrorManager(
            interface=capture_cfg.interface,
            management_interface=capture_cfg.management,
        )
        setup_result = await mirror_manager.setup()
        if setup_result.get("success"):
            logger.info(
                "Mirror interface %s configured successfully",
                capture_cfg.interface,
            )
        else:
            logger.error(
                "Mirror interface setup failed: %s",
                setup_result.get("errors", []),
            )
        if setup_result.get("warnings"):
            logger.warning(
                "Mirror setup warnings: %s", setup_result["warnings"]
            )
        capture_manager = mirror_manager
        logger.info("Capture manager: MirrorManager (mirror mode)")

    # --- Start monitoring tasks ---
    storage_task = asyncio.create_task(
        storage_loop(storage, cfg["storage_check_interval"], shutdown_event),
        name="storage-loop",
    )
    smart_task = asyncio.create_task(
        smart_loop(smart, cfg["smart_check_interval"], shutdown_event),
        name="smart-loop",
    )

    # Capture health loop: bridge mode uses the existing bridge_loop;
    # mirror mode (and future modes) use the generic capture_health_loop.
    if capture_cfg.mode == CaptureMode.BRIDGE:
        capture_health_task = asyncio.create_task(
            bridge_loop(bridge_health, cfg["bridge_check_interval"], shutdown_event),
            name="bridge-loop",
        )
    else:
        capture_health_task = asyncio.create_task(
            capture_health_loop(
                capture_manager, cfg["bridge_check_interval"], shutdown_event
            ),
            name="capture-health-loop",
        )

    all_tasks = (storage_task, smart_task, capture_health_task)

    logger.info("All monitoring loops running; waiting for shutdown signal")

    # Wait for shutdown event
    await shutdown_event.wait()

    logger.info("Shutdown requested — waiting for tasks to finish")

    # Cancel tasks and wait for them to complete
    for task in all_tasks:
        task.cancel()

    # Gather with return_exceptions to avoid raising CancelledError
    await asyncio.gather(*all_tasks, return_exceptions=True)

    # --- Cleanup HTTP API ---
    await api_runner.cleanup()
    logger.info("HTTP API server stopped")

    logger.info("NetTap daemon stopped cleanly")


# ---------------------------------------------------------------------------
# Synchronous entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point — run the async main loop."""
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        # This can happen if signal handlers aren't installed (e.g., Windows)
        logger.info("KeyboardInterrupt — shutting down")
        sys.exit(0)


if __name__ == "__main__":
    main()
