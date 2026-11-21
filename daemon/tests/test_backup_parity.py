"""NET-344: the preflight and the restore paths it stands in for agree (plan §2.4).

backup_checks repeats two rules it can't call without side effects: setup's _build_capture_config
(the capture restore) and RetentionConfigManager.save (the retention restore). Each table runs the
same sections through both, so a change to one that the other misses fails here.
"""

import pytest

import services.backup_checks as checks
from api.setup import _build_capture_config
from services.backup_checks import capture_section
from storage.retention_config import RetentionConfigManager

GOOD, BAD = "eth1", "eth1;reboot"

CAPTURE = [
    {"capture_mode": "bridge", "wan_interface": "eth0", "lan_interface": GOOD},
    {"capture_mode": "bridge", "wan_interface": "eth0"},
    {"capture_mode": "bridge", "wan_interface": "eth0", "lan_interface": BAD},
    {"capture_mode": "bridge", "wan_interface": "-x", "lan_interface": GOOD},
    {"capture_mode": "bridge", "wan_interface": "a" * 16, "lan_interface": GOOD},
    {"capture_mode": "bridge", "wan_interface": 5, "lan_interface": GOOD},
    {"capture_mode": "mirror", "capture_interface": GOOD},
    {"capture_mode": "mirror", "capture_interface": GOOD, "management_interface": ""},
    {"capture_mode": "mirror", "capture_interface": GOOD, "management_interface": 0},
    {
        "capture_mode": "mirror",
        "capture_interface": GOOD,
        "management_interface": "wlan0",
    },
    {"capture_mode": "mirror", "capture_interface": GOOD, "management_interface": BAD},
    {"capture_mode": "mirror", "capture_interface": "."},
    {"capture_mode": "mirror"},
    {"capture_mode": "dhcp_gateway", "capture_interface": GOOD},
    {"capture_mode": "dhcp_gateway", "capture_interface": GOOD, "dhcp_subnet": None},
    {
        "capture_mode": "dhcp_gateway",
        "capture_interface": GOOD,
        "dhcp_subnet": "192.168.50.0/24",
    },
    {
        "capture_mode": "dhcp_gateway",
        "capture_interface": GOOD,
        "dhcp_subnet": "10.77.0.5/24",
    },
    {
        "capture_mode": "dhcp_gateway",
        "capture_interface": GOOD,
        "dhcp_subnet": "8.8.8.0/24",
    },
    {
        "capture_mode": "dhcp_gateway",
        "capture_interface": GOOD,
        "dhcp_subnet": "10.0.0.0/8",
    },
    {"capture_mode": "dhcp_gateway", "capture_interface": GOOD, "dhcp_subnet": ""},
    {"capture_mode": "dhcp_gateway", "capture_interface": GOOD, "dhcp_subnet": 5},
    {"capture_mode": "dhcp_gateway", "capture_interface": BAD},
]


def _setup_builds(raw: dict) -> bool:
    """api/backup.py _restore_capture: setup's builder on the reduced section, ValueError and
    TypeError refused (anything else would be a 500 there, so it fails the test here)."""
    try:
        _build_capture_config(capture_section(raw))
    except (ValueError, TypeError):
        return False
    return True


@pytest.mark.parametrize("raw", CAPTURE, ids=lambda raw: str(raw))
def test_the_capture_check_agrees_with_setups_builder(raw):
    assert capture_section(raw), (
        "every row is a valid mode; an invalid one never builds"
    )
    assert (checks._capture_errors(raw) == []) == _setup_builds(raw)


RETENTION = [
    {"hot_days": 30},
    {"hot_days": 0},
    {"hot_days": 366},
    {"hot_days": "30"},
    {"hot_days": 30.0},
    {"hot_days": None},
    {"hot_days": True},
    {"warm_days": 730, "cold_days": 365},
    {"disk_threshold_percent": 85, "emergency_threshold_percent": 95},
    {"disk_threshold_percent": 90, "emergency_threshold_percent": 90},
    {"disk_threshold_percent": 95},  # over the default emergency threshold once merged
    {"emergency_threshold_percent": 60},  # under the default disk threshold once merged
    {"emergency_threshold_percent": 99},
    {"retention": {"hot_days": 7}, "thresholds": {"disk_threshold_percent": 70}},
    {"retention": {"hot_days": None}},
    {"retention": [], "hot_days": 7},
    {"thresholds": {"emergency_threshold_percent": "x"}},
    {"unrelated": 1},
]


def _save_takes(values: dict, tmp_path) -> bool:
    """POST /api/storage/config's save on a manager that has read nothing (the defaults), with
    the exceptions save_retention_config turns into a 400."""
    manager = RetentionConfigManager(
        config_path=str(tmp_path / "retention.json"), env_file=str(tmp_path / ".env")
    )
    try:
        manager.save(values)
    except (ValueError, TypeError, AttributeError):
        return False
    return True


@pytest.mark.parametrize("values", RETENTION, ids=lambda values: str(values))
def test_the_retention_check_agrees_with_the_save(values, tmp_path):
    assert (checks._retention_errors(values) == []) == _save_takes(values, tmp_path)
