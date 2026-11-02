"""
NetTap Device Registry API Routes (v2)

Provides REST endpoints for the DeviceRegistry service and UniFi
integration. These endpoints operate on the MAC-keyed ``nettap-devices``
index, separate from the original IP-based device inventory in devices.py.

Endpoints:
    GET  /api/devices/registry                      — list all discovered devices
    GET  /api/devices/registry/{mac}                — single device detail
    GET  /api/devices/registry/{mac}/traffic         — traffic for one device
    GET  /api/devices/registry/search               — search devices
    POST /api/integrations/unifi/configure           — set UniFi API key
    GET  /api/integrations/unifi/status              — connection status
    POST /api/integrations/unifi/test                — test connectivity
    GET  /api/integrations/unifi/sites               — list sites
    GET  /api/integrations/unifi/clients             — list connected clients
    GET  /api/integrations/unifi/devices             — list infrastructure devices
    GET  /api/integrations/unifi/devices/{id}/stats  — device statistics
    GET  /api/integrations/unifi/networks            — list networks
    GET  /api/integrations/unifi/wifi                — list WiFi broadcasts
    GET  /api/integrations/unifi/firewall            — firewall policies + zones
    GET  /api/integrations/unifi/acl                 — ACL rules
    GET  /api/integrations/unifi/dns-policies        — DNS policies
    GET  /api/integrations/unifi/wans                — WAN interfaces
    GET  /api/integrations/unifi/vpn                 — VPN tunnels
    GET  /api/integrations/unifi/dpi/categories      — DPI categories
    GET  /api/integrations/unifi/dpi/apps            — DPI applications
"""

import logging
import time
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from aiohttp import web
from opensearchpy import OpenSearchException

from api.devices import (
    _device_category,
    _is_skipped_device_ip,
    _lan_device_buckets,
    _vendor_category,
)
from services.device_fingerprint import _mac_from_hit, _oui_from_hit
from services.device_registry import DeviceRegistry
from services.unifi_integration import UnifiIntegration, normalize_controller_url

logger = logging.getLogger("nettap.api.devices_v2")

_DEFAULT_RANGE_HOURS = 24

# How often the daemon refreshes the device registry, and how far back each refresh looks
REGISTRY_REFRESH_INTERVAL_S = 300
REGISTRY_REFRESH_WINDOW = timedelta(hours=1)


# ---------------------------------------------------------------------------
# Registry refresh (run periodically by main.device_registry_loop)
# ---------------------------------------------------------------------------


# OLD CODE START — #96: a terms list of 500 IPs; past that, devices active this hour were never registered
# def _conn_devices_query(app: Mapping[str, Any], from_ts: str, to_ts: str) -> dict:
#     """The device list's LAN conn query, bucketed by IP with each IP's most common MAC."""
#     return {
#         "size": 0,
#         "query": {"bool": _lan_device_bool_query(app, from_ts, to_ts)},
#         "aggs": {
#             "devices": {
#                 "terms": {
#                     "field": "source.ip",
#                     "size": _MAX_DEVICE_LIMIT,
#                     "min_doc_count": _MIN_CONNECTIONS,
#                 },
#                 "aggs": {
#                     # OLD CODE START — the newest record's MAC: routed inter-VLAN legs on a
#                     # mirrored uplink carry the router's MAC, so IoT IPs were filed under the UDM (#26)
#                     # "with_mac": {"filter": {"exists": {"field": "source.mac"}},
#                     #              "aggs": {"latest": {"top_hits": {"size": 1, "sort": [{"@timestamp": "desc"}], ...}}}}
#                     # OLD CODE END
#                     # The device's own MAC is on every flow's first leg, so it is the most common
#                     "with_mac": {
#                         "terms": {"field": "source.mac", "size": 1},
#                         "aggs": {
#                             "latest": {
#                                 "top_hits": {
#                                     "size": 1,
#                                     "sort": [{"@timestamp": {"order": "desc"}}],
#                                     "_source": ["source.mac", "source.oui"],
#                                 }
#                             }
#                         },
#                     }
#                 },
#             }
#         },
#     }
# OLD CODE END


def _conn_device_aggs() -> dict:
    """Each device bucket's most common MAC (for _lan_device_buckets)."""
    return {
        # The device's own MAC is on every flow's first leg, so it is the most common
        "with_mac": {
            "terms": {"field": "source.mac", "size": 1},
            "aggs": {
                "latest": {
                    "top_hits": {
                        "size": 1,
                        "sort": [{"@timestamp": {"order": "desc"}}],
                        "_source": ["source.mac", "source.oui"],
                    }
                }
            },
        }
    }


