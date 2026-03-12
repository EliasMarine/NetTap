"""
Tests for the UnifiIntegration service.

Covers: configuration, test connection, poll devices, graceful degradation,
caching, device alias lookup, status reporting.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.unifi_integration import UnifiIntegration, _CACHE_TTL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockResponse:
    """Simulate an aiohttp response for testing."""

    def __init__(self, status: int, json_data: dict | None = None, text_data: str = ""):
        self.status = status
        self._json_data = json_data or {}
        self._text_data = text_data

    async def json(self):
        return self._json_data

    async def text(self):
        return self._text_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class MockSession:
    """Simulate an aiohttp ClientSession."""

    def __init__(self):
        self.post_responses: list[MockResponse] = []
        self.get_responses: list[MockResponse] = []
        self._post_call_count = 0
        self._get_call_count = 0
        self.closed = False

    def post(self, url, **kwargs):
        idx = min(self._post_call_count, len(self.post_responses) - 1)
        self._post_call_count += 1
        return self.post_responses[idx]

    def get(self, url, **kwargs):
        idx = min(self._get_call_count, len(self.get_responses) - 1)
        self._get_call_count += 1
        return self.get_responses[idx]

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
        username="admin",
        password="password123",
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
        """Should store controller URL, username, password."""
        unifi = UnifiIntegration()
        assert unifi.is_configured is False

        unifi.configure("https://10.0.0.1:8443", "admin", "pass")
        assert unifi.is_configured is True

    def test_configure_strips_trailing_slash(self):
        """Should normalize controller URL."""
        unifi = UnifiIntegration()
        unifi.configure("https://10.0.0.1:8443/", "admin", "pass")
        assert unifi._controller_url == "https://10.0.0.1:8443"

    def test_reconfigure_resets_auth(self):
        """Reconfiguring should reset authentication state."""
        unifi = UnifiIntegration()
        unifi.configure("https://10.0.0.1:8443", "admin", "pass")
        unifi._authenticated = True

        unifi.configure("https://10.0.0.2:8443", "admin2", "pass2")
        assert unifi._authenticated is False


# ---------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------


class TestTestConnection:
    @pytest.mark.asyncio
    async def test_successful_login(self, unifi, mock_session):
        """Should return True on HTTP 200 login response."""
        mock_session.post_responses = [MockResponse(200, {"data": []})]

        result = await unifi.test_connection()
        assert result is True
        assert unifi._authenticated is True

    @pytest.mark.asyncio
    async def test_failed_login(self, unifi, mock_session):
        """Should return False on HTTP 401."""
        mock_session.post_responses = [MockResponse(401, text_data="Unauthorized")]

        result = await unifi.test_connection()
        assert result is False
        assert unifi._authenticated is False
        assert unifi._last_error is not None

    @pytest.mark.asyncio
    async def test_connection_error(self, unifi):
        """Should return False and log error on network failure."""
        # Create a session that raises on post
        bad_session = MagicMock()
        bad_session.post.side_effect = Exception("Connection refused")
        unifi._session = bad_session

        result = await unifi.test_connection()
        assert result is False
        assert "Connection refused" in unifi._last_error

    @pytest.mark.asyncio
    async def test_unconfigured_returns_false(self, unifi_unconfigured):
        """Should return False when not configured."""
        result = await unifi_unconfigured.test_connection()
        assert result is False


# ---------------------------------------------------------------------------
# Poll devices
# ---------------------------------------------------------------------------


class TestPollDevices:
    @pytest.mark.asyncio
    async def test_poll_returns_devices(self, unifi, mock_session):
        """Should parse and return client devices from the API."""
        # Login response, then clients response
        mock_session.post_responses = [MockResponse(200, {"data": []})]
        mock_session.get_responses = [
            MockResponse(200, {
                "data": [
                    {
                        "mac": "aa:bb:cc:dd:ee:ff",
                        "hostname": "my-laptop",
                        "name": "Living Room Laptop",
                        "ip": "192.168.1.100",
                        "is_wired": True,
                    },
                    {
                        "mac": "11:22:33:44:55:66",
                        "hostname": "iphone",
                        "ip": "192.168.1.101",
                        "is_wired": False,
                    },
                ]
            }),
        ]

        devices = await unifi.poll_devices()

        assert len(devices) == 2
        assert devices[0]["mac"] == "AA:BB:CC:DD:EE:FF"
        assert devices[0]["alias"] == "Living Room Laptop"
        assert devices[0]["hostname"] == "my-laptop"
        assert devices[1]["mac"] == "11:22:33:44:55:66"

    @pytest.mark.asyncio
    async def test_poll_uses_cache(self, unifi, mock_session):
        """Should return cached data if cache is fresh."""
        mock_session.post_responses = [MockResponse(200)]
        mock_session.get_responses = [
            MockResponse(200, {"data": [{"mac": "aa:bb:cc:dd:ee:ff", "hostname": "test"}]}),
        ]

        # First poll
        devices1 = await unifi.poll_devices()

        # Reset get responses (should not be called again)
        mock_session.get_responses = [MockResponse(200, {"data": []})]
        mock_session._get_call_count = 0

        # Second poll should use cache
        devices2 = await unifi.poll_devices()
        assert len(devices2) == len(devices1)
        assert mock_session._get_call_count == 0  # No new GET request

    @pytest.mark.asyncio
    async def test_poll_refreshes_stale_cache(self, unifi, mock_session):
        """Should re-poll when cache is expired."""
        mock_session.post_responses = [MockResponse(200), MockResponse(200)]
        mock_session.get_responses = [
            MockResponse(200, {"data": [{"mac": "aa:bb:cc:dd:ee:ff"}]}),
            MockResponse(200, {"data": [{"mac": "11:22:33:44:55:66"}]}),
        ]

        # First poll
        await unifi.poll_devices()

        # Expire cache
        unifi._cache_time = time.time() - _CACHE_TTL - 1

        # Second poll should hit the API again
        devices = await unifi.poll_devices()
        assert mock_session._get_call_count == 2

    @pytest.mark.asyncio
    async def test_poll_unconfigured_returns_empty(self, unifi_unconfigured):
        """Should return empty list when not configured."""
        devices = await unifi_unconfigured.poll_devices()
        assert devices == []

    @pytest.mark.asyncio
    async def test_poll_handles_session_expiry(self, unifi, mock_session):
        """Should re-login and retry on 401."""
        # First GET returns 401, login succeeds, retry GET succeeds
        mock_session.post_responses = [
            MockResponse(200),  # Initial login
            MockResponse(200),  # Re-login after 401
        ]
        mock_session.get_responses = [
            MockResponse(401),  # Expired session
            MockResponse(200, {"data": [{"mac": "aa:bb:cc:dd:ee:ff"}]}),
        ]

        devices = await unifi.poll_devices()
        assert len(devices) == 1

    @pytest.mark.asyncio
    async def test_poll_returns_stale_cache_on_error(self, unifi, mock_session):
        """Should return stale cache when API is unreachable."""
        mock_session.post_responses = [MockResponse(200)]
        mock_session.get_responses = [
            MockResponse(200, {"data": [{"mac": "aa:bb:cc:dd:ee:ff"}]}),
        ]

        # First poll succeeds
        await unifi.poll_devices()

        # Expire cache
        unifi._cache_time = time.time() - _CACHE_TTL - 1

        # Second poll fails
        unifi._session = MagicMock()
        unifi._session.get.side_effect = Exception("Network error")
        unifi._session.post.side_effect = Exception("Network error")
        unifi._authenticated = False

        devices = await unifi.poll_devices()
        assert len(devices) == 1  # Stale cache returned


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

    def test_get_alias_not_found(self, unifi):
        """Should return None for unknown MAC."""
        unifi._device_cache = []
        assert unifi.get_device_alias("FF:FF:FF:FF:FF:FF") is None

    def test_get_alias_no_alias_set(self, unifi):
        """Should return None when device has no alias."""
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


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_status_unconfigured(self, unifi_unconfigured):
        """Should report unconfigured state."""
        status = unifi_unconfigured.get_status()
        assert status["configured"] is False
        assert status["authenticated"] is False
        assert status["cached_device_count"] == 0

    def test_status_configured(self, unifi):
        """Should report configured state."""
        status = unifi.get_status()
        assert status["configured"] is True
        assert status["controller_url"] == "https://192.168.1.1:8443"

    @pytest.mark.asyncio
    async def test_status_after_poll(self, unifi, mock_session):
        """Should report device count after polling."""
        mock_session.post_responses = [MockResponse(200)]
        mock_session.get_responses = [
            MockResponse(200, {"data": [
                {"mac": "aa:bb:cc:dd:ee:ff"},
                {"mac": "11:22:33:44:55:66"},
            ]}),
        ]

        await unifi.poll_devices()
        status = unifi.get_status()

        assert status["cached_device_count"] == 2
        assert status["cache_age_seconds"] is not None
        assert status["last_error"] is None

    def test_status_with_error(self, unifi):
        """Should include last error in status."""
        unifi._last_error = "Connection refused"
        status = unifi.get_status()
        assert status["last_error"] == "Connection refused"
