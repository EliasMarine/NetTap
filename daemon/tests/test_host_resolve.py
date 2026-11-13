"""Tests for services/host_resolve.py (NET-266, NET-267): getent and ip output is real G11 output."""

import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import host_resolve
from services.host_resolve import (
    HostLookupError,
    HostNameError,
    check_name,
    resolve,
    route_to,
    run,
)

# ssh nettap 'sudo -n docker exec nettap-storage-daemon getent ahosts one.one.one.one' (2026-11-13)
GETENT_ONE = """\
1.0.0.1         STREAM one.one.one.one
1.0.0.1         DGRAM
1.0.0.1         RAW
1.1.1.1         STREAM
1.1.1.1         DGRAM
1.1.1.1         RAW
2606:4700:4700::1001 STREAM
2606:4700:4700::1001 DGRAM
2606:4700:4700::1001 RAW
2606:4700:4700::1111 STREAM
2606:4700:4700::1111 DGRAM
2606:4700:4700::1111 RAW
"""
# ... ip -j route get 9.9.9.9 / 192.168.1.199 (the G11's own address goes out over lo)
ROUTE_9999 = '[{"dst":"9.9.9.9","gateway":"192.168.1.1","dev":"eno1","prefsrc":"192.168.1.199","flags":[],"uid":0,"cache":[]}]\n'
ROUTE_UNREACHABLE = "RTNETLINK answers: Network is unreachable\n"
# ... ip -j route get <the G11's own ULA>, with its dev (lo) swapped for eno1
ROUTE_V6 = '[{"type":"local","dst":"fd99:9c49:c85e:47f5:8e32:23ff:fe82:855","from":"::","dev":"eno1","table":"local","protocol":"kernel","prefsrc":"fd99:9c49:c85e:47f5:8e32:23ff:fe82:855","metric":0,"flags":[],"pref":"medium"}]\n'
# format, not captured (iproute2 6.1 print_rta_metrics / print_rta_cacheinfo): a route with its
# own mtu, and a cached router report, which also carries "expires"
ROUTE_MTU = ROUTE_9999.replace('"uid":0', '"uid":0,"metrics":[{"mtu":1420}]')
ROUTE_CACHED = ROUTE_9999.replace(
    '"uid":0', '"uid":0,"expires":590,"metrics":[{"mtu":1400}]'
)


class FakeProc:
    """A child: `communicate` waits for `release` (if any), then answers `out` / `err` / `code`."""

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


def exec_returning(*procs):
    calls = []
    queue = list(procs)

    def fake_exec(*argv, **kwargs):
        calls.append(argv)
        return queue.pop(0)

    return calls, patch("asyncio.create_subprocess_exec", side_effect=fake_exec)


class TestResolve(unittest.TestCase):
    def test_an_ip_literal_runs_nothing(self):
        calls, patcher = exec_returning()
        with patcher:
            self.assertEqual(asyncio.run(resolve("192.168.1.10")), ["192.168.1.10"])
            self.assertEqual(asyncio.run(resolve("FD00::0001")), ["fd00::1"])
        self.assertEqual(calls, [])

    def test_a_name_is_every_address_once_in_getent_order(self):
        calls, patcher = exec_returning(FakeProc(GETENT_ONE))
        with patcher:
            addrs = asyncio.run(resolve("one.one.one.one"))
        self.assertEqual(
            addrs,
            ["1.0.0.1", "1.1.1.1", "2606:4700:4700::1001", "2606:4700:4700::1111"],
        )
        self.assertEqual(calls, [("getent", "ahosts", "--", "one.one.one.one")])

    def test_an_unknown_name_is_a_plain_sentence(self):
        # getent exits 2 and prints nothing for a name that does not exist
        _, patcher = exec_returning(FakeProc("", code=2))
        with (
            patcher,
            self.assertRaisesRegex(HostLookupError, "^nope.lan could not be found.$"),
        ):
            asyncio.run(resolve("nope.lan"))

    def test_garbage_lines_are_not_addresses(self):
        _, patcher = exec_returning(FakeProc("not-an-ip STREAM x\n\n"))
        with patcher, self.assertRaises(HostLookupError):
            asyncio.run(resolve("x.lan"))

    def test_a_stalled_resolver_is_killed_and_reaped(self):
        child = FakeProc(release=asyncio.Event())  # never answers
        _, patcher = exec_returning(child)
        with (
            patch.object(host_resolve, "RESOLVE_TIMEOUT", 0.05),
            patcher,
            self.assertRaisesRegex(HostLookupError, "took too long"),
        ):
            asyncio.run(resolve("slow.lan"))
        child.kill.assert_called_once()
        child.wait.assert_awaited_once()


class TestCheckName(unittest.TestCase):
    def test_digits_and_dots_must_be_an_ip_address(self):
        # getent would read these the inet_aton way: 192.168.1.8, 0.0.4.210, 1.2.0.3
        for name in ("192.168.001.010", "1234", "1.2.3", "..."):
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    HostNameError, "is not a valid IP address."
                ):
                    check_name(name)
        for name in ("192.168.1.10", "nas.lan", "1password.com", "host-1.lan"):
            self.assertEqual(check_name(name), name)

    def test_resolve_refuses_them_without_running_getent(self):
        calls, patcher = exec_returning()
        with patcher, self.assertRaises(HostNameError):
            asyncio.run(resolve("192.168.001.010"))
        self.assertEqual(calls, [])


