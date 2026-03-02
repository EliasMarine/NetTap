"""
NetTap NIC Identification API Route

Provides an endpoint to blink a physical NIC's LEDs for visual identification
during initial setup.

Two blink strategies (tried in order):

1. **ethtool -p** — classic identify blink.  Works on most drivers that
   implement ``set_phys_id``.  Blocks for the requested duration.

2. **sysfs LED class** — for drivers like ``igc`` (Intel I226-V) that expose
   ``/sys/class/leds/igc-<pci>-led*`` but do NOT implement ``set_phys_id``.
   We set ``trigger=timer`` with fast on/off delays, sleep for the duration,
   then restore ``trigger=none``.

Both strategies use ``nsenter -t 1 -n`` when running inside Docker with
``pid: host`` to operate on the host's network namespace / sysfs.
"""

import asyncio
import logging
import os
import re
import shutil
from pathlib import Path

from aiohttp import web

logger = logging.getLogger("nettap.api.nic_identify")

# Interface name validation: only alphanumeric, hyphens, and underscores.
# This prevents shell injection via the interface parameter.
_VALID_IFACE_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

# Duration limits
_DEFAULT_DURATION = 15
_MAX_DURATION = 30
_MIN_DURATION = 1

# Sysfs LED paths — check host mount first, then local
_HOST_SYS_LEDS = os.environ.get("HOST_SYS_LEDS", "/host/sys/class/leds")
_LOCAL_SYS_LEDS = "/sys/class/leds"


# ---------------------------------------------------------------------------
# Sysfs LED blink (igc fallback)
# ---------------------------------------------------------------------------


def _get_leds_path() -> Path:
    """Return the sysfs leds directory — prefer host mount."""
    host = Path(_HOST_SYS_LEDS)
    if host.is_dir():
        try:
            if any(host.iterdir()):
                return host
        except OSError:
            pass
    return Path(_LOCAL_SYS_LEDS)


def _find_igc_leds(interface: str) -> list[Path]:
    """Find igc LED sysfs paths that belong to a given network interface.

    igc LEDs are named like: igc-0000:03:00.0-led0, igc-0000:03:00.0-led1
    The PCI address maps to the interface via /sys/class/net/<iface>/device.
    """
    leds_path = _get_leds_path()
    # Get the PCI address of the interface from sysfs
    sys_net = Path(os.environ.get("HOST_SYS_NET", "/host/sys/class/net"))
    if not sys_net.is_dir():
        sys_net = Path("/sys/class/net")

    device_link = sys_net / interface / "device"
    try:
        pci_addr = os.path.basename(os.readlink(str(device_link)))
    except (OSError, IOError):
        # Fall back to scanning all igc LEDs if we can't resolve PCI address
        pci_addr = None

    result: list[Path] = []
    try:
        for entry in leds_path.iterdir():
            name = entry.name
            if not name.startswith("igc-"):
                continue
            if pci_addr and pci_addr in name:
                result.append(entry)
            elif not pci_addr:
                # If we can't determine PCI address, collect all igc LEDs
                result.append(entry)
    except (OSError, IOError):
        pass

    return sorted(result, key=lambda p: p.name)


async def _blink_via_sysfs(interface: str, duration: int) -> bool:
    """Blink LEDs via sysfs timer trigger.  Returns True on success."""
    leds = _find_igc_leds(interface)
    if not leds:
        return False

    logger.info("Using sysfs LED blink for %s (%d LEDs found)", interface, len(leds))

    # Enable timer trigger with fast blink (150ms on / 150ms off)
    for led in leds:
        _sysfs_write(led / "trigger", "timer")
        _sysfs_write(led / "delay_on", "150")
        _sysfs_write(led / "delay_off", "150")

    # Schedule cleanup after duration (non-blocking)
    async def _restore():
        await asyncio.sleep(duration)
        for led in leds:
            _sysfs_write(led / "trigger", "none")
            _sysfs_write(led / "brightness", "0")
        logger.info("sysfs LED blink for %s finished", interface)

    asyncio.create_task(_restore())
    return True


def _sysfs_write(path: Path, value: str) -> None:
    """Write a value to a sysfs file.  Silently ignores errors."""
    try:
        path.write_text(value)
    except (OSError, IOError) as exc:
        logger.debug("sysfs write %s=%s failed: %s", path, value, exc)


# ---------------------------------------------------------------------------
# NIC info fallback (when LED blink is unavailable)
# ---------------------------------------------------------------------------


