"""
NetTap notification config: validation, the secret-free public view, the Settings tab's quick
setup and the first-start seed from the environment (NET-224).

Pure functions over the hub's channel and rule dicts; NotificationHub stores what they return.
"""

import os
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

CHANNEL_TYPES = {"email", "discord", "slack", "telegram", "pushover", "webhook"}
EVENT_TYPES = {
    "new_device",
    "alert",
    "anomaly",
    "storage_warning",
    "smart_warning",
    "capture_error",
    "system_error",
}

# Settings › API keys saves the SMTP server here (api/settings.py); the env is the fallback
ENV_FILE = os.environ.get("NETTAP_ENV_FILE", "/opt/nettap/data/.env")

# The Settings tab's own channels and rule, at fixed ids
QUICK_EMAIL = "settings-email"
QUICK_WEBHOOK = "settings-webhook"
QUICK_RULE = "settings-alerts"
DEFAULT_MIN_SEVERITY = 2  # high and above

# The public view shows only these config keys as they are...
_PUBLIC_KEYS = (
    "name",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "from_address",
    "recipients",
    "use_tls",
    "chat_id",
)
# ...these as a scheme://host hint (Discord, Slack and ntfy URLs carry their token)...
_URL_KEYS = ("webhook_url", "url")
# ...and these only as has_<key>
_SECRET_KEYS = ("smtp_pass", "bot_token", "api_token", "user_key", "headers")

_WHITESPACE = re.compile(r"\s")


_SMTP_NAMES = {
    "SMTP_HOST": "smtp_host",
    "SMTP_PORT": "smtp_port",
    "SMTP_USERNAME": "smtp_user",
    "SMTP_PASSWORD": "smtp_pass",
    "SMTP_SENDER_EMAIL": "from_address",
}


def _settings(names: list[str], env_file: str) -> dict[str, str]:
    """Values saved in Settings › API keys, else the process env (as _check_configured reads them)."""
    from api.settings import _load_env_file

    saved = _load_env_file(env_file)
    return {n: (saved.get(n) or os.environ.get(n, "")).strip() for n in names}


def setting(name: str, env_file: str = ENV_FILE) -> str:
    return _settings([name], env_file)[name]


def smtp_server(env_file: str = ENV_FILE) -> dict[str, Any]:
    """The SMTP server from Settings › API keys, in an email channel's config keys."""
    values = _settings(list(_SMTP_NAMES), env_file)
    return {key: values[name] for name, key in _SMTP_NAMES.items() if values[name]}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def url_problem(raw: Any) -> str | None:
    """Why `raw` can't be a webhook URL, or None. LAN addresses are fine (ntfy, Gotify)."""
    if not isinstance(raw, str) or not raw.strip():
        return "a webhook URL is required"
    parts = urlsplit(raw.strip())
    if parts.scheme not in ("http", "https"):
        return "the URL must start with http:// or https://"
    if not parts.hostname:
        return "the URL has no host"
    if parts.username is not None or parts.password is not None:
        return "the URL can't carry a user name or password before the host"
    return None


def _is_address(raw: Any) -> bool:
    # no whitespace, so no CR/LF into a mail header
    return isinstance(raw, str) and "@" in raw and not _WHITESPACE.search(raw)


def recipients_of(raw: Any) -> list[str]:
    """A recipients value as a list: older channels stored a comma-separated string."""
    if isinstance(raw, str):
        return [r.strip() for r in raw.split(",") if r.strip()]
    return raw if isinstance(raw, list) else []


def _is_int_in(raw: Any, low: int, high: int) -> bool:
    return isinstance(raw, int) and not isinstance(raw, bool) and low <= raw <= high


def validate_channel(channel_type: Any, config: Any) -> str | None:
    """Why this channel can't be saved, or None."""
    if channel_type not in CHANNEL_TYPES:
        return f"Unsupported channel type: {channel_type}"
    if not isinstance(config, dict):
        return "config must be an object"
    if channel_type in ("discord", "slack"):
        return url_problem(config.get("webhook_url"))
    if channel_type == "webhook":
        return url_problem(config.get("url"))
    if channel_type == "telegram":
        ok = config.get("bot_token") and config.get("chat_id")
        return None if ok else "a bot token and a chat ID are required"
    if channel_type == "pushover":
        ok = config.get("user_key") and config.get("api_token")
        return None if ok else "a user key and an API token are required"
    recipients = config.get("recipients")
    if not isinstance(recipients, list) or not recipients:
        return "add at least one recipient"
    if not all(_is_address(r) for r in recipients):
        return "each recipient must be an email address"
    if config.get("from_address") and not _is_address(config["from_address"]):
        return "the sender must be an email address"
    port = config.get("smtp_port")
    if port not in (None, ""):
        try:
            number = int(port)
        except (TypeError, ValueError):
            number = 0
        if isinstance(port, bool) or not 1 <= number <= 65535:
            return "the SMTP port must be a number from 1 to 65535"
    return None


