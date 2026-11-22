"""
NET-344: the one content check a config backup's validate, import and export share (plan §2.4).

``section_errors`` finds every content problem restoring a backup's sections would hit, without
changing anything, so a backup with one bad section applies nothing. A download that wouldn't
restore is refused with ``BackupRefused``: "legacy_excluded_ips" for an excluded-IP list an older
NetTap allowed (the owner can fix it), "invalid_section" for anything else.
"""

import ipaddress
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from services.bandwidth_tracker import MAX_MONTHLY_CAP_BYTES
from services.capture_config import CaptureConfig
from services.device_custom import restore_message, restore_problems
from services.device_details import problems as details_problems
from services.dhcp_gateway_net import validate_interface_name, validate_subnet
from services.excluded_ips import EXCLUDED_IPS_MAX, parse_single_ip
from services.home_location import parse_home
from services.notification_hub import backup_problems
from services.report_schedule import backup_problems as report_schedule_problems
from storage.retention_config import RetentionConfigManager

# The fields each capture mode uses, as POST /api/setup/configure takes them
CAPTURE_FIELDS = {
    "bridge": ("wan_interface", "lan_interface"),
    "mirror": ("capture_interface", "management_interface"),
    "dhcp_gateway": ("capture_interface", "dhcp_subnet"),
}
_SUPPRESS_TIMES = ("expires_at", "suppressed_at", "marked_at")
LEFT_OUT = "acknowledgements_left_out"
ACKS = "alert_acknowledgements"

# How the owner reads each section's name
LABELS = {
    "capture_mode_config": "the capture mode",
    "storage_retention": "retention",
    "notification_channels": "notification channels",
    "notification_rules": "notification rules",
    "notification_quiet": "quiet hours",
    "device_aliases": "device names",
    "device_pictures": "device pictures",
    "device_details": "device details",
    "excluded_ips": "excluded IPs",
    "bandwidth_cap": "the bandwidth cap",
    "home_location": "the home location",
    "alert_acknowledgements": "alert acknowledgements",
    "alert_suppressions": "alert suppressions",
    "report_schedules": "report schedules",
}
# The ConfigBackup path each section comes from, for the log
SECTION_FILES = {
    "capture_mode_config": "capture_config",
    "storage_retention": "retention_config",
    "notification_channels": "notification_config",
    "notification_rules": "notification_config",
    "notification_quiet": "notification_config",
    "excluded_ips": "excluded_ips",
    "bandwidth_cap": "bandwidth_cap",
    "home_location": "home_location",
    "alert_acknowledgements": "alert_acks",
    "alert_suppressions": "suppressions",
}


def capture_section(section: Any) -> dict:
    """A capture section reduced to its mode and the fields that mode uses; {} if no valid mode."""
    if (
        not isinstance(section, dict)
        or section.get("capture_mode") not in CAPTURE_FIELDS
    ):
        return {}
    mode = section["capture_mode"]
    return {"capture_mode": mode, **{f: section.get(f) for f in CAPTURE_FIELDS[mode]}}


def _timestamp_ok(value: Any) -> bool:
    """An ISO time with a zone: a naive expiry never expires (_is_entry_expired)."""
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _suppress_entry_ok(entry: Any) -> bool:
    sid = entry.get("signature_id") if isinstance(entry, dict) else None
    return (
        isinstance(sid, int)
        and not isinstance(sid, bool)
        # OLD CODE: and isinstance(entry.get("reason", ""), str)
        # (NET-344: older backups carry "reason": null, which the suppress API stored as sent)
        and isinstance(entry.get("reason", ""), (str, type(None)))
        and all(_timestamp_ok(entry[k]) for k in _SUPPRESS_TIMES if k in entry)
    )


