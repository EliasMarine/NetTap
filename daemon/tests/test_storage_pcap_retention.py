"""
Tests for PCAP retention and the disk emergency path in StorageManager.

Covers CR-001 (PCAP is found under the real PCAP_DIR, recursively, and
deleted), CR-002 (emergency prune keeps today's indices and deletes PCAP
first), CR-018 (critical disk really stops pcap-capture) and MS-002
(age-based PCAP retention on every cycle).
"""

import os
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from storage.manager import RetentionConfig, StorageManager
from storage.retention_config import RetentionConfigManager


def _make_manager(config: RetentionConfig, client=None) -> StorageManager:
    """Build a StorageManager without connecting to OpenSearch."""
    mgr = StorageManager.__new__(StorageManager)
    mgr.config = config
    mgr._client = client or MagicMock()
    mgr.opensearch_url = "https://localhost:9200"
    mgr._http_auth = None
    mgr._usage_history = deque(maxlen=StorageManager._USAGE_HISTORY_MAX)
    mgr._prediction_alert_active = False
    mgr._ilm_verified = True
    mgr._last_prune_at = None
    mgr._retention_config_manager = None
    mgr._cleanup_lock = threading.Lock()
    return mgr


def _pcap(path, days_old: float, size: int = 100):
    """Write a PCAP of *size* bytes whose mtime is *days_old* days ago."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)
    ts = (datetime.now(timezone.utc) - timedelta(days=days_old)).timestamp()
    os.utime(path, (ts, ts))
    return path


def _pcap_tree(root):
    """netsniff writes to the volume root; Arkime wrote to arkime-live/."""
    return {
        "arkime_old": _pcap(root / "arkime-live" / "node-260101-1.pcap", 40, 300),
        "netsniff_old": _pcap(root / "netsniff-br0_1.pcap", 35, 200),
        "netsniff_new": _pcap(root / "netsniff-br0_2.pcap", 1, 100),
    }


# =========================================================================
# CR-001: PCAP is found under PCAP_DIR, recursively
# =========================================================================


class TestPcapDir:
    def test_pcap_dir_defaults_to_pcap_dir_env(self, monkeypatch):
        monkeypatch.setenv("PCAP_DIR", "/srv/pcap")
        assert RetentionConfig().pcap_dir == "/srv/pcap"
        # Every builder in retention_config.py gets it too
        assert RetentionConfigManager._from_env().pcap_dir == "/srv/pcap"
        assert RetentionConfigManager._parse_json({}).pcap_dir == "/srv/pcap"

    def test_pcap_dir_default_matches_compose_mount(self, monkeypatch):
        monkeypatch.delenv("PCAP_DIR", raising=False)
        assert RetentionConfig().pcap_dir == "/opt/nettap/pcap"

    def test_oldest_first_is_recursive_and_sorted(self, tmp_path):
        files = _pcap_tree(tmp_path)
        mgr = _make_manager(RetentionConfig(pcap_dir=str(tmp_path)))

        found = [p for p, _ in mgr._pcaps_oldest_first()]

        assert found == [
            files["arkime_old"],
            files["netsniff_old"],
            files["netsniff_new"],
        ]

    def test_oldest_first_skips_files_that_vanish(self, tmp_path):
        """A file rotated away mid-scan must not abort the whole scan."""
        files = _pcap_tree(tmp_path)
        # A dangling symlink is listed by rglob but stat() raises
        # FileNotFoundError, like a file deleted between listing and stat.
        (tmp_path / "rotated.pcap").symlink_to(tmp_path / "gone.pcap")
        mgr = _make_manager(RetentionConfig(pcap_dir=str(tmp_path)))

        found = [p for p, _ in mgr._pcaps_oldest_first()]

        assert len(found) == 3
        assert files["arkime_old"] in found

    def test_delete_oldest_pcaps_reaches_subdirectories(self, tmp_path):
        files = _pcap_tree(tmp_path)
        sidecar = tmp_path / "arkime-live" / "node-260101-1.pcap.xxh3"
        sidecar.write_text("abc")
        mgr = _make_manager(RetentionConfig(pcap_dir=str(tmp_path)))

        deleted = mgr._delete_oldest_pcaps(max_delete=1)

        assert deleted == 1
        assert not files["arkime_old"].exists()
        assert not sidecar.exists()
        assert files["netsniff_old"].exists()

    def test_tier_usage_counts_nested_pcap(self, tmp_path):
        _pcap_tree(tmp_path)
        client = MagicMock()
        client.indices.stats.return_value = {"indices": {}}
        mgr = _make_manager(RetentionConfig(pcap_dir=str(tmp_path)), client)

        assert mgr.get_tier_usage()["cold_bytes"] == 600

    def test_preview_and_execute_cleanup_reach_subdirectories(self, tmp_path):
        files = _pcap_tree(tmp_path)
        client = MagicMock()
        client.cat.indices.return_value = []
        client.indices.stats.return_value = {"indices": {}}
        mgr = _make_manager(RetentionConfig(pcap_dir=str(tmp_path)), client)

        preview = mgr.preview_cleanup(older_than_days=30)
        result = mgr.execute_cleanup(older_than_days=30)

        assert preview["total_pcap_files"] == 2
        assert preview["pcap_size_bytes"] == 500
        assert result["deleted_pcap_files"] == 2
        assert result["freed_bytes_estimate"] == 500
        assert result["errors"] == []
        assert not files["arkime_old"].exists()
        assert not files["netsniff_old"].exists()
        assert files["netsniff_new"].exists()
