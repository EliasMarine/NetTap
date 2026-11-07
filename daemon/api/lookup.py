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
import time

from aiohttp import web

from api.offload import lookup_slot, run_lookup
from services.ttl_cache import TTLCache

logger = logging.getLogger("nettap.api.lookup")

# NET-192 PR 3: the container's resolver lost first queries (20 s cold on the G11, past the
# web proxy's 10 s), and every visit asked again. A lookup now has 6 s in all, one runs per IP
# at a time, and answers are kept: a name 1 h, no name or a timeout 5 min, WHOIS 24 h.
DNS_TIMEOUT_S = 6
WHOIS_TIMEOUT_S = 15
CACHE_SIZE = 2048
HIT_TTL_S = 3600
MISS_TTL_S = 300
WHOIS_TTL_S = 24 * 3600
STATS_EVERY_S = 3600

_dns_cache = TTLCache(CACHE_SIZE)
_whois_cache = TTLCache(CACHE_SIZE)
# (kind, ip) -> the lookup in flight; other requests for that IP wait for its answer
_in_flight: dict[tuple[str, str], asyncio.Future] = {}
_stats_logged_at = time.monotonic()

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
# Single-flight lookups with a cache (NET-192 PR 3)
# ---------------------------------------------------------------------------


async def _single_flight(kind: str, ip: str, lookup) -> dict:
    """`lookup(ip)`, run once per (kind, IP) at a time: a request for an IP already being
    looked up waits for that answer. A request that goes away doesn't stop the lookup."""
    key = (kind, ip)
    flight = _in_flight.get(key)
    if flight is None:
        flight = asyncio.ensure_future(lookup(ip))
        _in_flight[key] = flight
        flight.add_done_callback(lambda _done: _in_flight.pop(key, None))
    return await asyncio.shield(flight)


def _dns_answer(ip: str, hostname=None, aliases=(), addresses=(), **extra) -> dict:
    return {
        "ip": ip,
        "hostname": hostname,
        "aliases": list(aliases),
        "addresses": list(addresses),
        "error": None,
        "timed_out": False,
        **extra,
    }


async def _resolve(ip: str) -> dict:
    """Reverse lookup, then the forward check, in DNS_TIMEOUT_S in all; the answer is cached.

    A stuck resolver thread can't be cancelled; it holds one of the two lookup threads (only
    lookups wait on those) until glibc gives up. Any other error raises and isn't cached.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + DNS_TIMEOUT_S
    try:
        hostname, aliases, addrs = await asyncio.wait_for(
            run_lookup(socket.gethostbyaddr, ip), DNS_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        answer = _dns_answer(ip, timed_out=True)
        _dns_cache.set(ip, answer, MISS_TTL_S)
        return answer
    except socket.herror:
        answer = _dns_answer(ip, error="No reverse DNS record found")
        _dns_cache.set(ip, answer, MISS_TTL_S)
        return answer

    # The forward check: the name's own addresses. If it fails or runs out of time, the
    # reverse answer stands with the addresses it gave.
    forward = list(addrs)
    try:
        addrinfo = await asyncio.wait_for(
            run_lookup(socket.getaddrinfo, hostname, None),
            max(deadline - loop.time(), 0),
        )
        forward = list({ai[4][0] for ai in addrinfo})
    except (socket.gaierror, asyncio.TimeoutError):
        pass
    answer = _dns_answer(ip, hostname, aliases, forward)
    _dns_cache.set(ip, answer, HIT_TTL_S)
    return answer


async def _whois(ip: str) -> dict:
    """The `whois` tool's answer, parsed, in WHOIS_TIMEOUT_S; the answer is cached."""
    proc = await asyncio.create_subprocess_exec(
        "whois",
        ip,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=WHOIS_TIMEOUT_S)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        answer = {"ip": ip, "raw": "", "parsed": {}, "error": "WHOIS lookup timed out"}
        _whois_cache.set(ip, answer, MISS_TTL_S)
        return answer
    raw_output = stdout.decode("utf-8", errors="replace")
    answer = {
        "ip": ip,
        "raw": raw_output,
        "parsed": _parse_whois(raw_output),
        "error": None,
    }
    _whois_cache.set(ip, answer, WHOIS_TTL_S)
    return answer


def _log_cache_stats() -> None:
    """At most once an hour (on a lookup), the caches' size and hit counts at DEBUG."""
    global _stats_logged_at
    if time.monotonic() - _stats_logged_at < STATS_EVERY_S:
        return
    _stats_logged_at = time.monotonic()
    for name, cache in (("reverse DNS", _dns_cache), ("WHOIS", _whois_cache)):
        logger.debug(
            "Lookup cache %s: %d entries, %d hits, %d misses",
            name,
            len(cache),
            cache.hits,
            cache.misses,
        )


def _valid_ip(raw: str) -> str | None:
    """The address in its normal form, or None if `raw` isn't one."""
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@lookup_slot
async def handle_whois_lookup(request: web.Request) -> web.Response:
    """GET /api/lookup/whois/{ip}

    Run a WHOIS lookup for the given IP address.
    Returns raw output plus parsed structured fields.
    """
    raw_ip = request.match_info["ip"]
    ip = _valid_ip(raw_ip)
    if ip is None:
        return web.json_response({"error": f"Invalid IP address: {raw_ip}"}, status=400)

    answer = _whois_cache.get(ip)
    if answer is None:
        try:
            answer = await _single_flight("whois", ip, _whois)
        except Exception as exc:
            logger.exception("WHOIS lookup failed for %s", ip)
            return web.json_response(
                {"error": f"WHOIS lookup failed: {exc}"}, status=500
            )
    _log_cache_stats()
    return web.json_response(answer)