def _register_conn_devices(registry: DeviceRegistry, buckets: list[dict]) -> dict[str, str]:
    """Register each IP bucket under its MAC, skipping the IPs the device list skips.

    Returns the {ip: mac} pairs registered.
    """
    assigned: dict[str, str] = {}
    # OLD CODE START — #96: buckets came from one capped terms search
    # for bucket in result.get("aggregations", {}).get("devices", {}).get("buckets", []):
    # OLD CODE END
    for bucket in buckets:
        ip = bucket["key"]
        macs = bucket.get("with_mac", {}).get("buckets", [])
        hits = macs[0].get("latest", {}).get("hits", {}).get("hits", []) if macs else []
        mac = _mac_from_hit(hits[0]) if hits else None
        # shortcut: an IP with no MAC in its conn records can't be keyed, so it stays out of the registry
        if _is_skipped_device_ip(ip) or not mac:
            continue
        # OLD CODE START — the vendor came only from the bundled 208-prefix table (#26)
        # registry.register_device(mac=mac, ip=ip, source="conn")
        # OLD CODE END
        oui = _oui_from_hit(hits[0])  # Malcolm's IEEE vendor name, absent for randomized MACs
        metadata = {"manufacturer": oui, "category": _vendor_category(oui)} if oui else None
        registry.register_device(mac=mac, ip=ip, source="conn", metadata=metadata)
        assigned[ip] = mac
    return assigned


# OLD CODE START — only devices seen this refresh, and register_device moved their last_seen
# def _categorize_unknown(
#     app: Mapping[str, Any], registry: DeviceRegistry, assigned: dict[str, str], from_ts: str, to_ts: str
# ) -> int:
#     """Give still-"unknown" devices seen this refresh the Devices page's category (#26).
#
#     The registry only got categories from vendor metadata, so Home's grid called devices
#     "unknown" that the Devices page files under Computers or Phones by OS and hostname.
#     Only devices seen this refresh: a registry update also moves last_seen.
#     """
#     fingerprint = app.get("device_fingerprint")
#     count = 0
#     for ip, mac in assigned.items():
#         device = registry.get_device(mac)
#         if not device or device.get("category", "unknown") != "unknown":
#             continue
#         os_hint = fingerprint.get_os_hint(registry._client, ip, from_ts, to_ts) if fingerprint else None
#         names = " ".join(device.get("hostnames") or []) or None  # match hints in any of its names
#         category = _device_category(os_hint, names, device.get("manufacturer"))
#         if category != "unknown":
#             registry.register_device(mac=mac, source="fingerprint", metadata={"category": category})
#             count += 1
#     return count
# OLD CODE END


def _categorize_unknown(app: Mapping[str, Any], registry: DeviceRegistry, from_ts: str, to_ts: str) -> int:
    """Give every still-"unknown" registry device the Devices page's category (#26).

    The registry only got categories from vendor metadata, so Home's grid called devices
    "unknown" that the Devices page files under Computers or Phones. Same inputs as that
    page: OS hint and DNS hostname over its default range, plus the registry's own names
    (DHCP/mDNS) and the vendor. Devices that stay unknown are re-checked each refresh.
    """
    fingerprint = app.get("device_fingerprint")
    count = 0
    registry.refresh_index()  # vendors from enrich_with_oui must be searchable
    for device in registry.get_all_devices(limit=1000):
        if device.get("category", "unknown") != "unknown":
            continue
        ip = (device.get("ips") or [None])[0]
        os_hint = dns_name = None
        if fingerprint and ip:
            os_hint = fingerprint.get_os_hint(registry._client, ip, from_ts, to_ts)
            dns_name = fingerprint.get_hostname_for_ip(registry._client, ip, from_ts, to_ts)
        names = " ".join([*(device.get("hostnames") or []), dns_name or ""]).strip() or None
        category = _device_category(os_hint, names, device.get("manufacturer"))
        if category != "unknown" and registry.set_category(device, category):
            count += 1
    return count


