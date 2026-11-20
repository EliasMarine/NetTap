"""
A9 (NET-227): POST /api/backup/import restores retention and the capture mode through the
paths the daemon really uses, reloads what it keeps in memory, and says what it skipped.

OpenSearch and the setup apply are mocked; files live in a temp dir.
"""

import json
import os
import shutil
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.backup import EXPORT_UNREADABLE, register_backup_routes
from api.error_replies import safe_error_middleware
from api.server import IlmSyncState
from services.config_backup import DETAILS_UNREADABLE, ConfigBackup
from services.device_details import DeviceDetailsStore
from services.notification_hub import NotificationHub
from storage.manager import RetentionConfig, StorageManager
from storage.retention_config import RetentionConfigManager

MIRROR_INI = (
    "[capture]\nmode = mirror\ninterface = eth1\nmanagement = eth0\n\n"
    "[pcap]\nrotate_mb = 250\n"
)
RETENTION = {
    "retention": {"hot_days": 45, "warm_days": 90, "cold_days": 7},
    "thresholds": {"disk_threshold_percent": 75, "emergency_threshold_percent": 88},
}
OTHER_MIRROR = {
    "capture_mode": "mirror",
    "capture_interface": "eth2",
    "management_interface": "eth0",
}


def _ok_response():
    return web.json_response({"status": "ok", "capture_restart": {"errors": []}})


class BackupImportTest(AioHTTPTestCase):
    # NET-320: what device_details.json holds when the daemon starts (None: no file yet)
    DETAILS_FILE: str | None = None

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ini = os.path.join(self.tmp, "capture-mode.conf")
        with open(self.ini, "w") as f:
            f.write(MIRROR_INI)
        env = patch.dict(os.environ, {"CAPTURE_CONFIG_PATH": self.ini})
        env.start()
        self.addCleanup(env.stop)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def get_application(self):
        # OLD CODE: app = web.Application() (NET-320: the production error middleware, for the 503)
        app = web.Application(middlewares=[safe_error_middleware])
        with patch.object(StorageManager, "_create_client", return_value=MagicMock()):
            storage = StorageManager(RetentionConfig(), "http://localhost:9200")
        app["storage"] = storage
        app["opensearch_url"] = "http://localhost:9200"
        app["ilm_sync"] = IlmSyncState(lock=storage.ilm_lock)
        mgr = RetentionConfigManager(
            config_path=os.path.join(self.tmp, "retention.json"),
            env_file=os.path.join(self.tmp, ".env"),
        )
        mgr.load()
        app["retention_config_manager"] = mgr
        app["excluded_ips_file"] = os.path.join(self.tmp, "excluded_ips.json")
        app["excluded_ips"] = []
        # OLD CODE: app["notification_hub"] = MagicMock() (NET-224: the restore goes through the real hub)
        paths = {
            k: os.path.join(self.tmp, f"{k}.json")
            for k in (
                "notification_config",
                "bandwidth_cap",
                "home_location",
                "alert_acks",
                "suppressions",
                "env_file",
            )
        }
        paths["excluded_ips"] = app["excluded_ips_file"]
        paths["capture_config"] = self.ini
        paths["retention_config"] = os.path.join(self.tmp, "retention.json")
        # OLD CODE: register_backup_routes(app, ConfigBackup(config_paths=paths)) (NET-224: with the hub)
        hub = NotificationHub(
            config_path=paths["notification_config"], env_file=paths["env_file"]
        )
        app["notification_hub"] = hub
        # OLD CODE: register_backup_routes(app, ConfigBackup(config_paths=paths, notification_hub=hub))
        # (NET-320: with the device details store, as create_app builds it)
        appdata = os.path.join(self.tmp, "appdata")
        if self.DETAILS_FILE is not None:
            os.makedirs(appdata)
            with open(os.path.join(appdata, "device_details.json"), "w") as f:
                f.write(self.DETAILS_FILE)
        self.details = DeviceDetailsStore(appdata)
        register_backup_routes(
            app,
            ConfigBackup(
                config_paths=paths, notification_hub=hub, device_details=self.details
            ),
        )
        return app

    async def _import(self, sections, query=""):
        body = {"metadata": {"schema_version": 2}, "sections": sections}
        resp = await self.client.post(f"/api/backup/import{query}", json=body)
        return resp.status, await resp.json()