def suppressions_ok(data: Any) -> bool:
    """The whole suppress-list shape alert_intelligence reads, so a restore can't break it."""
    if not isinstance(data, dict):
        return False
    lists = [data.get("global", []), data.get("false_positives", [])]
    per_device = data.get("per_device", {})
    if not isinstance(per_device, dict):
        return False
    lists += list(per_device.values())
    return all(
        isinstance(entries, list) and all(_suppress_entry_ok(e) for e in entries)
        for entries in lists
    )


def labels(sections: Iterable[str]) -> str:
    return ", ".join(LABELS.get(name, name) for name in sections)


class BackupRefused(Exception):
    """A section this NetTap holds wouldn't restore, so no file is offered (plan §2.3 step 6).
    ``code``: "legacy_excluded_ips" (the owner can fix it) or "invalid_section"."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def invalid(sections: list[str]) -> BackupRefused:
    return BackupRefused(
        "invalid_section",
        f"No backup was made: {labels(sections)} on this NetTap can't be restored as "
        "stored. The daemon log has the details.",
    )


def _capture_errors(raw: Any) -> list[str]:
    """api/backup.py restores it through setup's _build_capture_config: these are its checks."""
    if not raw:
        return []  # a backup from before the capture mode was backed up: skipped
    wanted = capture_section(raw)
    if not wanted:
        return ["Capture mode not restored: this backup's mode isn't valid"]
    try:
        for field in CAPTURE_FIELDS[wanted["capture_mode"]]:
            value = wanted[field]
            if field == "dhcp_subnet":
                validate_subnet(CaptureConfig().dhcp_subnet if value is None else value)
            elif value or field != "management_interface":
                validate_interface_name(value)
    except (TypeError, ValueError) as exc:
        return [f"Capture mode not restored: {exc}"]
    return []


def _retention_errors(values: Any) -> list[str]:
    """POST /api/storage/config's checks, which api/backup.py restores it through."""
    if not values:
        return []  # a backup from before retention was backed up: skipped
    if not isinstance(values, dict):
        return ["Retention settings not restored: not a JSON object"]
    try:
        # save()'s own checks; a manager that has read nothing merges onto the defaults (the
        # restore merges onto the box's saved settings, so a partial section can still differ)
        RetentionConfigManager(config_path="").checked_merge(values)
    except (AttributeError, TypeError, ValueError) as exc:
        return [f"Retention settings not restored: {exc}"]
    return []


def _is_range(entry: Any) -> bool:
    """A CIDR range, as Settings kept before it took single IPs only."""
    if not isinstance(entry, str) or "/" not in entry:
        return False
    try:
        ipaddress.ip_network(entry.strip(), strict=False)
    except ValueError:
        return False
    return True


def _excluded_findings(raw: list) -> tuple[list[str], list[str], list[Any], int]:
    """(ranges, other text that isn't one IP, entries that aren't text, distinct single IPs).

    Settings saved any text before 7c1f7a99 (2026-10-29), so ranges and text such as
    printer.local are the owner's own entries; something that isn't text no API wrote.
    """
    ranges: list[str] = []
    words: list[str] = []
    other: list[Any] = []
    ips: set[str] = set()
    for entry in raw:
        ip = parse_single_ip(entry)
        if ip is not None:
            ips.add(ip)
        elif _is_range(entry):
            ranges.append(entry.strip())
        elif isinstance(entry, str):
            words.append(entry.strip())
        else:
            other.append(entry)
    return ranges, words, other, len(ips)


def _shown(text: str) -> str:
    """Owner text in a one-line message: printable characters, 64 at most."""
    clean = "".join(c if c.isprintable() else "?" for c in text)
    return clean if len(clean) <= 64 else clean[:63] + "…"


