"""
Tests for manual data cleanup feature — StorageManager.preview_cleanup()
and StorageManager.execute_cleanup().

Covers date filtering, today's index protection, PCAP scanning,
lock contention, and error handling.
"""

import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from opensearchpy import OpenSearchException

from storage.manager import RetentionConfig, StorageManager


def _make_manager(mock_client, config=None):
    """Create a StorageManager with a mocked OpenSearch client."""
    mgr = StorageManager.__new__(StorageManager)
    mgr.config = config or RetentionConfig(pcap_dir="/tmp/fake-pcap")
    mgr.opensearch_url = "https://localhost:9200"
    mgr._http_auth = None
    mgr._client = mock_client
    mgr._usage_history = deque(maxlen=StorageManager._USAGE_HISTORY_MAX)
    mgr._prediction_alert_active = False
    mgr._ilm_verified = True
    mgr._cleanup_lock = threading.Lock()
    return mgr


def _make_index_entry(name, size_str="50mb", date_str=None):
    """Create a fake _cat/indices entry."""
    return {
        "index": name,
        "store.size": size_str,
        "pri.store.size": size_str,
        "creation.date.string": date_str,
    }


# =========================================================================
# preview_cleanup
# =========================================================================


class TestPreviewCleanup:
    def test_filters_indices_by_date(self):
        """Only indices older than cutoff should appear in preview."""
        client = MagicMock()
        # 90 days ago and 10 days ago
        old_date = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y.%m.%d")
        recent_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y.%m.%d")

        client.cat.indices.return_value = [
            _make_index_entry(f"zeek-conn-{old_date}", "50mb", f"{old_date}T00:00:00.000Z"),
            _make_index_entry(f"zeek-dns-{recent_date}", "30mb", f"{recent_date}T00:00:00.000Z"),
        ]
        client.indices.stats.return_value = {
            "indices": {
                f"zeek-conn-{old_date}": {"total": {"store": {"size_in_bytes": 50_000_000}}},
                f"zeek-dns-{recent_date}": {"total": {"store": {"size_in_bytes": 30_000_000}}},
            }
        }

        mgr = _make_manager(client)
        result = mgr.preview_cleanup(older_than_days=30)

        assert result["total_indices"] == 1
        assert result["indices"][0]["name"] == f"zeek-conn-{old_date}"
        assert result["index_size_bytes"] == 50_000_000

    def test_protects_todays_index(self):
        """Today's index must never appear in preview."""
        client = MagicMock()
        today = datetime.now(timezone.utc).strftime("%Y.%m.%d")

        client.cat.indices.return_value = [
            _make_index_entry(f"zeek-conn-{today}", "100mb", f"{today}T00:00:00.000Z"),
        ]
        client.indices.stats.return_value = {
            "indices": {
                f"zeek-conn-{today}": {"total": {"store": {"size_in_bytes": 100_000_000}}},
            }
        }

        mgr = _make_manager(client)
        # Even with older_than_days=0 (min is 1 in API, but test the logic)
        result = mgr.preview_cleanup(older_than_days=1)

        assert result["total_indices"] == 0
        assert result["indices"] == []

    def test_includes_pcap_files(self, tmp_path):
        """PCAP files older than cutoff should appear in preview."""
        client = MagicMock()
        client.cat.indices.return_value = []
        client.indices.stats.return_value = {"indices": {}}

        # Create old and new PCAP files
        old_pcap = tmp_path / "old_capture.pcap"
        old_pcap.write_bytes(b"\x00" * 1000)
        # Set mtime to 60 days ago
        import os
        old_time = (datetime.now() - timedelta(days=60)).timestamp()
        os.utime(old_pcap, (old_time, old_time))

        new_pcap = tmp_path / "new_capture.pcap"
        new_pcap.write_bytes(b"\x00" * 500)

        config = RetentionConfig(pcap_dir=str(tmp_path))
        mgr = _make_manager(client, config)
        result = mgr.preview_cleanup(older_than_days=30)

        assert result["total_pcap_files"] == 1
        assert result["pcap_files"][0]["name"] == "old_capture.pcap"
        assert result["pcap_size_bytes"] == 1000

    def test_handles_opensearch_stats_error(self):
        """Preview should still work if indices.stats fails (sizes will be 0)."""
        client = MagicMock()
        old_date = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y.%m.%d")

        client.cat.indices.return_value = [
            _make_index_entry(f"zeek-conn-{old_date}", "50mb", f"{old_date}T00:00:00.000Z"),
        ]
        client.indices.stats.side_effect = OpenSearchException("connection refused")

        config = RetentionConfig(pcap_dir="/nonexistent")
        mgr = _make_manager(client, config)
        result = mgr.preview_cleanup(older_than_days=30)

        assert result["total_indices"] == 1
        assert result["index_size_bytes"] == 0  # No stats available

    def test_empty_when_no_old_data(self):
        """Preview returns empty when all data is recent."""
        client = MagicMock()
        recent_date = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y.%m.%d")

        client.cat.indices.return_value = [
            _make_index_entry(f"zeek-conn-{recent_date}", "50mb", f"{recent_date}T00:00:00.000Z"),
        ]
        client.indices.stats.return_value = {"indices": {}}

        config = RetentionConfig(pcap_dir="/nonexistent")
        mgr = _make_manager(client, config)
        result = mgr.preview_cleanup(older_than_days=30)

        assert result["total_indices"] == 0
        assert result["total_pcap_files"] == 0
        assert result["estimated_freed_bytes"] == 0

    def test_skips_undated_indices(self):
        """Indices without parseable dates should be skipped."""
        client = MagicMock()
        client.cat.indices.return_value = [
            _make_index_entry("custom-metrics", "5mb", None),
        ]
        client.indices.stats.return_value = {"indices": {}}

        config = RetentionConfig(pcap_dir="/nonexistent")
        mgr = _make_manager(client, config)
        result = mgr.preview_cleanup(older_than_days=1)

        assert result["total_indices"] == 0


