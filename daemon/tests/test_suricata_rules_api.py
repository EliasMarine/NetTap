"""GET /api/suricata/rules/live reports what Suricata really runs, or says it could not read it (#58)."""

from unittest.mock import AsyncMock, MagicMock

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.suricata_rules import register_suricata_rules_routes
from services.suricata_rules import SuricataRuleManager


class TestLiveStatusEndpoint(AioHTTPTestCase):
    async def get_application(self):
        self.manager = MagicMock(spec=SuricataRuleManager)
        app = web.Application()
        register_suricata_rules_routes(app, self.manager)
        return app

    async def test_returns_the_live_status(self):
        status = {
            "available": True,
            "enabled_rules": 64307,
            "disabled_rules": 15954,
            "last_updated": "2026-11-02T00:00:36+00:00",
            "sources": ["https://sslbl.abuse.ch/blacklist/sslblacklist.rules"],
            "schedule": "0 0 * * *",
            "error": None,
        }
        self.manager.get_live_status = AsyncMock(return_value=status)
        resp = await self.client.get("/api/suricata/rules/live")
        self.assertEqual(resp.status, 200)
        self.assertEqual(await resp.json(), status)

    async def test_unreadable_is_502_not_zero_rules(self):
        self.manager.get_live_status = AsyncMock(
            return_value={
                "available": False,
                "error": "Could not reach the Suricata container.",
            }
        )
        resp = await self.client.get("/api/suricata/rules/live")
        self.assertEqual(resp.status, 502)
        self.assertEqual(
            (await resp.json())["error"], "Could not reach the Suricata container."
        )
