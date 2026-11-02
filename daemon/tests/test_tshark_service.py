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
    TSharkValidationError,
    MAX_PACKETS,
    EXECUTION_TIMEOUT,
    bounded_exec,
)


def _mock_exists_true(*args, **kwargs):
    """Helper: always return True for os.path.exists (PCAP file exists)."""
    return True


class TestValidatePcapPath(unittest.TestCase):
    """Tests for TSharkService.validate_pcap_path."""

    def setUp(self):
        self.svc = TSharkService(pcap_base_dir="/opt/nettap/pcap")

    @patch("os.path.exists", return_value=True)
    def test_validate_pcap_path_valid(self, _mock_exists):
        """Valid relative path like 'session123.pcap' should resolve to container path."""
        result = self.svc.validate_pcap_path("session123.pcap")
        self.assertEqual(result, "/pcap/session123.pcap")

    @patch("os.path.exists", return_value=True)
    def test_validate_pcap_path_absolute_under_base(self, _mock_exists):
        """Absolute path under pcap_base_dir should resolve to container path."""
        result = self.svc.validate_pcap_path("/opt/nettap/pcap/capture.pcap")
        self.assertEqual(result, "/pcap/capture.pcap")

    def test_validate_pcap_path_file_not_found(self):
        """Non-existent file should raise TSharkValidationError with clear message."""
        with self.assertRaises(TSharkValidationError) as ctx:
            self.svc.validate_pcap_path("nonexistent.pcap")
        self.assertIn("not found", str(ctx.exception).lower())
        self.assertIn("nonexistent.pcap", str(ctx.exception))

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
        result = self.svc.validate_display_filter("http.request && ip.src == 10.0.0.1")
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

    @patch("os.path.exists", return_value=True)
    def test_max_packets_capped(self, _mock_exists):
        """Verify max_packets=2000 gets capped to MAX_PACKETS (1000)."""
        req = TSharkRequest(pcap_path="test.pcap", max_packets=2000)
        validated = self.svc.validate_request(req)
        self.assertEqual(validated.max_packets, MAX_PACKETS)

    @patch("os.path.exists", return_value=True)
    def test_max_packets_minimum(self, _mock_exists):
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
        json_data = json.dumps(
            [
                {"_index": "packets", "layers": {"frame": {}}},
                {"_index": "packets", "layers": {"ip": {}}},
            ]
        )
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

    @patch("os.path.exists", return_value=True)
    def test_analyze_success(self, _mock_exists):
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

    @patch("os.path.exists", return_value=True)
    def test_analyze_timeout(self, _mock_exists):
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


class TestInfoColumn(unittest.TestCase):
    """-T json has no Info column; a fields pass fills it in (TShark 4.0)."""

    def setUp(self):
        self.svc = TSharkService()

    @staticmethod
    def _pkt(number: str) -> dict:
        return {"_source": {"layers": {"frame": {"frame.number": number}}}}

    @patch("os.path.exists", return_value=True)
    def test_info_text_is_merged_by_frame_number(self, _mock_exists):
        json_out = json.dumps([self._pkt("1"), self._pkt("2")])
        fields_out = "1\t443 \u2192 51234 [ACK] Seq=1 Ack=1 Len=1448\n2\tStandard query 0x1a2b A example.com\n"

        async def run():
            with patch.object(self.svc, "_exec_tshark", new_callable=AsyncMock) as ex:
                # a filter first scans for its matches (#64)
                ex.side_effect = [("2\n", "", 0), (json_out, "", 0), (fields_out, "", 0)]
                with patch.object(self.svc, "get_version", new_callable=AsyncMock):
                    req = TSharkRequest(
                        pcap_path="test.pcap",
                        output_format="json",
                        display_filter="dns",
                    )
                    result = await self.svc.analyze(req)
                info_cmd = ex.call_args_list[2].args[0]
                self.assertEqual(
                    info_cmd[-4:], ["-e", "frame.number", "-e", "_ws.col.Info"]
                )
                self.assertIn("dns", info_cmd)
                return result

        result = asyncio.run(run())
        infos = [p["_source"]["layers"]["_ws.col.Info"] for p in result.packets]
        self.assertEqual(
            infos,
            [
                "443 \u2192 51234 [ACK] Seq=1 Ack=1 Len=1448",
                "Standard query 0x1a2b A example.com",
            ],
        )

    @patch("os.path.exists", return_value=True)
    def test_packets_survive_a_failed_info_pass(self, _mock_exists):
        json_out = json.dumps([self._pkt("1")])

        async def run():
            with patch.object(self.svc, "_exec_tshark", new_callable=AsyncMock) as ex:
                ex.side_effect = [(json_out, "", 0), TSharkValidationError("timed out")]
                with patch.object(self.svc, "get_version", new_callable=AsyncMock):
                    return await self.svc.analyze(
                        TSharkRequest(pcap_path="test.pcap", output_format="json")
                    )

        result = asyncio.run(run())
        self.assertEqual(result.packets, [self._pkt("1")])

    @patch("os.path.exists", return_value=True)
    def test_text_output_runs_tshark_once(self, _mock_exists):
        async def run():
            with patch.object(self.svc, "_exec_tshark", new_callable=AsyncMock) as ex:
                ex.return_value = ("1 0.0 a -> b TCP", "", 0)
                with patch.object(self.svc, "get_version", new_callable=AsyncMock):
                    await self.svc.analyze(
                        TSharkRequest(pcap_path="test.pcap", output_format="text")
                    )
                return ex.call_count

        self.assertEqual(asyncio.run(run()), 1)