class TestInvalidImportAppliesNothing(BackupImportTest):
    """An import that fails validation is a 400 before anything is saved or restarted."""

    async def test_a_newer_schema_restores_neither_retention_nor_capture(self):
        apply = AsyncMock(return_value=_ok_response())
        body = {
            "metadata": {"schema_version": 99},
            "sections": {
                "storage_retention": RETENTION,
                "capture_mode_config": OTHER_MIRROR,
            },
        }
        with (
            patch("api.backup._apply_configuration", new=apply),
            patch("api.server.apply_ilm_policies_from_config") as ilm,
        ):
            resp = await self.client.post(
                "/api/backup/import?apply_capture=1", json=body
            )
        self.assertEqual(resp.status, 400)
        # old code: retention saved, ILM pushed and capture restarted, then the 400
        apply.assert_not_called()
        ilm.assert_not_called()
        self.assertEqual(self.app["storage"].config.hot_days, 90)
        with open(os.path.join(self.tmp, "retention.json")) as f:
            self.assertEqual(
                json.load(f)["retention"]["hot_days"], 90
            )  # not the backup's 45

    async def test_a_body_that_isnt_an_object_is_a_400(self):
        resp = await self.client.post("/api/backup/import", json=[1, 2])
        self.assertEqual(resp.status, 400)  # old code: 500 on data.get

    async def test_a_schema_version_that_isnt_a_number_is_a_400(self):
        body = {"metadata": {"schema_version": "2"}, "sections": {}}
        resp = await self.client.post("/api/backup/import", json=body)
        self.assertEqual(resp.status, 400)  # old code: 500 (TypeError)


class TestRetentionRestore(BackupImportTest):
    async def test_restored_through_the_storage_config_path(self):
        with patch(
            "api.server.apply_ilm_policies_from_config",
            return_value={"nettap-hot-policy": "updated"},
        ) as apply:
            status, result = await self._import({"storage_retention": RETENTION})

        self.assertEqual(status, 200, result)
        self.assertIn("storage_retention", result["applied"])
        # live at once: the storage manager and OpenSearch both have it
        self.assertEqual(self.app["storage"].config.hot_days, 45)
        self.assertEqual(self.app["storage"].config.emergency_threshold, 0.88)
        apply.assert_called_once()
        with open(os.path.join(self.tmp, "retention.json")) as f:
            self.assertEqual(json.load(f)["retention"]["cold_days"], 7)

    async def test_an_empty_section_from_an_old_backup_is_skipped_with_a_reason(self):
        status, result = await self._import({"storage_retention": {}})
        self.assertEqual(status, 200)
        self.assertEqual(result["skipped"][0]["section"], "storage_retention")
        self.assertNotIn("storage_retention", result["applied"])

    async def test_invalid_values_are_an_error(self):
        bad = {"retention": {"hot_days": 0}}
        status, result = await self._import({"storage_retention": bad})
        self.assertEqual(status, 400)
        self.assertTrue(any("Retention" in e for e in result["errors"]))
        self.assertEqual(self.app["storage"].config.hot_days, 90)


class TestCaptureRestore(BackupImportTest):
    async def test_not_applied_without_confirmation(self):
        with patch("api.backup._apply_configuration", new=AsyncMock()) as apply:
            status, result = await self._import({"capture_mode_config": OTHER_MIRROR})
        apply.assert_not_called()
        self.assertEqual(status, 200)
        self.assertEqual(result["skipped"][0]["section"], "capture_mode_config")
        self.assertIn("wasn't confirmed", result["skipped"][0]["reason"])

    async def test_confirmed_goes_through_setup_with_validated_values_only(self):
        sneaky = {**OTHER_MIRROR, "storage": {"hot_days": 1}, "extra": "x\nX=1"}
        apply = AsyncMock(return_value=_ok_response())
        with patch("api.backup._apply_configuration", new=apply):
            status, result = await self._import(
                {"capture_mode_config": sneaky}, "?apply_capture=1"
            )
        self.assertEqual(status, 200, result)
        self.assertIn("capture_mode_config", result["applied"])
        _app, body, cfg = apply.call_args.args
        self.assertEqual(body, OTHER_MIRROR)  # no storage, no extra keys
        self.assertEqual(cfg.interface, "eth2")
        # OLD CODE: self.assertEqual(cfg.pcap_rotate_mb, 250)  # the box's own rotation size
        # _apply_configuration keeps the box's rotation size now (test_setup_configure)
        self.assertEqual(cfg.pcap_rotate_mb, 0)

    async def test_a_bad_mode_or_name_is_refused_and_nothing_applied(self):
        apply = AsyncMock(return_value=_ok_response())
        for bad in (
            {"capture_mode": "mirror\nX=1", "capture_interface": "eth2"},
            {"capture_mode": "evil", "capture_interface": "eth2"},
            {"capture_mode": "mirror", "capture_interface": "eth2;reboot"},
        ):
            with patch("api.backup._apply_configuration", new=apply):
                status, result = await self._import(
                    {"capture_mode_config": bad}, "?apply_capture=1"
                )
            self.assertEqual(status, 400, bad)
            self.assertTrue(any("Capture mode" in e for e in result["errors"]))
        apply.assert_not_called()

    async def test_the_same_mode_is_skipped(self):
        same = {
            "capture_mode": "mirror",
            "capture_interface": "eth1",
            "management_interface": "eth0",
        }
        with patch("api.backup._apply_configuration", new=AsyncMock()) as apply:
            _, result = await self._import(
                {"capture_mode_config": same}, "?apply_capture=1"
            )
        apply.assert_not_called()
        self.assertEqual(
            result["skipped"][0]["reason"], "Already the current capture mode"
        )

    async def test_a_failed_container_restart_is_not_reported_as_restored(self):
        response = web.json_response(
            {"status": "ok", "capture_restart": {"errors": ["docker restart failed"]}}
        )
        with patch(
            "api.backup._apply_configuration", new=AsyncMock(return_value=response)
        ):
            status, result = await self._import(
                {"capture_mode_config": OTHER_MIRROR}, "?apply_capture=1"
            )
        self.assertEqual(status, 400)
        self.assertNotIn("capture_mode_config", result["applied"])
        self.assertTrue(any("didn't restart" in e for e in result["errors"]))

    async def test_setups_refusal_is_reported(self):
        response = web.json_response({"error": "eth2 has an IP address"}, status=400)
        with patch(
            "api.backup._apply_configuration", new=AsyncMock(return_value=response)
        ):
            status, result = await self._import(
                {"capture_mode_config": OTHER_MIRROR}, "?apply_capture=1"
            )
        self.assertEqual(status, 400)
        self.assertIn("eth2 has an IP address", " ".join(result["errors"]))