def rule_ok(rule: Any) -> bool:
    """A stored rule dispatch can use: anything else is skipped, never raised on."""
    if not isinstance(rule, dict):
        return False
    channels = rule.get("channels")
    return (
        isinstance(rule.get("event_type"), str)
        and _is_int_in(rule.get("min_severity", 4), 1, 4)
        and isinstance(channels, list)
        and all(isinstance(c, str) for c in channels)
    )


def validate_rule(body: Any, channel_ids: set[str]) -> str | None:
    """Why this rule can't be saved, or None."""
    if not isinstance(body, dict):
        return "Body must be a JSON object"
    if body.get("event_type") not in EVENT_TYPES:
        return f"Unknown event type: {body.get('event_type')}"
    if not _is_int_in(body.get("min_severity", 4), 1, 4):
        return "min_severity must be 1 (critical) to 4 (low)"
    channels = body.get("channels")
    if not isinstance(channels, list) or not channels:
        return "pick at least one channel"
    if not all(isinstance(c, str) and c in channel_ids for c in channels):
        return "a picked channel doesn't exist"
    return None


# ---------------------------------------------------------------------------
# The public view (never a secret)
# ---------------------------------------------------------------------------


def url_hint(raw: Any) -> str:
    """scheme://host[:port]/… with the user info, path and query left out."""
    if not isinstance(raw, str):
        return ""
    parts = urlsplit(raw.strip())
    # netloc keeps an IPv6 address's brackets; anything before an @ is user info
    host = parts.netloc.rpartition("@")[2]
    return f"{parts.scheme}://{host}/…" if parts.hostname else ""


def is_enabled(channel: dict) -> bool:
    return channel.get("enabled", True) is not False


def public_channel(channel: dict, last_delivery: dict | None = None) -> dict:
    """A channel as GET may show it: listed keys, URL hints and has_<secret> flags only."""
    config = channel.get("config") if isinstance(channel.get("config"), dict) else {}
    shown = {k: config[k] for k in _PUBLIC_KEYS if k in config}
    hints = {f"{k}_hint": url_hint(config[k]) for k in _URL_KEYS if config.get(k)}
    flags = {f"has_{k}": True for k in (*_URL_KEYS, *_SECRET_KEYS) if config.get(k)}
    return {
        "id": channel.get("id"),
        "type": channel.get("type"),
        "name": channel.get("name"),
        "created_at": channel.get("created_at"),
        "enabled": is_enabled(channel),
        "config": {**shown, **hints, **flags},
        "last_delivery": last_delivery,
    }


# ---------------------------------------------------------------------------
# The Settings tab's quick setup
# ---------------------------------------------------------------------------


def quick_view(channels: dict, rules: dict, smtp_configured: bool) -> dict:
    """What the Settings tab shows: no URL or password, only whether one is saved."""
    email = channels.get(QUICK_EMAIL) or {}
    webhook = channels.get(QUICK_WEBHOOK) or {}
    rule = rules.get(QUICK_RULE)
    url = (webhook.get("config") or {}).get("url", "")
    return {
        "min_severity": rule["min_severity"]
        if rule_ok(rule) and "min_severity" in rule
        else DEFAULT_MIN_SEVERITY,
        "email": {
            "enabled": bool(email) and is_enabled(email),
            "recipients": recipients_of((email.get("config") or {}).get("recipients")),
            "smtp_configured": smtp_configured,
        },
        "webhook": {
            "enabled": bool(webhook) and is_enabled(webhook),
            "has_url": bool(url),
            "url_hint": url_hint(url),
        },
    }


def _quick_channel(
    old: dict | None, cid: str, kind: str, config: dict, enabled: bool, now: str
) -> dict:
    name = "Email (Settings)" if kind == "email" else "Webhook (Settings)"
    return {
        "id": cid,
        "type": kind,
        "name": name,
        "config": {"name": name, **config},
        "created_at": (old or {}).get("created_at", now),
        "enabled": enabled,
    }


