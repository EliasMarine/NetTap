"""
Tests for daemon/api/iot.py

Every handler must run its IoTMonitor call on the IoT API's dedicated
single-worker executor: off the event loop, and never two at once.
"""

import asyncio
import threading
import unittest
from unittest.mock import MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.iot import register_iot_routes
from storage.manager import RetentionConfig, StorageManager

MAC = "aa:bb:cc:dd:ee:ff"
# One request per handler (11). The baseline handler calls the monitor twice.
ENDPOINTS = [
    ("GET", "/api/iot/devices"),
    ("GET", f"/api/iot/devices/{MAC}/baseline"),
    ("GET", f"/api/iot/devices/{MAC}/communication-map"),
    ("GET", f"/api/iot/devices/{MAC}/activity-timeline"),
    ("GET", "/api/iot/anomalies"),
    ("GET", "/api/iot/fleet-summary"),
    ("GET", "/api/iot/privacy-report"),
    ("GET", "/api/iot/protocol-audit"),
    ("GET", "/api/iot/network-isolation"),
    ("GET", "/api/iot/manufacturer-profiles"),
    ("POST", f"/api/iot/devices/{MAC}/classify"),
]


class _RecordingMonitor:
    """Stands in for IoTMonitor; records which thread ran each call."""

    RETURNS = {
        "get_iot_devices": [],
        "get_anomalies": [],
        "get_device_baseline": None,
        "classify_as_iot": True,
    }

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.hooks: dict = {}

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.calls.append((name, threading.current_thread().name))
            hook = self.hooks.get(name)
            if hook:
                hook()
            return self.RETURNS.get(name, {})

        return method


class TestIoTHandlersUseSerialExecutor(AioHTTPTestCase):
    def setUp(self):
        with patch.object(StorageManager, "_create_client") as mock_create:
            mock_create.return_value = MagicMock()
            self.storage = StorageManager(RetentionConfig(), "http://localhost:9200")
        self.monitor = _RecordingMonitor()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_iot_routes(app, self.storage)
        app["iot_monitor"] = self.monitor
        return app

    @unittest_run_loop
    async def test_every_handler_runs_on_the_iot_executor(self):
        for method, path in ENDPOINTS:
            resp = await self.client.request(method, path, json={})
            self.assertEqual(resp.status, 200, path)

        names = [name for name, _ in self.monitor.calls]
        self.assertEqual(len(names), len(ENDPOINTS) + 1)  # + build_baseline
        for name, thread in self.monitor.calls:
            self.assertTrue(thread.startswith("nettap-iot"), f"{name} ran on {thread}")

    @unittest_run_loop
    async def test_discovery_and_report_never_overlap(self):
        """A report queued behind a running fleet discovery waits for it."""
        discovery_running = threading.Event()
        release_discovery = threading.Event()
        report_started = threading.Event()
        overlapped = []

        def discovery():
            discovery_running.set()
            release_discovery.wait(timeout=5)
            overlapped.append(report_started.is_set())

        self.monitor.hooks = {
            "get_fleet_summary": discovery,
            "get_privacy_report": report_started.set,
        }

        fleet = asyncio.create_task(self.client.get("/api/iot/fleet-summary"))
        self.assertTrue(await asyncio.to_thread(discovery_running.wait, 5))
        report = asyncio.create_task(self.client.get("/api/iot/privacy-report"))

        # With one worker the report cannot start while discovery holds it.
        self.assertFalse(await asyncio.to_thread(report_started.wait, 0.3))
        release_discovery.set()

        self.assertEqual((await fleet).status, 200)
        self.assertEqual((await report).status, 200)
        self.assertTrue(report_started.is_set())
        self.assertEqual(overlapped, [False])


if __name__ == "__main__":
    unittest.main()
