"""
Excluded IPs apply to device-centric views only.

Alerts, logs and threat detections must keep showing excluded IPs (the
Settings copy promises it); device and traffic views must still hide them.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.alerts import register_alert_routes
from api.devices import register_device_routes
from api.logs import register_log_routes
from api.traffic import register_traffic_routes
from services.alert_intelligence import THREAT_CATEGORIES
from services.threat_detection import (
    analyze_dns_anomalies,
    detect_beaconing,
    detect_lateral_movement,
)
from services.threat_intel import ThreatIntelService
from storage.manager import RetentionConfig, StorageManager

EXCLUDED_IP = "10.9.9.9"
EMPTY_RESULT = {"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}}
CATEGORY = next(iter(THREAT_CATEGORIES))


def _mock_storage():
    with patch.object(StorageManager, "_create_client") as mock_create:
        client = MagicMock()
        client.search.return_value = EMPTY_RESULT
        mock_create.return_value = client
        storage = StorageManager(RetentionConfig(), "http://localhost:9200")
    return storage, client


def _search_bodies(client: MagicMock) -> str:
    return json.dumps([c.kwargs.get("body") for c in client.search.call_args_list])


class _ScopeCase(AioHTTPTestCase):
    """Registers routes with one excluded IP and records every search body."""

    register = None

    def setUp(self):
        self.storage, self.mock_client = _mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        app["excluded_ips"] = [EXCLUDED_IP]
        type(self).register(app, self.storage)
        return app

    async def _bodies_for(self, path: str) -> str:
        self.mock_client.search.reset_mock()
        await self.client.request("GET", path)
        self.assertTrue(self.mock_client.search.called, f"{path} never searched")
        return _search_bodies(self.mock_client)


class TestAlertQueriesKeepExcludedIps(_ScopeCase):
    register = staticmethod(register_alert_routes)

    @unittest_run_loop
    async def test_no_alert_query_filters_excluded_ips(self):
        for path in (
            "/api/alerts",
            "/api/alerts/count",
            "/api/alerts/timeline",
            "/api/alerts/top-signatures",
            "/api/alerts/top-ips",
            "/api/alerts/categories",
            f"/api/alerts/categories/{CATEGORY}",
            f"/api/alerts/categories/{CATEGORY}/timeline",
            "/api/alerts/smart",
            "/api/alerts/smart/summary",
        ):
            self.assertNotIn(EXCLUDED_IP, await self._bodies_for(path), path)


class TestLogQueriesKeepExcludedIps(_ScopeCase):
    register = staticmethod(register_log_routes)

    @unittest_run_loop
    async def test_no_log_query_filters_excluded_ips(self):
        for path in (
            "/api/logs/search",
            "/api/logs/stats",
            "/api/logs/timeline",
            "/api/logs/top-talkers",
            "/api/logs/protocol-breakdown",
            "/api/logs/top-destinations",
            "/api/logs/top-dns",
        ):
            self.assertNotIn(EXCLUDED_IP, await self._bodies_for(path), path)


class TestTrafficQueriesHideExcludedIps(_ScopeCase):
    register = staticmethod(register_traffic_routes)

    @unittest_run_loop
    async def test_traffic_views_still_filter_excluded_ips(self):
        for path in ("/api/traffic/top-talkers", "/api/traffic/top-destinations"):
            self.assertIn(EXCLUDED_IP, await self._bodies_for(path), path)


class TestDeviceQueriesHideExcludedIps(_ScopeCase):
    register = staticmethod(register_device_routes)

    @unittest_run_loop
    async def test_device_list_still_filters_excluded_ips(self):
        self.assertIn(EXCLUDED_IP, await self._bodies_for("/api/devices"))


class TestThreatQueriesKeepExcludedIps(unittest.TestCase):
    def test_threat_detection_ignores_excluded_ips(self):
        for detect in (
            detect_beaconing,
            detect_lateral_movement,
            analyze_dns_anomalies,
        ):
            client = MagicMock()
            client.search.return_value = EMPTY_RESULT
            detect(client, "now-1h", "now", excluded_ips=[EXCLUDED_IP])
            self.assertTrue(client.search.called, detect.__name__)
            self.assertNotIn(EXCLUDED_IP, _search_bodies(client), detect.__name__)

    def test_threat_intel_populate_ignores_excluded_ips(self):
        client = MagicMock()
        client.search.return_value = EMPTY_RESULT
        ThreatIntelService().populate_from_suricata(
            client, "now-1h", "now", excluded_ips=[EXCLUDED_IP]
        )
        self.assertTrue(client.search.called)
        self.assertNotIn(EXCLUDED_IP, _search_bodies(client))


if __name__ == "__main__":
    unittest.main()