# OLD CODE START — NET-192 PR 3: no cache, and two requests for one IP ran whois twice
# @lookup_slot
# async def handle_whois_lookup(request: web.Request) -> web.Response:
#     raw_ip = request.match_info["ip"]
#
#     try:
#         ipaddress.ip_address(raw_ip)
#     except ValueError:
#         return web.json_response({"error": f"Invalid IP address: {raw_ip}"}, status=400)
#
#     try:
#         proc = await asyncio.create_subprocess_exec(
#             "whois",
#             raw_ip,
#             stdout=asyncio.subprocess.PIPE,
#             stderr=asyncio.subprocess.PIPE,
#         )
#         stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
#         raw_output = stdout.decode("utf-8", errors="replace")
#         parsed = _parse_whois(raw_output)
#
#         return web.json_response(
#             {"ip": raw_ip, "raw": raw_output, "parsed": parsed, "error": None}
#         )
#
#     except asyncio.TimeoutError:
#         # Kill the process if it's still running
#         try:
#             proc.kill()  # type: ignore[possibly-undefined]
#         except ProcessLookupError:
#             pass
#         return web.json_response(
#             {
#                 "ip": raw_ip,
#                 "raw": "",
#                 "parsed": {},
#                 "error": "WHOIS lookup timed out",
#             }
#         )
#
#     except Exception as exc:
#         logger.exception("WHOIS lookup failed for %s", raw_ip)
#         return web.json_response({"error": f"WHOIS lookup failed: {exc}"}, status=500)
# OLD CODE END


@lookup_slot
async def handle_dns_lookup(request: web.Request) -> web.Response:
    """GET /api/lookup/dns/{ip}

    Perform reverse DNS lookup for the given IP address.
    Returns hostname, aliases, and forward-resolved addresses; `timed_out` is true when the
    resolver didn't answer in DNS_TIMEOUT_S (the answer is then 200 with no hostname).
    """
    raw_ip = request.match_info["ip"]
    ip = _valid_ip(raw_ip)
    if ip is None:
        return web.json_response({"error": f"Invalid IP address: {raw_ip}"}, status=400)

    answer = _dns_cache.get(ip)
    if answer is None:
        try:
            answer = await _single_flight("dns", ip, _resolve)
        except Exception as exc:
            logger.exception("DNS lookup failed for %s", ip)
            return web.json_response({"error": f"DNS lookup failed: {exc}"}, status=500)
    _log_cache_stats()
    return web.json_response(answer)


# OLD CODE START — NET-192 PR 3: no time limit (20 s cold on the G11), no cache, and two
# requests for one IP asked the resolver twice
# @lookup_slot
# async def handle_dns_lookup(request: web.Request) -> web.Response:
#     raw_ip = request.match_info["ip"]
#
#     try:
#         ipaddress.ip_address(raw_ip)
#     except ValueError:
#         return web.json_response({"error": f"Invalid IP address: {raw_ip}"}, status=400)
#
#     # OLD CODE START — PR #200 review: a public route on the shared default pool, uncapped
#     # loop = asyncio.get_event_loop()
#     #
#     # try:
#     #     hostname, aliases, addrs = await loop.run_in_executor(
#     #         None, socket.gethostbyaddr, raw_ip
#     #     )
#     # OLD CODE END
#     try:
#         hostname, aliases, addrs = await run_lookup(socket.gethostbyaddr, raw_ip)
#     except socket.herror:
#         return web.json_response(
#             {
#                 "ip": raw_ip,
#                 "hostname": None,
#                 "aliases": [],
#                 "addresses": [],
#                 "error": "No reverse DNS record found",
#             }
#         )
#     except Exception as exc:
#         logger.exception("DNS lookup failed for %s", raw_ip)
#         return web.json_response({"error": f"DNS lookup failed: {exc}"}, status=500)
#
#     # Forward lookup to get all addresses for the hostname
#     forward_addrs: list[str] = []
#     try:
#         # OLD CODE START — PR #200 review: the shared default pool
#         # addrinfo = await loop.run_in_executor(None, socket.getaddrinfo, hostname, None)
#         # OLD CODE END
#         addrinfo = await run_lookup(socket.getaddrinfo, hostname, None)
#         forward_addrs = list({ai[4][0] for ai in addrinfo})
#     except socket.gaierror:
#         # Forward lookup failed; return what we have from reverse
#         forward_addrs = list(addrs)
#
#     return web.json_response(
#         {
#             "ip": raw_ip,
#             "hostname": hostname,
#             "aliases": list(aliases),
#             "addresses": forward_addrs,
#             "error": None,
#         }
#     )
# OLD CODE END


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_lookup_routes(app: web.Application) -> None:
    """Register all IP lookup API routes on the given aiohttp application."""
    app.router.add_get("/api/lookup/whois/{ip}", handle_whois_lookup)
    app.router.add_get("/api/lookup/dns/{ip}", handle_dns_lookup)
    logger.info("Lookup API routes registered (2 endpoints)")
