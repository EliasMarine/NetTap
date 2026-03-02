"""
NetTap NIC Discovery API Route

Detects physical network interfaces on the host for the setup wizard.
Reads from /sys/class/net/ (or a host-mounted path when running inside
Docker) and optionally uses ``ip -j addr show`` (via nsenter into the
host network namespace) to resolve IPv4 addresses.
"""

import asyncio
import json as json_mod
import logging
import os
from pathlib import Path

from aiohttp import web

logger = logging.getLogger("nettap.api.nic_discovery")

# When running in Docker, /sys/class/net shows container interfaces.
# Mount the host's sysfs via docker-compose:
#   volumes: ["/sys/class/net:/host/sys/class/net:ro"]
# The code checks HOST_SYS_NET first, then falls back to the local path.
HOST_SYS_NET = os.environ.get("HOST_SYS_NET", "/host/sys/class/net")
LOCAL_SYS_NET = "/sys/class/net"

# Interface type constants from <linux/if_arp.h>
ARPHRD_ETHER = 1
ARPHRD_LOOPBACK = 772

# Prefixes for interfaces that are never useful for bridge selection.
_EXCLUDE_PREFIXES = ("docker", "br-", "veth", "virbr", "flannel", "cni", "cali")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_sys_net_path() -> Path:
    """Return the sysfs net directory — prefer host mount, fall back to local."""
    host = Path(HOST_SYS_NET)
    if host.is_dir():
        try:
            # Make sure it's populated (not an empty mount)
            if any(host.iterdir()):
                return host
        except OSError:
            pass
    return Path(LOCAL_SYS_NET)


def _read_sysfs(path: Path) -> str:
    """Read a single-line sysfs file.  Empty string on any error."""
    try:
        return path.read_text().strip()
    except (OSError, IOError):
        return ""


def _should_exclude(name: str) -> bool:
    """True if an interface should be hidden from the wizard."""
    for prefix in _EXCLUDE_PREFIXES:
        if name.startswith(prefix):
            return True
    return False


def _classify_type(sys_path: Path, name: str) -> str:
    """Classify an interface as ethernet / wireless / virtual / loopback."""
    if name == "lo":
        return "loopback"

    # Wireless interfaces expose a /wireless or /phy80211 subdirectory.
    if (sys_path / name / "wireless").exists() or (sys_path / name / "phy80211").exists():
        return "wireless"

    # Physical devices have a /device symlink; virtual ones don't.
    if not (sys_path / name / "device").exists():
        return "virtual"

    # Check ARP hardware type
    type_val = _read_sysfs(sys_path / name / "type")
    if type_val == str(ARPHRD_LOOPBACK):
        return "loopback"

    return "ethernet"


def _get_driver(sys_path: Path, name: str) -> str:
    """Resolve the kernel driver name from the /device/driver symlink."""
    driver_link = sys_path / name / "device" / "driver"
    try:
        target = os.readlink(str(driver_link))
        return os.path.basename(target)
    except (OSError, IOError):
        return ""


def _get_speed(sys_path: Path, name: str) -> str:
    """Human-readable link speed (e.g. '2.5Gb/s').  Empty if link is down."""
    raw = _read_sysfs(sys_path / name / "speed")
    if not raw or raw == "-1":
        return ""
    try:
        mbps = int(raw)
        if mbps >= 1000:
            gbs = mbps / 1000
            # Avoid ".0" for whole numbers but keep decimals for 2.5G etc.
            if gbs == int(gbs):
                return f"{int(gbs)}Gb/s"
            return f"{gbs}Gb/s"
        return f"{mbps}Mb/s"
    except ValueError:
        return ""


async def _get_ipv4_map() -> dict[str, str]:
    """Return {iface_name: ipv4_address} by running ``ip -j -4 addr show``.

    Tries nsenter into host PID 1 first (Docker with pid: host), then
    falls back to running ip directly (bare-metal or dev environment).

    NOTE: Both nsenter and ip are invoked via create_subprocess_exec with
    arguments as a list (never shell=True) to prevent injection.
    """
    commands = [
        ["nsenter", "-t", "1", "-n", "--", "ip", "-j", "-4", "addr", "show"],
        ["ip", "-j", "-4", "addr", "show"],
    ]
    for cmd in commands:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode != 0:
                continue
            data = json_mod.loads(stdout.decode())
            result: dict[str, str] = {}
            for entry in data:
                ifname = entry.get("ifname", "")
                addr_info = entry.get("addr_info", [])
                if addr_info:
                    result[ifname] = addr_info[0].get("local", "")
            return result
        except Exception:
            continue
    return {}


# ---------------------------------------------------------------------------
# Core discovery
# ---------------------------------------------------------------------------


async def discover_interfaces() -> list[dict]:
    """Enumerate host network interfaces from sysfs + ip.

    Returns a list of dicts matching the ``NetworkInterface`` schema the
    frontend expects (name, mac, state, speed, driver, ipv4, type).
    """
    sys_path = _get_sys_net_path()
    logger.info("Discovering NICs from %s", sys_path)

    try:
        iface_names = sorted(
            entry.name
            for entry in sys_path.iterdir()
            if entry.is_dir() or entry.is_symlink()
        )
    except (OSError, IOError) as exc:
        logger.error("Cannot read sysfs net dir %s: %s", sys_path, exc)
        return []

    # Fetch IPv4 addresses concurrently while we iterate sysfs.
    ipv4_map = await _get_ipv4_map()

    interfaces: list[dict] = []
    for name in iface_names:
        if _should_exclude(name):
            continue

        mac = _read_sysfs(sys_path / name / "address")
        # Skip all-zero MACs (virtual/unnamed) except loopback
        if mac == "00:00:00:00:00:00" and name != "lo":
            continue

        operstate = _read_sysfs(sys_path / name / "operstate")
        if operstate == "up":
            state = "up"
        elif operstate == "down":
            state = "down"
        else:
            state = "unknown"

        iface: dict = {
            "name": name,
            "mac": mac,
            "state": state,
            "speed": _get_speed(sys_path, name),
            "driver": _get_driver(sys_path, name),
            "type": _classify_type(sys_path, name),
        }

        ipv4 = ipv4_map.get(name, "")
        if ipv4:
            iface["ipv4"] = ipv4

        interfaces.append(iface)

    logger.info(
        "Discovered %d interfaces (%d usable)",
        len(interfaces),
        sum(1 for i in interfaces if i["type"] in ("ethernet", "wireless")),
    )
    return interfaces


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


async def handle_nic_list(request: web.Request) -> web.Response:
    """GET /api/setup/nics — Return detected host network interfaces."""
    interfaces = await discover_interfaces()
    return web.json_response({
        "interfaces": interfaces,
        "source": "daemon",
    })


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_nic_discovery_routes(app: web.Application) -> None:
    """Register NIC discovery API routes on the aiohttp application."""
    app.router.add_get("/api/setup/nics", handle_nic_list)
    logger.info("NIC discovery API routes registered (1 endpoint)")
