"""
NetTap Suricata Rule Manager

Manages suricata-update rule sources: listing, enabling/disabling feeds,
triggering rule updates inside the Suricata container, tracking stats,
scheduling auto-updates, custom rules, and commercial license keys.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from services import rules_lock
from services.tshark_service import bounded_exec

logger = logging.getLogger("nettap.services.suricata_rules")

# Default config path -- overridable via env var
DEFAULT_SOURCES_CONFIG = os.environ.get(
    "SURICATA_SOURCES_CONFIG",
    os.path.join(
        os.path.dirname(__file__), "../../config/suricata/update-sources.yaml"
    ),
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


# What the Suricata container really runs. update-sources.yaml, the schedule file, custom
# rules and commercial keys are not wired into suricata-update (dashboard data accuracy #58),
# so the page reads the facts from the container instead.
# OLD CODE START — NET-191 slice 2: one awk pass also counts ET Pro rules; adds the enabled
# sources and the running engine's rule counts and last reload
# _LIVE_STATUS_SCRIPT = r"""
# R=/var/lib/suricata/rules/suricata.rules
# [ -f "$R" ] || { echo MISSING; exit 0; }
# echo "ENABLED $(grep -cE '^(alert|drop|pass|reject) ' "$R")"
# echo "DISABLED $(grep -cE '^# *(alert|drop|pass|reject) ' "$R")"
# echo "MTIME $(stat -c %Y "$R")"
# sed -n '/^sources:/,/^[a-z]/p' /etc/suricata/update.yaml 2>/dev/null | sed -n 's/^ *- *//p' | sed 's/^/SOURCE /'
# grep suricata-update-rules /etc/crontab 2>/dev/null | awk '{ print "CRON", $1, $2, $3, $4, $5 }'
# """
# OLD CODE END
# ET Pro SIDs are 2800000-2899999. Source configs are read for their name only: et-pro.yaml also
# holds the code. No interval expressions in the awk regex: Debian's awk is mawk.
_LIVE_STATUS_SCRIPT = r"""
R=/var/lib/suricata/rules/suricata.rules
[ -f "$R" ] || { echo MISSING; exit 0; }
awk '/^(alert|drop|pass|reject) / { e++; if ($0 ~ /sid: *28[0-9][0-9][0-9][0-9][0-9] *;/) p++ }
     /^# *(alert|drop|pass|reject) / { d++ }
     END { print "ENABLED", e + 0; print "DISABLED", d + 0; print "ETPRO", p + 0 }' "$R"
echo "MTIME $(stat -c %Y "$R")"
sed -n '/^sources:/,/^[a-z]/p' /etc/suricata/update.yaml 2>/dev/null | sed -n 's/^ *- *//p' | sed 's/^/SOURCE /'
grep suricata-update-rules /etc/crontab 2>/dev/null | awk '{ print "CRON", $1, $2, $3, $4, $5 }'
for f in /var/lib/suricata/update/sources/*.yaml; do
    [ -f "$f" ] && sed -n 's/^source: *//p' "$f" | head -1 | sed 's/^/ENABLED_SOURCE /'
done
S=/var/run/suricata/suricata-command.socket
echo "STATS $(suricatasc "$S" -c ruleset-stats 2>/dev/null | tr -d '\n')"
echo "RELOAD $(suricatasc "$S" -c ruleset-reload-time 2>/dev/null | tr -d '\n')"
"""
_LIVE_STATUS_TIMEOUT = 20

# NET-191 slice 2: "Update now" runs what the startup and nightly updates run: Malcolm's script path,
# which is NetTap's shim (rules lock, Malcolm's options with --fail, engine confirmation, last good
# rules, status record). As Malcolm's user, whose UID is PUID.
RULES_UPDATE_SHIM = "/usr/local/bin/suricata-update-rules.sh"
RULES_UPDATE_USER = "suricata"
# The web proxy waits 290 s; past this the update keeps running and its status record says how it went
RULES_UPDATE_WAIT_S = 270
STALE_AFTER = timedelta(hours=48)
_RECORD_FIELDS = (
    "state",
    "attempt",
    "exit_code",
    "reason",
    "last_success",
    "last_activation",
)