class TestBandwidthCapReload(BackupImportTest):
    async def test_a_restored_cap_takes_effect_at_once(self):
        from services.bandwidth_tracker import BandwidthTracker

        cap_file = os.path.join(self.tmp, "bandwidth_cap.json")
        with patch("services.bandwidth_tracker._CAP_FILE", cap_file):
            self.app["bandwidth_tracker"] = BandwidthTracker(client=None)
            status, result = await self._import(
                {"bandwidth_cap": {"monthly_cap_bytes": 7_000_000_000}}
            )
            self.assertEqual(status, 200, result)
            cap = self.app["bandwidth_tracker"].get_cap()
        self.assertEqual(cap["monthly_cap_bytes"], 7_000_000_000)


class TestRunningStateReload(BackupImportTest):
    async def test_the_boxs_own_ip_stays_excluded(self):
        """create_app excludes the management IP at runtime only; a reload must keep it."""
        self.app["appliance_ip"] = "192.0.2.1"
        status, result = await self._import({"excluded_ips": ["192.0.2.7"]})
        self.assertEqual(status, 200, result)
        self.assertEqual(self.app["excluded_ips"], ["192.0.2.7", "192.0.2.1"])

    async def test_excluded_ips_and_notifications_take_effect_at_once(self):
        # OLD CODE START — NET-224: checked the bare reload; the restore goes through the hub now
        # status, result = await self._import(
        #     {"excluded_ips": ["192.0.2.7"], "notification_rules": {}}
        # )
        # self.assertEqual(status, 200, result)
        # self.assertEqual(self.app["excluded_ips"], ["192.0.2.7"])
        # self.app["notification_hub"]._load_config.assert_called_once()
        # OLD CODE END
        hub = self.app["notification_hub"]
        old = hub.configure("slack", {"webhook_url": "https://hooks.example.net/a"})
        hub.add_rule("alert", [old["id"]], 2)
        channel = {"id": "new", "type": "slack", "name": "New", "config": {}}
        status, result = await self._import(
            {
                "excluded_ips": ["192.0.2.7"],
                "notification_channels": {"new": channel},
                "notification_rules": {},
            }
        )
        self.assertEqual(status, 200, result)
        self.assertEqual(self.app["excluded_ips"], ["192.0.2.7"])
        # live in the running hub, no reload: the old channel and its rule are gone
        self.assertEqual([c["id"] for c in hub.get_channels()], ["new"])
        self.assertEqual(hub.get_rules(), [])

    async def test_a_malformed_channel_is_refused_and_nothing_changes(self):
        hub = self.app["notification_hub"]
        kept = hub.configure("slack", {"webhook_url": "https://hooks.example.net/a"})
        status, result = await self._import(
            {
                "notification_channels": {
                    "ok": {"id": "ok", "type": "slack", "config": {}},
                    "bad": {"type": "slack", "config": {}},
                }
            }
        )
        self.assertEqual(status, 400, result)
        self.assertIn("'bad'", " ".join(result["errors"]))
        self.assertEqual([c["id"] for c in hub.get_channels()], [kept["id"]])
        resp = await self.client.get("/api/backup/export")
        self.assertEqual(resp.status, 200)


