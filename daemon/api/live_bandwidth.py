"""
NetTap live bandwidth API (NET-205).

GET /api/live-bandwidth?mac=aa:bb:cc:dd:ee:ff   (the MAC device page)
GET /api/live-bandwidth?ip=192.168.1.5          (the IP device page)

Each poll is the keepalive for that device's watch; see services/live_bandwidth.py.
"""

import ipaddress
import logging

from aiohttp import web

from api.dhcp_gateway import CAPTURE_LOCK_KEY
from services.device_custom import normalize_mac
from services.excluded_ips import (
    RFC1918_CIDRS,
    RFC1918_SOURCE_FILTER,
    cidr,
    lan_subnets_of,
    parse_single_ip,
)
from services.live_bandwidth import (
    LiveBandwidthBusyError,
    LiveBandwidthError,
    LiveBandwidthMeter,
)
from services.live_bandwidth_tc import Key

logger = logging.getLogger("nettap.api.live_bandwidth")

METER_KEY = "live_bandwidth"


class KeyError400(ValueError):
    """The query doesn't name exactly one valid device key."""


def _mac_key(raw: str) -> Key:
    try:
        mac = normalize_mac(raw).lower()
    except ValueError as exc:
        raise KeyError400("Not a valid MAC address.") from exc
    first = int(mac[:2], 16)
    if first & 1 or mac == "00:00:00:00:00:00":
        raise KeyError400("A broadcast, multicast or empty MAC address isn't a device.")
    return Key("mac", mac)


def _ip_key(raw: str, lan_filter: dict | None) -> Key:
    canonical = parse_single_ip(raw)
    if canonical is None or ":" in canonical:
        raise KeyError400("Not a valid IPv4 address.")
    address = ipaddress.ip_address(canonical)
    subnets = lan_subnets_of(lan_filter)
    networks = [ipaddress.ip_network(cidr(s)) for s in subnets] or [
        ipaddress.ip_network(c) for c in RFC1918_CIDRS
    ]
    if not any(address in net for net in networks):
        raise KeyError400("Live bandwidth only measures addresses on your network.")
    return Key("ip", canonical)


def parse_key(query, lan_filter: dict | None) -> Key:
    """Exactly one of mac= or ip=, validated."""
    macs, ips = query.getall("mac", []), query.getall("ip", [])
    if len(macs) + len(ips) != 1:
        raise KeyError400("Give exactly one device: mac= or ip=.")
    return _mac_key(macs[0]) if macs else _ip_key(ips[0], lan_filter)


async def handle_live_bandwidth(request: web.Request) -> web.Response:
    """GET /api/live-bandwidth: one device's live download and upload rate."""
    lan_filter = request.app.get("lan_filter", RFC1918_SOURCE_FILTER)
    try:
        key = parse_key(request.query, lan_filter)
    except KeyError400 as exc:
        return web.json_response({"error": str(exc)}, status=400)
    meter: LiveBandwidthMeter = request.app[METER_KEY]
    try:
        return web.json_response(await meter.watch(key))
    except LiveBandwidthBusyError as exc:
        return web.json_response({"error": str(exc)}, status=503)
    except LiveBandwidthError as exc:
        logger.warning("Live bandwidth for %s %s failed: %s", key.kind, key.value, exc)
        return web.json_response({"error": str(exc)}, status=500)


def register_live_bandwidth_routes(app: web.Application) -> LiveBandwidthMeter:
    """Create the meter, remove its filters on shutdown, and add the route."""
    meter = LiveBandwidthMeter(
        get_manager=lambda: app.get("capture_manager"),
        get_capture_lock=lambda: app.get(CAPTURE_LOCK_KEY),
    )
    app[METER_KEY] = meter
    app.on_cleanup.append(meter.shutdown)
    app.router.add_get("/api/live-bandwidth", handle_live_bandwidth)
    return meter