def _parse_time(value: Any) -> datetime | None:
    """The status record's "2026-11-07T00:00:05Z" or Suricata's "2026-11-07T00:01:12.123456+0000"."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def read_update_status(state_dir: str | None = None) -> dict[str, Any]:
    """update-status.json written by nettap-rules-update.sh. Missing = "unknown", never guessed."""
    state = state_dir or rules_lock.RULES_STATE_DIR
    try:
        with open(os.path.join(state, "update-status.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    record: dict[str, Any] = {field: data.get(field) for field in _RECORD_FIELDS}
    record["state"] = record["state"] or "unknown"
    record["reason"] = record["reason"] or ""
    # The script keeps the marker after a failure only when restoring the last good rules wasn't confirmed
    marker = os.path.exists(os.path.join(state, "update-in-progress"))
    record["recovery_pending"] = marker and record["state"] in ("failed", "interrupted")
    return record


def _engine_answer(line: str) -> dict[str, Any] | None:
    """The first engine's entry of a suricatasc JSON answer, or None when Suricata didn't answer."""
    try:
        answer = json.loads(line)
    except ValueError:
        return None
    if not isinstance(answer, dict) or answer.get("return") != "OK":
        return None
    message = answer.get("message")
    if isinstance(message, list):
        message = message[0] if message else None
    return message if isinstance(message, dict) else None


def with_update_status(
    status: dict[str, Any], record: dict[str, Any], now: datetime | None = None
) -> dict[str, Any]:
    """Add the update record to a live status. A "prepared" update (written at startup, before
    Suricata ran) is active once the engine's last load is later; stale = no success in 48 h."""
    now = now or datetime.now(timezone.utc)
    update = dict(record)
    engine = status.get("engine") or {}
    loaded_at = _parse_time(engine.get("reload_time"))
    prepared_at = _parse_time(update.get("last_success"))
    if (
        update["state"] == "prepared"
        and loaded_at
        and prepared_at
        and loaded_at >= prepared_at
    ):
        update = {**update, "state": "active", "last_activation": engine["reload_time"]}
    stale = update["state"] != "unknown" and (
        prepared_at is None or now - prepared_at > STALE_AFTER
    )
    return {**status, "update": {**update, "stale": stale}}


def update_record() -> dict[str, Any]:
    """The status record in the shape the live status shows it (with "stale"), for "Update now"."""
    return with_update_status({}, read_update_status())["update"]


