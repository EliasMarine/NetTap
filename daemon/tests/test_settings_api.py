"""
Tests for daemon/api/settings.py

All tests use a temporary env file. Tests cover GET/POST endpoints,
env file parsing, saving, unknown key handling, validation, and
edge cases.
"""

import json
import os
import tempfile
import unittest

import sys

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.settings import register_settings_routes, _load_env_file, _save_env_file


class TestGetApiKeys(AioHTTPTestCase):
    """Tests for GET /api/settings/api-keys."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".env", delete=False, mode="w")
        self.tmp.write('MAXMIND_LICENSE_KEY="test-key-123"\n')
        self.tmp.write("SMTP_HOST=smtp.example.com\n")
        self.tmp.write("# Comment line\n")
        self.tmp.write("\n")
        self.tmp.close()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    async def get_application(self):
        app = web.Application()
        register_settings_routes(app, env_file=self.tmp.name)
        return app

    @unittest_run_loop
    async def test_get_returns_configured_flags(self):
        """GET /api/settings/api-keys returns boolean flags for each key."""
        resp = await self.client.request("GET", "/api/settings/api-keys")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("keys", data)
        self.assertTrue(data["keys"]["MAXMIND_LICENSE_KEY"])
        self.assertTrue(data["keys"]["SMTP_HOST"])
        self.assertFalse(data["keys"]["WEBHOOK_URL"])

    @unittest_run_loop
    async def test_get_returns_all_known_fields(self):
        """GET /api/settings/api-keys returns all known key fields."""
        resp = await self.client.request("GET", "/api/settings/api-keys")
        data = await resp.json()
        keys = data["keys"]
        expected_fields = [
            "MAXMIND_LICENSE_KEY", "SMTP_HOST", "SMTP_PORT",
            "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_SENDER_EMAIL",
            "WEBHOOK_URL", "SURICATA_ET_PRO_KEY",
        ]
        for field in expected_fields:
            self.assertIn(field, keys)


class TestGetApiKeysEmptyFile(AioHTTPTestCase):
    """Tests for GET /api/settings/api-keys when env file does not exist."""

    def setUp(self):
        self.tmp_path = tempfile.mktemp(suffix=".env")
        # Don't create the file -- it should not exist
        super().setUp()

    def tearDown(self):
        super().tearDown()
        if os.path.exists(self.tmp_path):
            os.unlink(self.tmp_path)

    async def get_application(self):
        app = web.Application()
        register_settings_routes(app, env_file=self.tmp_path)
        return app

    @unittest_run_loop
    async def test_get_returns_all_false_when_no_env_file(self):
        """GET returns all false flags when env file does not exist."""
        resp = await self.client.request("GET", "/api/settings/api-keys")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        for value in data["keys"].values():
            self.assertFalse(value)


class TestSaveApiKeys(AioHTTPTestCase):
    """Tests for POST /api/settings/api-keys."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".env", delete=False, mode="w")
        self.tmp.write('MAXMIND_LICENSE_KEY="old-key"\n')
        self.tmp.close()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    async def get_application(self):
        app = web.Application()
        register_settings_routes(app, env_file=self.tmp.name)
        return app

    @unittest_run_loop
    async def test_save_new_key(self):
        """POST /api/settings/api-keys saves a new key."""
        resp = await self.client.request(
            "POST", "/api/settings/api-keys",
            json={"WEBHOOK_URL": "https://hooks.example.com/nettap"},
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["result"], "saved")
        self.assertTrue(data["keys"]["WEBHOOK_URL"])

    @unittest_run_loop
    async def test_save_updates_existing_key(self):
        """POST /api/settings/api-keys updates an existing key in-place."""
        resp = await self.client.request(
            "POST", "/api/settings/api-keys",
            json={"MAXMIND_LICENSE_KEY": "new-key-456"},
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["keys"]["MAXMIND_LICENSE_KEY"])
        # Verify the file was actually updated
        env_vars = _load_env_file(self.tmp.name)
        self.assertEqual(env_vars["MAXMIND_LICENSE_KEY"], "new-key-456")

    @unittest_run_loop
    async def test_save_multiple_keys_at_once(self):
        """POST /api/settings/api-keys saves multiple keys in one request."""
        resp = await self.client.request(
            "POST", "/api/settings/api-keys",
            json={
                "SMTP_HOST": "smtp.gmail.com",
                "SMTP_PORT": "587",
                "SMTP_USERNAME": "user@gmail.com",
            },
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["saved_count"], 3)
        self.assertTrue(data["keys"]["SMTP_HOST"])
        self.assertTrue(data["keys"]["SMTP_PORT"])
        self.assertTrue(data["keys"]["SMTP_USERNAME"])

    @unittest_run_loop
    async def test_save_unknown_keys_are_ignored_with_warning(self):
        """POST /api/settings/api-keys ignores unknown keys and warns."""
        resp = await self.client.request(
            "POST", "/api/settings/api-keys",
            json={
                "MAXMIND_LICENSE_KEY": "valid",
                "RANDOM_KEY": "should-be-ignored",
            },
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["saved_count"], 1)
        self.assertIn("warnings", data)
        self.assertTrue(any("RANDOM_KEY" in w for w in data["warnings"]))

    @unittest_run_loop
    async def test_save_empty_body_returns_400(self):
        """POST /api/settings/api-keys with no valid keys returns 400."""
        resp = await self.client.request(
            "POST", "/api/settings/api-keys",
            json={"UNKNOWN_FIELD": "value"},
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("error", data)

    @unittest_run_loop
    async def test_save_invalid_json_returns_400(self):
        """POST /api/settings/api-keys with invalid JSON returns 400."""
        resp = await self.client.request(
            "POST", "/api/settings/api-keys",
            data="not json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_save_non_object_body_returns_400(self):
        """POST /api/settings/api-keys with array body returns 400."""
        resp = await self.client.request(
            "POST", "/api/settings/api-keys",
            json=["MAXMIND_LICENSE_KEY"],
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("error", data)


class TestEnvFileHelpers(unittest.TestCase):
    """Tests for the _load_env_file and _save_env_file helper functions."""

    def test_load_env_file_strips_quotes(self):
        """_load_env_file strips surrounding quotes from values."""
        tmp = tempfile.NamedTemporaryFile(suffix=".env", delete=False, mode="w")
        tmp.write('KEY1="double-quoted"\n')
        tmp.write("KEY2='single-quoted'\n")
        tmp.write("KEY3=unquoted\n")
        tmp.close()
        try:
            env = _load_env_file(tmp.name)
            self.assertEqual(env["KEY1"], "double-quoted")
            self.assertEqual(env["KEY2"], "single-quoted")
            self.assertEqual(env["KEY3"], "unquoted")
        finally:
            os.unlink(tmp.name)

    def test_save_env_file_creates_file_if_not_exists(self):
        """_save_env_file creates the env file and parent dirs."""
        tmp_dir = tempfile.mkdtemp()
        env_path = os.path.join(tmp_dir, "subdir", "test.env")
        try:
            _save_env_file(env_path, {"MY_KEY": "my_value"})
            self.assertTrue(os.path.exists(env_path))
            env = _load_env_file(env_path)
            self.assertEqual(env["MY_KEY"], "my_value")
        finally:
            import shutil
            shutil.rmtree(tmp_dir)


class TestRouteRegistration(AioHTTPTestCase):
    """Tests for route registration."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".env", delete=False, mode="w")
        self.tmp.close()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    async def get_application(self):
        app = web.Application()
        register_settings_routes(app, env_file=self.tmp.name)
        return app

    @unittest_run_loop
    async def test_env_file_stored_on_app(self):
        """The env_file path should be stored on the app dict."""
        self.assertEqual(self.app["env_file"], self.tmp.name)


if __name__ == "__main__":
    unittest.main()
