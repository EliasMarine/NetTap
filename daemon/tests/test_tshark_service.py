"""
Tests for daemon/services/tshark_service.py

All tests use mocks -- no Docker or TShark binary required.
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.tshark_service import (
    TSharkService,
    TSharkRequest,
    TSharkResult,
    TSharkValidationError,
    MAX_PACKETS,
    MAX_OUTPUT_BYTES,
    PCAP_MOUNT_PATH,
)


class TestValidatePcapPath(unittest.TestCase):
    """Tests for TSharkService.validate_pcap_path."""

    def setUp(self):
        self.svc = TSharkService(pcap_base_dir="/opt/nettap/pcap")

    def test_validate_pcap_path_valid(self):
        """Valid relative path like 'session123.pcap' should resolve to container path."""
        result = self.svc.validate_pcap_path("session123.pcap")
        self.assertEqual(result, "/pcap/session123.pcap")

    def test_validate_pcap_path_absolute_under_base(self):
        """Absolute path under pcap_base_dir should resolve to container path."""
        result = self.svc.validate_pcap_path("/opt/nettap/pcap/capture.pcap")
        self.assertEqual(result, "/pcap/capture.pcap")

    def test_validate_pcap_path_traversal_dotdot(self):
        """Reject relative path with '..' traversal."""
        with self.assertRaises(TSharkValidationError) as ctx:
            self.svc.validate_pcap_path("../etc/passwd.pcap")
        self.assertIn("traversal", str(ctx.exception).lower())

    def test_validate_pcap_path_traversal_absolute(self):
        """Reject absolute path outside pcap_base_dir."""
        with self.assertRaises(TSharkValidationError) as ctx:
            self.svc.validate_pcap_path("/etc/passwd")
        # Could match either "must be under" or "Invalid PCAP file extension"
        self.assertTrue(
            "must be under" in str(ctx.exception).lower()
            or "invalid pcap file extension" in str(ctx.exception).lower()
        )

    def test_validate_pcap_path_bad_extension(self):
        """Reject file with non-PCAP extension."""
        with self.assertRaises(TSharkValidationError) as ctx:
            self.svc.validate_pcap_path("file.txt")
        self.assertIn("invalid pcap file extension", str(ctx.exception).lower())


class TestValidateDisplayFilter(unittest.TestCase):
    """Tests for TSharkService.validate_display_filter."""

    def setUp(self):
        self.svc = TSharkService()

    def test_validate_display_filter_clean(self):
        """Allow valid display filter with comparison operators."""
        result = self.svc.validate_display_filter(
            "http.request && ip.src == 10.0.0.1"
        )
        self.assertEqual(result, "http.request && ip.src == 10.0.0.1")

    def test_validate_display_filter_shell_metachar(self):
        """Reject filter containing semicolon (shell metacharacter)."""
        with self.assertRaises(TSharkValidationError) as ctx:
            self.svc.validate_display_filter("; rm -rf /")
        self.assertIn("forbidden", str(ctx.exception).lower())

    def test_validate_display_filter_backtick(self):
        """Reject filter containing backticks (command substitution)."""
        with self.assertRaises(TSharkValidationError) as ctx:
            self.svc.validate_display_filter("`whoami`")
        self.assertIn("forbidden", str(ctx.exception).lower())

    def test_validate_display_filter_dollar(self):
        """Reject filter containing dollar sign (variable expansion)."""
        with self.assertRaises(TSharkValidationError) as ctx:
            self.svc.validate_display_filter("http && $HOME")
        self.assertIn("forbidden", str(ctx.exception).lower())

    def test_validate_display_filter_too_long(self):
        """Reject filter exceeding 500 characters."""
        long_filter = "a" * 501
        with self.assertRaises(TSharkValidationError) as ctx:
            self.svc.validate_display_filter(long_filter)
        self.assertIn("too long", str(ctx.exception).lower())

    def test_validate_display_filter_empty(self):
        """Empty filter should return empty string."""
        result = self.svc.validate_display_filter("")
        self.assertEqual(result, "")


class TestValidateFields(unittest.TestCase):
    """Tests for TSharkService.validate_fields."""

    def setUp(self):
        self.svc = TSharkService()

    def test_validate_fields_valid(self):
        """Allow valid field names with dots and underscores."""
        result = self.svc.validate_fields(["ip.src", "ip.dst", "tcp.port"])
        self.assertEqual(result, ["ip.src", "ip.dst", "tcp.port"])

    def test_validate_fields_invalid(self):
        """Reject field names containing shell metacharacters."""
        with self.assertRaises(TSharkValidationError) as ctx:
            self.svc.validate_fields(["ip.src; rm -rf"])
        self.assertIn("invalid field name", str(ctx.exception).lower())

    def test_validate_fields_too_many(self):
        """Reject more than 50 fields."""
        fields = [f"field.{i}" for i in range(51)]
        with self.assertRaises(TSharkValidationError) as ctx:
            self.svc.validate_fields(fields)
        self.assertIn("too many", str(ctx.exception).lower())


class TestValidateRequest(unittest.TestCase):
    """Tests for max_packets capping in validate_request."""

    def setUp(self):
        self.svc = TSharkService()

    def test_max_packets_capped(self):
        """Verify max_packets=2000 gets capped to MAX_PACKETS (1000)."""
        req = TSharkRequest(pcap_path="test.pcap", max_packets=2000)
        validated = self.svc.validate_request(req)
        self.assertEqual(validated.max_packets, MAX_PACKETS)

    def test_max_packets_minimum(self):
        """Verify max_packets=0 gets set to 1."""
        req = TSharkRequest(pcap_path="test.pcap", max_packets=0)
        validated = self.svc.validate_request(req)
        self.assertEqual(validated.max_packets, 1)


class TestBuildCommand(unittest.TestCase):
    """Tests for TSharkService._build_tshark_command."""

    def setUp(self):
        self.svc = TSharkService()

    def test_build_command_json(self):
        """Verify correct tshark JSON output arguments."""
        req = TSharkRequest(
            pcap_path="/pcap/test.pcap",
            max_packets=50,
            output_format="json",
        )
        cmd = self.svc._build_tshark_command(req)
        self.assertIn("docker", cmd)
        self.assertIn("exec", cmd)
        self.assertIn("nettap-tshark", cmd)
        self.assertIn("tshark", cmd)
        # Check -r flag
        r_idx = cmd.index("-r")
        self.assertEqual(cmd[r_idx + 1], "/pcap/test.pcap")
        # Check -c flag
        c_idx = cmd.index("-c")
        self.assertEqual(cmd[c_idx + 1], "50")
        # Check -T json
        t_idx = cmd.index("-T")
        self.assertEqual(cmd[t_idx + 1], "json")

    def test_build_command_with_filter(self):
        """Verify -Y flag is included when display_filter is set."""
        req = TSharkRequest(
            pcap_path="/pcap/test.pcap",
            display_filter="http.request",
            output_format="text",
        )
        cmd = self.svc._build_tshark_command(req)
        y_idx = cmd.index("-Y")
        self.assertEqual(cmd[y_idx + 1], "http.request")

    def test_build_command_with_fields(self):
        """Verify -T fields -e field1 -e field2 when fields are specified."""
        req = TSharkRequest(
            pcap_path="/pcap/test.pcap",
            fields=["ip.src", "ip.dst"],
            output_format="json",  # Should be overridden by fields
        )
        cmd = self.svc._build_tshark_command(req)
        t_idx = cmd.index("-T")
        self.assertEqual(cmd[t_idx + 1], "fields")
        # Check -e flags
        e_indices = [i for i, c in enumerate(cmd) if c == "-e"]
        self.assertEqual(len(e_indices), 2)
        self.assertEqual(cmd[e_indices[0] + 1], "ip.src")
        self.assertEqual(cmd[e_indices[1] + 1], "ip.dst")


class TestParseOutput(unittest.TestCase):
    """Tests for output parsing methods."""

    def setUp(self):
        self.svc = TSharkService()

    def test_parse_json_output(self):
        """Valid JSON array should be parsed into list of dicts."""
        json_data = json.dumps([
            {"_index": "packets", "layers": {"frame": {}}},
            {"_index": "packets", "layers": {"ip": {}}},
        ])
        result = self.svc._parse_json_output(json_data)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["_index"], "packets")

    def test_parse_json_output_empty(self):
        """Empty string should return empty list."""
        result = self.svc._parse_json_output("")
        self.assertEqual(result, [])

    def test_parse_text_output(self):
        """Multiple lines should produce list of dicts with 'no' and 'raw'."""
        text = "  1 0.000000 10.0.0.1 -> 10.0.0.2 TCP\n  2 0.001000 10.0.0.2 -> 10.0.0.1 TCP\n"
        result = self.svc._parse_text_output(text)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["no"], 1)
        self.assertIn("10.0.0.1", result[0]["raw"])
        self.assertEqual(result[1]["no"], 2)


class TestAnalyze(unittest.TestCase):
    """Tests for TSharkService.analyze (async)."""

    def setUp(self):
        self.svc = TSharkService()

    def test_analyze_success(self):
        """Mock subprocess execution and verify parse of JSON output."""
        json_output = json.dumps([{"_index": "packets", "layers": {"frame": {}}}])

        async def run():
            with patch.object(
                self.svc, "_exec_tshark", new_callable=AsyncMock
            ) as mock_exec:
                mock_exec.return_value = (json_output, "", 0)
                with patch.object(
                    self.svc, "get_version", new_callable=AsyncMock
                ) as mock_ver:
                    mock_ver.return_value = "TShark 4.2.2"
                    req = TSharkRequest(pcap_path="test.pcap", output_format="json")
                    result = await self.svc.analyze(req)
                    self.assertEqual(result.packet_count, 1)
                    self.assertIsNone(result.error)
                    self.assertEqual(result.tshark_version, "TShark 4.2.2")
                    self.assertFalse(result.truncated)

        asyncio.run(run())

    def test_analyze_timeout(self):
        """Mock timeout and verify TSharkValidationError is raised."""

        async def run():
            with patch.object(
                self.svc, "_exec_tshark", new_callable=AsyncMock
            ) as mock_exec:
                mock_exec.side_effect = TSharkValidationError(
                    "TShark execution timed out after 30s"
                )
                req = TSharkRequest(pcap_path="test.pcap")
                with self.assertRaises(TSharkValidationError) as ctx:
                    await self.svc.analyze(req)
                self.assertIn("timed out", str(ctx.exception).lower())

        asyncio.run(run())


class TestIsAvailable(unittest.TestCase):
    """Tests for TSharkService.is_available."""

    def test_is_available_running(self):
        """Mock docker inspect returning 'true' -- should report available."""

        async def run():
            svc = TSharkService()
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(
                return_value=(b"true\n", b"")
            )
            mock_process.returncode = 0

            with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
                mock_exec.return_value = mock_process
                with patch.object(
                    svc, "get_version", new_callable=AsyncMock
                ) as mock_ver:
                    mock_ver.return_value = "TShark 4.2.2"
                    result = await svc.is_available()
                    self.assertTrue(result["available"])
                    self.assertTrue(result["container_running"])
                    self.assertEqual(result["version"], "TShark 4.2.2")

        asyncio.run(run())

    def test_is_available_not_running(self):
        """Mock docker inspect returning 'false' -- should report unavailable."""

        async def run():
            svc = TSharkService()
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(
                return_value=(b"false\n", b"")
            )
            mock_process.returncode = 0

            with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
                mock_exec.return_value = mock_process
                result = await svc.is_available()
                self.assertFalse(result["available"])
                self.assertFalse(result["container_running"])
                self.assertEqual(result["version"], "unknown")

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