def parse_live_status(output: str) -> dict[str, Any]:
    """Parse the _LIVE_STATUS_SCRIPT output into the /api/suricata/rules/live body."""
    if output.strip() == "MISSING":
        return {"available": False, "error": "Suricata has no rules file yet."}
    status: dict[str, Any] = {
        "available": False,
        "enabled_rules": 0,
        "disabled_rules": 0,
        "last_updated": None,
        "sources": [],
        "schedule": None,
        "error": None,
        "enabled_sources": [],
        "etpro_rules": 0,
        "engine": None,
    }
    engine: dict[str, Any] = {}
    for line in output.splitlines():
        key, _, value = line.strip().partition(" ")
        value = value.strip()
        if key == "ENABLED" and value.isdigit():
            status = {**status, "enabled_rules": int(value), "available": True}
        elif key == "DISABLED" and value.isdigit():
            status = {**status, "disabled_rules": int(value)}
        elif key == "MTIME" and value.isdigit():
            updated = datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
            status = {**status, "last_updated": updated}
        elif key == "SOURCE" and value:
            status = {**status, "sources": [*status["sources"], value]}
        elif key == "CRON" and value:
            status = {**status, "schedule": value}
        elif key == "ETPRO" and value.isdigit():
            status = {**status, "etpro_rules": int(value)}
        elif key == "ENABLED_SOURCE" and value:
            status = {**status, "enabled_sources": [*status["enabled_sources"], value]}
        elif key == "STATS" and (answer := _engine_answer(value)):
            engine = {
                **engine,
                "loaded": answer.get("rules_loaded"),
                "failed": answer.get("rules_failed"),
            }
        elif key == "RELOAD" and (answer := _engine_answer(value)):
            engine = {**engine, "reload_time": answer.get("last_reload")}
    if engine:
        status = {
            **status,
            "engine": {"loaded": None, "failed": None, "reload_time": None, **engine},
        }
    if not status["available"]:
        return {**status, "error": "Could not read Suricata's rule count."}
    return status


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
        # One rule-management operation at a time in this process (in front of the file lock)
        self._op_lock = asyncio.Lock()
        self._update_drain: asyncio.Future | None = None

    @property
    def container_name(self) -> str:
        return self._container_name

    @property
    def op_lock(self) -> asyncio.Lock:
        return self._op_lock

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
            result.append(
                {
                    "id": source_id,
                    "enabled": config.get("enabled", False),
                    "description": config.get("description", ""),
                }
            )
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
        """Update the rules the way the nightly update does (NET-191 slice 2).

        Runs the shim in the Suricata container, which takes the rules lock, runs Malcolm's
        updater (its options, --fail), waits until Suricata has loaded the result with 0 failed
        rules, keeps or restores the last good rules, and writes the status record. The daemon
        never holds the rules lock here: the shim takes it.

        Returns 'success', 'output' (redacted by the shim), 'reload_output' (the record's reason or
        state), 'status' (the record) and, when the wait ran out first, 'running'.
        """
        async with self._op_lock:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker",
                    "exec",
                    "-u",
                    RULES_UPDATE_USER,
                    self._container_name,
                    RULES_UPDATE_SHIM,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
            except OSError as exc:
                logger.error("Could not start the rule update: %s", exc)
                return {
                    "success": False,
                    "output": f"Could not start the rule update: {exc}",
                    "reload_output": "",
                    "status": update_record(),
                }
            # Keeps draining the output if the wait runs out, so the update never blocks on a full pipe
            # (kept on self: asyncio holds only a weak reference to a task)
            drain = self._update_drain = asyncio.ensure_future(proc.communicate())
            try:
                stdout, _ = await asyncio.wait_for(
                    asyncio.shield(drain), RULES_UPDATE_WAIT_S
                )
            except asyncio.TimeoutError:
                logger.info("Rule update still running after %d s", RULES_UPDATE_WAIT_S)
                return {
                    "success": False,
                    "running": True,
                    "output": "The update is still running. Its result shows under "
                    "Rules Suricata runs when it finishes.",
                    "reload_output": "",
                    "status": update_record(),
                }
        output = (stdout or b"").decode("utf-8", errors="replace")
        record = update_record()
        success = proc.returncode == 0 and record["state"] in ("active", "prepared")
        logger.info(
            "Rule update: exit %s, state %s%s",
            proc.returncode,
            record["state"],
            f" ({record['reason']})" if record["reason"] else "",
        )
        return {
            "success": success,
            "output": output[-4000:],
            "reload_output": record["reason"] or record["state"],
            "status": record,
        }

    # OLD CODE START — NET-191 slice 2: bare suricata-update had no --fail and none of Malcolm's
    # options (a source failure could install a partial ruleset), no lock and no status record
    # async def update_rules(self) -> dict[str, Any]:
    #     """Run suricata-update inside the container and reload rules.

    #     Returns a dict with 'success', 'output', and 'reload_output' keys.
    #     """
    #     container = self._container_name

    #     # Step 1: Run suricata-update
    #     try:
    #         proc = await asyncio.create_subprocess_exec(
    #             "docker",
    #             "exec",
    #             container,
    #             "suricata-update",
    #             stdout=asyncio.subprocess.PIPE,
    #             stderr=asyncio.subprocess.STDOUT,
    #         )
    #         stdout, _ = await proc.communicate()
    #         update_output = stdout.decode("utf-8", errors="replace") if stdout else ""
    #         update_success = proc.returncode == 0
    #     except Exception as exc:
    #         logger.error("Failed to run suricata-update: %s", exc)
    #         return {
    #             "success": False,
    #             "output": "Failed to run suricata-update: {}".format(exc),
    #             "reload_output": "",
    #         }

    #     # Step 2: Reload rules via suricatasc
    #     reload_output = ""
    #     reload_ok = False
    #     if update_success:
    #         try:
    #             reload_proc = await asyncio.create_subprocess_exec(
    #                 "docker",
    #                 "exec",
    #                 container,
    #                 "suricatasc",
    #                 "-c",
    #                 "reload-rules",
    #                 stdout=asyncio.subprocess.PIPE,
    #                 stderr=asyncio.subprocess.STDOUT,
    #             )
    #             reload_stdout, _ = await reload_proc.communicate()
    #             reload_output = (
    #                 reload_stdout.decode("utf-8", errors="replace")
    #                 if reload_stdout
    #                 else ""
    #             )
    #             # suricatasc exits non-zero when Suricata answers NOK
    #             reload_ok = reload_proc.returncode == 0
    #             if not reload_ok:
    #                 logger.error("Suricata rule reload failed: %s", reload_output)
    #         except Exception as exc:
    #             logger.error("Failed to reload rules: %s", exc)
    #             reload_output = "Reload failed: {}".format(exc)

    #     return {
    #         # OLD CODE START — #96: a failed reload still said success, while Suricata
    #         # kept running the old rules
    #         # "success": update_success,
    #         # OLD CODE END
    #         "success": update_success and reload_ok,
    #         "output": update_output,
    #         "reload_output": reload_output,
    #     }
    # OLD CODE END

    # ------------------------------------------------------------------
    # Live status (read from the Suricata container)
    # ------------------------------------------------------------------

    async def get_live_status(self) -> dict[str, Any]:
        """Rule counts, last refresh, sources and schedule Suricata really uses."""
        cmd = bounded_exec(
            ["docker", "exec", self._container_name, "sh", "-c", _LIVE_STATUS_SCRIPT],
            _LIVE_STATUS_TIMEOUT,
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_LIVE_STATUS_TIMEOUT + 10
            )
        except (OSError, asyncio.TimeoutError) as exc:
            logger.error("Could not read Suricata's rule status: %s", exc)
            return {
                "available": False,
                "error": "Could not reach the Suricata container.",
            }
        if proc.returncode != 0:
            detail = (stderr or b"").decode("utf-8", errors="replace").strip()[:200]
            logger.error(
                "Reading Suricata's rule status failed (rc=%s): %s",
                proc.returncode,
                detail,
            )
            return {"available": False, "error": "Could not read Suricata's rules."}
        # OLD CODE START — NET-191 slice 2: adds the update status record
        # return parse_live_status((stdout or b"").decode("utf-8", errors="replace"))
        # OLD CODE END
        status = parse_live_status((stdout or b"").decode("utf-8", errors="replace"))
        return with_update_status(status, read_update_status())

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
                "Invalid interval '{}'. Must be one of: {}".format(
                    interval, valid_intervals
                )
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

    # OLD CODE START — NET-191 slice 2: wrote the licence key in plain text to config/suricata/commercial.yaml, which nothing read; ET Pro is services/etpro.py
    # def configure_commercial(
    #     self, source_type: str, license_key: str
    # ) -> dict[str, Any]:
    #     """Configure a commercial rule source (ET Pro or Snort Subscriber).
    #
    #     Args:
    #         source_type: 'etpro' or 'snort'
    #         license_key: The license/oink code
    #     """
    #     valid_types = {"etpro", "snort"}
    #     if source_type not in valid_types:
    #         raise ValueError(
    #             "Invalid source type '{}'. Must be one of: {}".format(
    #                 source_type, valid_types
    #             )
    #         )
    #
    #     if not license_key or len(license_key) < 8:
    #         raise ValueError("License key must be at least 8 characters")
    #
    #     config = {
    #         "source_type": source_type,
    #         "license_key": license_key,
    #         "configured_at": datetime.now(timezone.utc).isoformat(),
    #     }
    #
    #     path = Path(self._commercial_config)
    #     path.parent.mkdir(parents=True, exist_ok=True)
    #     with open(path, "w") as f:
    #         yaml.dump(config, f, default_flow_style=False)
    #
    #     logger.info("Configured commercial source: %s", source_type)
    #     return {
    #         "success": True,
    #         "source_type": source_type,
    #         "configured_at": config["configured_at"],
    #     }
    #
    # def get_commercial_config(self) -> dict[str, Any] | None:
    #     """Read current commercial source configuration (without exposing key)."""
    #     path = Path(self._commercial_config)
    #     if not path.exists():
    #         return None
    #     with open(path, "r") as f:
    #         data = yaml.safe_load(f) or {}
    #     # Mask the license key
    #     key = data.get("license_key", "")
    #     masked = key[:4] + "****" + key[-4:] if len(key) > 8 else "****"
    #     return {
    #         "source_type": data.get("source_type", ""),
    #         "license_key_masked": masked,
    #         "configured_at": data.get("configured_at", ""),
    #     }
    # OLD CODE END
