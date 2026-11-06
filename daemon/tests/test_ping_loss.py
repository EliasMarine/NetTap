"""S2 and S12: ping loss is read as a decimal, and no reply means no round-trip time."""

from unittest.mock import AsyncMock, MagicMock

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.tools import register_tools_routes
from services.network_diag_service import NetworkDiagService


def test_fractional_loss_is_not_read_as_thousands():
    out = "3 packets transmitted, 2 received, 33.3333% packet loss, time 2003ms"
    assert NetworkDiagService()._parse_ping_output(out)["stats"]["packet_loss_percent"] == 33.3333


def test_loss_after_an_error_count():
    out = "4 packets transmitted, 0 received, +4 errors, 100% packet loss, time 3065ms"
    assert NetworkDiagService()._parse_ping_output(out)["stats"]["packet_loss_percent"] == 100


class TestPingApiWithoutReplies(AioHTTPTestCase):
    async def get_application(self):
        diag = MagicMock()
        diag.ping = AsyncMock(
            return_value={
                "target": "192.0.2.1",
                "output": "4 packets transmitted, 0 received, 100% packet loss",
                "replies": [],
                "stats": {"packets_transmitted": 4, "packets_received": 0, "packet_loss_percent": 100.0},
                "error": None,
            }
        )
        app = web.Application()
        register_tools_routes(app, MagicMock(), MagicMock(), diag, MagicMock())
        return app

    async def test_no_replies_means_no_rtt_not_zero(self):
        body = await (await self.client.post("/api/tools/ping", json={"target": "192.0.2.1"})).json()
        assert body["packet_loss_pct"] == 100
        assert [body[k] for k in ("rtt_min", "rtt_avg", "rtt_max", "rtt_mdev")] == [None] * 4
