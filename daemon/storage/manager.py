"""
NetTap Storage Manager

Monitors disk usage and enforces rolling retention policies for
Zeek logs, Suricata alerts, and PCAP data via OpenSearch index management.

Phase 2 rewrite: Uses opensearch-py client with tiered pruning,
emergency pruning, and status reporting.
"""

import json
import os
import re
import logging
import shutil
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from opensearchpy import OpenSearch, OpenSearchException

logger = logging.getLogger("nettap.storage")

# ---------------------------------------------------------------------------
# OLD CODE START — Original StorageManager (Phase 1 scaffold)
# Replaced by Phase 2 implementation below with opensearch-py client,
# tiered pruning, emergency pruning, and status reporting.
# ---------------------------------------------------------------------------
# @dataclass
# class RetentionConfig:
#     hot_days: int = 90      # Zeek metadata
#     warm_days: int = 180    # Suricata alerts
#     cold_days: int = 30     # Raw PCAP
#     disk_threshold: float = 0.80  # Trigger early pruning at 80%
#
#
# class StorageManager:
#     """Manages disk utilization and triggers retention pruning."""
#
#     def __init__(self, config: RetentionConfig, opensearch_url: str):
#         self.config = config
#         self.opensearch_url = opensearch_url
#
#     def check_disk_usage(self, path: str = "/") -> float:
#         """Returns disk usage as a fraction (0.0 to 1.0)."""
#         usage = shutil.disk_usage(path)
#         return usage.used / usage.total
#
#     def should_prune(self, path: str = "/") -> bool:
#         """Check if disk usage exceeds the configured threshold."""
#         usage = self.check_disk_usage(path)
#         if usage >= self.config.disk_threshold:
#             logger.warning(
#                 "Disk usage %.1f%% exceeds threshold %.1f%%",
#                 usage * 100,
#                 self.config.disk_threshold * 100,
#             )
#             return True
#         return False
#
#     def prune_oldest_indices(self):
#         """Delete oldest OpenSearch indices to reclaim space."""
#         # TODO: Query OpenSearch for indices sorted by date,
#         # delete oldest beyond retention window
#         raise NotImplementedError
#
#     def run_cycle(self):
#         """Execute one maintenance cycle: check disk, prune if needed."""
#         if self.should_prune():
#             logger.info("Starting early pruning cycle")
#             self.prune_oldest_indices()
#         else:
#             logger.debug("Disk usage within threshold, no action needed")
# ---------------------------------------------------------------------------
# OLD CODE END
# ---------------------------------------------------------------------------


# Index name date patterns — supports both dot and dash separators
# Examples: zeek-conn-2026.02.25, suricata-alert-2026-02-25, arkime_sessions3-260225
_DATE_PATTERN_DOT = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})$")
_DATE_PATTERN_DASH = re.compile(r"(\d{4})-(\d{2})-(\d{2})$")
_DATE_PATTERN_COMPACT = re.compile(r"(\d{6})$")  # YYMMDD used by Arkime


# Tier classification prefixes
_TIER_PREFIXES = {
    "cold": ["arkime", "sessions"],
    "warm": ["suricata"],
    "hot": ["zeek"],
}


@dataclass
class RetentionConfig:
    """Configuration for tiered retention policies and disk thresholds."""

    hot_days: int = 90  # Zeek metadata retention (days)
    warm_days: int = 180  # Suricata alert retention (days)
    cold_days: int = 30  # Raw PCAP / Arkime retention (days)
    disk_threshold: float = 0.80  # Trigger pruning at 80%
    emergency_threshold: float = 0.90  # Aggressive pruning at 90%
    critical_threshold: float = 0.95  # Stop capture at 95%
    resume_threshold: float = 0.85  # Resume normal operation below 85%
    check_path: str = "/"  # Filesystem path for disk usage checks
    pcap_dir: str = "/data/pcap"  # Directory containing PCAP files
    capture_stop_flag: str = "/tmp/nettap-stop-capture"  # Flag file to stop capture
    ilm_policy_path: str = ""  # Path to ILM policy JSON (auto-detected if empty)


