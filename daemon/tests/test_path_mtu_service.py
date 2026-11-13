"""
Tests for services/path_mtu_service.py and POST /api/tools/mtu (NET-267).

Ping output is real iputils 20221126 output from the G11 daemon container (2026-11-13), except the
two router reports (FRAG_V4, TOO_BIG_V6): the G11's paths never sent one, so those follow the exact
iputils 20221126 format strings (ping.c pr_icmph, ping6_common.c print_icmp).
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.tools import register_tools_routes
from services import path_mtu_service
from services.host_resolve import HostLookupError
from services.network_diag_service import NetworkDiagValidationError
from services.path_mtu_service import (
    BUSY,
    PathMtuBusyError,
    PathMtuService,
    PathMtuValidationError,
    parse_probe,
)

# ping -4 -M do -c 1 -W 1 -s 1472 9.9.9.9
REPLY_V4 = """\
PING 9.9.9.9 (9.9.9.9) 1472(1500) bytes of data.
1480 bytes from 9.9.9.9: icmp_seq=1 ttl=52 time=7.67 ms

--- 9.9.9.9 ping statistics ---
1 packets transmitted, 1 received, 0% packet loss, time 0ms
rtt min/avg/max/mdev = 7.672/7.672/7.672/0.000 ms
"""
# ... -s 1473 9.9.9.9: stdout, then stderr
LOCAL_V4 = (
    "PING 9.9.9.9 (9.9.9.9) 1473(1501) bytes of data.\n\n--- 9.9.9.9 ping statistics ---\n"
    "1 packets transmitted, 0 received, +1 errors, 100% packet loss, time 0ms\n\n",
    "ping: local error: message too long, mtu=1500\n",
)
# ... -s 56 192.0.2.1
SILENT_V4 = """\
PING 192.0.2.1 (192.0.2.1) 56(84) bytes of data.

--- 192.0.2.1 ping statistics ---
1 packets transmitted, 0 received, 100% packet loss, time 0ms

"""
# ping -6 -M do -c 1 -W 1 -s 1452 / -s 65500 <the G11's own ULA>, and -s 56 2606:4700:4700::1111
REPLY_V6 = """\
PING fd99:9c49:c85e:47f5:8e32:23ff:fe82:855(fd99:9c49:c85e:47f5:8e32:23ff:fe82:855) 1452 data bytes
1460 bytes from fd99:9c49:c85e:47f5:8e32:23ff:fe82:855: icmp_seq=1 ttl=64 time=0.040 ms

--- fd99:9c49:c85e:47f5:8e32:23ff:fe82:855 ping statistics ---
1 packets transmitted, 1 received, 0% packet loss, time 0ms
rtt min/avg/max/mdev = 0.040/0.040/0.040/0.000 ms
"""
LOCAL_V6_ERR = "ping: local error: message too long, mtu: 65536\n"
UNREACHABLE_ERR = "ping: connect: Network is unreachable\n"
# format, not captured: "From %s icmp_seq=%u " + "Frag needed and DF set (mtu = %u)\n"
FRAG_V4 = """\
PING 10.8.0.1 (10.8.0.1) 1472(1500) bytes of data.
From 192.168.1.1 icmp_seq=1 Frag needed and DF set (mtu = 1420)

--- 10.8.0.1 ping statistics ---
1 packets transmitted, 0 received, +1 errors, 100% packet loss, time 0ms

