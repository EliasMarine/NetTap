"""
Tests for daemon/storage/manager.py — StorageManager.

Covers RetentionConfig defaults and custom values, disk usage helpers,
index tier classification, date parsing, listing/filtering indices,
tiered pruning, emergency pruning, run_cycle behaviour, and status
reporting.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from opensearchpy import OpenSearchException

from storage.manager import RetentionConfig, StorageManager


# =========================================================================
# RetentionConfig
# =========================================================================


class TestRetentionConfig:
    def test_retention_config_defaults(self):
        """Verify default values match the PRD-specified retention periods."""
        cfg = RetentionConfig()
        assert cfg.hot_days == 90
        assert cfg.warm_days == 180
        assert cfg.cold_days == 30
        assert cfg.disk_threshold == 0.80
        assert cfg.emergency_threshold == 0.90
        assert cfg.check_path == "/"

    def test_retention_config_custom(self):
        """Verify custom values including emergency_threshold are stored."""
        cfg = RetentionConfig(
            hot_days=30,
            warm_days=60,
            cold_days=15,
            disk_threshold=0.75,
            emergency_threshold=0.95,
            check_path="/data",
        )
        assert cfg.hot_days == 30
        assert cfg.warm_days == 60
        assert cfg.cold_days == 15
        assert cfg.disk_threshold == 0.75
        assert cfg.emergency_threshold == 0.95
        assert cfg.check_path == "/data"


# =========================================================================
# Disk usage
# =========================================================================


class TestDiskUsage:
    @patch("storage.manager.shutil.disk_usage")
    def test_check_disk_usage_returns_fraction(self, mock_disk_usage, retention_config):
        """Mock shutil.disk_usage and verify result is in 0.0-1.0 range."""
        # Simulate 60% usage: 600 GB used out of 1000 GB total
        mock_disk_usage.return_value = MagicMock(
            total=1_000_000_000_000,
            used=600_000_000_000,
            free=400_000_000_000,
        )

        mgr = StorageManager.__new__(StorageManager)
        mgr.config = retention_config
        mgr._client = MagicMock()

        usage = mgr.check_disk_usage("/")
        assert 0.0 <= usage <= 1.0
        assert abs(usage - 0.6) < 0.001


# =========================================================================
# Index tier classification
# =========================================================================


class TestParseIndexTier:
    def test_parse_index_tier_hot(self):
        """Zeek indices should be classified as hot tier."""
        assert StorageManager._parse_index_tier("zeek-conn-2026.02.25") == "hot"
        assert StorageManager._parse_index_tier("zeek-dns-2026.01.01") == "hot"
        assert StorageManager._parse_index_tier("Zeek-http-2026.03.01") == "hot"

    def test_parse_index_tier_warm(self):
        """Suricata indices should be classified as warm tier."""
        assert StorageManager._parse_index_tier("suricata-alert-2026-01-20") == "warm"
        assert StorageManager._parse_index_tier("suricata-eve-2026.02.10") == "warm"

    def test_parse_index_tier_cold_arkime(self):
        """Arkime indices should be classified as cold tier."""
        assert StorageManager._parse_index_tier("arkime_sessions3-260125") == "cold"
        assert StorageManager._parse_index_tier("arkime-history-v1-260201") == "cold"

    def test_parse_index_tier_cold_sessions(self):
        """Indices with 'sessions' prefix should be classified as cold tier."""
        assert StorageManager._parse_index_tier("sessions3-260130") == "cold"
        assert StorageManager._parse_index_tier("sessions2-daily-260201") == "cold"

    def test_parse_index_tier_unknown(self):
        """Unrecognised prefixes should return 'unknown'."""
        assert StorageManager._parse_index_tier("custom-metrics") == "unknown"
        assert StorageManager._parse_index_tier("grafana-dashboards") == "unknown"
        assert StorageManager._parse_index_tier("logstash-2026.01.01") == "unknown"


# =========================================================================
# Index date parsing
# =========================================================================


class TestParseIndexDate:
    def test_parse_index_date_dot_format(self):
        """Test YYYY.MM.DD (dot-separated) date parsing."""
        result = StorageManager._parse_index_date("zeek-conn-2026.02.25")
        assert result is not None
        assert result == datetime(2026, 2, 25, tzinfo=timezone.utc)

    def test_parse_index_date_dash_format(self):
        """Test YYYY-MM-DD (dash-separated) date parsing."""
        result = StorageManager._parse_index_date("suricata-alert-2026-02-25")
        assert result is not None
        assert result == datetime(2026, 2, 25, tzinfo=timezone.utc)

    def test_parse_index_date_compact_format(self):
        """Test YYMMDD (compact) date parsing used by Arkime."""
        result = StorageManager._parse_index_date("arkime_sessions3-260225")
        assert result is not None
        assert result == datetime(2026, 2, 25, tzinfo=timezone.utc)

    def test_parse_index_date_no_date(self):
        """Test returns None for indices without a recognisable date."""
        result = StorageManager._parse_index_date("custom-metrics")
        assert result is None


# =========================================================================
# list_indices
# =========================================================================


class TestListIndices:
    def test_list_indices_filters_system(
        self, retention_config, mock_opensearch_client, sample_indices
    ):
        """Mock client and verify that dot-prefixed system indices are excluded."""
        mock_opensearch_client.cat.indices.return_value = sample_indices

        mgr = StorageManager.__new__(StorageManager)
        mgr.config = retention_config
        mgr._client = mock_opensearch_client
        mgr.opensearch_url = "http://localhost:9200"

        indices = mgr.list_indices()

        # The sample_indices fixture includes ".opensearch-dashboards"
        names = [idx["name"] for idx in indices]
        assert ".opensearch-dashboards" not in names
        # All non-system indices should be present
        assert "zeek-conn-2026.01.15" in names
        assert "suricata-alert-2026-01-20" in names
        assert "arkime_sessions3-260125" in names

    def test_list_indices_handles_opensearch_error(
        self, retention_config, mock_opensearch_client
    ):
        """Verify returns empty list when OpenSearch raises an error."""
        mock_opensearch_client.cat.indices.side_effect = OpenSearchException(
            "connection refused"
        )

        mgr = StorageManager.__new__(StorageManager)
        mgr.config = retention_config
        mgr._client = mock_opensearch_client
        mgr.opensearch_url = "http://localhost:9200"

        indices = mgr.list_indices()
        assert indices == []


# =========================================================================
# Tiered pruning
# =========================================================================


class TestPruneOldestIndices:
    def _make_manager(self, retention_config, mock_client):
        """Helper to construct a StorageManager without hitting real OpenSearch."""
        mgr = StorageManager.__new__(StorageManager)
        mgr.config = retention_config
        mgr._client = mock_client
        mgr.opensearch_url = "http://localhost:9200"
        return mgr

    def test_prune_oldest_indices_deletes_expired(
        self, retention_config, mock_opensearch_client
    ):
        """Create indices past retention and verify they are deleted."""
        now = datetime.now(timezone.utc)
        # Cold retention = 15 days; create an index 30 days old
        old_cold_date = now - timedelta(days=30)
        old_cold_name = f"arkime_sessions3-{old_cold_date.strftime('%y%m%d')}"

        # Fresh hot index within retention
        fresh_hot_date = now - timedelta(days=5)
        fresh_hot_name = f"zeek-conn-{fresh_hot_date.strftime('%Y.%m.%d')}"

        mock_opensearch_client.cat.indices.return_value = [
            {
                "index": old_cold_name,
                "store.size": "200mb",
                "pri.store.size": "200mb",
                "creation.date.string": old_cold_date.isoformat(),
            },
            {
                "index": fresh_hot_name,
                "store.size": "50mb",
                "pri.store.size": "50mb",
                "creation.date.string": fresh_hot_date.isoformat(),
            },
        ]

        mgr = self._make_manager(retention_config, mock_opensearch_client)

        # Keep disk above threshold after delete so pruning continues
        with patch.object(mgr, "check_disk_usage", return_value=0.85):
            deleted = mgr.prune_oldest_indices()

        # The expired cold index should be deleted
        assert deleted >= 1
        mock_opensearch_client.indices.delete.assert_called_with(index=old_cold_name)

    def test_prune_oldest_indices_respects_tier_order(
        self, retention_config, mock_opensearch_client
    ):
        """Verify cold is deleted before warm before hot."""
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=200)

        # All indices expired (retention: cold=15, warm=60, hot=30)
        cold_name = f"arkime_sessions3-{old.strftime('%y%m%d')}"
        warm_name = f"suricata-alert-{old.strftime('%Y-%m-%d')}"
        hot_name = f"zeek-conn-{old.strftime('%Y.%m.%d')}"

        mock_opensearch_client.cat.indices.return_value = [
            {
                "index": cold_name,
                "store.size": "200mb",
                "pri.store.size": "200mb",
                "creation.date.string": old.isoformat(),
            },
            {
                "index": warm_name,
                "store.size": "10mb",
                "pri.store.size": "10mb",
                "creation.date.string": old.isoformat(),
            },
            {
                "index": hot_name,
                "store.size": "50mb",
                "pri.store.size": "50mb",
                "creation.date.string": old.isoformat(),
            },
        ]

        mgr = self._make_manager(retention_config, mock_opensearch_client)

        # Disk stays above threshold so all tiers are processed
        with patch.object(mgr, "check_disk_usage", return_value=0.85):
            deleted = mgr.prune_oldest_indices()

        assert deleted == 3
        # Verify deletion order: cold first, then warm, then hot
        calls = mock_opensearch_client.indices.delete.call_args_list
        deleted_names = [
            call.kwargs.get("index")
            or call[1].get("index", call[0][0] if call[0] else None)
            for call in calls
        ]
        # Use the call keyword arg "index"
        deleted_names = []
        for call in calls:
            # call is a call object; call[1] is kwargs
            idx_name = call.kwargs.get("index") if call.kwargs else None
            if idx_name is None and call.args:
                idx_name = call.args[0]
            deleted_names.append(idx_name)

        assert deleted_names.index(cold_name) < deleted_names.index(warm_name)
        assert deleted_names.index(warm_name) < deleted_names.index(hot_name)

    def test_prune_oldest_indices_stops_below_threshold(
        self, retention_config, mock_opensearch_client
    ):
        """Verify early exit when disk drops below threshold after a deletion."""
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=200)

        cold1 = f"arkime_sessions3-{old.strftime('%y%m%d')}"
        cold2_date = old + timedelta(days=1)
        cold2 = f"sessions3-{cold2_date.strftime('%y%m%d')}"

        mock_opensearch_client.cat.indices.return_value = [
            {
                "index": cold1,
                "store.size": "200mb",
                "pri.store.size": "200mb",
                "creation.date.string": old.isoformat(),
            },
            {
                "index": cold2,
                "store.size": "180mb",
                "pri.store.size": "180mb",
                "creation.date.string": cold2_date.isoformat(),
            },
        ]

        mgr = self._make_manager(retention_config, mock_opensearch_client)

        # First check returns above threshold; after first deletion, below
        disk_values = iter([0.70])
        with patch.object(
            mgr,
            "check_disk_usage",
            side_effect=lambda *a, **kw: next(disk_values, 0.70),
        ):
            deleted = mgr.prune_oldest_indices()

        # Should stop after first deletion brings disk below threshold
        assert deleted == 1


# =========================================================================
# Emergency pruning
# =========================================================================


class TestPruneEmergency:
    def test_prune_emergency_deletes_all_tiers(
        self, retention_config, mock_opensearch_client
    ):
        """Verify emergency mode deletes across all tiers regardless of tier boundaries."""
        now = datetime.now(timezone.utc)
        # Mix of tiers — some within retention, some not.
        # Emergency mode ignores retention windows entirely.
        dates = [now - timedelta(days=d) for d in (5, 10, 20)]

        cold_name = f"arkime_sessions3-{dates[0].strftime('%y%m%d')}"
        warm_name = f"suricata-alert-{dates[1].strftime('%Y-%m-%d')}"
        hot_name = f"zeek-conn-{dates[2].strftime('%Y.%m.%d')}"

        mock_opensearch_client.cat.indices.return_value = [
            {
                "index": cold_name,
                "store.size": "200mb",
                "pri.store.size": "200mb",
                "creation.date.string": dates[0].isoformat(),
            },
            {
                "index": warm_name,
                "store.size": "10mb",
                "pri.store.size": "10mb",
                "creation.date.string": dates[1].isoformat(),
            },
            {
                "index": hot_name,
                "store.size": "50mb",
                "pri.store.size": "50mb",
                "creation.date.string": dates[2].isoformat(),
            },
        ]

        mgr = StorageManager.__new__(StorageManager)
        mgr.config = retention_config
        mgr._client = mock_opensearch_client
        mgr.opensearch_url = "http://localhost:9200"

        # Disk stays above threshold so all indices get deleted
        with patch.object(mgr, "check_disk_usage", return_value=0.92):
            deleted = mgr.prune_emergency()

        assert deleted == 3
        assert mock_opensearch_client.indices.delete.call_count == 3


# =========================================================================
# run_cycle
# =========================================================================


class TestRunCycle:
    def _make_manager(self, retention_config, mock_client):
        mgr = StorageManager.__new__(StorageManager)
        mgr.config = retention_config
        mgr._client = mock_client
        mgr.opensearch_url = "http://localhost:9200"
        return mgr

    def test_run_cycle_no_action_below_threshold(
        self, retention_config, mock_opensearch_client
    ):
        """Mock disk at 50% and verify no prune method is called."""
        mgr = self._make_manager(retention_config, mock_opensearch_client)

        with (
            patch.object(mgr, "check_disk_usage", return_value=0.50),
            patch.object(mgr, "prune_oldest_indices") as mock_prune,
            patch.object(mgr, "prune_emergency") as mock_emergency,
        ):
            mgr.run_cycle()

        mock_prune.assert_not_called()
        mock_emergency.assert_not_called()

    def test_run_cycle_normal_prune(self, retention_config, mock_opensearch_client):
        """Mock disk at 85% and verify prune_oldest_indices is called."""
        mgr = self._make_manager(retention_config, mock_opensearch_client)

        with (
            patch.object(mgr, "check_disk_usage", return_value=0.85),
            patch.object(mgr, "prune_oldest_indices", return_value=2) as mock_prune,
            patch.object(mgr, "prune_emergency") as mock_emergency,
        ):
            mgr.run_cycle()

        mock_prune.assert_called_once()
        mock_emergency.assert_not_called()

    def test_run_cycle_emergency_prune(self, retention_config, mock_opensearch_client):
        """Mock disk at 95% and verify prune_emergency is called."""
        mgr = self._make_manager(retention_config, mock_opensearch_client)

        with (
            patch.object(mgr, "check_disk_usage", return_value=0.95),
            patch.object(mgr, "prune_oldest_indices") as mock_prune,
            patch.object(mgr, "prune_emergency", return_value=5) as mock_emergency,
        ):
            mgr.run_cycle()

        mock_emergency.assert_called_once()
        mock_prune.assert_not_called()


# =========================================================================
# get_status
# =========================================================================


class TestGetStatus:
    def test_get_status_structure(
        self, retention_config, mock_opensearch_client, sample_indices
    ):
        """Verify get_status returns all expected keys with correct types."""
        # Filter out system indices for the mock return
        mock_opensearch_client.cat.indices.return_value = sample_indices

        mgr = StorageManager.__new__(StorageManager)
        mgr.config = retention_config
        mgr._client = mock_opensearch_client
        mgr.opensearch_url = "http://localhost:9200"

        with patch.object(mgr, "check_disk_usage", return_value=0.65):
            status = mgr.get_status()

        # Top-level keys
        assert "disk_usage" in status
        assert "disk_usage_percent" in status
        assert "disk_threshold" in status
        assert "emergency_threshold" in status
        assert "check_path" in status
        assert "index_counts" in status
        assert "total_indices" in status
        assert "retention" in status

        # Type checks
        assert isinstance(status["disk_usage"], float)
        assert isinstance(status["disk_usage_percent"], str)
        assert isinstance(status["index_counts"], dict)
        assert isinstance(status["total_indices"], int)
        assert isinstance(status["retention"], dict)

        # Retention sub-keys
        assert "hot_days" in status["retention"]
        assert "warm_days" in status["retention"]
        assert "cold_days" in status["retention"]

        # Index counts should include expected tiers
        for tier in ("hot", "warm", "cold", "unknown"):
            assert tier in status["index_counts"]
