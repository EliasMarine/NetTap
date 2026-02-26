"""
NetTap NIC Identification API Route

Provides an endpoint to blink a physical NIC's LEDs using `ethtool -p`,
allowing users to visually identify which Ethernet port corresponds to
which interface name during initial setup.
"""

import asyncio
import logging
import re
import shutil

from aiohttp import web

logger = logging.getLogger("nettap.api.nic_identify")

# Interface name validation: only alphanumeric, hyphens, and underscores.
# This prevents shell injection via the interface parameter.
_VALID_IFACE_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

# Duration limits
_DEFAULT_DURATION = 15
_MAX_DURATION = 30
_MIN_DURATION = 1


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

async def handle_nic_identify(request: web.Request) -> web.Response:
    """POST /api/setup/nics/identify

    Blink a NIC's physical LEDs for identification.

    Request body (JSON):
        interface: str  — network interface name (e.g. "eth0")
        duration: int   — seconds to blink (default 15, max 30)

    Returns immediately; ethtool runs in background for the requested
    duration since `ethtool -p` blocks for the blink period.

    Security: uses asyncio.create_subprocess_exec (NOT shell=True) with
    arguments passed as a list to prevent command injection. Interface
    names are additionally validated against a strict regex whitelist.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Invalid JSON body"},
            status=400,
        )

    # --- Validate interface name ---
    interface = body.get("interface")
    if not interface or not isinstance(interface, str):
        return web.json_response(
            {"error": "Missing or empty 'interface' field"},
            status=400,
        )

    interface = interface.strip()
    if not _VALID_IFACE_RE.match(interface):
        return web.json_response(
            {"error": f"Invalid interface name: '{interface}'. Only alphanumeric characters, hyphens, and underscores are allowed."},
            status=400,
        )

    # --- Validate duration ---
    raw_duration = body.get("duration", _DEFAULT_DURATION)
    try:
        duration = int(raw_duration)
    except (TypeError, ValueError):
        duration = _DEFAULT_DURATION

    if duration < _MIN_DURATION:
        duration = _MIN_DURATION
    if duration > _MAX_DURATION:
        duration = _MAX_DURATION

    # --- Check ethtool availability ---
    ethtool_path = shutil.which("ethtool")
    if ethtool_path is None:
        return web.json_response(
            {
                "error": "ethtool is not installed",
                "hint": "Install with: apt install ethtool",
            },
            status=500,
        )

    # --- Launch ethtool in background ---
    # ethtool -p <interface> <duration> blinks the NIC LEDs.
    # It blocks for the duration, so we run it as a background subprocess
    # and return immediately to the caller.
    #
    # NOTE: We use create_subprocess_exec (not create_subprocess_shell)
    # to avoid shell injection. All arguments are passed as separate list
    # elements, never interpolated into a shell string.
    try:
        process = await asyncio.create_subprocess_exec(
            ethtool_path, "-p", interface, str(duration),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

        # Check very briefly that the process started successfully.
        # Give it a moment to fail (e.g. invalid interface) before
        # declaring success.
        try:
            await asyncio.wait_for(process.wait(), timeout=0.5)
            # Process exited within 0.5s — it likely errored
            stderr_bytes = await process.stderr.read()
            stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
            if process.returncode != 0:
                return web.json_response(
                    {"error": f"ethtool failed: {stderr_text or 'unknown error'}"},
                    status=500,
                )
        except asyncio.TimeoutError:
            # Process is still running (expected — it blocks for `duration` seconds).
            # This means ethtool started successfully and is blinking the LEDs.
            pass

    except FileNotFoundError:
        return web.json_response(
            {
                "error": "ethtool is not installed",
                "hint": "Install with: apt install ethtool",
            },
            status=500,
        )
    except OSError as exc:
        return web.json_response(
            {"error": f"Failed to start ethtool: {exc}"},
            status=500,
        )

    logger.info("NIC identify: blinking %s for %ds", interface, duration)

    return web.json_response({
        "result": "blinking",
        "interface": interface,
        "duration": duration,
    })


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_nic_identify_routes(app: web.Application) -> None:
    """Register NIC identification API routes on the given aiohttp application."""
    app.router.add_post("/api/setup/nics/identify", handle_nic_identify)
    logger.info("NIC identify API routes registered (1 endpoint)")
