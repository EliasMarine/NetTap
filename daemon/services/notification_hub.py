"""
NetTap NotificationHub — Multi-channel notification system.

Supports 6 channel types: email (SMTP), Discord, Slack, Telegram,
Pushover, and generic webhook. Includes a routing rules engine
that maps event types to channels with severity filtering.

Channel and rule configs are persisted to a JSON file.

NET-224: the daemon is the only external dispatcher. Saves are atomic, mode 600, and swap the
live config only once written; GET never shows a secret (notification_config.public_channel);
every send has a deadline and records why it failed.
"""

import asyncio
import contextlib
import json
import logging
import os
import smtplib
import socket
import ssl
import threading
import uuid
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import aiohttp

from services import notification_config as nc
from services.capture_config import write_file_atomic

logger = logging.getLogger("nettap.services.notification_hub")

# OLD CODE START — NET-224: one definition, in notification_config, which validates against them
# # Supported channel types
# CHANNEL_TYPES = {"email", "discord", "slack", "telegram", "pushover", "webhook"}
#
# # Supported event types for routing rules
# EVENT_TYPES = {
#     "new_device",
#     "alert",
#     "anomaly",
#     "storage_warning",
#     "smart_warning",
#     "capture_error",
#     "system_error",
# }
# OLD CODE END
CHANNEL_TYPES = nc.CHANNEL_TYPES
EVENT_TYPES = nc.EVENT_TYPES

# Severity levels (1 = critical, 4 = low)
SEVERITY_LEVELS = {1: "critical", 2: "high", 3: "medium", 4: "low"}

# Seconds for the SMTP connect and each reply: an unreachable server must not hold a thread
_SMTP_TIMEOUT_S = 10
# The whole SMTP transaction: the socket timeout is per reply, so a server trickling replies (or an
# endless run of continuation lines) could hold the thread for ever (NET-224)
_SMTP_DEADLINE_S = 30
# Each HTTP send, connect to last byte
_HTTP_TIMEOUT_S = 10

# Default config path
_DEFAULT_CONFIG_PATH = os.environ.get(
    "NOTIFICATION_CONFIG", "./data/notifications.json"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _post(url: str, **kwargs: Any) -> str | None:
    """POST with a deadline and no redirects (a 3xx fails, so it never reaches another scheme or
    host). None for a 2xx, else the reason."""
    timeout = aiohttp.ClientTimeout(total=_HTTP_TIMEOUT_S)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, allow_redirects=False, **kwargs) as resp:
            return None if 200 <= resp.status < 300 else f"HTTP {resp.status}"


def _reason(exc: BaseException) -> str:
    """A failed send in plain words, without the URL: Telegram and Discord URLs carry tokens."""
    if isinstance(exc, TimeoutError):  # asyncio's and the socket's, on 3.11+
        return "timed out"
    if isinstance(exc, aiohttp.ClientConnectorError):
        return f"can't connect to {exc.host}"
    if isinstance(exc, smtplib.SMTPResponseException):
        text = (
            exc.smtp_error.decode(errors="replace")
            if isinstance(exc.smtp_error, bytes)
            else str(exc.smtp_error)
        )
        return f"the mail server answered {exc.smtp_code} {text}"[:300]
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "the mail server refused every recipient"
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return "the mail server closed the connection (or the 30 s limit cut it off)"
    if isinstance(exc, ssl.SSLError):
        return f"TLS failed: {exc.reason or type(exc).__name__}"
    if isinstance(exc, OSError) and exc.strerror:
        return f"can't connect: {exc.strerror}"
    return type(exc).__name__


def _cut_off(server: smtplib.SMTP) -> None:
    """The SMTP deadline: shutting the socket down wakes a blocked read, so the send raises."""
    with contextlib.suppress(OSError, AttributeError):
        server.sock.shutdown(socket.SHUT_RDWR)


