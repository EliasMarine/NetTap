"""
Tests for daemon/main.py — environment variable parsing, config loading,
and logging configuration.

All environment variables are managed via monkeypatch to ensure test
isolation and avoid leaking state between tests.
"""

import asyncio
import logging
import sys
import pathlib
import threading
from unittest.mock import AsyncMock, MagicMock

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
from main import storage_loop  # noqa: E402
from main import async_main, capture_health_loop, init_capture_manager  # noqa: E402
from services.bridge_capture_adapter import BridgeCaptureAdapter  # noqa: E402
from services.capture_config import CaptureConfig, save_capture_config  # noqa: E402
from services.capture_manager import CaptureHealth, CaptureMode  # noqa: E402
from services.capture_mode_stub import CaptureManagerStub  # noqa: E402
from services.dhcp_gateway import DhcpGatewayManager  # noqa: E402
from storage.manager import RetentionConfig  # noqa: E402


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
        # SMART_DEVICE falls back to auto-detect; hide host disks (CI runners have
        # /dev/sda) so the documented /dev/nvme0n1 default is what gets asserted.
        monkeypatch.setattr("smart.monitor.globmod.glob", lambda pattern: [])

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


# =========================================================================
# storage_loop
# =========================================================================


class TestStorageLoop:
    def test_run_cycle_runs_off_the_event_loop(self):
        """A cycle blocked on _cleanup_lock must not freeze the event loop."""

        async def scenario() -> list[threading.Thread]:
            loop = asyncio.get_running_loop()
            shutdown = asyncio.Event()
            ran_on: list[threading.Thread] = []

            def run_cycle():
                ran_on.append(threading.current_thread())
                loop.call_soon_threadsafe(shutdown.set)

            storage = MagicMock()
            storage.run_cycle.side_effect = run_cycle
            await asyncio.wait_for(storage_loop(storage, 60, shutdown), timeout=5)
            return ran_on

        loop_thread = threading.current_thread()
        ran_on = asyncio.run(scenario())
        assert len(ran_on) == 1
        assert ran_on[0] is not loop_thread


# =========================================================================
# capture_health_loop
# =========================================================================


HEALTHY = CaptureHealth(
    mode="dhcp_gateway",
    status="normal",
    capture_interface="enp1s0",
    link_up=True,
    promisc_enabled=False,
)


def _fake_manager(name: str, calls: list) -> MagicMock:
    mgr = MagicMock()
    mgr.mode = CaptureMode.DHCP_GATEWAY
    mgr.reconcile = AsyncMock(side_effect=lambda: calls.append(f"{name}.reconcile"))
    mgr.get_health = AsyncMock(return_value=HEALTHY)
    return mgr


class TestCaptureHealthLoop:
    def test_reconciles_then_checks_the_live_manager_each_tick(self):
        """The loop re-reads the manager each tick (setup can swap it)."""
        calls: list[str] = []
        first, second = _fake_manager("first", calls), _fake_manager("second", calls)
        current = {"mgr": first}

        async def scenario():
            shutdown = asyncio.Event()

            async def swap_after_health():
                calls.append("first.health")
                current["mgr"] = second
                return HEALTHY

            async def stop_after_health():
                calls.append("second.health")
                shutdown.set()
                return HEALTHY

            first.get_health.side_effect = swap_after_health
            second.get_health.side_effect = stop_after_health
            await asyncio.wait_for(
                capture_health_loop(lambda: current["mgr"], 0.01, shutdown), timeout=5
            )

        asyncio.run(scenario())
        assert calls == [
            "first.reconcile",
            "first.health",
            "second.reconcile",
            "second.health",
        ]

    def test_a_failing_tick_does_not_stop_the_loop(self):
        calls: list[str] = []
        mgr = _fake_manager("m", calls)

        async def scenario():
            shutdown = asyncio.Event()
            mgr.reconcile.side_effect = [RuntimeError("nsenter gone"), None]

            async def stop_after_health():
                shutdown.set()
                return HEALTHY

            mgr.get_health.side_effect = stop_after_health
            await asyncio.wait_for(
                capture_health_loop(lambda: mgr, 0.01, shutdown), timeout=5
            )

        asyncio.run(scenario())
        assert mgr.reconcile.await_count == 2
        mgr.get_health.assert_awaited_once()  # skipped on the failing tick


# =========================================================================
# init_capture_manager (CR-167 guard)
# =========================================================================


