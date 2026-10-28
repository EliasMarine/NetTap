"""
Tests for daemon/services/notification_hub.py

Covers channel CRUD, test delivery, routing rules, and event processing.
All tests use mocks and temp files — no external dependencies required.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.notification_hub import NotificationHub, CHANNEL_TYPES, EVENT_TYPES


def run_async(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestNotificationHubChannelCRUD(unittest.TestCase):
    """Tests for channel create/read/delete."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        self.tmp.close()
        # Remove so it starts fresh
        os.unlink(self.tmp.name)
        self.hub = NotificationHub(config_path=self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_configure_creates_channel(self):
        """configure() creates and returns a channel."""
        ch = self.hub.configure("discord", {"webhook_url": "https://discord.com/api/webhooks/test", "name": "My Discord"})
        self.assertEqual(ch["type"], "discord")
        self.assertEqual(ch["name"], "My Discord")
        self.assertIn("id", ch)

    def test_configure_invalid_type_raises(self):
        """configure() with invalid type raises ValueError."""
        with self.assertRaises(ValueError):
            self.hub.configure("carrier_pigeon", {"name": "Pigeon"})

    def test_get_channels_returns_all(self):
        """get_channels() returns all configured channels."""
        self.hub.configure("discord", {"webhook_url": "url1", "name": "D1"})
        self.hub.configure("slack", {"webhook_url": "url2", "name": "S1"})
        channels = self.hub.get_channels()
        self.assertEqual(len(channels), 2)

    def test_get_channel_by_id(self):
        """get_channel() returns specific channel."""
        ch = self.hub.configure("email", {"smtp_host": "smtp.test.com", "name": "Email"})
        result = self.hub.get_channel(ch["id"])
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "email")

    def test_get_channel_nonexistent_returns_none(self):
        """get_channel() returns None for missing ID."""
        self.assertIsNone(self.hub.get_channel("nonexistent"))

    def test_delete_channel(self):
        """delete_channel() removes channel and returns True."""
        ch = self.hub.configure("webhook", {"url": "https://example.com", "name": "WH"})
        self.assertTrue(self.hub.delete_channel(ch["id"]))
        self.assertEqual(len(self.hub.get_channels()), 0)

    def test_delete_channel_nonexistent_returns_false(self):
        """delete_channel() returns False for missing ID."""
        self.assertFalse(self.hub.delete_channel("nonexistent"))

    def test_config_persists_to_file(self):
        """Channels are saved to and loaded from the config file."""
        self.hub.configure("telegram", {"bot_token": "tok", "chat_id": "123", "name": "TG"})

        # Create a new hub from the same file
        hub2 = NotificationHub(config_path=self.tmp.name)
        channels = hub2.get_channels()
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0]["type"], "telegram")

    def test_all_channel_types_accepted(self):
        """All 6 channel types can be configured."""
        for ct in CHANNEL_TYPES:
            ch = self.hub.configure(ct, {"name": ct, "id": ct})
            self.assertEqual(ch["type"], ct)
        self.assertEqual(len(self.hub.get_channels()), len(CHANNEL_TYPES))


class TestNotificationHubDelivery(unittest.TestCase):
    """Tests for notification delivery (mocked HTTP)."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.hub = NotificationHub(config_path=self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_send_unknown_channel_returns_false(self):
        """send() returns False for unknown channel ID."""
        result = run_async(self.hub.send("nonexistent", "Title", "Msg"))
        self.assertFalse(result)

    def test_test_unknown_channel_returns_false(self):
        """test() returns False for unknown channel ID."""
        result = run_async(self.hub.test("nonexistent"))
        self.assertFalse(result)

    @patch("services.notification_hub.aiohttp.ClientSession")
    def test_send_discord_success(self, mock_session_cls):
        """send() to Discord returns True on 204."""
        ch = self.hub.configure("discord", {"webhook_url": "https://discord.com/api/webhooks/test"})

        mock_resp = MagicMock()
        mock_resp.status = 204

        # Build a proper async context manager chain:
        # async with ClientSession() as session:
        #     async with session.post(...) as resp:
        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post_cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = mock_session_cm

        result = run_async(self.hub.send(ch["id"], "Test", "Hello", 2))
        self.assertTrue(result)

    @patch("services.notification_hub.aiohttp.ClientSession")
    def test_send_slack_success(self, mock_session_cls):
        """send() to Slack returns True on 200."""
        ch = self.hub.configure("slack", {"webhook_url": "https://hooks.slack.com/test"})

        mock_resp = MagicMock()
        mock_resp.status = 200

        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post_cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = mock_session_cm

        result = run_async(self.hub.send(ch["id"], "Test", "Hello", 3))
        self.assertTrue(result)

    @patch("services.notification_hub.aiohttp.ClientSession")
    def test_send_webhook_success(self, mock_session_cls):
        """send() to webhook returns True on 200."""
        ch = self.hub.configure("webhook", {"url": "https://example.com/hook"})

        mock_resp = MagicMock()
        mock_resp.status = 200

        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post_cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = mock_session_cm

        result = run_async(self.hub.send(ch["id"], "Test", "Hello", 4))
        self.assertTrue(result)

    def test_delivery_log_records_entries(self):
        """Delivery log records send attempts."""
        ch = self.hub.configure("webhook", {"url": ""})  # will fail
        run_async(self.hub.send(ch["id"], "Test", "Hello", 3))
        log = self.hub.get_delivery_log()
        self.assertEqual(len(log), 1)
        self.assertFalse(log[0]["success"])

    def test_delivery_log_caps_at_100(self):
        """Delivery log keeps only the last 100 entries."""
        ch = self.hub.configure("webhook", {"url": ""})
        for _ in range(110):
            run_async(self.hub.send(ch["id"], "Test", "Hello"))
        log = self.hub.get_delivery_log()
        self.assertLessEqual(len(log), 100)


class TestNotificationHubRoutingRules(unittest.TestCase):
    """Tests for routing rules engine."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.hub = NotificationHub(config_path=self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_add_rule(self):
        """add_rule() creates and returns a rule."""
        rule = self.hub.add_rule("alert", ["ch1", "ch2"], 2)
        self.assertEqual(rule["event_type"], "alert")
        self.assertEqual(rule["channels"], ["ch1", "ch2"])
        self.assertEqual(rule["min_severity"], 2)

    def test_add_rule_invalid_event_type_raises(self):
        """add_rule() with invalid event type raises ValueError."""
        with self.assertRaises(ValueError):
            self.hub.add_rule("invalid_event", ["ch1"], 3)

    def test_get_rules(self):
        """get_rules() returns all rules."""
        self.hub.add_rule("alert", ["ch1"], 3)
        self.hub.add_rule("new_device", ["ch2"], 4)
        rules = self.hub.get_rules()
        self.assertEqual(len(rules), 2)

    def test_delete_rule(self):
        """delete_rule() removes rule and returns True."""
        rule = self.hub.add_rule("alert", ["ch1"], 3)
        self.assertTrue(self.hub.delete_rule(rule["id"]))
        self.assertEqual(len(self.hub.get_rules()), 0)

    def test_delete_rule_nonexistent(self):
        """delete_rule() returns False for missing ID."""
        self.assertFalse(self.hub.delete_rule("nonexistent"))

    def test_rules_persist_to_file(self):
        """Rules are saved to and loaded from config file."""
        self.hub.add_rule("anomaly", ["ch1"], 2)

        hub2 = NotificationHub(config_path=self.tmp.name)
        rules = hub2.get_rules()
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["event_type"], "anomaly")


