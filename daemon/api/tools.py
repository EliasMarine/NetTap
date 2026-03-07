"""
NetTap Tools API Routes

Registers network tool endpoints with the aiohttp application:
- DNS Recon (dig-based structured lookups)
- MAC Address OUI Lookup
- Ping / Traceroute
- SSL Certificate Inspection
"""

import logging
from aiohttp import web

from services.dns_recon_service import DnsReconService, DnsReconValidationError
from services.mac_lookup_service import MacLookupService, MacLookupValidationError
from services.network_diag_service import NetworkDiagService, NetworkDiagValidationError
from services.ssl_cert_service import SslCertService, SslCertValidationError

logger = logging.getLogger("nettap.api.tools")


# ---------------------------------------------------------------------------
# DNS Recon
# ---------------------------------------------------------------------------


async def handle_dns_recon(request: web.Request) -> web.Response:
    """POST /api/tools/dns-recon -- Structured DNS lookup for a domain."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    dns_recon: DnsReconService = request.app["dns_recon"]

    try:
        result = await dns_recon.lookup(
            domain=body.get("domain", ""),
            record_types=body.get("record_types"),
        )
        return web.json_response(result)
    except DnsReconValidationError as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as exc:
        logger.exception("DNS recon failed")
        return web.json_response({"error": f"DNS recon failed: {exc}"}, status=500)


# ---------------------------------------------------------------------------
# MAC Lookup
# ---------------------------------------------------------------------------


async def handle_mac_lookup(request: web.Request) -> web.Response:
    """GET /api/tools/mac-lookup/{mac} -- OUI vendor lookup for a MAC address."""
    raw_mac = request.match_info["mac"]
    mac_lookup: MacLookupService = request.app["mac_lookup"]

    try:
        result = mac_lookup.lookup(raw_mac)
        return web.json_response(result)
    except MacLookupValidationError as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as exc:
        logger.exception("MAC lookup failed")
        return web.json_response({"error": f"MAC lookup failed: {exc}"}, status=500)


# ---------------------------------------------------------------------------
# Ping
# ---------------------------------------------------------------------------


async def handle_ping(request: web.Request) -> web.Response:
    """POST /api/tools/ping -- Ping a target host."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    network_diag: NetworkDiagService = request.app["network_diag"]

    try:
        result = await network_diag.ping(
            target=body.get("target", ""),
            count=body.get("count"),
        )
        return web.json_response(result)
    except NetworkDiagValidationError as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as exc:
        logger.exception("Ping failed")
        return web.json_response({"error": f"Ping failed: {exc}"}, status=500)


# ---------------------------------------------------------------------------
# Traceroute
# ---------------------------------------------------------------------------


async def handle_traceroute(request: web.Request) -> web.Response:
    """POST /api/tools/traceroute -- Traceroute to a target host."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    network_diag: NetworkDiagService = request.app["network_diag"]

    try:
        result = await network_diag.traceroute(
            target=body.get("target", ""),
            max_hops=body.get("max_hops"),
        )
        return web.json_response(result)
    except NetworkDiagValidationError as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as exc:
        logger.exception("Traceroute failed")
        return web.json_response({"error": f"Traceroute failed: {exc}"}, status=500)


# ---------------------------------------------------------------------------
# SSL Certificate
# ---------------------------------------------------------------------------


async def handle_ssl_cert(request: web.Request) -> web.Response:
    """POST /api/tools/ssl-cert -- Inspect SSL/TLS certificate on a remote host."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    ssl_cert: SslCertService = request.app["ssl_cert"]

    try:
        result = await ssl_cert.inspect(
            host=body.get("host", ""),
            port=body.get("port"),
        )
        return web.json_response(result)
    except SslCertValidationError as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as exc:
        logger.exception("SSL cert inspection failed")
        return web.json_response(
            {"error": f"SSL cert inspection failed: {exc}"}, status=500
        )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_tools_routes(
    app: web.Application,
    dns_recon: DnsReconService,
    mac_lookup: MacLookupService,
    network_diag: NetworkDiagService,
    ssl_cert: SslCertService,
) -> None:
    """Register all network tools API routes on the given aiohttp application."""
    app["dns_recon"] = dns_recon
    app["mac_lookup"] = mac_lookup
    app["network_diag"] = network_diag
    app["ssl_cert"] = ssl_cert

    app.router.add_post("/api/tools/dns-recon", handle_dns_recon)
    app.router.add_get("/api/tools/mac-lookup/{mac}", handle_mac_lookup)
    app.router.add_post("/api/tools/ping", handle_ping)
    app.router.add_post("/api/tools/traceroute", handle_traceroute)
    app.router.add_post("/api/tools/ssl-cert", handle_ssl_cert)

    logger.info("Tools API routes registered (5 endpoints)")
