"""
Tests for services/throughput_service.py and POST /api/tools/throughput (NET-266).

The iperf3 output is real `iperf3 -c 127.0.0.1 -p 5299 -t 1 -J [-R]` output from iperf 3.22
(macOS, hostname redacted; the JSON shape is the same on Linux): tests/fixtures/iperf3_*.json.
"""

import asyncio
import os
import socket
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.tools import register_tools_routes
from services import throughput_service
from services.capture_manager import CaptureMode
from services.network_diag_service import NetworkDiagValidationError
from services.throughput_service import (
    BUSY,
    LINK_LOCAL,
    NOT_LOCAL,
    TOO_LONG,
    ThroughputBusyError,
    ThroughputService,
    ThroughputValidationError,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
PATH = {
    "interface": "eno1",
    "source_ip": "192.168.1.199",
    "wifi": False,
    "speed_mbps": 1000,
    "mtu": 1500,
}


def fixture(name):
    with open(os.path.join(FIXTURES, f"iperf3_{name}.json")) as f:
        return f.read()


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


class Harness(unittest.TestCase):
    """route_to is mocked (tests/test_host_resolve.py covers it); every child is a FakeProc."""

    def setUp(self):
        self.svc = ThroughputService()
        self.calls = []
        self.procs = []
        patches = [
            patch.object(throughput_service, "route_to", AsyncMock(return_value=PATH)),
            patch("asyncio.create_subprocess_exec", side_effect=self._exec),
            patch.object(throughput_service.psutil, "net_if_addrs", return_value={}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _exec(self, *argv, **kwargs):
        self.calls.append(argv)
        return self.procs.pop(0)

    def run_one(self, host="192.168.1.20", direction="upload", **kw):
        return asyncio.run(self.svc.run_test(host=host, direction=direction, **kw))


class TestValidation(Harness):
    def test_bad_input_is_refused_before_anything_runs(self):
        cases = [
            ({"host": None}, "Enter the peer"),
            ({"port": 0}, "Port must be a whole number from 1 to 65535."),
            ({"port": 65536}, "Port"),
            ({"port": "5201"}, "Port"),
            ({"port": True}, "Port"),
            ({"duration": 0}, "Duration must be a whole number from 1 to 30."),
            ({"duration": 31}, "Duration"),
            ({"direction": "both"}, "Direction must be upload or download."),
            ({"direction": None}, "Direction"),
        ]
        for kw, message in cases:
            args = {"host": "192.168.1.20", "direction": "upload", **kw}
            with self.subTest(kw=kw), self.assertRaisesRegex(ThroughputValidationError, message):
                asyncio.run(self.svc.run_test(**args))
        with self.assertRaises(NetworkDiagValidationError):
            self.run_one(host="-f")
        self.assertEqual(self.calls, [])

    def test_only_local_ranges_are_tested(self):
        refused = {
            "9.9.9.9": NOT_LOCAL,
            "172.32.0.1": NOT_LOCAL,
            "100.128.0.1": NOT_LOCAL,
            "127.0.0.1": NOT_LOCAL,
            "224.0.0.251": NOT_LOCAL,
            "0.0.0.0": NOT_LOCAL,
            "2606:4700:4700::1111": NOT_LOCAL,
            "::1": NOT_LOCAL,
            "ff02::1": NOT_LOCAL,
            "169.254.10.1": LINK_LOCAL,
            "fe80::1": LINK_LOCAL,
        }
        for ip, message in refused.items():
            with self.subTest(ip=ip), self.assertRaises(ThroughputValidationError) as ctx:
                self.run_one(host=ip)
            self.assertEqual(str(ctx.exception), message)
        for ip in ("10.1.2.3", "172.16.0.9", "192.168.1.20", "100.64.0.7", "fd12:3456::1"):
            self.procs.append(FakeProc(fixture("upload")))
            with self.subTest(ip=ip):
                self.assertIsNone(self.run_one(host=ip)["error"])
        self.assertEqual([c[0] for c in self.calls], ["iperf3"] * 5)

    def test_a_name_uses_its_first_local_address(self):
        getent = "fe80::5         STREAM nas.lan\n192.168.1.20    STREAM \n"
        self.procs += [FakeProc(getent), FakeProc(fixture("upload"))]
        result = self.run_one(host="nas.lan")
        self.assertEqual(result["resolved_ip"], "192.168.1.20")
        self.assertEqual(self.calls[1][:3], ("iperf3", "-c", "192.168.1.20"))

    def test_a_name_with_no_local_address_is_refused(self):
        self.procs.append(FakeProc("9.9.9.9         STREAM dns.quad9.net\n"))
        with self.assertRaisesRegex(ThroughputValidationError, "only runs against local"):
            self.run_one(host="dns.quad9.net")

    def test_an_unknown_name_is_an_error_in_the_result(self):
        self.procs.append(FakeProc("", code=2))
        result = self.run_one(host="nope.lan")
        self.assertEqual(result["error"], "nope.lan could not be found.")
        self.assertIsNone(result["bits_per_second"])


class TestRun(Harness):
    def test_upload_reads_the_sender_sum(self):
        self.procs.append(FakeProc(fixture("upload")))
        result = self.run_one(port=5299, duration=1)
        self.assertEqual(
            self.calls[0],
            ("iperf3", "-c", "192.168.1.20", "-p", "5299", "-t", "1",
             "--connect-timeout", "3000", "-J"),
        )
        self.assertEqual(result["bits_per_second"], 76279042022.8845)
        self.assertEqual(result["retransmits"], 0)
        self.assertEqual(result["path"], PATH)
        self.assertEqual(
            {k: result[k] for k in ("peer", "resolved_ip", "port", "direction", "duration")},
            {"peer": "192.168.1.20", "resolved_ip": "192.168.1.20", "port": 5299,
             "direction": "upload", "duration": 1},
        )

    def test_download_reverses_and_reads_the_receiver_sum(self):
        self.procs.append(FakeProc(fixture("download")))
        result = self.run_one(direction="download")
        self.assertEqual(self.calls[0][-1], "-R")
        self.assertIn("5201", self.calls[0])  # the default port
        self.assertIn("10", self.calls[0])  # the default duration
        self.assertEqual(result["bits_per_second"], 78669655144.41032)
        self.assertIsNone(result["retransmits"])

    def test_iperf3_errors_read_as_plain_sentences(self):
        self.procs.append(FakeProc(fixture("refused"), code=1))
        self.assertEqual(
            self.run_one(port=5298)["error"],
            "No iperf3 server on 192.168.1.20:5298. Start one there with iperf3 -s.",
        )
        self.procs.append(FakeProc(fixture("refused"), code=1))
        self.assertIn("No iperf3 server on [fd00::5]:5201.", self.run_one(host="fd00::5")["error"])
        self.procs.append(FakeProc(fixture("busy"), code=1))
        result = self.run_one()
        self.assertEqual(result["error"], "The iperf3 server is busy with another test.")
        self.assertIsNone(result["bits_per_second"])

    def test_output_with_no_result_reports_stderr_or_the_exit_code(self):
        self.procs.append(FakeProc("", "iperf3: error - bad option\n", code=1))
        self.assertEqual(self.run_one()["error"], "iperf3: error - bad option")
        self.procs.append(FakeProc("[]", code=3))
        self.assertEqual(self.run_one()["error"], "iperf3 exited with code 3")

    def test_the_deadline_stops_and_reaps_iperf3(self):
        child = FakeProc(release=asyncio.Event())  # never finishes
        self.procs.append(child)
        with patch.object(throughput_service, "DEADLINE_SLACK", -0.95):  # 1 s test: 0.05 s
            result = self.run_one(duration=1)
        self.assertEqual(result["error"], TOO_LONG)
        child.kill.assert_called_once()
        child.wait.assert_awaited_once()

    def test_a_missing_binary_is_an_error_not_a_crash(self):
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError(2, "No such file", "iperf3")):
            result = self.run_one()
        self.assertIn("NetTap could not start the test", result["error"])

    def test_one_test_at_a_time(self):
        async def go():
            release = asyncio.Event()
            self.procs.append(FakeProc(fixture("upload"), release=release))
            first = asyncio.create_task(self.svc.run_test(host="192.168.1.20", direction="upload"))
            await asyncio.sleep(0.01)
            with self.assertRaisesRegex(ThroughputBusyError, BUSY):
                await self.svc.run_test(host="192.168.1.21", direction="download")
            release.set()
            return await first

        self.assertIsNone(asyncio.run(go())["error"])
        self.assertEqual(len(self.calls), 1)

    def test_capture_port_address(self):
        addr = lambda family, address: SimpleNamespace(family=family, address=address)
        addrs = {
            "enp4s0": [addr(socket.AF_INET6, "fe80::8e32:23ff:fe82:856%enp4s0")],
            "br0": [addr(socket.AF_INET, "192.168.1.2")],
        }
        with patch.object(throughput_service.psutil, "net_if_addrs", return_value=addrs):
            for iface, has_ip in (("enp4s0", False), ("br0", True), ("gone0", False)):
                self.procs.append(FakeProc(fixture("upload")))
                capture = self.run_one(capture_mode="mirror", capture_interface=iface)["capture"]
                self.assertEqual(capture, {"mode": "mirror", "interface": iface, "has_ip": has_ip})


class TestThroughputRoute(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        register_tools_routes(app, MagicMock(), MagicMock(), MagicMock(), MagicMock())
        self.svc = MagicMock()
        self.svc.run_test = AsyncMock(return_value={"error": None, "bits_per_second": 1.0})
        app["throughput"] = self.svc
        app["capture_manager"] = SimpleNamespace(
            mode=CaptureMode.MIRROR, get_capture_interface=lambda: "enp4s0"
        )
        return app

    async def test_passes_the_body_and_the_capture_mode(self):
        body = {"host": "192.168.1.20", "port": 5299, "duration": 5, "direction": "download"}
        resp = await self.client.post("/api/tools/throughput", json=body)
        self.assertEqual(resp.status, 200)
        self.svc.run_test.assert_awaited_once_with(
            **body, capture_mode="mirror", capture_interface="enp4s0"
        )

    async def test_bad_input_is_400_busy_is_409(self):
        for exc, status in (
            (ThroughputValidationError("Port must be a whole number from 1 to 65535."), 400),
            (NetworkDiagValidationError("Target is required"), 400),
            (ThroughputBusyError(BUSY), 409),
        ):
            self.svc.run_test.side_effect = exc
            resp = await self.client.post("/api/tools/throughput", json={})
            self.assertEqual(resp.status, status)
            self.assertEqual((await resp.json())["error"], str(exc))

    async def test_a_body_that_is_not_an_object_is_400(self):
        for raw in ("[1]", "not json"):
            resp = await self.client.post("/api/tools/throughput", data=raw)
            self.assertEqual(resp.status, 400)
        self.svc.run_test.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