class NotificationHub:
    """Multi-channel notification system with routing rules."""

    def __init__(
        self, config_path: str | None = None, env_file: str | None = None
    ) -> None:
        self._config_path = Path(config_path or _DEFAULT_CONFIG_PATH)
        # Settings › API keys' file: the SMTP server and the first-start seed (NET-224)
        self._env_file = env_file or nc.ENV_FILE
        self._channels: dict[str, dict[str, Any]] = {}
        self._rules: dict[str, dict[str, Any]] = {}
        self._delivery_log: list[dict[str, Any]] = []
        # channel id -> {"ok", "at", "error"} of its last send, shown in Settings
        self._last_delivery: dict[str, dict[str, Any]] = {}
        self._warned_rules: frozenset[str] = frozenset()
        self._load_config()

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        """Load channels and rules from the JSON config file."""
        if self._config_path.exists():
            try:
                # OLD CODE START — NET-224: a non-dict section (hand-edited file) broke every later call
                # data = json.loads(self._config_path.read_text())
                # self._channels = data.get("channels", {})
                # self._rules = data.get("rules", {})
                # OLD CODE END
                data = json.loads(self._config_path.read_text())
                data = data if isinstance(data, dict) else {}
                channels, rules = data.get("channels"), data.get("rules")
                self._channels = channels if isinstance(channels, dict) else {}
                self._rules = rules if isinstance(rules, dict) else {}
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
            logger.info(
                "No notification config at %s, starting fresh", self._config_path
            )
            self._seed_from_env()

    def _seed_from_env(self) -> None:
        """First start only: the email/webhook named in the environment (NET-224)."""
        channels, rules, warnings = nc.seed_from_env(
            lambda name: nc.setting(name, self._env_file), _now()
        )
        for warning in warnings:
            logger.warning("Notification seed: %s", warning)
        if not channels:
            return
        try:
            self._commit(channels, rules)
            logger.info(
                "Notification settings seeded from the environment: %s",
                ", ".join(channels),
            )
        except OSError as exc:
            logger.warning("Couldn't save the seeded notification settings: %s", exc)

    # OLD CODE START — NET-224: not atomic, mode from umask (the file holds SMTP passwords and tokens), and callers had already changed the live config, so a failed write left the daemon using what was never saved
    # def _save_config(self) -> None:
    #     """Persist channels and rules to the JSON config file."""
    #     self._config_path.parent.mkdir(parents=True, exist_ok=True)
    #     data = {"channels": self._channels, "rules": self._rules}
    #     self._config_path.write_text(json.dumps(data, indent=2))
    #     logger.debug("Saved notification config to %s", self._config_path)
    # OLD CODE END
    def _commit(self, channels: dict[str, Any], rules: dict[str, Any]) -> None:
        """Write the new config atomically (600), then make it live. OSError leaves both as they were."""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"channels": channels, "rules": rules}, indent=2)
        write_file_atomic(str(self._config_path), text, mode=0o600)
        self._channels, self._rules = channels, rules
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
            raise ValueError(
                f"Unsupported channel type: {channel_type}. Must be one of {CHANNEL_TYPES}"
            )

        channel_id = config.get("id") or str(uuid.uuid4())[:8]
        channel = {
            "id": channel_id,
            "type": channel_type,
            "name": config.get("name", f"{channel_type}-{channel_id}"),
            "config": config,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        # OLD CODE START — NET-224: saved through _commit
        # self._channels[channel_id] = channel
        # self._save_config()
        # logger.info("Configured %s channel: %s", channel_type, channel_id)
        # OLD CODE END
        self._commit({**self._channels, channel_id: channel}, self._rules)
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
        # OLD CODE START — NET-224: saved through _commit
        # if channel_id in self._channels:
        #     del self._channels[channel_id]
        #     self._save_config()
        #     logger.info("Deleted channel: %s", channel_id)
        #     return True
        # return False
        # OLD CODE END
        if channel_id not in self._channels:
            return False
        kept = {k: v for k, v in self._channels.items() if k != channel_id}
        self._commit(kept, self._rules)
        logger.info("Deleted channel: %s", channel_id)
        return True

    def public_channels(self) -> list[dict[str, Any]]:
        """The channels as the API shows them: no secret, plus each one's last delivery."""
        return [
            nc.public_channel(ch, self._last_delivery.get(cid))
            for cid, ch in self._channels.items()
        ]

    def last_delivery(self, channel_id: str) -> dict[str, Any] | None:
        return self._last_delivery.get(channel_id)

    def smtp_configured(self) -> bool:
        return bool(nc.smtp_server(self._env_file).get("smtp_host"))

    def get_quick_settings(self) -> dict[str, Any]:
        """The Settings tab's email, webhook and minimum severity (no URL or password)."""
        return nc.quick_view(self._channels, self._rules, self.smtp_configured())

    def set_quick_settings(self, body: Any) -> dict[str, Any]:
        """Save the Settings tab. ValueError: the reason it can't; OSError: the write failed."""
        channels, rules = nc.apply_quick_settings(
            self._channels, self._rules, body, self.smtp_configured(), _now()
        )
        self._commit(channels, rules)
        return self.get_quick_settings()

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

        # OLD CODE START — NET-224: a bare bool, so the page could only say 'failed'; the exception text could carry a webhook URL's token into the log
        # channel_type = channel["type"]
        # config = channel.get("config", {})
        # success = False
        #
        # try:
        #     if channel_type == "email":
        #         success = await self._send_email(config, title, message, severity)
        #     elif channel_type == "discord":
        #         success = await self._send_discord(config, title, message, severity)
        #     elif channel_type == "slack":
        #         success = await self._send_slack(config, title, message, severity)
        #     elif channel_type == "telegram":
        #         success = await self._send_telegram(config, title, message, severity)
        #     elif channel_type == "pushover":
        #         success = await self._send_pushover(config, title, message, severity)
        #     elif channel_type == "webhook":
        #         success = await self._send_webhook(config, title, message, severity)
        #     else:
        #         logger.error("Unknown channel type: %s", channel_type)
        # except Exception as exc:
        #     logger.error(
        #         "Failed to send to channel %s (%s): %s", channel_id, channel_type, exc
        #     )
        #     success = False
        #
        # # Log delivery
        # self._delivery_log.append(
        #     {
        #         "channel_id": channel_id,
        #         "channel_type": channel_type,
        #         "title": title,
        #         "severity": severity,
        #         "success": success,
        #         "timestamp": datetime.now(timezone.utc).isoformat(),
        #     }
        # )
        # # Keep only last 100 entries
        # if len(self._delivery_log) > 100:
        #     self._delivery_log = self._delivery_log[-100:]
        #
        # return success
        # OLD CODE END
        channel_type = channel["type"]
        config = channel.get("config", {})
        senders = {
            "email": self._send_email,
            "discord": self._send_discord,
            "slack": self._send_slack,
            "telegram": self._send_telegram,
            "pushover": self._send_pushover,
            "webhook": self._send_webhook,
        }
        sender = senders.get(channel_type)
        try:
            # each sender answers None when sent, else the reason
            error = (
                await sender(config, title, message, severity)
                if sender
                else f"unknown channel type {channel_type}"
            )
        except Exception as exc:
            error = _reason(exc)
        if error:
            # the reason, never the exception text: a URL in it can carry a token
            logger.error(
                "Failed to send to channel %s (%s): %s", channel_id, channel_type, error
            )
        success = error is None
        now = _now()
        self._last_delivery = {
            **self._last_delivery,
            channel_id: {"ok": success, "at": now, "error": error},
        }
        entry = {
            "channel_id": channel_id,
            "channel_type": channel_type,
            "title": title,
            "severity": severity,
            "success": success,
            "error": error,
            "timestamp": now,
        }
        # Keep only the last 100 entries
        self._delivery_log = [*self._delivery_log, entry][-100:]
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
    ) -> str | None:
        # OLD CODE START — NET-224: no API-keys server, a bool answer, and the title went into the header as given
        # """Send an email notification via SMTP."""
        # host = config.get("smtp_host", "")
        # port = int(config.get("smtp_port", 587))
        # username = config.get("smtp_user", "")
        # password = config.get("smtp_pass", "")
        # from_addr = config.get("from_address", username)
        # recipients = config.get("recipients", [])
        # use_tls = config.get("use_tls", True)
        #
        # if not host or not recipients:
        #     logger.error("Email config incomplete: missing host or recipients")
        #     return False
        #
        # severity_tag = self._severity_label(severity).upper()
        # msg = MIMEText(f"[{severity_tag}] {message}")
        # msg["Subject"] = f"[NetTap] [{severity_tag}] {title}"
        # OLD CODE END
        """Send an email notification via SMTP. None when sent, else the reason."""
        # NET-224: a channel without its own server uses the one in Settings › API keys
        server = config if config.get("smtp_host") else nc.smtp_server(self._env_file)
        host = server.get("smtp_host", "")
        try:
            port = int(server.get("smtp_port") or 587)
        except ValueError:  # Settings › API keys saves the port as typed
            return "the SMTP port isn't a number"
        username = server.get("smtp_user", "")
        password = server.get("smtp_pass", "")
        from_addr = server.get("from_address") or username
        recipients = nc.recipients_of(config.get("recipients"))
        use_tls = server.get("use_tls", True)

        if not host:
            return "no SMTP server: set one in Settings › API keys"
        if not recipients:
            return "no recipients"

        severity_tag = self._severity_label(severity).upper()
        msg = MIMEText(f"[{severity_tag}] {message}")
        # no CR/LF into the header
        subject_title = title.replace("\r", " ").replace("\n", " ")
        msg["Subject"] = f"[NetTap] [{severity_tag}] {subject_title}"
        msg["From"] = from_addr
        msg["To"] = ", ".join(recipients)

        # OLD CODE START — PR 2 (reliability): connect, STARTTLS, login and send blocked the
        # request loop, with no timeout (an unreachable server held every page)
        # try:
        #     if use_tls:
        #         ctx = ssl.create_default_context()
        #         with smtplib.SMTP(host, port) as server:
        #             server.starttls(context=ctx)
        #             if username and password:
        #                 server.login(username, password)
        #             server.sendmail(from_addr, recipients, msg.as_string())
        #     else:
        #         with smtplib.SMTP(host, port) as server:
        #             if username and password:
        #                 server.login(username, password)
        #             server.sendmail(from_addr, recipients, msg.as_string())
        #     return True
        # except Exception as exc:
        #     logger.error("SMTP send failed: %s", exc)
        #     return False
        # OLD CODE END
        # OLD CODE START — NET-224: send() records the reason now; a partly refused message counted as sent
        # try:
        #     await asyncio.to_thread(
        #         self._smtp_send,
        #         host,
        #         port,
        #         use_tls,
        #         username,
        #         password,
        #         from_addr,
        #         recipients,
        #         msg.as_string(),
        #     )
        #     return True
        # except Exception as exc:
        #     logger.error("SMTP send failed: %s", exc)
        #     return False
        # OLD CODE END
        refused = await asyncio.to_thread(
            self._smtp_send,
            host,
            port,
            use_tls,
            username,
            password,
            from_addr,
            recipients,
            msg.as_string(),
        )
        # sendmail returns normally when only some recipients were refused
        if refused:
            return "the mail server refused " + ", ".join(sorted(refused))
        return None

    @staticmethod
    def _smtp_send(
        host: str,
        port: int,
        use_tls: bool,
        username: str,
        password: str,
        from_addr: str,
        recipients: list[str],
        text: str,
    ) -> dict:
        # OLD CODE START — NET-224: no overall deadline, no port 465, and refused recipients were ignored
        # """The whole SMTP transaction; it blocks, so it runs in a worker thread."""
        # with smtplib.SMTP(host, port, timeout=_SMTP_TIMEOUT_S) as server:
        #     if use_tls:
        #         server.starttls(context=ssl.create_default_context())
        #     if username and password:
        #         server.login(username, password)
        #     server.sendmail(from_addr, recipients, text)
        # OLD CODE END
        """The whole SMTP transaction; it blocks, so it runs in a worker thread.

        Returns the recipients the server refused (empty when all took it). Port 465 is TLS from
        the first byte, other ports upgrade with STARTTLS; both verify the certificate.
        """
        implicit_tls = port == 465
        smtp_cls = smtplib.SMTP_SSL if implicit_tls else smtplib.SMTP
        tls = {"context": ssl.create_default_context()} if implicit_tls else {}
        with smtp_cls(host, port, timeout=_SMTP_TIMEOUT_S, **tls) as server:
            deadline = threading.Timer(_SMTP_DEADLINE_S, _cut_off, args=(server,))
            deadline.daemon = True
            deadline.start()
            try:
                if use_tls and not implicit_tls:
                    server.starttls(context=ssl.create_default_context())
                if username and password:
                    server.login(username, password)
                refused = server.sendmail(from_addr, recipients, text)
            finally:
                deadline.cancel()
        return refused if isinstance(refused, dict) else {}

    async def _send_discord(
        self, config: dict, title: str, message: str, severity: int
    ) -> str | None:
        """Send a Discord webhook notification."""
        webhook_url = config.get("webhook_url", "")
        if not webhook_url:
            return "no webhook URL"

        payload = {
            "embeds": [
                {
                    "title": title,
                    "description": message,
                    "color": self._severity_color(severity),
                    "footer": {
                        "text": f"NetTap | {self._severity_label(severity).upper()}"
                    },
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ]
        }

        # OLD CODE START — NET-224: through _post (deadline, no redirects, the status as the reason)
        # async with aiohttp.ClientSession() as session:
        #     async with session.post(webhook_url, json=payload) as resp:
        #         return resp.status in (200, 204)
        # OLD CODE END
        return await _post(webhook_url, json=payload)

    async def _send_slack(
        self, config: dict, title: str, message: str, severity: int
    ) -> str | None:
        """Send a Slack webhook notification."""
        webhook_url = config.get("webhook_url", "")
        if not webhook_url:
            return "no webhook URL"

        severity_emoji = {
            1: ":red_circle:",
            2: ":orange_circle:",
            3: ":large_yellow_circle:",
            4: ":large_blue_circle:",
        }
        emoji = severity_emoji.get(severity, ":white_circle:")

        payload = {
            "text": f"{emoji} *{title}*\n{message}\n_Severity: {self._severity_label(severity)}_",
        }

        # OLD CODE START — NET-224: through _post (deadline, no redirects, the status as the reason)
        # async with aiohttp.ClientSession() as session:
        #     async with session.post(webhook_url, json=payload) as resp:
        #         return resp.status == 200
        # OLD CODE END
        return await _post(webhook_url, json=payload)

    async def _send_telegram(
        self, config: dict, title: str, message: str, severity: int
    ) -> str | None:
        """Send a Telegram bot notification."""
        bot_token = config.get("bot_token", "")
        chat_id = config.get("chat_id", "")
        if not bot_token or not chat_id:
            return "no bot token or chat ID"

        severity_tag = self._severity_label(severity).upper()
        text = f"*[{severity_tag}] {title}*\n\n{message}"
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}

        # OLD CODE START — NET-224: through _post (deadline, no redirects, the status as the reason)
        # async with aiohttp.ClientSession() as session:
        #     async with session.post(url, json=payload) as resp:
        #         return resp.status == 200
        # OLD CODE END
        return await _post(url, json=payload)

    async def _send_pushover(
        self, config: dict, title: str, message: str, severity: int
    ) -> str | None:
        """Send a Pushover notification."""
        user_key = config.get("user_key", "")
        api_token = config.get("api_token", "")
        if not user_key or not api_token:
            return "no user key or API token"

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

        # OLD CODE START — NET-224: through _post (deadline, no redirects, the status as the reason)
        # async with aiohttp.ClientSession() as session:
        #     async with session.post(
        #         "https://api.pushover.net/1/messages.json", data=payload
        #     ) as resp:
        #         return resp.status == 200
        # OLD CODE END
        return await _post("https://api.pushover.net/1/messages.json", data=payload)

    async def _send_webhook(
        self, config: dict, title: str, message: str, severity: int
    ) -> str | None:
        """Send a generic webhook POST notification."""
        webhook_url = config.get("url", "")
        if not webhook_url:
            return "no webhook URL"

        payload = {
            "title": title,
            "message": message,
            "severity": severity,
            "severity_label": self._severity_label(severity),
            "source": "nettap",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # OLD CODE START — NET-224: through _post (deadline, no redirects, the status as the reason)
        # headers = config.get("headers", {})
        # headers.setdefault("Content-Type", "application/json")
        #
        # async with aiohttp.ClientSession() as session:
        #     async with session.post(webhook_url, json=payload, headers=headers) as resp:
        #         return 200 <= resp.status < 300
        # OLD CODE END
        # a copy: setdefault wrote Content-Type into the stored config
        headers = {"Content-Type": "application/json", **(config.get("headers") or {})}
        return await _post(webhook_url, json=payload, headers=headers)

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
            raise ValueError(
                f"Unknown event type: {event_type}. Must be one of {EVENT_TYPES}"
            )

        rule_id = str(uuid.uuid4())[:8]
        rule = {
            "id": rule_id,
            "event_type": event_type,
            "channels": channels,
            "min_severity": min_severity,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        # OLD CODE START — NET-224: saved through _commit
        # self._rules[rule_id] = rule
        # self._save_config()
        # OLD CODE END
        self._commit(self._channels, {**self._rules, rule_id: rule})
        logger.info(
            "Added routing rule %s: %s -> %s (min_severity=%d)",
            rule_id,
            event_type,
            channels,
            min_severity,
        )
        return rule

    def get_rules(self) -> list[dict[str, Any]]:
        """List all routing rules."""
        return list(self._rules.values())

    def delete_rule(self, rule_id: str) -> bool:
        """Remove a routing rule. Returns True if it existed."""
        # OLD CODE START — NET-224: saved through _commit
        # if rule_id in self._rules:
        #     del self._rules[rule_id]
        #     self._save_config()
        #     logger.info("Deleted routing rule: %s", rule_id)
        #     return True
        # return False
        # OLD CODE END
        if rule_id not in self._rules:
            return False
        self._commit(
            self._channels, {k: v for k, v in self._rules.items() if k != rule_id}
        )
        logger.info("Deleted routing rule: %s", rule_id)
        return True

    def _matching_rules(self, event_type: str, severity: int) -> list[dict[str, Any]]:
        """The rules this event matches, read before any await (a save mid-send can't break it)."""
        matched = []
        for rule_id, rule in list(self._rules.items()):
            if not nc.rule_ok(rule):
                # a hand-edited or legacy rule is skipped, once warned, never raised on
                if rule_id not in self._warned_rules:
                    self._warned_rules = self._warned_rules | {rule_id}
                    logger.warning(
                        "Skipping notification rule %s: not a valid rule", rule_id
                    )
                continue
            # severity 1 = critical ... 4 = low: send when at least as severe as the rule's minimum
            if rule["event_type"] == event_type and severity <= rule.get(
                "min_severity", 4
            ):
                matched.append(rule)
        return matched

    def channels_for(self, event_type: str, severity: int) -> list[str]:
        """The enabled, existing channels the rules send this event to, each once."""
        rules = self._matching_rules(event_type, severity)
        ids = dict.fromkeys(cid for rule in rules for cid in rule["channels"])
        return [
            cid
            for cid in ids
            if cid in self._channels and nc.is_enabled(self._channels[cid])
        ]

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
        # OLD CODE START — NET-224: iterated the live rules across each await (a save mid-send raised), and one malformed stored rule raised for every event
        # results: dict[str, bool] = {}
        # matched_rules = 0
        #
        # for rule in self._rules.values():
        #     if rule["event_type"] != event_type:
        #         continue
        #     if severity > rule.get("min_severity", 4):
        #         # severity 4 = low, severity 1 = critical
        #         # Only send if event severity <= rule min_severity (i.e. more severe)
        #         continue
        #     matched_rules += 1
        #     for channel_id in rule.get("channels", []):
        #         if channel_id not in results:  # avoid duplicate sends
        #             success = await self.send(channel_id, title, message, severity)
        #             results[channel_id] = success
        #
        # return {
        #     "event_type": event_type,
        #     "severity": severity,
        #     "matched_rules": matched_rules,
        # OLD CODE END
        matched_rules = len(self._matching_rules(event_type, severity))
        results: dict[str, bool] = {}
        for channel_id in self.channels_for(event_type, severity):
            results[channel_id] = await self.send(channel_id, title, message, severity)

        return {
            "event_type": event_type,
            "severity": severity,
            "matched_rules": matched_rules,
            "channels_notified": results,
        }
