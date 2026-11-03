"""Manual cleanup logs its details as changelog metadata, not as the description."""

from unittest.mock import MagicMock

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.server import handle_cleanup_execute
from services.changelog import ChangelogService


class TestCleanupChangelog(AioHTTPTestCase):
    async def get_application(self):
        self.storage = MagicMock()
        self.storage.execute_cleanup.return_value = {
            "deleted_indices": ["arkime_sessions3-260101"],
            "deleted_pcap_files": 2,
            "freed_bytes_estimate": 1024,
            "cutoff_date": "2026-01-01",
        }
        self.changelog = MagicMock(spec=ChangelogService)
        app = web.Application()
        app["storage"] = self.storage
        app["changelog_service"] = self.changelog
        app.router.add_post("/api/storage/cleanup/execute", handle_cleanup_execute)
        return app

    async def test_details_go_in_metadata(self):
        resp = await self.client.post(
            "/api/storage/cleanup/execute", json={"older_than_days": 30}
        )
        self.assertEqual(resp.status, 200)
        self.changelog.log_event.assert_called_once()
        args, kwargs = self.changelog.log_event.call_args
        self.assertEqual(args[0], "storage_pruned")
        self.assertIsInstance(args[1], str)
        self.assertEqual(len(args), 2)  # nothing slips into the description slot
        self.assertEqual(kwargs["metadata"]["older_than_days"], 30)
        self.assertEqual(kwargs["metadata"]["trigger"], "manual")