def refresh_device_registry(app: Mapping[str, Any]) -> int:
    """Register the LAN devices seen in recent conn traffic, then add names and vendors.

    Uses the device list's filters, threshold and skip rules, so the registry
    agrees with GET /api/devices. Blocking: run it in an executor.

    Returns:
        Number of devices registered from conn traffic.
    """
    registry: DeviceRegistry | None = app.get("device_registry")
    if registry is None:
        return 0
    started = time.monotonic()
    # The daemon often starts before OpenSearch; never let a write auto-create the index unmapped
    registry._ensure_index()

    now = datetime.now(timezone.utc)
    from_ts = (now - REGISTRY_REFRESH_WINDOW).isoformat()
    to_ts = now.isoformat()
    # OLD CODE START — #96: the capped terms search (see _conn_devices_query)
    # query = _conn_devices_query(app, from_ts, to_ts)
    # result = registry._client.search(index=NETWORK_INDEX, body=query)
    # OLD CODE END
    buckets = _lan_device_buckets(registry._client, app, from_ts, to_ts, aggs=_conn_device_aggs())
    # OLD CODE START — #26: the {ip: mac} pairs are needed to drop IPs that moved
    # count = _register_conn_devices(registry, result)
    # OLD CODE END
    assigned = _register_conn_devices(registry, buckets)
    count = len(assigned)
    registry.merge_long_macs()
    registry.drop_reassigned_ips(assigned)

    # enrich_from_arp is left out: it registers any MAC from any record (public
    # IPs, multicast), which breaks agreement with the device list
    registry.enrich_from_dhcp(from_ts, to_ts)
    registry.enrich_from_mdns(from_ts, to_ts)
    registry.enrich_from_ssdp(from_ts, to_ts)
    mac_lookup = app.get("mac_lookup")
    if mac_lookup is not None:
        registry.enrich_with_oui(mac_lookup)
    # After names and vendors are in; OS hints over the Devices page's default range so both agree
    hint_from = (now - timedelta(hours=_DEFAULT_RANGE_HOURS)).isoformat()
    _categorize_unknown(app, registry, hint_from, to_ts)

    # OLD CODE START — no duration; it took ~1 min before writes stopped waiting for refreshes
    # logger.info("Device registry refresh: %d LAN devices from conn traffic", count)
    # OLD CODE END
    logger.info(
        "Device registry refresh: %d LAN devices from conn traffic in %.1f s", count, time.monotonic() - started
    )
    return count


def _parse_time_range(request: web.Request) -> tuple[str, str]:
    """Extract 'from' and 'to' query parameters as ISO timestamps."""
    now = datetime.now(timezone.utc)
    default_from = (now - timedelta(hours=_DEFAULT_RANGE_HOURS)).isoformat()
    default_to = now.isoformat()

    raw_from = request.query.get("from", "")
    raw_to = request.query.get("to", "")

    if raw_from:
        try:
            datetime.fromisoformat(raw_from.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raw_from = ""
    if raw_to:
        try:
            datetime.fromisoformat(raw_to.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raw_to = ""

    return (raw_from or default_from, raw_to or default_to)


def _parse_int_param(request: web.Request, name: str, default: int) -> int:
    """Parse an integer query parameter with a fallback default."""
    raw = request.query.get(name, "")
    if raw:
        try:
            return max(1, int(raw))
        except (ValueError, TypeError):
            pass
    return default


def _get_registry(request: web.Request) -> DeviceRegistry:
    """Retrieve the DeviceRegistry from the app."""
    registry = request.app.get("device_registry")
    if registry is None:
        raise web.HTTPServiceUnavailable(text="Device registry not initialized")
    return registry


def _get_unifi(request: web.Request) -> UnifiIntegration:
    """Retrieve the UnifiIntegration from the app."""
    unifi = request.app.get("unifi_integration")
    if unifi is None:
        raise web.HTTPServiceUnavailable(text="UniFi integration not initialized")
    return unifi


# ---------------------------------------------------------------------------
# Device registry handlers
# ---------------------------------------------------------------------------


async def handle_registry_list(request: web.Request) -> web.Response:
    """GET /api/devices/registry?limit=100&offset=0"""
    registry = _get_registry(request)
    limit = min(_parse_int_param(request, "limit", 100), 500)
    offset = _parse_int_param(request, "offset", 0) - 1  # Convert 1-based to 0-based
    offset = max(0, offset)

    try:
        devices = registry.get_all_devices(limit=limit, offset=offset)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in device registry: %s", exc)
        return web.json_response({"error": f"OpenSearch query failed: {exc}"}, status=502)

    # Add display_name to each device
    for device in devices:
        device["display_name"] = registry.get_display_name(device)

    return web.json_response(
        {
            "devices": devices,
            "count": len(devices),
            "limit": limit,
            "offset": offset,
        }
    )


async def handle_registry_detail(request: web.Request) -> web.Response:
    """GET /api/devices/registry/{mac}"""
    registry = _get_registry(request)
    mac = request.match_info["mac"]

    try:
        device = registry.get_device(mac)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in device registry: %s", exc)
        return web.json_response({"error": f"OpenSearch query failed: {exc}"}, status=502)
    if device is None:
        return web.json_response({"error": f"Device not found: {mac}"}, status=404)

    device["display_name"] = registry.get_display_name(device)
    return web.json_response({"device": device})


async def handle_registry_traffic(request: web.Request) -> web.Response:
    """GET /api/devices/registry/{mac}/traffic?from=&to="""
    registry = _get_registry(request)
    mac = request.match_info["mac"]
    from_ts, to_ts = _parse_time_range(request)

    try:
        device = registry.get_device(mac)
        if device is None:
            return web.json_response({"error": f"Device not found: {mac}"}, status=404)
        traffic = registry.get_device_traffic(mac, from_ts, to_ts)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in device registry: %s", exc)
        return web.json_response({"error": f"OpenSearch query failed: {exc}"}, status=502)
    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "traffic": traffic,
        }
    )