class TestIsAvailable(unittest.TestCase):
    """Tests for TSharkService.is_available."""

    def test_is_available_running(self):
        """Mock docker inspect returning 'true' -- should report available."""

        async def run():
            svc = TSharkService()
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(return_value=(b"true\n", b""))
            mock_process.returncode = 0

            with patch(
                "asyncio.create_subprocess_exec", new_callable=AsyncMock
            ) as mock_exec:
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
            mock_process.communicate = AsyncMock(return_value=(b"false\n", b""))
            mock_process.returncode = 0

            with patch(
                "asyncio.create_subprocess_exec", new_callable=AsyncMock
            ) as mock_exec:
                mock_exec.return_value = mock_process
                result = await svc.is_available()
                self.assertFalse(result["available"])
                self.assertFalse(result["container_running"])
                self.assertEqual(result["version"], "unknown")

        asyncio.run(run())


class TestBuildCommandVerbose(unittest.TestCase):
    """Tests for verbose mode in _build_tshark_command."""

    def setUp(self):
        self.svc = TSharkService()

    def test_build_command_verbose_has_V_flag(self):
        """Verify -V flag is present in verbose mode."""
        req = TSharkRequest(
            pcap_path="/pcap/test.pcap",
            display_filter="ip.addr == 10.0.0.1",
            max_packets=20,
            verbose=True,
        )
        cmd = self.svc._build_tshark_command(req)
        self.assertIn("-V", cmd)
        # Verbose mode should NOT have -T json
        self.assertNotIn("json", cmd)

    def test_build_command_verbose_has_filter_and_c(self):
        """Verify -Y and -c are still present in verbose mode."""
        req = TSharkRequest(
            pcap_path="/pcap/test.pcap",
            display_filter="http.request",
            max_packets=10,
            verbose=True,
        )
        cmd = self.svc._build_tshark_command(req)
        self.assertIn("-Y", cmd)
        self.assertIn("-c", cmd)
        self.assertIn("-V", cmd)


class TestBuildCommandFollowStream(unittest.TestCase):
    """Tests for follow stream mode in _build_tshark_command."""

    def setUp(self):
        self.svc = TSharkService()

    def test_build_command_follow_stream_tcp(self):
        """Verify -q -z follow,tcp,ascii,<filter> structure."""
        req = TSharkRequest(
            pcap_path="/pcap/test.pcap",
            display_filter="ip.addr == 10.0.0.1 && tcp.port == 443",
            follow_stream="tcp",
        )
        cmd = self.svc._build_tshark_command(req)
        self.assertIn("-q", cmd)
        self.assertIn("-z", cmd)
        z_idx = cmd.index("-z")
        z_arg = cmd[z_idx + 1]
        self.assertTrue(z_arg.startswith("follow,tcp,ascii,"))
        self.assertIn("ip.addr == 10.0.0.1", z_arg)

    def test_follow_stream_no_Y_or_c_flags(self):
        """Follow stream mode with display_filter should NOT have -Y or -c flags."""
        req = TSharkRequest(
            pcap_path="/pcap/test.pcap",
            display_filter="http.request",
            max_packets=50,
            follow_stream="udp",
        )
        cmd = self.svc._build_tshark_command(req)
        self.assertNotIn("-Y", cmd)
        self.assertNotIn("-c", cmd)
        self.assertIn("-q", cmd)

    def test_follow_stream_no_T_flag(self):
        """Follow stream mode with display_filter should NOT have -T flag."""
        req = TSharkRequest(
            pcap_path="/pcap/test.pcap",
            display_filter="ip.addr == 10.0.0.1",
            follow_stream="tls",
            output_format="json",
        )
        cmd = self.svc._build_tshark_command(req)
        self.assertNotIn("-T", cmd)

    def test_follow_stream_without_filter_falls_through(self):
        """When no display_filter given, follow mode is skipped.

        Previously this would default to stream index "0", which silently
        followed an arbitrary stream.  Now it falls through to normal
        packet listing with -c and the requested output format.
        """
        req = TSharkRequest(
            pcap_path="/pcap/test.pcap",
            follow_stream="http",
            max_packets=50,
            output_format="json",
        )
        cmd = self.svc._build_tshark_command(req)
        # Should NOT have -z follow (no filter to follow with)
        self.assertNotIn("-z", cmd)
        self.assertNotIn("-q", cmd)
        # Should fall through to normal packet output
        self.assertIn("-c", cmd)
        self.assertIn("-T", cmd)


