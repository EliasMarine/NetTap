"""
Tests for the ConfigBackup service.

Covers: export completeness, import validation, version compatibility,
section writing, round-trip export/import.
"""

import json
from pathlib import Path

import pytest

from services.config_backup import ConfigBackup, _SCHEMA_VERSION, _NETTAP_VERSION
from services.device_custom import DeviceCustomStore
from services.notification_hub import NotificationHub


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config_paths(tmp_path):
    """Create temp config files and return the paths dict."""
    paths = {
        "notification_config": str(tmp_path / "notifications.json"),
        "device_baseline": str(tmp_path / "device_baseline.json"),
        "excluded_ips": str(tmp_path / "excluded_ips.json"),
        "env_file": str(tmp_path / ".env"),
        "bandwidth_cap": str(tmp_path / "bandwidth_cap.json"),
        # OLD CODE START — A9: the daemon never used these two names
        # "capture_config": str(tmp_path / "capture_config.json"),
        # "retention_config": str(tmp_path / "retention_config.json"),
        # OLD CODE END
        "capture_config": str(tmp_path / "capture-mode.conf"),
        "retention_config": str(tmp_path / "retention.json"),
        "home_location": str(tmp_path / "home_location.json"),
        "alert_acks": str(tmp_path / "alert_acks.json"),
        "suppressions": str(tmp_path / "nettap-suppress.json"),
    }

    # Write sample config files
    (tmp_path / "notifications.json").write_text(
        json.dumps(
            {
                "channels": {
                    # OLD CODE: "ch1": {"type": "email", "config": {"to": "admin@test.com"}}, (NET-224: the hub stores channels with their id)
                    "ch1": {
                        "id": "ch1",
                        "type": "email",
                        "config": {"to": "admin@test.com"},
                    },
                },
                "rules": {
                    "r1": {"event_type": "alert", "channel": "ch1"},
                },
            }
        )
    )

    (tmp_path / "device_baseline.json").write_text(
        json.dumps(
            {
                "aliases": {"00:11:22:33:44:55": "My Laptop"},
                "devices": [],
            }
        )
    )

    (tmp_path / "excluded_ips.json").write_text(json.dumps(["192.168.1.1", "10.0.0.1"]))

    (tmp_path / "bandwidth_cap.json").write_text(
        # OLD CODE: {"monthly_cap_gb": 1000, "enabled": True} (a shape the tracker never wrote)
        json.dumps(
            {
                "monthly_cap_bytes": 1_000_000_000_000,
            }
        )
    )

    # OLD CODE START — A9: files in shapes the daemon never wrote
    # (tmp_path / "capture_config.json").write_text(
    #     json.dumps({"mode": "bridge", "interfaces": ["eth0", "eth1"]})
    # )
    # (tmp_path / "retention_config.json").write_text(
    #     json.dumps({"hot_days": 90, "warm_days": 180, "cold_days": 30})
    # )
    # OLD CODE END
    # As save_capture_config and RetentionConfigManager write them
    (tmp_path / "capture-mode.conf").write_text(
        "[capture]\nmode = mirror\ninterface = eth1\nmanagement = eth0\n\n"
        "[bridge]\nwan_interface = eth0\nlan_interface = eth1\n"
    )
    (tmp_path / "retention.json").write_text(
        json.dumps(
            {
                "version": 1,
                "retention": {"hot_days": 90, "warm_days": 180, "cold_days": 30},
                "thresholds": {
                    "disk_threshold_percent": 80,
                    "emergency_threshold_percent": 90,
                },
                "ilm_applied": {"last_success": "2026-11-09T00:00:00+00:00"},
            }
        )
    )

    return paths


