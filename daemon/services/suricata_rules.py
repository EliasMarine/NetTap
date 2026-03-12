"""
NetTap Suricata Rule Manager

Manages suricata-update rule sources: listing, enabling/disabling feeds,
triggering rule updates inside the Suricata container, tracking stats,
scheduling auto-updates, custom rules, and commercial license keys.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("nettap.services.suricata_rules")

# Default config path -- overridable via env var
DEFAULT_SOURCES_CONFIG = os.environ.get(
    "SURICATA_SOURCES_CONFIG",
    os.path.join(os.path.dirname(__file__), "../../config/suricata/update-sources.yaml"),
)

DEFAULT_CONTAINER_NAME = os.environ.get(
    "SURICATA_CONTAINER_NAME", "nettap-suricata-live"
)

# Schedule config path (stored alongside sources)
DEFAULT_SCHEDULE_FILE = os.environ.get(
    "SURICATA_SCHEDULE_FILE",
    os.path.join(os.path.dirname(__file__), "../../config/suricata/rule-schedule.yaml"),
)

# Custom rules file
DEFAULT_CUSTOM_RULES_FILE = os.environ.get(
    "SURICATA_CUSTOM_RULES_FILE",
    os.path.join(os.path.dirname(__file__), "../../config/suricata/custom.rules"),
)

# Commercial config
DEFAULT_COMMERCIAL_CONFIG = os.environ.get(
    "SURICATA_COMMERCIAL_CONFIG",
    os.path.join(os.path.dirname(__file__), "../../config/suricata/commercial.yaml"),
)


class SuricataRuleManager:
    """Manage Suricata rule sources and updates."""

    def __init__(
        self,
        sources_config: str | None = None,
        container_name: str | None = None,
        schedule_file: str | None = None,
        custom_rules_file: str | None = None,
        commercial_config: str | None = None,
    ):
        self._sources_config = sources_config or DEFAULT_SOURCES_CONFIG
        self._container_name = container_name or DEFAULT_CONTAINER_NAME
        self._schedule_file = schedule_file or DEFAULT_SCHEDULE_FILE
        self._custom_rules_file = custom_rules_file or DEFAULT_CUSTOM_RULES_FILE
        self._commercial_config = commercial_config or DEFAULT_COMMERCIAL_CONFIG

    # ------------------------------------------------------------------
    # YAML helpers
    # ------------------------------------------------------------------

    def _read_sources(self) -> dict[str, Any]:
        """Read and parse the sources YAML config."""
        path = Path(self._sources_config)
        if not path.exists():
            logger.warning("Sources config not found at %s, returning empty", path)
            return {"sources": {}}
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        if "sources" not in data:
            data["sources"] = {}
        return data

    def _write_sources(self, data: dict[str, Any]) -> None:
        """Write sources config back to YAML."""
        path = Path(self._sources_config)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    # ------------------------------------------------------------------
    # Source management
    # ------------------------------------------------------------------

    def get_enabled_sources(self) -> list[dict[str, Any]]:
        """Return list of all sources with their enabled/disabled status."""
        data = self._read_sources()
        sources = data.get("sources", {})
        result = []
        for source_id, config in sources.items():
            result.append({
                "id": source_id,
                "enabled": config.get("enabled", False),
                "description": config.get("description", ""),
            })
        return result

    def enable_source(self, source_id: str) -> bool:
        """Enable a rule source. Returns True if found and enabled."""
        data = self._read_sources()
        sources = data.get("sources", {})
        if source_id not in sources:
            return False
        sources[source_id]["enabled"] = True
        self._write_sources(data)
        logger.info("Enabled rule source: %s", source_id)
        return True

    def disable_source(self, source_id: str) -> bool:
        """Disable a rule source. Returns True if found and disabled."""
        data = self._read_sources()
        sources = data.get("sources", {})
        if source_id not in sources:
            return False
        sources[source_id]["enabled"] = False
        self._write_sources(data)
        logger.info("Disabled rule source: %s", source_id)
        return True

    # ------------------------------------------------------------------
    # Rule updates
    # ------------------------------------------------------------------

    async def update_rules(self) -> dict[str, Any]:
        """Run suricata-update inside the container and reload rules.

        Returns a dict with 'success', 'output', and 'reload_output' keys.
        """
        container = self._container_name

        # Step 1: Run suricata-update
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", container,
                "suricata-update",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await proc.communicate()
            update_output = stdout.decode("utf-8", errors="replace") if stdout else ""
            update_success = proc.returncode == 0
        except Exception as exc:
            logger.error("Failed to run suricata-update: %s", exc)
            return {
                "success": False,
                "output": "Failed to run suricata-update: {}".format(exc),
                "reload_output": "",
            }

        # Step 2: Reload rules via suricatasc
        reload_output = ""
        if update_success:
            try:
                reload_proc = await asyncio.create_subprocess_exec(
                    "docker", "exec", container,
                    "suricatasc", "-c", "reload-rules",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                reload_stdout, _ = await reload_proc.communicate()
                reload_output = reload_stdout.decode("utf-8", errors="replace") if reload_stdout else ""
            except Exception as exc:
                logger.error("Failed to reload rules: %s", exc)
                reload_output = "Reload failed: {}".format(exc)

        return {
            "success": update_success,
            "output": update_output,
            "reload_output": reload_output,
        }

    # ------------------------------------------------------------------
    # Rule stats
    # ------------------------------------------------------------------

    def get_rule_stats(self) -> dict[str, Any]:
        """Parse rule stats from suricata-update output or rules files.

        Returns category counts based on known rule prefixes.
        """
        categories: dict[str, int] = {}
        total = 0

        # Known category prefixes from rule SIDs
        category_prefixes = {
            "ET MALWARE": "Malware",
            "ET TROJAN": "Trojans",
            "ET SCAN": "Scanning",
            "ET EXPLOIT": "Exploits",
            "ET POLICY": "Policy",
            "ET INFO": "Informational",
            "ET DNS": "DNS",
            "ET WEB_SERVER": "Web Server Attacks",
            "ET WEB_CLIENT": "Web Client Threats",
            "ET HUNTING": "Threat Hunting",
            "ET CURRENT_EVENTS": "Current Events",
            "ET DROP": "Known Malicious IPs",
            "ET DOS": "Denial of Service",
            "SSLBL": "SSL Blacklist",
            "OISF": "Traffic ID",
            "PT": "Attack Detection",
        }

        # Return structure with category stubs (actual counts require
        # parsing the rules file from within the container)
        sources = self.get_enabled_sources()
        enabled_count = sum(1 for s in sources if s["enabled"])

        return {
            "total_rules": total,
            "enabled_sources": enabled_count,
            "total_sources": len(sources),
            "categories": categories,
            "category_prefixes": category_prefixes,
        }

    # ------------------------------------------------------------------
    # Last update time
    # ------------------------------------------------------------------

    def get_last_update(self) -> str | None:
        """Check mtime of the sources config as a proxy for last update time."""
        path = Path(self._sources_config)
        if not path.exists():
            return None
        mtime = path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Schedule management
    # ------------------------------------------------------------------

    def get_update_schedule(self) -> dict[str, Any]:
        """Return current auto-update schedule."""
        path = Path(self._schedule_file)
        if not path.exists():
            return {"interval": "daily", "enabled": True}
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        return {
            "interval": data.get("interval", "daily"),
            "enabled": data.get("enabled", True),
        }

    def set_update_schedule(self, interval: str) -> dict[str, Any]:
        """Set auto-update interval (daily/weekly/manual).

        'manual' effectively disables auto-updates.
        """
        valid_intervals = {"daily", "weekly", "manual"}
        if interval not in valid_intervals:
            raise ValueError(
                "Invalid interval '{}'. Must be one of: {}".format(interval, valid_intervals)
            )

        enabled = interval != "manual"
        schedule = {"interval": interval, "enabled": enabled}

        path = Path(self._schedule_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(schedule, f, default_flow_style=False)

        logger.info("Update schedule set to: %s (enabled=%s)", interval, enabled)
        return schedule

    # ------------------------------------------------------------------
    # Custom rules
    # ------------------------------------------------------------------

    def add_custom_rules(self, content: str) -> dict[str, Any]:
        """Write custom rules to a local .rules file."""
        path = Path(self._custom_rules_file)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Count rules (non-empty, non-comment lines)
        lines = [line.strip() for line in content.strip().split("\n")]
        rule_lines = [ln for ln in lines if ln and not ln.startswith("#")]

        with open(path, "w") as f:
            f.write(content)

        logger.info("Wrote %d custom rules to %s", len(rule_lines), path)
        return {
            "success": True,
            "rules_written": len(rule_lines),
            "file": str(path),
        }

    def get_custom_rules(self) -> str:
        """Read current custom rules content."""
        path = Path(self._custom_rules_file)
        if not path.exists():
            return ""
        return path.read_text()

    # ------------------------------------------------------------------
    # Commercial source configuration
    # ------------------------------------------------------------------

    def configure_commercial(self, source_type: str, license_key: str) -> dict[str, Any]:
        """Configure a commercial rule source (ET Pro or Snort Subscriber).

        Args:
            source_type: 'etpro' or 'snort'
            license_key: The license/oink code
        """
        valid_types = {"etpro", "snort"}
        if source_type not in valid_types:
            raise ValueError(
                "Invalid source type '{}'. Must be one of: {}".format(source_type, valid_types)
            )

        if not license_key or len(license_key) < 8:
            raise ValueError("License key must be at least 8 characters")

        config = {
            "source_type": source_type,
            "license_key": license_key,
            "configured_at": datetime.now(timezone.utc).isoformat(),
        }

        path = Path(self._commercial_config)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(config, f, default_flow_style=False)

        logger.info("Configured commercial source: %s", source_type)
        return {
            "success": True,
            "source_type": source_type,
            "configured_at": config["configured_at"],
        }

    def get_commercial_config(self) -> dict[str, Any] | None:
        """Read current commercial source configuration (without exposing key)."""
        path = Path(self._commercial_config)
        if not path.exists():
            return None
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        # Mask the license key
        key = data.get("license_key", "")
        masked = key[:4] + "****" + key[-4:] if len(key) > 8 else "****"
        return {
            "source_type": data.get("source_type", ""),
            "license_key_masked": masked,
            "configured_at": data.get("configured_at", ""),
        }