class TestFollowStreamValidation(unittest.TestCase):
    """Tests for follow_stream validation in validate_request."""

    def setUp(self):
        self.svc = TSharkService()

    @patch("os.path.exists", return_value=True)
    def test_valid_follow_protocols(self, _mock_exists):
        """Valid protocols should pass validation."""
        from services.tshark_service import ALLOWED_FOLLOW_PROTOCOLS

        for proto in ALLOWED_FOLLOW_PROTOCOLS:
            req = TSharkRequest(pcap_path="test.pcap", follow_stream=proto)
            validated = self.svc.validate_request(req)
            self.assertEqual(validated.follow_stream, proto)

    @patch("os.path.exists", return_value=True)
    def test_invalid_follow_protocol(self, _mock_exists):
        """Invalid protocol should raise TSharkValidationError."""
        req = TSharkRequest(pcap_path="test.pcap", follow_stream="ftp")
        with self.assertRaises(TSharkValidationError) as ctx:
            self.svc.validate_request(req)
        self.assertIn("invalid follow protocol", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()


class TestBoundedExec(unittest.TestCase):
    """tshark must die inside the container when the daemon gives up on it."""

    def test_docker_exec_gets_in_container_timeout(self):
        cmd = ["docker", "exec", "nettap-tshark", "tshark", "-r", "/pcap/a.pcap"]
        self.assertEqual(
            bounded_exec(cmd, 30),
            [
                "docker",
                "exec",
                "nettap-tshark",
                "timeout",
                "-k",
                "5",
                "30",
                "tshark",
                "-r",
                "/pcap/a.pcap",
            ],
        )

    def test_other_commands_unchanged(self):
        inspect = ["docker", "inspect", "--format", "{{.State.Running}}", "x"]
        self.assertEqual(bounded_exec(inspect, 30), inspect)

    def test_every_service_command_runs_bounded(self):
        captured = []

        async def fake_exec(*argv, **kwargs):
            captured.append(list(argv))
            proc = MagicMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        svc = TSharkService()
        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            asyncio.run(
                svc._exec_tshark(["docker", "exec", "nettap-tshark", "tshark", "-v"])
            )
        self.assertEqual(
            captured[0][3:7], ["timeout", "-k", "5", str(EXECUTION_TIMEOUT)]
        )


class TestFilterSearchesWholeFile(unittest.TestCase):
    """#64: -c counts packets read, so "-c 100 -Y dns" only searched the first 100 packets."""

    def setUp(self):
        self.svc = TSharkService()

    def _run(self, responses, **kw):
        async def run():
            with patch.object(self.svc, "_exec_tshark", new_callable=AsyncMock) as ex:
                ex.side_effect = responses
                with patch.object(self.svc, "get_version", new_callable=AsyncMock):
                    result = await self.svc.analyze(
                        TSharkRequest(pcap_path="test.pcap", output_format="text", display_filter="dns", **kw)
                    )
                return result, [c.args[0] for c in ex.call_args_list]

        with patch("os.path.exists", return_value=True):
            return asyncio.run(run())

    def test_reads_up_to_the_nth_match(self):
        result, calls = self._run([("48211\n", "", 0), ("1 0.0 a -> b DNS", "", 0)], max_packets=100)
        scan, main = calls
        self.assertEqual(scan[:5], ["docker", "exec", "nettap-tshark", "sh", "-c"])
        self.assertEqual(scan[-4:-1], ["/pcap/test.pcap", "dns", "100"])
        self.assertEqual(main[main.index("-c") + 1], "48211")
        self.assertEqual(main[main.index("-Y") + 1], "dns")
        self.assertEqual(result.packet_count, 1)
        self.assertFalse(result.truncated)

    def test_no_match_skips_the_analysis(self):
        result, calls = self._run([("", "", 0)])
        self.assertEqual((result.packet_count, len(calls)), (0, 1))
        self.assertIsNone(result.error)

    def test_scan_cut_short_by_time_is_flagged(self):
        with patch("services.tshark_service.MATCH_SCAN_SECONDS", 0):
            result, _ = self._run([("900\n", "", 0), ("1 0.0 a -> b DNS", "", 0)])
        self.assertTrue(result.truncated)

    def test_filter_and_path_are_not_parsed_by_the_shell(self):
        from services.tshark_service import _LAST_MATCH_SCRIPT

        self.assertIn('-r "$1" -Y "$2"', _LAST_MATCH_SCRIPT)
        self.assertIn('head -n "$3"', _LAST_MATCH_SCRIPT)