class TestRun(unittest.TestCase):
    def test_a_cancelled_run_kills_and_reaps_its_child(self):
        child = FakeProc(release=asyncio.Event())

        async def go():
            task = asyncio.create_task(run("iperf3", "-c", "10.0.0.2"))
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        _, patcher = exec_returning(child)
        with patcher:
            asyncio.run(go())
        child.kill.assert_called_once()
        child.wait.assert_awaited_once()

    def test_a_finished_child_is_not_killed(self):
        child = FakeProc("out", "err", code=1)
        _, patcher = exec_returning(child)
        with patcher:
            self.assertEqual(asyncio.run(run("ping")), (1, "out", "err"))
        child.kill.assert_not_called()


class TestRouteTo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ipv6 = os.path.join(self.tmp.name, "ipv6conf")
        for name, value in (("SYS_NET", self.tmp.name), ("PROC_IPV6_CONF", self.ipv6)):
            patcher = patch.object(host_resolve, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _iface(self, name, **files):
        path = os.path.join(self.tmp.name, name)
        os.makedirs(path)
        for key, value in files.items():
            if value is None:
                os.makedirs(os.path.join(path, key))
            else:
                with open(os.path.join(path, key), "w") as f:
                    f.write(value + "\n")

    def test_the_g11_route_with_sysfs(self):
        self._iface("eno1", speed="1000", mtu="1500")
        calls, patcher = exec_returning(FakeProc(ROUTE_9999))
        with patcher:
            path = asyncio.run(route_to("9.9.9.9"))
        self.assertEqual(calls, [("ip", "-j", "route", "get", "9.9.9.9")])
        self.assertEqual(
            path,
            {
                "interface": "eno1",
                "source_ip": "192.168.1.199",
                "wifi": False,
                "speed_mbps": 1000,
                "mtu": 1500,
            },
        )

    def test_wifi_and_an_unknown_speed(self):
        self._iface("wlp2s0", speed="-1", mtu="1500", wireless=None)
        out = ROUTE_9999.replace('"eno1"', '"wlp2s0"')
        _, patcher = exec_returning(FakeProc(out))
        with patcher:
            path = asyncio.run(route_to("9.9.9.9"))
        self.assertTrue(path["wifi"])
        self.assertIsNone(path["speed_mbps"])

    def test_no_route_is_a_plain_sentence(self):
        _, patcher = exec_returning(FakeProc("", ROUTE_UNREACHABLE, code=2))
        with (
            patcher,
            self.assertRaisesRegex(
                HostLookupError, "^NetTap has no route to fd00::1.$"
            ),
        ):
            asyncio.run(route_to("fd00::1"))

    def test_a_dev_that_is_not_an_interface_name_is_refused(self):
        for dev in ("../../etc", "..", "a" * 16):
            out = ROUTE_9999.replace('"eno1"', f'"{dev}"')
            _, patcher = exec_returning(FakeProc(out))
            with self.subTest(dev=dev), patcher, self.assertRaises(HostLookupError):
                asyncio.run(route_to("9.9.9.9"))

    def test_ipv6_uses_the_links_own_ipv6_mtu(self):
        # a router advertisement can lower IPv6's MTU below the link's, e.g. 1492 behind PPPoE
        self._iface("eno1", speed="1000", mtu="1500")
        os.makedirs(os.path.join(self.ipv6, "eno1"))
        with open(os.path.join(self.ipv6, "eno1", "mtu"), "w") as f:
            f.write("1492\n")
        for ip, out, mtu in (
            ("fd99:9c49:c85e:47f5:8e32:23ff:fe82:855", ROUTE_V6, 1492),
            ("9.9.9.9", ROUTE_9999, 1500),  # IPv4 ignores it
        ):
            _, patcher = exec_returning(FakeProc(out))
            with self.subTest(ip=ip), patcher:
                self.assertEqual(asyncio.run(route_to(ip))["mtu"], mtu)

    def test_a_routes_own_mtu_caps_it_but_a_cached_report_does_not(self):
        self._iface("eno1", speed="1000", mtu="1500")
        for out, mtu in ((ROUTE_MTU, 1420), (ROUTE_CACHED, 1500)):
            _, patcher = exec_returning(FakeProc(out))
            with self.subTest(out=out), patcher:
                self.assertEqual(asyncio.run(route_to("9.9.9.9"))["mtu"], mtu)

    def test_unreadable_sysfs_is_unknown_not_zero(self):
        _, patcher = exec_returning(FakeProc(ROUTE_9999))
        with patcher:
            path = asyncio.run(route_to("9.9.9.9"))
        self.assertEqual((path["speed_mbps"], path["mtu"]), (None, None))


if __name__ == "__main__":
    unittest.main()
