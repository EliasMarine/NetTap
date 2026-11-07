"""NET-158: GET /api/alerts/smart's total counts every group, not the `limit` it lists.

The device page showed "10 grouped" (its limit) for a device with more alert groups.
"""

from unittest.mock import MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.alerts import register_alert_routes
from storage.manager import RetentionConfig, StorageManager


def _storage() -> StorageManager:
    with patch.object(StorageManager, "_create_client") as create:
        create.return_value = MagicMock()
        return StorageManager(RetentionConfig(), "http://localhost:9200")


class TestSmartAlertTotal(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        storage = _storage()
        app["storage"] = storage
        register_alert_routes(app, storage)
        return app

    @unittest_run_loop
    async def test_total_counts_every_group_past_the_limit(self):
        groups = [{"signature_id": i, "severity": 2, "count": 1} for i in range(15)]
        fetch = MagicMock(return_value=groups)
        with patch("services.alert_intelligence.get_smart_alerts", fetch):
            resp = await self.client.request(
                "GET", "/api/alerts/smart?device_ip=192.168.1.5&limit=10"
            )
        data = await resp.json()

        self.assertEqual(data["total"], 15)  # was 10
        self.assertEqual([a["signature_id"] for a in data["alerts"]], list(range(10)))
        # every group is fetched; the handler lists the first `limit`
        self.assertIsNone(fetch.call_args.args[5])
