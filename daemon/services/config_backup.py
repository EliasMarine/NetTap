"""
NetTap ConfigBackup — Export/import all NetTap settings.

Gathers capture mode config, storage retention, notification channels (without
their secrets), notification rules, device names and pictures, excluded IPs,
bandwidth cap, home location, alert acknowledgements and suppressions into a
single JSON-serializable dict. Includes version stamp for compatibility checking.

Never exported: the .env (API keys, SMTP password), the daemon token, UniFi and
ET Pro credentials, and notification passwords, URLs and tokens (A9).

The capture mode and the retention settings need the running daemon to apply,
so ``api/backup.py`` restores those two; ``import_config`` does the rest.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services import alert_intelligence

# OLD CODE: from services.backup_notifications import redact_channels, restore_channels (NET-224: the hub restores)
from services.backup_notifications import redact_channels
from services.capture_config import load_capture_config, write_file_atomic
from services.excluded_ips import parse_single_ip
from services.home_location import load_home, parse_home, save_home

logger = logging.getLogger("nettap.services.config_backup")

# Current config schema version
# OLD CODE: _SCHEMA_VERSION = 1 (A9: notification channels lost their secrets, so an older
# daemon, which replaces them whole, must refuse these files)
_SCHEMA_VERSION = 2

# NetTap version for compatibility
_NETTAP_VERSION = os.environ.get("NETTAP_VERSION", "0.4.0")

# Config file locations (defaults)
_DEFAULT_PATHS = {
    "notification_config": os.environ.get(
        "NOTIFICATION_CONFIG", "/opt/nettap/data/notifications.json"
    ),
    "device_baseline": os.environ.get(
        "DEVICE_BASELINE_FILE", "/opt/nettap/data/device_baseline.json"
    ),
    "excluded_ips": os.environ.get(
        "EXCLUDED_IPS_FILE", "/opt/nettap/data/excluded_ips.json"
    ),
    "env_file": os.environ.get("NETTAP_ENV_FILE", "/opt/nettap/data/.env"),
    "bandwidth_cap": os.environ.get(
        "BANDWIDTH_CAP_FILE", "/opt/nettap/data/bandwidth_cap.json"
    ),
    # OLD CODE START — A9: neither file exists; the daemon uses the two below, so a backup
    # skipped capture mode and retention and still said "Import successful"
    # "capture_config": os.environ.get(
    #     "CAPTURE_CONFIG_FILE", "/opt/nettap/data/capture_config.json"
    # ),
    # "retention_config": os.environ.get(
    #     "RETENTION_CONFIG_FILE", "/opt/nettap/data/retention_config.json"
    # ),
    # OLD CODE END
    "capture_config": os.environ.get(
        "CAPTURE_CONFIG_PATH", "/etc/nettap/capture-mode.conf"
    ),
    "retention_config": os.environ.get(
        "RETENTION_CONFIG_PATH", "/opt/nettap/data/retention.json"
    ),
    "home_location": os.environ.get(
        "HOME_LOCATION_FILE", "/opt/nettap/data/home_location.json"
    ),
    "alert_acks": os.environ.get("ALERT_ACK_FILE", "/opt/nettap/data/alert_acks.json"),
    "suppressions": str(alert_intelligence._SUPPRESS_PATH),
}

# The fields each capture mode uses, as POST /api/setup/configure takes them
CAPTURE_FIELDS = {
    "bridge": ("wan_interface", "lan_interface"),
    "mirror": ("capture_interface", "management_interface"),
    "dhcp_gateway": ("capture_interface", "dhcp_subnet"),
}
_SUPPRESS_TIMES = ("expires_at", "suppressed_at", "marked_at")

# Sections that are exported/imported
_VALID_SECTIONS = {
    "capture_mode_config",
    "storage_retention",
    "notification_channels",
    "notification_rules",
    "device_aliases",
    # NET-200: the owner's device icons and photos ({MAC: {"icon"} | {"image": data URL}})
    "device_pictures",
    "excluded_ips",
    "bandwidth_cap",
    # A9: the rest of the owner's own settings in /opt/nettap/data
    "home_location",
    "alert_acknowledgements",
    "alert_suppressions",
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
        and isinstance(entry.get("reason", ""), str)
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


class ConfigBackup:
    """Export/import all NetTap configuration settings."""

    # OLD CODE START — NET-200: device names come from the DeviceCustomStore now
    # def __init__(self, config_paths: dict[str, str] | None = None) -> None:
    #     self._paths = {**_DEFAULT_PATHS, **(config_paths or {})}
    # OLD CODE END
    # OLD CODE START — NET-224: notifications are restored through the running hub
    # def __init__(
    #     self, config_paths: dict[str, str] | None = None, device_custom: Any = None
    # ) -> None:
    #     self._paths = {**_DEFAULT_PATHS, **(config_paths or {})}
    #     # DeviceCustomStore: the owner's device names, icons and photos (NET-200)
    #     self._device_custom = device_custom
    # OLD CODE END
    def __init__(
        self,
        config_paths: dict[str, str] | None = None,
        device_custom: Any = None,
        notification_hub: Any = None,
    ) -> None:
        self._paths = {**_DEFAULT_PATHS, **(config_paths or {})}
        # DeviceCustomStore: the owner's device names, icons and photos (NET-200)
        self._device_custom = device_custom
        # NotificationHub: a restore goes through it, so it is live at once and validated
        self._notification_hub = notification_hub

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_config(self) -> dict[str, Any]:
        """Gather all settings into a single dict for backup.

        Returns a dict with metadata (version, timestamp, schema_version)
        and all configuration sections.
        """
        config: dict[str, Any] = {
            "metadata": {
                "nettap_version": _NETTAP_VERSION,
                "schema_version": _SCHEMA_VERSION,
                "exported_at": datetime.now(timezone.utc).isoformat(),
            },
            "sections": {},
        }

        # OLD CODE START — A9: read files that don't exist (always {}), and exported every
        # notification password, token and webhook URL
        # # Capture mode config
        # config["sections"]["capture_mode_config"] = self._read_json(
        #     self._paths.get("capture_config", ""), default={}
        # )
        #
        # # Storage retention
        # config["sections"]["storage_retention"] = self._read_json(
        #     self._paths.get("retention_config", ""), default={}
        # )
        #
        # # Notification channels + rules
        # notif_data = self._read_json(
        #     self._paths.get("notification_config", ""), default={}
        # )
        # config["sections"]["notification_channels"] = notif_data.get("channels", {})
        # config["sections"]["notification_rules"] = notif_data.get("rules", {})
        # OLD CODE END
        config["sections"]["capture_mode_config"] = self.current_capture()

        # Retention days and thresholds, not the ILM status beside them
        retention = self._read_json(self._paths.get("retention_config", ""), default={})
        config["sections"]["storage_retention"] = {
            k: retention[k]
            for k in ("retention", "thresholds")
            if isinstance(retention, dict) and k in retention
        }

        # Notification channels without their secrets (re-entered after a restore) + rules
        notif_data = self._read_json(
            self._paths.get("notification_config", ""), default={}
        )
        notif_data = notif_data if isinstance(notif_data, dict) else {}
        config["sections"]["notification_channels"] = redact_channels(
            notif_data.get("channels", {})
        )
        config["sections"]["notification_rules"] = notif_data.get("rules", {})

        # OLD CODE START — NET-200: device_baseline.json is a flat {MAC: info} map with no
        # "aliases" key, so this always exported {} (and its import planted an "aliases" MAC)
        # # Device aliases (from baseline file)
        # baseline = self._read_json(self._paths.get("device_baseline", ""), default={})
        # config["sections"]["device_aliases"] = baseline.get("aliases", {})
        # OLD CODE END
        # The owner's names and pictures; an unreadable store or a missing photo raises, so
        # the export fails rather than hand back a backup without them
        if self._device_custom is not None:
            names, pictures = self._device_custom.export()
            config["sections"]["device_aliases"] = names
            config["sections"]["device_pictures"] = pictures

        # Excluded IPs
        config["sections"]["excluded_ips"] = self._read_json(
            self._paths.get("excluded_ips", ""), default=[]
        )

        # Bandwidth cap
        config["sections"]["bandwidth_cap"] = self._read_json(
            self._paths.get("bandwidth_cap", ""), default={}
        )

        # A9: None when no location was ever set
        config["sections"]["home_location"] = load_home(self._paths["home_location"])
        config["sections"]["alert_acknowledgements"] = self._read_json(
            self._paths["alert_acks"], default={}
        )
        # Suppressions and false-positive marks
        config["sections"]["alert_suppressions"] = self._read_json(
            self._paths["suppressions"],
            default={"global": [], "per_device": {}, "false_positives": []},
        )

        logger.info("Exported config with %d sections", len(config["sections"]))
        return config

    def current_capture(self) -> dict:
        """The box's capture mode as a backup section; {} before setup has saved one."""
        path = self._paths.get("capture_config", "")
        if not path or not os.path.exists(path):
            return {}
        cfg = load_capture_config(path)
        return capture_section(
            {
                "capture_mode": cfg.mode.value,
                "capture_interface": cfg.interface,
                "management_interface": cfg.management,
                "wan_interface": cfg.wan_interface,
                "lan_interface": cfg.lan_interface,
                "dhcp_subnet": cfg.dhcp_subnet,
            }
        )

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def validate_import(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate import data for version compatibility and schema.

        Returns a validation result with is_valid, warnings, errors,
        and a preview of what will be imported.
        """
        result: dict[str, Any] = {
            "is_valid": True,
            "warnings": [],
            "errors": [],
            "preview": {},
            "capture_restart": False,
        }

        # Check top-level structure
        if not isinstance(data, dict):
            result["is_valid"] = False
            result["errors"].append("Import data must be a JSON object")
            return result

        metadata = data.get("metadata", {})
        sections = data.get("sections", {})

        if not isinstance(metadata, dict):
            result["is_valid"] = False
            result["errors"].append("Missing or invalid 'metadata' field")
            return result

        if not isinstance(sections, dict):
            result["is_valid"] = False
            result["errors"].append("Missing or invalid 'sections' field")
            return result

        # Check schema version
        schema_version = metadata.get("schema_version", 0)
        if schema_version > _SCHEMA_VERSION:
            result["is_valid"] = False
            result["errors"].append(
                f"Schema version {schema_version} is newer than supported "
                f"version {_SCHEMA_VERSION}. Update NetTap first."
            )
            return result

        # Check NetTap version compatibility
        export_version = metadata.get("nettap_version", "unknown")
        if export_version != _NETTAP_VERSION:
            result["warnings"].append(
                f"Config was exported from version {export_version}, "
                f"current version is {_NETTAP_VERSION}. "
                f"Some settings may not apply."
            )

        # Validate sections
        for section_name, section_data in sections.items():
            if section_name not in _VALID_SECTIONS:
                result["warnings"].append(
                    f"Unknown section '{section_name}' will be skipped"
                )
            else:
                result["preview"][section_name] = {
                    "type": type(section_data).__name__,
                    "size": (
                        len(section_data)
                        if isinstance(section_data, (dict, list))
                        else 1
                    ),
                }

        if not sections:
            result["warnings"].append("No sections found in import data")

        # A9: restoring a different capture mode restarts capture, so the page asks first
        capture = capture_section(sections.get("capture_mode_config"))
        result["capture_restart"] = bool(capture) and capture != self.current_capture()

        return result

    def import_config(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate and apply settings from import data.

        Returns a result dict with applied sections and any errors.
        """
        validation = self.validate_import(data)
        if not validation["is_valid"]:
            return {
                "success": False,
                "errors": validation["errors"],
                "applied": [],
                "skipped": [],
                "warnings": [],
            }

        sections = data.get("sections", {})
        applied = []
        errors = []

        # OLD CODE START — A9: wrote files the daemon never reads (capture_config.json,
        # retention_config.json) and reported them applied; notification channels were replaced
        # whole. Capture mode and retention are restored by api/backup.py now.
        # # Apply capture mode config
        # if "capture_mode_config" in sections:
        #     ok = self._write_json(
        #         self._paths.get("capture_config", ""),
        #         sections["capture_mode_config"],
        #     )
        #     if ok:
        #         applied.append("capture_mode_config")
        #     else:
        #         errors.append("Failed to write capture_mode_config")
        #
        # # Apply storage retention
        # if "storage_retention" in sections:
        #     ok = self._write_json(
        #         self._paths.get("retention_config", ""),
        #         sections["storage_retention"],
        #     )
        #     if ok:
        #         applied.append("storage_retention")
        #     else:
        #         errors.append("Failed to write storage_retention")
        #
        # # Apply notification channels + rules
        # if "notification_channels" in sections or "notification_rules" in sections:
        #     existing = self._read_json(
        #         self._paths.get("notification_config", ""), default={}, lenient=True
        #     )
        #     if "notification_channels" in sections:
        #         existing["channels"] = sections["notification_channels"]
        #     if "notification_rules" in sections:
        #         existing["rules"] = sections["notification_rules"]
        #     ok = self._write_json(self._paths.get("notification_config", ""), existing)
        #     if ok:
        #         applied.extend(
        #             s
        #             for s in ["notification_channels", "notification_rules"]
        #             if s in sections
        #         )
        #     else:
        #         errors.append("Failed to write notification config")
        # OLD CODE END
        skipped: list[dict[str, str]] = []
        notes: list[str] = []
        self._restore_notifications(sections, applied, errors, notes)

        # OLD CODE START — NET-200: wrote an "aliases" key into the flat baseline map
        # # Apply device aliases
        # if "device_aliases" in sections:
        #     existing = self._read_json(
        #         self._paths.get("device_baseline", ""), default={}, lenient=True
        #     )
        #     existing["aliases"] = sections["device_aliases"]
        #     ok = self._write_json(self._paths.get("device_baseline", ""), existing)
        #     if ok:
        #         applied.append("device_aliases")
        #     else:
        #         errors.append("Failed to write device_aliases")
        # OLD CODE END
        # Device names and pictures: each present section replaces the owner's set, all or nothing
        device_parts = [
            s for s in ("device_aliases", "device_pictures") if s in sections
        ]
        device_names = sections.get("device_aliases")
        # OLD CODE: notes: list[str] = [] (A9: created above, the notification notes go first)
        if "device_aliases" in sections and "device_pictures" not in sections:
            # A backup from before NET-200: its device_aliases came from the dead baseline
            # code and is always {}, so replacing with it would wipe every owner's name
            device_parts.remove("device_aliases")
            device_names = None
            notes.append(
                "This backup was made before device names could be backed up; "
                "the current device names are kept."
            )
        if device_parts and self._device_custom is None:
            errors.append("Device names and pictures can't be restored here")
        elif device_parts:
            try:
                self._device_custom.restore(
                    device_names, sections.get("device_pictures")
                )
                applied.extend(device_parts)
            # TypeError too: a malformed backup must never escape after other sections applied
            except (ValueError, TypeError, RuntimeError, OSError) as exc:
                logger.error("Device names and pictures not restored: %s", exc)
                errors.append(f"Device names and pictures not restored: {exc}")

        # OLD CODE START — A9: any JSON was written, CIDRs and junk included (the Settings
        # form refuses them), and the running daemon kept its old list
        # # Apply excluded IPs
        # if "excluded_ips" in sections:
        #     ok = self._write_json(
        #         self._paths.get("excluded_ips", ""),
        #         sections["excluded_ips"],
        #     )
        #     if ok:
        #         applied.append("excluded_ips")
        #     else:
        #         errors.append("Failed to write excluded_ips")
        # OLD CODE END
        if "excluded_ips" in sections:
            raw = sections["excluded_ips"]
            ips = (
                [parse_single_ip(ip) for ip in raw] if isinstance(raw, list) else [None]
            )
            if None in ips:
                errors.append(
                    "Excluded IPs not restored: each must be a single IP address"
                )
            elif self._write_json(self._paths.get("excluded_ips", ""), ips):
                applied.append("excluded_ips")
            else:
                errors.append("Failed to write excluded_ips")

        # Apply bandwidth cap
        if "bandwidth_cap" in sections:
            ok = self._write_json(
                self._paths.get("bandwidth_cap", ""),
                sections["bandwidth_cap"],
            )
            if ok:
                applied.append("bandwidth_cap")
            else:
                errors.append("Failed to write bandwidth_cap")

        self._restore_owner_files(sections, applied, skipped, errors)

        logger.info(
            "Imported config: %d sections applied, %d skipped, %d errors",
            len(applied),
            len(skipped),
            len(errors),
        )

        return {
            "success": len(errors) == 0,
            "applied": applied,
            # A9: what wasn't restored, and why
            "skipped": skipped,
            "errors": errors,
            # OLD CODE: "warnings": validation.get("warnings", []), (NET-200: plus the device notes)
            "warnings": [*validation.get("warnings", []), *notes],
        }

    # OLD CODE START — NET-224: wrote the file from this worker thread while the running hub kept
    # its own copy (a Settings save in between put the old config back), stored a channel with no
    # id or an unknown type (the dispatcher then raised every minute); api/backup.py reloaded it
    # def _restore_notifications(
    #     self, sections: dict, applied: list, errors: list, notes: list
    # ) -> None:
    #     """Channels with the box's own secrets where safe (backup_notifications), then rules."""
    #     present = [
    #         s for s in ("notification_channels", "notification_rules") if s in sections
    #     ]
    #     if not present:
    #         return
    #     path = self._paths.get("notification_config", "")
    #     existing = self._read_json(path, default={}, lenient=True)
    #     existing = existing if isinstance(existing, dict) else {}
    #     channels, rules = existing.get("channels", {}), existing.get("rules", {})
    #     try:
    #         if "notification_channels" in sections:
    #             channels, warnings = restore_channels(
    #                 sections["notification_channels"], channels, self._smtp_host_set()
    #             )
    #             notes.extend(warnings)
    #         if "notification_rules" in sections:
    #             rules = sections["notification_rules"]
    #             if not isinstance(rules, dict) or not all(
    #                 isinstance(r, dict) for r in rules.values()
    #             ):
    #                 raise ValueError("Notification rules in this backup aren't valid")
    #         # 600: the file holds the SMTP password and tokens (NET-224)
    #         self._write_atomic(path, {"channels": channels, "rules": rules}, mode=0o600)
    #         applied.extend(present)
    #     except (ValueError, OSError) as exc:
    #         errors.append(f"Notifications not restored: {exc}")
    #
    # def _smtp_host_set(self) -> bool:
    #     """Settings › API keys has an SMTP server (the data .env, else the environment)."""
    #     from api.settings import _load_env_file  # api imports services, not the reverse
    #
    #     env_file = self._paths.get("env_file", "")
    #     saved = _load_env_file(env_file) if env_file else {}
    #     return bool((saved.get("SMTP_HOST") or os.environ.get("SMTP_HOST", "")).strip())
    # OLD CODE END
    def _restore_notifications(
        self, sections: dict, applied: list, errors: list, notes: list
    ) -> None:
        """Channels (the box's own secrets where safe) and rules, through the running hub."""
        present = [
            s for s in ("notification_channels", "notification_rules") if s in sections
        ]
        if not present:
            return
        if self._notification_hub is None:
            errors.append("Notification settings can't be restored here")
            return
        try:
            notes.extend(self._notification_hub.restore_backup(sections))
            applied.extend(present)
        except (ValueError, OSError) as exc:
            errors.append(f"Notifications not restored: {exc}")

    def _restore_owner_files(
        self, sections: dict, applied: list, skipped: list, errors: list
    ) -> None:
        """A9: home location, alert acknowledgements and suppressions, each checked first."""
        if "home_location" in sections:
            home = sections["home_location"]
            if home is None:
                skipped.append(
                    {"section": "home_location", "reason": "No location in this backup"}
                )
            else:
                try:
                    save_home(parse_home(home), self._paths["home_location"])
                    applied.append("home_location")
                except (ValueError, OSError) as exc:
                    errors.append(f"Home location not restored: {exc}")

        checks = {
            "alert_acknowledgements": (
                "alert_acks",
                "Alert acknowledgements",
                lambda d: (
                    isinstance(d, dict) and all(isinstance(v, dict) for v in d.values())
                ),
            ),
            "alert_suppressions": (
                "suppressions",
                "Alert suppressions",
                suppressions_ok,
            ),
        }
        for section, (path_key, name, valid) in checks.items():
            if section not in sections:
                continue
            if not valid(sections[section]):
                errors.append(f"{name} not restored: this backup's copy isn't valid")
                continue
            try:
                self._write_atomic(self._paths[path_key], sections[section])
                applied.append(section)
            except OSError as exc:
                errors.append(f"{name} not restored: {exc}")

    # ------------------------------------------------------------------
    # File I/O helpers
    # ------------------------------------------------------------------

    def _read_json(self, path: str, default: Any = None, lenient: bool = False) -> Any:
        """Read a JSON file; default when it isn't there yet.

        A file that exists but can't be read raises, unless ``lenient`` (an
        import about to overwrite it), so an export never drops it silently.
        """
        if not path:
            return default
        p = Path(path)
        if not p.exists():
            return default
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            # OLD CODE START — #96: the export left the section empty and still "succeeded"
            # return default
            # OLD CODE END
            if lenient:
                return default
            raise ValueError(f"Could not read {path}: {exc}") from exc

    @staticmethod
    def _write_atomic(path: str, data: Any, mode: int = 0o644) -> None:
        """Write JSON atomically (readers in other threads never see half a file); raises OSError."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        write_file_atomic(path, json.dumps(data, indent=2), mode=mode)

    def _write_json(self, path: str, data: Any) -> bool:
        """Write data as JSON to a file. Returns True on success."""
        if not path:
            return False
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, indent=2, default=str))
            return True
        except OSError as exc:
            logger.error("Failed to write %s: %s", path, exc)
            return False
