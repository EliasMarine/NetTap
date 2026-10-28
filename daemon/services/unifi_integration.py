"""
NetTap UniFi Controller Integration — Optional Tier-2 device enrichment.

Polls a UniFi Network Controller API for device aliases, AP associations,
and VLAN assignments. This is an optional enrichment source — the system
works perfectly without it. When configured and reachable, UniFi aliases
take top priority in device naming.

API endpoints used:
    POST /api/login            — authenticate session
    GET  /api/s/default/stat/sta    — connected clients (MAC, hostname, alias)
    GET  /api/s/default/stat/device — APs, switches, gateways

Graceful degradation: if the controller is unreachable or credentials are
wrong, we log a warning and continue with Tier 1 (passive) enrichment only.
"""

import logging
import time
from typing import Any

logger = logging.getLogger("nettap.services.unifi_integration")

# How often to poll the controller (seconds)
_POLL_INTERVAL = 300  # 5 minutes

# Cache TTL (seconds) — stale cache is better than no data
_CACHE_TTL = 600  # 10 minutes


class UnifiIntegration:
    """UniFi Controller API client for device enrichment.

    Usage:
        unifi = UnifiIntegration()
        unifi.configure("https://192.168.1.1:8443", "admin", "password")
        if unifi.test_connection():
            devices = unifi.poll_devices()
    """

    def __init__(self, session_factory: Any = None):
        """Initialize the UniFi integration.

        Args:
            session_factory: Optional callable that returns an HTTP session
                (for testing). Defaults to aiohttp.ClientSession.
        """
        self._controller_url: str | None = None
        self._username: str | None = None
        self._password: str | None = None
        self._site: str = "default"
        self._configured: bool = False

        # Session management
        self._session_factory = session_factory
        self._session: Any = None
        self._authenticated: bool = False

        # Cache
        self._device_cache: list[dict] = []
        self._cache_time: float = 0
        self._last_poll_time: float = 0
        self._last_error: str | None = None

    @property
    def is_configured(self) -> bool:
        return self._configured

    def configure(
        self,
        controller_url: str,
        username: str,
        password: str,
        site: str = "default",
    ) -> None:
        """Store controller credentials.

        Args:
            controller_url: Base URL (e.g. "https://192.168.1.1:8443").
            username: UniFi admin username.
            password: UniFi admin password.
            site: UniFi site name (default: "default").
        """
        # Strip trailing slash
        self._controller_url = controller_url.rstrip("/")
        self._username = username
        self._password = password
        self._site = site
        self._configured = True
        self._authenticated = False
        self._last_error = None
        logger.info("UniFi integration configured for %s", self._controller_url)

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

    async def _login(self) -> bool:
        """Authenticate to the UniFi controller.

        Returns:
            True if login succeeded.
        """
        if not self._configured:
            return False

        session = await self._get_session()
        url = f"{self._controller_url}/api/login"
        payload = {"username": self._username, "password": self._password}

        try:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    self._authenticated = True
                    self._last_error = None
                    logger.info("UniFi login successful")
                    return True
                else:
                    body = await resp.text()
                    self._last_error = f"Login failed: HTTP {resp.status} — {body[:200]}"
                    logger.warning("UniFi login failed: %s", self._last_error)
                    return False
        except Exception as exc:
            self._last_error = f"Login error: {exc}"
            logger.warning("UniFi login error: %s", exc)
            return False

    async def test_connection(self) -> bool:
        """Test connectivity to the UniFi controller.

        Returns:
            True if we can authenticate successfully.
        """
        if not self._configured:
            self._last_error = "Not configured"
            return False

        return await self._login()

    async def poll_devices(self) -> list[dict]:
        """Poll the UniFi controller for all client devices.

        Returns cached data if the cache is still fresh.

        Returns:
            List of device dicts with: mac, hostname, alias, ip, is_wired, etc.
        """
        if not self._configured:
            return []

        # Return cache if fresh
        now = time.time()
        if self._device_cache and (now - self._cache_time) < _CACHE_TTL:
            return self._device_cache

        # Ensure authenticated
        if not self._authenticated:
            if not await self._login():
                return self._device_cache  # Return stale cache if available

        session = await self._get_session()

        # Fetch clients (stations)
        clients_url = f"{self._controller_url}/api/s/{self._site}/stat/sta"
        devices: list[dict] = []

        try:
            async with session.get(clients_url) as resp:
                if resp.status == 401:
                    # Session expired, try re-login
                    self._authenticated = False
                    if not await self._login():
                        return self._device_cache
                    async with session.get(clients_url) as retry_resp:
                        if retry_resp.status != 200:
                            self._last_error = f"Clients fetch failed: HTTP {retry_resp.status}"
                            return self._device_cache
                        data = await retry_resp.json()
                elif resp.status != 200:
                    self._last_error = f"Clients fetch failed: HTTP {resp.status}"
                    return self._device_cache
                else:
                    data = await resp.json()

            raw_clients = data.get("data", [])
            for client in raw_clients:
                mac = client.get("mac", "").upper()
                if not mac:
                    continue

                # Normalize MAC to colon-separated
                if len(mac) == 12 and ":" not in mac:
                    mac = ":".join(mac[i:i+2] for i in range(0, 12, 2))

                devices.append({
                    "mac": mac,
                    "hostname": client.get("hostname"),
                    "alias": client.get("name"),  # User-set alias in UniFi
                    "ip": client.get("ip"),
                    "is_wired": client.get("is_wired", False),
                    "network": client.get("network"),
                    "oui": client.get("oui"),
                    "rx_bytes": client.get("rx_bytes", 0),
                    "tx_bytes": client.get("tx_bytes", 0),
                    "uptime": client.get("uptime", 0),
                    "last_seen": client.get("last_seen"),
                    "ap_mac": client.get("ap_mac"),
                })

            # Update cache
            self._device_cache = devices
            self._cache_time = now
            self._last_poll_time = now
            self._last_error = None
            logger.info("UniFi poll: got %d clients", len(devices))

        except Exception as exc:
            self._last_error = f"Poll error: {exc}"
            logger.warning("UniFi poll failed: %s", exc)
            return self._device_cache  # Return stale cache

        return devices

    def get_device_alias(self, mac: str) -> str | None:
        """Get the user-assigned alias for a device from cached data.

        Args:
            mac: MAC address (any format).

        Returns:
            User-assigned alias string, or None if not found/not set.
        """
        mac = mac.strip().upper().replace("-", ":").replace(".", ":")

        for device in self._device_cache:
            if device.get("mac") == mac:
                return device.get("alias")

        return None

    def get_status(self) -> dict:
        """Get the current integration status.

        Returns:
            Dict with: configured, authenticated, last_poll, device_count, last_error.
        """
        return {
            "configured": self._configured,
            "controller_url": self._controller_url,
            "authenticated": self._authenticated,
            "last_poll_time": self._last_poll_time,
            "cached_device_count": len(self._device_cache),
            "cache_age_seconds": (
                round(time.time() - self._cache_time, 1)
                if self._cache_time > 0
                else None
            ),
            "last_error": self._last_error,
        }

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session_factory:
            await self._session.close()
            self._session = None