# =========================================================================
# execute_cleanup
# =========================================================================


class TestExecuteCleanup:
    def test_deletes_old_indices(self):
        """Old indices should be deleted; recent ones kept."""
        client = MagicMock()
        old_date = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y.%m.%d")
        recent_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y.%m.%d")

        client.cat.indices.return_value = [
            _make_index_entry(f"zeek-conn-{old_date}", "50mb", f"{old_date}T00:00:00.000Z"),
            _make_index_entry(f"zeek-dns-{recent_date}", "30mb", f"{recent_date}T00:00:00.000Z"),
        ]
        client.indices.stats.return_value = {
            "indices": {
                f"zeek-conn-{old_date}": {"total": {"store": {"size_in_bytes": 50_000_000}}},
                f"zeek-dns-{recent_date}": {"total": {"store": {"size_in_bytes": 30_000_000}}},
            }
        }
        client.indices.delete.return_value = {"acknowledged": True}

        config = RetentionConfig(pcap_dir="/nonexistent")
        mgr = _make_manager(client, config)
        result = mgr.execute_cleanup(older_than_days=30)

        assert result["deleted_indices"] == 1
        assert result["freed_bytes_estimate"] == 50_000_000
        client.indices.delete.assert_called_once_with(index=f"zeek-conn-{old_date}")

    def test_deletes_pcap_files(self, tmp_path):
        """Old PCAP files and their sidecars should be deleted."""
        client = MagicMock()
        client.cat.indices.return_value = []
        client.indices.stats.return_value = {"indices": {}}

        # Create old PCAP with sidecar
        old_pcap = tmp_path / "old.pcap"
        old_pcap.write_bytes(b"\x00" * 2000)
        sidecar = tmp_path / "old.pcap.xxh3"
        sidecar.write_text("abc123")
        import os
        old_time = (datetime.now() - timedelta(days=60)).timestamp()
        os.utime(old_pcap, (old_time, old_time))

        config = RetentionConfig(pcap_dir=str(tmp_path))
        mgr = _make_manager(client, config)
        result = mgr.execute_cleanup(older_than_days=30)

        assert result["deleted_pcap_files"] == 1
        assert result["freed_bytes_estimate"] == 2000
        assert not old_pcap.exists()
        assert not sidecar.exists()

    def test_lock_contention_raises(self):
        """Execute should raise RuntimeError if cleanup lock is held."""
        client = MagicMock()
        client.cat.indices.return_value = []
        client.indices.stats.return_value = {"indices": {}}

        config = RetentionConfig(pcap_dir="/nonexistent")
        mgr = _make_manager(client, config)

        # Hold the lock
        mgr._cleanup_lock.acquire()
        try:
            with pytest.raises(RuntimeError, match="maintenance cycle is currently running"):
                mgr.execute_cleanup(older_than_days=30)
        finally:
            mgr._cleanup_lock.release()

    def test_protects_todays_index(self):
        """Today's index must never be deleted."""
        client = MagicMock()
        today = datetime.now(timezone.utc).strftime("%Y.%m.%d")

        client.cat.indices.return_value = [
            _make_index_entry(f"zeek-conn-{today}", "100mb", f"{today}T00:00:00.000Z"),
        ]
        client.indices.stats.return_value = {
            "indices": {
                f"zeek-conn-{today}": {"total": {"store": {"size_in_bytes": 100_000_000}}},
            }
        }

        config = RetentionConfig(pcap_dir="/nonexistent")
        mgr = _make_manager(client, config)
        result = mgr.execute_cleanup(older_than_days=1)

        assert result["deleted_indices"] == 0
        client.indices.delete.assert_not_called()

    def test_reports_deletion_errors(self):
        """Errors during index deletion should be captured, not crash."""
        client = MagicMock()
        old_date = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y.%m.%d")

        client.cat.indices.return_value = [
            _make_index_entry(f"zeek-conn-{old_date}", "50mb", f"{old_date}T00:00:00.000Z"),
        ]
        client.indices.stats.return_value = {"indices": {}}
        client.indices.delete.side_effect = OpenSearchException("delete failed")

        config = RetentionConfig(pcap_dir="/nonexistent")
        mgr = _make_manager(client, config)
        result = mgr.execute_cleanup(older_than_days=30)

        assert result["deleted_indices"] == 0
        assert len(result["errors"]) == 1
        assert "Failed to delete index" in result["errors"][0]

    def test_lock_released_on_error(self):
        """Lock must be released even if cleanup raises an exception."""
        client = MagicMock()
        client.cat.indices.side_effect = Exception("unexpected error")
        client.indices.stats.return_value = {"indices": {}}

        config = RetentionConfig(pcap_dir="/nonexistent")
        mgr = _make_manager(client, config)

        with pytest.raises(Exception, match="unexpected error"):
            mgr.execute_cleanup(older_than_days=30)

        # Lock should be released
        assert mgr._cleanup_lock.acquire(blocking=False)
        mgr._cleanup_lock.release()

    def test_compact_date_format_arkime(self):
        """Arkime compact YYMMDD date format should be correctly parsed."""
        client = MagicMock()
        # 90 days ago in compact format
        old_dt = datetime.now(timezone.utc) - timedelta(days=90)
        compact_date = old_dt.strftime("%y%m%d")

        client.cat.indices.return_value = [
            _make_index_entry(f"arkime_sessions3-{compact_date}", "200mb"),
        ]
        client.indices.stats.return_value = {
            "indices": {
                f"arkime_sessions3-{compact_date}": {"total": {"store": {"size_in_bytes": 200_000_000}}},
            }
        }
        client.indices.delete.return_value = {"acknowledged": True}

        config = RetentionConfig(pcap_dir="/nonexistent")
        mgr = _make_manager(client, config)
        result = mgr.execute_cleanup(older_than_days=30)

        assert result["deleted_indices"] == 1
        assert result["freed_bytes_estimate"] == 200_000_000
