"""
Tests for daemon/main.py — environment variable parsing, config loading,
and logging configuration.

All environment variables are managed via monkeypatch to ensure test
isolation and avoid leaking state between tests.
"""

import logging
import sys
import pathlib

# We import the module-level functions directly. Note: main.py uses
# relative imports like ``from storage.manager import ...`` which are
# resolved at import time.  To avoid needing the actual opensearch-py
# dependency chain, we add the daemon/ directory to sys.path in the
# tests (conftest or pytest configuration) or run pytest from daemon/.
# The conftest.py already sets up the path correctly.

# Ensure daemon/ is on sys.path so main.py's imports resolve
_daemon_dir = str(pathlib.Path(__file__).resolve().parent.parent)
if _daemon_dir not in sys.path:
    sys.path.insert(0, _daemon_dir)

from main import _env_int, _env_float, _env_str, load_config, configure_logging  # noqa: E402


# =========================================================================
# _env_int
# =========================================================================


class TestEnvInt:
    def test_env_int_valid(self, monkeypatch):
        """Verify _env_int parses a valid integer from the environment."""
        monkeypatch.setenv("TEST_INT_VAR", "42")
        assert _env_int("TEST_INT_VAR", 0) == 42

    def test_env_int_invalid_falls_back(self, monkeypatch):
        """Verify _env_int returns the default on invalid (non-integer) value."""
        monkeypatch.setenv("TEST_INT_VAR", "not_a_number")
        assert _env_int("TEST_INT_VAR", 99) == 99

    def test_env_int_missing_falls_back(self, monkeypatch):
        """Verify _env_int returns the default when the env var is not set."""
        monkeypatch.delenv("TEST_INT_MISSING", raising=False)
        assert _env_int("TEST_INT_MISSING", 55) == 55


# =========================================================================
# _env_float
# =========================================================================


class TestEnvFloat:
    def test_env_float_valid(self, monkeypatch):
        """Verify _env_float parses a valid float from the environment."""
        monkeypatch.setenv("TEST_FLOAT_VAR", "3.14")
        result = _env_float("TEST_FLOAT_VAR", 0.0)
        assert abs(result - 3.14) < 0.001

    def test_env_float_invalid_falls_back(self, monkeypatch):
        """Verify _env_float returns the default on invalid value."""
        monkeypatch.setenv("TEST_FLOAT_VAR", "abc")
        assert _env_float("TEST_FLOAT_VAR", 1.5) == 1.5

    def test_env_float_missing_falls_back(self, monkeypatch):
        """Verify _env_float returns the default when env var is missing."""
        monkeypatch.delenv("TEST_FLOAT_MISSING", raising=False)
        assert _env_float("TEST_FLOAT_MISSING", 2.5) == 2.5


# =========================================================================
# _env_str
# =========================================================================


class TestEnvStr:
    def test_env_str_default(self, monkeypatch):
        """Verify _env_str returns the default when the env var is not set."""
        monkeypatch.delenv("TEST_STR_MISSING", raising=False)
        assert _env_str("TEST_STR_MISSING", "fallback") == "fallback"

    def test_env_str_set(self, monkeypatch):
        """Verify _env_str returns the env var value when set."""
        monkeypatch.setenv("TEST_STR_VAR", "custom_value")
        assert _env_str("TEST_STR_VAR", "fallback") == "custom_value"


# =========================================================================
# load_config
# =========================================================================


class TestLoadConfig:
    def test_load_config_defaults(self, monkeypatch):
        """Verify all defaults are correct when no env vars are set."""
        # Clear all relevant env vars
        for var in (
            "RETENTION_HOT",
            "RETENTION_WARM",
            "RETENTION_COLD",
            "DISK_THRESHOLD_PERCENT",
            "EMERGENCY_THRESHOLD_PERCENT",
            "OPENSEARCH_URL",
            "SMART_DEVICE",
            "STORAGE_CHECK_INTERVAL",
            "SMART_CHECK_INTERVAL",
            "API_PORT",
            "LOG_LEVEL",
        ):
            monkeypatch.delenv(var, raising=False)

        cfg = load_config()

        assert cfg["retention_hot"] == 90
        assert cfg["retention_warm"] == 180
        assert cfg["retention_cold"] == 30
        assert abs(cfg["disk_threshold"] - 0.80) < 0.001
        assert abs(cfg["emergency_threshold"] - 0.90) < 0.001
        assert cfg["opensearch_url"] == "http://localhost:9200"
        assert cfg["smart_device"] == "/dev/nvme0n1"
        assert cfg["storage_check_interval"] == 300
        assert cfg["smart_check_interval"] == 3600
        assert cfg["api_port"] == 8880
        assert cfg["log_level"] == "INFO"

    def test_load_config_custom_env(self, monkeypatch):
        """Set env vars and verify they are picked up by load_config."""
        monkeypatch.setenv("RETENTION_HOT", "30")
        monkeypatch.setenv("RETENTION_WARM", "60")
        monkeypatch.setenv("RETENTION_COLD", "15")
        monkeypatch.setenv("DISK_THRESHOLD_PERCENT", "75")
        monkeypatch.setenv("EMERGENCY_THRESHOLD_PERCENT", "85")
        monkeypatch.setenv("OPENSEARCH_URL", "https://os.local:9200")
        monkeypatch.setenv("SMART_DEVICE", "/dev/sda")
        monkeypatch.setenv("STORAGE_CHECK_INTERVAL", "120")
        monkeypatch.setenv("SMART_CHECK_INTERVAL", "1800")
        monkeypatch.setenv("API_PORT", "9999")
        monkeypatch.setenv("LOG_LEVEL", "debug")

        cfg = load_config()

        assert cfg["retention_hot"] == 30
        assert cfg["retention_warm"] == 60
        assert cfg["retention_cold"] == 15
        assert abs(cfg["disk_threshold"] - 0.75) < 0.001
        assert abs(cfg["emergency_threshold"] - 0.85) < 0.001
        assert cfg["opensearch_url"] == "https://os.local:9200"
        assert cfg["smart_device"] == "/dev/sda"
        assert cfg["storage_check_interval"] == 120
        assert cfg["smart_check_interval"] == 1800
        assert cfg["api_port"] == 9999
        assert cfg["log_level"] == "DEBUG"


# =========================================================================
# configure_logging
# =========================================================================


class TestConfigureLogging:
    def test_configure_logging_sets_level(self):
        """Verify logging level is set correctly by configure_logging."""
        configure_logging("WARNING")
        root_logger = logging.getLogger()
        assert root_logger.level == logging.WARNING

        # Reset to INFO so we don't affect other tests
        configure_logging("INFO")
        assert root_logger.level == logging.INFO

    def test_configure_logging_debug(self):
        """Verify DEBUG level is configured properly."""
        configure_logging("DEBUG")
        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG

        # Clean up
        configure_logging("INFO")

    def test_configure_logging_invalid_falls_back(self):
        """Verify an invalid level name falls back to INFO."""
        configure_logging("NONEXISTENT_LEVEL")
        root_logger = logging.getLogger()
        # getattr(logging, "NONEXISTENT_LEVEL", logging.INFO) returns INFO
        assert root_logger.level == logging.INFO
