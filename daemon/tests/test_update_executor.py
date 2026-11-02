"""
Tests for daemon/services/update_executor.py

All tests use mocks -- no real Docker, system commands, or filesystem
access required. Tests cover the UpdateExecutor class: update execution,
rollback, backup creation, history tracking, concurrent update prevention,
and error handling.
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock
from datetime import datetime, timezone

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.update_executor import UpdateResult, UpdateExecutor


class TestUpdateResultDataclass(unittest.TestCase):
    """Tests for the UpdateResult dataclass."""

    def test_to_dict_returns_all_fields(self):
        """to_dict() should return a dict with all expected fields."""
        result = UpdateResult(
            component="zeek",
            success=True,
            old_version="6.0.3",
            new_version="6.0.4",
            started_at="2026-02-26T12:00:00+00:00",
            completed_at="2026-02-26T12:05:00+00:00",
            error=None,
            rollback_available=True,
        )
        d = result.to_dict()
        expected_keys = {
            "component",
            "success",
            "old_version",
            "new_version",
            "started_at",
            "completed_at",
            "error",
            "rollback_available",
        }
        self.assertEqual(set(d.keys()), expected_keys)

    def test_to_dict_preserves_values(self):
        """to_dict() should preserve exact values."""
        result = UpdateResult(
            component="suricata",
            success=False,
            old_version="7.0.2",
            new_version="7.0.2",
            started_at="2026-02-26T12:00:00+00:00",
            completed_at="2026-02-26T12:01:00+00:00",
            error="Pull failed",
            rollback_available=True,
        )
        d = result.to_dict()
        self.assertEqual(d["component"], "suricata")
        self.assertFalse(d["success"])
        self.assertEqual(d["error"], "Pull failed")
        self.assertTrue(d["rollback_available"])

    def test_to_dict_success_with_none_error(self):
        """Successful result should have None error."""
        result = UpdateResult(
            component="zeek",
            success=True,
            old_version="1.0",
            new_version="1.1",
            started_at="ts1",
            completed_at="ts2",
            error=None,
            rollback_available=True,
        )
        d = result.to_dict()
        self.assertIsNone(d["error"])
        self.assertTrue(d["success"])


class TestUpdateExecutorInitialization(unittest.TestCase):
    """Tests for UpdateExecutor initialization."""

    def test_default_parameters(self):
        """Default init should use expected paths."""
        ue = UpdateExecutor()
        self.assertEqual(
            ue._compose_file,
            "/opt/nettap/docker/docker-compose.yml",
        )
        self.assertEqual(ue._backup_dir, "/opt/nettap/backups")
        self.assertIsNone(ue._current_update)
        self.assertEqual(ue._update_history, [])
        self.assertEqual(ue._max_history, 50)

    def test_custom_parameters(self):
        """Custom parameters should be stored correctly."""
        ue = UpdateExecutor(
            compose_file="/custom/compose.yml",
            backup_dir="/custom/backups",
        )
        self.assertEqual(ue._compose_file, "/custom/compose.yml")
        self.assertEqual(ue._backup_dir, "/custom/backups")


class TestApplyUpdate(unittest.TestCase):
    """Tests for UpdateExecutor.apply_update()."""

    def _make_executor_with_mocks(self, success=True):
        """Create an UpdateExecutor with mocked internal methods."""
        ue = UpdateExecutor()

        async def mock_update_docker(components):
            results = []
            for comp in components:
                results.append(
                    UpdateResult(
                        component=comp,
                        success=success,
                        old_version="1.0.0",
                        new_version="1.1.0" if success else "1.0.0",
                        started_at=datetime.now(timezone.utc).isoformat(),
                        completed_at=datetime.now(timezone.utc).isoformat(),
                        error=None if success else "Update failed",
                        rollback_available=True,
                    )
                )
            return results

        async def mock_update_rules():
            return UpdateResult(
                component="suricata-rules",
                success=success,
                old_version="2026-02-25",
                new_version="2026-02-26",
                started_at=datetime.now(timezone.utc).isoformat(),
                completed_at=datetime.now(timezone.utc).isoformat(),
                error=None if success else "Update failed",
                rollback_available=True,
            )

        async def mock_update_geoip():
            return UpdateResult(
                component="geoip-db",
                success=success,
                old_version="2026-02-20",
                new_version="2026-02-26",
                started_at=datetime.now(timezone.utc).isoformat(),
                completed_at=datetime.now(timezone.utc).isoformat(),
                error=None if success else "Update failed",
                rollback_available=True,
            )

        ue._update_docker_images = mock_update_docker
        ue._update_suricata_rules = mock_update_rules
        ue._update_geoip = mock_update_geoip

        return ue

    def test_apply_update_returns_results_dict(self):
        """apply_update() should return dict with expected structure."""
        ue = self._make_executor_with_mocks()
        result = asyncio.run(ue.apply_update(["zeek"]))

        self.assertIn("results", result)
        self.assertIn("success", result)
        self.assertIn("total", result)
        self.assertIn("succeeded", result)
        self.assertIn("failed", result)

    # OLD CODE START — Malcolm's images are pinned: zeek and suricata are no longer pulled
    # def test_apply_update_docker_component(self):
    #     ... apply_update(["zeek", "suricata"]) -> total 2, succeeded 2, success True
    # OLD CODE END
    def test_apply_update_docker_component(self):
        """Malcolm containers are pinned: both fail with the reason, nothing is pulled."""
        ue = self._make_executor_with_mocks()
        result = asyncio.run(ue.apply_update(["zeek", "suricata"]))

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["succeeded"], 0)
        self.assertEqual(result["failed"], 2)
        self.assertFalse(result["success"])

    def test_apply_update_rules_component(self):
        """apply_update() should handle suricata-rules component."""
        ue = self._make_executor_with_mocks()
        result = asyncio.run(ue.apply_update(["suricata-rules"]))

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["succeeded"], 1)

    def test_apply_update_geoip_component(self):
        """apply_update() should handle geoip-db component."""
        ue = self._make_executor_with_mocks()
        result = asyncio.run(ue.apply_update(["geoip-db"]))

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["succeeded"], 1)

    def test_apply_update_unsupported_component(self):
        """apply_update() should return error for unsupported components."""
        ue = self._make_executor_with_mocks()
        result = asyncio.run(ue.apply_update(["unknown-component"]))

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertFalse(result["success"])
        self.assertIn("Unsupported", result["results"][0]["error"])

    def test_apply_update_empty_components(self):
        """apply_update() with empty list should return success with no results."""
        ue = self._make_executor_with_mocks()
        result = asyncio.run(ue.apply_update([]))

        self.assertEqual(result["total"], 0)
        self.assertTrue(result["success"])
        self.assertIn("message", result)

    def test_apply_update_stores_in_history(self):
        """apply_update() should store results in history."""
        ue = self._make_executor_with_mocks()
        self.assertEqual(len(ue._update_history), 0)

        asyncio.run(ue.apply_update(["zeek"]))

        self.assertEqual(len(ue._update_history), 1)

    def test_apply_update_mixed_components(self):
        """apply_update() should handle mixed component types."""
        ue = self._make_executor_with_mocks()
        result = asyncio.run(ue.apply_update(["zeek", "suricata-rules", "geoip-db"]))

        self.assertEqual(result["total"], 3)
        # OLD CODE START — zeek is a pinned Malcolm container now
        # self.assertEqual(result["succeeded"], 3)
        # OLD CODE END
        self.assertEqual(result["succeeded"], 2)
        self.assertEqual(
            [r["component"] for r in result["results"] if not r["success"]], ["zeek"]
        )

    def test_apply_update_with_failures(self):
        """apply_update() should report failures correctly."""
        ue = self._make_executor_with_mocks(success=False)
        result = asyncio.run(ue.apply_update(["zeek"]))

        self.assertEqual(result["failed"], 1)
        self.assertFalse(result["success"])


class TestConcurrentUpdatePrevention(unittest.TestCase):
    """Tests for concurrent update prevention."""

    def test_concurrent_update_rejected(self):
        """apply_update() should reject if update already in progress."""
        ue = UpdateExecutor()
        ue._current_update = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "components": ["zeek"],
            "status": "in_progress",
        }

        result = asyncio.run(ue.apply_update(["suricata"]))

        self.assertIn("error", result)
        self.assertIn("already in progress", result["error"])
        self.assertFalse(result["success"])

    def test_current_update_cleared_after_completion(self):
        """_current_update should be None after apply_update completes."""
        ue = UpdateExecutor()

        async def mock_update_docker(components):
            return [
                UpdateResult(
                    component=components[0],
                    success=True,
                    old_version="1.0",
                    new_version="1.1",
                    started_at="ts1",
                    completed_at="ts2",
                    error=None,
                    rollback_available=True,
                )
            ]

        ue._update_docker_images = mock_update_docker

        asyncio.run(ue.apply_update(["zeek"]))
        self.assertIsNone(ue._current_update)

    def test_current_update_cleared_on_error(self):
        """_current_update should be cleared even if update raises."""
        ue = UpdateExecutor()

        # OLD CODE START — zeek no longer reaches _update_docker_images (pinned)
        # async def mock_update_docker(components):
        #     raise RuntimeError("test error")
        #
        # ue._update_docker_images = mock_update_docker
        #
        # with self.assertRaises(RuntimeError):
        #     asyncio.run(ue.apply_update(["zeek"]))
        # OLD CODE END
        async def mock_update_rules():
            raise RuntimeError("test error")

        ue._update_suricata_rules = mock_update_rules

        with self.assertRaises(RuntimeError):
            asyncio.run(ue.apply_update(["suricata-rules"]))

        self.assertIsNone(ue._current_update)


class TestGetStatus(unittest.TestCase):
    """Tests for UpdateExecutor.get_status()."""

    def test_idle_status_when_no_update(self):
        """get_status() should return 'idle' when no update is running."""
        ue = UpdateExecutor()
        result = asyncio.run(ue.get_status())

        self.assertEqual(result["status"], "idle")
        self.assertIsNone(result["current_update"])
        self.assertIsNone(result["last_completed"])

    def test_in_progress_status(self):
        """get_status() should return 'in_progress' during update."""
        ue = UpdateExecutor()
        ue._current_update = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "components": ["zeek"],
            "status": "in_progress",
        }

        result = asyncio.run(ue.get_status())
        self.assertEqual(result["status"], "in_progress")
        self.assertIsNotNone(result["current_update"])

    def test_last_completed_from_history(self):
        """get_status() should include last completed update from history."""
        ue = UpdateExecutor()
        ue._update_history = [
            {"results": [], "success": True, "total": 1, "succeeded": 1, "failed": 0}
        ]

        result = asyncio.run(ue.get_status())
        self.assertIsNotNone(result["last_completed"])


class TestGetHistory(unittest.TestCase):
    """Tests for UpdateExecutor.get_history()."""

    def test_empty_history(self):
        """get_history() should return empty list initially."""
        ue = UpdateExecutor()
        result = asyncio.run(ue.get_history())
        self.assertEqual(result, [])

    def test_history_newest_first(self):
        """get_history() should return newest entries first."""
        ue = UpdateExecutor()
        ue._update_history = [
            {"id": 1, "results": []},
            {"id": 2, "results": []},
            {"id": 3, "results": []},
        ]

        result = asyncio.run(ue.get_history())
        self.assertEqual(result[0]["id"], 3)
        self.assertEqual(result[-1]["id"], 1)

    def test_history_returns_list(self):
        """get_history() should return a list."""
        ue = UpdateExecutor()
        result = asyncio.run(ue.get_history())
        self.assertIsInstance(result, list)


class TestHistoryBounding(unittest.TestCase):
    """Tests for update history size bounding."""

    def test_history_bounded_to_max(self):
        """History should be trimmed when exceeding max_history."""
        ue = UpdateExecutor()
        ue._max_history = 5

        async def mock_update_docker(components):
            return [
                UpdateResult(
                    component=components[0],
                    success=True,
                    old_version="1.0",
                    new_version="1.1",
                    started_at="ts1",
                    completed_at="ts2",
                    error=None,
                    rollback_available=True,
                )
            ]

        ue._update_docker_images = mock_update_docker

        for i in range(10):
            asyncio.run(ue.apply_update(["zeek"]))

        self.assertLessEqual(len(ue._update_history), 5)

    def test_history_keeps_newest(self):
        """After trimming, newest entries should be retained."""
        ue = UpdateExecutor()
        ue._max_history = 3

        for i in range(5):
            ue._update_history.append({"id": i})

        # Simulate trimming logic
        if len(ue._update_history) > ue._max_history:
            ue._update_history = ue._update_history[-ue._max_history :]

        self.assertEqual(len(ue._update_history), 3)
        self.assertEqual(ue._update_history[0]["id"], 2)
        self.assertEqual(ue._update_history[-1]["id"], 4)


class TestRollback(unittest.TestCase):
    """Tests for UpdateExecutor.rollback()."""

    def test_rollback_unknown_component_returns_error(self):
        """rollback() should return error for component with no backup."""
        ue = UpdateExecutor(backup_dir="/nonexistent/path")
        # OLD CODE START — zeek is a pinned Malcolm container now (answered before backups)
        # result = asyncio.run(ue.rollback("zeek"))
        # self.assertEqual(result["component"], "zeek")
        # OLD CODE END
        result = asyncio.run(ue.rollback("suricata-rules"))

        self.assertFalse(result["success"])
        self.assertEqual(result["component"], "suricata-rules")
        self.assertIn("No backup", result["message"])

    def test_rollback_unsupported_component(self):
        """rollback() should return error for unsupported component types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ue = UpdateExecutor(backup_dir=tmpdir)
            # Create a backup directory for an unsupported component
            os.makedirs(os.path.join(tmpdir, "unsupported-thing"))

            result = asyncio.run(ue.rollback("unsupported-thing"))
            self.assertFalse(result["success"])
            self.assertIn("not supported", result["message"])

    def test_rollback_returns_expected_structure(self):
        """rollback() should return dict with success, component, message."""
        ue = UpdateExecutor(backup_dir="/nonexistent/path")
        result = asyncio.run(ue.rollback("zeek"))

        self.assertIn("success", result)
        self.assertIn("component", result)
        self.assertIn("message", result)


