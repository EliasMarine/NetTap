"""
Tests for UniFi controller identity changes (services/unifi_integration.py
and the configure endpoint in api/devices_v2.py).

Covers: the stored API key cannot be redirected to another controller,
site_id is kept when omitted, ``connected`` needs a successful poll for the
current configuration, a controller change resets state, and a slow poll or
connection test for the old controller can never touch the new one's status
or caches, whether it succeeds or fails.
"""

import asyncio
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.devices_v2 import register_devices_v2_routes
from services.unifi_integration import UnifiIntegration

URL_A = "https://10.0.0.1"
URL_B = "https://10.0.0.2"


@pytest.fixture(autouse=True)
def _unifi_config_file(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_CONFIG_FILE", str(tmp_path / "unifi_config.json"))


class _Response:
    def __init__(self, data: dict | None = None, error: Exception | None = None):
        self._data = data or {"data": []}
        self._error = error
        self.status = 200

    def raise_for_status(self):
        pass

    async def json(self):
        return self._data


class _Request:
    """Async context manager for one request; optionally held at a gate."""

    def __init__(self, response: _Response, gate: asyncio.Event | None, entered):
        self._response = response
        self._gate = gate
        self._entered = entered

    async def __aenter__(self):
        if self._gate is not None:
            self._entered.set()
            await self._gate.wait()
        if self._response._error is not None:
            raise self._response._error
        return self._response

    async def __aexit__(self, *args):
        pass


class _Session:
    """Answers controller A after a gate opens; answers B immediately."""

    def __init__(self, a_response: _Response, b_response: _Response):
        self.a_response = a_response
        self.b_response = b_response
        self.gate = asyncio.Event()
        self.a_entered = asyncio.Event()
        self.urls: list[str] = []

    def request(self, method, url, **kwargs):
        self.urls.append(url)
        if url.startswith(URL_A):
            return _Request(self.a_response, self.gate, self.a_entered)
        return _Request(self.b_response, None, None)

    async def close(self):
        pass


B_CLIENTS = {"data": [{"macAddress": "BB:BB:BB:BB:BB:BB", "name": "b-laptop"}]}
A_CLIENTS = {"data": [{"macAddress": "AA:AA:AA:AA:AA:AA", "name": "a-phone"}]}
A_FAILURE = ConnectionError("controller A timed out")


async def _old_poll_finishes_after_b(a_response: _Response) -> UnifiIntegration:
    session = _Session(a_response, _Response(B_CLIENTS))
    unifi = UnifiIntegration(session_factory=lambda: session)
    unifi.configure(URL_A, api_key="key-a", site_id="site-a")

    a_poll = asyncio.create_task(unifi.poll_clients())
    await session.a_entered.wait()

    unifi.configure(URL_B, api_key="key-b", site_id="site-b")
    assert await unifi.poll_clients() == B_CLIENTS["data"]

    session.gate.set()
    await a_poll
    return unifi


async def _old_test_finishes_after_b(a_response: _Response) -> UnifiIntegration:
    session = _Session(a_response, _Response(B_CLIENTS))
    unifi = UnifiIntegration(session_factory=lambda: session)
    unifi.configure(URL_A, api_key="key-a", site_id="site-a")

    a_test = asyncio.create_task(unifi.test_connection())
    await session.a_entered.wait()

    unifi.configure(URL_B, api_key="key-b", site_id="site-b")
    await unifi.poll_clients()

    session.gate.set()
    assert await a_test is False  # a result for a controller no longer configured
    return unifi


def _assert_b_untouched(unifi: UnifiIntegration) -> None:
    status = unifi.get_status()
    assert status["controller_url"] == URL_B
    assert status["connected"] is True
    assert status["last_error"] is None
    assert unifi._cache_clients == B_CLIENTS["data"]
    assert unifi.get_device_alias("AA:AA:AA:AA:AA:AA") is None


class TestStaleResultsAreDropped:
    def test_slow_successful_poll_for_a_cannot_overwrite_b(self):
        _assert_b_untouched(
            asyncio.run(_old_poll_finishes_after_b(_Response(A_CLIENTS)))
        )

    def test_slow_failed_poll_for_a_cannot_set_b_error(self):
        unifi = asyncio.run(_old_poll_finishes_after_b(_Response(error=A_FAILURE)))
        _assert_b_untouched(unifi)

    def test_slow_successful_test_for_a_cannot_touch_b(self):
        _assert_b_untouched(asyncio.run(_old_test_finishes_after_b(_Response())))

    def test_slow_failed_test_for_a_cannot_set_b_error(self):
        unifi = asyncio.run(_old_test_finishes_after_b(_Response(error=A_FAILURE)))
        _assert_b_untouched(unifi)

    def test_poll_for_a_changed_controller_never_reaches_b_until_polled(self):
        """A delayed A poll arriving after the switch leaves B disconnected and empty."""

        async def scenario():
            session = _Session(_Response(A_CLIENTS), _Response(B_CLIENTS))
            unifi = UnifiIntegration(session_factory=lambda: session)
            unifi.configure(URL_A, api_key="key-a", site_id="site-a")
            a_poll = asyncio.create_task(unifi.poll_clients())
            await session.a_entered.wait()
            unifi.configure(URL_B, api_key="key-b", site_id="site-b")
            session.gate.set()
            await a_poll
            return unifi

        unifi = asyncio.run(scenario())
        assert unifi.get_status()["connected"] is False
        assert unifi.get_status()["last_poll_time"] == 0
        assert unifi._cache_clients == []

    def test_transport_does_not_write_shared_status(self):
        async def scenario():
            session = _Session(_Response(), _Response(error=A_FAILURE))
            unifi = UnifiIntegration(session_factory=lambda: session)
            unifi.configure(URL_B, api_key="key-b", site_id="site-b")
            with pytest.raises(ConnectionError):
                await unifi._request("GET", "/v1/info")
            return unifi

        assert asyncio.run(scenario())._last_error is None


class TestConfigureIdentity:
    def test_connected_only_after_a_successful_poll(self):
        session = _Session(_Response(), _Response(B_CLIENTS))
        unifi = UnifiIntegration(session_factory=lambda: session)
        unifi.configure(URL_B, api_key="key-b", site_id="site-b")
        assert unifi.get_status()["connected"] is False

        asyncio.run(unifi.poll_clients())
        assert unifi.get_status()["connected"] is True

    def test_controller_change_resets_poll_state_and_caches(self):
        unifi = UnifiIntegration()
        unifi.configure(URL_A, api_key="key-a", site_id="site-a")
        unifi._cache_clients = A_CLIENTS["data"]
        unifi._cache_devices = [{"id": "ap"}]
        unifi._last_poll_time = 123.0

        unifi.configure(URL_B, api_key="key-b", site_id="site-b")

        status = unifi.get_status()
        assert status["connected"] is False
        assert status["last_poll_time"] == 0
        assert all(count == 0 for count in status["cache_counts"].values())
        assert unifi.get_device_alias("AA:AA:AA:AA:AA:AA") is None

    def test_same_configuration_keeps_state(self):
        unifi = UnifiIntegration()
        unifi.configure(URL_A, api_key="key-a", site_id="site-a")
        unifi._last_poll_time = 123.0
        unifi._last_error = "Poll error (clients): boom"

        unifi.configure(URL_A + "/", api_key="key-a")

        assert unifi._last_poll_time == 123.0
        assert unifi._last_error == "Poll error (clients): boom"
        assert unifi.get_status()["connected"] is False

    def test_site_id_kept_when_omitted(self):
        unifi = UnifiIntegration()
        unifi.configure(URL_A, api_key="key-a", site_id="site-a")
        unifi.configure(URL_A, api_key="key-a")
        assert unifi.get_status()["site_id"] == "site-a"


def _make_app(unifi: UnifiIntegration) -> web.Application:
    app = web.Application()
    register_devices_v2_routes(app, MagicMock(), unifi)
    return app


class TestConfigureEndpoint(AioHTTPTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env = patch.dict(
            os.environ,
            {"UNIFI_CONFIG_FILE": os.path.join(self._tmp.name, "unifi.json")},
        )
        self._env.start()
        self.unifi = UnifiIntegration()
        self.unifi.configure(URL_A, api_key="stored-key", site_id="site-a")
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self._env.stop()
        self._tmp.cleanup()

    async def get_application(self):
        return _make_app(self.unifi)

    async def _configure(self, body):
        return await self.client.post("/api/integrations/unifi/configure", json=body)

    async def test_new_url_without_key_is_rejected(self):
        resp = await self._configure({"controller_url": "https://attacker.example"})
        self.assertEqual(resp.status, 400)
        self.assertIn("api_key is required", (await resp.json())["error"])
        self.assertEqual(self.unifi._base_url, URL_A)
        self.assertEqual(self.unifi._api_key, "stored-key")

    async def test_http_variant_of_the_same_url_keeps_the_key(self):
        resp = await self._configure({"controller_url": "http://10.0.0.1/"})
        self.assertEqual(resp.status, 200)
        self.assertEqual(self.unifi._api_key, "stored-key")

    async def test_new_url_with_its_own_key_is_accepted(self):
        resp = await self._configure({"controller_url": URL_B, "api_key": "key-b"})
        self.assertEqual(resp.status, 200)
        self.assertEqual(self.unifi._base_url, URL_B)
        self.assertEqual(self.unifi._api_key, "key-b")

    async def test_omitted_or_empty_site_id_keeps_the_site(self):
        for body in (
            {"controller_url": URL_A},
            {"controller_url": URL_A, "site_id": ""},
        ):
            resp = await self._configure(body)
            self.assertEqual(resp.status, 200)
            self.assertEqual(self.unifi.get_status()["site_id"], "site-a")

    async def test_non_string_fields_are_rejected(self):
        for body in (
            {"controller_url": ["https://10.0.0.1"]},
            {"controller_url": URL_A, "api_key": 42},
            ["not", "an", "object"],
        ):
            resp = await self._configure(body)
            self.assertEqual(resp.status, 400)

    async def test_status_reports_site_and_connection(self):
        resp = await self.client.get("/api/integrations/unifi/status")
        data = await resp.json()
        self.assertEqual(data["site_id"], "site-a")
        self.assertIs(data["connected"], False)


if __name__ == "__main__":
    unittest.main()
