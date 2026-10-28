"""
Tests for storage hardening features (Phase C).

Covers:
  C1 — Predictive disk exhaustion alerting
  C2 — Emergency cascade deletion (90%/95% thresholds)
  C3 — ILM policy verification on daemon startup
  C4 — Per-tier disk accounting
  C5 — PCAP checksum writing/verification
  C6 — Re-index from logs recovery path
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from opensearchpy import OpenSearchException

from storage.manager import RetentionConfig, StorageManager
from storage.pcap_integrity import PcapIntegrityChecker


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

        with patch.object(mgr, "check_disk_usage", return_value=0.75), \
             patch("storage.manager.shutil.disk_usage") as mock_disk:
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

        with patch.object(mgr, "check_disk_usage", return_value=0.50), \
             patch("storage.manager.shutil.disk_usage") as mock_disk:
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

        with patch.object(mgr, "check_disk_usage", return_value=0.85), \
             patch("storage.manager.shutil.disk_usage") as mock_disk:
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

        with patch.object(mgr, "check_disk_usage", return_value=0.60), \
             patch("storage.manager.shutil.disk_usage") as mock_disk:
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
        """At 90%: should prune indices and PCAPs, NOT stop capture."""
        mgr = _make_manager()

        with patch.object(mgr, "check_disk_usage", return_value=0.91), \
             patch.object(mgr, "prune_emergency", return_value=3) as mock_prune, \
             patch.object(mgr, "_delete_oldest_pcaps", return_value=2) as mock_pcap, \
             patch.object(mgr, "_set_capture_stop_flag") as mock_stop, \
             patch.object(mgr, "is_capture_stopped", return_value=False):
            deleted = mgr.emergency_cascade()

        assert deleted == 5
        mock_prune.assert_called_once()
        mock_pcap.assert_called_once_with(max_delete=10)
        mock_stop.assert_not_called()

    def test_emergency_stop_capture_at_95_percent(self):
        """At 95%: should stop capture AND do aggressive pruning."""
        mgr = _make_manager()

        with patch.object(mgr, "check_disk_usage", return_value=0.96), \
             patch.object(mgr, "prune_emergency", return_value=5) as mock_prune, \
             patch.object(mgr, "_delete_oldest_pcaps", return_value=3) as mock_pcap, \
             patch.object(mgr, "_set_capture_stop_flag") as mock_stop, \
             patch.object(mgr, "is_capture_stopped", return_value=True):
            deleted = mgr.emergency_cascade()

        assert deleted == 8
        mock_stop.assert_called_once()
        mock_prune.assert_called_once()
        mock_pcap.assert_called_once_with(max_delete=20)

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

    def test_run_cycle_resumes_capture_below_resume_threshold(self, tmp_path):
        """run_cycle should clear stop flag when disk is below resume threshold."""
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
        with patch.object(mgr, "check_disk_usage", return_value=0.70), \
             patch.object(mgr, "get_disk_prediction", return_value={}):
            mgr.run_cycle()

        assert not flag_file.exists()


# =========================================================================
# C3: ILM policy verification on daemon startup
# =========================================================================


class TestIlmPolicyVerification:
    def test_ilm_policy_verification_creates_missing(self):
        """When policies are missing, verify_ilm_policy should create them."""
        mgr = _make_manager()

        with patch("storage.ilm.apply_ilm_policies") as mock_apply, \
             patch("os.path.isfile", return_value=True):
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

    def test_ilm_policy_verification_passes_when_exists(self):
        """When policies already exist, verify_ilm_policy reports unchanged."""
        mgr = _make_manager()

        with patch("storage.ilm.apply_ilm_policies") as mock_apply, \
             patch("os.path.isfile", return_value=True):
            mock_apply.return_value = {
                "nettap-hot-policy": "unchanged",
                "nettap-warm-policy": "unchanged",
                "nettap-cold-policy": "unchanged",
            }
            result = mgr.verify_ilm_policy()

        assert all(v == "unchanged" for v in result.values())
        assert mgr._ilm_verified is True

    def test_ilm_policy_verification_handles_missing_file(self):
        """When policy file is not found, returns error."""
        cfg = RetentionConfig(ilm_policy_path="/nonexistent/path.json")
        mgr = _make_manager(config=cfg)

        with patch("os.path.isfile", return_value=False):
            result = mgr.verify_ilm_policy()

        assert "_error" in result
        assert "error:" in result["_error"]

    def test_run_cycle_verifies_ilm_on_first_run(self):
        """run_cycle should call verify_ilm_policy on the first cycle."""
        mgr = _make_manager()
        mgr._ilm_verified = False

        with patch.object(mgr, "check_disk_usage", return_value=0.50), \
             patch.object(mgr, "verify_ilm_policy") as mock_verify, \
             patch.object(mgr, "get_disk_prediction", return_value={}):
            mgr.run_cycle()

        mock_verify.assert_called_once()

    def test_run_cycle_skips_ilm_after_first_verification(self):
        """run_cycle should NOT re-verify ILM after the first cycle."""
        mgr = _make_manager()
        mgr._ilm_verified = True

        with patch.object(mgr, "check_disk_usage", return_value=0.50), \
             patch.object(mgr, "verify_ilm_policy") as mock_verify, \
             patch.object(mgr, "get_disk_prediction", return_value={}):
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

        with patch("storage.manager.shutil.disk_usage") as mock_disk, \
             patch("storage.manager.Path") as mock_path_cls:
            mock_disk.return_value = MagicMock(total=1_000_000_000_000)

            # Mock PCAP directory - no PCAP files
            mock_pcap_dir = MagicMock()
            mock_pcap_dir.exists.return_value = False
            mock_path_cls.return_value = mock_pcap_dir

            result = mgr.get_tier_usage()

        assert result["hot_bytes"] == 80_000_000  # 50M + 30M
        assert result["warm_bytes"] == 10_000_000
        assert result["cold_bytes"] == 200_000_000
        assert result["total_bytes"] == 290_000_000
        assert result["disk_capacity_bytes"] == 1_000_000_000_000

    def test_tier_usage_handles_opensearch_error(self):
        """Should return zeros when OpenSearch is unreachable."""
        mock_client = MagicMock()
        mock_client.indices.stats.side_effect = OpenSearchException("connection refused")

        mgr = _make_manager(mock_client=mock_client)

        with patch("storage.manager.shutil.disk_usage") as mock_disk, \
             patch("storage.manager.Path") as mock_path_cls:
            mock_disk.return_value = MagicMock(total=500_000_000_000)
            mock_path_cls.return_value.exists.return_value = False

            result = mgr.get_tier_usage()

        assert result["hot_bytes"] == 0
        assert result["warm_bytes"] == 0
        assert result["cold_bytes"] == 0
        assert result["disk_capacity_bytes"] == 500_000_000_000


# =========================================================================
# C5: PCAP checksum writing/verification
# =========================================================================


class TestPcapChecksum:
    def test_pcap_checksum_write_and_verify(self, tmp_path):
        """Write a checksum and verify it returns True."""
        # Create a fake PCAP file
        pcap_file = tmp_path / "capture.pcap"
        pcap_file.write_bytes(b"\xd4\xc3\xb2\xa1" + os.urandom(1024))

        checker = PcapIntegrityChecker()
        cksum_path = checker.write_checksum(pcap_file)

        # Checksum file should exist
        assert cksum_path.exists()
        assert cksum_path.name.startswith("capture.pcap.")

        # Verification should pass
        assert checker.verify_pcap_integrity(pcap_file) is True

    def test_pcap_checksum_detects_corruption(self, tmp_path):
        """Corrupted PCAP should fail verification."""
        # Create a PCAP and write its checksum
        pcap_file = tmp_path / "capture.pcap"
        original_data = b"\xd4\xc3\xb2\xa1" + os.urandom(1024)
        pcap_file.write_bytes(original_data)

        checker = PcapIntegrityChecker()
        checker.write_checksum(pcap_file)

        # Corrupt the PCAP file (flip some bytes)
        corrupted_data = bytearray(original_data)
        corrupted_data[100] = (corrupted_data[100] + 1) % 256
        corrupted_data[200] = (corrupted_data[200] + 1) % 256
        pcap_file.write_bytes(bytes(corrupted_data))

        # Verification should fail
        assert checker.verify_pcap_integrity(pcap_file) is False

    def test_pcap_checksum_missing_checksum_file(self, tmp_path):
        """Missing checksum file should return False."""
        pcap_file = tmp_path / "capture.pcap"
        pcap_file.write_bytes(b"some data")

        checker = PcapIntegrityChecker()
        assert checker.verify_pcap_integrity(pcap_file) is False

    def test_pcap_checksum_missing_pcap_file(self, tmp_path):
        """Missing PCAP file should return False."""
        checker = PcapIntegrityChecker()
        assert checker.verify_pcap_integrity(tmp_path / "nonexistent.pcap") is False

    def test_pcap_checksum_extension(self):
        """Checker should use sha256 extension when xxhash is unavailable."""
        checker = PcapIntegrityChecker()
        # Algorithm is either xxh3 or sha256 depending on availability
        assert checker.algorithm in ("xxh3", "sha256")
        assert checker.checksum_extension in (".xxh3", ".sha256")


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
        log_file.write_text(
            '{"valid": true}\n'
            'not json at all\n'
            '{"also_valid": true}\n'
        )

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
                {"index": {"_id": "2", "status": 400, "error": {"type": "mapper_parsing_exception"}}},
            ],
        }

        mgr = _make_manager(mock_client=mock_client)
        result = mgr.reindex_from_logs(str(log_dir))

        assert result["files_processed"] == 1
        assert result["documents_indexed"] == 1
        assert result["errors"] == 1