class TestCreateBackup(unittest.TestCase):
    """Tests for UpdateExecutor._create_backup()."""

    def test_create_backup_creates_directory(self):
        """_create_backup() should create the backup directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ue = UpdateExecutor(backup_dir=tmpdir)
            path = asyncio.run(ue._create_backup("test-component"))

            self.assertTrue(os.path.exists(path))
            self.assertTrue(os.path.isdir(path))

    def test_create_backup_writes_metadata(self):
        """_create_backup() should write metadata.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ue = UpdateExecutor(backup_dir=tmpdir)
            path = asyncio.run(ue._create_backup("test-component"))

            metadata_file = os.path.join(path, "metadata.json")
            self.assertTrue(os.path.exists(metadata_file))

            with open(metadata_file, "r") as f:
                metadata = json.load(f)
            self.assertEqual(metadata["component"], "test-component")
            self.assertEqual(metadata["type"], "pre_update")
            self.assertIn("backup_time", metadata)

    def test_create_backup_returns_path(self):
        """_create_backup() should return the backup path string."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ue = UpdateExecutor(backup_dir=tmpdir)
            path = asyncio.run(ue._create_backup("test-component"))
            self.assertIsInstance(path, str)
            self.assertTrue(path.startswith(tmpdir))


class TestRunCommand(unittest.TestCase):
    """Tests for UpdateExecutor._run_command()."""

    def test_run_command_returns_output_and_code(self):
        """_run_command() should return (output, returncode) tuple."""
        ue = UpdateExecutor()
        output, code = asyncio.run(ue._run_command(["echo", "test"]))

        self.assertIn("test", output)
        self.assertEqual(code, 0)

    def test_run_command_handles_missing_command(self):
        """_run_command() should handle missing commands gracefully."""
        ue = UpdateExecutor()
        output, code = asyncio.run(ue._run_command(["nonexistent_cmd_xyz"]))

        self.assertNotEqual(code, 0)
        self.assertIn("not found", output.lower())

    def test_run_command_returns_nonzero_for_failure(self):
        """_run_command() should return non-zero code for failed commands."""
        ue = UpdateExecutor()
        output, code = asyncio.run(ue._run_command(["false"]))
        self.assertNotEqual(code, 0)

    def test_run_command_captures_stderr(self):
        """_run_command() should capture stderr in output."""
        ue = UpdateExecutor()
        output, code = asyncio.run(ue._run_command(["ls", "/nonexistent_path_xyz"]))
        # ls should fail and stderr should be captured
        self.assertNotEqual(code, 0)


class TestSetReferences(unittest.TestCase):
    """Tests for setting cross-service references."""

    def test_set_version_manager(self):
        """set_version_manager() should store the reference."""
        ue = UpdateExecutor()
        mock_vm = MagicMock()
        ue.set_version_manager(mock_vm)
        self.assertIs(ue._version_manager, mock_vm)

    def test_set_update_checker(self):
        """set_update_checker() should store the reference."""
        ue = UpdateExecutor()
        mock_uc = MagicMock()
        ue.set_update_checker(mock_uc)
        self.assertIs(ue._update_checker, mock_uc)


class TestRollbackOnlyWithABackup(unittest.TestCase):
    """#96: rollback_available was True whether or not the backup worked."""

    def _docker_update(self, inspect_result):
        """Update "zeek" with pull and up succeeding; docker inspect gives inspect_result."""
        with tempfile.TemporaryDirectory() as tmp:
            ue = UpdateExecutor(backup_dir=tmp)

            async def run_command(cmd):
                return inspect_result if cmd[1] == "inspect" else ("", 0)

            ue._run_command = run_command
            (result,) = asyncio.run(ue._update_docker_images(["zeek"]))
        return result

    def test_failed_image_backup_means_no_rollback(self):
        result = self._docker_update(("Error: No such object: zeek", 1))
        self.assertTrue(result.success)
        self.assertFalse(result.rollback_available)

    def test_saved_image_id_means_rollback(self):
        result = self._docker_update(("sha256:0123abcd\n", 0))
        self.assertTrue(result.rollback_available)

    def test_rules_update_without_a_rules_file_has_no_rollback(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            ue = UpdateExecutor(backup_dir=tmp)

            async def run_command(cmd):
                return ("", 0)

            ue._run_command = run_command
            with patch("os.path.exists", return_value=False):
                result = asyncio.run(ue._update_suricata_rules())
        self.assertTrue(result.success)
        self.assertFalse(result.rollback_available)

    def test_half_copied_backup_is_removed(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "GeoLite2-City.mmdb")
            with open(db, "w") as f:
                f.write("db")
            ue = UpdateExecutor(backup_dir=os.path.join(tmp, "backups"))
            with (
                patch.dict(os.environ, {"GEOIP_DB_PATH": db}),
                patch("shutil.copy2", side_effect=OSError(28, "No space left on device")),
            ):
                path = asyncio.run(ue._create_backup("geoip-db"))
            self.assertFalse(os.path.exists(path))
            self.assertFalse(ue._has_restorable_backup(path))


class TestPinnedMalcolmContainers(unittest.TestCase):
    """NetTap pins Malcolm's images. The old pull used names that aren't compose services
    and a compose file the daemon container doesn't have, and the rollback never used the
    saved image ID, so apply and rollback answer with the reason and run nothing."""

    REASON = (
        "NetTap pins Malcolm's container images to a tested release, so they can't be "
        "updated from here: update NetTap to get a newer Malcolm."
    )

    def _executor(self, tmp):
        ue = UpdateExecutor(backup_dir=tmp)
        ue.ran = []

        async def run_command(cmd):
            ue.ran.append(cmd)
            return ("sha256:0123abcd", 0)

        ue._run_command = run_command
        return ue

    def test_apply_runs_no_docker_and_says_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            ue = self._executor(tmp)
            result = asyncio.run(ue.apply_update(["suricata", "arkime", "pcap-capture"]))

        self.assertEqual(ue.ran, [])
        self.assertEqual(result["failed"], 3)
        for r in result["results"]:
            self.assertFalse(r["success"])
            self.assertEqual(r["error"], self.REASON)
            self.assertFalse(r["rollback_available"])

    def test_rollback_runs_no_docker_and_says_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved = os.path.join(tmp, "suricata", "20260101_000000")
            os.makedirs(saved)
            with open(os.path.join(saved, "image_id.txt"), "w") as f:
                f.write("sha256:0123abcd")
            ue = self._executor(tmp)
            result = asyncio.run(ue.rollback("suricata"))

        self.assertEqual(ue.ran, [])
        self.assertFalse(result["success"])
        self.assertEqual(result["message"], self.REASON)

    def test_update_the_checker_says_comes_with_nettap_is_not_applied(self):
        """e.g. Logstash's bundled GeoIP database, or a Malcolm container with no short name."""
        sentence = "Comes with Malcolm's Logstash image: update NetTap to get a newer one."

        class Checker:
            async def get_update_for(self, component):
                return {"component": component, "applies_with": sentence}

        with tempfile.TemporaryDirectory() as tmp:
            ue = self._executor(tmp)
            ue.set_update_checker(Checker())
            result = asyncio.run(ue.apply_update(["geoip-db", "nettap-filebeat"]))

        self.assertEqual(ue.ran, [])
        self.assertEqual([r["error"] for r in result["results"]], [sentence, sentence])
        self.assertFalse(any(r["rollback_available"] for r in result["results"]))

    def test_rules_update_is_still_applied(self):
        class Checker:
            async def get_update_for(self, component):
                return {"component": component, "applies_with": None}

        with tempfile.TemporaryDirectory() as tmp:
            ue = self._executor(tmp)
            ue.set_update_checker(Checker())
            result = asyncio.run(ue.apply_update(["suricata-rules"]))

        self.assertEqual(ue.ran[0], ["suricata-update", "update"])
        self.assertTrue(result["success"])


if __name__ == "__main__":
    unittest.main()
