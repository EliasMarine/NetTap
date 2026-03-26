"""
Tests for the UnifiIntegration service (official API v10.2.93, API-key auth).

Covers: configuration, test connection (GET /v1/info), poll_clients,
poll_devices, graceful degradation, caching, pagination, device alias
lookup, status reporting, security/DPI/WAN/VPN polling.

Uses asyncio.new_event_loop().run_until_complete() instead of pytest-asyncio
to avoid dependency on the installed pytest-asyncio version.
"""

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from services.unifi_integration import (
    UnifiAuthError,
    UnifiIntegration,
    _CACHE_TTL_CLIENTS,
    _CACHE_TTL_DEVICES,
    _CACHE_TTL_DPI,
    _CACHE_TTL_FIREWALL,
    _CACHE_TTL_NETWORKS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run an async coroutine synchronously for testing."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class MockResponse:
    """Simulate an aiohttp response for testing."""

    def __init__(
        self,
        status: int,
        json_data: dict | None = None,
        text_data: str = "",
    ):
        self.status = status
        self._json_data = json_data or {}
        self._text_data = text_data

    async def json(self):
        return self._json_data

    async def text(self):
        return self._text_data

    def raise_for_status(self):
        """Mimic aiohttp's raise_for_status — raise on 4xx/5xx (except 401
        which is handled explicitly before this is called)."""
        if self.status >= 400:
            raise Exception(f"HTTP {self.status}: {self._text_data}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class MockSession:
    """Simulate an aiohttp ClientSession.

    The _request() method uses ``session.request(method, url, ...)``,
    so we route through a unified ``request()`` dispatcher.
    """

    def __init__(self):
        self.request_responses: list[MockResponse] = []
        self._request_call_count = 0
        self.closed = False
        # Track calls for assertions
        self.request_log: list[dict] = []

    def request(self, method, url, **kwargs):
        """Return the next queued response."""
        self.request_log.append({"method": method, "url": url, **kwargs})
        idx = min(self._request_call_count, len(self.request_responses) - 1)
        self._request_call_count += 1
        return self.request_responses[idx]

    # Legacy helpers — redirect to request()
    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    async def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_session():
    return MockSession()


@pytest.fixture
def unifi(mock_session):
    """Return a configured UnifiIntegration with a mock session."""
    integration = UnifiIntegration(session_factory=lambda: mock_session)
    integration.configure(
        controller_url="https://192.168.1.1:8443",
        api_key="test-api-key-abc123",
        site_id="site-uuid-001",
    )
    return integration


@pytest.fixture
def unifi_unconfigured():
    """Return an unconfigured UnifiIntegration."""
    return UnifiIntegration(session_factory=lambda: MockSession())


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestConfigure:
    def test_configure_sets_fields(self):
        """Should store controller URL and API key."""
        unifi = UnifiIntegration()
        assert unifi.is_configured is False

        unifi.configure("https://10.0.0.1:8443", api_key="my-key")
        assert unifi.is_configured is True

    def test_configure_strips_trailing_slash(self):
        """Should normalize controller URL."""
        unifi = UnifiIntegration()
        unifi.configure("https://10.0.0.1:8443/", api_key="key")
        assert unifi._base_url == "https://10.0.0.1:8443"

    def test_reconfigure_clears_error(self):
        """Reconfiguring should clear last error."""
        unifi = UnifiIntegration()
        unifi.configure("https://10.0.0.1:8443", api_key="key1")
        unifi._last_error = "previous error"

        unifi.configure("https://10.0.0.2:8443", api_key="key2")
        assert unifi._last_error is None

    def test_configure_stores_site_id(self):
        """Should store the site_id when provided."""
        unifi = UnifiIntegration()
        unifi.configure(
            "https://10.0.0.1:8443",
            api_key="key",
            site_id="my-site-uuid",
        )
        assert unifi._site_id == "my-site-uuid"

    def test_is_configured_false_by_default(self):
        """is_configured should be False before configure() is called."""
        unifi = UnifiIntegration()
        assert unifi.is_configured is False
        assert unifi._base_url is None
        assert unifi._api_key is None

    def test_reconfigure_resets_caches(self):
        """Reconfiguring should clear error state and update fields."""
        unifi = UnifiIntegration()
        unifi.configure("https://10.0.0.1", api_key="key-1", site_id="s1")
        unifi._cache_clients = [{"mac": "AA:BB:CC:DD:EE:FF"}]
        unifi._cache_clients_time = time.time()
        unifi._last_error = "old error"

        # Reconfigure — error should be cleared
        unifi.configure("https://10.0.0.2", api_key="key-2", site_id="s2")
        assert unifi._base_url == "https://10.0.0.2"
        assert unifi._api_key == "key-2"
        assert unifi._last_error is None

    def test_configure_site_id_defaults_none(self):
        """site_id should default to None when not provided."""
        unifi = UnifiIntegration()
        unifi.configure("https://10.0.0.1:8443", api_key="key")
        assert unifi._site_id is None


# ---------------------------------------------------------------------------
# Test connection (GET /v1/info)
# ---------------------------------------------------------------------------


class TestTestConnection:
    def test_successful_connection(self, unifi, mock_session):
        """Should return True on successful GET /v1/info."""
        mock_session.request_responses = [
            MockResponse(200, {"applicationVersion": "10.2.93"}),
        ]

        result = _run(unifi.test_connection())
        assert result is True
        assert unifi._last_error is None

    def test_invalid_api_key(self, unifi, mock_session):
        """Should return False on HTTP 401 (invalid API key)."""
        mock_session.request_responses = [
            MockResponse(401, text_data="Unauthorized"),
        ]

        result = _run(unifi.test_connection())
        assert result is False
        assert "Invalid API key" in unifi._last_error

    def test_connection_error(self, unifi):
        """Should return False and log error on network failure."""
        bad_session = MagicMock()
        bad_session.request.side_effect = Exception("Connection refused")
        unifi._session = bad_session

        result = _run(unifi.test_connection())
        assert result is False
        assert "Connection refused" in unifi._last_error

    def test_unconfigured_returns_false(self, unifi_unconfigured):
        """Should return False when not configured."""
        result = _run(unifi_unconfigured.test_connection())
        assert result is False

    def test_sends_api_key_header(self, unifi, mock_session):
        """Should send X-API-Key header in the request."""
        mock_session.request_responses = [
            MockResponse(200, {"applicationVersion": "10.2.93"}),
        ]

        _run(unifi.test_connection())

        assert len(mock_session.request_log) == 1
        call = mock_session.request_log[0]
        assert call["method"] == "GET"
        assert "/proxy/network/integration/v1/info" in call["url"]
        assert call["headers"]["X-API-Key"] == "test-api-key-abc123"


# ---------------------------------------------------------------------------
# Core _request() method
# ---------------------------------------------------------------------------


class TestRequest:
    def test_request_builds_correct_url(self, unifi, mock_session):
        """Should build URL with /proxy/network/integration prefix."""
        mock_session.request_responses = [
            MockResponse(200, {"data": []}),
        ]

        _run(unifi._request("GET", "/v1/info"))

        call = mock_session.request_log[0]
        assert call["url"] == (
            "https://192.168.1.1:8443/proxy/network/integration/v1/info"
        )

    def test_request_raises_on_401(self, unifi, mock_session):
        """Should raise UnifiAuthError on 401."""
        mock_session.request_responses = [
            MockResponse(401, text_data="Unauthorized"),
        ]

        with pytest.raises(UnifiAuthError, match="Invalid API key"):
            _run(unifi._request("GET", "/v1/info"))

    def test_request_raises_on_server_error(self, unifi, mock_session):
        """Should raise on non-2xx status (via raise_for_status)."""
        mock_session.request_responses = [
            MockResponse(500, text_data="Internal Server Error"),
        ]

        with pytest.raises(Exception, match="HTTP 500"):
            _run(unifi._request("GET", "/v1/info"))


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestPaginate:
    def test_single_page(self, unifi, mock_session):
        """Should return data from a single page when count < limit."""
        mock_session.request_responses = [
            MockResponse(200, {"data": [{"id": 1}, {"id": 2}]}),
        ]

        result = _run(unifi._paginate("/v1/sites"))
        assert len(result) == 2
        assert result[0]["id"] == 1

    def test_multi_page(self, unifi, mock_session):
        """Should fetch multiple pages when first page is full."""
        # First page returns exactly 200 items (limit), so we fetch another
        page1 = [{"id": i} for i in range(200)]
        page2 = [{"id": i} for i in range(200, 250)]

        mock_session.request_responses = [
            MockResponse(200, {"data": page1}),
            MockResponse(200, {"data": page2}),
        ]

        result = _run(unifi._paginate("/v1/sites"))
        assert len(result) == 250

    def test_pagination_params(self, unifi, mock_session):
        """Should send offset and limit as query params."""
        mock_session.request_responses = [
            MockResponse(200, {"data": []}),
        ]

        _run(unifi._paginate("/v1/sites", params={"filter": "name.eq('test')"}))

        call = mock_session.request_log[0]
        params = call["params"]
        assert params["offset"] == 0
        assert params["limit"] == 200
        assert params["filter"] == "name.eq('test')"


# ---------------------------------------------------------------------------
# Poll clients (device enrichment)
# ---------------------------------------------------------------------------


class TestPollClients:
    def test_poll_returns_clients(self, unifi, mock_session):
        """Should fetch and return client data from the API."""
        mock_session.request_responses = [
            MockResponse(200, {
                "data": [
                    {"macAddress": "AA:BB:CC:DD:EE:FF", "name": "Laptop"},
                    {"macAddress": "11:22:33:44:55:66", "name": "Phone"},
                ],
            }),
        ]

        clients = _run(unifi.poll_clients())
        assert len(clients) == 2

    def test_poll_clients_uses_cache(self, unifi, mock_session):
        """Should return cached data if cache is fresh."""
        mock_session.request_responses = [
            MockResponse(200, {"data": [{"macAddress": "AA:BB:CC:DD:EE:FF"}]}),
        ]

        # First poll
        clients1 = _run(unifi.poll_clients())

        # Reset call count
        mock_session._request_call_count = 0

        # Second poll should use cache
        clients2 = _run(unifi.poll_clients())
        assert len(clients2) == len(clients1)
        assert mock_session._request_call_count == 0

    def test_poll_clients_refreshes_stale_cache(self, unifi, mock_session):
        """Should re-poll when cache is expired."""
        mock_session.request_responses = [
            MockResponse(200, {"data": [{"macAddress": "AA:BB:CC:DD:EE:FF"}]}),
            MockResponse(200, {"data": [{"macAddress": "11:22:33:44:55:66"}]}),
        ]

        # First poll
        _run(unifi.poll_clients())

        # Expire cache
        unifi._cache_clients_time = time.time() - _CACHE_TTL_CLIENTS - 1

        # Second poll should hit the API again
        clients = _run(unifi.poll_clients())
        assert mock_session._request_call_count == 2
        assert len(clients) == 1

    def test_poll_clients_handles_auth_error(self, unifi, mock_session):
        """Should return empty cache and record error on 401 (auth error)."""
        mock_session.request_responses = [
            MockResponse(401, text_data="Unauthorized"),
        ]

        clients = _run(unifi.poll_clients())
        assert clients == []
        assert unifi._last_error is not None
        assert "Invalid API key" in unifi._last_error

    def test_poll_clients_unconfigured_raises(self, unifi_unconfigured):
        """Should raise ValueError when site_id is not set (unconfigured).

        poll_clients() calls _site_path() before _cached_poll(); without
        site_id the path builder raises immediately.
        """
        with pytest.raises(ValueError, match="site_id is required"):
            _run(unifi_unconfigured.poll_clients())

    def test_poll_clients_returns_stale_on_error(self, unifi, mock_session):
        """Should return stale cache when API is unreachable."""
        mock_session.request_responses = [
            MockResponse(200, {"data": [{"macAddress": "AA:BB:CC:DD:EE:FF"}]}),
        ]

        # First poll succeeds
        _run(unifi.poll_clients())

        # Expire cache
        unifi._cache_clients_time = time.time() - _CACHE_TTL_CLIENTS - 1

        # Break the session
        unifi._session = MagicMock()
        unifi._session.request.side_effect = Exception("Network error")

        clients = _run(unifi.poll_clients())
        assert len(clients) == 1  # Stale cache returned

    def test_poll_clients_syncs_device_cache(self, unifi, mock_session):
        """poll_clients() should update _device_cache for get_device_alias()."""
        mock_session.request_responses = [
            MockResponse(200, {
                "data": [
                    {"macAddress": "AA:BB:CC:DD:EE:FF", "name": "Test Device"},
                ],
            }),
        ]

        _run(unifi.poll_clients())
        assert len(unifi._device_cache) == 1


# ---------------------------------------------------------------------------
# Poll devices (infrastructure: APs, switches, gateways)
# ---------------------------------------------------------------------------


class TestPollDevices:
    def test_poll_returns_devices(self, unifi, mock_session):
        """Should fetch infrastructure devices from the API."""
        mock_session.request_responses = [
            MockResponse(200, {
                "data": [
                    {
                        "id": "device-1",
                        "macAddress": "AA:BB:CC:DD:EE:01",
                        "name": "Main AP",
                        "model": "U6-LR",
                        "state": "ONLINE",
                    },
                ],
            }),
        ]

        devices = _run(unifi.poll_devices())
        assert len(devices) == 1
        assert devices[0]["name"] == "Main AP"

    def test_poll_devices_uses_cache(self, unifi, mock_session):
        """Should return cached device data if fresh."""
        mock_session.request_responses = [
            MockResponse(200, {"data": [{"id": "d1"}]}),
        ]

        _run(unifi.poll_devices())
        mock_session._request_call_count = 0

        devices2 = _run(unifi.poll_devices())
        assert len(devices2) == 1
        assert mock_session._request_call_count == 0

    def test_poll_devices_refreshes_stale(self, unifi, mock_session):
        """Should re-poll when device cache expires."""
        mock_session.request_responses = [
            MockResponse(200, {"data": [{"id": "d1"}]}),
            MockResponse(200, {"data": [{"id": "d2"}, {"id": "d3"}]}),
        ]

        _run(unifi.poll_devices())
        unifi._cache_devices_time = time.time() - _CACHE_TTL_DEVICES - 1

        devices = _run(unifi.poll_devices())
        assert len(devices) == 2
        assert mock_session._request_call_count == 2

    def test_poll_devices_unconfigured_raises(self, unifi_unconfigured):
        """Should raise ValueError when site_id is not set (unconfigured).

        poll_devices() calls _site_path() before _cached_poll(); without
        site_id the path builder raises immediately.
        """
        with pytest.raises(ValueError, match="site_id is required"):
            _run(unifi_unconfigured.poll_devices())


# ---------------------------------------------------------------------------
# Device stats
# ---------------------------------------------------------------------------


class TestGetDeviceStats:
    def test_returns_stats(self, unifi, mock_session):
        """Should fetch latest stats for a device."""
        mock_session.request_responses = [
            MockResponse(200, {"uptimeSeconds": 86400, "cpuUsage": 12.5}),
        ]

        stats = _run(unifi.get_device_stats("device-uuid-123"))
        assert stats["uptimeSeconds"] == 86400


# ---------------------------------------------------------------------------
# Device alias
# ---------------------------------------------------------------------------


class TestGetDeviceAlias:
    def test_get_alias_found(self, unifi):
        """Should return the alias for a known device."""
        unifi._device_cache = [
            {"mac": "AA:BB:CC:DD:EE:FF", "alias": "Living Room TV"},
        ]

        assert unifi.get_device_alias("AA:BB:CC:DD:EE:FF") == "Living Room TV"

    def test_get_alias_found_via_macAddress(self, unifi):
        """Should work with official API 'macAddress' field."""
        unifi._device_cache = [
            {"macAddress": "AA:BB:CC:DD:EE:FF", "name": "Living Room TV"},
        ]

        assert unifi.get_device_alias("AA:BB:CC:DD:EE:FF") == "Living Room TV"

    def test_get_alias_not_found(self, unifi):
        """Should return None for unknown MAC."""
        unifi._device_cache = []
        assert unifi.get_device_alias("FF:FF:FF:FF:FF:FF") is None

    def test_get_alias_no_alias_set(self, unifi):
        """Should return None when device has no name/alias."""
        unifi._device_cache = [
            {"mac": "AA:BB:CC:DD:EE:FF", "alias": None},
        ]

        assert unifi.get_device_alias("AA:BB:CC:DD:EE:FF") is None

    def test_get_alias_normalizes_mac(self, unifi):
        """Should normalize MAC format before lookup."""
        unifi._device_cache = [
            {"mac": "AA:BB:CC:DD:EE:FF", "alias": "Test"},
        ]

        assert unifi.get_device_alias("aa-bb-cc-dd-ee-ff") == "Test"

    def test_get_alias_normalizes_bare_mac(self, unifi):
        """Should handle bare MAC addresses (no separators)."""
        unifi._device_cache = [
            {"mac": "AA:BB:CC:DD:EE:FF", "alias": "Test"},
        ]

        assert unifi.get_device_alias("AABBCCDDEEFF") == "Test"


# ---------------------------------------------------------------------------
# Security polling
# ---------------------------------------------------------------------------


class TestSecurityPolling:
    def test_poll_firewall_policies(self, unifi, mock_session):
        """Should fetch firewall policies."""
        mock_session.request_responses = [
            MockResponse(200, {"data": [{"id": "policy-1", "action": "ALLOW"}]}),
        ]

        policies = _run(unifi.poll_firewall_policies())
        assert len(policies) == 1

    def test_poll_firewall_zones(self, unifi, mock_session):
        """Should fetch firewall zones."""
        mock_session.request_responses = [
            MockResponse(200, {"data": [{"id": "zone-1", "name": "LAN"}]}),
        ]

        zones = _run(unifi.poll_firewall_zones())
        assert len(zones) == 1

    def test_poll_acl_rules(self, unifi, mock_session):
        """Should fetch ACL rules."""
        mock_session.request_responses = [
            MockResponse(200, {"data": [{"id": "acl-1"}]}),
        ]

        rules = _run(unifi.poll_acl_rules())
        assert len(rules) == 1

    def test_poll_dns_policies(self, unifi, mock_session):
        """Should fetch DNS policies."""
        mock_session.request_responses = [
            MockResponse(200, {"data": [{"id": "dns-1"}]}),
        ]

        policies = _run(unifi.poll_dns_policies())
        assert len(policies) == 1

    def test_firewall_cache(self, unifi, mock_session):
        """Firewall data should be cached for 10 minutes."""
        mock_session.request_responses = [
            MockResponse(200, {"data": [{"id": "policy-1"}]}),
        ]

        _run(unifi.poll_firewall_policies())
        mock_session._request_call_count = 0

        # Second call should use cache
        _run(unifi.poll_firewall_policies())
        assert mock_session._request_call_count == 0

        # Expire cache
        unifi._cache_firewall_policies_time = (
            time.time() - _CACHE_TTL_FIREWALL - 1
        )
        mock_session.request_responses = [
            MockResponse(200, {"data": [{"id": "policy-2"}]}),
        ]

        policies = _run(unifi.poll_firewall_policies())
        assert mock_session._request_call_count == 1
        assert policies[0]["id"] == "policy-2"


# ---------------------------------------------------------------------------
# DPI reference data
# ---------------------------------------------------------------------------


class TestDpiPolling:
    def test_get_dpi_categories(self, unifi, mock_session):
        """Should fetch DPI categories (not site-scoped)."""
        mock_session.request_responses = [
            MockResponse(200, {
                "data": [
                    {"id": 1, "name": "Social Media"},
                    {"id": 2, "name": "Streaming"},
                ],
            }),
        ]

        categories = _run(unifi.get_dpi_categories())
        assert len(categories) == 2

    def test_get_dpi_applications(self, unifi, mock_session):
        """Should fetch DPI applications."""
        mock_session.request_responses = [
            MockResponse(200, {"data": [{"id": 1, "name": "YouTube"}]}),
        ]

        apps = _run(unifi.get_dpi_applications())
        assert len(apps) == 1

    def test_dpi_uses_long_ttl_cache(self, unifi, mock_session):
        """DPI data should use 1-hour TTL."""
        mock_session.request_responses = [
            MockResponse(200, {"data": [{"id": 1}]}),
        ]

        _run(unifi.get_dpi_categories())
        mock_session._request_call_count = 0

        # Should use cache within 1 hour
        _run(unifi.get_dpi_categories())
        assert mock_session._request_call_count == 0

        # Expire after 1 hour
        unifi._cache_dpi_categories_time = time.time() - _CACHE_TTL_DPI - 1
        mock_session.request_responses = [
            MockResponse(200, {"data": [{"id": 2}]}),
        ]

        result = _run(unifi.get_dpi_categories())
        assert mock_session._request_call_count == 1
        assert result[0]["id"] == 2


# ---------------------------------------------------------------------------
# Networks & WiFi
# ---------------------------------------------------------------------------


class TestNetworkWifiPolling:
    def test_poll_networks(self, unifi, mock_session):
        """Should fetch network configurations."""
        mock_session.request_responses = [
            MockResponse(200, {
                "data": [{"id": "net-1", "name": "Default"}],
            }),
        ]

        networks = _run(unifi.poll_networks())
        assert len(networks) == 1

    def test_poll_wifi(self, unifi, mock_session):
        """Should fetch WiFi broadcasts."""
        mock_session.request_responses = [
            MockResponse(200, {
                "data": [{"id": "wifi-1", "name": "HomeNet"}],
            }),
        ]

        wifi = _run(unifi.poll_wifi())
        assert len(wifi) == 1

    def test_networks_cache(self, unifi, mock_session):
        """Network data should use 10-minute TTL."""
        mock_session.request_responses = [
            MockResponse(200, {"data": [{"id": "net-1"}]}),
        ]

        _run(unifi.poll_networks())
        mock_session._request_call_count = 0

        _run(unifi.poll_networks())
        assert mock_session._request_call_count == 0

        unifi._cache_networks_time = time.time() - _CACHE_TTL_NETWORKS - 1
        mock_session.request_responses = [
            MockResponse(200, {"data": [{"id": "net-2"}]}),
        ]

        networks = _run(unifi.poll_networks())
        assert mock_session._request_call_count == 1
        assert len(networks) == 1


# ---------------------------------------------------------------------------
# WAN & VPN
# ---------------------------------------------------------------------------


class TestWanVpnPolling:
    def test_poll_wans(self, unifi, mock_session):
        """Should fetch WAN interfaces."""
        mock_session.request_responses = [
            MockResponse(200, {"data": [{"id": "wan-1"}]}),
        ]

        wans = _run(unifi.poll_wans())
        assert len(wans) == 1

    def test_poll_vpn_tunnels(self, unifi, mock_session):
        """Should fetch VPN tunnels."""
        mock_session.request_responses = [
            MockResponse(200, {"data": [{"id": "vpn-1"}]}),
        ]

        tunnels = _run(unifi.poll_vpn_tunnels())
        assert len(tunnels) == 1


# ---------------------------------------------------------------------------
# Sites discovery
# ---------------------------------------------------------------------------


class TestListSites:
    def test_list_sites(self, unifi, mock_session):
        """Should list sites via paginated GET /v1/sites."""
        mock_session.request_responses = [
            MockResponse(200, {
                "data": [
                    {"id": "site-1", "name": "Default"},
                    {"id": "site-2", "name": "Office"},
                ],
            }),
        ]

        sites = _run(unifi.list_sites())
        assert len(sites) == 2

    def test_list_sites_handles_pagination(self, unifi, mock_session):
        """Should fetch multiple pages until a page returns fewer than limit."""
        # First page: 200 items (full page = limit)
        page1 = [{"id": f"site-{i}"} for i in range(200)]
        # Second page: 50 items (partial page = end of data)
        page2 = [{"id": f"site-{200 + i}"} for i in range(50)]

        mock_session.request_responses = [
            MockResponse(200, {"data": page1}),
            MockResponse(200, {"data": page2}),
        ]

        sites = _run(unifi.list_sites())
        assert len(sites) == 250
        assert mock_session._request_call_count == 2


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_status_unconfigured(self, unifi_unconfigured):
        """Should report unconfigured state."""
        status = unifi_unconfigured.get_status()
        assert status["configured"] is False
        assert status["cached_device_count"] == 0

    def test_status_configured(self, unifi):
        """Should report configured state."""
        status = unifi.get_status()
        assert status["configured"] is True
        assert status["controller_url"] == "https://192.168.1.1:8443"

    def test_status_after_poll(self, unifi, mock_session):
        """Should report cache counts after polling."""
        mock_session.request_responses = [
            MockResponse(200, {"data": [
                {"macAddress": "AA:BB:CC:DD:EE:FF"},
                {"macAddress": "11:22:33:44:55:66"},
            ]}),
        ]

        _run(unifi.poll_clients())
        status = unifi.get_status()

        assert status["cached_device_count"] == 2
        assert status["cache_counts"]["clients"] == 2
        assert status["cache_age_seconds"] is not None
        assert status["last_error"] is None

    def test_status_with_error(self, unifi):
        """Should include last error in status."""
        unifi._last_error = "Connection refused"
        status = unifi.get_status()
        assert status["last_error"] == "Connection refused"

    def test_status_includes_cache_counts(self, unifi):
        """Should report zero counts for all data types when empty."""
        status = unifi.get_status()
        assert "cache_counts" in status
        assert status["cache_counts"]["clients"] == 0
        assert status["cache_counts"]["devices"] == 0
        assert status["cache_counts"]["firewall_policies"] == 0
        assert status["cache_counts"]["dpi_categories"] == 0


# ---------------------------------------------------------------------------
# Site path helper
# ---------------------------------------------------------------------------


class TestSitePath:
    def test_builds_correct_path(self, unifi):
        """Should build /v1/sites/{siteId}/suffix."""
        path = unifi._site_path("/clients")
        assert path == "/v1/sites/site-uuid-001/clients"

    def test_raises_without_site_id(self):
        """Should raise ValueError if site_id is not set."""
        unifi = UnifiIntegration()
        unifi.configure("https://10.0.0.1", api_key="key")
        # site_id is None

        with pytest.raises(ValueError, match="site_id is required"):
            unifi._site_path("/clients")


# ---------------------------------------------------------------------------
# Close / lifecycle
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_with_factory_session(self, unifi, mock_session):
        """Should NOT close a factory-provided session (caller owns it)."""
        # Trigger session creation
        _run(unifi._get_session())
        _run(unifi.close())
        # Session should still exist (factory sessions are not closed)
        assert not mock_session.closed

    def test_close_without_session(self, unifi_unconfigured):
        """Should be a no-op if no session was created."""
        _run(unifi_unconfigured.close())  # Should not raise