def _get_nic_info(interface: str) -> dict:
    """Read MAC, PCI slot, and driver from sysfs for a given interface.

    Reuses the same host-mount logic as nic_discovery.py — checks
    HOST_SYS_NET first, falls back to /sys/class/net.
    """
    sys_net = Path(os.environ.get("HOST_SYS_NET", "/host/sys/class/net"))
    if not sys_net.is_dir():
        sys_net = Path("/sys/class/net")

    info: dict = {}

    # MAC address
    mac_path = sys_net / interface / "address"
    try:
        info["mac"] = mac_path.read_text().strip()
    except (OSError, IOError):
        info["mac"] = ""

    # PCI slot (from /device symlink basename)
    device_link = sys_net / interface / "device"
    try:
        info["pci_slot"] = os.path.basename(os.readlink(str(device_link)))
    except (OSError, IOError):
        info["pci_slot"] = ""

    # Driver (from /device/driver symlink basename)
    driver_link = sys_net / interface / "device" / "driver"
    try:
        info["driver"] = os.path.basename(os.readlink(str(driver_link)))
    except (OSError, IOError):
        info["driver"] = ""

    return info


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


async def handle_nic_identify(request: web.Request) -> web.Response:
    """POST /api/setup/nics/identify

    Blink a NIC's physical LEDs for identification.

    Request body (JSON):
        interface: str  — network interface name (e.g. "enp3s0")
        duration: int   — seconds to blink (default 15, max 30)

    Returns immediately; the blink runs in the background.

    Strategy:
        1. Try ``ethtool -p`` (via nsenter if in Docker)
        2. If ethtool fails with "Operation not supported" (igc driver),
           fall back to sysfs LED timer trigger

    Security: uses asyncio.create_subprocess_exec (NOT shell=True) with
    arguments passed as a list to prevent command injection.  Interface
    names are validated against a strict regex whitelist.
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
            {
                "error": f"Invalid interface name: '{interface}'. Only alphanumeric characters, hyphens, and underscores are allowed."
            },
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

    # --- Strategy 1: ethtool -p ---
    ethtool_path = shutil.which("ethtool")
    if ethtool_path:
        ethtool_ok = await _try_ethtool(ethtool_path, interface, duration)
        if ethtool_ok:
            logger.info("NIC identify: blinking %s for %ds via ethtool", interface, duration)
            return web.json_response({
                "result": "blinking",
                "interface": interface,
                "duration": duration,
                "method": "ethtool",
            })

    # --- Strategy 2: sysfs LED timer trigger (igc fallback) ---
    sysfs_ok = await _blink_via_sysfs(interface, duration)
    if sysfs_ok:
        logger.info("NIC identify: blinking %s for %ds via sysfs LED", interface, duration)
        return web.json_response({
            "result": "blinking",
            "interface": interface,
            "duration": duration,
            "method": "sysfs_led",
        })

    # --- Both strategies failed — return NIC info as graceful fallback ---
    # Instead of HTTP 500, provide MAC/PCI/driver so the user can still
    # physically identify the NIC by checking labels on the hardware.
    info = _get_nic_info(interface)
    logger.info(
        "NIC identify: LED blink unavailable for %s, returning info fallback", interface
    )
    return web.json_response({
        "result": "info",
        "interface": interface,
        "method": "info",
        **info,
        "message": "LED blink not available \u2014 use MAC address or PCI slot to identify this NIC.",
    })


async def _try_ethtool(ethtool_path: str, interface: str, duration: int) -> bool:
    """Try ``ethtool -p`` (via nsenter if available).  Returns True on success.

    NOTE: All subprocess calls use create_subprocess_exec with arguments
    as a list (never shell=True) to prevent injection.
    """
    nsenter_path = shutil.which("nsenter")
    if nsenter_path:
        cmd = [nsenter_path, "-t", "1", "-n", "--",
               ethtool_path, "-p", interface, str(duration)]
    else:
        cmd = [ethtool_path, "-p", interface, str(duration)]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

        # Give it a moment to fail (e.g. "Operation not supported")
        try:
            await asyncio.wait_for(process.wait(), timeout=0.5)
            stderr_bytes = await process.stderr.read()
            stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
            if process.returncode != 0:
                logger.info("ethtool -p failed for %s: %s", interface, stderr_text)
                return False
        except asyncio.TimeoutError:
            # Still running — means ethtool started successfully and is blinking
            return True

    except (FileNotFoundError, OSError) as exc:
        logger.info("ethtool not available: %s", exc)
        return False

    return True


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_nic_identify_routes(app: web.Application) -> None:
    """Register NIC identification API routes on the given aiohttp application."""
    app.router.add_post("/api/setup/nics/identify", handle_nic_identify)
    logger.info("NIC identify API routes registered (1 endpoint)")
