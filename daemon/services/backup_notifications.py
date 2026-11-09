"""
Notification channels in a config backup (A9, NET-224).

Exported without their secrets; restored with the box's own secrets, but only where they would
still go to the same server, account and transport, so a crafted backup can't redirect them.
"""

from typing import Any

from services.notification_config import QUICK_WEBHOOK

# A backup carries only these; passwords, tokens, webhook URLs, headers and any unknown key stay
# on the box. The same keys as NET-224's public view (notification_config._PUBLIC_KEYS).
PUBLIC_KEYS = (
    "name",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "from_address",
    "recipients",
    "use_tls",
    "chat_id",
)
_CHANNEL_KEYS = ("id", "type", "name", "created_at", "enabled")
# A kept secret must still go to the same SMTP server, account and transport...
_DESTINATION_KEYS = ("smtp_host", "smtp_port", "smtp_user", "use_tls")
# ...and, when an older backup carries a URL, to that same URL
_URL_KEYS = ("url", "webhook_url")


def redact_channels(channels: Any) -> dict:
    """Channels for a backup: public keys only, plus the names of the keys left out."""
    if not isinstance(channels, dict):
        return {}
    out = {}
    for cid, channel in channels.items():
        if not isinstance(channel, dict):
            continue
        config = channel.get("config")
        config = config if isinstance(config, dict) else {}
        out[cid] = {
            **{k: channel[k] for k in _CHANNEL_KEYS if k in channel},
            "config": {k: v for k, v in config.items() if k in PUBLIC_KEYS},
            "secrets_left_out": sorted(k for k in config if k not in PUBLIC_KEYS),
        }
    return out


def _valid_channel(channel: Any) -> bool:
    if not isinstance(channel, dict) or not isinstance(channel.get("type"), str):
        return False
    left_out = channel.get("secrets_left_out", [])
    return isinstance(channel.get("config", {}), dict) and (
        isinstance(left_out, list) and all(isinstance(k, str) for k in left_out)
    )


def _same_destination(config: dict, old_config: dict) -> bool:
    if any(config.get(k) != old_config.get(k) for k in _DESTINATION_KEYS):
        return False
    return all(config[k] == old_config.get(k) for k in _URL_KEYS if k in config)


def restore_channels(
    backup: Any, current: Any, smtp_host_set: bool
) -> tuple[dict, list[str]]:
    """The channels to store and the warnings for the report. ValueError if the section is bad.

    ``smtp_host_set``: Settings › API keys has an SMTP server, which email channels without
    their own ``smtp_host`` send through.
    """
    if not isinstance(backup, dict) or not all(
        _valid_channel(c) for c in backup.values()
    ):
        raise ValueError("Notification channels in this backup aren't valid")
    current = current if isinstance(current, dict) else {}

    channels: dict = {}
    turned_off: list[str] = []
    quick_off: list[str] = []
    no_smtp: list[str] = []
    for cid, channel in backup.items():
        config = dict(channel.get("config") or {})
        old = current.get(cid) if isinstance(current.get(cid), dict) else {}
        old_config = old.get("config") if isinstance(old.get("config"), dict) else {}
        if channel["type"] == old.get("type") and _same_destination(config, old_config):
            secrets = {k: v for k, v in old_config.items() if k not in PUBLIC_KEYS}
            config = {**secrets, **config}
        stored = {k: v for k, v in channel.items() if k != "secrets_left_out"}
        stored["config"] = config
        label = str(channel.get("name") or cid)
        if any(k not in config for k in channel.get("secrets_left_out", [])):
            stored["enabled"] = False
            # OLD CODE: turned_off.append(label) (NET-224: the Settings webhook is fixed elsewhere)
            (quick_off if cid == QUICK_WEBHOOK else turned_off).append(label)
        elif (
            channel["type"] == "email"
            and stored.get("enabled", True) is not False
            and not config.get("smtp_host")
            and not smtp_host_set
        ):
            no_smtp.append(label)
        channels[cid] = stored

    warnings = []
    # OLD CODE START — NET-224: those channels have no edit or on switch; only the Settings tab's
    # webhook can be turned on with a new URL, so this asked for something the page can't do
    # if turned_off:
    #     warnings.append(
    #         "Notification channels restored without their passwords, URLs or tokens, "
    #         f"and turned off: {', '.join(turned_off)}. Enter them again in "
    #         "Settings › Notifications, then turn them on."
    #     )
    # OLD CODE END
    if quick_off:
        warnings.append(
            "The webhook restored without its URL and turned off. Turn it on in "
            "Settings › Notifications and enter its URL."
        )
    if turned_off:
        # a new channel gets a new id, so the restored rules don't reach it
        warnings.append(
            "Notification channels restored without their passwords, URLs or tokens, "
            f"and turned off: {', '.join(turned_off)}. On the Notification channels page, "
            "add each again with its secret and add its routing rules again for the new "
            "channel, then delete the old channel and rules."
        )
    if no_smtp:
        warnings.append(
            f"Email notifications ({', '.join(no_smtp)}) can't send until the SMTP server "
            "is set in Settings › API keys."
        )
    return channels, warnings