# OLD CODE START — NET-200: device names come from the DeviceCustomStore, not the baseline file
# @pytest.fixture
# def backup(config_paths):
#     """Return a ConfigBackup with temp config paths."""
#     return ConfigBackup(config_paths=config_paths)
# OLD CODE END
@pytest.fixture
def backup(config_paths, tmp_path):
    """Return a ConfigBackup with temp config paths and one owner-named device."""
    store = DeviceCustomStore(str(tmp_path / "appdata"))
    store.set_name("00:11:22:33:44:55", "My Laptop")
    # OLD CODE: return ConfigBackup(config_paths=config_paths, device_custom=store) (NET-224: plus the running hub)
    hub = NotificationHub(
        config_path=config_paths["notification_config"],
        env_file=config_paths["env_file"],
    )
    return ConfigBackup(
        config_paths=config_paths, device_custom=store, notification_hub=hub
    )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_has_metadata(self, backup):
        """Export should include version and timestamp metadata."""
        config = backup.export_config()

        assert "metadata" in config
        assert config["metadata"]["nettap_version"] == _NETTAP_VERSION
        assert config["metadata"]["schema_version"] == _SCHEMA_VERSION
        assert "exported_at" in config["metadata"]

    def test_export_has_all_sections(self, backup):
        """Export should include all configuration sections."""
        config = backup.export_config()
        sections = config["sections"]

        assert "capture_mode_config" in sections
        assert "storage_retention" in sections
        assert "notification_channels" in sections
        assert "notification_rules" in sections
        assert "device_aliases" in sections
        assert "device_pictures" in sections
        assert "excluded_ips" in sections
        assert "bandwidth_cap" in sections

    def test_export_correct_values(self, backup):
        """Export should contain the actual config values."""
        config = backup.export_config()
        sections = config["sections"]

        assert sections["excluded_ips"] == ["192.168.1.1", "10.0.0.1"]
        # OLD CODE: assert sections["bandwidth_cap"]["monthly_cap_gb"] == 1000
        assert sections["bandwidth_cap"] == {"monthly_cap_bytes": 1_000_000_000_000}
        assert sections["device_aliases"] == {"00:11:22:33:44:55": "My Laptop"}
        assert "ch1" in sections["notification_channels"]

    def test_export_missing_files(self, tmp_path):
        """Export should use defaults for missing config files."""
        paths = {
            "notification_config": str(tmp_path / "nonexistent.json"),
        }
        b = ConfigBackup(config_paths=paths)
        config = b.export_config()

        # Should not crash, should have empty defaults
        assert config["sections"]["notification_channels"] == {}

    def test_export_unreadable_file_fails(self, backup, config_paths):
        """#96: a corrupt config file fails the export, not a backup missing it."""
        Path(config_paths["excluded_ips"]).write_text("[not json")
        with pytest.raises(ValueError, match="excluded_ips"):
            backup.export_config()

    def test_import_over_corrupt_file_still_works(self, backup, config_paths):
        """Restoring a backup over a corrupt file replaces it."""
        Path(config_paths["notification_config"]).write_text("{not json")
        data = {
            "metadata": {
                "nettap_version": _NETTAP_VERSION,
                "schema_version": _SCHEMA_VERSION,
            },
            # OLD CODE: "sections": {"notification_channels": {"ch9": {"type": "x"}}}, (NET-224: a channel needs its id and a real type)
            "sections": {
                "notification_channels": {"ch9": {"id": "ch9", "type": "slack"}}
            },
        }
        result = backup.import_config(data)
        assert result["success"] is True
        notif = json.loads(Path(config_paths["notification_config"]).read_text())
        assert "ch9" in notif["channels"]


# ---------------------------------------------------------------------------
# Validate import
# ---------------------------------------------------------------------------


