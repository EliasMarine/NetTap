"""
NetTap Retention Configuration Manager

Single source of truth for all retention settings. Manages a persistent
``retention.json`` config file with load/save/validate logic, replacing
the fragmented env-var / .env / hardcoded-ILM approach.

Priority chain on load:
  1. ``retention.json`` exists and is valid JSON -> parse and return
  2. Missing/corrupt -> read env vars -> create ``retention.json`` -> return
  3. No env vars -> use ``RetentionConfig`` defaults (90/180/30/80/90)

Why: The setup wizard wrote wrong env-var key names (HOT_RETENTION_DAYS
vs. RETENTION_HOT) and the daemon only read env vars at startup. This
module creates a persistent, canonical config file that survives restarts
and is the single place to update retention settings.
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from storage.manager import RetentionConfig

logger = logging.getLogger("nettap.storage.retention_config")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_config(values: dict) -> None:
    """Validate retention configuration values.

    Args:
        values: Dict with keys matching the ``retention.json`` structure.
            Expected keys under ``retention``: hot_days, warm_days, cold_days.
            Expected keys under ``thresholds``: disk_threshold_percent,
            emergency_threshold_percent.
            Alternatively, flat keys (hot_days, warm_days, cold_days,
            disk_threshold_percent, emergency_threshold_percent) are accepted
            for convenience when called from the API layer.

    Raises:
        ValueError: If any value is out of range or has the wrong type.
    """
    # Support both nested (retention.json shape) and flat dicts
    if "retention" in values and isinstance(values["retention"], dict):
        hot = values["retention"].get("hot_days")
        warm = values["retention"].get("warm_days")
        cold = values["retention"].get("cold_days")
    else:
        hot = values.get("hot_days")
        warm = values.get("warm_days")
        cold = values.get("cold_days")

    if "thresholds" in values and isinstance(values["thresholds"], dict):
        disk_pct = values["thresholds"].get("disk_threshold_percent")
        emergency_pct = values["thresholds"].get("emergency_threshold_percent")
    else:
        disk_pct = values.get("disk_threshold_percent")
        emergency_pct = values.get("emergency_threshold_percent")

    # --- hot_days ---
    if hot is not None:
        if not isinstance(hot, int):
            raise ValueError(
                f"hot_days must be an integer, got {type(hot).__name__}"
            )
        if not 1 <= hot <= 365:
            raise ValueError(
                f"hot_days must be between 1 and 365, got {hot}"
            )

    # --- warm_days ---
    if warm is not None:
        if not isinstance(warm, int):
            raise ValueError(
                f"warm_days must be an integer, got {type(warm).__name__}"
            )
        if not 1 <= warm <= 730:
            raise ValueError(
                f"warm_days must be between 1 and 730, got {warm}"
            )

    # --- cold_days ---
    if cold is not None:
        if not isinstance(cold, int):
            raise ValueError(
                f"cold_days must be an integer, got {type(cold).__name__}"
            )
        if not 1 <= cold <= 365:
            raise ValueError(
                f"cold_days must be between 1 and 365, got {cold}"
            )

    # --- disk_threshold_percent ---
    if disk_pct is not None:
        if not isinstance(disk_pct, int):
            raise ValueError(
                f"disk_threshold_percent must be an integer, got {type(disk_pct).__name__}"
            )
        if not 50 <= disk_pct <= 95:
            raise ValueError(
                f"disk_threshold_percent must be between 50 and 95, got {disk_pct}"
            )

    # --- emergency_threshold_percent ---
    if emergency_pct is not None:
        if not isinstance(emergency_pct, int):
            raise ValueError(
                f"emergency_threshold_percent must be an integer, "
                f"got {type(emergency_pct).__name__}"
            )
        if not 51 <= emergency_pct <= 99:
            raise ValueError(
                f"emergency_threshold_percent must be between 51 and 99, "
                f"got {emergency_pct}"
            )

    # Cross-field: emergency must be > disk threshold
    if disk_pct is not None and emergency_pct is not None:
        if emergency_pct <= disk_pct:
            raise ValueError(
                f"emergency_threshold_percent ({emergency_pct}) must be greater "
                f"than disk_threshold_percent ({disk_pct})"
            )


# ---------------------------------------------------------------------------
# Configuration Manager
# ---------------------------------------------------------------------------


class RetentionConfigManager:
    """Manages the canonical ``retention.json`` configuration file.

    Provides thread-safe load/save/validate logic for retention settings,
    with fallback to environment variables and ``RetentionConfig`` defaults.
    Also synchronises settings to the ``.env`` file using the correct
    variable names (RETENTION_HOT, not HOT_RETENTION_DAYS).

    Args:
        config_path: Path to the ``retention.json`` file.
        env_file: Path to the ``.env`` file for backwards-compatible sync.
    """

    def __init__(
        self,
        config_path: str = "/opt/nettap/data/retention.json",
        env_file: str = "/opt/nettap/data/.env",
    ):
        self._config_path = config_path
        self._env_file = env_file
        self._lock = threading.Lock()
        self._config: RetentionConfig = RetentionConfig()
        self._ilm_status: dict = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> RetentionConfig:
        """Load retention config using the priority chain.

        1. If ``retention.json`` exists and is valid -> parse and return.
        2. If missing or corrupt -> read env vars, create file, return.
        3. If no env vars set -> use ``RetentionConfig`` defaults.

        Returns:
            A populated ``RetentionConfig`` instance.
        """
        with self._lock:
            config_file = Path(self._config_path)

            # Priority 1: existing retention.json
            if config_file.exists():
                try:
                    data = json.loads(config_file.read_text(encoding="utf-8"))
                    self._config = self._parse_json(data)
                    self._ilm_status = data.get("ilm_applied", {})
                    logger.info(
                        "Loaded retention config from %s "
                        "(hot=%dd, warm=%dd, cold=%dd, disk=%.0f%%, emergency=%.0f%%)",
                        self._config_path,
                        self._config.hot_days,
                        self._config.warm_days,
                        self._config.cold_days,
                        self._config.disk_threshold * 100,
                        self._config.emergency_threshold * 100,
                    )
                    return self._config
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    logger.warning(
                        "Corrupt retention.json at %s (%s), falling back to env vars",
                        self._config_path,
                        exc,
                    )

            # Priority 2: env vars -> create retention.json
            self._config = self._from_env()
            logger.info(
                "Built retention config from env vars / defaults "
                "(hot=%dd, warm=%dd, cold=%dd, disk=%.0f%%, emergency=%.0f%%)",
                self._config.hot_days,
                self._config.warm_days,
                self._config.cold_days,
                self._config.disk_threshold * 100,
                self._config.emergency_threshold * 100,
            )

            # Persist so next load hits priority 1
            self._write_json(self._config)
            return self._config

    def save(self, new_config: dict) -> RetentionConfig:
        """Validate, persist, and return a new retention configuration.

        1. Validate individual field ranges in the input.
        2. Merge onto current config (partial updates keep existing values).
        3. Validate cross-field constraints on the merged result.
        4. Write ``retention.json`` atomically (write .tmp, then rename).
        5. Sync to ``.env`` with the correct variable names.
        6. Update in-memory config.

        Args:
            new_config: Dict with retention/threshold values. Supports both
                flat keys (``hot_days``, ``disk_threshold_percent``) and the
                nested ``retention.json`` structure.

        Returns:
            The newly saved ``RetentionConfig``.

        Raises:
            ValueError: If any value fails validation.
        """
        # Validate individual field ranges first
        validate_config(new_config)

        with self._lock:
            # Merge new values onto current config (partial updates)
            merged = self._merge_config(new_config)

            # Validate cross-field constraints on the MERGED result to catch
            # partial updates that create invalid combinations (e.g. lowering
            # emergency_threshold below the existing disk_threshold)
            merged_dict = {
                "disk_threshold_percent": int(merged.disk_threshold * 100),
                "emergency_threshold_percent": int(merged.emergency_threshold * 100),
            }
            validate_config(merged_dict)
            self._config = merged
            self._write_json(merged)
            self._sync_env(merged)

            logger.info(
                "Saved retention config "
                "(hot=%dd, warm=%dd, cold=%dd, disk=%.0f%%, emergency=%.0f%%)",
                merged.hot_days,
                merged.warm_days,
                merged.cold_days,
                merged.disk_threshold * 100,
                merged.emergency_threshold * 100,
            )
            return merged

    def get_config(self) -> RetentionConfig:
        """Return the current in-memory retention config."""
        return self._config

    def update_config(self, new_config: RetentionConfig) -> None:
        """Replace the in-memory config reference.

        Used when the API handler hot-reloads the ``StorageManager`` and
        needs to keep this manager in sync.
        """
        with self._lock:
            self._config = new_config

    def get_ilm_status(self) -> dict:
        """Return the ``ilm_applied`` section from retention.json."""
        with self._lock:
            return dict(self._ilm_status)

    def mark_ilm_applied(self, results: dict) -> None:
        """Update ``retention.json`` with ILM application results.

        Args:
            results: Dict mapping policy names to their application status
                (e.g. ``{"nettap-hot-policy": "updated", ...}``).
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._ilm_status = {
                "last_success": now,
                "last_attempt": now,
                "policies": results,
            }
            # Re-write the full file to include updated ILM status
            self._write_json(self._config)
            logger.info("Marked ILM applied: %s", results)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json(data: dict) -> RetentionConfig:
        """Parse a ``retention.json`` dict into a ``RetentionConfig``.

        Expects the canonical nested format:
        ``{"retention": {...}, "thresholds": {...}}``.
        """
        retention = data.get("retention", {})
        thresholds = data.get("thresholds", {})

        return RetentionConfig(
            hot_days=int(retention.get("hot_days", 90)),
            warm_days=int(retention.get("warm_days", 180)),
            cold_days=int(retention.get("cold_days", 30)),
            disk_threshold=int(thresholds.get("disk_threshold_percent", 80)) / 100.0,
            emergency_threshold=int(thresholds.get("emergency_threshold_percent", 90)) / 100.0,
        )

    @staticmethod
    def _from_env() -> RetentionConfig:
        """Build a ``RetentionConfig`` from environment variables.

        Uses the correct env-var names (``RETENTION_HOT``, not
        ``HOT_RETENTION_DAYS``) with ``RetentionConfig`` defaults as
        fallback when vars are unset.
        """
        defaults = RetentionConfig()
        return RetentionConfig(
            hot_days=int(os.environ.get("RETENTION_HOT", defaults.hot_days)),
            warm_days=int(os.environ.get("RETENTION_WARM", defaults.warm_days)),
            cold_days=int(os.environ.get("RETENTION_COLD", defaults.cold_days)),
            disk_threshold=int(
                os.environ.get("DISK_THRESHOLD_PERCENT", int(defaults.disk_threshold * 100))
            ) / 100.0,
            emergency_threshold=int(
                os.environ.get(
                    "EMERGENCY_THRESHOLD_PERCENT",
                    int(defaults.emergency_threshold * 100),
                )
            ) / 100.0,
        )

    def _merge_config(self, new_config: dict) -> RetentionConfig:
        """Merge a partial config dict onto the current config.

        Supports both flat and nested dict formats. Only overwrites
        fields that are present in *new_config*; missing fields retain
        their current value.
        """
        # Extract values from nested or flat format
        if "retention" in new_config and isinstance(new_config["retention"], dict):
            r = new_config["retention"]
        else:
            r = new_config

        if "thresholds" in new_config and isinstance(new_config["thresholds"], dict):
            t = new_config["thresholds"]
        else:
            t = new_config

        hot = int(r["hot_days"]) if "hot_days" in r else self._config.hot_days
        warm = int(r["warm_days"]) if "warm_days" in r else self._config.warm_days
        cold = int(r["cold_days"]) if "cold_days" in r else self._config.cold_days

        disk_pct = (
            int(t["disk_threshold_percent"])
            if "disk_threshold_percent" in t
            else int(self._config.disk_threshold * 100)
        )
        emergency_pct = (
            int(t["emergency_threshold_percent"])
            if "emergency_threshold_percent" in t
            else int(self._config.emergency_threshold * 100)
        )

        return RetentionConfig(
            hot_days=hot,
            warm_days=warm,
            cold_days=cold,
            disk_threshold=disk_pct / 100.0,
            emergency_threshold=emergency_pct / 100.0,
        )

    def _write_json(self, config: RetentionConfig) -> None:
        """Atomically write ``retention.json``.

        Writes to a temporary ``.tmp`` file first, then renames to avoid
        partial writes on crash/power loss.
        """
        data = {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "retention": {
                "hot_days": config.hot_days,
                "warm_days": config.warm_days,
                "cold_days": config.cold_days,
            },
            "thresholds": {
                "disk_threshold_percent": int(config.disk_threshold * 100),
                "emergency_threshold_percent": int(config.emergency_threshold * 100),
            },
            "ilm_applied": self._ilm_status or {
                "last_success": None,
                "last_attempt": None,
                "policies": {},
            },
        }

        config_path = Path(self._config_path)
        tmp_path = config_path.with_suffix(".tmp")

        os.makedirs(config_path.parent, exist_ok=True)
        tmp_path.write_text(
            json.dumps(data, indent=2) + "\n",
            encoding="utf-8",
        )
        os.rename(str(tmp_path), str(config_path))

    def _sync_env(self, config: RetentionConfig) -> None:
        """Sync retention values to the ``.env`` file.

        Uses the CORRECT env-var names (``RETENTION_HOT``, ``RETENTION_WARM``,
        ``RETENTION_COLD``) — NOT the wrong names the setup wizard previously
        used (``HOT_RETENTION_DAYS``, etc.).

        Follows the read/update/append pattern from
        ``daemon/api/setup.py:_update_env_file()``.
        """
        env_vars = {
            "RETENTION_HOT": str(config.hot_days),
            "RETENTION_WARM": str(config.warm_days),
            "RETENTION_COLD": str(config.cold_days),
            "DISK_THRESHOLD_PERCENT": str(int(config.disk_threshold * 100)),
            "EMERGENCY_THRESHOLD_PERCENT": str(int(config.emergency_threshold * 100)),
        }

        # Read existing .env if it exists
        existing_lines: list[str] = []
        existing_keys: set[str] = set()
        env_path = Path(self._env_file)

        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#") and "=" in stripped:
                        key = stripped.split("=", 1)[0]
                        if key in env_vars:
                            # Replace with new value
                            existing_lines.append(f"{key}={env_vars[key]}\n")
                            existing_keys.add(key)
                        else:
                            existing_lines.append(line)
                    else:
                        existing_lines.append(line)

        # Append any new vars not already in the file
        for key, value in env_vars.items():
            if key not in existing_keys:
                existing_lines.append(f"{key}={value}\n")

        os.makedirs(os.path.dirname(self._env_file), exist_ok=True)
        with open(self._env_file, "w", encoding="utf-8") as f:
            f.writelines(existing_lines)

        logger.debug("Synced retention config to %s", self._env_file)
