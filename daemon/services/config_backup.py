"""
NetTap ConfigBackup — Export/import all NetTap settings.

Gathers capture mode config, storage retention, notification channels (without
their secrets), notification rules and quiet hours, device names, pictures and details, excluded IPs,
bandwidth cap, home location, alert acknowledgements and suppressions into a
single JSON-serializable dict. Includes version stamp for compatibility checking.

Never exported: the .env (API keys, SMTP password), the daemon token, UniFi and
ET Pro credentials, and notification passwords, URLs and tokens (A9).

The capture mode and the retention settings need the running daemon to apply,
so ``api/backup.py`` restores those two; ``import_config`` does the rest.

NET-344: a download is ``fit``'s bytes, under the restore limit (the oldest alert
acknowledgements are left out first; owner settings never are), and validate, import and
export share one side-effect-free content check, ``section_errors``.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services import alert_intelligence, owner_tz, quiet_hours
from services.backup_devices import restore_devices

# NET-344: the encoding and the content check live in their own modules; their public names are
# re-exported here (`as` marks a re-export), so callers keep importing from config_backup
from services.backup_checks import (
    CAPTURE_FIELDS as CAPTURE_FIELDS,
    LEFT_OUT as LEFT_OUT,
    BackupRefused as BackupRefused,
    SECTION_FILES,
    ack_errors,
    cap_errors,
    excluded_ip_errors,
    first_bad_entry,
    left_out_check,
    refusal,
    capture_section,
    section_errors,
    suppressions_ok,
)
from services.backup_fit import (
    RESTORE_LIMIT_BYTES as RESTORE_LIMIT_BYTES,
    BackupTooLarge as BackupTooLarge,
    encode as encode,
    encode_exact,
    fit,
)

# OLD CODE: from services.backup_notifications import redact_channels, restore_channels (NET-224: the hub restores)
from services.backup_notifications import redact_channels
from services.capture_config import load_capture_config, write_file_atomic
from services.excluded_ips import parse_single_ip
from services.home_location import load_home, parse_home, save_home
from services.report_generator import restore_report_schedules

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
    # NET-330: quiet hours, with the owner's zone they were set in ({..., "tz"})
    "notification_quiet",
    # NET-320: watch time, group, owner and notes ({MAC: entry})
    "device_details",
    # NET-340: report schedules with their weekday, hour and card; restored paused
    "report_schedules",
}

DETAILS_UNREADABLE = (
    "Device details on this NetTap are unreadable; fix that before restoring them."
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
    # OLD CODE: def __init__(self, config_paths=None, device_custom=None, notification_hub=None)
    # (NET-320: plus the device details store)
    # OLD CODE: (..., device_details: Any = None) (NET-340: plus the report generator)
    def __init__(
        self,
        config_paths: dict[str, str] | None = None,
        device_custom: Any = None,
        notification_hub: Any = None,
        device_details: Any = None,
        report_generator: Any = None,
    ) -> None:
        self._paths = {**_DEFAULT_PATHS, **(config_paths or {})}
        # DeviceCustomStore: the owner's device names, icons and photos (NET-200)
        self._device_custom = device_custom
        # NotificationHub: a restore goes through it, so it is live at once and validated
        self._notification_hub = notification_hub
        # DeviceDetailsStore: watch time, group, owner and notes (NET-320)
        self._device_details = device_details
        # ReportGenerator: report schedules, through its lock (NET-340)
        self._report_generator = report_generator

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
        if self._notification_hub is not None:
            # NET-344: what the box runs and a restore reproduces; the file can still hold a
            # channel the hub skipped at load, and then no backup would ever be offered
            notif_data = self._notification_hub.backup_state()
        else:
            notif_data = self._read_json(
                self._paths.get("notification_config", ""), default={}
            )
            notif_data = notif_data if isinstance(notif_data, dict) else {}
        config["sections"]["notification_channels"] = redact_channels(
            notif_data.get("channels", {})
        )
        config["sections"]["notification_rules"] = notif_data.get("rules", {})
        # NET-330: as this version accepts them (a hand-broken value as the default), and the zone
        # they are read in, so a restore on a box in another zone can say so
        config["sections"]["notification_quiet"] = {
            **quiet_hours.of(notif_data.get("quiet")),
            "tz": owner_tz.read()["tz"],
        }

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
        # NET-320: a damaged details file raises StoreUnavailable too, for the same reason
        if self._device_details is not None:
            config["sections"]["device_details"] = self._device_details.export()
        # NET-340: an unreadable schedule store raises, so the export fails rather than drop it
        if self._report_generator is not None:
            config["sections"]["report_schedules"] = (
                self._report_generator.export_backup()
            )

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

    def export_file(self) -> tuple[bytearray, int]:
        """NET-344: the download's bytes and the acknowledgements it leaves out (fit), checked as
        a restore checks it, so no file is offered that wouldn't restore (plan §2.3 steps 5-6).

        Raises BackupTooLarge (413) or BackupRefused (422); anything else is a failed export.
        """
        fitted, size, left_out = fit(self.export_config())
        sections = fitted["sections"]
        errors = section_errors(sections)
        if errors:
            for name, reasons in errors.items():
                logger.error(
                    "Backup refused: %s in %s can't be restored: %s%s",
                    name,
                    self._paths.get(SECTION_FILES.get(name, ""), "the device store"),
                    "; ".join(reasons),
                    first_bad_entry(name, sections.get(name)),
                )
            raise refusal(errors, sections)
        return encode_exact(fitted, size), left_out

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
        # A string or null raised TypeError on the comparison below, so the reply was a 500
        if not isinstance(schema_version, int) or isinstance(schema_version, bool):
            result["is_valid"] = False
            result["errors"].append("The backup's schema version isn't a whole number")
            return result
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

        # OLD CODE START — NET-344: every section is checked before any applies (section_errors)
        # # NET-330: bad quiet hours refuse the whole import, before any section applies
        # if "notification_quiet" in sections:
        #     reason = quiet_hours.problem(sections["notification_quiet"])
        #     if reason:
        #         result["is_valid"] = False
        #         result["errors"].append(reason)
        # OLD CODE END
        problems = [r for reasons in section_errors(sections).values() for r in reasons]
        left_out_error, left_out_warning = left_out_check(metadata, sections)
        if left_out_error:
            problems.append(left_out_error)
        if left_out_warning:
            result["warnings"].append(left_out_warning)
        if problems:
            result["is_valid"] = False
            result["errors"].extend(problems)

        # NET-320: a damaged details file here refuses the whole import too (the section's
        # content is checked in section_errors)
        if "device_details" in sections and self._device_details is not None:
            if not self._device_details.healthy:
                result["is_valid"] = False
                result["errors"].append(DETAILS_UNREADABLE)

        # A9: restoring a different capture mode restarts capture, so the page asks first
        capture = capture_section(sections.get("capture_mode_config"))
        result["capture_restart"] = bool(capture) and capture != self.current_capture()

        return result

    # OLD CODE: def import_config(self, data: dict[str, Any]) -> dict[str, Any]:
    # (NET-344: takes the handler's preflight, so it runs once per import)
    def import_config(
        self, data: dict[str, Any], validation: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Validate and apply settings from import data.

        ``validation``: validate_import(data)'s result when the caller has it already. With
        errors nothing is applied: content is checked for every section before any applies.
        Returns a result dict with applied sections and any errors.
        """
        # OLD CODE: validation = self.validate_import(data)
        if validation is None:
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
        # Device names and pictures, then details (NET-320)
        restore_devices(
            sections, self._device_custom, self._device_details, applied, errors, notes
        )

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
        # OLD CODE START — NET-344: checked by the preflight now; duplicates were written (Settings
        # keys its rows by IP) and a failed write could leave half a file
        # if "excluded_ips" in sections:
        #     raw = sections["excluded_ips"]
        #     ips = (
        #         [parse_single_ip(ip) for ip in raw] if isinstance(raw, list) else [None]
        #     )
        #     if None in ips:
        #         errors.append(
        #             "Excluded IPs not restored: each must be a single IP address"
        #         )
        #     elif self._write_json(self._paths.get("excluded_ips", ""), ips):
        #         applied.append("excluded_ips")
        #     else:
        #         errors.append("Failed to write excluded_ips")
        # OLD CODE END
        if "excluded_ips" in sections:
            raw = sections["excluded_ips"]
            # the preflight's own rule again at the write, so a hand-built validation can't put
            # nulls or an oversized list in the file
            problems = excluded_ip_errors(raw)
            if problems:
                errors.extend(problems)
            else:
                # single IPs, at most EXCLUDED_IPS_MAX of them, canonical and once each
                ips = list(dict.fromkeys(map(parse_single_ip, raw)))
                try:
                    self._write_atomic(self._paths.get("excluded_ips", ""), ips)
                    applied.append("excluded_ips")
                except OSError as exc:
                    # the reason stays in the log: the reply (a 400) never carries paths
                    logger.error("Excluded IPs not restored: %s", exc)
                    errors.append(
                        "Excluded IPs not restored: the file couldn't be written."
                    )

        # Apply bandwidth cap
        # OLD CODE START — wrote any JSON, and a shape the tracker can't read (a list, Infinity)
        # stopped the daemon starting until the file was deleted by hand
        # if "bandwidth_cap" in sections:
        #     ok = self._write_json(
        #         self._paths.get("bandwidth_cap", ""),
        #         sections["bandwidth_cap"],
        #     )
        #     if ok:
        #         applied.append("bandwidth_cap")
        #     else:
        #         errors.append("Failed to write bandwidth_cap")
        # OLD CODE END
        if "bandwidth_cap" in sections:
            self._restore_bandwidth_cap(
                sections["bandwidth_cap"], applied, skipped, errors
            )

        self._restore_owner_files(sections, applied, skipped, errors)
        # NET-340: restored paused, through the generator's lock
        restore_report_schedules(
            sections, self._report_generator, applied, errors, notes
        )

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
        """Channels (the box's own secrets where safe), rules and quiet hours, through the hub."""
        # OLD CODE START — NET-330: quiet hours are restored with them
        # present = [
        #     s for s in ("notification_channels", "notification_rules") if s in sections
        # ]
        # OLD CODE END
        present = [
            s
            for s in (
                "notification_channels",
                "notification_rules",
                "notification_quiet",
            )
            if s in sections
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

    def _restore_bandwidth_cap(
        self, cap: Any, applied: list, skipped: list, errors: list
    ) -> None:
        """The cap as BandwidthTracker reads it: {"monthly_cap_bytes": 0 to 1 PB, whole}."""
        if cap == {}:  # exported from a box that never set one
            skipped.append(
                {
                    "section": "bandwidth_cap",
                    "reason": "No bandwidth cap in this backup",
                }
            )
            return
        # OLD CODE START — NET-344: one rule shared with the preflight
        # value = cap.get("monthly_cap_bytes") if isinstance(cap, dict) else None
        # # OLD CODE: if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        # # (D5: no upper bound, so 10**400 was restored and every bandwidth page answered 500)
        # if (
        #     not isinstance(value, int)
        #     or isinstance(value, bool)
        #     or not 0 <= value <= MAX_MONTHLY_CAP_BYTES
        # ):
        #     errors.append("Bandwidth cap not restored: this backup's copy isn't valid")
        #     return
        # OLD CODE END
        problems = cap_errors(cap)
        if problems:
            errors.extend(problems)
            return
        value = cap["monthly_cap_bytes"]
        try:
            self._write_atomic(
                self._paths.get("bandwidth_cap", ""), {"monthly_cap_bytes": value}
            )
            applied.append("bandwidth_cap")
        except OSError as exc:
            errors.append(f"Bandwidth cap not restored: {exc}")

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
                # OLD CODE START — NET-344: one rule shared with the preflight
                # lambda d: (
                #     isinstance(d, dict) and all(isinstance(v, dict) for v in d.values())
                # ),
                # OLD CODE END
                lambda d: not ack_errors(d),
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