class TestValidateImport:
    def test_valid_data(self, backup):
        """Valid import data should pass validation."""
        data = {
            "metadata": {
                "nettap_version": _NETTAP_VERSION,
                "schema_version": _SCHEMA_VERSION,
            },
            "sections": {
                "excluded_ips": ["1.2.3.4"],
            },
        }
        result = backup.validate_import(data)
        assert result["is_valid"] is True
        assert len(result["errors"]) == 0

    def test_non_dict_data(self, backup):
        """Non-dict data should fail validation."""
        result = backup.validate_import("not a dict")
        assert result["is_valid"] is False

    def test_missing_metadata_still_valid(self, backup):
        """Missing metadata defaults to empty — still valid but may warn."""
        result = backup.validate_import({"sections": {}})
        assert result["is_valid"] is True

    def test_missing_sections_still_valid(self, backup):
        """Missing sections defaults to empty — valid with warning."""
        result = backup.validate_import(
            {
                "metadata": {"schema_version": 1, "nettap_version": "0.4.0"},
            }
        )
        assert result["is_valid"] is True

    @pytest.mark.parametrize("version", ["2", None, 2.5, True, [2]])
    def test_a_schema_version_that_isnt_a_whole_number_is_invalid(
        self, backup, version
    ):
        """Old code: TypeError comparing it, so the reply was a 500."""
        result = backup.validate_import(
            {"metadata": {"schema_version": version}, "sections": {}}
        )
        assert result["is_valid"] is False
        assert any("schema version" in e.lower() for e in result["errors"])

    def test_newer_schema_version(self, backup):
        """Schema version newer than supported should fail."""
        data = {
            "metadata": {
                "nettap_version": _NETTAP_VERSION,
                "schema_version": _SCHEMA_VERSION + 10,
            },
            "sections": {},
        }
        result = backup.validate_import(data)
        assert result["is_valid"] is False
        assert any("newer" in e for e in result["errors"])

    def test_different_nettap_version_warns(self, backup):
        """Different NetTap version should produce a warning."""
        data = {
            "metadata": {
                "nettap_version": "99.99.99",
                "schema_version": _SCHEMA_VERSION,
            },
            "sections": {"excluded_ips": []},
        }
        result = backup.validate_import(data)
        assert result["is_valid"] is True
        assert len(result["warnings"]) > 0

    def test_unknown_section_warns(self, backup):
        """Unknown sections should produce a warning."""
        data = {
            "metadata": {
                "nettap_version": _NETTAP_VERSION,
                "schema_version": _SCHEMA_VERSION,
            },
            "sections": {"unknown_section": {}},
        }
        result = backup.validate_import(data)
        assert result["is_valid"] is True
        assert any("unknown" in w.lower() for w in result["warnings"])

    def test_preview_included(self, backup):
        """Validation should include preview of importable sections."""
        data = {
            "metadata": {
                "nettap_version": _NETTAP_VERSION,
                "schema_version": _SCHEMA_VERSION,
            },
            "sections": {
                "excluded_ips": ["1.2.3.4", "5.6.7.8"],
                "bandwidth_cap": {"monthly_cap_gb": 500},
            },
        }
        result = backup.validate_import(data)
        assert "excluded_ips" in result["preview"]
        assert result["preview"]["excluded_ips"]["size"] == 2


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


class TestImport:
    def test_import_applies_sections(self, backup, config_paths):
        """Import should write sections to their config files."""
        data = {
            "metadata": {
                "nettap_version": _NETTAP_VERSION,
                "schema_version": _SCHEMA_VERSION,
            },
            "sections": {
                "excluded_ips": ["10.10.10.10"],
                # OLD CODE: "bandwidth_cap": {"monthly_cap_gb": 500, "enabled": False},
                "bandwidth_cap": {"monthly_cap_bytes": 500_000_000_000},
            },
        }

        result = backup.import_config(data)

        assert result["success"] is True
        assert "excluded_ips" in result["applied"]
        assert "bandwidth_cap" in result["applied"]

        # Verify files were written
        ips = json.loads(Path(config_paths["excluded_ips"]).read_text())
        assert ips == ["10.10.10.10"]

        cap = json.loads(Path(config_paths["bandwidth_cap"]).read_text())
        # OLD CODE: assert cap["monthly_cap_gb"] == 500
        assert cap == {"monthly_cap_bytes": 500_000_000_000}

    @pytest.mark.parametrize(
        "bad",
        [
            [500],
            "500",
            {"monthly_cap_gb": 500},  # not the tracker's key
            {"monthly_cap_bytes": "500"},
            {"monthly_cap_bytes": True},
            {"monthly_cap_bytes": -1},
            {"monthly_cap_bytes": float("inf")},  # JSON Infinity
        ],
    )
    def test_a_malformed_bandwidth_cap_is_refused_and_the_file_kept(
        self, backup, config_paths, bad
    ):
        """Old code wrote it, and the tracker then crashed create_app on every start."""
        path = Path(config_paths["bandwidth_cap"])
        before = path.read_text()
        result = backup.import_config(
            {
                "metadata": {"schema_version": _SCHEMA_VERSION},
                "sections": {"bandwidth_cap": bad},
            }
        )
        assert result["success"] is False
        assert "bandwidth_cap" not in result["applied"]
        assert path.read_text() == before

    def test_a_backup_without_a_cap_leaves_the_boxs_cap(self, backup, config_paths):
        path = Path(config_paths["bandwidth_cap"])
        before = path.read_text()
        result = backup.import_config(
            {
                "metadata": {"schema_version": _SCHEMA_VERSION},
                "sections": {"bandwidth_cap": {}},
            }
        )
        assert result["skipped"] == [
            {"section": "bandwidth_cap", "reason": "No bandwidth cap in this backup"}
        ]
        assert path.read_text() == before

    def test_import_no_sections(self, backup):
        """Import with no sections should succeed but apply nothing."""
        result = backup.import_config(
            {
                "metadata": {"schema_version": 1, "nettap_version": "0.4.0"},
                "sections": {},
            }
        )
        assert result["success"] is True
        assert result["applied"] == []

    def test_import_non_dict_fails(self, backup):
        """Import with non-dict data should fail validation."""
        result = backup.import_config("not a dict")
        assert result["success"] is False

    def test_import_notification_config(self, backup, config_paths):
        """Import should merge notification channels and rules."""
        data = {
            "metadata": {
                "nettap_version": _NETTAP_VERSION,
                "schema_version": _SCHEMA_VERSION,
            },
            "sections": {
                "notification_channels": {
                    # OLD CODE: "ch2": {"type": "discord", "config": {}}, (NET-224: with its id)
                    "ch2": {"id": "ch2", "type": "discord", "config": {}},
                },
                "notification_rules": {
                    "r2": {"event_type": "new_device", "channel": "ch2"},
                },
            },
        }

        result = backup.import_config(data)
        assert result["success"] is True

        notif = json.loads(Path(config_paths["notification_config"]).read_text())
        assert "ch2" in notif["channels"]
        assert "r2" in notif["rules"]

    def test_round_trip(self, backup):
        """Export then import should preserve data."""
        exported = backup.export_config()
        result = backup.import_config(exported)
        assert result["success"] is True

        # Re-export and compare sections
        re_exported = backup.export_config()
        for key in exported["sections"]:
            assert re_exported["sections"][key] == exported["sections"][key]