class TestNotificationHubEventProcessing(unittest.TestCase):
    """Tests for process_event routing logic."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.hub = NotificationHub(config_path=self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_process_event_no_matching_rules(self):
        """process_event with no rules returns 0 matched."""
        result = run_async(
            self.hub.process_event("alert", "Test Alert", "Body", 2)
        )
        self.assertEqual(result["matched_rules"], 0)
        self.assertEqual(result["channels_notified"], {})

    def test_process_event_severity_filtering(self):
        """process_event respects severity filtering."""
        ch = self.hub.configure("webhook", {"url": ""})
        self.hub.add_rule("alert", [ch["id"]], min_severity=2)

        # Severity 4 (low) should NOT match rule with min_severity=2
        result = run_async(
            self.hub.process_event("alert", "Low Alert", "Body", 4)
        )
        self.assertEqual(result["matched_rules"], 0)

        # Severity 1 (critical) should match
        result = run_async(
            self.hub.process_event("alert", "Critical Alert", "Body", 1)
        )
        self.assertEqual(result["matched_rules"], 1)

    def test_process_event_sends_to_channels(self):
        """process_event sends to matched channels."""
        ch = self.hub.configure("webhook", {"url": ""})
        self.hub.add_rule("new_device", [ch["id"]], min_severity=4)

        result = run_async(
            self.hub.process_event("new_device", "New Device", "A device joined", 4)
        )
        self.assertEqual(result["matched_rules"], 1)
        self.assertIn(ch["id"], result["channels_notified"])

    def test_process_event_no_duplicate_sends(self):
        """process_event avoids duplicate sends to the same channel."""
        ch = self.hub.configure("webhook", {"url": ""})
        # Two rules pointing to the same channel
        self.hub.add_rule("alert", [ch["id"]], min_severity=4)
        self.hub.add_rule("alert", [ch["id"]], min_severity=4)

        result = run_async(
            self.hub.process_event("alert", "Alert", "Body", 3)
        )
        self.assertEqual(result["matched_rules"], 2)
        # Channel should only appear once in results
        self.assertEqual(len(result["channels_notified"]), 1)


class TestNotificationHubConfigLoading(unittest.TestCase):
    """Tests for config file edge cases."""

    def test_missing_config_file(self):
        """Hub works with missing config file."""
        hub = NotificationHub(config_path="/tmp/nettap-test-nonexistent-notif-config.json")
        self.assertEqual(hub.get_channels(), [])
        self.assertEqual(hub.get_rules(), [])

    def test_corrupt_config_file(self):
        """Hub handles corrupt JSON gracefully."""
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write("not valid json{{{")
        tmp.close()
        try:
            hub = NotificationHub(config_path=tmp.name)
            self.assertEqual(hub.get_channels(), [])
            self.assertEqual(hub.get_rules(), [])
        finally:
            os.unlink(tmp.name)

    def test_empty_config_file(self):
        """Hub handles empty JSON file."""
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write("{}")
        tmp.close()
        try:
            hub = NotificationHub(config_path=tmp.name)
            self.assertEqual(hub.get_channels(), [])
            self.assertEqual(hub.get_rules(), [])
        finally:
            os.unlink(tmp.name)


if __name__ == "__main__":
    unittest.main()
