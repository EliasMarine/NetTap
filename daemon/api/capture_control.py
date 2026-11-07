"""
NetTap Capture Control API Routes

Manages the nettap-pcap-capture Docker container (netsniff-ng raw packet
capture).  Provides endpoints to start/stop capture, read/update the max
PCAP file rotation size, and persist settings to the environment file.

Endpoints:
    GET  /api/capture/status     Read capture state + container status
    PUT  /api/capture/toggle     Start or stop the pcap-capture container
    PUT  /api/capture/settings   Update max file size (10-10000 MB)

Also provides restart_capture_containers(), used after /etc/nettap/capture.env
changes so the capture containers' entrypoints re-read it.
"""

import asyncio
import logging
import os
from dataclasses import replace

from aiohttp import web

from api.settings import _load_env_file, _save_env_file
from services.capture_config import (
    capture_config_exists,
    load_capture_config,
    save_capture_config,
    write_env_file_if_changed,
)
from services.rules_lock import rules_lock

logger = logging.getLogger("nettap.api.capture_control")

CONTAINER_NAME = "nettap-pcap-capture"
# OLD CODE START — 2026-11-02: arkime-live is off by default (compose profile
# "arkime", tracking-fixes/2026-11-01-dashboard-data-accuracy.md #44)
# CAPTURE_CONTAINERS = (
#     "nettap-zeek-live",
#     "nettap-suricata-live",
#     "nettap-arkime-live",
#     CONTAINER_NAME,
# )
# OLD CODE END
SURICATA_CONTAINER = "nettap-suricata-live"
SURICATA_RESTART_TIMEOUT_S = (
    120  # the restart holds the rules lock, so a hung one must not hold it for ever
)
# Containers whose entrypoint reads /etc/nettap/capture.env
CAPTURE_CONTAINERS = (
    "nettap-zeek-live",
    "nettap-suricata-live",
    CONTAINER_NAME,
)
DEFAULT_ENV_FILE = "/opt/nettap/data/.env"
DEFAULT_MAX_FILE_SIZE_MB = 100
MIN_FILE_SIZE_MB = 10
MAX_FILE_SIZE_MB = 10000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_env_file(app: web.Application) -> str:
    """Get the capture env file path from app config or default."""
    return app.get("capture_env_file", DEFAULT_ENV_FILE)


def _read_capture_config(env_file: str) -> dict:
    """Read capture configuration from the env file.

    Returns:
        {"enabled": bool, "maxFileSizeMB": int}
    """
    env = _load_env_file(env_file)
    enabled_str = env.get("PCAP_CAPTURE_ENABLED", "true").lower()
    enabled = enabled_str != "false"
    # OLD CODE START — 2026-11-02: read a value pcap-capture never sees, so the page
    # showed 100 MB while netsniff rotated at 4096 MiB (docker/.env)
    # try:
    #     max_file_size = int(env.get("PCAP_ROTATE_MB", str(DEFAULT_MAX_FILE_SIZE_MB)))
    # except (ValueError, TypeError):
    #     max_file_size = DEFAULT_MAX_FILE_SIZE_MB
    # OLD CODE END
    return {"enabled": enabled, "maxFileSizeMB": _effective_rotate_mb()}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _effective_rotate_mb() -> int:
    """The size netsniff rotates at: the saved setting, else the compose value
    pcap-capture starts with (PCAP_ROTATE_MB, passed to the daemon the same way)."""
    saved = load_capture_config().pcap_rotate_mb if capture_config_exists() else 0
    return saved or _env_int("PCAP_ROTATE_MB", DEFAULT_MAX_FILE_SIZE_MB)