# ---------------------------------------------------------------------------
# A9: the real files, no secrets, and the owner's other settings
# ---------------------------------------------------------------------------


def _data(sections: dict) -> dict:
    return {
        "metadata": {"nettap_version": _NETTAP_VERSION, "schema_version": 2},
        "sections": sections,
    }


SECRET_CHANNELS = {
    "mail": {
        "id": "mail",
        "type": "email",
        "name": "Mail",
        "config": {
            "smtp_host": "smtp.example.net",
            "smtp_port": 587,
            "smtp_user": "device-A",
            "smtp_pass": "hunter2",
            "use_tls": True,
            "recipients": ["owner@example.net"],
        },
    },
    "hook": {
        "id": "hook",
        "type": "webhook",
        "name": "Hook",
        "config": {
            "url": "https://hooks.example.net/T0KEN",
            "headers": {"Authorization": "Bearer s3cret"},
        },
    },
}


class TestA9Export:
    def test_capture_and_retention_come_from_the_files_the_daemon_uses(self, backup):
        sections = backup.export_config()["sections"]
        assert sections["capture_mode_config"] == {
            "capture_mode": "mirror",
            "capture_interface": "eth1",
            "management_interface": "eth0",
        }
        # The days and thresholds, not the ILM status stored beside them
        assert sections["storage_retention"] == {
            "retention": {"hot_days": 90, "warm_days": 180, "cold_days": 30},
            "thresholds": {
                "disk_threshold_percent": 80,
                "emergency_threshold_percent": 90,
            },
        }

    def test_no_notification_secret_is_exported(self, backup, config_paths):
        Path(config_paths["notification_config"]).write_text(
            json.dumps({"channels": SECRET_CHANNELS, "rules": {}})
        )
        exported = backup.export_config()
        text = json.dumps(exported)
        # the values; only the names of what was left out go in the file
        for secret in ("hunter2", "T0KEN", "s3cret", "Authorization"):
            assert secret not in text
        channels = exported["sections"]["notification_channels"]
        assert channels["mail"]["config"]["smtp_host"] == "smtp.example.net"
        assert channels["mail"]["secrets_left_out"] == ["smtp_pass"]
        assert channels["hook"]["secrets_left_out"] == ["headers", "url"]

    def test_the_owners_other_files_are_exported(self, backup, config_paths):
        Path(config_paths["home_location"]).write_text(
            json.dumps({"lat": 51.5, "lon": -0.1, "label": "Home"})
        )
        Path(config_paths["alert_acks"]).write_text(
            json.dumps({"a1": {"acknowledged_at": "2026-11-05T23:32:09+00:00"}})
        )
        suppress = {
            "global": [
                {"signature_id": 2001, "expires_at": "2026-12-01T00:00:00+00:00"}
            ],
            "per_device": {},
            "false_positives": [],
        }
        Path(config_paths["suppressions"]).write_text(json.dumps(suppress))

        sections = backup.export_config()["sections"]
        assert sections["home_location"] == {"lat": 51.5, "lon": -0.1, "label": "Home"}
        assert sections["alert_acknowledgements"]["a1"]["acknowledged_at"]
        assert sections["alert_suppressions"] == suppress

    def test_export_is_schema_2_and_a_newer_file_is_refused(self, backup):
        assert backup.export_config()["metadata"]["schema_version"] == 2
        assert not backup.validate_import(
            {"metadata": {"schema_version": 3}, "sections": {"excluded_ips": []}}
        )["is_valid"]


