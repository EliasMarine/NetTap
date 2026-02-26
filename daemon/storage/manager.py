"""
NetTap Storage Manager

Monitors disk usage and enforces rolling retention policies for
Zeek logs, Suricata alerts, and PCAP data via OpenSearch index management.

Phase 2 rewrite: Uses opensearch-py client with tiered pruning,
emergency pruning, and status reporting.
"""

import re
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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

    hot_days: int = 90            # Zeek metadata retention (days)
    warm_days: int = 180          # Suricata alert retention (days)
    cold_days: int = 30           # Raw PCAP / Arkime retention (days)
    disk_threshold: float = 0.80  # Trigger pruning at 80%
    emergency_threshold: float = 0.90  # Aggressive pruning at 90%
    check_path: str = "/"         # Filesystem path for disk usage checks


class StorageManager:
    """Manages disk utilization and enforces rolling retention via OpenSearch.

    Monitors disk usage against configurable thresholds and deletes the
    oldest OpenSearch indices tier-by-tier (cold -> warm -> hot) to
    reclaim space.  An emergency mode bypasses tier ordering when disk
    usage exceeds the emergency threshold.
    """

    def __init__(self, config: RetentionConfig, opensearch_url: str):
        self.config = config
        self.opensearch_url = opensearch_url

        # Parse URL for opensearch-py client
        self._client = self._create_client(opensearch_url)

    # ------------------------------------------------------------------
    # Client helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _create_client(url: str) -> OpenSearch:
        """Create an OpenSearch client from a URL string.

        Supports both http:// and https:// URLs.  For https, SSL
        certificate verification is disabled by default (typical for
        internal Malcolm deployments with self-signed certificates).
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

        return OpenSearch(
            hosts=[{"host": host, "port": port}],
            use_ssl=use_ssl,
            verify_certs=False,
            ssl_show_warn=False,
            timeout=30,
            max_retries=3,
            retry_on_timeout=True,
        )

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

            indices.append({
                "name": name,
                "size": size_str,
                "creation_date": creation,
                "tier": tier,
                "parsed_date": parsed_date,
            })

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
                return datetime.strptime(
                    match.group(1), "%y%m%d"
                ).replace(tzinfo=timezone.utc)
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
            dated = [
                idx for idx in group if idx["parsed_date"] is not None
            ]
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

        logger.info(
            "Tiered prune complete: deleted %d indices", deleted
        )
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

        indices = self.list_indices()
        if not indices:
            logger.warning("No indices available for emergency pruning")
            return 0

        # Collect all dated indices, sort oldest first globally
        dated = [
            idx for idx in indices if idx["parsed_date"] is not None
        ]
        dated.sort(key=lambda x: x["parsed_date"])

        deleted = 0

        for idx in dated:
            if self._delete_index(idx["name"]):
                deleted += 1

            # Re-check disk after each deletion
            usage = self.check_disk_usage()
            if usage < self.config.disk_threshold:
                logger.info(
                    "Emergency prune brought disk to %.1f%%; "
                    "deleted %d indices total",
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
    # Main cycle
    # ------------------------------------------------------------------

    def run_cycle(self) -> None:
        """Execute one maintenance cycle: check disk, prune if needed.

        Decision flow:
          1. Check current disk usage
          2. If above emergency_threshold -> ``prune_emergency()``
          3. Elif above disk_threshold -> ``prune_oldest_indices()``
          4. Otherwise log and return
        """
        try:
            usage = self.check_disk_usage()
        except OSError as exc:
            logger.error(
                "Cannot check disk usage on '%s': %s",
                self.config.check_path,
                exc,
            )
            return

        logger.debug("Disk usage: %.1f%%", usage * 100)

        if usage >= self.config.emergency_threshold:
            logger.warning(
                "Disk usage %.1f%% >= emergency threshold %.1f%% — "
                "starting emergency prune",
                usage * 100,
                self.config.emergency_threshold * 100,
            )
            deleted = self.prune_emergency()
            logger.info("Emergency prune cycle deleted %d indices", deleted)

        elif usage >= self.config.disk_threshold:
            logger.warning(
                "Disk usage %.1f%% >= threshold %.1f%% — "
                "starting tiered prune",
                usage * 100,
                self.config.disk_threshold * 100,
            )
            deleted = self.prune_oldest_indices()
            logger.info("Tiered prune cycle deleted %d indices", deleted)

        else:
            logger.debug(
                "Disk usage %.1f%% within threshold (%.1f%%); "
                "no action needed",
                usage * 100,
                self.config.disk_threshold * 100,
            )

    # ------------------------------------------------------------------
    # Status reporting (for HTTP API)
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Return current storage status for the HTTP API.

        Returns a dict with:
          - disk_usage: current usage as fraction
          - disk_usage_percent: usage as percentage string
          - disk_threshold: configured threshold
          - emergency_threshold: configured emergency threshold
          - check_path: filesystem path being monitored
          - index_counts: dict of tier -> count of indices
          - total_indices: total number of tracked indices
          - retention: dict of tier retention days
        """
        try:
            usage = self.check_disk_usage()
        except OSError:
            usage = -1.0

        indices = self.list_indices()

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
            "disk_usage": round(usage, 4),
            "disk_usage_percent": f"{usage * 100:.1f}%",
            "disk_threshold": self.config.disk_threshold,
            "emergency_threshold": self.config.emergency_threshold,
            "check_path": self.config.check_path,
            "index_counts": tier_counts,
            "total_indices": len(indices),
            "retention": {
                "hot_days": self.config.hot_days,
                "warm_days": self.config.warm_days,
                "cold_days": self.config.cold_days,
            },
        }
