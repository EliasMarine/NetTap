"""
Tests for storage hardening features (Phase C).

Covers:
  C1 — Predictive disk exhaustion alerting
  C2 — Emergency cascade deletion (90%/95% thresholds)
  C3 — ILM policy verification on daemon startup
  C4 — Per-tier disk accounting
  C6 — Re-index from logs recovery path
"""

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from opensearchpy import OpenSearchException

from storage.manager import RetentionConfig, StorageManager


# =========================================================================
# Helpers
# =========================================================================


def _make_manager(
    config=None,
    mock_client=None,
    usage_history=None,
):
    """Build a StorageManager without connecting to real OpenSearch."""
    cfg = config or RetentionConfig(
        hot_days=30,
        warm_days=60,
        cold_days=15,
        disk_threshold=0.80,
        emergency_threshold=0.90,
        critical_threshold=0.95,
        resume_threshold=0.85,
        check_path="/",
        pcap_dir="/data/pcap",
        capture_stop_flag="/tmp/nettap-stop-capture-test",
    )
    mgr = StorageManager.__new__(StorageManager)
    mgr.config = cfg
    mgr._client = mock_client or MagicMock()
    mgr.opensearch_url = "http://localhost:9200"
    mgr._http_auth = None
    mgr._ilm_verified = False

    from collections import deque

    mgr._usage_history = deque(maxlen=StorageManager._USAGE_HISTORY_MAX)
    mgr._prediction_alert_active = False

    import threading

    mgr._cleanup_lock = threading.Lock()

    if usage_history:
        for entry in usage_history:
            mgr._usage_history.append(entry)

    return mgr


# =========================================================================
# C1: Predictive disk exhaustion alerting
# =========================================================================


class TestPredictiveExhaustion:
    def test_predictive_exhaustion_alert_when_projected_full(self):
        """Alert should fire when fill rate projects threshold hit within 48h."""
        now = datetime.now(timezone.utc)

        # Simulate disk growing from 70% to 75% over 12 hours
        # That's 5% in 12h = 0.417%/h. Need 5% more to reach 80%.
        # Time to threshold: 5% / 0.417%/h = 12h -> well within 48h
        usage_history = [
            (now - timedelta(hours=12), 0.70),
            (now - timedelta(hours=6), 0.725),
            (now, 0.75),
        ]

        mgr = _make_manager(usage_history=usage_history)

        with (
            patch.object(mgr, "check_disk_usage", return_value=0.75),
            patch("storage.manager.shutil.disk_usage") as mock_disk,
        ):
            mock_disk.return_value = MagicMock(
                total=1_000_000_000_000,
                used=750_000_000_000,
                free=250_000_000_000,
            )
            result = mgr.get_disk_prediction()

        assert result["alert_active"] is True
        assert result["current_usage_pct"] == 75.0
        assert result["fill_rate_bytes_per_hour"] > 0
        assert 0 < result["hours_until_threshold"] <= 48

    def test_predictive_exhaustion_no_alert_when_stable(self):
        """No alert when disk usage is stable (not growing)."""
        now = datetime.now(timezone.utc)

        # Stable at 50% for 24 hours
        usage_history = [
            (now - timedelta(hours=24), 0.50),
            (now - timedelta(hours=12), 0.50),
            (now, 0.50),
        ]

        mgr = _make_manager(usage_history=usage_history)

        with (
            patch.object(mgr, "check_disk_usage", return_value=0.50),
            patch("storage.manager.shutil.disk_usage") as mock_disk,
        ):
            mock_disk.return_value = MagicMock(
                total=1_000_000_000_000,
                used=500_000_000_000,
                free=500_000_000_000,
            )
            result = mgr.get_disk_prediction()

        assert result["alert_active"] is False
        assert result["current_usage_pct"] == 50.0
        assert result["hours_until_threshold"] == float("inf")

    def test_predictive_already_above_threshold(self):
        """When already above threshold, alert is always active."""
        mgr = _make_manager()

        with (
            patch.object(mgr, "check_disk_usage", return_value=0.85),
            patch("storage.manager.shutil.disk_usage") as mock_disk,
        ):
            mock_disk.return_value = MagicMock(
                total=1_000_000_000_000,
                used=850_000_000_000,
                free=150_000_000_000,
            )
            result = mgr.get_disk_prediction()

        assert result["alert_active"] is True
        assert result["hours_until_threshold"] == -1

    def test_predictive_insufficient_data(self):
        """With fewer than 2 samples, no alert fires."""
        mgr = _make_manager()
        # Only 1 data point
        mgr._usage_history.append((datetime.now(timezone.utc), 0.60))

        with (
            patch.object(mgr, "check_disk_usage", return_value=0.60),
            patch("storage.manager.shutil.disk_usage") as mock_disk,
        ):
            mock_disk.return_value = MagicMock(
                total=1_000_000_000_000,
                used=600_000_000_000,
                free=400_000_000_000,
            )
            result = mgr.get_disk_prediction()

        assert result["alert_active"] is False
        assert result["hours_until_threshold"] == float("inf")


