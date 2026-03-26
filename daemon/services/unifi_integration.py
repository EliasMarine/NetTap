"""
NetTap UniFi Controller Integration — Optional Tier-2 device enrichment.

Uses the official UniFi Network API (v10.2.93) with API-key authentication.
Polls for device aliases, infrastructure status, network/WiFi configs,
firewall policies, DPI reference data, and more. This is an optional
enrichment source — the system works perfectly without it. When configured
and reachable, UniFi aliases take top priority in device naming.

API base path:
    {controller_url}/proxy/network/integration/v1/...

Authentication:
    X-API-Key header on every request (no session cookies).

Graceful degradation: if the controller is unreachable or the API key is
invalid, we log a warning and continue with Tier 1 (passive) enrichment only.
"""

# OLD CODE START — legacy API docs, replaced by official API v10.2.93
# API endpoints used (legacy internal API, session-cookie auth):
#     POST /api/login            — authenticate session
#     GET  /api/s/default/stat/sta    — connected clients (MAC, hostname, alias)
#     GET  /api/s/default/stat/device — APs, switches, gateways
#
# Replaced because:
#     1. The internal API is undocumented and breaks across controller updates
#     2. Session-cookie auth requires periodic re-login and cookie management
#     3. Official API v10.2.93 provides stable, versioned endpoints with API-key auth
# OLD CODE END

import logging
import time
from typing import Any

logger = logging.getLogger("nettap.services.unifi_integration")

# ---------------------------------------------------------------------------
# Cache TTLs (seconds) — stale cache is better than no data
# ---------------------------------------------------------------------------
_CACHE_TTL_CLIENTS = 300      # 5 minutes — clients change frequently
_CACHE_TTL_DEVICES = 300      # 5 minutes — infrastructure status
_CACHE_TTL_NETWORKS = 600     # 10 minutes — network config rarely changes
_CACHE_TTL_WIFI = 600         # 10 minutes
_CACHE_TTL_FIREWALL = 600     # 10 minutes — policies/zones/ACLs
_CACHE_TTL_DNS = 600          # 10 minutes
_CACHE_TTL_DPI = 3600         # 1 hour — reference data, rarely changes
_CACHE_TTL_WANS = 600         # 10 minutes
_CACHE_TTL_VPN = 600          # 10 minutes

# Kept for backward compat with tests that import it
_CACHE_TTL = _CACHE_TTL_CLIENTS


class UnifiAuthError(Exception):
    """Raised when the UniFi API rejects the API key (HTTP 401)."""