async def handle_registry_new_count(request: web.Request) -> web.Response:
    """GET /api/devices/registry/new-count?since=ISO (default: 24 h ago)

    Devices NetTap saw for the first time since then. The device list's first_seen is the
    first record in the page's time window, so it can't tell a new device from an old one.
    """
    registry = _get_registry(request)
    raw = request.query.get("since", "")
    try:
        since = (
            datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if raw
            else datetime.now(timezone.utc) - timedelta(hours=24)
        )
    except ValueError:
        return web.json_response({"error": "since must be an ISO timestamp"}, status=400)
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    since_iso = since.astimezone(timezone.utc).isoformat()
    try:
        count = registry.count_first_seen_since(since_iso)
    except OpenSearchException as exc:
        logger.error("OpenSearch error counting new devices: %s", exc)
        return web.json_response({"error": f"OpenSearch query failed: {exc}"}, status=502)
    return web.json_response({"count": count, "since": since_iso})


async def handle_registry_search(request: web.Request) -> web.Response:
    """GET /api/devices/registry/search?q="""
    registry = _get_registry(request)
    query_str = request.query.get("q", "").strip()

    if not query_str:
        return web.json_response(
            {"error": "Query parameter 'q' is required"}, status=400
        )

    try:
        devices = registry.search_devices(query_str)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in device registry: %s", exc)
        return web.json_response({"error": f"OpenSearch query failed: {exc}"}, status=502)
    for device in devices:
        device["display_name"] = registry.get_display_name(device)

    return web.json_response(
        {
            "query": query_str,
            "devices": devices,
            "count": len(devices),
        }
    )


# ---------------------------------------------------------------------------
# UniFi integration handlers
# ---------------------------------------------------------------------------


async def handle_unifi_configure(request: web.Request) -> web.Response:
    """POST /api/integrations/unifi/configure

    Body: {"controller_url": "...", "api_key": "...", "site_id": "..."}
    """
    # OLD CODE START — previous body format used username/password session auth
    # Body: {"controller_url": "...", "username": "...", "password": "...", "site": "default"}
    # unifi.configure(controller_url, username, password, site)
    # OLD CODE END

    unifi = _get_unifi(request)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    if not isinstance(body, dict):
        return web.json_response({"error": "JSON body must be an object"}, status=400)

    controller_url = body.get("controller_url")
    api_key = body.get("api_key")
    # OLD CODE START — an empty site_id wiped the stored site (2026-10-29)
    # site_id = body.get("site_id")
    # OLD CODE END
    site_id = body.get("site_id") or None  # omitted or empty keeps the current site

    if any(
        value is not None and not isinstance(value, str)
        for value in (controller_url, api_key, site_id)
    ):
        return web.json_response(
            {"error": "controller_url, api_key and site_id must be strings"},
            status=400,
        )
    if not controller_url:
        return web.json_response(
            {"error": "controller_url is required"},
            status=400,
        )
    # api_key can be omitted when reconfiguring (e.g. changing site)
    # — keep the existing key if already configured
    if not api_key and not unifi.is_configured:
        return web.json_response(
            {"error": "api_key is required for initial configuration"},
            status=400,
        )
    # The stored key may only go to the controller it was entered for.
    # Otherwise anyone could point controller_url at their own server
    # and receive the key in the X-API-Key header of the next request.
    if not api_key and normalize_controller_url(controller_url) != unifi._base_url:
        return web.json_response(
            {"error": "api_key is required when changing controller_url"},
            status=400,
        )

    effective_key = api_key or (unifi._api_key if unifi.is_configured else "")
    unifi.configure(controller_url, effective_key, site_id=site_id)
    return web.json_response(
        {
            "status": "configured",
            "controller_url": controller_url,
        }
    )


