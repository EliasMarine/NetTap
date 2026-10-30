"""
Tests for the daemon API shared-token auth (daemon/api/daemon_auth.py).

Covers: the token check (missing, wrong, right), the /api/health exemption,
no loopback exemption, fail-closed behaviour without a token, rate-limited
rejection logging that never contains the token, first-start token file
creation (0644 in a 0755 dir) and reuse, and create_app() wiring with the
CORS middleware gone.
"""

import os
import stat
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.daemon_auth import TOKEN_HEADER, load_or_create_token, make_auth_middleware

TOKEN = "test-daemon-token-0123456789abcdef"


async def _ok(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


def _make_app(token: str | None) -> web.Application:
    app = web.Application(middlewares=[make_auth_middleware(token)])
    app.router.add_get("/api/health", _ok)
    app.router.add_post("/api/health", _ok)
    app.router.add_get("/api/system/health", _ok)
    app.router.add_post("/api/storage/prune", _ok)
    return app


class TestTokenRequired(AioHTTPTestCase):
    async def get_application(self):
        return _make_app(TOKEN)

    async def test_missing_header_is_401(self):
        resp = await self.client.get("/api/system/health")
        self.assertEqual(resp.status, 401)
        self.assertEqual(await resp.json(), {"error": "Unauthorized"})

    async def test_wrong_token_is_401(self):
        resp = await self.client.post(
            "/api/storage/prune", headers={TOKEN_HEADER: TOKEN + "x"}
        )
        self.assertEqual(resp.status, 401)

    async def test_non_ascii_token_is_401_not_500(self):
        resp = await self.client.get(
            "/api/system/health", headers={TOKEN_HEADER: "tökén"}
        )
        self.assertEqual(resp.status, 401)

    async def test_right_token_is_200(self):
        resp = await self.client.get(
            "/api/system/health", headers={TOKEN_HEADER: TOKEN}
        )
        self.assertEqual(resp.status, 200)

    async def test_health_get_is_open(self):
        resp = await self.client.get("/api/health")
        self.assertEqual(resp.status, 200)

    async def test_health_exemption_is_get_only(self):
        resp = await self.client.post("/api/health")
        self.assertEqual(resp.status, 401)

    async def test_loopback_without_token_is_401(self):
        """Host-networked capture containers share loopback, so it is not trusted."""
        resp = await self.client.get("/api/system/health")
        self.assertEqual(self.client.host, "127.0.0.1")
        self.assertEqual(resp.status, 401)

    async def test_rejections_log_once_per_ip_without_the_token(self):
        with self.assertLogs("nettap.api.auth", "WARNING") as logs:
            await self.client.get("/api/system/health", headers={TOKEN_HEADER: "bad"})
            await self.client.get("/api/system/health")
        self.assertEqual(len(logs.records), 1)
        self.assertIn("127.0.0.1", logs.output[0])
        self.assertIn("/api/system/health", logs.output[0])
        self.assertNotIn("bad", logs.output[0])
        self.assertNotIn(TOKEN, logs.output[0])


class TestNoTokenFailsClosed(AioHTTPTestCase):
    async def get_application(self):
        return _make_app(None)

    async def test_everything_but_health_is_401(self):
        self.assertEqual((await self.client.get("/api/health")).status, 200)
        for headers in ({}, {TOKEN_HEADER: ""}, {TOKEN_HEADER: "None"}):
            resp = await self.client.get("/api/system/health", headers=headers)
            self.assertEqual(resp.status, 401)


class TestTokenFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self._tmp.name, "nettap-auth")
        self.path = os.path.join(self.dir, "daemon-token")

    def tearDown(self):
        self._tmp.cleanup()

    def test_created_once_world_readable_then_reused(self):
        first = load_or_create_token(self.path)

        self.assertGreaterEqual(len(first), 40)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(os.stat(self.dir).st_mode), 0o755)
        self.assertFalse(os.path.exists(self.path + ".tmp"))

        self.assertEqual(load_or_create_token(self.path), first)
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), first)

    def test_existing_token_is_used_and_trimmed(self):
        os.makedirs(self.dir)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("existing-token\n")
        self.assertEqual(load_or_create_token(self.path), "existing-token")

    def test_empty_file_is_replaced(self):
        os.makedirs(self.dir)
        open(self.path, "w").close()
        token = load_or_create_token(self.path)
        self.assertTrue(token)
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), token)

    def test_unwritable_location_raises(self):
        blocker = os.path.join(self._tmp.name, "file")
        open(blocker, "w").close()
        with self.assertRaises(OSError):
            load_or_create_token(os.path.join(blocker, "daemon-token"))


def _make_full_app(tmp_dir: str) -> web.Application:
    """Build the real create_app() with OpenSearch and host detection mocked."""
    from api.server import create_app
    from storage.manager import RetentionConfig, StorageManager

    with patch.object(StorageManager, "_create_client", return_value=MagicMock()):
        storage = StorageManager(RetentionConfig(), "http://localhost:9200")
    with (
        patch.dict(
            os.environ,
            {
                "DAEMON_TOKEN_FILE": os.path.join(tmp_dir, "auth", "daemon-token"),
                "EXCLUDED_IPS_FILE": os.path.join(tmp_dir, "excluded_ips.json"),
            },
        ),
        patch("api.server.detect_appliance_ip", return_value=None),
    ):
        return create_app(storage, MagicMock(), "http://localhost:9200")


class TestCreateAppWiring(AioHTTPTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self._tmp.cleanup()

    async def get_application(self):
        return _make_full_app(self._tmp.name)

    def _token(self) -> str:
        with open(os.path.join(self._tmp.name, "auth", "daemon-token")) as f:
            return f.read()

    async def test_real_routes_require_the_token(self):
        resp = await self.client.get("/api/storage/retention")
        self.assertEqual(resp.status, 401)

        resp = await self.client.get(
            "/api/storage/retention", headers={TOKEN_HEADER: self._token()}
        )
        self.assertNotEqual(resp.status, 401)

    async def test_health_stays_open_for_the_compose_healthcheck(self):
        resp = await self.client.get("/api/health")
        self.assertEqual(resp.status, 200)

    async def test_no_cors_headers_or_preflight(self):
        resp = await self.client.options(
            "/api/storage/retention", headers={"Origin": "http://evil.example"}
        )
        self.assertEqual(resp.status, 401)
        self.assertNotIn("Access-Control-Allow-Origin", resp.headers)

        resp = await self.client.get("/api/health")
        self.assertNotIn("Access-Control-Allow-Origin", resp.headers)


class TestCreateAppWithoutToken(AioHTTPTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        blocker = os.path.join(self._tmp.name, "auth")
        open(blocker, "w").close()  # a file where the token dir should be
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self._tmp.cleanup()

    async def get_application(self):
        with self.assertLogs("nettap.api", "ERROR"):
            return _make_full_app(self._tmp.name)

    async def test_unprovisioned_token_locks_the_api(self):
        self.assertEqual((await self.client.get("/api/health")).status, 200)
        resp = await self.client.get("/api/storage/retention")
        self.assertEqual(resp.status, 401)


if __name__ == "__main__":
    unittest.main()
