"""NET-224: the notification API never returns a secret, validates what it saves, saves the
Settings tab for real, and tests every channel with each one's reason."""

import json
import os
import sys
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.notifications_hub import register_notification_hub_routes  # noqa: E402
from services import notification_config as nc  # noqa: E402
from services.notification_hub import NotificationHub  # noqa: E402

TOKEN = "s3cr3t-T0KEN-value"


class NotificationApiCase(AioHTTPTestCase):
    async def get_application(self):
        import tempfile

        self.dir = tempfile.mkdtemp()
        self.env_file = os.path.join(self.dir, ".env")
        open(self.env_file, "w").close()
        self.hub = NotificationHub(
            config_path=os.path.join(self.dir, "n.json"), env_file=self.env_file
        )
        app = web.Application()
        register_notification_hub_routes(app, self.hub)
        return app

    async def test_channels_list_and_create_show_no_secret(self):
        resp = await self.client.post(
            "/api/notifications/channels",
            json={
                "type": "discord",
                "name": "D",
                "config": {
                    "webhook_url": f"https://discord.example.net/api/webhooks/1/{TOKEN}"
                },
            },
        )
        self.assertEqual(resp.status, 201)
        created = await resp.text()
        listed = await (await self.client.get("/api/notifications/channels")).text()

        self.assertNotIn(TOKEN, created)
        self.assertNotIn(TOKEN, listed)
        self.assertEqual(
            json.loads(listed)["channels"][0]["config"]["webhook_url_hint"],
            "https://discord.example.net/…",
        )

    async def test_a_bad_url_is_refused_with_the_reason(self):
        resp = await self.client.post(
            "/api/notifications/channels",
            json={
                "type": "webhook",
                "name": "W",
                "config": {"url": "file:///etc/passwd"},
            },
        )
        self.assertEqual(resp.status, 400)
        self.assertIn("http", (await resp.json())["error"])
        self.assertEqual(self.hub.get_channels(), [])

    async def test_a_body_id_cannot_overwrite_another_channel(self):
        first = self.hub.configure(
            "webhook", {"url": "https://hooks.example.net/a", "name": "A"}
        )
        resp = await self.client.post(
            "/api/notifications/channels",
            json={
                "type": "webhook",
                "name": "B",
                "config": {"id": first["id"], "url": "https://hooks.example.net/b"},
            },
        )
        self.assertEqual(resp.status, 201)
        self.assertEqual(sorted(c["name"] for c in self.hub.get_channels()), ["A", "B"])

    async def test_a_malformed_rule_is_refused(self):
        ch = self.hub.configure("webhook", {"url": "https://hooks.example.net/a"})
        for body in (
            {"event_type": "alert", "channels": [ch["id"]], "min_severity": "2"},
            {"event_type": "alert", "channels": [{}], "min_severity": 2},
            {"event_type": "alert", "channels": ["gone"], "min_severity": 2},
        ):
            resp = await self.client.post("/api/notifications/rules", json=body)
            self.assertEqual(resp.status, 400, body)
        self.assertEqual(self.hub.get_rules(), [])

    async def test_the_settings_tab_saves_and_reads_back_without_the_url(self):
        url = f"https://hooks.example.net/{TOKEN}"
        resp = await self.client.put(
            "/api/notifications/config",
            json={
                "min_severity": 1,
                "email": {"enabled": False},
                "webhook": {"enabled": True, "url": url},
            },
        )
        self.assertEqual(resp.status, 200)

        got = await (await self.client.get("/api/notifications/config")).json()
        self.assertNotIn(TOKEN, json.dumps(got))
        self.assertEqual(got["min_severity"], 1)
        self.assertEqual(
            got["webhook"],
            {
                "enabled": True,
                "has_url": True,
                "url_hint": "https://hooks.example.net/…",
            },
        )
        self.assertEqual(self.hub.channels_for("alert", 1), [nc.QUICK_WEBHOOK])

    async def test_the_settings_tab_gets_the_reason_it_cannot_save(self):
        resp = await self.client.put(
            "/api/notifications/config",
            json={
                "min_severity": 2,
                "email": {"enabled": True, "recipients": ["a@example.net"]},
                "webhook": {},
            },
        )
        self.assertEqual(resp.status, 400)
        self.assertIn("SMTP server", (await resp.json())["error"])

    async def test_a_failed_write_is_a_500_with_the_reason(self):
        with patch(
            "services.notification_hub.write_file_atomic",
            side_effect=OSError(28, "No space left on device"),
        ):
            resp = await self.client.put(
                "/api/notifications/config",
                json={
                    "min_severity": 2,
                    "email": {},
                    "webhook": {"enabled": True, "url": "https://hooks.example.net/x"},
                },
            )
        self.assertEqual(resp.status, 500)
        self.assertIn("No space left on device", (await resp.json())["error"])

    async def test_test_all_with_no_channel_is_409(self):
        resp = await self.client.post("/api/notifications/test")
        self.assertEqual(resp.status, 409)

    async def test_test_all_names_each_failure_and_skips_disabled_channels(self):
        good = self.hub.configure(
            "webhook", {"url": "https://hooks.example.net/a", "name": "Good"}
        )
        bad = self.hub.configure(
            "webhook", {"url": "https://hooks.example.net/b", "name": "Bad"}
        )
        off = self.hub.configure(
            "webhook", {"url": "https://hooks.example.net/c", "name": "Off"}
        )
        self.hub._commit(
            {**self.hub._channels, off["id"]: {**off, "enabled": False}},
            self.hub._rules,
        )
        tested = []

        async def fake_post(url, **_kwargs):
            tested.append(url)
            return "HTTP 500" if url.endswith("/b") else None

        with patch("services.notification_hub._post", side_effect=fake_post):
            resp = await self.client.post("/api/notifications/test")

        self.assertEqual(resp.status, 502)
        body = await resp.json()
        self.assertEqual(body["error"], "The test didn't go through: Bad (HTTP 500).")
        self.assertEqual(
            {r["channel_id"]: r["ok"] for r in body["results"]},
            {good["id"]: True, bad["id"]: False},
        )
        self.assertNotIn("https://hooks.example.net/c", tested)

        with patch("services.notification_hub._post", return_value=None):
            self.hub.delete_channel(bad["id"])
            resp = await self.client.post("/api/notifications/test")
        self.assertEqual(resp.status, 200)

    async def test_one_channel_test_reports_its_reason(self):
        ch = self.hub.configure("webhook", {"url": "https://hooks.example.net/a"})
        with patch("services.notification_hub._post", return_value="HTTP 404"):
            body = await (
                await self.client.post(f"/api/notifications/channels/{ch['id']}/test")
            ).json()
        self.assertEqual(
            body, {"success": False, "channel_id": ch["id"], "error": "HTTP 404"}
        )
        listed = await (await self.client.get("/api/notifications/channels")).json()
        self.assertEqual(listed["channels"][0]["last_delivery"]["error"], "HTTP 404")
