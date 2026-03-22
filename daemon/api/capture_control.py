"""
NetTap Capture Control API Routes

Manages the nettap-pcap-capture Docker container (netsniff-ng raw packet
capture).  Provides endpoints to start/stop capture, read/update the max
PCAP file rotation size, and persist settings to the environment file.

Endpoints:
    GET  /api/capture/status     Read capture state + container status
    PUT  /api/capture/toggle     Start or stop the pcap-capture container
    PUT  /api/capture/settings   Update max file size (10-10000 MB)
"""

import asyncio
import logging

from aiohttp import web

from api.settings import _load_env_file, _save_env_file

logger = logging.getLogger("nettap.api.capture_control")

CONTAINER_NAME = "nettap-pcap-capture"
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
    try:
        max_file_size = int(env.get("PCAP_ROTATE_MB", str(DEFAULT_MAX_FILE_SIZE_MB)))
    except (ValueError, TypeError):
        max_file_size = DEFAULT_MAX_FILE_SIZE_MB
    return {"enabled": enabled, "maxFileSizeMB": max_file_size}


async def _docker_cmd(action: str, container: str) -> tuple[int, str]:
    """Run a docker command (start/stop/restart) on a container.

    Uses create_subprocess_exec with explicit argument arrays to prevent
    shell injection.  Never passes user input through a shell.

    Args:
        action: One of "start", "stop", "restart".
        container: The Docker container name.

    Returns:
        Tuple of (return_code, combined_output).
    """
    proc = await asyncio.create_subprocess_exec(
        "docker", action, container,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
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
        "docker", "inspect",
        "--format", "{{.State.Running}}|{{.State.Status}}",
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
    return web.json_response({
        "enabled": config["enabled"],
        "maxFileSizeMB": config["maxFileSizeMB"],
        "containerRunning": container["running"],
        "containerStatus": container["status"],
    })


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
        return web.json_response(
            {"error": "'enabled' must be a boolean"}, status=400
        )

    env_file = _get_env_file(request.app)

    # Persist to env file
    _save_env_file(env_file, {"PCAP_CAPTURE_ENABLED": "true" if enabled else "false"})

    # Start or stop the container
    action = "start" if enabled else "stop"
    returncode, output = await _docker_cmd(action, CONTAINER_NAME)
    if returncode != 0:
        logger.warning(
            "docker %s %s failed (rc=%d): %s",
            action, CONTAINER_NAME, returncode, output,
        )

    container = await _get_container_status(CONTAINER_NAME)
    return web.json_response({
        "enabled": enabled,
        "containerRunning": container["running"],
        "containerStatus": container["status"],
    })


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

    env_file = _get_env_file(request.app)

    # Persist to env file
    _save_env_file(env_file, {"PCAP_ROTATE_MB": str(max_size)})

    # Restart container if it is currently running so it picks up the new size
    container = await _get_container_status(CONTAINER_NAME)
    restarted = False
    if container["running"]:
        returncode, output = await _docker_cmd("restart", CONTAINER_NAME)
        if returncode != 0:
            logger.warning(
                "docker restart %s failed (rc=%d): %s",
                CONTAINER_NAME, returncode, output,
            )
        restarted = True

    return web.json_response({
        "maxFileSizeMB": max_size,
        "restarted": restarted,
    })


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
                CONTAINER_NAME, returncode, output,
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
