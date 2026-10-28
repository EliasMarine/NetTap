"""
Tests for daemon/services/network_diag_service.py

All tests use mocks -- no ping or traceroute binary required.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.network_diag_service import (
    NetworkDiagService,
    NetworkDiagValidationError,
)


class TestValidateTarget(unittest.TestCase):
    """Tests for NetworkDiagService.validate_target."""

    def setUp(self):
        self.svc = NetworkDiagService()

    def test_valid_hostname(self):
        result = self.svc.validate_target("example.com")
        self.assertEqual(result, "example.com")

    def test_valid_ip(self):
        result = self.svc.validate_target("8.8.8.8")
        self.assertEqual(result, "8.8.8.8")

    def test_valid_ipv6(self):
        result = self.svc.validate_target("2001:4860:4860::8888")
        self.assertEqual(result, "2001:4860:4860::8888")

    def test_strips_whitespace(self):
        result = self.svc.validate_target("  8.8.8.8  ")
        self.assertEqual(result, "8.8.8.8")

    def test_empty_target(self):
        with self.assertRaises(NetworkDiagValidationError):
            self.svc.validate_target("")

    def test_too_long(self):
        with self.assertRaises(NetworkDiagValidationError):
            self.svc.validate_target("a" * 254)

    def test_shell_metachar_semicolon(self):
        with self.assertRaises(NetworkDiagValidationError):
            self.svc.validate_target("; rm -rf /")

    def test_shell_metachar_pipe(self):
        with self.assertRaises(NetworkDiagValidationError):
            self.svc.validate_target("8.8.8.8 | cat /etc/passwd")

    def test_shell_metachar_backtick(self):
        with self.assertRaises(NetworkDiagValidationError):
            self.svc.validate_target("`whoami`")


class TestValidateCount(unittest.TestCase):
    """Tests for NetworkDiagService.validate_count."""

    def setUp(self):
        self.svc = NetworkDiagService()

    def test_none_returns_default(self):
        self.assertEqual(self.svc.validate_count(None), 4)

    def test_valid_count(self):
        self.assertEqual(self.svc.validate_count(5), 5)

    def test_clamp_low(self):
        self.assertEqual(self.svc.validate_count(0), 1)

    def test_clamp_high(self):
        self.assertEqual(self.svc.validate_count(100), 10)

    def test_negative(self):
        self.assertEqual(self.svc.validate_count(-5), 1)


class TestValidateMaxHops(unittest.TestCase):
    """Tests for NetworkDiagService.validate_max_hops."""

    def setUp(self):
        self.svc = NetworkDiagService()

    def test_none_returns_default(self):
        self.assertEqual(self.svc.validate_max_hops(None), 30)

    def test_valid_hops(self):
        self.assertEqual(self.svc.validate_max_hops(15), 15)

    def test_clamp_low(self):
        self.assertEqual(self.svc.validate_max_hops(0), 1)

    def test_clamp_high(self):
        self.assertEqual(self.svc.validate_max_hops(50), 30)


class TestParsePingOutput(unittest.TestCase):
    """Tests for NetworkDiagService._parse_ping_output."""

    def setUp(self):
        self.svc = NetworkDiagService()

    def test_parse_successful_ping(self):
        output = """PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=12.3 ms
64 bytes from 8.8.8.8: icmp_seq=2 ttl=117 time=11.5 ms
64 bytes from 8.8.8.8: icmp_seq=3 ttl=117 time=13.1 ms
64 bytes from 8.8.8.8: icmp_seq=4 ttl=117 time=12.0 ms

--- 8.8.8.8 ping statistics ---
4 packets transmitted, 4 received, 0% packet loss, time 3004ms
rtt min/avg/max/mdev = 11.500/12.225/13.100/0.578 ms"""
        result = self.svc._parse_ping_output(output)

        self.assertEqual(len(result["replies"]), 4)
        self.assertEqual(result["replies"][0]["bytes"], 64)
        self.assertEqual(result["replies"][0]["from"], "8.8.8.8")
        self.assertEqual(result["replies"][0]["icmp_seq"], 1)
        self.assertEqual(result["replies"][0]["ttl"], 117)
        self.assertEqual(result["replies"][0]["time_ms"], 12.3)

        self.assertEqual(result["stats"]["packets_transmitted"], 4)
        self.assertEqual(result["stats"]["packets_received"], 4)
        self.assertEqual(result["stats"]["packet_loss_percent"], 0)
        self.assertAlmostEqual(result["stats"]["rtt_min_ms"], 11.5)
        self.assertAlmostEqual(result["stats"]["rtt_avg_ms"], 12.225)
        self.assertAlmostEqual(result["stats"]["rtt_max_ms"], 13.1)

    def test_parse_packet_loss(self):
        output = """PING 10.0.0.1 (10.0.0.1) 56(84) bytes of data.
