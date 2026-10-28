"""
NetTap IP Lookup API Routes

Registers WHOIS and reverse-DNS lookup endpoints with the aiohttp application.
These endpoints provide on-demand IP investigation tools for the web dashboard.
"""

import asyncio
import ipaddress
import logging
import re
import socket

from aiohttp import web

logger = logging.getLogger("nettap.api.lookup")

# Common WHOIS field patterns (case-insensitive)
_WHOIS_FIELD_MAP = {
    "netrange": ["NetRange", "inetnum"],
    "cidr": ["CIDR"],
    "netname": ["NetName", "netname"],
    "orgname": ["OrgName", "org-name", "descr"],
    "country": ["Country", "country"],
    "regdate": ["RegDate"],
    "updated": ["Updated"],
    "ref": ["Ref"],
}


def _parse_whois(raw: str) -> dict:
    """Extract structured fields from raw WHOIS output."""
    parsed: dict[str, str] = {}
    for key, patterns in _WHOIS_FIELD_MAP.items():
        for pattern in patterns:
            match = re.search(
                rf"^{re.escape(pattern)}:\s*(.+)$", raw, re.MULTILINE | re.IGNORECASE
            )
            if match:
                parsed[key] = match.group(1).strip()
                break
    return parsed


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_whois_lookup(request: web.Request) -> web.Response:
    """GET /api/lookup/whois/{ip}

    Run a WHOIS lookup for the given IP address.
    Returns raw output plus parsed structured fields.
    """
    raw_ip = request.match_info["ip"]

    try:
        ipaddress.ip_address(raw_ip)
    except ValueError:
        return web.json_response(
            {"error": f"Invalid IP address: {raw_ip}"}, status=400
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            "whois",
            raw_ip,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        raw_output = stdout.decode("utf-8", errors="replace")
        parsed = _parse_whois(raw_output)

        return web.json_response(
            {"ip": raw_ip, "raw": raw_output, "parsed": parsed, "error": None}
        )

    except asyncio.TimeoutError:
        # Kill the process if it's still running
        try:
            proc.kill()  # type: ignore[possibly-undefined]
        except ProcessLookupError:
            pass
        return web.json_response(
            {
                "ip": raw_ip,
                "raw": "",
                "parsed": {},
                "error": "WHOIS lookup timed out",
            }
        )

    except Exception as exc:
        logger.exception("WHOIS lookup failed for %s", raw_ip)
        return web.json_response(
            {"error": f"WHOIS lookup failed: {exc}"}, status=500
        )


async def handle_dns_lookup(request: web.Request) -> web.Response:
    """GET /api/lookup/dns/{ip}

    Perform reverse DNS lookup for the given IP address.
    Returns hostname, aliases, and forward-resolved addresses.
    """
    raw_ip = request.match_info["ip"]

    try:
        ipaddress.ip_address(raw_ip)
    except ValueError:
        return web.json_response(
            {"error": f"Invalid IP address: {raw_ip}"}, status=400
        )

    loop = asyncio.get_event_loop()

    try:
        hostname, aliases, addrs = await loop.run_in_executor(
            None, socket.gethostbyaddr, raw_ip
        )
    except socket.herror:
        return web.json_response(
            {
                "ip": raw_ip,
                "hostname": None,
                "aliases": [],
                "addresses": [],
                "error": "No reverse DNS record found",
            }
        )
    except Exception as exc:
        logger.exception("DNS lookup failed for %s", raw_ip)
        return web.json_response(
            {"error": f"DNS lookup failed: {exc}"}, status=500
        )

    # Forward lookup to get all addresses for the hostname
    forward_addrs: list[str] = []
    try:
        addrinfo = await loop.run_in_executor(
            None, socket.getaddrinfo, hostname, None
        )
        forward_addrs = list({ai[4][0] for ai in addrinfo})
    except socket.gaierror:
        # Forward lookup failed; return what we have from reverse
        forward_addrs = list(addrs)

    return web.json_response(
        {
            "ip": raw_ip,
            "hostname": hostname,
            "aliases": list(aliases),
            "addresses": forward_addrs,
            "error": None,
        }
    )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_lookup_routes(app: web.Application) -> None:
    """Register all IP lookup API routes on the given aiohttp application."""
    app.router.add_get("/api/lookup/whois/{ip}", handle_whois_lookup)
    app.router.add_get("/api/lookup/dns/{ip}", handle_dns_lookup)
    logger.info("Lookup API routes registered (2 endpoints)")
