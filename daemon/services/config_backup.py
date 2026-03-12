"""
NetTap ConfigBackup — Export/import all NetTap settings.

Gathers capture mode config, storage retention, notification channels,
notification rules, device aliases, and bandwidth cap into a single
JSON-serializable dict. Includes version stamp for compatibility checking.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("nettap.services.config_backup")

# Current config schema version
_SCHEMA_VERSION = 1

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
    "capture_config": os.environ.get(
        "CAPTURE_CONFIG_FILE", "/opt/nettap/data/capture_config.json"
    ),
    "retention_config": os.environ.get(
        "RETENTION_CONFIG_FILE", "/opt/nettap/data/retention_config.json"
    ),
}

# Sections that are exported/imported
_VALID_SECTIONS = {
    "capture_mode_config",
    "storage_retention",
    "notification_channels",
    "notification_rules",
    "device_aliases",
    "excluded_ips",
    "bandwidth_cap",
}


class ConfigBackup:
    """Export/import all NetTap configuration settings."""

    def __init__(self, config_paths: dict[str, str] | None = None) -> None:
        self._paths = {**_DEFAULT_PATHS, **(config_paths or {})}

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

        # Capture mode config
        config["sections"]["capture_mode_config"] = self._read_json(
            self._paths.get("capture_config", ""), default={}
        )

        # Storage retention
        config["sections"]["storage_retention"] = self._read_json(
            self._paths.get("retention_config", ""), default={}
        )

        # Notification channels + rules
        notif_data = self._read_json(
            self._paths.get("notification_config", ""), default={}
        )
        config["sections"]["notification_channels"] = notif_data.get("channels", {})
        config["sections"]["notification_rules"] = notif_data.get("rules", {})

        # Device aliases (from baseline file)
        baseline = self._read_json(
            self._paths.get("device_baseline", ""), default={}
        )
        config["sections"]["device_aliases"] = baseline.get("aliases", {})

        # Excluded IPs
        config["sections"]["excluded_ips"] = self._read_json(
            self._paths.get("excluded_ips", ""), default=[]
        )

        # Bandwidth cap
        config["sections"]["bandwidth_cap"] = self._read_json(
            self._paths.get("bandwidth_cap", ""), default={}
        )

        logger.info(
            "Exported config with %d sections", len(config["sections"])
        )
        return config

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
                        len(section_data) if isinstance(section_data, (dict, list))
                        else 1
                    ),
                }

        if not sections:
            result["warnings"].append("No sections found in import data")

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
            }

        sections = data.get("sections", {})
        applied = []
        errors = []

        # Apply capture mode config
        if "capture_mode_config" in sections:
            ok = self._write_json(
                self._paths.get("capture_config", ""),
                sections["capture_mode_config"],
            )
            if ok:
                applied.append("capture_mode_config")
            else:
                errors.append("Failed to write capture_mode_config")

        # Apply storage retention
        if "storage_retention" in sections:
            ok = self._write_json(
                self._paths.get("retention_config", ""),
                sections["storage_retention"],
            )
            if ok:
                applied.append("storage_retention")
            else:
                errors.append("Failed to write storage_retention")

        # Apply notification channels + rules
        if "notification_channels" in sections or "notification_rules" in sections:
            existing = self._read_json(
                self._paths.get("notification_config", ""), default={}
            )
            if "notification_channels" in sections:
                existing["channels"] = sections["notification_channels"]
            if "notification_rules" in sections:
                existing["rules"] = sections["notification_rules"]
            ok = self._write_json(
                self._paths.get("notification_config", ""), existing
            )
            if ok:
                applied.extend(
                    s for s in ["notification_channels", "notification_rules"]
                    if s in sections
                )
            else:
                errors.append("Failed to write notification config")

        # Apply device aliases
        if "device_aliases" in sections:
            existing = self._read_json(
                self._paths.get("device_baseline", ""), default={}
            )
            existing["aliases"] = sections["device_aliases"]
            ok = self._write_json(
                self._paths.get("device_baseline", ""), existing
            )
            if ok:
                applied.append("device_aliases")
            else:
                errors.append("Failed to write device_aliases")

        # Apply excluded IPs
        if "excluded_ips" in sections:
            ok = self._write_json(
                self._paths.get("excluded_ips", ""),
                sections["excluded_ips"],
            )
            if ok:
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

        logger.info(
            "Imported config: %d sections applied, %d errors",
            len(applied),
            len(errors),
        )

        return {
            "success": len(errors) == 0,
            "applied": applied,
            "errors": errors,
            "warnings": validation.get("warnings", []),
        }

    # ------------------------------------------------------------------
    # File I/O helpers
    # ------------------------------------------------------------------

    def _read_json(self, path: str, default: Any = None) -> Any:
        """Read a JSON file, returning default on any error."""
        if not path:
            return default
        p = Path(path)
        if not p.exists():
            return default
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            return default

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
