"""Live bandwidth is the capture NIC's line rate, not a sum of conn records."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.live import ThroughputSampler, register_live_routes


def _manager(*byte_counts: int) -> MagicMock:
    cm = MagicMock()
    cm.get_stats = AsyncMock(
        side_effect=[SimpleNamespace(rx_bytes=b, tx_bytes=0) for b in byte_counts]
    )
    return cm


def _run(coro):
    return asyncio.run(coro)


class TestThroughputSampler:
    def test_first_call_measures_over_a_short_gap(self):
        sampler = ThroughputSampler(clock=iter([100.0, 101.0]).__next__)
        with patch("api.live.asyncio.sleep", AsyncMock()):
            rate = _run(sampler.rate(_manager(1_000_000, 1_301_103)))
        assert rate == 301_103

    def test_later_calls_rate_against_the_previous_read(self):
        sampler = ThroughputSampler(clock=iter([100.0, 101.0, 106.0]).__next__)
        with patch("api.live.asyncio.sleep", AsyncMock()):
            cm = _manager(0, 1000, 6000)
            _run(sampler.rate(cm))
            assert _run(sampler.rate(cm)) == 1000  # 5000 bytes over 5 s

    def test_counter_reset_is_unavailable_not_negative(self):
        sampler = ThroughputSampler(clock=iter([100.0, 101.0]).__next__)
        with patch("api.live.asyncio.sleep", AsyncMock()):
            assert _run(sampler.rate(_manager(5000, 10))) is None

    def test_no_manager_or_failing_stats_is_unavailable(self):
        assert _run(ThroughputSampler().rate(None)) is None
        cm = MagicMock()
        cm.get_stats = AsyncMock(side_effect=NotImplementedError)
        assert _run(ThroughputSampler().rate(cm)) is None


class TestDashboardBandwidth(AioHTTPTestCase):
    async def get_application(self):
        tracker = MagicMock()
        tracker.fetch_dashboard_data.return_value = {
            "connections": [],
            "stats": {"bandwidth_bytes_per_second": 147_811, "active_devices": 38},
        }
        app = web.Application()
        register_live_routes(app, tracker)
        self.sampler = app["live_throughput"]
        return app

    async def test_line_rate_replaces_the_conn_record_estimate(self):
        with patch.object(self.sampler, "rate", AsyncMock(return_value=301_103.4)):
            data = await (await self.client.get("/api/live/dashboard")).json()
        assert data["stats"]["bandwidth_bytes_per_second"] == 301_103.4
        assert data["stats"]["active_devices"] == 38

    async def test_a_filtered_request_takes_no_line_rate_sample(self):
        """O7: the page's filtered side-card request would cut the sampler's interval short."""
        rate = AsyncMock(return_value=301_103.4)
        with patch.object(self.sampler, "rate", rate):
            data = await (await self.client.get("/api/live/dashboard?proto=udp")).json()
        rate.assert_not_called()
        assert data["stats"]["bandwidth_bytes_per_second"] == 147_811

    async def test_estimate_kept_when_the_line_rate_is_unavailable(self):
        with patch.object(self.sampler, "rate", AsyncMock(return_value=None)):
            data = await (await self.client.get("/api/live/dashboard")).json()
        assert data["stats"]["bandwidth_bytes_per_second"] == 147_811
