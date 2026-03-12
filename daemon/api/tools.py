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
        # Reshape to match frontend PingResult interface
        stats = result.get("stats", {})
        response = {
            "target": result["target"],
            "raw": result.get("output", ""),
            "packets_sent": stats.get("packets_transmitted", 0),
            "packets_received": stats.get("packets_received", 0),
            "packet_loss_pct": stats.get("packet_loss_percent", 100),
            "rtt_min": stats.get("rtt_min_ms", 0),
            "rtt_avg": stats.get("rtt_avg_ms", 0),
            "rtt_max": stats.get("rtt_max_ms", 0),
            "rtt_mdev": stats.get("rtt_mdev_ms", 0),
            "replies": [
                {
                    "bytes": r.get("bytes", 0),
                    "from": r.get("from", ""),
                    "seq": r.get("icmp_seq", 0),
                    "ttl": r.get("ttl", 0),
                    "time_ms": r.get("time_ms", 0),
                }
                for r in result.get("replies", [])
            ],
            "error": result.get("error"),
        }
        return web.json_response(response)
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
        # Reshape to match frontend TracerouteResult interface
        hops = result.get("hops", [])
        response = {
            "target": result["target"],
            "raw": result.get("output", ""),
            "total_hops": len(hops),
            "hops": [
                {
                    "hop": h.get("hop", 0),
                    "host": "* * *" if h.get("host") == "*" else h.get("host", ""),
                    "ip": h.get("ip", ""),
                    "rtts": h.get("rtt_ms", []),
                }
                for h in hops
            ],
            "error": result.get("error"),
        }
        return web.json_response(response)
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
        # Reshape to match frontend SslCertResult interface
        chain = result.get("chain", [])
        chain_strings = []
        for c in chain:
            if isinstance(c, dict):
                chain_strings.append(c.get("subject", ""))
            else:
                chain_strings.append(str(c))
        response = {
            "host": result.get("host", ""),
            "port": result.get("port", 443),
            "subject": result.get("subject") or {},
            "issuer": result.get("issuer") or {},
            "not_before": result.get("not_before") or "",
            "not_after": result.get("not_after") or "",
            "serial": result.get("serial") or "",
            "fingerprint_sha256": result.get("fingerprint_sha256") or "",
            "san": result.get("sans", []),
            "chain": chain_strings,
            "raw": result.get("output", ""),
            "error": result.get("error"),
        }
        return web.json_response(response)
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
