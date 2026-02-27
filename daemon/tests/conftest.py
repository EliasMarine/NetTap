"""
Shared pytest fixtures for the NetTap daemon test suite.

Provides mocked OpenSearch clients, sample index data, retention configs,
sample smartctl JSON outputs, and filesystem helpers.
"""

from unittest.mock import MagicMock

import pytest

from storage.manager import RetentionConfig


# ---------------------------------------------------------------------------
# OpenSearch client mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_opensearch_client():
    """Return a MagicMock pretending to be an opensearch-py OpenSearch client.

    The mock has the following pre-configured behaviour:
    - ``client.cat.indices(...)`` returns an empty list by default.
      Override via ``client.cat.indices.return_value = [...]``.
    - ``client.indices.delete(...)`` returns ``{"acknowledged": True}``.
    """
    client = MagicMock()
    client.cat.indices.return_value = []
    client.indices.delete.return_value = {"acknowledged": True}
    return client


# ---------------------------------------------------------------------------
# Sample index data
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_indices():
    """Return a list of fake OpenSearch ``_cat/indices`` entries.

    Covers all three tiers (hot / warm / cold) plus a system index that
    should be filtered out, and an index with no recognisable date.
    """
    return [
        # System index (should be filtered by list_indices)
        {
            "index": ".opensearch-dashboards",
            "store.size": "2mb",
            "pri.store.size": "2mb",
            "creation.date.string": "2026-01-01T00:00:00.000Z",
        },
        # Hot tier — Zeek (dot-separated date)
        {
            "index": "zeek-conn-2026.01.15",
            "store.size": "50mb",
            "pri.store.size": "50mb",
            "creation.date.string": "2026-01-15T00:00:00.000Z",
        },
        {
            "index": "zeek-dns-2026.01.20",
            "store.size": "30mb",
            "pri.store.size": "30mb",
            "creation.date.string": "2026-01-20T00:00:00.000Z",
        },
        # Warm tier — Suricata (dash-separated date)
        {
            "index": "suricata-alert-2026-01-20",
            "store.size": "10mb",
            "pri.store.size": "10mb",
            "creation.date.string": "2026-01-20T00:00:00.000Z",
        },
        {
            "index": "suricata-alert-2026-02-10",
            "store.size": "12mb",
            "pri.store.size": "12mb",
            "creation.date.string": "2026-02-10T00:00:00.000Z",
        },
        # Cold tier — Arkime (compact YYMMDD date)
        {
            "index": "arkime_sessions3-260125",
            "store.size": "200mb",
            "pri.store.size": "200mb",
            "creation.date.string": "2026-01-25T00:00:00.000Z",
        },
        # Cold tier — sessions prefix
        {
            "index": "sessions3-260130",
            "store.size": "180mb",
            "pri.store.size": "180mb",
            "creation.date.string": "2026-01-30T00:00:00.000Z",
        },
        # Unknown tier with no recognisable date
        {
            "index": "custom-metrics",
            "store.size": "5mb",
            "pri.store.size": "5mb",
            "creation.date.string": None,
        },
    ]


# ---------------------------------------------------------------------------
# Retention configuration
# ---------------------------------------------------------------------------

@pytest.fixture
def retention_config():
    """Return a RetentionConfig with shortened test values."""
    return RetentionConfig(
        hot_days=30,
        warm_days=60,
        cold_days=15,
        disk_threshold=0.80,
        emergency_threshold=0.90,
        check_path="/",
    )


# ---------------------------------------------------------------------------
# Sample smartctl JSON outputs
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_smartctl_nvme():
    """Return sample smartctl JSON output for an NVMe drive."""
    return {
        "json_format_version": [1, 0],
        "smartctl": {"version": [7, 3]},
        "device": {"name": "/dev/nvme0n1", "type": "nvme"},
        "model_name": "Samsung 980 PRO 1TB",
        "serial_number": "S6B1NJ0TB12345",
        "firmware_version": "5B2QGXA7",
        "smart_status": {"passed": True},
        "temperature": {"current": 38},
        "nvme_smart_health_information_log": {
            "critical_warning": 0,
            "temperature": 38,
            "available_spare": 100,
            "available_spare_threshold": 10,
            "percentage_used": 3,
            "data_units_read": 52459106,
            "data_units_written": 43285012,
            "host_reads": 781254321,
            "host_writes": 612345678,
            "controller_busy_time": 1234,
            "power_cycles": 150,
            "power_on_hours": 8760,
            "unsafe_shutdowns": 5,
            "media_errors": 0,
            "num_err_log_entries": 0,
            "warning_comp_temperature_time": 0,
            "critical_comp_temperature_time": 0,
        },
    }


@pytest.fixture
def mock_smartctl_sata():
    """Return sample smartctl JSON output for a SATA SSD."""
    return {
        "json_format_version": [1, 0],
        "smartctl": {"version": [7, 3]},
        "device": {"name": "/dev/sda", "type": "sat"},
        "model_name": "Samsung SSD 870 EVO 1TB",
        "serial_number": "S5Y1NJ0TB98765",
        "firmware_version": "SVT02B6Q",
        "smart_status": {"passed": True},
        "temperature": {"current": 34},
        "logical_block_size": 512,
        "ata_smart_attributes": {
            "revision": 1,
            "table": [
                {
                    "id": 5,
                    "name": "Reallocated_Sector_Ct",
                    "value": 100,
                    "worst": 100,
                    "thresh": 10,
                    "raw": {"value": 0, "string": "0"},
                },
                {
                    "id": 9,
                    "name": "Power_On_Hours",
                    "value": 99,
                    "worst": 99,
                    "thresh": 0,
                    "raw": {"value": 4380, "string": "4380"},
                },
                {
                    "id": 177,
                    "name": "Wear_Leveling_Count",
                    "value": 98,
                    "worst": 98,
                    "thresh": 0,
                    "raw": {"value": 12, "string": "12"},
                },
                {
                    "id": 194,
                    "name": "Temperature_Celsius",
                    "value": 66,
                    "worst": 53,
                    "thresh": 0,
                    "raw": {"value": 34, "string": "34"},
                },
                {
                    "id": 241,
                    "name": "Total_LBAs_Written",
                    "value": 99,
                    "worst": 99,
                    "thresh": 0,
                    "raw": {"value": 87654321, "string": "87654321"},
                },
                {
                    "id": 242,
                    "name": "Total_LBAs_Read",
                    "value": 99,
                    "worst": 99,
                    "thresh": 0,
                    "raw": {"value": 123456789, "string": "123456789"},
                },
            ],
        },
    }


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir(tmp_path):
    """Alias for pytest's built-in ``tmp_path`` fixture."""
    return tmp_path