"""
# format, not captured: "From %s icmp_seq=%u " + "Packet too big: mtu=%u" + "\n"
TOO_BIG_V6 = "PING fd00::1(fd00::1) 1452 data bytes\nFrom fd00::fe icmp_seq=1 Packet too big: mtu=1400\n"

PATH = {"interface": "eno1", "source_ip": "192.168.1.199", "wifi": False, "speed_mbps": 1000, "mtu": 1500}


def reply(*_):
    return REPLY_V4, "", 0


def silent(*_):
    return SILENT_V4, "", 1


def frag(mtu):
    return lambda *_: (FRAG_V4.replace("1420", str(mtu)), "", 1)


def local(mtu):
    return lambda *_: (LOCAL_V4[0], LOCAL_V4[1].replace("1500", str(mtu)), 1)


class FakeProc:
    def __init__(self, out="", err="", code=0, release=None):
        self.out, self.err, self.code, self.release = out, err, code, release
        self.returncode = None
        self.kill = MagicMock(side_effect=lambda: setattr(self, "returncode", -9))
        self.wait = AsyncMock()

    async def communicate(self):
        if self.release is not None:
            await self.release.wait()
        self.returncode = self.code
        return self.out.encode(), self.err.encode()


class Net:
    """A fake path: `rule(size, nth)` answers the nth ping of that IP size."""

    def __init__(self, rule, overhead=28):
        self.rule, self.overhead = rule, overhead
        self.pings = []

    def __call__(self, *argv, **kwargs):
        assert argv[0] == "ping", argv
        size = int(argv[-2]) + self.overhead
        nth = sum(1 for s in self.pings if s == size)
        self.pings.append(size)
        self.argv = argv
        out, err, code = self.rule(size, nth)
        return FakeProc(out, err, code)


def path_rule(limit, above):
    """Sizes up to `limit` reply; above it, `above(size, nth)` answers."""

    def rule(size, nth):
        if size <= limit:
            return reply(size)
        return above(size, nth)

    return rule


class Harness(unittest.TestCase):
    def setUp(self):
        self.svc = PathMtuService()
        self.route = AsyncMock(return_value=PATH)
        p = patch.object(path_mtu_service, "route_to", self.route)
        p.start()
        self.addCleanup(p.stop)

    def check(self, rule, target="10.8.0.1", overhead=28):
        net = Net(rule, overhead)
        with patch("asyncio.create_subprocess_exec", side_effect=net):
            result = asyncio.run(self.svc.check(target))
        return result, net


class TestParseProbe(unittest.TestCase):
    def test_every_real_and_format_output(self):
        cases = [
            ((REPLY_V4, ""), {"result": "reply", "mtu": None}),
            ((REPLY_V6, ""), {"result": "reply", "mtu": None}),
            (LOCAL_V4, {"result": "local_error", "mtu": 1500}),
            (("", LOCAL_V6_ERR), {"result": "local_error", "mtu": 65536}),
            ((SILENT_V4, ""), {"result": "no_reply", "mtu": None}),
            ((FRAG_V4, ""), {"result": "icmp_too_big", "mtu": 1420}),
            ((TOO_BIG_V6, ""), {"result": "icmp_too_big", "mtu": 1400}),
            (("", UNREACHABLE_ERR), {"result": "local_error", "mtu": None}),
        ]
        for (out, err), expected in cases:
            with self.subTest(out=out[:30], err=err):
                self.assertEqual(parse_probe(out, err), expected)


class TestSearch(Harness):
    def test_full_size_packets_are_limited_by_the_interface(self):
        result, net = self.check(path_rule(1500, silent))
        self.assertEqual(net.argv, ("ping", "-4", "-M", "do", "-c", "1", "-W", "1", "-s", "1472", "10.8.0.1"))
        self.assertEqual(net.pings, [84, 576, 1500, 1500])  # small, floor, ceiling, re-probe
        self.assertEqual(result["status"], "interface")
        self.assertEqual((result["largest_confirmed"], result["payload"]), (1500, 1472))
        self.assertTrue(result["upper_known"])
        self.assertEqual(
            {k: result[k] for k in ("resolved_ip", "family", "interface", "interface_mtu")},
            {"resolved_ip": "10.8.0.1", "family": 4, "interface": "eno1", "interface_mtu": 1500},
        )

    def test_a_router_report_is_probed_exactly_and_bounds_the_path(self):
        # the router reports 1420 once; with DF set the kernel then refuses bigger sizes itself
        reported = []

        def above(size, nth):
            if reported:
                return local(1420)(size)
            reported.append(size)
            return frag(1420)(size)

        result, net = self.check(path_rule(1420, above))
        self.assertEqual(net.pings[:4], [84, 576, 1500, 1420])
        self.assertEqual(result["status"], "icmp_bound")
        self.assertEqual((result["largest_confirmed"], result["icmp_reported_mtu"]), (1420, 1420))
        self.assertTrue(result["upper_known"])
        self.assertEqual(result["probes"][2], {"size": 1500, "result": "icmp_too_big", "mtu": 1420})

    def test_a_report_equal_to_a_size_that_replied_ends_the_search(self):
        # 1384 has replied when a router reports exactly 1384 for 1442: nothing is left to probe
        def rule(size, nth):
            if size <= 1384:
                return reply(size)
            return frag(1384)(size) if size == 1442 else silent(size)

        result, net = self.check(rule)
        self.assertEqual(net.pings[-2:], [1442, 1384])  # the report, then the re-probe
        self.assertNotIn(1413, net.pings)  # the next bisection step was not needed
        self.assertEqual(result["status"], "icmp_bound")
        self.assertEqual((result["largest_confirmed"], result["icmp_reported_mtu"]), (1384, 1384))
        self.assertTrue(result["upper_known"])

    def test_silence_above_never_makes_the_limit_known(self):
        result, net = self.check(path_rule(1400, silent))
        self.assertEqual(result["status"], "unanswered_above")
        self.assertEqual((result["largest_confirmed"], result["first_unanswered"]), (1400, 1401))
        self.assertFalse(result["upper_known"])
        self.assertLessEqual(len(result["probes"]), path_mtu_service.MAX_PROBES)
        # every silent size was pinged twice before it counted
        for size in {p["size"] for p in result["probes"] if p["result"] == "no_reply"}:
            self.assertEqual(net.pings.count(size), 2)

    def test_a_lost_ping_is_tried_again(self):
        # the first ping of each size is lost; the second answers
        result, _ = self.check(lambda size, nth: silent(size) if nth == 0 else reply(size))
        self.assertEqual(result["status"], "interface")

    def test_a_report_the_probes_contradict_is_not_trusted(self):
        # the router says 1420, but 1420 itself gets no reply
        def rule(size, nth):
            if size <= 1400:
                return reply(size)
            return frag(1420)(size) if size > 1420 else silent(size)

        result, _ = self.check(rule)
        self.assertEqual(result["status"], "unanswered_above")
        self.assertEqual((result["largest_confirmed"], result["icmp_reported_mtu"]), (1400, 1420))
        self.assertFalse(result["upper_known"])

    def test_a_report_below_a_size_that_replied_is_contradicted(self):
        # 1384 has replied when a router claims an MTU of 1300 for 1442: the report can't be right
        def rule(size, nth):
            if size <= 1400:
                return reply(size)
            return frag(1300)(size) if size == 1442 else silent(size)

        result, _ = self.check(rule)
        self.assertIn({"size": 1442, "result": "icmp_too_big", "mtu": 1300}, result["probes"])
        self.assertEqual(result["status"], "unanswered_above")
        self.assertEqual((result["largest_confirmed"], result["icmp_reported_mtu"]), (1400, 1300))
        self.assertFalse(result["upper_known"])

    def test_a_cached_limit_is_nettaps_own_not_a_router_report(self):
        result, net = self.check(path_rule(1400, local(1400)))
        self.assertEqual(net.pings, [84, 576, 1500, 1400, 1400])
        self.assertEqual(result["status"], "local_limit")
        self.assertEqual((result["largest_confirmed"], result["local_mtu"]), (1400, 1400))
        self.assertIsNone(result["icmp_reported_mtu"])
        self.assertFalse(result["upper_known"])

    def test_no_reply_to_a_small_ping(self):
        result, net = self.check(lambda size, nth: silent(size))
        self.assertEqual(net.pings, [84, 84])
        self.assertEqual(result["status"], "no_ping_reply")
        self.assertIsNone(result["largest_confirmed"])

    def test_small_pings_answer_but_the_floor_does_not(self):
        result, _ = self.check(path_rule(300, silent))
        self.assertEqual(result["status"], "floor_unanswered")
        self.assertEqual((result["largest_confirmed"], result["first_unanswered"]), (84, 576))

    def test_inconsistent_replies_confirm_nothing(self):
        # 1500 answers once, then never again
        result, _ = self.check(lambda size, nth: reply(size) if size < 1500 or nth == 0 else silent(size))
        self.assertEqual(result["status"], "unreliable")
        self.assertFalse(result["upper_known"])

    def test_pings_own_error_is_the_error(self):
        result, _ = self.check(lambda size, nth: ("", UNREACHABLE_ERR, 2))
        self.assertEqual(result["status"], "ping_error")
        self.assertEqual(result["error"], "connect: Network is unreachable")

    def test_ipv6_uses_its_own_sizes(self):
        self.route.return_value = {**PATH, "mtu": 1500}

        def rule(size, nth):
            return (REPLY_V6, "", 0) if size <= 1400 else (TOO_BIG_V6, "", 1) if nth == 0 else ("", LOCAL_V6_ERR.replace("65536", "1400"), 1)

        result, net = self.check(rule, target="fd00::1", overhead=48)
        self.assertEqual(net.argv[:2], ("ping", "-6"))
        self.assertEqual(net.pings[:4], [104, 1280, 1500, 1400])
        self.assertEqual(result["status"], "icmp_bound")
        self.assertEqual((result["largest_confirmed"], result["payload"], result["family"]), (1400, 1352, 6))

    def test_the_probe_cap_returns_what_is_confirmed(self):
        with patch.object(path_mtu_service, "MAX_PROBES", 3):
            result, _ = self.check(path_rule(1400, silent))
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["largest_confirmed"], 576)
        self.assertFalse(result["upper_known"])

    def test_the_deadline_stops_and_reaps_ping(self):
        hung = FakeProc(release=asyncio.Event())
        procs = [FakeProc(REPLY_V4), hung]
        with (
            patch.object(path_mtu_service, "DEADLINE", 0.05),
            patch("asyncio.create_subprocess_exec", side_effect=lambda *a, **k: procs.pop(0)),
        ):
            result = asyncio.run(self.svc.check("10.8.0.1"))
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["largest_confirmed"], 84)
        hung.kill.assert_called_once()
        hung.wait.assert_awaited_once()

    def test_a_target_that_does_not_resolve(self):
        self.route.side_effect = HostLookupError("NetTap has no route to fd00::1.")
        result, _ = self.check(reply, target="fd00::1")
        self.assertEqual(result["error"], "NetTap has no route to fd00::1.")
        self.assertIsNone(result["status"])


class TestAdmission(Harness):
    def test_bad_input_is_refused(self):
        with self.assertRaises(PathMtuValidationError):
            asyncio.run(self.svc.check(None))
        with self.assertRaises(NetworkDiagValidationError):
            asyncio.run(self.svc.check("-f"))

    def test_two_checks_at_a_time_then_busy(self):
        async def go():
            release = asyncio.Event()
            with patch(
                "asyncio.create_subprocess_exec",
                side_effect=lambda *a, **k: FakeProc(REPLY_V4, release=release),
            ):
                running = [asyncio.create_task(self.svc.check(t)) for t in ("10.8.0.1", "10.8.0.2")]
                await asyncio.sleep(0.01)
                with self.assertRaisesRegex(PathMtuBusyError, BUSY):
                    await self.svc.check("10.8.0.3")
                release.set()
                return await asyncio.gather(*running)

        self.assertEqual([r["status"] for r in asyncio.run(go())], ["interface", "interface"])


class TestMtuRoute(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        register_tools_routes(app, MagicMock(), MagicMock(), MagicMock(), MagicMock())
        self.svc = MagicMock()
        self.svc.check = AsyncMock(return_value={"status": "interface", "error": None})
        app["path_mtu"] = self.svc
        return app

    async def test_passes_the_target(self):
        resp = await self.client.post("/api/tools/mtu", json={"target": "10.8.0.1"})
        self.assertEqual(resp.status, 200)
        self.svc.check.assert_awaited_once_with("10.8.0.1")

    async def test_bad_input_is_400_busy_is_503(self):
        for exc, status in (
            (PathMtuValidationError("Enter a host name or IP address."), 400),
            (NetworkDiagValidationError("Target is required"), 400),
            (PathMtuBusyError(BUSY), 503),
        ):
            self.svc.check.side_effect = exc
            resp = await self.client.post("/api/tools/mtu", json={})
            self.assertEqual(resp.status, status)
            self.assertEqual((await resp.json())["error"], str(exc))

    async def test_a_body_that_is_not_an_object_is_400(self):
        for raw in ("[1]", "not json"):
            resp = await self.client.post("/api/tools/mtu", data=raw)
            self.assertEqual(resp.status, 400)
        self.svc.check.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