class StorageManager:
    """Manages disk utilization and enforces rolling retention via OpenSearch.

    Monitors disk usage against configurable thresholds and deletes the
    oldest OpenSearch indices tier-by-tier (cold -> warm -> hot) to
    reclaim space.  An emergency mode bypasses tier ordering when disk
    usage exceeds the emergency threshold.
    """

    # Maximum number of disk usage samples to keep (24h at 5-min intervals)
    _USAGE_HISTORY_MAX = 288

    def __init__(
        self,
        config: RetentionConfig,
        opensearch_url: str,
        http_auth: tuple[str, str] | None = None,
    ):
        self.config = config
        self.opensearch_url = opensearch_url
        self._http_auth = http_auth

        # Parse URL for opensearch-py client
        self._client = self._create_client(opensearch_url, http_auth=http_auth)

        # C1: Rolling disk usage history for predictive exhaustion alerting
        # Each entry is (timestamp, usage_fraction)
        self._usage_history: deque[tuple[datetime, float]] = deque(
            maxlen=self._USAGE_HISTORY_MAX
        )
        self._prediction_alert_active: bool = False

        # C3: Track whether ILM policy has been verified this session
        self._ilm_verified: bool = False

        # Lock to prevent manual cleanup from racing with auto-prune cycles
        self._cleanup_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Client helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _create_client(
        url: str,
        http_auth: tuple[str, str] | None = None,
    ) -> OpenSearch:
        """Create an OpenSearch client from a URL string.

        Supports both http:// and https:// URLs.  For https, SSL
        certificate verification is disabled by default (typical for
        internal Malcolm deployments with self-signed certificates).

        Args:
            url: OpenSearch URL (e.g., "https://opensearch:9200").
            http_auth: Optional (username, password) tuple for Basic Auth.
                Required after OpenSearch security bootstrap.
        """
        use_ssl = url.startswith("https")
        # Strip protocol for host parsing
        host_part = url.replace("https://", "").replace("http://", "")
        # Handle host:port
        if ":" in host_part:
            host, port_str = host_part.rsplit(":", 1)
            port = int(port_str.rstrip("/"))
        else:
            host = host_part.rstrip("/")
            port = 9200

        kwargs: dict = {
            "hosts": [{"host": host, "port": port}],
            "use_ssl": use_ssl,
            "verify_certs": False,
            "ssl_show_warn": False,
            "timeout": 30,
            "max_retries": 3,
            "retry_on_timeout": True,
        }
        if http_auth:
            kwargs["http_auth"] = http_auth

        return OpenSearch(**kwargs)

    # ------------------------------------------------------------------
    # Disk usage
    # ------------------------------------------------------------------

    def check_disk_usage(self, path: str | None = None) -> float:
        """Returns disk usage as a fraction (0.0 to 1.0).

        Uses ``config.check_path`` when *path* is not explicitly given.
        """
        check = path if path is not None else self.config.check_path
        usage = shutil.disk_usage(check)
        return usage.used / usage.total

    # ------------------------------------------------------------------
    # Index discovery
    # ------------------------------------------------------------------

    def list_indices(self) -> list[dict]:
        """Query OpenSearch ``_cat/indices`` and return a list of dicts.

        Each dict contains:
          - name: index name
          - size: human-readable size string (e.g. "24.5mb")
          - size_bytes: size in bytes (parsed from ``pri.store.size``)
          - creation_date: ISO-8601 creation date string or None
          - tier: one of "hot", "warm", "cold", "unknown"
          - parsed_date: datetime extracted from index name or None
        """
        try:
            raw = self._client.cat.indices(
                format="json",
                h="index,store.size,pri.store.size,creation.date.string",
                s="index",
            )
        except OpenSearchException as exc:
            logger.error("Failed to list indices from OpenSearch: %s", exc)
            return []

        indices: list[dict] = []
        for entry in raw:
            name = entry.get("index", "")
            # Skip internal/system indices
            if name.startswith("."):
                continue

            size_str = entry.get("store.size", "0b")
            creation = entry.get("creation.date.string")
            tier = self._parse_index_tier(name)
            parsed_date = self._parse_index_date(name)

            indices.append(
                {
                    "name": name,
                    "size": size_str,
                    "creation_date": creation,
                    "tier": tier,
                    "parsed_date": parsed_date,
                }
            )

        return indices

    # ------------------------------------------------------------------
    # Index classification helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_index_tier(index_name: str) -> str:
        """Classify an index into a retention tier based on its name prefix.

        Returns one of: "cold", "warm", "hot", "unknown".

        Tier mapping:
          - cold: arkime-*, sessions* (PCAP indices)
          - warm: suricata-* (IDS alert indices)
          - hot: zeek-* (metadata log indices)
        """
        lower = index_name.lower()
        for tier, prefixes in _TIER_PREFIXES.items():
            for prefix in prefixes:
                if lower.startswith(prefix):
                    return tier
        return "unknown"

    @staticmethod
    def _parse_index_date(index_name: str) -> Optional[datetime]:
        """Extract a date from an index name suffix.

        Supports formats:
          - zeek-conn-2026.02.25  (dot-separated)
          - suricata-alert-2026-02-25  (dash-separated)
          - arkime_sessions3-260225  (compact YYMMDD)

        Returns a timezone-aware UTC datetime at midnight, or None if
        no date pattern is found.
        """
        # Try dot format: YYYY.MM.DD
        match = _DATE_PATTERN_DOT.search(index_name)
        if match:
            try:
                return datetime(
                    int(match.group(1)),
                    int(match.group(2)),
                    int(match.group(3)),
                    tzinfo=timezone.utc,
                )
            except ValueError:
                pass

        # Try dash format: YYYY-MM-DD
        match = _DATE_PATTERN_DASH.search(index_name)
        if match:
            try:
                return datetime(
                    int(match.group(1)),
                    int(match.group(2)),
                    int(match.group(3)),
                    tzinfo=timezone.utc,
                )
            except ValueError:
                pass

        # Try compact format: YYMMDD
        match = _DATE_PATTERN_COMPACT.search(index_name)
        if match:
            try:
                return datetime.strptime(match.group(1), "%y%m%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                pass

        return None

    # ------------------------------------------------------------------
    # Retention window helpers
    # ------------------------------------------------------------------

    def _retention_days_for_tier(self, tier: str) -> int:
        """Return the configured retention days for a given tier."""
        mapping = {
            "hot": self.config.hot_days,
            "warm": self.config.warm_days,
            "cold": self.config.cold_days,
        }
        # Unknown tier uses the shortest retention (cold) as safeguard
        return mapping.get(tier, self.config.cold_days)

    def _cutoff_date_for_tier(self, tier: str) -> datetime:
        """Return the earliest allowed date for indices in *tier*."""
        days = self._retention_days_for_tier(tier)
        return datetime.now(timezone.utc) - timedelta(days=days)

    # ------------------------------------------------------------------
    # Index deletion
    # ------------------------------------------------------------------

    def _delete_index(self, index_name: str) -> bool:
        """Delete a single OpenSearch index. Returns True on success."""
        try:
            self._client.indices.delete(index=index_name)
            logger.info("Deleted index: %s", index_name)
            return True
        except OpenSearchException as exc:
            logger.error("Failed to delete index %s: %s", index_name, exc)
            return False

    # ------------------------------------------------------------------
    # Tiered pruning
    # ------------------------------------------------------------------

    def prune_oldest_indices(self) -> int:
        """Delete indices older than their tier's retention window.

        Processing order: cold (PCAP) first, then warm (Suricata),
        then hot (Zeek).  After each deletion, disk usage is re-checked;
        pruning stops early if usage drops below the threshold.

        Returns the number of indices deleted.
        """
        with self._cleanup_lock:
            indices = self.list_indices()
            if not indices:
                logger.debug("No indices found; nothing to prune")
                return 0

            # Group by tier
            tier_order = ["cold", "warm", "hot"]
            tier_groups: dict[str, list[dict]] = {t: [] for t in tier_order}
            for idx in indices:
                tier = idx["tier"]
                if tier in tier_groups:
                    tier_groups[tier].append(idx)

            deleted = 0

            for tier in tier_order:
                group = tier_groups[tier]
                if not group:
                    continue

                cutoff = self._cutoff_date_for_tier(tier)

                # Sort oldest first
                dated = [idx for idx in group if idx["parsed_date"] is not None]
                dated.sort(key=lambda x: x["parsed_date"])

                for idx in dated:
                    if idx["parsed_date"] >= cutoff:
                        # Remaining indices in this tier are within retention
                        break

                    if self._delete_index(idx["name"]):
                        deleted += 1

                    # Re-check disk after each deletion
                    usage = self.check_disk_usage()
                    if usage < self.config.disk_threshold:
                        logger.info(
                            "Disk usage %.1f%% now below threshold %.1f%%; "
                            "stopping prune (deleted %d indices)",
                            usage * 100,
                            self.config.disk_threshold * 100,
                            deleted,
                        )
                        return deleted

            logger.info("Tiered prune complete: deleted %d indices", deleted)
            return deleted

    # ------------------------------------------------------------------
    # Emergency pruning
    # ------------------------------------------------------------------

    def prune_emergency(self) -> int:
        """Aggressively delete the oldest indices regardless of tier.

        Called when disk usage exceeds the emergency threshold.
        Deletes oldest-first across ALL tiers until usage drops below
        the normal threshold or no more deletable indices remain.

        Returns the number of indices deleted.
        """
        logger.warning(
            "EMERGENCY PRUNE: disk usage exceeds %.1f%% threshold",
            self.config.emergency_threshold * 100,
        )

        with self._cleanup_lock:
            indices = self.list_indices()
            if not indices:
                logger.warning("No indices available for emergency pruning")
                return 0

            # Collect all dated indices, sort oldest first globally
            dated = [idx for idx in indices if idx["parsed_date"] is not None]
            dated.sort(key=lambda x: x["parsed_date"])

            deleted = 0

            for idx in dated:
                if self._delete_index(idx["name"]):
                    deleted += 1

                # Re-check disk after each deletion
                usage = self.check_disk_usage()
                if usage < self.config.disk_threshold:
                    logger.info(
                        "Emergency prune brought disk to %.1f%%; deleted %d indices total",
                        usage * 100,
                        deleted,
                    )
                    return deleted

            logger.warning(
                "Emergency prune exhausted all deletable indices "
                "(deleted %d); disk still at %.1f%%",
                deleted,
                self.check_disk_usage() * 100,
            )
            return deleted

    # ------------------------------------------------------------------
    # C1: Predictive disk exhaustion alerting
    # ------------------------------------------------------------------

    def _record_usage(self, usage_frac: float) -> None:
        """Record a disk usage measurement for trend analysis."""
        self._usage_history.append((datetime.now(timezone.utc), usage_frac))

    def get_disk_prediction(self) -> dict:
        """Calculate predictive disk exhaustion metrics.

        Uses the rolling window of disk usage measurements to project
        when the disk will hit the 80% threshold.

        Returns:
            Dict with:
              - current_usage_pct: current disk usage as 0-100 percentage
              - fill_rate_bytes_per_hour: estimated bytes added per hour
              - hours_until_threshold: projected hours until 80% threshold
                (float('inf') if usage is stable or decreasing, -1 if
                already above threshold)
              - alert_active: True if projected to hit threshold within 48h
        """
        try:
            usage_frac = self.check_disk_usage()
            disk = shutil.disk_usage(self.config.check_path)
        except OSError:
            return {
                "current_usage_pct": -1,
                "fill_rate_bytes_per_hour": 0,
                "hours_until_threshold": float("inf"),
                "alert_active": False,
            }

        current_pct = round(usage_frac * 100, 1)

        # Already above threshold
        if usage_frac >= self.config.disk_threshold:
            self._prediction_alert_active = True
            return {
                "current_usage_pct": current_pct,
                "fill_rate_bytes_per_hour": 0,
                "hours_until_threshold": -1,
                "alert_active": True,
            }

        # Need at least 2 data points for trend calculation
        if len(self._usage_history) < 2:
            return {
                "current_usage_pct": current_pct,
                "fill_rate_bytes_per_hour": 0,
                "hours_until_threshold": float("inf"),
                "alert_active": False,
            }

        # Find the oldest sample within 24h
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=24)
        oldest_in_window = None
        for ts, frac in self._usage_history:
            if ts >= cutoff:
                oldest_in_window = (ts, frac)
                break

        if oldest_in_window is None:
            oldest_in_window = self._usage_history[0]

        oldest_ts, oldest_frac = oldest_in_window
        elapsed_hours = (now - oldest_ts).total_seconds() / 3600.0

        if elapsed_hours < 0.001:  # Avoid division by zero
            return {
                "current_usage_pct": current_pct,
                "fill_rate_bytes_per_hour": 0,
                "hours_until_threshold": float("inf"),
                "alert_active": False,
            }

        # Calculate fill rate
        usage_delta_frac = usage_frac - oldest_frac
        frac_per_hour = usage_delta_frac / elapsed_hours

        # Convert to bytes per hour
        fill_rate_bytes = frac_per_hour * disk.total

        if frac_per_hour <= 0:
            # Usage is stable or decreasing
            self._prediction_alert_active = False
            return {
                "current_usage_pct": current_pct,
                "fill_rate_bytes_per_hour": max(0, fill_rate_bytes),
                "hours_until_threshold": float("inf"),
                "alert_active": False,
            }

        # Project time to threshold
        remaining_frac = self.config.disk_threshold - usage_frac
        hours_until = remaining_frac / frac_per_hour

        # Alert if projected to hit threshold within 48h
        alert = hours_until <= 48.0
        self._prediction_alert_active = alert

        if alert:
            logger.warning(
                "PREDICTIVE ALERT: Disk projected to reach %.0f%% threshold "
                "in %.1f hours (current: %.1f%%, fill rate: %.0f bytes/hour)",
                self.config.disk_threshold * 100,
                hours_until,
                current_pct,
                fill_rate_bytes,
            )

        return {
            "current_usage_pct": current_pct,
            "fill_rate_bytes_per_hour": fill_rate_bytes,
            "hours_until_threshold": hours_until,
            "alert_active": alert,
        }

    # ------------------------------------------------------------------
    # C2: Emergency cascade deletion (90%/95% thresholds)
    # ------------------------------------------------------------------

    def _delete_oldest_pcaps(self, max_delete: int = 10) -> int:
        """Delete the oldest PCAP files from the PCAP directory.

        Args:
            max_delete: Maximum number of PCAP files to delete per call.

        Returns:
            Number of PCAP files deleted.
        """
        pcap_dir = Path(self.config.pcap_dir)
        if not pcap_dir.exists():
            logger.debug("PCAP directory %s does not exist", pcap_dir)
            return 0

        # Collect PCAP files sorted by modification time (oldest first)
        pcap_files = sorted(
            pcap_dir.glob("*.pcap"),
            key=lambda p: p.stat().st_mtime,
        )

        deleted = 0
        for pcap_file in pcap_files[:max_delete]:
            try:
                # Also remove the checksum sidecar if it exists
                for ext in (".xxh3", ".sha256"):
                    sidecar = pcap_file.parent / f"{pcap_file.name}{ext}"
                    if sidecar.exists():
                        sidecar.unlink()

                pcap_file.unlink()
                deleted += 1
                logger.warning("Emergency deleted PCAP: %s", pcap_file.name)
            except OSError as exc:
                logger.error("Failed to delete PCAP %s: %s", pcap_file, exc)

        return deleted

    def _set_capture_stop_flag(self) -> None:
        """Write the stop-capture flag file to halt PCAP capture."""
        flag_path = Path(self.config.capture_stop_flag)
        try:
            flag_path.parent.mkdir(parents=True, exist_ok=True)
            flag_path.write_text(
                f"stopped by storage manager at {datetime.now(timezone.utc).isoformat()}\n",
                encoding="utf-8",
            )
            logger.warning(
                "CAPTURE STOPPED: Wrote stop flag %s (disk critical)", flag_path
            )
        except OSError as exc:
            logger.error("Failed to write capture stop flag: %s", exc)

    def _clear_capture_stop_flag(self) -> None:
        """Remove the stop-capture flag file to resume PCAP capture."""
        flag_path = Path(self.config.capture_stop_flag)
        try:
            if flag_path.exists():
                flag_path.unlink()
                logger.info(
                    "CAPTURE RESUMED: Cleared stop flag %s", flag_path
                )
        except OSError as exc:
            logger.error("Failed to clear capture stop flag: %s", exc)

    def is_capture_stopped(self) -> bool:
        """Check whether the capture stop flag is currently set."""
        return Path(self.config.capture_stop_flag).exists()

    def emergency_cascade(self) -> int:
        """Execute emergency cascade deletion based on disk usage level.

        At 90%: prune oldest OpenSearch indices regardless of retention,
                then prune oldest PCAPs.
        At 95%: additionally stop PCAP capture via flag file.
        Below 85%: resume normal operation, clear stop-capture flag.

        Returns:
            Total number of items (indices + PCAPs) deleted.
        """
        try:
            usage = self.check_disk_usage()
        except OSError as exc:
            logger.error("Cannot check disk for emergency cascade: %s", exc)
            return 0

        total_deleted = 0

        if usage >= self.config.critical_threshold:
            # 95%+ — stop capture AND aggressive pruning
            logger.warning(
                "CRITICAL: Disk at %.1f%% >= %.1f%% — stopping capture "
                "and starting aggressive pruning",
                usage * 100,
                self.config.critical_threshold * 100,
            )
            self._set_capture_stop_flag()
            total_deleted += self.prune_emergency()
            total_deleted += self._delete_oldest_pcaps(max_delete=20)

        elif usage >= self.config.emergency_threshold:
            # 90%+ — aggressive pruning (indices + PCAPs)
            logger.warning(
                "EMERGENCY: Disk at %.1f%% >= %.1f%% — starting cascade deletion",
                usage * 100,
                self.config.emergency_threshold * 100,
            )
            total_deleted += self.prune_emergency()
            total_deleted += self._delete_oldest_pcaps(max_delete=10)

        # Check if we've recovered below resume threshold
        try:
            usage_after = self.check_disk_usage()
        except OSError:
            usage_after = usage

        if usage_after < self.config.resume_threshold:
            if self.is_capture_stopped():
                logger.info(
                    "Disk at %.1f%% < resume threshold %.1f%% — resuming capture",
                    usage_after * 100,
                    self.config.resume_threshold * 100,
                )
                self._clear_capture_stop_flag()

        return total_deleted

    # ------------------------------------------------------------------
    # C3: ILM policy verification on daemon startup
    # ------------------------------------------------------------------

    def verify_ilm_policy(self) -> dict[str, str]:
        """Verify that ILM/ISM policies exist in OpenSearch, recreating if needed.

        Checks for the three NetTap ISM policies (hot, warm, cold). If any
        are missing or corrupted, recreates them from the bundled policy
        template at ``config/opensearch/ilm-policy.json``.

        Returns:
            Dict mapping policy_name -> status ("exists", "created", "error: ...").
        """
        from storage.ilm import apply_ilm_policies

        # Determine policy file path
        policy_path = self.config.ilm_policy_path
        if not policy_path:
            # Try common locations
            candidates = [
                os.environ.get("ILM_POLICY_PATH", ""),
                "/opt/nettap/config/opensearch/ilm-policy.json",
                os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                    "config",
                    "opensearch",
                    "ilm-policy.json",
                ),
            ]
            for candidate in candidates:
                if candidate and os.path.isfile(candidate):
                    policy_path = candidate
                    break

        if not policy_path or not os.path.isfile(policy_path):
            msg = f"ILM policy file not found (tried: {policy_path or 'no candidates'})"
            logger.error(msg)
            return {"_error": f"error: {msg}"}

        logger.info("Verifying ILM policies from %s", policy_path)

        try:
            results = apply_ilm_policies(
                self.opensearch_url,
                policy_path=policy_path,
                http_auth=self._http_auth,
            )
            self._ilm_verified = True

            # Log summary
            for name, status in results.items():
                if status == "created":
                    logger.warning("ILM policy '%s' was MISSING — recreated", name)
                elif status.startswith("error"):
                    logger.error("ILM policy '%s' verification failed: %s", name, status)
                else:
                    logger.info("ILM policy '%s': %s", name, status)

            return results

        except Exception as exc:
            logger.error("ILM policy verification failed: %s", exc)
            return {"_error": f"error: {exc}"}

    # ------------------------------------------------------------------
    # C4: Per-tier disk accounting
    # ------------------------------------------------------------------

    def get_tier_usage(self) -> dict:
        """Calculate disk usage broken down by storage tier.

        Queries OpenSearch for index-level storage stats and checks
        the PCAP directory for file sizes.

        Returns:
            Dict with:
              - hot_bytes: total bytes used by Zeek indices
              - warm_bytes: total bytes used by Suricata indices
              - cold_bytes: total bytes used by Arkime indices + PCAP files
              - total_bytes: sum of all tiers
              - disk_capacity_bytes: total disk capacity
        """
        tier_bytes: dict[str, int] = {"hot": 0, "warm": 0, "cold": 0}

        # Query OpenSearch index stats for size per index
        try:
            stats = self._client.indices.stats(metric="store")
            indices_stats = stats.get("indices", {})
            for index_name, index_data in indices_stats.items():
                if index_name.startswith("."):
                    continue
                tier = self._parse_index_tier(index_name)
                if tier in tier_bytes:
                    size = index_data.get("total", {}).get("store", {}).get(
                        "size_in_bytes", 0
                    )
                    tier_bytes[tier] += size
        except OpenSearchException as exc:
            logger.error("Failed to query index stats for tier accounting: %s", exc)

        # Add PCAP file sizes to cold tier
        pcap_dir = Path(self.config.pcap_dir)
        if pcap_dir.exists():
            try:
                for pcap_file in pcap_dir.glob("*.pcap"):
                    try:
                        tier_bytes["cold"] += pcap_file.stat().st_size
                    except OSError:
                        pass
            except OSError as exc:
                logger.error("Failed to scan PCAP directory: %s", exc)

        total = sum(tier_bytes.values())

        # Get disk capacity
        try:
            disk = shutil.disk_usage(self.config.check_path)
            capacity = disk.total
        except OSError:
            capacity = 0

        return {
            "hot_bytes": tier_bytes["hot"],
            "warm_bytes": tier_bytes["warm"],
            "cold_bytes": tier_bytes["cold"],
            "total_bytes": total,
            "disk_capacity_bytes": capacity,
        }

    # ------------------------------------------------------------------
    # Manual data cleanup (preview + execute)
    # ------------------------------------------------------------------

    def preview_cleanup(self, older_than_days: int) -> dict:
        """Calculate what would be deleted by a manual cleanup.

        Returns a preview of indices and PCAP files older than the cutoff
        date, with their sizes, without actually deleting anything.

        Args:
            older_than_days: Delete data older than this many days.

        Returns:
            Dict with indices, pcap_files, totals, and cutoff_date.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=older_than_days)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Get indices with date parsing
        indices = self.list_indices()

        # Get per-index byte sizes from stats API
        index_sizes: dict[str, int] = {}
        try:
            stats = self._client.indices.stats(metric="store")
            for idx_name, idx_data in stats.get("indices", {}).items():
                index_sizes[idx_name] = (
                    idx_data.get("total", {})
                    .get("store", {})
                    .get("size_in_bytes", 0)
                )
        except OpenSearchException as exc:
            logger.error("Failed to get index stats for cleanup preview: %s", exc)

        # Filter indices older than cutoff, protect today
        target_indices = []
        total_index_bytes = 0
        for idx in indices:
            parsed = idx.get("parsed_date")
            if parsed is None:
                continue
            # Never delete today's active index
            if parsed >= today:
                continue
            if parsed < cutoff:
                size_bytes = index_sizes.get(idx["name"], 0)
                target_indices.append({
                    "name": idx["name"],
                    "size_bytes": size_bytes,
                    "tier": idx["tier"],
                    "parsed_date": parsed.isoformat(),
                })
                total_index_bytes += size_bytes

        # Scan PCAP files older than cutoff
        target_pcaps = []
        total_pcap_bytes = 0
        pcap_dir = Path(self.config.pcap_dir)
        if pcap_dir.exists():
            try:
                for pcap_file in pcap_dir.glob("*.pcap"):
                    try:
                        stat = pcap_file.stat()
                        file_time = datetime.fromtimestamp(
                            stat.st_mtime, tz=timezone.utc
                        )
                        if file_time < cutoff:
                            target_pcaps.append({
                                "name": pcap_file.name,
                                "size_bytes": stat.st_size,
                                "modified": file_time.isoformat(),
                            })
                            total_pcap_bytes += stat.st_size
                    except OSError:
                        pass
            except OSError as exc:
                logger.error("Failed to scan PCAP dir for cleanup preview: %s", exc)

        return {
            "indices": target_indices,
            "pcap_files": target_pcaps,
            "total_indices": len(target_indices),
            "total_pcap_files": len(target_pcaps),
            "total_size_bytes": total_index_bytes + total_pcap_bytes,
            "index_size_bytes": total_index_bytes,
            "pcap_size_bytes": total_pcap_bytes,
            "cutoff_date": cutoff.isoformat(),
            "estimated_freed_bytes": total_index_bytes + total_pcap_bytes,
        }

    def execute_cleanup(self, older_than_days: int) -> dict:
        """Execute manual data cleanup, deleting indices and PCAPs older than cutoff.

        Acquires the cleanup lock to prevent races with automatic prune cycles.

        Args:
            older_than_days: Delete data older than this many days.

        Returns:
            Dict with deleted counts, freed bytes estimate, and any errors.

        Raises:
            RuntimeError: If the cleanup lock cannot be acquired (auto-prune running).
        """
        if not self._cleanup_lock.acquire(blocking=False):
            raise RuntimeError(
                "A storage maintenance cycle is currently running. "
                "Please try again in a few minutes."
            )

        try:
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(days=older_than_days)
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)

            # Get indices
            indices = self.list_indices()

            # Get byte sizes for reporting
            index_sizes: dict[str, int] = {}
            try:
                stats = self._client.indices.stats(metric="store")
                for idx_name, idx_data in stats.get("indices", {}).items():
                    index_sizes[idx_name] = (
                        idx_data.get("total", {})
                        .get("store", {})
                        .get("size_in_bytes", 0)
                    )
            except OpenSearchException:
                pass

            deleted_indices = 0
            deleted_pcaps = 0
            freed_bytes = 0
            errors: list[str] = []

            # Delete indices older than cutoff
            for idx in indices:
                parsed = idx.get("parsed_date")
                if parsed is None:
                    continue
                if parsed >= today:
                    continue
                if parsed < cutoff:
                    size = index_sizes.get(idx["name"], 0)
                    if self._delete_index(idx["name"]):
                        deleted_indices += 1
                        freed_bytes += size
                    else:
                        errors.append(f"Failed to delete index: {idx['name']}")

            # Delete PCAP files older than cutoff
            pcap_dir = Path(self.config.pcap_dir)
            if pcap_dir.exists():
                try:
                    for pcap_file in sorted(
                        pcap_dir.glob("*.pcap"),
                        key=lambda p: p.stat().st_mtime,
                    ):
                        try:
                            stat = pcap_file.stat()
                            file_time = datetime.fromtimestamp(
                                stat.st_mtime, tz=timezone.utc
                            )
                            if file_time < cutoff:
                                file_size = stat.st_size
                                # Remove checksum sidecars
                                for ext in (".xxh3", ".sha256"):
                                    sidecar = pcap_file.parent / f"{pcap_file.name}{ext}"
                                    if sidecar.exists():
                                        sidecar.unlink()
                                pcap_file.unlink()
                                deleted_pcaps += 1
                                freed_bytes += file_size
                        except OSError as exc:
                            errors.append(f"Failed to delete PCAP {pcap_file.name}: {exc}")
                except OSError as exc:
                    errors.append(f"Failed to scan PCAP directory: {exc}")

            logger.info(
                "Manual cleanup complete: deleted %d indices + %d PCAPs, "
                "freed ~%d bytes, older_than_days=%d",
                deleted_indices,
                deleted_pcaps,
                freed_bytes,
                older_than_days,
            )

            return {
                "deleted_indices": deleted_indices,
                "deleted_pcap_files": deleted_pcaps,
                "freed_bytes_estimate": freed_bytes,
                "errors": errors,
                "cutoff_date": cutoff.isoformat(),
            }
        finally:
            self._cleanup_lock.release()

    # ------------------------------------------------------------------
    # C6: Re-index from logs recovery path
    # ------------------------------------------------------------------

    def reindex_from_logs(
        self,
        log_dir: str,
        index_pattern: str = "zeek-recovered-{date}",
        batch_size: int = 500,
    ) -> dict:
        """Rebuild OpenSearch indices from raw Zeek JSON log files on disk.

        This is a recovery feature used when OpenSearch data is corrupted.
        Reads JSON files line-by-line and bulk-indexes them into OpenSearch.

        Args:
            log_dir: Directory containing Zeek JSON log files.
            index_pattern: Index name pattern. ``{date}`` is replaced with
                the current date (YYYY.MM.DD).
            batch_size: Number of documents per bulk request.

        Returns:
            Dict with:
              - files_processed: number of JSON files read
              - documents_indexed: total documents successfully indexed
              - errors: number of bulk indexing errors
              - index_name: the target index name used
        """
        log_path = Path(log_dir)
        if not log_path.exists() or not log_path.is_dir():
            logger.error("Log directory does not exist: %s", log_dir)
            return {
                "files_processed": 0,
                "documents_indexed": 0,
                "errors": 0,
                "index_name": "",
            }

        date_str = datetime.now(timezone.utc).strftime("%Y.%m.%d")
        index_name = index_pattern.replace("{date}", date_str)

        files_processed = 0
        docs_indexed = 0
        errors = 0

        # Collect JSON log files
        json_files = sorted(log_path.glob("*.json"))
        if not json_files:
            # Also try .log files that may contain JSON
            json_files = sorted(log_path.glob("*.log"))

        logger.info(
            "Re-indexing from %d files in %s -> %s",
            len(json_files),
            log_dir,
            index_name,
        )

        for json_file in json_files:
            files_processed += 1
            batch: list[dict] = []

            try:
                with open(json_file, "r", encoding="utf-8", errors="replace") as f:
                    for line_num, line in enumerate(f, 1):
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        try:
                            doc = json.loads(line)
                            batch.append(doc)
                        except json.JSONDecodeError:
                            errors += 1
                            if errors <= 10:
                                logger.warning(
                                    "Skipping invalid JSON at %s:%d",
                                    json_file.name,
                                    line_num,
                                )
                            continue

                        if len(batch) >= batch_size:
                            indexed, errs = self._bulk_index(index_name, batch)
                            docs_indexed += indexed
                            errors += errs
                            batch = []

                # Flush remaining batch
                if batch:
                    indexed, errs = self._bulk_index(index_name, batch)
                    docs_indexed += indexed
                    errors += errs

            except OSError as exc:
                logger.error("Failed to read log file %s: %s", json_file, exc)
                errors += 1

            logger.info(
                "Processed %s (%d/%d files, %d docs so far)",
                json_file.name,
                files_processed,
                len(json_files),
                docs_indexed,
            )

        logger.info(
            "Re-index complete: %d files, %d documents indexed, %d errors",
            files_processed,
            docs_indexed,
            errors,
        )

        return {
            "files_processed": files_processed,
            "documents_indexed": docs_indexed,
            "errors": errors,
            "index_name": index_name,
        }

    def _bulk_index(self, index_name: str, docs: list[dict]) -> tuple[int, int]:
        """Bulk-index a batch of documents into OpenSearch.

        Args:
            index_name: Target index name.
            docs: List of document dicts to index.

        Returns:
            Tuple of (successful_count, error_count).
        """
        if not docs:
            return 0, 0

        # Build bulk request body
        bulk_body: list[dict] = []
        for doc in docs:
            bulk_body.append({"index": {"_index": index_name}})
            bulk_body.append(doc)

        try:
            response = self._client.bulk(body=bulk_body)
            error_count = 0
            success_count = 0
            if response.get("errors"):
                for item in response.get("items", []):
                    action = item.get("index", {})
                    if action.get("error"):
                        error_count += 1
                    else:
                        success_count += 1
            else:
                success_count = len(docs)
            return success_count, error_count
        except OpenSearchException as exc:
            logger.error("Bulk index failed: %s", exc)
            return 0, len(docs)

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    def run_cycle(self) -> None:
        """Execute one maintenance cycle: check disk, prune if needed.

        Decision flow:
          1. Verify ILM policies on first run (C3)
          2. Check current disk usage and record for trending (C1)
          3. If above critical_threshold (95%) -> cascade with capture stop (C2)
          4. Elif above emergency_threshold (90%) -> cascade deletion (C2)
          5. Elif above disk_threshold (80%) -> ``prune_oldest_indices()``
          6. Else check if capture can be resumed (C2)
          7. Run predictive exhaustion check (C1)
        """
        # C3: Verify ILM policies on first run
        if not self._ilm_verified:
            try:
                self.verify_ilm_policy()
            except Exception:
                logger.exception("ILM policy verification failed on startup")

        try:
            usage = self.check_disk_usage()
        except OSError as exc:
            logger.error(
                "Cannot check disk usage on '%s': %s",
                self.config.check_path,
                exc,
            )
            return

        # C1: Record usage for predictive alerting
        self._record_usage(usage)

        logger.debug("Disk usage: %.1f%%", usage * 100)

        if usage >= self.config.critical_threshold:
            # C2: 95%+ — stop capture and aggressive cascade
            logger.warning(
                "Disk usage %.1f%% >= critical threshold %.1f%% — "
                "stopping capture and starting cascade deletion",
                usage * 100,
                self.config.critical_threshold * 100,
            )
            deleted = self.emergency_cascade()
            logger.info("Emergency cascade deleted %d items", deleted)

        elif usage >= self.config.emergency_threshold:
            # C2: 90%+ — emergency cascade (no capture stop)
            logger.warning(
                "Disk usage %.1f%% >= emergency threshold %.1f%% — "
                "starting emergency cascade",
                usage * 100,
                self.config.emergency_threshold * 100,
            )
            deleted = self.emergency_cascade()
            logger.info("Emergency cascade deleted %d items", deleted)

        elif usage >= self.config.disk_threshold:
            logger.warning(
                "Disk usage %.1f%% >= threshold %.1f%% — starting tiered prune",
                usage * 100,
                self.config.disk_threshold * 100,
            )
            deleted = self.prune_oldest_indices()
            logger.info("Tiered prune cycle deleted %d indices", deleted)

        else:
            logger.debug(
                "Disk usage %.1f%% within threshold (%.1f%%); no action needed",
                usage * 100,
                self.config.disk_threshold * 100,
            )
            # C2: Resume capture if we're below resume threshold
            if usage < self.config.resume_threshold and self.is_capture_stopped():
                logger.info(
                    "Disk at %.1f%% < resume threshold %.1f%% — resuming capture",
                    usage * 100,
                    self.config.resume_threshold * 100,
                )
                self._clear_capture_stop_flag()

        # C1: Predictive exhaustion check
        try:
            self.get_disk_prediction()
        except Exception:
            logger.exception("Predictive exhaustion check failed")

    # ------------------------------------------------------------------
    # Status reporting (for HTTP API)
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Return current storage status for the HTTP API.

        Returns a dict matching the frontend's StorageStatus interface:
          - disk_total_bytes, disk_used_bytes, disk_free_bytes: absolute byte values
          - disk_usage_percent: usage as 0-100 number (NOT string, NOT fraction)
          - hot_days, warm_days, cold_days: retention days (top-level)
          - disk_threshold_percent, emergency_threshold_percent: 0-100 numbers
          - estimated_daily_gb: estimated daily ingest size
          - source: "daemon"
          - index_counts, total_indices: index metadata
        """
        try:
            usage_frac = self.check_disk_usage()
            disk = shutil.disk_usage(self.config.check_path)
            disk_total_bytes = disk.total
            disk_used_bytes = disk.used
            disk_free_bytes = disk.free
            disk_total_gb = round(disk.total / (1024**3), 2)
            disk_used_gb = round(disk.used / (1024**3), 2)
            disk_free_gb = round(disk.free / (1024**3), 2)
        except OSError:
            usage_frac = -1.0
            disk_total_bytes = 0
            disk_used_bytes = 0
            disk_free_bytes = 0
            disk_total_gb = 0
            disk_used_gb = 0
            disk_free_gb = 0

        try:
            indices = self.list_indices()
        except Exception:
            indices = []

        # Count indices per tier
        tier_counts: dict[str, int] = {
            "hot": 0,
            "warm": 0,
            "cold": 0,
            "unknown": 0,
        }
        for idx in indices:
            tier = idx.get("tier", "unknown")
            tier_counts[tier] = tier_counts.get(tier, 0) + 1

        return {
            # Absolute disk values (bytes) — required by frontend formatBytes()
            "disk_total_bytes": disk_total_bytes,
            "disk_used_bytes": disk_used_bytes,
            "disk_free_bytes": disk_free_bytes,
            # Absolute disk values (GB) — human-readable convenience
            "disk_total_gb": disk_total_gb,
            "disk_used_gb": disk_used_gb,
            "disk_free_gb": disk_free_gb,
            "disk_usage_percent": round(usage_frac * 100, 1),
            # Retention days — top-level (frontend reads these directly)
            "hot_days": self.config.hot_days,
            "warm_days": self.config.warm_days,
            "cold_days": self.config.cold_days,
            # Thresholds as 0-100 percentages (not 0-1 fractions)
            "disk_threshold_percent": round(self.config.disk_threshold * 100),
            "emergency_threshold_percent": round(
                self.config.emergency_threshold * 100
            ),
            # Estimates
            "estimated_daily_gb": 1.2,
            "source": "daemon",
            # Index metadata
            "index_counts": tier_counts,
            "total_indices": len(indices),
            # Legacy fields (backward compat)
            "disk_usage": round(usage_frac, 4),
            "disk_threshold": self.config.disk_threshold,
            "emergency_threshold": self.config.emergency_threshold,
            "check_path": self.config.check_path,
            "retention": {
                "hot_days": self.config.hot_days,
                "warm_days": self.config.warm_days,
                "cold_days": self.config.cold_days,
            },
        }