class TestA9Validate:
    def test_capture_restart_only_when_the_mode_differs(self, backup):
        same = {
            "capture_mode": "mirror",
            "capture_interface": "eth1",
            "management_interface": "eth0",
        }
        assert (
            backup.validate_import(_data({"capture_mode_config": same}))[
                "capture_restart"
            ]
            is False
        )
        other = {**same, "capture_interface": "eth2"}
        assert (
            backup.validate_import(_data({"capture_mode_config": other}))[
                "capture_restart"
            ]
            is True
        )
        bad = {"capture_mode": "mirror\nX=1", "capture_interface": "eth2"}
        assert (
            backup.validate_import(_data({"capture_mode_config": bad}))[
                "capture_restart"
            ]
            is False
        )


class TestA9Import:
    def test_capture_and_retention_are_left_to_the_api_layer(
        self, backup, config_paths
    ):
        before = Path(config_paths["capture_config"]).read_text()
        result = backup.import_config(
            _data(
                {
                    "capture_mode_config": {"capture_mode": "bridge"},
                    "storage_retention": {},
                }
            )
        )
        assert Path(config_paths["capture_config"]).read_text() == before
        assert "capture_mode_config" not in result["applied"]
        assert "storage_retention" not in result["applied"]

    def test_invalid_excluded_ips_are_refused_and_the_file_kept(
        self, backup, config_paths
    ):
        result = backup.import_config(
            _data({"excluded_ips": ["192.0.2.1", "10.0.0.0/8"]})
        )
        assert result["success"] is False
        assert "excluded_ips" not in result["applied"]
        assert json.loads(Path(config_paths["excluded_ips"]).read_text()) == [
            "192.168.1.1",
            "10.0.0.1",
        ]

    def test_home_acks_and_suppressions_are_restored(self, backup, config_paths):
        suppress = {
            "global": [
                {
                    "signature_id": 7,
                    "reason": "noisy",
                    "expires_at": "2030-01-01T00:00:00Z",
                }
            ],
            "per_device": {"192.0.2.5": [{"signature_id": 8}]},
            "false_positives": [
                {"signature_id": 9, "marked_at": "2026-11-01T00:00:00+00:00"}
            ],
        }
        result = backup.import_config(
            _data(
                {
                    "home_location": {"lat": 1.5, "lon": 2.5, "label": "Office"},
                    "alert_acknowledgements": {"a1": {"acknowledged_by": "admin"}},
                    "alert_suppressions": suppress,
                }
            )
        )
        assert result["success"] is True, result
        assert {"home_location", "alert_acknowledgements", "alert_suppressions"} <= set(
            result["applied"]
        )
        assert (
            json.loads(Path(config_paths["home_location"]).read_text())["label"]
            == "Office"
        )
        assert json.loads(Path(config_paths["suppressions"]).read_text()) == suppress
        assert json.loads(Path(config_paths["alert_acks"]).read_text()) == {
            "a1": {"acknowledged_by": "admin"}
        }

    @pytest.mark.parametrize(
        "bad",
        [
            {"global": [None]},
            {"false_positives": [{}]},
            {"per_device": {"192.0.2.5": "x"}},
            {"global": [{"signature_id": True}]},
            # naive: _is_entry_expired would treat it as never expiring
            {"global": [{"signature_id": 1, "expires_at": "2020-01-01T00:00:00"}]},
            {"global": [{"signature_id": 1, "expires_at": "soon"}]},
        ],
    )
    def test_malformed_suppressions_are_refused_and_the_file_kept(
        self, backup, config_paths, bad
    ):
        path = Path(config_paths["suppressions"])
        path.write_text('{"global": [], "per_device": {}, "false_positives": []}')
        result = backup.import_config(_data({"alert_suppressions": bad}))
        assert result["success"] is False
        # the owner reads this, so the section's name, not its key
        assert result["errors"] == [
            "Alert suppressions not restored: this backup's copy isn't valid"
        ]
        assert json.loads(path.read_text()) == {
            "global": [],
            "per_device": {},
            "false_positives": [],
        }

    def test_no_home_location_in_the_backup_is_skipped_with_a_reason(self, backup):
        result = backup.import_config(_data({"home_location": None}))
        assert result["skipped"] == [
            {"section": "home_location", "reason": "No location in this backup"}
        ]


