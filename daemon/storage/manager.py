"""
NetTap Storage Manager

Monitors disk usage and enforces rolling retention policies for
Zeek logs, Suricata alerts, and PCAP data via OpenSearch ILM.
"""

import os
import logging
import shutil
from dataclasses import dataclass

logger = logging.getLogger("nettap.storage")


@dataclass
class RetentionConfig:
    hot_days: int = 90      # Zeek metadata
    warm_days: int = 180    # Suricata alerts
    cold_days: int = 30     # Raw PCAP
    disk_threshold: float = 0.80  # Trigger early pruning at 80%


class StorageManager:
    """Manages disk utilization and triggers retention pruning."""

    def __init__(self, config: RetentionConfig, opensearch_url: str):
        self.config = config
        self.opensearch_url = opensearch_url

    def check_disk_usage(self, path: str = "/") -> float:
        """Returns disk usage as a fraction (0.0 to 1.0)."""
        usage = shutil.disk_usage(path)
        return usage.used / usage.total

    def should_prune(self, path: str = "/") -> bool:
        """Check if disk usage exceeds the configured threshold."""
        usage = self.check_disk_usage(path)
        if usage >= self.config.disk_threshold:
            logger.warning(
                "Disk usage %.1f%% exceeds threshold %.1f%%",
                usage * 100,
                self.config.disk_threshold * 100,
            )
            return True
        return False

    def prune_oldest_indices(self):
        """Delete oldest OpenSearch indices to reclaim space."""
        # TODO: Query OpenSearch for indices sorted by date,
        # delete oldest beyond retention window
        raise NotImplementedError

    def run_cycle(self):
        """Execute one maintenance cycle: check disk, prune if needed."""
        if self.should_prune():
            logger.info("Starting early pruning cycle")
            self.prune_oldest_indices()
        else:
            logger.debug("Disk usage within threshold, no action needed")