64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=1.5 ms

--- 10.0.0.1 ping statistics ---
4 packets transmitted, 1 received, 75% packet loss, time 3003ms
rtt min/avg/max/mdev = 1.500/1.500/1.500/0.000 ms"""
        result = self.svc._parse_ping_output(output)

        self.assertEqual(len(result["replies"]), 1)
        self.assertEqual(result["stats"]["packet_loss_percent"], 75)

    def test_parse_empty_output(self):
        result = self.svc._parse_ping_output("")
        self.assertEqual(result["replies"], [])
        self.assertEqual(result["stats"], {})


class TestParseTracerouteOutput(unittest.TestCase):
    """Tests for NetworkDiagService._parse_traceroute_output."""

    def setUp(self):
        self.svc = NetworkDiagService()

    def test_parse_successful_traceroute(self):
        output = """traceroute to example.com (93.184.216.34), 30 hops max, 60 byte packets
 1  gateway (10.0.0.1)  1.234 ms  1.345 ms  1.456 ms
 2  isp-router (192.168.1.1)  5.678 ms  5.789 ms  5.890 ms
 3  * * *
 4  target (93.184.216.34)  15.123 ms  15.234 ms  15.345 ms"""
        hops = self.svc._parse_traceroute_output(output)

        self.assertEqual(len(hops), 4)

        self.assertEqual(hops[0]["hop"], 1)
        self.assertEqual(hops[0]["host"], "gateway")
        self.assertEqual(hops[0]["ip"], "10.0.0.1")
        self.assertEqual(len(hops[0]["rtt_ms"]), 3)

        self.assertEqual(hops[2]["hop"], 3)
        self.assertEqual(hops[2]["host"], "*")
        self.assertIsNone(hops[2]["ip"])
        self.assertEqual(hops[2]["rtt_ms"], [])

    def test_parse_empty_output(self):
        hops = self.svc._parse_traceroute_output("")
        self.assertEqual(hops, [])


class TestPing(unittest.TestCase):
    """Tests for NetworkDiagService.ping (async)."""

    def setUp(self):
        self.svc = NetworkDiagService()

    def test_ping_success(self):
        ping_output = b"""PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=12.3 ms

--- 8.8.8.8 ping statistics ---
1 packets transmitted, 1 received, 0% packet loss, time 0ms
rtt min/avg/max/mdev = 12.300/12.300/12.300/0.000 ms"""

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(ping_output, b""))
        mock_proc.returncode = 0

        async def run_test():
            with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                result = await self.svc.ping("8.8.8.8", count=1)

            self.assertEqual(result["target"], "8.8.8.8")
            self.assertEqual(result["count"], 1)
            self.assertIsNone(result["error"])
            self.assertEqual(len(result["replies"]), 1)

        asyncio.run(run_test())

    def test_ping_validation_error(self):
        async def run_test():
            with self.assertRaises(NetworkDiagValidationError):
                await self.svc.ping("")

        asyncio.run(run_test())

    def test_ping_timeout(self):
        async def run_test():
            with patch(
                "asyncio.create_subprocess_exec",
                return_value=MagicMock(
                    communicate=AsyncMock(side_effect=asyncio.TimeoutError),
                    kill=MagicMock(),
                ),
            ):
                result = await self.svc.ping("8.8.8.8")

            self.assertEqual(result["error"], "Ping timed out")
            self.assertEqual(result["replies"], [])

        asyncio.run(run_test())


class TestTraceroute(unittest.TestCase):
    """Tests for NetworkDiagService.traceroute (async)."""

    def setUp(self):
        self.svc = NetworkDiagService()

    def test_traceroute_success(self):
        tr_output = b"""traceroute to 8.8.8.8 (8.8.8.8), 30 hops max, 60 byte packets
 1  gateway (10.0.0.1)  1.234 ms  1.345 ms  1.456 ms
 2  8.8.8.8 (8.8.8.8)  5.678 ms  5.789 ms  5.890 ms"""

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(tr_output, b""))
        mock_proc.returncode = 0

        async def run_test():
            with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                result = await self.svc.traceroute("8.8.8.8", max_hops=10)

            self.assertEqual(result["target"], "8.8.8.8")
            self.assertEqual(result["max_hops"], 10)
            self.assertIsNone(result["error"])
            self.assertEqual(len(result["hops"]), 2)

        asyncio.run(run_test())

    def test_traceroute_timeout(self):
        async def run_test():
            with patch(
                "asyncio.create_subprocess_exec",
                return_value=MagicMock(
                    communicate=AsyncMock(side_effect=asyncio.TimeoutError),
                    kill=MagicMock(),
                ),
            ):
                result = await self.svc.traceroute("8.8.8.8")

            self.assertEqual(result["error"], "Traceroute timed out")
            self.assertEqual(result["hops"], [])

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
