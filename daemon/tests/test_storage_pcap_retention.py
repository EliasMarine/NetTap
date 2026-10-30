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
import subprocess
from unittest.mock import MagicMock, patch

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


# =========================================================================
# CR-002: emergency prune keeps today's indices and deletes PCAP first
# =========================================================================


def _index(name):
    return {"index": name, "store.size": "1mb", "creation.date.string": None}


def _cfg(tmp_path, **overrides):
    values = {
        "pcap_dir": str(tmp_path),
        "capture_stop_flag": str(tmp_path / "stopped-capture"),
        "disk_threshold": 0.80,
        "emergency_threshold": 0.90,
        "critical_threshold": 0.95,
        "resume_threshold": 0.85,
    }
    values.update(overrides)
    return RetentionConfig(**values)


class TestPruneEmergency:
    def test_never_deletes_today_or_later(self, tmp_path, caplog):
        now = datetime.now(timezone.utc)
        today = f"arkime_sessions3-{now.strftime('%y%m%d')}"
        tomorrow = f"zeek-conn-{(now + timedelta(days=1)).strftime('%Y.%m.%d')}"
        yesterday = f"zeek-conn-{(now - timedelta(days=1)).strftime('%Y.%m.%d')}"
        client = MagicMock()
        client.cat.indices.return_value = [
            _index(today),
            _index(tomorrow),
            _index(yesterday),
        ]
        mgr = _make_manager(_cfg(tmp_path), client)
        mgr.check_disk_usage = MagicMock(return_value=0.97)

        with caplog.at_level("CRITICAL", logger="nettap.storage"):
            deleted = mgr.prune_emergency()

        assert deleted == 1
        client.indices.delete.assert_called_once_with(index=yesterday)
        assert any(r.levelname == "CRITICAL" for r in caplog.records)

    def test_stops_below_emergency_threshold(self, tmp_path):
        """80-90% is the tiered prune's job, not the emergency's."""
        now = datetime.now(timezone.utc)
        older = f"zeek-conn-{(now - timedelta(days=3)).strftime('%Y.%m.%d')}"
        old = f"zeek-conn-{(now - timedelta(days=2)).strftime('%Y.%m.%d')}"
        client = MagicMock()
        client.cat.indices.return_value = [_index(older), _index(old)]
        mgr = _make_manager(_cfg(tmp_path), client)
        mgr.check_disk_usage = MagicMock(return_value=0.85)

        assert mgr.prune_emergency() == 1
        client.indices.delete.assert_called_once_with(index=older)


class TestEmergencyCascadeOrder:
    def test_pcap_deleted_first_and_indices_kept(self, tmp_path):
        files = _pcap_tree(tmp_path)
        mgr = _make_manager(_cfg(tmp_path))

        def usage():
            # Each PCAP left on disk is worth 2% of the disk
            return 0.87 + 0.02 * len(list(tmp_path.rglob("*.pcap")))

        mgr.check_disk_usage = MagicMock(side_effect=usage)
        mgr.prune_emergency = MagicMock(return_value=0)

        assert mgr.emergency_cascade() == 2

        mgr.prune_emergency.assert_not_called()
        assert not files["arkime_old"].exists()
        assert not files["netsniff_old"].exists()
        assert files["netsniff_new"].exists()

    def test_indices_pruned_when_pcap_is_not_enough(self, tmp_path):
        mgr = _make_manager(_cfg(tmp_path))  # no PCAP on disk
        mgr.check_disk_usage = MagicMock(return_value=0.92)
        mgr.prune_emergency = MagicMock(return_value=4)

        assert mgr.emergency_cascade() == 4
        mgr.prune_emergency.assert_called_once()


# =========================================================================
# CR-018: critical disk really stops pcap-capture, and resumes it
# =========================================================================

_STOP = ["docker", "stop", "nettap-pcap-capture"]
_START = ["docker", "start", "nettap-pcap-capture"]


def _docker_ok():
    return MagicMock(returncode=0, stdout="", stderr="")


class TestCaptureStop:
    def test_flag_default_is_on_persistent_storage(self):
        assert (
            RetentionConfig().capture_stop_flag
            == "/opt/nettap/data/storage-stopped-capture"
        )

    def test_critical_runs_docker_stop_and_sets_flag(self, tmp_path):
        cfg = _cfg(tmp_path)
        mgr = _make_manager(cfg)
        mgr.check_disk_usage = MagicMock(return_value=0.96)
        mgr.prune_emergency = MagicMock(return_value=0)

        with patch("storage.manager.subprocess.run", return_value=_docker_ok()) as run:
            mgr.emergency_cascade()

        run.assert_called_once()
        assert run.call_args.args[0] == _STOP
        assert run.call_args.kwargs["timeout"] > 0
        assert not run.call_args.kwargs.get("shell")
        assert mgr.is_capture_stopped()

    def test_docker_failure_is_logged_and_not_raised(self, tmp_path, caplog):
        mgr = _make_manager(_cfg(tmp_path))
        mgr.check_disk_usage = MagicMock(return_value=0.96)
        mgr.prune_emergency = MagicMock(return_value=0)

        for error in (
            FileNotFoundError("docker"),
            subprocess.TimeoutExpired("docker", 60),
        ):
            with (
                patch("storage.manager.subprocess.run", side_effect=error),
                caplog.at_level("ERROR", logger="nettap.storage"),
            ):
                mgr.emergency_cascade()

        failed = _docker_ok()
        failed.returncode = 1
        with patch("storage.manager.subprocess.run", return_value=failed):
            mgr.emergency_cascade()

        # Not recorded as stopped, so the next cycle retries the stop
        assert not mgr.is_capture_stopped()
        assert any("docker stop" in r.getMessage() for r in caplog.records)


class TestCaptureResume:
    def _stopped_manager(self, tmp_path, monkeypatch, env_text=""):
        env = tmp_path / ".env"
        env.write_text(env_text)
        monkeypatch.setenv("NETTAP_ENV_FILE", str(env))
        cfg = _cfg(tmp_path)
        (tmp_path / "stopped-capture").write_text("stopped\n")
        mgr = _make_manager(cfg)
        mgr.get_disk_prediction = MagicMock(return_value={})
        mgr.prune_oldest_indices = MagicMock(return_value=0)
        return mgr

    def test_resumes_between_disk_and_resume_threshold(self, tmp_path, monkeypatch):
        """83% is below resume (85%) though still above the 80% prune line."""
        mgr = self._stopped_manager(tmp_path, monkeypatch)
        mgr.check_disk_usage = MagicMock(return_value=0.83)

        with patch("storage.manager.subprocess.run", return_value=_docker_ok()) as run:
            mgr.run_cycle()

        assert run.call_args.args[0] == _START
        assert not mgr.is_capture_stopped()

    def test_does_not_start_capture_the_user_turned_off(self, tmp_path, monkeypatch):
        mgr = self._stopped_manager(
            tmp_path, monkeypatch, env_text="PCAP_CAPTURE_ENABLED=false\n"
        )
        mgr.check_disk_usage = MagicMock(return_value=0.50)

        with patch("storage.manager.subprocess.run") as run:
            mgr.run_cycle()

        run.assert_not_called()
        assert not mgr.is_capture_stopped()

    def test_keeps_flag_when_docker_start_fails(self, tmp_path, monkeypatch):
        mgr = self._stopped_manager(tmp_path, monkeypatch)
        mgr.check_disk_usage = MagicMock(return_value=0.50)

        with patch("storage.manager.subprocess.run", side_effect=OSError("socket")):
            mgr.run_cycle()

        assert mgr.is_capture_stopped()
