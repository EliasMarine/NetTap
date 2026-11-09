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

from api.error_replies import public_json
from api.offload import lookup_slot, run_lookup

# OLD CODE: from services.dns_recon_service import DnsReconService, DnsReconValidationError (NET-203)
from services.dns_recon_service import (
    DnsReconBusyError,
    DnsReconService,
    DnsReconValidationError,
)
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
    except DnsReconBusyError as e:  # NET-203: too many lookups at once
        # NET-229 follow-up: its text is the plain LOOKUPS_BUSY line
        return public_json({"error": str(e)}, status=503)
    except Exception as exc:
        logger.exception("DNS recon failed")
        return web.json_response({"error": f"DNS recon failed: {exc}"}, status=500)


# ---------------------------------------------------------------------------
# MAC Lookup
# ---------------------------------------------------------------------------


# OLD CODE START — moved into MacLookupService so the device registry's vendor pass gets it too (#26)
# def _vendor_seen_on_network(app: web.Application, oui_prefix: str) -> str | None:
#     """Malcolm's IEEE vendor name for a prefix any captured device has used (#26).
#
#     shortcut: only knows prefixes seen on this network; bundle the full IEEE table if the
#     tool must answer for arbitrary MACs.
#     """
#     storage = app.get("storage")
#     if storage is None:
#         return None
#     body = {
#         "size": 1,
#         "query": {
#             "bool": {
#                 "filter": [
#                     {"prefix": {"source.mac": oui_prefix.lower()}},
#                     {"exists": {"field": "source.oui"}},
#                 ]
#             }
#         },
#         "_source": ["source.oui"],
#     }
#     try:
#         hits = storage._client.search(index=NETWORK_INDEX, body=body)["hits"]["hits"]
#     except Exception as exc:
#         logger.warning("MAC lookup: OpenSearch vendor fallback failed: %s", exc)
#         return None
#     oui = hits[0].get("_source", {}).get("source", {}).get("oui") if hits else None
#     if isinstance(oui, list):
#         oui = next((o for o in oui if o), None)
#     return oui or None
# OLD CODE END


@lookup_slot
async def handle_mac_lookup(request: web.Request) -> web.Response:
    """GET /api/tools/mac-lookup/{mac} -- OUI vendor lookup for a MAC address."""
    raw_mac = request.match_info["mac"]
    mac_lookup: MacLookupService = request.app["mac_lookup"]

    try:
        # Unknown vendors query OpenSearch, so it runs on the lookup pool
        result = await run_lookup(mac_lookup.lookup, raw_mac)
        # OLD CODE START — handler-level fallback, now inside MacLookupService.lookup (#26)
        # if not result["found"]:
        #     vendor = _vendor_seen_on_network(request.app, result["oui_prefix"])
        #     if vendor:
        #         result = {**result, "vendor": vendor, "found": True}
        # OLD CODE END
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
            # OLD CODE START — 2026-11-06 (S12): no replies (100% loss) read as a 0.0 ms round trip
            # "rtt_min": stats.get("rtt_min_ms", 0),
            # "rtt_avg": stats.get("rtt_avg_ms", 0),
            # "rtt_max": stats.get("rtt_max_ms", 0),
            # "rtt_mdev": stats.get("rtt_mdev_ms", 0),
            # OLD CODE END
            "rtt_min": stats.get("rtt_min_ms"),
            "rtt_avg": stats.get("rtt_avg_ms"),
            "rtt_max": stats.get("rtt_max_ms"),
            "rtt_mdev": stats.get("rtt_mdev_ms"),
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
        # OLD CODE START — 2026-11-06 (S3): sent the one-line strings, but the page reads
        # subject.CN and issuer.O, so both always showed "—"
        #     "subject": result.get("subject") or {},
        #     "issuer": result.get("issuer") or {},
        # OLD CODE END
        verify_code = result.get("verify_code")
        response = {
            "host": result.get("host", ""),
            "port": result.get("port", 443),
            "subject": SslCertService.parse_dn(result.get("subject")),
            "issuer": SslCertService.parse_dn(result.get("issuer")),
            "not_before": result.get("not_before") or "",
            "not_after": result.get("not_after") or "",
            "serial": result.get("serial") or "",
            "fingerprint_sha256": result.get("fingerprint_sha256") or "",
            "san": result.get("sans", []),
            "chain": chain_strings,
            "raw": result.get("output", ""),
            # S1: s_client's own verdict (chain and name); None when nothing was checked
            # Trusted only when s_client's own result is 0 and its verify callback, on stderr
            # where the server can't write, reported no error
            "trusted": None
            if verify_code is None
            else verify_code == 0 and not result.get("verify_errors"),
            "verify_errors": result.get("verify_errors", []),
            "name_match": result.get("name_match"),
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