class UnifiIntegration:
    """UniFi Network API client (official API v10.2.93) for device enrichment.

    Usage:
        unifi = UnifiIntegration()
        unifi.configure("https://192.168.1.1", api_key="abc123")
        if await unifi.test_connection():
            clients = await unifi.poll_clients()
    """

    # OLD CODE START — legacy configure() signature for reference
    # def configure(self, controller_url, username, password, site="default"):
    #     Replaced with API-key auth: configure(controller_url, api_key, site_id=None)
    # OLD CODE END

    def __init__(self, session_factory: Any = None):
        """Initialize the UniFi integration.

        Args:
            session_factory: Optional callable that returns an HTTP session
                (for testing). Defaults to aiohttp.ClientSession.
        """
        self._base_url: str | None = None
        self._api_key: str | None = None
        self._site_id: str | None = None
        self._configured: bool = False

        # OLD CODE START — removed fields (session-cookie auth no longer used)
        # self._username: str | None = None
        # self._password: str | None = None
        # self._site: str = "default"
        # self._authenticated: bool = False
        # OLD CODE END

        # Session management
        self._session_factory = session_factory
        self._session: Any = None

        # Per-data-type caches: each holds (data, timestamp)
        self._cache_clients: list[dict] = []
        self._cache_clients_time: float = 0
        self._cache_devices: list[dict] = []
        self._cache_devices_time: float = 0
        self._cache_networks: list[dict] = []
        self._cache_networks_time: float = 0
        self._cache_wifi: list[dict] = []
        self._cache_wifi_time: float = 0
        self._cache_firewall_policies: list[dict] = []
        self._cache_firewall_policies_time: float = 0
        self._cache_firewall_zones: list[dict] = []
        self._cache_firewall_zones_time: float = 0
        self._cache_acl_rules: list[dict] = []
        self._cache_acl_rules_time: float = 0
        self._cache_dns_policies: list[dict] = []
        self._cache_dns_policies_time: float = 0
        self._cache_dpi_categories: list[dict] = []
        self._cache_dpi_categories_time: float = 0
        self._cache_dpi_applications: list[dict] = []
        self._cache_dpi_applications_time: float = 0
        self._cache_wans: list[dict] = []
        self._cache_wans_time: float = 0
        self._cache_vpn_tunnels: list[dict] = []
        self._cache_vpn_tunnels_time: float = 0

        # Legacy compat: _device_cache is an alias for _cache_clients
        # so get_device_alias() and old tests that poke _device_cache still work
        self._device_cache: list[dict] = self._cache_clients

        self._last_poll_time: float = 0
        self._last_error: str | None = None

    @property
    def is_configured(self) -> bool:
        return self._configured

    def configure(
        self,
        controller_url: str,
        api_key: str,
        site_id: str | None = None,
    ) -> None:
        """Store controller URL and API key.

        Args:
            controller_url: Base URL (e.g. "https://192.168.1.1").
            api_key: UniFi API key (generated in Integrations settings).
            site_id: Optional site UUID. If None, call list_sites() to
                discover it.
        """
        # Strip trailing slash
        self._base_url = controller_url.rstrip("/")
        self._api_key = api_key
        self._site_id = site_id
        self._configured = True
        self._last_error = None
        logger.info("UniFi integration configured for %s", self._base_url)

    # ------------------------------------------------------------------
    # HTTP transport
    # ------------------------------------------------------------------

    async def _get_session(self) -> Any:
        """Get or create an HTTP session."""
        if self._session is None:
            if self._session_factory:
                self._session = self._session_factory()
            else:
                import aiohttp
                # UniFi controllers often use self-signed certs
                import ssl
                ssl_ctx = ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE
                connector = aiohttp.TCPConnector(ssl=ssl_ctx)
                self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
    ) -> dict:
        """Make an authenticated request to the UniFi Network API.

        Args:
            method: HTTP method (GET, POST, etc.).
            path: API path (e.g. "/v1/info"). Appended to the integration base.
            params: Optional query parameters.

        Returns:
            Parsed JSON response dict.

        Raises:
            UnifiAuthError: If the API returns 401 (invalid/expired key).
            aiohttp.ClientResponseError: On other non-2xx responses.
            Exception: On connection errors (timeout, refused, SSL) — stored
                in ``self._last_error`` before re-raising so callers can
                surface the message without catching.
        """
        session = await self._get_session()
        url = f"{self._base_url}/proxy/network/integration{path}"
        headers = {"X-API-Key": self._api_key}
        try:
            async with session.request(
                method, url, headers=headers, params=params, ssl=False,
            ) as resp:
                if resp.status == 401:
                    self._last_error = "Invalid API key"
                    raise UnifiAuthError("Invalid API key")
                resp.raise_for_status()
                return await resp.json()
        except UnifiAuthError:
            raise
        except Exception as exc:
            self._last_error = f"Request error ({method} {path}): {exc}"
            raise

    async def _paginate(
        self,
        path: str,
        params: dict | None = None,
    ) -> list[dict]:
        """Fetch all pages of a paginated endpoint.

        Uses offset/limit pagination. Stops when a page returns fewer
        items than the requested limit.

        Args:
            path: API path for the paginated endpoint.
            params: Optional extra query parameters (e.g. filters).

        Returns:
            Concatenated list of all ``data`` items across pages.
        """
        all_data: list[dict] = []
        offset = 0
        limit = 200  # max allowed by the API
        while True:
            p = {**(params or {}), "offset": offset, "limit": limit}
            result = await self._request("GET", path, params=p)
            data = result.get("data", [])
            all_data.extend(data)
            if len(data) < limit:
                break
            offset += limit
        return all_data

    # OLD CODE START — _login() removed (API-key auth replaces session cookies)
    # async def _login(self) -> bool:
    #     """Authenticate to the UniFi controller via POST /api/login.
    #
    #     Returns:
    #         True if login succeeded.
    #     """
    #     if not self._configured:
    #         return False
    #
    #     session = await self._get_session()
    #     url = f"{self._controller_url}/api/login"
    #     payload = {"username": self._username, "password": self._password}
    #
    #     try:
    #         async with session.post(url, json=payload) as resp:
    #             if resp.status == 200:
    #                 self._authenticated = True
    #                 self._last_error = None
    #                 logger.info("UniFi login successful")
    #                 return True
    #             else:
    #                 body = await resp.text()
    #                 self._last_error = (
    #                     f"Login failed: HTTP {resp.status} — {body[:200]}"
    #                 )
    #                 logger.warning("UniFi login failed: %s", self._last_error)
    #                 return False
    #     except Exception as exc:
    #         self._last_error = f"Login error: {exc}"
    #         logger.warning("UniFi login error: %s", exc)
    #         return False
    # OLD CODE END

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def get_info(self) -> dict:
        """GET /v1/info — retrieve UniFi Network application info.

        Returns:
            Dict with at least ``applicationVersion``.
        """
        return await self._request("GET", "/v1/info")

    async def list_sites(self) -> list[dict]:
        """GET /v1/sites — list all local sites (paginated).

        Returns:
            List of site dicts.
        """
        return await self._paginate("/v1/sites")

    async def test_connection(self) -> bool:
        """Test connectivity and API-key validity.

        Attempts GET /v1/info. Returns True on success, False on any error.
        """
        if not self._configured:
            self._last_error = "Not configured"
            return False

        try:
            await self.get_info()
            self._last_error = None
            return True
        except UnifiAuthError:
            self._last_error = "Invalid API key"
            return False
        except Exception as exc:
            self._last_error = f"Connection error: {exc}"
            logger.warning("UniFi connection test failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Helpers: site-aware path + cached poll
    # ------------------------------------------------------------------

    def _site_path(self, suffix: str) -> str:
        """Build a site-scoped API path.

        Args:
            suffix: Path after ``/v1/sites/{siteId}`` (e.g. "/clients").

        Returns:
            Full API path string.

        Raises:
            ValueError: If ``site_id`` is not set.
        """
        if not self._site_id:
            raise ValueError(
                "site_id is required — call configure(site_id=...) or "
                "list_sites() first"
            )
        return f"/v1/sites/{self._site_id}{suffix}"

    async def _cached_poll(
        self,
        cache_attr: str,
        time_attr: str,
        ttl: float,
        path: str,
        *,
        paginated: bool = True,
        label: str = "",
    ) -> list[dict]:
        """Generic cached-poll helper.

        Checks the cache TTL, fetches fresh data if stale, falls back to
        stale cache on errors.

        Args:
            cache_attr: Instance attribute name for the cached list.
            time_attr: Instance attribute name for the cache timestamp.
            ttl: Cache TTL in seconds.
            path: API path to poll.
            paginated: Whether to use ``_paginate`` or plain ``_request``.
            label: Human-readable name for log messages.

        Returns:
            List of data dicts (fresh or stale-cached).
        """
        if not self._configured:
            return []

        now = time.time()
        cache: list[dict] = getattr(self, cache_attr)
        cache_time: float = getattr(self, time_attr)

        # Return cache if fresh
        if cache and (now - cache_time) < ttl:
            return cache

        try:
            if paginated:
                data = await self._paginate(path)
            else:
                result = await self._request("GET", path)
                data = result.get("data", []) if isinstance(result, dict) else []

            setattr(self, cache_attr, data)
            setattr(self, time_attr, now)
            self._last_poll_time = now
            self._last_error = None
            logger.info("UniFi poll %s: got %d items", label or path, len(data))
            return data

        except Exception as exc:
            self._last_error = f"Poll error ({label or path}): {exc}"
            logger.warning("UniFi poll %s failed: %s", label or path, exc)
            return cache  # Return stale cache

    # ------------------------------------------------------------------
    # Clients (device enrichment — primary use case)
    # ------------------------------------------------------------------

    async def poll_clients(self) -> list[dict]:
        """GET /v1/sites/{siteId}/clients — list connected clients (paginated).

        Returns:
            List of client dicts from the API.
        """
        path = self._site_path("/clients")
        data = await self._cached_poll(
            "_cache_clients",
            "_cache_clients_time",
            _CACHE_TTL_CLIENTS,
            path,
            label="clients",
        )
        # Keep _device_cache in sync for get_device_alias() backward compat
        self._device_cache = data
        return data

    def get_device_alias(self, mac: str) -> str | None:
        """Get the user-assigned alias for a device from cached client data.

        Args:
            mac: MAC address (any format: colon, dash, dot, or bare).

        Returns:
            User-assigned name/alias string, or None if not found/not set.
        """
        # Normalize to uppercase colon-separated
        mac = mac.strip().upper().replace("-", ":").replace(".", ":")
        # Handle bare MACs (e.g. "AABBCCDDEEFF")
        if len(mac) == 12 and ":" not in mac:
            mac = ":".join(mac[i : i + 2] for i in range(0, 12, 2))

        for device in self._device_cache:
            device_mac = device.get("macAddress", device.get("mac", ""))
            # Normalize the stored MAC for comparison
            normalized = device_mac.strip().upper().replace("-", ":").replace(".", ":")
            if len(normalized) == 12 and ":" not in normalized:
                normalized = ":".join(
                    normalized[i : i + 2] for i in range(0, 12, 2)
                )
            if normalized == mac:
                return device.get("name", device.get("alias"))

        return None

    # OLD CODE START — legacy poll_devices() that fetched from /api/s/{site}/stat/sta
    # async def poll_devices(self) -> list[dict]:
    #     """Poll the UniFi controller for all client devices (legacy internal API).
    #
    #     Used POST /api/login for session cookies and GET /api/s/{site}/stat/sta
    #     for client list. Replaced by poll_clients() using official API.
    #     """
    #     ...
    # OLD CODE END

    # ------------------------------------------------------------------
    # Infrastructure (UniFi devices: APs, switches, gateways)
    # ------------------------------------------------------------------

    async def poll_devices(self) -> list[dict]:
        """GET /v1/sites/{siteId}/devices — list adopted devices (paginated).

        Returns:
            List of UniFi device dicts (APs, switches, gateways).
        """
        path = self._site_path("/devices")
        return await self._cached_poll(
            "_cache_devices",
            "_cache_devices_time",
            _CACHE_TTL_DEVICES,
            path,
            label="devices",
        )

    async def get_device_stats(self, device_id: str) -> dict:
        """GET /v1/sites/{siteId}/devices/{deviceId}/statistics/latest.

        Args:
            device_id: UUID of the adopted device.

        Returns:
            Latest statistics dict for the device.
        """
        path = self._site_path(f"/devices/{device_id}/statistics/latest")
        return await self._request("GET", path)

    # ------------------------------------------------------------------
    # Networks & WiFi
    # ------------------------------------------------------------------

    async def poll_networks(self) -> list[dict]:
        """GET /v1/sites/{siteId}/networks — list network configurations.

        Returns:
            List of network config dicts.
        """
        path = self._site_path("/networks")
        return await self._cached_poll(
            "_cache_networks",
            "_cache_networks_time",
            _CACHE_TTL_NETWORKS,
            path,
            paginated=False,
            label="networks",
        )

    async def poll_wifi(self) -> list[dict]:
        """GET /v1/sites/{siteId}/wifi/broadcasts — list WiFi SSIDs.

        Returns:
            List of WiFi broadcast dicts.
        """
        path = self._site_path("/wifi/broadcasts")
        return await self._cached_poll(
            "_cache_wifi",
            "_cache_wifi_time",
            _CACHE_TTL_WIFI,
            path,
            paginated=False,
            label="wifi",
        )

    # ------------------------------------------------------------------
    # Security: Firewall, ACLs, DNS
    # ------------------------------------------------------------------

    async def poll_firewall_policies(self) -> list[dict]:
        """GET /v1/sites/{siteId}/firewall/policies — list firewall policies.

        Returns:
            List of firewall policy dicts.
        """
        path = self._site_path("/firewall/policies")
        return await self._cached_poll(
            "_cache_firewall_policies",
            "_cache_firewall_policies_time",
            _CACHE_TTL_FIREWALL,
            path,
            paginated=False,
            label="firewall_policies",
        )

    async def poll_firewall_zones(self) -> list[dict]:
        """GET /v1/sites/{siteId}/firewall/zones — list firewall zones.

        Returns:
            List of firewall zone dicts.
        """
        path = self._site_path("/firewall/zones")
        return await self._cached_poll(
            "_cache_firewall_zones",
            "_cache_firewall_zones_time",
            _CACHE_TTL_FIREWALL,
            path,
            paginated=False,
            label="firewall_zones",
        )

    async def poll_acl_rules(self) -> list[dict]:
        """GET /v1/sites/{siteId}/acl-rules — list ACL rules.

        Returns:
            List of ACL rule dicts.
        """
        path = self._site_path("/acl-rules")
        return await self._cached_poll(
            "_cache_acl_rules",
            "_cache_acl_rules_time",
            _CACHE_TTL_FIREWALL,
            path,
            paginated=False,
            label="acl_rules",
        )

    async def poll_dns_policies(self) -> list[dict]:
        """GET /v1/sites/{siteId}/dns/policies — list DNS policies.

        Returns:
            List of DNS policy dicts.
        """
        path = self._site_path("/dns/policies")
        return await self._cached_poll(
            "_cache_dns_policies",
            "_cache_dns_policies_time",
            _CACHE_TTL_DNS,
            path,
            paginated=False,
            label="dns_policies",
        )

    # ------------------------------------------------------------------
    # DPI Reference Data
    # ------------------------------------------------------------------

    async def get_dpi_categories(self) -> list[dict]:
        """GET /v1/dpi/categories — list DPI categories (not site-scoped).

        Returns:
            List of DPI category dicts.
        """
        return await self._cached_poll(
            "_cache_dpi_categories",
            "_cache_dpi_categories_time",
            _CACHE_TTL_DPI,
            "/v1/dpi/categories",
            paginated=False,
            label="dpi_categories",
        )

    async def get_dpi_applications(self) -> list[dict]:
        """GET /v1/dpi/applications — list DPI applications (not site-scoped).

        Returns:
            List of DPI application dicts.
        """
        return await self._cached_poll(
            "_cache_dpi_applications",
            "_cache_dpi_applications_time",
            _CACHE_TTL_DPI,
            "/v1/dpi/applications",
            paginated=False,
            label="dpi_applications",
        )

    # ------------------------------------------------------------------
    # WAN & VPN
    # ------------------------------------------------------------------

    async def poll_wans(self) -> list[dict]:
        """GET /v1/sites/{siteId}/wans — list WAN interfaces.

        Returns:
            List of WAN dicts.
        """
        path = self._site_path("/wans")
        return await self._cached_poll(
            "_cache_wans",
            "_cache_wans_time",
            _CACHE_TTL_WANS,
            path,
            paginated=False,
            label="wans",
        )

    async def poll_vpn_tunnels(self) -> list[dict]:
        """GET /v1/sites/{siteId}/vpn/site-to-site-tunnels — list VPN tunnels.

        Returns:
            List of VPN tunnel dicts.
        """
        path = self._site_path("/vpn/site-to-site-tunnels")
        return await self._cached_poll(
            "_cache_vpn_tunnels",
            "_cache_vpn_tunnels_time",
            _CACHE_TTL_VPN,
            path,
            paginated=False,
            label="vpn_tunnels",
        )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Get the current integration status.

        Returns:
            Dict with: configured, controller_url, cache stats, last_error.
        """
        # Aggregate cache stats across all data types
        cache_stats: dict[str, int] = {}
        for name in (
            "clients", "devices", "networks", "wifi",
            "firewall_policies", "firewall_zones", "acl_rules",
            "dns_policies", "dpi_categories", "dpi_applications",
            "wans", "vpn_tunnels",
        ):
            cache_list: list[dict] = getattr(self, f"_cache_{name}", [])
            cache_stats[name] = len(cache_list)

        return {
            "configured": self._configured,
            "controller_url": self._base_url,
            "last_poll_time": self._last_poll_time,
            "cache_counts": cache_stats,
            # Legacy compat fields
            "cached_device_count": len(self._device_cache),
            "cache_age_seconds": (
                round(time.time() - self._cache_clients_time, 1)
                if self._cache_clients_time > 0
                else None
            ),
            "last_error": self._last_error,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session_factory:
            await self._session.close()
            self._session = None