class TestQuietHoursPreflight(BackupImportTest):
    """NET-330: bad quiet hours refuse the whole import, so a valid section beside them (here the
    bandwidth cap) isn't applied either."""

    async def test_bad_quiet_hours_beside_a_valid_cap_apply_nothing(self):
        cap_file = os.path.join(self.tmp, "bandwidth_cap.json")
        with open(cap_file, "w") as f:
            json.dump({"monthly_cap_bytes": 1_000_000_000_000}, f)
        with open(cap_file) as f:
            before = f.read()
        bad = {
            "enabled": True,
            "start": "0٠:0٠",
            "end": "07:00",
            "critical_through": True,
        }

        status, result = await self._import(
            {
                "notification_quiet": bad,
                "bandwidth_cap": {"monthly_cap_bytes": 500_000_000_000},
            }
        )

        self.assertEqual(status, 400, result)
        self.assertEqual(result["applied"], [])
        self.assertIn("start and end must be times", " ".join(result["errors"]))
        with open(cap_file) as f:
            self.assertEqual(f.read(), before)
        self.assertFalse(self.app["notification_hub"].quiet()["enabled"])


class DetailsImportTest(BackupImportTest):
    """NET-320: a device details section beside a valid bandwidth cap."""

    CAP = {"monthly_cap_bytes": 500_000_000_000}

    def _cap_file(self) -> str:
        """The box's own cap, so a refused import can be shown to leave it alone."""
        path = os.path.join(self.tmp, "bandwidth_cap.json")
        with open(path, "w") as f:
            json.dump({"monthly_cap_bytes": 1_000_000_000_000}, f)
        return path

    def _read(self, path: str) -> str:
        with open(path) as f:
            return f.read()


class TestDeviceDetailsPreflight(DetailsImportTest):
    async def test_a_bad_section_beside_a_valid_cap_applies_nothing(self):
        self.details.update("AA:BB:CC:DD:EE:01", {"group": "Kids"})
        cap_file = self._cap_file()
        before = self._read(cap_file)

        status, result = await self._import(
            {
                # not canonical: two spellings could otherwise collapse onto one device
                "device_details": {"aa:bb:cc:dd:ee:02": {"owner": "Sam"}},
                "bandwidth_cap": self.CAP,
            }
        )

        self.assertEqual(status, 400, result)
        self.assertEqual(result["applied"], [])
        self.assertIn("AA:BB:CC:DD:EE:FF", " ".join(result["errors"]))
        self.assertEqual(self._read(cap_file), before)
        self.assertEqual(
            self.details.export(), {"AA:BB:CC:DD:EE:01": {"group": "Kids"}}
        )

    async def test_validate_runs_off_the_loop_and_refuses_a_bad_section(self):
        body = {
            "metadata": {"schema_version": 2},
            "sections": {
                "device_details": {"AA:BB:CC:DD:EE:01": {"watch_after_min": 7}}
            },
        }
        offload = AsyncMock(side_effect=lambda fn, *args: fn(*args))
        with patch("api.backup.run_blocking", new=offload):
            resp = await self.client.post("/api/backup/validate", json=body)
        result = await resp.json()

        self.assertEqual(resp.status, 200)
        offload.assert_awaited_once_with(
            self.app["config_backup"].validate_import, body
        )
        self.assertFalse(result["is_valid"])
        self.assertIn("Pick 15, 30, 60, 240 or 1440 minutes.", result["errors"][0])


class TestDamagedDetailsFile(DetailsImportTest):
    """A details file this daemon can't trust: the import and the export both refuse."""

    DETAILS_FILE = "{not json"

    async def test_the_import_is_refused_and_a_valid_cap_beside_it_left_alone(self):
        cap_file = self._cap_file()
        before = self._read(cap_file)

        status, result = await self._import(
            {
                "device_details": {"AA:BB:CC:DD:EE:01": {"group": "Kids"}},
                "bandwidth_cap": self.CAP,
            }
        )

        self.assertEqual(status, 400, result)
        self.assertEqual(result["applied"], [])
        self.assertEqual(result["errors"], [DETAILS_UNREADABLE])
        self.assertEqual(self._read(cap_file), before)

    async def test_export_is_a_503_with_the_fixed_reason_and_the_log_names_the_file(
        self,
    ):
        with self.assertLogs("nettap.api.backup", "ERROR") as logs:
            resp = await self.client.get("/api/backup/export")

        self.assertEqual(resp.status, 503)
        self.assertEqual(await resp.json(), {"error": EXPORT_UNREADABLE})
        self.assertIn("device_details.json", "\n".join(logs.output))
