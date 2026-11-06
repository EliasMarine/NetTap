"""api/drilldown_runner.py (NET-160): at most two drill-downs, off the event loop, in budget."""

import asyncio
import threading
import time
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api import drilldown_runner
from api.drilldown_runner import install, ip_param, lan_check, run_drilldown
from services.excluded_ips import build_lan_filter
from storage.snapshot_search import Budget, QueryFailed, TooSlow


class TestRunner(AioHTTPTestCase):
    async def get_application(self):
        self.started = threading.Semaphore(0)
        self.release = threading.Event()
        self.runs = 0
        self.fail: Exception | None = None

        def work(budget: Budget) -> dict:
            self.runs += 1
            self.started.release()
            self.release.wait(5)
            if self.fail:
                raise self.fail
            return {"ok": True, "budget_left": budget.remaining() > 0}

        async def drill(request: web.Request) -> web.Response:
            return await run_drilldown(request, work, "test")

        async def health(request: web.Request) -> web.Response:
            return web.json_response({"status": "ok"})

        app = web.Application()
        install(app, client=None)
        app.router.add_get("/drill", drill)
        app.router.add_get("/api/health", health)
        return app

    async def _wait_started(self, n: int) -> None:
        loop = asyncio.get_running_loop()
        for _ in range(n):
            self.assertTrue(
                await loop.run_in_executor(None, self.started.acquire, True, 5)
            )

    async def test_a_slow_drill_down_does_not_hold_up_health(self):
        first = asyncio.ensure_future(self.client.get("/drill"))
        await self._wait_started(1)
        began = time.monotonic()
        resp = await self.client.get("/api/health")
        self.assertEqual(resp.status, 200)
        self.assertLess(time.monotonic() - began, 1.0)
        self.release.set()
        self.assertEqual((await first).status, 200)

    async def test_a_third_request_waits_and_never_runs_a_third_scan(self):
        running = [asyncio.ensure_future(self.client.get("/drill")) for _ in range(2)]
        await self._wait_started(2)
        with patch.object(drilldown_runner, "BUDGET_SECONDS", 0.1):
            third = await self.client.get("/drill")
        self.assertEqual(third.status, 503)
        self.assertIn("try again", (await third.json())["error"])
        self.assertEqual(self.runs, 2)
        self.release.set()
        self.assertEqual([(await r).status for r in running], [200, 200])

    async def test_a_cancelled_request_keeps_its_permit_until_its_worker_ends(self):
        slots = self.app["drill_slots"]
        first = asyncio.ensure_future(self.client.get("/drill"))
        await self._wait_started(1)
        first.cancel()  # the client gives up; the thread is still working
        await asyncio.sleep(0.05)
        self.assertEqual(slots._value, 1)
        self.release.set()
        for _ in range(100):
            if slots._value == 2:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(slots._value, 2)

    async def test_failures_are_a_502_or_a_503_with_a_reason(self):
        self.release.set()
        for error, status, words in (
            (QueryFailed("address peers timed out"), 502, "address peers timed out"),
            (TooSlow("address totals took too long"), 503, "too long"),
        ):
            self.fail = error
            resp = await self.client.get("/drill")
            self.assertEqual(resp.status, status)
            self.assertIn(words, (await resp.json())["error"])

    async def test_an_unexpected_error_is_a_json_500_logged_with_its_traceback(self):
        self.release.set()
        self.fail = KeyError("buckets")  # e.g. a malformed bucket
        with self.assertLogs("nettap.api.drilldown", "ERROR") as logs:
            resp = await self.client.get("/drill")
        self.assertEqual(resp.status, 500)
        self.assertIn("went wrong", (await resp.json())["error"])
        self.assertIn("KeyError", logs.output[0])

    async def test_the_reply_is_the_work_as_json(self):
        self.release.set()
        resp = await self.client.get("/drill")
        self.assertEqual(await resp.json(), {"ok": True, "budget_left": True})


def test_ip_param_is_one_canonical_address():
    assert ip_param("2001:DB8:0:0::1") == "2001:db8::1"
    assert ip_param(" 192.168.1.20 ") == "192.168.1.20"
    for bad in ("", "10.0.0.0/8", "example.com", "fe80::1%eth0", "1.2.3", None):
        assert ip_param(bad) is None, bad


def test_lan_check_follows_the_daemon_rule():
    app = {"lan_filter": build_lan_filter([(192, 168, 1)])}
    is_lan = lan_check(app)
    assert is_lan("192.168.1.20") and not is_lan("192.168.2.20")
    assert not is_lan("fd00::1")  # IPv6 is never LAN, as every device filter
    rfc1918 = lan_check({"lan_filter": build_lan_filter([])})
    assert rfc1918("10.1.2.3") and not rfc1918("93.184.216.34")