async def handle_unifi_status(request: web.Request) -> web.Response:
    """GET /api/integrations/unifi/status"""
    unifi = _get_unifi(request)
    return web.json_response(unifi.get_status())


async def handle_unifi_test(request: web.Request) -> web.Response:
    """POST /api/integrations/unifi/test"""
    unifi = _get_unifi(request)

    if not unifi.is_configured:
        return web.json_response(
            {"success": False, "error": "UniFi integration not configured"},
            status=400,
        )

    success = await unifi.test_connection()

    # If test succeeded, eagerly poll clients + devices so the UI
    # immediately shows cached counts instead of staying at 0.
    if success and unifi._site_id:
        try:
            await unifi.poll_clients()
            await unifi.poll_devices()
        except Exception as exc:
            logger.warning("Post-test poll failed: %s", exc)

    return web.json_response(
        {
            "success": success,
            "status": unifi.get_status(),
        }
    )


# ---------------------------------------------------------------------------
# UniFi data endpoints
# ---------------------------------------------------------------------------


async def handle_unifi_sites(request: web.Request) -> web.Response:
    """GET /api/integrations/unifi/sites"""
    unifi = _get_unifi(request)
    if not unifi.is_configured:
        return web.json_response({"error": "UniFi not configured"}, status=400)
    sites = await unifi.list_sites()
    return web.json_response({"sites": sites})


async def handle_unifi_clients(request: web.Request) -> web.Response:
    """GET /api/integrations/unifi/clients"""
    unifi = _get_unifi(request)
    if not unifi.is_configured:
        return web.json_response({"error": "UniFi not configured"}, status=400)
    try:
        clients = await unifi.poll_clients()
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response({"clients": clients})


async def handle_unifi_devices(request: web.Request) -> web.Response:
    """GET /api/integrations/unifi/devices"""
    unifi = _get_unifi(request)
    if not unifi.is_configured:
        return web.json_response({"error": "UniFi not configured"}, status=400)
    try:
        devices = await unifi.poll_devices()
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response({"devices": devices})


async def handle_unifi_device_stats(request: web.Request) -> web.Response:
    """GET /api/integrations/unifi/devices/{id}/stats"""
    unifi = _get_unifi(request)
    if not unifi.is_configured:
        return web.json_response({"error": "UniFi not configured"}, status=400)
    device_id = request.match_info["id"]
    try:
        stats = await unifi.get_device_stats(device_id)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.warning("Failed to fetch device stats for %s: %s", device_id, exc)
        return web.json_response({"error": f"Failed to fetch stats: {exc}"}, status=502)
    return web.json_response({"device_id": device_id, "stats": stats})


async def handle_unifi_networks(request: web.Request) -> web.Response:
    """GET /api/integrations/unifi/networks"""
    unifi = _get_unifi(request)
    if not unifi.is_configured:
        return web.json_response({"error": "UniFi not configured"}, status=400)
    try:
        networks = await unifi.poll_networks()
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response({"networks": networks})


async def handle_unifi_wifi(request: web.Request) -> web.Response:
    """GET /api/integrations/unifi/wifi"""
    unifi = _get_unifi(request)
    if not unifi.is_configured:
        return web.json_response({"error": "UniFi not configured"}, status=400)
    try:
        wifi = await unifi.poll_wifi()
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response({"wifi": wifi})


async def handle_unifi_firewall(request: web.Request) -> web.Response:
    """GET /api/integrations/unifi/firewall

    Returns both firewall policies and zones in a single response.
    """
    unifi = _get_unifi(request)
    if not unifi.is_configured:
        return web.json_response({"error": "UniFi not configured"}, status=400)
    try:
        policies = await unifi.poll_firewall_policies()
        zones = await unifi.poll_firewall_zones()
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response(
        {
            "policies": policies,
            "zones": zones,
        }
    )