def excluded_ip_errors(raw: Any) -> list[str]:
    """Single IPs only, as the Settings PUT keeps them, and at most EXCLUDED_IPS_MAX."""
    if not isinstance(raw, list):
        return [
            "Excluded IPs not restored: this backup's copy isn't a list of IP addresses"
        ]
    ranges, words, other, count = _excluded_findings(raw)
    errors = []
    if ranges or words or other:
        first = str((ranges or words or other)[0])[:64]
        errors.append(
            "Excluded IPs not restored: each must be a single IP address, "
            f"and {first!r} isn't"
        )
    if count > EXCLUDED_IPS_MAX:
        errors.append(
            f"Excluded IPs not restored: up to {EXCLUDED_IPS_MAX:,}, "
            f"and this backup has {count:,}"
        )
    return errors


def cap_errors(cap: Any) -> list[str]:
    """As _restore_bandwidth_cap checks it; {} (a box that never set one) is skipped."""
    if cap == {}:
        return []
    value = cap.get("monthly_cap_bytes") if isinstance(cap, dict) else None
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= MAX_MONTHLY_CAP_BYTES
    ):
        return []
    return ["Bandwidth cap not restored: this backup's copy isn't valid"]


def _home_errors(home: Any) -> list[str]:
    if home is None:
        return []  # no location in this backup: skipped
    try:
        parse_home(home)
    except ValueError as exc:
        return [f"Home location not restored: {exc}"]
    return []


def ack_errors(acks: Any) -> list[str]:
    if isinstance(acks, dict) and all(isinstance(v, dict) for v in acks.values()):
        return []
    return ["Alert acknowledgements not restored: this backup's copy isn't valid"]


def _suppression_errors(data: Any) -> list[str]:
    if suppressions_ok(data):
        return []
    return ["Alert suppressions not restored: this backup's copy isn't valid"]


def _joined(problems: list[str]) -> list[str]:
    """DeviceCustomStore.restore's message, worded by the same function."""
    if not problems:
        return []
    return [f"Device names and pictures not restored: {restore_message(problems)}"]


def _device_errors(sections: dict) -> dict[str, list[str]]:
    """Names and pictures restore together; names alone (from before NET-200) are skipped."""
    if "device_pictures" not in sections:
        return {}
    names, pictures = restore_problems(
        sections.get("device_aliases"), sections["device_pictures"]
    )
    return {"device_aliases": _joined(names), "device_pictures": _joined(pictures)}


def _details_errors(section: Any) -> list[str]:
    """DeviceDetailsStore.restore's reasons, with the restore's own prefix (backup_devices)."""
    return [
        f"Device details not restored: {reason}" for reason in details_problems(section)
    ]


_SECTION_CHECKS = {
    "capture_mode_config": _capture_errors,
    "storage_retention": _retention_errors,
    "excluded_ips": excluded_ip_errors,
    "bandwidth_cap": cap_errors,
    "home_location": _home_errors,
    "alert_acknowledgements": ack_errors,
    "alert_suppressions": _suppression_errors,
    # NET-320: worded as the restore words them, "Device details not restored: …"
    "device_details": _details_errors,
    # NET-340: worded as the restore words them, "Report schedules not restored: …"
    "report_schedules": report_schedule_problems,
}


def section_errors(sections: dict) -> dict[str, list[str]]:
    """Every content problem restoring these sections would hit, by section; {} when none.

    Side-effect free, and the one check validate, import and export share (plan §2.4), so a
    content failure applies nothing. What depends on the box (a write, a capture restart, the
    device cap) is still found while applying, and reported then.
    """
    found = {
        name: check(sections[name])
        for name, check in _SECTION_CHECKS.items()
        if name in sections
    }
    for name, problem in backup_problems(sections).items():
        # quiet hours' reason stands alone, as NET-330's preflight gave it
        found[name] = [
            problem
            if name == "notification_quiet"
            else f"Notifications not restored: {problem}"
        ]
    found.update(_device_errors(sections))
    return {name: reasons for name, reasons in found.items() if reasons}