def _with_quick_rule(channels: dict, rules: dict, min_severity: int, now: str) -> dict:
    """`rules` with the Settings rule sending alerts to whichever Settings channels exist."""
    ids = [cid for cid in (QUICK_EMAIL, QUICK_WEBHOOK) if cid in channels]
    others = {k: v for k, v in rules.items() if k != QUICK_RULE}
    if not ids:
        return others
    old = rules.get(QUICK_RULE) if isinstance(rules.get(QUICK_RULE), dict) else {}
    rule = {
        "id": QUICK_RULE,
        "event_type": "alert",
        "channels": ids,
        "min_severity": min_severity,
        "created_at": old.get("created_at", now),
    }
    return {**others, QUICK_RULE: rule}


def apply_quick_settings(
    channels: dict, rules: dict, body: Any, smtp_configured: bool, now: str
) -> tuple[dict, dict]:
    """The new (channels, rules) for a Settings tab save. Raises ValueError with the reason.

    Off keeps a channel's settings (enabled: false), so a webhook comes back on with a blank URL.
    """
    if not isinstance(body, dict):
        raise ValueError("Body must be a JSON object")
    min_severity = body.get("min_severity")
    if not _is_int_in(min_severity, 1, 4):
        raise ValueError("min_severity must be 1 (critical) to 4 (low)")
    email = body.get("email") or {}
    webhook = body.get("webhook") or {}
    if not isinstance(email, dict) or not isinstance(webhook, dict):
        raise ValueError("email and webhook must be objects")

    new = dict(channels)
    old_email = channels.get(QUICK_EMAIL)
    if email.get("enabled") is True:
        recipients = email.get("recipients")
        problem = validate_channel("email", {"recipients": recipients})
        if problem:
            raise ValueError(f"Email: {problem}")
        if not smtp_configured:
            raise ValueError("Email: set the SMTP server in Settings › API keys first")
        new[QUICK_EMAIL] = _quick_channel(
            old_email, QUICK_EMAIL, "email", {"recipients": recipients}, True, now
        )
    elif old_email:
        new[QUICK_EMAIL] = {**old_email, "enabled": False}

    old_webhook = channels.get(QUICK_WEBHOOK)
    if webhook.get("enabled") is True:
        given = webhook.get("url")
        given = given.strip() if isinstance(given, str) else ""
        url = given or ((old_webhook or {}).get("config") or {}).get("url", "")
        problem = url_problem(url)
        if problem:
            raise ValueError(f"Webhook: {problem}")
        new[QUICK_WEBHOOK] = _quick_channel(
            old_webhook, QUICK_WEBHOOK, "webhook", {"url": url}, True, now
        )
    elif old_webhook:
        new[QUICK_WEBHOOK] = {**old_webhook, "enabled": False}

    return new, _with_quick_rule(new, rules, min_severity, now)


def seed_from_env(get: Callable[[str], str], now: str) -> tuple[dict, dict, list[str]]:
    """(channels, rules, warnings) from ALERT_EMAIL, WEBHOOK_URL and ALERT_SEVERITY_THRESHOLD.

    Used once, when there is no notifications.json yet. Warnings name the key, never its value.
    """
    channels: dict = {}
    warnings: list[str] = []
    recipients = recipients_of(get("ALERT_EMAIL"))
    if recipients:
        if validate_channel("email", {"recipients": recipients}) is None:
            channels[QUICK_EMAIL] = _quick_channel(
                None, QUICK_EMAIL, "email", {"recipients": recipients}, True, now
            )
        else:
            warnings.append("ALERT_EMAIL isn't a list of email addresses; not used")
    url = get("WEBHOOK_URL")
    if url:
        if url_problem(url) is None:
            channels[QUICK_WEBHOOK] = _quick_channel(
                None, QUICK_WEBHOOK, "webhook", {"url": url}, True, now
            )
        else:
            warnings.append("WEBHOOK_URL isn't an http(s) URL; not used")
    raw = get("ALERT_SEVERITY_THRESHOLD")
    try:
        min_severity = int(raw) if raw else DEFAULT_MIN_SEVERITY
    except ValueError:
        min_severity = 0
    if not 1 <= min_severity <= 4:
        warnings.append(
            "ALERT_SEVERITY_THRESHOLD isn't 1 to 4; using 2 (high and above)"
        )
        min_severity = DEFAULT_MIN_SEVERITY
    return channels, _with_quick_rule(channels, {}, min_severity, now), warnings
