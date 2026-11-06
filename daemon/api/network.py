"""GET /api/network/lan — the daemon's own LAN rule, so the web app links the same way (NET-160).

Subnets come from the live LAN filter (detected, or LAN_SUBNETS); an empty list means all
of RFC1918. IPv6 is never LAN: every device filter matches IPv4 only.
"""

import hashlib
import logging

from aiohttp import web

from services.excluded_ips import (
    RFC1918_SOURCE_FILTER,
    _parse_manual_subnets,
    lan_subnets_of,
)

logger = logging.getLogger("nettap.api.network")


def _cidr(subnet: tuple[int, int, int]) -> str:
    """(a, b, c) with -1 for any octet, as the filter stores it, in CIDR form."""
    fixed = [o for o in subnet if o != -1]
    octets = [*fixed, *[0] * (4 - len(fixed))]
    return f"{'.'.join(map(str, octets))}/{8 * len(fixed)}"


async def handle_lan(request: web.Request) -> web.Response:
    """GET /api/network/lan → {version, subnets, source, ipv6}."""
    subnets = [
        _cidr(s)
        for s in lan_subnets_of(request.app.get("lan_filter", RFC1918_SOURCE_FILTER))
    ]
    if not subnets:
        source = "rfc1918"
    else:
        # With LAN_SUBNETS set the filter is never re-detected (changed_lan_filter)
        source = "env" if _parse_manual_subnets() else "detected"
    version = hashlib.sha256(",".join(subnets).encode()).hexdigest()[:12]
    return web.json_response(
        {"version": version, "subnets": subnets, "source": source, "ipv6": "not-lan"}
    )


def register_network_routes(app: web.Application) -> None:
    app.router.add_get("/api/network/lan", handle_lan)
    logger.info("Network API routes registered (1 endpoint)")
