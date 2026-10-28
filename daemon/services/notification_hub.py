"""
NetTap NotificationHub — Multi-channel notification system.

Supports 6 channel types: email (SMTP), Discord, Slack, Telegram,
Pushover, and generic webhook. Includes a routing rules engine
that maps event types to channels with severity filtering.

Channel and rule configs are persisted to a JSON file.
"""

import json
import logging
import os
import smtplib
import ssl
import uuid
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import aiohttp

logger = logging.getLogger("nettap.services.notification_hub")

# Supported channel types
CHANNEL_TYPES = {"email", "discord", "slack", "telegram", "pushover", "webhook"}

# Supported event types for routing rules
EVENT_TYPES = {
    "new_device",
    "alert",
    "anomaly",
    "storage_warning",
    "smart_warning",
    "capture_error",
    "system_error",
}

# Severity levels (1 = critical, 4 = low)
SEVERITY_LEVELS = {1: "critical", 2: "high", 3: "medium", 4: "low"}

# Default config path
_DEFAULT_CONFIG_PATH = os.environ.get(
    "NOTIFICATION_CONFIG", "./data/notifications.json"
)


class NotificationHub:
    """Multi-channel notification system with routing rules."""

    def __init__(self, config_path: str | None = None) -> None:
        self._config_path = Path(config_path or _DEFAULT_CONFIG_PATH)
        self._channels: dict[str, dict[str, Any]] = {}
        self._rules: dict[str, dict[str, Any]] = {}
        self._delivery_log: list[dict[str, Any]] = []
        self._load_config()

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        """Load channels and rules from the JSON config file."""
        if self._config_path.exists():
            try:
                data = json.loads(self._config_path.read_text())
                self._channels = data.get("channels", {})
                self._rules = data.get("rules", {})
                logger.info(
                    "Loaded %d channels, %d rules from %s",
                    len(self._channels),
                    len(self._rules),
                    self._config_path,
                )
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load notification config: %s", exc)
                self._channels = {}
                self._rules = {}
        else:
            logger.info("No notification config at %s, starting fresh", self._config_path)

    def _save_config(self) -> None:
        """Persist channels and rules to the JSON config file."""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"channels": self._channels, "rules": self._rules}
        self._config_path.write_text(json.dumps(data, indent=2))
        logger.debug("Saved notification config to %s", self._config_path)

    # ------------------------------------------------------------------
    # Channel CRUD
    # ------------------------------------------------------------------

    def configure(self, channel_type: str, config: dict[str, Any]) -> dict[str, Any]:
        """Create or update a notification channel.

        Args:
            channel_type: One of email, discord, slack, telegram, pushover, webhook.
            config: Channel-specific configuration dict.

        Returns:
            The created channel dict including its generated ID.
        """
        if channel_type not in CHANNEL_TYPES:
            raise ValueError(f"Unsupported channel type: {channel_type}. Must be one of {CHANNEL_TYPES}")

        channel_id = config.get("id") or str(uuid.uuid4())[:8]
        channel = {
            "id": channel_id,
            "type": channel_type,
            "name": config.get("name", f"{channel_type}-{channel_id}"),
            "config": config,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._channels[channel_id] = channel
        self._save_config()
        logger.info("Configured %s channel: %s", channel_type, channel_id)
        return channel

    def get_channels(self) -> list[dict[str, Any]]:
        """List all configured notification channels."""
        return list(self._channels.values())

    def get_channel(self, channel_id: str) -> dict[str, Any] | None:
        """Get a single channel by ID."""
        return self._channels.get(channel_id)

    def delete_channel(self, channel_id: str) -> bool:
        """Remove a notification channel.

        Returns True if the channel existed and was removed.
        """
        if channel_id in self._channels:
            del self._channels[channel_id]
            self._save_config()
            logger.info("Deleted channel: %s", channel_id)
            return True
        return False

    # ------------------------------------------------------------------
    # Channel delivery
    # ------------------------------------------------------------------

    async def test(self, channel_id: str) -> bool:
        """Send a test notification to the specified channel.

        Returns True on success.
        """
        channel = self._channels.get(channel_id)
        if not channel:
            logger.warning("Test failed: channel %s not found", channel_id)
            return False

        return await self.send(
            channel_id,
            title="NetTap Test Notification",
            message="This is a test notification from your NetTap appliance. If you see this, the channel is configured correctly.",
            severity=4,
        )

    async def send(
        self,
        channel_id: str,
        title: str,
        message: str,
        severity: int = 3,
    ) -> bool:
        """Send a notification to the specified channel.

        Args:
            channel_id: The channel to send to.
            title: Notification title/subject.
            message: Notification body.
            severity: 1=critical, 2=high, 3=medium, 4=low.

        Returns:
            True if delivery succeeded.
        """
        channel = self._channels.get(channel_id)
        if not channel:
            logger.warning("Send failed: channel %s not found", channel_id)
            return False

        channel_type = channel["type"]
        config = channel.get("config", {})
        success = False

        try:
            if channel_type == "email":
                success = await self._send_email(config, title, message, severity)
            elif channel_type == "discord":
                success = await self._send_discord(config, title, message, severity)
            elif channel_type == "slack":
                success = await self._send_slack(config, title, message, severity)
            elif channel_type == "telegram":
                success = await self._send_telegram(config, title, message, severity)
            elif channel_type == "pushover":
                success = await self._send_pushover(config, title, message, severity)
            elif channel_type == "webhook":
                success = await self._send_webhook(config, title, message, severity)
            else:
                logger.error("Unknown channel type: %s", channel_type)
        except Exception as exc:
            logger.error("Failed to send to channel %s (%s): %s", channel_id, channel_type, exc)
            success = False

        # Log delivery
        self._delivery_log.append({
            "channel_id": channel_id,
            "channel_type": channel_type,
            "title": title,
            "severity": severity,
            "success": success,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        # Keep only last 100 entries
        if len(self._delivery_log) > 100:
            self._delivery_log = self._delivery_log[-100:]

        return success

    def get_delivery_log(self) -> list[dict[str, Any]]:
        """Return the recent delivery log entries."""
        return list(reversed(self._delivery_log))

    # ------------------------------------------------------------------
    # Channel-specific senders
    # ------------------------------------------------------------------

    @staticmethod
    def _severity_label(severity: int) -> str:
        return SEVERITY_LEVELS.get(severity, f"severity-{severity}")

    @staticmethod
    def _severity_color(severity: int) -> int:
        """Return a Discord embed colour for the severity level."""
        colors = {1: 0xFF0000, 2: 0xFF8C00, 3: 0xFFD700, 4: 0x00BFFF}
        return colors.get(severity, 0x808080)

    async def _send_email(
        self, config: dict, title: str, message: str, severity: int
    ) -> bool:
        """Send an email notification via SMTP."""
        host = config.get("smtp_host", "")
        port = int(config.get("smtp_port", 587))
        username = config.get("smtp_user", "")
        password = config.get("smtp_pass", "")
        from_addr = config.get("from_address", username)
        recipients = config.get("recipients", [])
        use_tls = config.get("use_tls", True)

        if not host or not recipients:
            logger.error("Email config incomplete: missing host or recipients")
            return False

        severity_tag = self._severity_label(severity).upper()
        msg = MIMEText(f"[{severity_tag}] {message}")
        msg["Subject"] = f"[NetTap] [{severity_tag}] {title}"
        msg["From"] = from_addr
        msg["To"] = ", ".join(recipients)

        try:
            if use_tls:
                ctx = ssl.create_default_context()
                with smtplib.SMTP(host, port) as server:
                    server.starttls(context=ctx)
                    if username and password:
                        server.login(username, password)
                    server.sendmail(from_addr, recipients, msg.as_string())
            else:
                with smtplib.SMTP(host, port) as server:
                    if username and password:
                        server.login(username, password)
                    server.sendmail(from_addr, recipients, msg.as_string())
            return True
        except Exception as exc:
            logger.error("SMTP send failed: %s", exc)
            return False

    async def _send_discord(
        self, config: dict, title: str, message: str, severity: int
    ) -> bool:
        """Send a Discord webhook notification."""
        webhook_url = config.get("webhook_url", "")
        if not webhook_url:
            logger.error("Discord config missing webhook_url")
            return False

        payload = {
            "embeds": [
                {
                    "title": title,
                    "description": message,
                    "color": self._severity_color(severity),
                    "footer": {"text": f"NetTap | {self._severity_label(severity).upper()}"},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ]
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload) as resp:
                return resp.status in (200, 204)

    async def _send_slack(
        self, config: dict, title: str, message: str, severity: int
    ) -> bool:
        """Send a Slack webhook notification."""
        webhook_url = config.get("webhook_url", "")
        if not webhook_url:
            logger.error("Slack config missing webhook_url")
            return False

        severity_emoji = {1: ":red_circle:", 2: ":orange_circle:", 3: ":large_yellow_circle:", 4: ":large_blue_circle:"}
        emoji = severity_emoji.get(severity, ":white_circle:")

        payload = {
            "text": f"{emoji} *{title}*\n{message}\n_Severity: {self._severity_label(severity)}_",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload) as resp:
                return resp.status == 200

    async def _send_telegram(
        self, config: dict, title: str, message: str, severity: int
    ) -> bool:
        """Send a Telegram bot notification."""
        bot_token = config.get("bot_token", "")
        chat_id = config.get("chat_id", "")
        if not bot_token or not chat_id:
            logger.error("Telegram config missing bot_token or chat_id")
            return False

        severity_tag = self._severity_label(severity).upper()
        text = f"*[{severity_tag}] {title}*\n\n{message}"
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                return resp.status == 200

    async def _send_pushover(
        self, config: dict, title: str, message: str, severity: int
    ) -> bool:
        """Send a Pushover notification."""
        user_key = config.get("user_key", "")
        api_token = config.get("api_token", "")
        if not user_key or not api_token:
            logger.error("Pushover config missing user_key or api_token")
            return False

        # Map severity to Pushover priority (-2 to 2)
        priority_map = {1: 2, 2: 1, 3: 0, 4: -1}
        priority = priority_map.get(severity, 0)

        payload = {
            "token": api_token,
            "user": user_key,
            "title": title,
            "message": message,
            "priority": priority,
        }
        # Emergency priority requires retry/expire
        if priority == 2:
            payload["retry"] = 60
            payload["expire"] = 3600

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.pushover.net/1/messages.json", data=payload
            ) as resp:
                return resp.status == 200

    async def _send_webhook(
        self, config: dict, title: str, message: str, severity: int
    ) -> bool:
        """Send a generic webhook POST notification."""
        webhook_url = config.get("url", "")
        if not webhook_url:
            logger.error("Webhook config missing url")
            return False

        payload = {
            "title": title,
            "message": message,
            "severity": severity,
            "severity_label": self._severity_label(severity),
            "source": "nettap",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        headers = config.get("headers", {})
        headers.setdefault("Content-Type", "application/json")

        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload, headers=headers) as resp:
                return 200 <= resp.status < 300

    # ------------------------------------------------------------------
    # Routing rules
    # ------------------------------------------------------------------

    def add_rule(
        self,
        event_type: str,
        channels: list[str],
        min_severity: int = 4,
    ) -> dict[str, Any]:
        """Add a routing rule that maps events to channels.

        Args:
            event_type: The event type to match (e.g. 'alert', 'new_device').
            channels: List of channel IDs to notify.
            min_severity: Only route events at or above this severity (1=critical).

        Returns:
            The created rule dict.
        """
        if event_type not in EVENT_TYPES:
            raise ValueError(f"Unknown event type: {event_type}. Must be one of {EVENT_TYPES}")

        rule_id = str(uuid.uuid4())[:8]
        rule = {
            "id": rule_id,
            "event_type": event_type,
            "channels": channels,
            "min_severity": min_severity,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._rules[rule_id] = rule
        self._save_config()
        logger.info("Added routing rule %s: %s -> %s (min_severity=%d)", rule_id, event_type, channels, min_severity)
        return rule

    def get_rules(self) -> list[dict[str, Any]]:
        """List all routing rules."""
        return list(self._rules.values())

    def delete_rule(self, rule_id: str) -> bool:
        """Remove a routing rule. Returns True if it existed."""
        if rule_id in self._rules:
            del self._rules[rule_id]
            self._save_config()
            logger.info("Deleted routing rule: %s", rule_id)
            return True
        return False

    async def process_event(
        self,
        event_type: str,
        title: str,
        message: str,
        severity: int = 3,
    ) -> dict[str, Any]:
        """Match routing rules and send notifications to appropriate channels.

        Returns a summary of which channels were notified and their success status.
        """
        results: dict[str, bool] = {}
        matched_rules = 0

        for rule in self._rules.values():
            if rule["event_type"] != event_type:
                continue
            if severity > rule.get("min_severity", 4):
                # severity 4 = low, severity 1 = critical
                # Only send if event severity <= rule min_severity (i.e. more severe)
                continue
            matched_rules += 1
            for channel_id in rule.get("channels", []):
                if channel_id not in results:  # avoid duplicate sends
                    success = await self.send(channel_id, title, message, severity)
                    results[channel_id] = success

        return {
            "event_type": event_type,
            "severity": severity,
            "matched_rules": matched_rules,
            "channels_notified": results,
        }