def left_out_check(metadata: dict, sections: dict) -> tuple[str | None, str | None]:
    """(error, warning) for metadata.acknowledgements_left_out; absent means 0 (plan §2.4)."""
    left = metadata.get(LEFT_OUT, 0)
    if not isinstance(left, int) or isinstance(left, bool) or left < 0:
        return (
            "The backup's count of left-out acknowledgements isn't a whole number",
            None,
        )
    if left == 0:
        return None, None
    acks = sections.get(ACKS)
    if not isinstance(acks, dict):
        return "The backup says it leaves out acknowledgements but carries none", None
    noun = "acknowledgement" if left == 1 else "acknowledgements"
    return None, (
        f"This backup leaves out {left:,} alert {noun}. Restoring replaces this NetTap's "
        f"acknowledgements with the {len(acks):,} it carries."
    )


def _legacy_message(raw: list) -> str:
    """The 422 for an excluded-IP list an older NetTap allowed (plan §2.3 step 6)."""
    ranges, words, _, count = _excluded_findings(raw)
    parts = []
    if len(ranges) == 1:
        parts.append(
            f"Excluded IPs: {ranges[0]} is a range. NetTap no longer keeps ranges, so it "
            "can't restore this one. Remove it in Settings › Network, then export again. "
            "Live Connections and Top Destinations stop hiding that range once it's removed."
        )
    elif ranges:
        parts.append(
            f"Excluded IPs: {ranges[0]} and {len(ranges) - 1:,} more are ranges. NetTap no "
            "longer keeps ranges, so it can't restore them. Remove them in Settings › Network, "
            "then export again. Live Connections and Top Destinations stop hiding those "
            "ranges once they're removed."
        )
    if len(words) == 1:
        parts.append(
            f"Excluded IPs: {_shown(words[0])} isn't a single IP address. Remove it in "
            "Settings › Network, then export again."
        )
    elif words:
        parts.append(
            f"Excluded IPs: {_shown(words[0])} and {len(words) - 1:,} more aren't single IP "
            "addresses. Remove them in Settings › Network, then export again."
        )
    if count > EXCLUDED_IPS_MAX:
        parts.append(
            f"Excluded IPs: there are {count:,}, and NetTap restores up to "
            f"{EXCLUDED_IPS_MAX:,}. Remove {count - EXCLUDED_IPS_MAX:,} in Settings › Network, "
            "then export again."
        )
    return " ".join(parts)


def refusal(errors: dict[str, list[str]], sections: dict) -> BackupRefused:
    """legacy_excluded_ips when the only problem is excluded IPs an older NetTap kept: text
    that isn't one IP (ranges included), or too many; invalid_section for anything else."""
    raw = sections.get("excluded_ips")
    if set(errors) == {"excluded_ips"} and isinstance(raw, list):
        if not _excluded_findings(raw)[2]:
            return BackupRefused("legacy_excluded_ips", _legacy_message(raw))
    return invalid(list(errors))


def first_bad_entry(section: str, data: Any) -> str:
    """Where acknowledgements or suppressions fail the restore check, for the log."""
    if section == ACKS and isinstance(data, dict):
        bad = next((k for k, v in data.items() if not isinstance(v, dict)), None)
        return "" if bad is None else f" (first bad entry {str(bad)[:64]!r})"
    if section != "alert_suppressions" or not isinstance(data, dict):
        return ""
    per_device = data.get("per_device", {})
    lists = [
        ("global", data.get("global", [])),
        ("false_positives", data.get("false_positives", [])),
    ]
    lists += (
        [(f"per_device[{str(ip)[:64]!r}]", v) for ip, v in per_device.items()]
        if isinstance(per_device, dict)
        else [("per_device", per_device)]
    )
    for where, entries in lists:
        if not isinstance(entries, list):
            return f" ({where} isn't a list)"
        bad = next(
            (i for i, e in enumerate(entries) if not _suppress_entry_ok(e)), None
        )
        if bad is not None:
            return f" (first bad entry {where}[{bad}])"
    return ""