class TestA9NotificationRestore:
    def _box(self, config_paths, channels, backup=None):
        Path(config_paths["notification_config"]).write_text(
            json.dumps({"channels": channels, "rules": {}})
        )
        if backup is not None:  # NET-224: the running hub holds what the box has
            backup._notification_hub._load_config()

    def _round_trip(self, backup, config_paths, edit=None):
        self._box(config_paths, SECRET_CHANNELS, backup)
        section = backup.export_config()["sections"]["notification_channels"]
        if edit:
            edit(section)
        result = backup.import_config(_data({"notification_channels": section}))
        stored = json.loads(Path(config_paths["notification_config"]).read_text())
        return result, stored["channels"]

    def test_the_boxs_own_secrets_are_kept_and_the_file_is_private(
        self, backup, config_paths
    ):
        result, channels = self._round_trip(backup, config_paths)
        assert result["success"] is True
        assert channels["mail"]["config"]["smtp_pass"] == "hunter2"
        assert channels["hook"]["config"]["url"] == "https://hooks.example.net/T0KEN"
        assert channels["hook"].get("enabled", True) is True
        assert Path(config_paths["notification_config"]).stat().st_mode & 0o777 == 0o600

    @pytest.mark.parametrize(
        "edit",
        [
            lambda s: s["mail"]["config"].update(smtp_host="mail.evil.example"),
            lambda s: s["mail"]["config"].update(use_tls=False),
            lambda s: s["mail"]["config"].update(smtp_user="someone-else"),
        ],
    )
    def test_a_changed_destination_gets_none_of_the_boxs_secrets(
        self, backup, config_paths, edit
    ):
        result, channels = self._round_trip(backup, config_paths, edit)
        assert "smtp_pass" not in channels["mail"]["config"]
        assert channels["mail"]["enabled"] is False
        # OLD CODE: "Mail" in w and "Settings › Notifications" in w (NET-224: page channels have no edit; add again, rules too)
        assert any(
            "Mail" in w and "Notification channels page" in w and "routing rules" in w
            for w in result["warnings"]
        )

    def test_an_older_backup_with_another_webhook_url_keeps_no_headers(
        self, backup, config_paths
    ):
        self._box(config_paths, SECRET_CHANNELS, backup)
        old_style = {
            # OLD CODE: "hook": {"type": "webhook", "config": {"url": "https://evil.example/x"}} (NET-224: with its id)
            "hook": {
                "id": "hook",
                "type": "webhook",
                "config": {"url": "https://evil.example/x"},
            }
        }
        backup.import_config(_data({"notification_channels": old_style}))
        stored = json.loads(Path(config_paths["notification_config"]).read_text())
        assert stored["channels"]["hook"]["config"] == {"url": "https://evil.example/x"}

    def test_a_fresh_box_turns_off_channels_missing_secrets_and_names_them(
        self, backup, config_paths
    ):
        self._box(config_paths, SECRET_CHANNELS, backup)
        section = backup.export_config()["sections"]["notification_channels"]
        self._box(config_paths, {}, backup)
        result = backup.import_config(_data({"notification_channels": section}))
        channels = json.loads(Path(config_paths["notification_config"]).read_text())[
            "channels"
        ]
        assert channels["hook"]["enabled"] is False
        assert channels["mail"]["enabled"] is False
        assert "secrets_left_out" not in channels["hook"]
        assert any("Hook" in w for w in result["warnings"])

    def test_a_recipients_only_email_channel_without_smtp_is_named(
        self, backup, config_paths, monkeypatch
    ):
        monkeypatch.delenv("SMTP_HOST", raising=False)
        quick = {
            "settings-email": {
                "id": "settings-email",  # NET-224: every stored channel has its id
                "type": "email",
                "name": "Email (Settings)",
                "config": {"recipients": ["owner@example.net"]},
                "secrets_left_out": [],
            }
        }
        result = backup.import_config(_data({"notification_channels": quick}))
        assert result["success"] is True
        assert any(
            "SMTP server" in w and "Email (Settings)" in w for w in result["warnings"]
        )
        Path(config_paths["env_file"]).write_text("SMTP_HOST=smtp.example.net\n")
        result = backup.import_config(_data({"notification_channels": quick}))
        assert not any("SMTP server" in w for w in result["warnings"])