# =========================================================================
# C2: Emergency cascade deletion (90%/95% thresholds)
# =========================================================================


class TestEmergencyCascade:
    def test_emergency_cascade_at_90_percent(self):
        """At 90%: should prune PCAPs then indices, NOT stop capture."""
        mgr = _make_manager()

        with (
            patch.object(mgr, "check_disk_usage", return_value=0.91),
            patch.object(mgr, "prune_emergency", return_value=3) as mock_prune,
            patch.object(mgr, "_delete_oldest_pcaps", return_value=2) as mock_pcap,
            patch.object(mgr, "_stop_capture") as mock_stop,
            patch.object(mgr, "is_capture_stopped", return_value=False),
        ):
            deleted = mgr.emergency_cascade()

        assert deleted == 5
        mock_prune.assert_called_once()
        # OLD CODE: mock_pcap.assert_called_once_with(max_delete=...) (B-l: the call names its target)
        mock_pcap.assert_called_once_with(
            max_delete=StorageManager._EMERGENCY_PCAP_DELETE_CAP, target=0.90
        )
        mock_stop.assert_not_called()

    def test_emergency_stop_capture_at_95_percent(self):
        """At 95%: should stop capture AND do aggressive pruning."""
        mgr = _make_manager()

        with (
            patch.object(mgr, "check_disk_usage", return_value=0.96),
            patch.object(mgr, "prune_emergency", return_value=5) as mock_prune,
            patch.object(mgr, "_delete_oldest_pcaps", return_value=3) as mock_pcap,
            patch.object(mgr, "_stop_capture") as mock_stop,
            patch.object(mgr, "is_capture_stopped", return_value=True),
        ):
            deleted = mgr.emergency_cascade()

        assert deleted == 8
        mock_stop.assert_called_once()
        mock_prune.assert_called_once()
        # OLD CODE: mock_pcap.assert_called_once_with(max_delete=...) (B-l: paused, so down to resume)
        mock_pcap.assert_called_once_with(
            max_delete=StorageManager._EMERGENCY_PCAP_DELETE_CAP, target=0.85
        )

    def test_emergency_resume_below_85_percent(self, tmp_path):
        """When disk drops below 85%, capture should be resumed."""
        flag_file = tmp_path / "stop-capture"
        flag_file.write_text("stopped\n")

        cfg = RetentionConfig(
            capture_stop_flag=str(flag_file),
            resume_threshold=0.85,
            emergency_threshold=0.90,
            critical_threshold=0.95,
        )
        mgr = _make_manager(config=cfg)

        # Simulate: currently at 84% (below emergency, below resume)
        # But the flag file exists from a previous emergency
        with patch.object(mgr, "check_disk_usage", return_value=0.84):
            # emergency_cascade won't trigger at 84%, but run_cycle should
            # clear the flag
            pass

        # Test the flag-clearing logic directly
        assert flag_file.exists()
        mgr._clear_capture_stop_flag()
        assert not flag_file.exists()

    def test_capture_stop_flag_lifecycle(self, tmp_path):
        """Test write/check/clear of the capture stop flag."""
        flag_file = tmp_path / "stop-capture"
        cfg = RetentionConfig(capture_stop_flag=str(flag_file))
        mgr = _make_manager(config=cfg)

        # Initially no flag
        assert not mgr.is_capture_stopped()

        # Set the flag
        mgr._set_capture_stop_flag()
        assert mgr.is_capture_stopped()
        assert flag_file.exists()

        # Clear the flag
        mgr._clear_capture_stop_flag()
        assert not mgr.is_capture_stopped()
        assert not flag_file.exists()

    def test_run_cycle_resumes_capture_below_resume_threshold(
        self, tmp_path, monkeypatch
    ):
        """run_cycle should start capture and clear the flag below resume threshold."""
        monkeypatch.setenv("NETTAP_ENV_FILE", str(tmp_path / ".env"))
        flag_file = tmp_path / "stop-capture"
        flag_file.write_text("stopped\n")

        cfg = RetentionConfig(
            capture_stop_flag=str(flag_file),
            resume_threshold=0.85,
            disk_threshold=0.80,
            emergency_threshold=0.90,
            critical_threshold=0.95,
        )
        mgr = _make_manager(config=cfg)
        mgr._ilm_verified = True  # Skip ILM check

        # Disk at 70% — well below all thresholds
        with (
            patch.object(mgr, "check_disk_usage", return_value=0.70),
            patch.object(mgr, "get_disk_prediction", return_value={}),
            patch("storage.manager.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            mgr.run_cycle()

        assert mock_run.call_args.args[0] == ["docker", "start", "nettap-pcap-capture"]
        assert not flag_file.exists()


# =========================================================================
# C3: ILM policy verification on daemon startup
# =========================================================================


class TestIlmPolicyVerification:
    def test_ilm_policy_verification_creates_missing(self):
        """When policies are missing, verify_ilm_policy should create them."""
        mgr = _make_manager()

        with patch("storage.ilm.apply_ilm_policies_from_config") as mock_apply:
            mock_apply.return_value = {
                "nettap-hot-policy": "created",
                "nettap-warm-policy": "created",
                "nettap-cold-policy": "created",
            }
            result = mgr.verify_ilm_policy()

        assert result["nettap-hot-policy"] == "created"
        assert result["nettap-warm-policy"] == "created"
        assert result["nettap-cold-policy"] == "created"
        assert mgr._ilm_verified is True

    def test_ilm_verification_keeps_ism_history_without_replicas(self):
        """Single node: ISM history must ask for 0 replicas or the cluster stays yellow."""
        mgr = _make_manager()
        mgr._client = MagicMock()

        with patch("storage.ilm.apply_ilm_policies_from_config") as mock_apply:
            mock_apply.return_value = {"nettap-hot-policy": "unchanged"}
            mgr.verify_ilm_policy()

        settings = mgr._client.cluster.put_settings.call_args.kwargs["body"]
        assert (
            settings["persistent"][
                "plugins.index_state_management.history.number_of_replicas"
            ]
            == 0
        )
        index_call = mgr._client.indices.put_settings.call_args.kwargs
        assert index_call["index"] == ".opendistro-ism-managed-index-history-*"
        assert index_call["body"] == {"index": {"number_of_replicas": 0}}
        assert index_call["expand_wildcards"] == "all"

    # OLD CODE START — #96: the setting moved from the one-time ILM check to every cycle
    # until it takes (TestExactCountsRetried below)
    # def test_ilm_verification_turns_off_concurrent_segment_search(self):
    #     """#90: OpenSearch 3.x slices each shard for aggregations, so terms top-N counts read low."""
    #     mgr = _make_manager()
    #     mgr._client = MagicMock()
    #
    #     with patch("storage.ilm.apply_ilm_policies_from_config") as mock_apply:
    #         mock_apply.return_value = {"nettap-hot-policy": "unchanged"}
    #         mgr.verify_ilm_policy()
    #
    #     bodies = [c.kwargs["body"] for c in mgr._client.cluster.put_settings.call_args_list]
    #     assert {"persistent": {"search.concurrent_segment_search.mode": "none"}} in bodies
    # OLD CODE END

    def test_ilm_policy_verification_passes_when_exists(self):
        """When policies already exist, verify_ilm_policy reports unchanged."""
        mgr = _make_manager()

        with patch("storage.ilm.apply_ilm_policies_from_config") as mock_apply:
            mock_apply.return_value = {
                "nettap-hot-policy": "unchanged",
                "nettap-warm-policy": "unchanged",
                "nettap-cold-policy": "unchanged",
            }
            result = mgr.verify_ilm_policy()

        assert all(v == "unchanged" for v in result.values())
        assert mgr._ilm_verified is True

    def test_startup_verification_marks_the_health_card_synced(self):
        """Startup apply records its result, so Settings stops saying "Out of sync"."""
        mgr = _make_manager()
        mgr._retention_config_manager = MagicMock()
        mgr._retention_config_manager.get_ilm_status.return_value = {}
        results = {"nettap-hot-policy": "updated", "nettap-warm-policy": "unchanged"}

        with patch("storage.ilm.apply_ilm_policies_from_config") as mock_apply:
            mock_apply.return_value = results
            mgr.verify_ilm_policy()

        mgr._retention_config_manager.mark_ilm_applied.assert_called_once_with(results)

    def test_startup_verification_with_errors_does_not_mark_synced(self):
        mgr = _make_manager()
        mgr._retention_config_manager = MagicMock()

        with patch("storage.ilm.apply_ilm_policies_from_config") as mock_apply:
            mock_apply.return_value = {"nettap-hot-policy": "error: 403"}
            mgr.verify_ilm_policy()

        mgr._retention_config_manager.mark_ilm_applied.assert_not_called()

    def test_ilm_policy_verification_handles_missing_file(self):
        """When OpenSearch is unreachable, returns error dict."""
        mgr = _make_manager()

        with patch(
            "storage.ilm.apply_ilm_policies_from_config",
            side_effect=ConnectionError("OpenSearch unreachable"),
        ):
            result = mgr.verify_ilm_policy()

        assert "_error" in result
        assert "error:" in result["_error"]

    def test_run_cycle_verifies_ilm_on_first_run(self):
        """run_cycle should call verify_ilm_policy on the first cycle."""
        mgr = _make_manager()
        mgr._ilm_verified = False

        with (
            patch.object(mgr, "check_disk_usage", return_value=0.50),
            patch.object(mgr, "verify_ilm_policy") as mock_verify,
            patch.object(mgr, "get_disk_prediction", return_value={}),
        ):
            mgr.run_cycle()

        mock_verify.assert_called_once()

    def test_run_cycle_skips_ilm_after_first_verification(self):
        """run_cycle should NOT re-verify ILM after the first cycle."""
        mgr = _make_manager()
        mgr._ilm_verified = True

        with (
            patch.object(mgr, "check_disk_usage", return_value=0.50),
            patch.object(mgr, "verify_ilm_policy") as mock_verify,
            patch.object(mgr, "get_disk_prediction", return_value={}),
        ):
            mgr.run_cycle()

        mock_verify.assert_not_called()


# =========================================================================
# C4: Per-tier disk accounting
# =========================================================================


class TestTierUsageAccounting:
    def test_tier_usage_accounting(self):
        """Verify per-tier byte counts from index stats + PCAP directory."""
        mock_client = MagicMock()
        mock_client.indices.stats.return_value = {
            "indices": {
                "zeek-conn-2026.01.15": {
                    "total": {"store": {"size_in_bytes": 50_000_000}}
                },
                "zeek-dns-2026.01.20": {
                    "total": {"store": {"size_in_bytes": 30_000_000}}
                },
                "suricata-alert-2026-01-20": {
                    "total": {"store": {"size_in_bytes": 10_000_000}}
                },
                "arkime_sessions3-260125": {
                    "total": {"store": {"size_in_bytes": 200_000_000}}
                },
                ".opensearch-dashboards": {
                    "total": {"store": {"size_in_bytes": 2_000_000}}
                },
            }
        }

        mgr = _make_manager(mock_client=mock_client)

        with (
            patch("storage.manager.shutil.disk_usage") as mock_disk,
            patch("storage.manager.Path") as mock_path_cls,
        ):
            mock_disk.return_value = MagicMock(total=1_000_000_000_000)

            # Mock PCAP directory - no PCAP files
            mock_pcap_dir = MagicMock()
            mock_pcap_dir.exists.return_value = False
            mock_path_cls.return_value = mock_pcap_dir

            result = mgr.get_tier_usage()

        # OLD CODE START — arkime_sessions3 was counted as cold (CR-038)
        # assert result["hot_bytes"] == 80_000_000  # 50M + 30M
        # assert result["warm_bytes"] == 10_000_000
        # assert result["cold_bytes"] == 200_000_000
        # OLD CODE END
        # arkime_sessions3 holds Zeek metadata and Suricata alerts: hot tier
        assert result["hot_bytes"] == 280_000_000  # 50M + 30M + 200M
        assert result["warm_bytes"] == 10_000_000
        assert result["cold_bytes"] == 0
        assert result["total_bytes"] == 290_000_000
        assert result["disk_capacity_bytes"] == 1_000_000_000_000

    def test_tier_usage_handles_opensearch_error(self):
        """Should return zeros when OpenSearch is unreachable."""
        mock_client = MagicMock()
        mock_client.indices.stats.side_effect = OpenSearchException(
            "connection refused"
        )

        mgr = _make_manager(mock_client=mock_client)

        with (
            patch("storage.manager.shutil.disk_usage") as mock_disk,
            patch("storage.manager.Path") as mock_path_cls,
        ):
            mock_disk.return_value = MagicMock(total=500_000_000_000)
            mock_path_cls.return_value.exists.return_value = False

            result = mgr.get_tier_usage()

        assert result["hot_bytes"] == 0
        assert result["warm_bytes"] == 0
        assert result["cold_bytes"] == 0
        assert result["disk_capacity_bytes"] == 500_000_000_000


# =========================================================================
# C6: Re-index from logs
# =========================================================================


class TestReindexFromLogs:
    def test_reindex_from_logs(self, tmp_path):
        """Verify re-indexing reads JSON lines and bulk-indexes them."""
        # Create sample Zeek JSON log files
        log_dir = tmp_path / "zeek-logs"
        log_dir.mkdir()

        log1 = log_dir / "conn.json"
        docs = [
            {"uid": "C001", "id.orig_h": "192.168.1.1", "proto": "tcp"},
            {"uid": "C002", "id.orig_h": "192.168.1.2", "proto": "udp"},
        ]
        log1.write_text("\n".join(json.dumps(d) for d in docs) + "\n")

        log2 = log_dir / "dns.json"
        dns_docs = [
            {"uid": "D001", "query": "example.com", "qtype": "A"},
        ]
        log2.write_text(json.dumps(dns_docs[0]) + "\n")

        mock_client = MagicMock()
        mock_client.bulk.return_value = {"errors": False, "items": []}

        mgr = _make_manager(mock_client=mock_client)

        result = mgr.reindex_from_logs(str(log_dir))

        assert result["files_processed"] == 2
        assert result["documents_indexed"] == 3
        assert result["errors"] == 0
        assert "zeek-recovered" in result["index_name"]

        # Verify bulk was called
        assert mock_client.bulk.call_count >= 1

    def test_reindex_from_logs_nonexistent_dir(self):
        """Non-existent directory should return zeros gracefully."""
        mgr = _make_manager()
        result = mgr.reindex_from_logs("/nonexistent/path")

        assert result["files_processed"] == 0
        assert result["documents_indexed"] == 0

    def test_reindex_from_logs_skips_invalid_json(self, tmp_path):
        """Invalid JSON lines should be counted as errors and skipped."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        log_file = log_dir / "mixed.json"
        log_file.write_text('{"valid": true}\nnot json at all\n{"also_valid": true}\n')

        mock_client = MagicMock()
        mock_client.bulk.return_value = {"errors": False, "items": []}

        mgr = _make_manager(mock_client=mock_client)
        result = mgr.reindex_from_logs(str(log_dir))

        assert result["files_processed"] == 1
        assert result["documents_indexed"] == 2
        assert result["errors"] == 1

    def test_reindex_handles_bulk_errors(self, tmp_path):
        """Bulk indexing errors should be counted."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        log_file = log_dir / "data.json"
        log_file.write_text('{"doc": 1}\n{"doc": 2}\n')

        mock_client = MagicMock()
        mock_client.bulk.return_value = {
            "errors": True,
            "items": [
                {"index": {"_id": "1", "status": 201}},
                {
                    "index": {
                        "_id": "2",
                        "status": 400,
                        "error": {"type": "mapper_parsing_exception"},
                    }
                },
            ],
        }

        mgr = _make_manager(mock_client=mock_client)
        result = mgr.reindex_from_logs(str(log_dir))

        assert result["files_processed"] == 1
        assert result["documents_indexed"] == 1
        assert result["errors"] == 1


_EXACT = {"persistent": {"search.concurrent_segment_search.mode": "none"}}


class TestExactCountsRetried:
    """#96: turning off concurrent segment search (#90) was tried once at startup; a
    failure was only logged, and top-N counts stayed approximate with nothing saying so."""

    def _cycle(self, mgr):
        with (
            patch.object(mgr, "check_disk_usage", return_value=0.50),
            patch.object(mgr, "get_disk_prediction", return_value={}),
            patch.object(mgr, "prune_expired_pcaps"),
            patch.object(mgr, "prune_pcaps_over_cap"),
        ):
            mgr.run_cycle()

    def _exact_calls(self, mgr):
        return [
            c
            for c in mgr._client.cluster.put_settings.call_args_list
            if c.kwargs.get("body") == _EXACT
        ]

    def _status(self, mgr):
        mgr._last_prune_at = None
        mgr._retention_config_manager = None
        with (
            patch.object(mgr, "check_disk_usage", return_value=0.50),
            patch.object(mgr, "list_indices", return_value=[]),
        ):
            return mgr.get_status()

    def test_failure_is_retried_next_cycle_and_shown(self):
        mgr = _make_manager()
        mgr._ilm_verified = True
        mgr._client.cluster.put_settings.side_effect = OpenSearchException("503")
        self._cycle(mgr)
        assert self._status(mgr)["exact_counts"] is False

        mgr._client.cluster.put_settings.side_effect = None
        self._cycle(mgr)
        assert len(self._exact_calls(mgr)) == 2
        assert self._status(mgr)["exact_counts"] is True

    def test_not_resent_once_taken(self):
        mgr = _make_manager()
        mgr._ilm_verified = True
        self._cycle(mgr)
        self._cycle(mgr)
        assert len(self._exact_calls(mgr)) == 1


# =========================================================================
# B-l (NET-227): capture never stays paused between the resume and emergency lines
# =========================================================================


class _Disk:
    """check_disk_usage that drops by `step` for each PCAP or index deleted."""

    def __init__(self, start: float, step: float):
        self.usage, self.step = start, step

    def __call__(self, path=None):
        return self.usage

    def free(self, *_a, **_k):
        self.usage -= self.step


def _paused_manager(tmp_path, monkeypatch, usage, step=0.01, pcaps=0):
    monkeypatch.setenv("NETTAP_ENV_FILE", str(tmp_path / ".env"))
    pcap_dir = tmp_path / "pcap"
    pcap_dir.mkdir()
    for i in range(pcaps):
        f = pcap_dir / f"cap{i:04d}.pcap"
        f.write_bytes(b"x")
        os.utime(f, (1_000 + i, 1_000 + i))
    flag = tmp_path / "storage-stopped-capture"
    flag.write_text("stopped\n")
    mgr = _make_manager(
        config=RetentionConfig(
            disk_threshold=0.80,
            emergency_threshold=0.90,
            critical_threshold=0.95,
            resume_threshold=0.85,
            pcap_dir=str(pcap_dir),
            capture_stop_flag=str(flag),
            pcap_max_disk_fraction=0,
        )
    )
    mgr._ilm_verified = True
    disk = _Disk(usage, step)
    return mgr, disk, flag


class TestCapturePauseHysteresis:
    def test_paused_at_88_percent_frees_to_the_resume_line_and_resumes(
        self, tmp_path, monkeypatch
    ):
        """Old code: deleted nothing between 85 and 90 %, so capture never came back."""
        mgr, disk, flag = _paused_manager(tmp_path, monkeypatch, 0.88, pcaps=10)
        real_unlink = StorageManager._unlink_pcap

        def unlink(path):
            real_unlink(path)
            disk.free()

        with (
            patch.object(mgr, "check_disk_usage", side_effect=disk),
            patch.object(StorageManager, "_unlink_pcap", side_effect=unlink),
            patch.object(mgr, "get_disk_prediction", return_value={}),
            patch("storage.manager.subprocess.run") as run,
        ):
            run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            mgr.run_cycle()

        assert disk.usage < 0.85
        assert run.call_args.args[0] == ["docker", "start", "nettap-pcap-capture"]
        assert not flag.exists()

    def test_a_full_pcap_batch_leaves_indices_alone(self, tmp_path, monkeypatch):
        mgr, disk, _ = _paused_manager(tmp_path, monkeypatch, 0.96, step=0)
        with (
            patch.object(mgr, "check_disk_usage", side_effect=disk),
            patch.object(
                mgr,
                "_delete_oldest_pcaps",
                return_value=StorageManager._EMERGENCY_PCAP_DELETE_CAP,
            ),
            patch.object(mgr, "prune_emergency") as prune,
            patch.object(mgr, "_stop_capture"),
        ):
            mgr.emergency_cascade()
        prune.assert_not_called()

    def test_undeletable_oldest_pcap_never_blocks_the_rest(self, tmp_path, monkeypatch):
        """Old code: the first max_delete files were the batch, deleted or not."""
        mgr, disk, _ = _paused_manager(tmp_path, monkeypatch, 0.88, step=0, pcaps=6)
        oldest = {f"cap{i:04d}.pcap" for i in range(3)}
        real_unlink = StorageManager._unlink_pcap

        def unlink(path):
            if path.name in oldest:
                raise PermissionError("read-only")
            real_unlink(path)

        with (
            patch.object(mgr, "check_disk_usage", side_effect=disk),
            patch.object(StorageManager, "_unlink_pcap", side_effect=unlink),
        ):
            deleted = mgr._delete_oldest_pcaps(max_delete=3, target=0.85)

        assert deleted == 3
        left = sorted(p.name for p in (tmp_path / "pcap").iterdir())
        assert left == sorted(oldest)

    def test_all_pcap_undeletable_falls_back_to_indices(self, tmp_path, monkeypatch):
        mgr, disk, _ = _paused_manager(tmp_path, monkeypatch, 0.88, step=0, pcaps=4)
        with (
            patch.object(mgr, "check_disk_usage", side_effect=disk),
            patch.object(
                StorageManager, "_unlink_pcap", side_effect=PermissionError("ro")
            ),
            patch.object(mgr, "prune_emergency", return_value=0) as prune,
            patch.object(mgr, "_stop_capture"),
        ):
            mgr.emergency_cascade()
        prune.assert_called_once_with(target=0.85)

    def test_status_reports_the_pause(self, tmp_path, monkeypatch):
        mgr, _, flag = _paused_manager(tmp_path, monkeypatch, 0.5)
        mgr._client.cat.indices.return_value = []
        mgr._retention_config_manager = None
        mgr._last_prune_at = None
        with patch.object(mgr, "check_disk_usage", return_value=0.5):
            assert mgr.get_status()["capture_paused_disk_full"] is True
            flag.unlink()
            assert mgr.get_status()["capture_paused_disk_full"] is False


# =========================================================================
# A15 (NET-227): a failed startup ILM apply is retried with backoff and reported
# =========================================================================


class TestIlmStartupRetry:
    ERROR = {"nettap-hot-policy": "error: ConnectionError(Connection refused)"}

    def test_error_results_are_retried_after_a_backoff(self):
        mgr = _make_manager()
        mgr._retention_config_manager = MagicMock()
        with patch(
            "storage.ilm.apply_ilm_policies_from_config", return_value=self.ERROR
        ):
            mgr.verify_ilm_policy()

        # old code set _ilm_verified here, so it was never tried again
        assert mgr._ilm_verified is False
        mgr._retention_config_manager.mark_ilm_failed.assert_called_once_with(
            self.ERROR["nettap-hot-policy"]
        )
        mgr._retention_config_manager.mark_ilm_applied.assert_not_called()

        with (
            patch.object(mgr, "check_disk_usage", return_value=0.5),
            patch.object(mgr, "get_disk_prediction", return_value={}),
            patch.object(mgr, "verify_ilm_policy") as verify,
        ):
            mgr.run_cycle()  # still inside the 5-minute backoff
            verify.assert_not_called()
            mgr._ilm_retry_at = 0.0  # backoff over
            mgr.run_cycle()
            verify.assert_called_once()

    def test_backoff_doubles_up_to_an_hour(self):
        mgr = _make_manager()
        delays = []
        with patch("storage.manager.time.monotonic", return_value=0.0):
            for _ in range(6):
                mgr._ilm_failed("down")
                delays.append(mgr._ilm_retry_at)
        assert delays == [300, 600, 1200, 2400, 3600, 3600]

    def test_status_says_not_synced_retrying_and_why(self, tmp_path):
        from storage.retention_config import RetentionConfigManager

        cm = RetentionConfigManager(
            config_path=str(tmp_path / "retention.json"),
            env_file=str(tmp_path / ".env"),
        )
        cm.load()
        cm.mark_ilm_applied({"nettap-hot-policy": "updated"})  # an earlier success
        mgr = _make_manager()
        mgr._retention_config_manager = cm
        with patch(
            "storage.ilm.apply_ilm_policies_from_config",
            side_effect=ConnectionError("Connection refused"),
        ):
            mgr.verify_ilm_policy()

        status = mgr._get_ilm_status()
        # old code: "synced" from the earlier success
        assert status["synced"] is False
        assert status["pending_retry"] is True
        assert "Connection refused" in status["last_error"]
        assert status["last_applied"] is not None

        with patch(
            "storage.ilm.apply_ilm_policies_from_config",
            return_value={"nettap-hot-policy": "unchanged"},
        ):
            mgr.verify_ilm_policy()
        status = mgr._get_ilm_status()
        assert status["synced"] is True
        assert status["last_error"] is None
        assert status["pending_retry"] is False

    def test_a_settings_save_that_applies_clears_the_retry_note(self, tmp_path):
        """Startup failed, then a Settings save applied the policies: in sync, not retrying."""
        from storage.retention_config import RetentionConfigManager

        cm = RetentionConfigManager(
            config_path=str(tmp_path / "retention.json"),
            env_file=str(tmp_path / ".env"),
        )
        cm.load()
        mgr = _make_manager()
        mgr._retention_config_manager = cm
        with patch(
            "storage.ilm.apply_ilm_policies_from_config",
            side_effect=ConnectionError("Connection refused"),
        ):
            mgr.verify_ilm_policy()
        cm.mark_ilm_applied({"nettap-hot-policy": "updated"})  # the save's own apply

        status = mgr._get_ilm_status()
        assert status["synced"] is True
        # old code: True until the startup retry came round, so the card stayed amber
        assert status["pending_retry"] is False

    def test_verification_reads_the_config_and_applies_inside_the_shared_lock(self):
        """Startup and saves share one lock, so an older config never lands after a newer save."""
        import threading

        mgr = _make_manager()
        mgr.ilm_lock = threading.Lock()
        held = []

        def apply(*_a, **_k):
            held.append(mgr.ilm_lock.locked())
            return {"nettap-hot-policy": "unchanged"}

        def generate(config):
            held.append(mgr.ilm_lock.locked())
            return {}

        with (
            patch("storage.ilm.apply_ilm_policies_from_config", side_effect=apply),
            patch("storage.ilm_generator.generate_ilm_policies", side_effect=generate),
        ):
            mgr.verify_ilm_policy()
        assert held == [True, True]


# =========================================================================
# B-m (NET-227): the retention estimate is measured, not 1.2 GB a day
# =========================================================================


class TestGrowthEstimate:
    def _indices(self, sizes_by_days_ago):
        today = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return [
            {"parsed_date": today - timedelta(days=ago), "size_bytes": size}
            for ago, size in sizes_by_days_ago
        ]

    def test_indices_average_complete_past_days_and_ignore_today(self, tmp_path):
        mgr = _make_manager(config=RetentionConfig(pcap_dir=str(tmp_path)))
        indices = self._indices(
            [(0, 999e9), (1, 2e9), (1, 1e8), (2, 1.9e9), (9, 50e9), (3, None)]
        )
        g = mgr._growth_estimate(indices)
        assert g["index_bytes_per_day"] == round((2.1e9 + 1.9e9) / 2)
        assert g["index_days_measured"] == 2
        assert g["pcap_bytes_per_day"] is None  # no PCAP

    def test_pcap_rate_from_the_span_on_disk_and_days_kept_from_its_own_disk(
        self, tmp_path
    ):
        for i, mtime in enumerate((0, 86_400, 2 * 86_400)):
            f = tmp_path / f"c{i}.pcap"
            f.write_bytes(b"x" * 1000)
            os.utime(f, (mtime, mtime))
        mgr = _make_manager(
            config=RetentionConfig(
                pcap_dir=str(tmp_path),
                cold_days=30,
                pcap_max_disk_fraction=0.25,
                check_path="/elsewhere",
            )
        )
        disk = MagicMock(total=6000)
        with patch("storage.manager.shutil.disk_usage", return_value=disk) as usage:
            g = mgr._growth_estimate([])
        assert g["pcap_bytes_per_day"] == 1500  # 3000 bytes over 2 days
        assert g["pcap_days_measured"] == 2.0
        assert g["pcap_days_kept"] == 1.0  # 25 % of 6000 = 1500 bytes
        usage.assert_called_with(str(tmp_path))  # the PCAP disk, not check_path

    def test_under_a_day_of_pcap_is_not_a_rate(self, tmp_path):
        for i in range(2):
            f = tmp_path / f"c{i}.pcap"
            f.write_bytes(b"x")
            os.utime(f, (i * 3600, i * 3600))
        mgr = _make_manager(config=RetentionConfig(pcap_dir=str(tmp_path)))
        g = mgr._growth_estimate([])
        assert g["pcap_bytes_per_day"] is None
        assert g["pcap_days_kept"] is None

    def test_status_carries_the_estimate_instead_of_1_2_gb(self, tmp_path):
        mgr = _make_manager(config=RetentionConfig(pcap_dir=str(tmp_path)))
        mgr._retention_config_manager = None
        mgr._last_prune_at = None
        mgr._client.cat.indices.return_value = []
        with patch.object(mgr, "check_disk_usage", return_value=0.3):
            status = mgr.get_status()
        assert status["estimated_daily_gb"] is None
        assert status["growth_estimate"]["index_bytes_per_day"] is None

    def test_list_indices_reads_byte_sizes(self):
        mgr = _make_manager()
        mgr._client.cat.indices.return_value = [
            {"index": "arkime_sessions3-261108", "store.size": "1852771868"},
            {"index": "closed-index", "store.size": None},
        ]
        indices = mgr.list_indices()
        assert mgr._client.cat.indices.call_args.kwargs["bytes"] == "b"
        assert [i["size_bytes"] for i in indices] == [1852771868, None]