async def _docker_cmd(
    action: str, container: str, timeout: float | None = None
) -> tuple[int, str]:
    """Run a docker command (start/stop/restart) on a container.

    Uses create_subprocess_exec with explicit argument arrays to prevent
    shell injection.  Never passes user input through a shell.

    Args:
        action: One of "start", "stop", "restart".
        container: The Docker container name.
        timeout: Seconds before the docker command is killed (None = no limit).

    Returns:
        Tuple of (return_code, combined_output).
    """
    proc = await asyncio.create_subprocess_exec(
        "docker",
        action,
        container,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    # OLD CODE START — review round 2: no time limit, so a hung restart held the rules lock indefinitely
    # stdout, stderr = await proc.communicate()
    # OLD CODE END
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return (
            -1,
            f"docker {action} {container} did not finish within {timeout:.0f} s",
        )
    output = (stdout.decode() + stderr.decode()).strip()
    return (proc.returncode, output)


async def _get_container_status(container: str) -> dict:
    """Inspect a Docker container and return its running state.

    Uses create_subprocess_exec with explicit argument arrays to prevent
    shell injection.

    Returns:
        {"running": bool, "status": str}
    """
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "inspect",
        "--format",
        "{{.State.Running}}|{{.State.Status}}",
        container,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning(
            "docker inspect failed for %s: %s", container, stderr.decode().strip()
        )
        return {"running": False, "status": "unknown"}

    raw = stdout.decode().strip()
    parts = raw.split("|", 1)
    running = parts[0].lower() == "true" if parts else False
    status = parts[1] if len(parts) > 1 else "unknown"
    return {"running": running, "status": status}


async def _restart_if_running(container: str) -> tuple[bool, str]:
    """Restart one container if it is running.

    Returns (restarted, error). A stopped container is left stopped:
    ``docker restart`` would start it, and the PCAP toggle stops
    nettap-pcap-capture on purpose. It reads capture.env when it next starts.
    """
    try:
        status = await _get_container_status(container)
        if not status["running"]:
            logger.info("Not restarting %s: it is %s", container, status["status"])
            return False, ""
        # OLD CODE START — NET-191 slice 2: Suricata is restarted only between rule updates
        # returncode, output = await _docker_cmd("restart", container)
        # OLD CODE END
        if container == SURICATA_CONTAINER:
            # Held until docker restart returns, so the new container's startup update can take it
            async with rules_lock():
                returncode, output = await _docker_cmd(
                    "restart", container, timeout=SURICATA_RESTART_TIMEOUT_S
                )
        else:
            returncode, output = await _docker_cmd("restart", container)
    except Exception as exc:  # docker CLI missing, socket unreachable, rules lock busy
        returncode, output = -1, str(exc)
    if returncode != 0:
        logger.warning(
            "docker restart %s failed (rc=%d): %s", container, returncode, output
        )
        return False, f"{container}: {output or f'exit code {returncode}'}"
    return True, ""


async def restart_capture_containers() -> dict:
    """Restart the running capture containers so they re-read capture.env.

    Best effort and never raises: one failure doesn't stop the others.
    Containers are never created or removed.

    Returns:
        {"restarted": [container, ...], "errors": [message, ...]}
    """
    results = await asyncio.gather(
        *(_restart_if_running(c) for c in CAPTURE_CONTAINERS)
    )
    restarted = [c for c, (ok, _) in zip(CAPTURE_CONTAINERS, results) if ok]
    errors = [err for _, err in results if err]
    return {"restarted": restarted, "errors": errors}


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_capture_status(request: web.Request) -> web.Response:
    """GET /api/capture/status

    Returns capture configuration and container state.
    """
    env_file = _get_env_file(request.app)
    config = _read_capture_config(env_file)
    container = await _get_container_status(CONTAINER_NAME)
    return web.json_response(
        {
            "enabled": config["enabled"],
            "maxFileSizeMB": config["maxFileSizeMB"],
            # netsniff-roll.sh also starts a new file after this many minutes
            "rotateMinutes": _env_int("PCAP_ROTATE_MIN", 10),
            "containerRunning": container["running"],
            "containerStatus": container["status"],
        }
    )


async def handle_capture_toggle(request: web.Request) -> web.Response:
    """PUT /api/capture/toggle

    Start or stop the pcap-capture container.
    Body: {"enabled": bool}
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    if not isinstance(body, dict) or "enabled" not in body:
        return web.json_response(
            {"error": "Body must contain 'enabled' boolean field"}, status=400
        )

    enabled = body["enabled"]
    if not isinstance(enabled, bool):
        return web.json_response({"error": "'enabled' must be a boolean"}, status=400)

    env_file = _get_env_file(request.app)

    # Persist to env file
    _save_env_file(env_file, {"PCAP_CAPTURE_ENABLED": "true" if enabled else "false"})

    # Start or stop the container
    action = "start" if enabled else "stop"
    returncode, output = await _docker_cmd(action, CONTAINER_NAME)
    if returncode != 0:
        logger.warning(
            "docker %s %s failed (rc=%d): %s",
            action,
            CONTAINER_NAME,
            returncode,
            output,
        )

    container = await _get_container_status(CONTAINER_NAME)
    return web.json_response(
        {
            "enabled": enabled,
            "containerRunning": container["running"],
            "containerStatus": container["status"],
        }
    )


async def handle_capture_settings(request: web.Request) -> web.Response:
    """PUT /api/capture/settings

    Update the max PCAP file rotation size.
    Body: {"maxFileSizeMB": int}  (10-10000)
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    if not isinstance(body, dict) or "maxFileSizeMB" not in body:
        return web.json_response(
            {"error": "Body must contain 'maxFileSizeMB' integer field"}, status=400
        )

    try:
        max_size = int(body["maxFileSizeMB"])
    except (ValueError, TypeError):
        return web.json_response(
            {"error": "'maxFileSizeMB' must be an integer"}, status=400
        )

    if max_size < MIN_FILE_SIZE_MB or max_size > MAX_FILE_SIZE_MB:
        return web.json_response(
            {
                "error": (
                    f"'maxFileSizeMB' must be between "
                    f"{MIN_FILE_SIZE_MB} and {MAX_FILE_SIZE_MB}"
                )
            },
            status=400,
        )

    # OLD CODE START — 2026-11-02: saved where pcap-capture never reads it
    # env_file = _get_env_file(request.app)
    #
    # # Persist to env file
    # _save_env_file(env_file, {"PCAP_ROTATE_MB": str(max_size)})
    # OLD CODE END
    # capture.env is what pcap-capture's loader reads on (re)start
    if not capture_config_exists():
        return web.json_response(
            {"error": "Finish the setup wizard first: no capture mode is saved yet."},
            status=409,
        )
    config = replace(load_capture_config(), pcap_rotate_mb=max_size)
    save_capture_config(config)
    write_env_file_if_changed(config)

    # Restart container if it is currently running so it picks up the new size
    container = await _get_container_status(CONTAINER_NAME)
    restarted = False
    if container["running"]:
        returncode, output = await _docker_cmd("restart", CONTAINER_NAME)
        if returncode != 0:
            logger.warning(
                "docker restart %s failed (rc=%d): %s",
                CONTAINER_NAME,
                returncode,
                output,
            )
        restarted = True

    return web.json_response(
        {
            "maxFileSizeMB": max_size,
            "restarted": restarted,
        }
    )


# ---------------------------------------------------------------------------
# Startup enforcement
# ---------------------------------------------------------------------------


async def enforce_capture_state(env_file: str) -> None:
    """Enforce capture state on daemon startup.

    If PCAP_CAPTURE_ENABLED is set to false in the env file, stop the
    capture container to ensure it respects the persisted setting.
    """
    config = _read_capture_config(env_file)
    if not config["enabled"]:
        logger.info("Capture disabled in config — stopping %s", CONTAINER_NAME)
        returncode, output = await _docker_cmd("stop", CONTAINER_NAME)
        if returncode != 0:
            logger.warning(
                "Failed to stop %s on startup (rc=%d): %s",
                CONTAINER_NAME,
                returncode,
                output,
            )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_capture_control_routes(
    app: web.Application, env_file: str | None = None
) -> None:
    """Register capture control API routes on the aiohttp application.

    Args:
        app: The aiohttp web application to register routes on.
        env_file: Optional path to the env file. Defaults to /opt/nettap/data/.env.
    """
    app["capture_env_file"] = env_file or DEFAULT_ENV_FILE

    app.router.add_get("/api/capture/status", handle_capture_status)
    app.router.add_put("/api/capture/toggle", handle_capture_toggle)
    app.router.add_put("/api/capture/settings", handle_capture_settings)

    logger.info("Capture control API routes registered")