async def handle_unifi_acl(request: web.Request) -> web.Response:
    """GET /api/integrations/unifi/acl"""
    unifi = _get_unifi(request)
    if not unifi.is_configured:
        return web.json_response({"error": "UniFi not configured"}, status=400)
    try:
        rules = await unifi.poll_acl_rules()
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response({"rules": rules})


async def handle_unifi_dns_policies(request: web.Request) -> web.Response:
    """GET /api/integrations/unifi/dns-policies"""
    unifi = _get_unifi(request)
    if not unifi.is_configured:
        return web.json_response({"error": "UniFi not configured"}, status=400)
    try:
        policies = await unifi.poll_dns_policies()
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response({"policies": policies})


async def handle_unifi_wans(request: web.Request) -> web.Response:
    """GET /api/integrations/unifi/wans"""
    unifi = _get_unifi(request)
    if not unifi.is_configured:
        return web.json_response({"error": "UniFi not configured"}, status=400)
    try:
        wans = await unifi.poll_wans()
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response({"wans": wans})


async def handle_unifi_vpn(request: web.Request) -> web.Response:
    """GET /api/integrations/unifi/vpn"""
    unifi = _get_unifi(request)
    if not unifi.is_configured:
        return web.json_response({"error": "UniFi not configured"}, status=400)
    try:
        tunnels = await unifi.poll_vpn_tunnels()
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response({"tunnels": tunnels})


async def handle_unifi_dpi_categories(request: web.Request) -> web.Response:
    """GET /api/integrations/unifi/dpi/categories"""
    unifi = _get_unifi(request)
    if not unifi.is_configured:
        return web.json_response({"error": "UniFi not configured"}, status=400)
    categories = await unifi.get_dpi_categories()
    return web.json_response({"categories": categories})


async def handle_unifi_dpi_apps(request: web.Request) -> web.Response:
    """GET /api/integrations/unifi/dpi/apps"""
    unifi = _get_unifi(request)
    if not unifi.is_configured:
        return web.json_response({"error": "UniFi not configured"}, status=400)
    apps = await unifi.get_dpi_applications()
    return web.json_response({"applications": apps})


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_devices_v2_routes(
    app: web.Application,
    device_registry: DeviceRegistry,
    unifi_integration: UnifiIntegration,
) -> None:
    """Register device registry and UniFi integration routes."""
    app["device_registry"] = device_registry
    app["unifi_integration"] = unifi_integration

    # Device registry endpoints
    # Note: search must be registered BEFORE {mac} to avoid routing conflicts
    app.router.add_get("/api/devices/registry/search", handle_registry_search)
    app.router.add_get("/api/devices/registry/new-count", handle_registry_new_count)
    app.router.add_get("/api/devices/registry", handle_registry_list)
    app.router.add_get("/api/devices/registry/{mac}", handle_registry_detail)
    app.router.add_get("/api/devices/registry/{mac}/traffic", handle_registry_traffic)

    # UniFi integration — configuration & status
    app.router.add_post("/api/integrations/unifi/configure", handle_unifi_configure)
    app.router.add_get("/api/integrations/unifi/status", handle_unifi_status)
    app.router.add_post("/api/integrations/unifi/test", handle_unifi_test)

    # UniFi integration — data endpoints
    app.router.add_get("/api/integrations/unifi/sites", handle_unifi_sites)
    app.router.add_get("/api/integrations/unifi/clients", handle_unifi_clients)
    app.router.add_get("/api/integrations/unifi/devices", handle_unifi_devices)
    app.router.add_get(
        "/api/integrations/unifi/devices/{id}/stats",
        handle_unifi_device_stats,
    )
    app.router.add_get("/api/integrations/unifi/networks", handle_unifi_networks)
    app.router.add_get("/api/integrations/unifi/wifi", handle_unifi_wifi)
    app.router.add_get("/api/integrations/unifi/firewall", handle_unifi_firewall)
    app.router.add_get("/api/integrations/unifi/acl", handle_unifi_acl)
    app.router.add_get(
        "/api/integrations/unifi/dns-policies", handle_unifi_dns_policies
    )
    app.router.add_get("/api/integrations/unifi/wans", handle_unifi_wans)
    app.router.add_get("/api/integrations/unifi/vpn", handle_unifi_vpn)
    app.router.add_get(
        "/api/integrations/unifi/dpi/categories", handle_unifi_dpi_categories
    )
    app.router.add_get("/api/integrations/unifi/dpi/apps", handle_unifi_dpi_apps)

    logger.info("Device Registry v2 + UniFi routes registered (20 endpoints)")