class TestInitCaptureManager:
    def _with_config(self, monkeypatch, tmp_path, config=None, text=None):
        path = tmp_path / "capture-mode.conf"
        monkeypatch.setenv("CAPTURE_CONFIG_PATH", str(path))
        if text is not None:
            path.write_text(text)
        else:
            save_capture_config(config)

    def test_unreadable_config_falls_back_to_stub(self, monkeypatch, tmp_path):
        """CR-167: a bad capture-mode.conf must not crash-loop the daemon."""
        self._with_config(monkeypatch, tmp_path, text="mode = dhcp_gateway %(\n")
        mgr, bridge_health = asyncio.run(init_capture_manager())
        assert isinstance(mgr, CaptureManagerStub)
        assert bridge_health is None

    def test_failing_setup_falls_back_to_stub(self, monkeypatch, tmp_path):
        self._with_config(
            monkeypatch,
            tmp_path,
            CaptureConfig(mode=CaptureMode.MIRROR, interface="enp2s0"),
        )
        mirror_cls = MagicMock()
        mirror_cls.return_value.setup = AsyncMock(side_effect=OSError("no nsenter"))
        monkeypatch.setattr("main.MirrorManager", mirror_cls)
        mgr, _ = asyncio.run(init_capture_manager())
        assert isinstance(mgr, CaptureManagerStub)

    def test_dhcp_mode_with_routing_runs_setup(self, monkeypatch, tmp_path):
        self._with_config(
            monkeypatch,
            tmp_path,
            CaptureConfig(
                mode=CaptureMode.DHCP_GATEWAY,
                interface="enp1s0",
                dhcp_upstream_address="192.168.1.50/24",
                dhcp_upstream_gateway="192.168.1.1",
                dhcp_enabled=True,
            ),
        )
        setup = AsyncMock(return_value={"success": True, "warnings": [], "errors": []})
        monkeypatch.setattr(DhcpGatewayManager, "setup", setup)
        mgr, bridge_health = asyncio.run(init_capture_manager())
        assert isinstance(mgr, DhcpGatewayManager)
        assert mgr.routing_active
        assert bridge_health is None
        setup.assert_awaited_once()

    def test_dhcp_mode_not_enabled_skips_setup(self, monkeypatch, tmp_path):
        self._with_config(
            monkeypatch,
            tmp_path,
            CaptureConfig(mode=CaptureMode.DHCP_GATEWAY, interface="enp1s0"),
        )
        setup = AsyncMock()
        monkeypatch.setattr(DhcpGatewayManager, "setup", setup)
        mgr, _ = asyncio.run(init_capture_manager())
        assert isinstance(mgr, DhcpGatewayManager)
        setup.assert_not_awaited()

    def test_bridge_mode_returns_adapter_and_bridge_health(self, monkeypatch, tmp_path):
        self._with_config(monkeypatch, tmp_path, CaptureConfig())
        mgr, bridge_health = asyncio.run(init_capture_manager())
        assert isinstance(mgr, BridgeCaptureAdapter)
        assert bridge_health is not None


# =========================================================================
# async_main startup order
# =========================================================================


class TestAsyncMainStartup:
    def _run(self, monkeypatch, capture_result):
        events: list = []
        runner = MagicMock()
        runner.app = {}
        runner.cleanup = AsyncMock()
        config_manager = MagicMock()
        config_manager.load.return_value = RetentionConfig()

        async def fake_storage_loop(storage, interval, shutdown):
            events.append("storage")
            await shutdown.wait()

        async def fake_smart_loop(smart, interval, shutdown):
            events.append("smart")
            await shutdown.wait()

        async def fake_init():
            await asyncio.sleep(0)  # let already-created tasks take their first step
            events.append("capture_init")
            return capture_result

        async def fake_capture_loop(get_manager, interval, shutdown):
            events.append(("capture_loop", get_manager()))
            shutdown.set()

        async def fake_bridge_loop(bridge_health, interval, shutdown):
            events.append("bridge")
            await shutdown.wait()

        monkeypatch.setattr(
            "main.load_config",
            lambda: {
                "log_level": "INFO",
                "opensearch_url": "http://localhost:9200",
                "smart_device": "/dev/nvme0n1",
                "storage_check_interval": 300,
                "smart_check_interval": 3600,
                "bridge_check_interval": 30,
                "api_port": 8880,
            },
        )
        monkeypatch.setattr("main.configure_logging", lambda level: None)
        monkeypatch.setattr("main.RetentionConfigManager", lambda **kw: config_manager)
        monkeypatch.setattr("main.StorageManager", MagicMock())
        monkeypatch.setattr("main.SmartMonitor", MagicMock())
        monkeypatch.setattr("main.start_api", AsyncMock(return_value=runner))
        monkeypatch.setattr("main.enforce_capture_state", AsyncMock())
        monkeypatch.setattr("main.storage_loop", fake_storage_loop)
        monkeypatch.setattr("main.smart_loop", fake_smart_loop)
        monkeypatch.setattr("main.init_capture_manager", fake_init)
        monkeypatch.setattr("main.capture_health_loop", fake_capture_loop)
        monkeypatch.setattr("main.bridge_loop", fake_bridge_loop)
        monkeypatch.delenv("OPENSEARCH_CREDS_CONFIG_FILE", raising=False)

        asyncio.run(asyncio.wait_for(async_main(), timeout=5))
        return events, runner

    def test_storage_and_smart_start_before_capture_setup(self, monkeypatch):
        """CR-167: a slow or broken capture setup can't hold up storage / SMART."""
        mgr = MagicMock()
        events, runner = self._run(monkeypatch, (mgr, None))
        assert events.index("storage") < events.index("capture_init")
        assert events.index("smart") < events.index("capture_init")
        assert runner.app["capture_manager"] is mgr

    def test_capture_loop_runs_in_every_mode_and_bridge_keeps_its_loop(
        self, monkeypatch
    ):
        mgr = MagicMock()
        events, _ = self._run(monkeypatch, (mgr, None))
        assert ("capture_loop", mgr) in events
        assert "bridge" not in events

        events, _ = self._run(monkeypatch, (mgr, MagicMock()))
        assert ("capture_loop", mgr) in events
        assert "bridge" in events
