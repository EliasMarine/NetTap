"""
Tests for daemon/services/dns_recon_service.py

All tests use mocks -- no dig binary required.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.tools import register_tools_routes
from services.dns_recon_service import (
    DnsReconBusyError,
    DnsReconService,
    DnsReconValidationError,
    ALLOWED_RECORD_TYPES,
    DEFAULT_RECORD_TYPES,
    LOOKUPS_BUSY,
    MAX_CONCURRENT_LOOKUPS,
)


class TestValidateDomain(unittest.TestCase):
    """Tests for DnsReconService.validate_domain."""

    def setUp(self):
        self.svc = DnsReconService()

    def test_valid_domain(self):
        result = self.svc.validate_domain("example.com")
        self.assertEqual(result, "example.com")

    def test_valid_subdomain(self):
        result = self.svc.validate_domain("sub.example.com")
        self.assertEqual(result, "sub.example.com")

    def test_valid_hyphenated(self):
        result = self.svc.validate_domain("my-site.example.com")
        self.assertEqual(result, "my-site.example.com")

    def test_normalizes_to_lowercase(self):
        result = self.svc.validate_domain("EXAMPLE.COM")
        self.assertEqual(result, "example.com")

    def test_strips_whitespace(self):
        result = self.svc.validate_domain("  example.com  ")
        self.assertEqual(result, "example.com")

    def test_empty_domain(self):
        with self.assertRaises(DnsReconValidationError):
            self.svc.validate_domain("")

    def test_too_long_domain(self):
        with self.assertRaises(DnsReconValidationError):
            self.svc.validate_domain("a" * 254)

    def test_shell_metachar_semicolon(self):
        with self.assertRaises(DnsReconValidationError):
            self.svc.validate_domain("; rm -rf /")

    def test_shell_metachar_backtick(self):
        with self.assertRaises(DnsReconValidationError):
            self.svc.validate_domain("`whoami`")

    def test_shell_metachar_dollar(self):
        with self.assertRaises(DnsReconValidationError):
            self.svc.validate_domain("$(whoami)")

    def test_spaces_in_domain(self):
        with self.assertRaises(DnsReconValidationError):
            self.svc.validate_domain("example .com")

    def test_single_char_domain(self):
        result = self.svc.validate_domain("x")
        self.assertEqual(result, "x")


class TestValidateRecordTypes(unittest.TestCase):
    """Tests for DnsReconService.validate_record_types."""

    def setUp(self):
        self.svc = DnsReconService()

    def test_none_returns_defaults(self):
        result = self.svc.validate_record_types(None)
        self.assertEqual(result, list(DEFAULT_RECORD_TYPES))

    def test_empty_list_returns_defaults(self):
        result = self.svc.validate_record_types([])
        self.assertEqual(result, list(DEFAULT_RECORD_TYPES))

    def test_valid_types(self):
        result = self.svc.validate_record_types(["A", "MX"])
        self.assertEqual(result, ["A", "MX"])

    def test_normalizes_to_uppercase(self):
        result = self.svc.validate_record_types(["a", "mx"])
        self.assertEqual(result, ["A", "MX"])

    def test_invalid_type(self):
        with self.assertRaises(DnsReconValidationError):
            self.svc.validate_record_types(["INVALID"])

    def test_all_allowed_types(self):
        for rtype in ALLOWED_RECORD_TYPES:
            result = self.svc.validate_record_types([rtype])
            self.assertEqual(result, [rtype])


class TestParseDigOutput(unittest.TestCase):
    """Tests for DnsReconService._parse_dig_output."""

    def setUp(self):
        self.svc = DnsReconService()

    def test_parse_a_records(self):
        output = """;; ANSWER SECTION:
example.com.		300	IN	A	93.184.216.34

"""
        records = self.svc._parse_dig_output(output)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], "example.com.")
        self.assertEqual(records[0]["ttl"], 300)
        self.assertEqual(records[0]["class"], "IN")
        self.assertEqual(records[0]["type"], "A")
        self.assertEqual(records[0]["value"], "93.184.216.34")

    def test_parse_mx_records(self):
        output = """;; ANSWER SECTION:
example.com.		3600	IN	MX	10 mail.example.com.
example.com.		3600	IN	MX	20 mail2.example.com.

"""
        records = self.svc._parse_dig_output(output)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["type"], "MX")
        self.assertEqual(records[0]["value"], "10 mail.example.com.")
        self.assertEqual(records[1]["value"], "20 mail2.example.com.")

    def test_parse_empty_output(self):
        records = self.svc._parse_dig_output("")
        self.assertEqual(records, [])

    def test_parse_no_answer_section(self):
        output = """;; AUTHORITY SECTION:
example.com.		86400	IN	SOA	ns1.example.com. admin.example.com. 2024010101 3600 900 604800 86400

"""
        records = self.svc._parse_dig_output(output)
        self.assertEqual(records, [])

    def test_parse_multiple_sections(self):
        output = """;; ANSWER SECTION:
example.com.		300	IN	A	93.184.216.34

;; AUTHORITY SECTION:
example.com.		86400	IN	NS	ns1.example.com.

"""
        records = self.svc._parse_dig_output(output)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["type"], "A")


class TestLookup(unittest.TestCase):
    """Tests for DnsReconService.lookup (async)."""

    def setUp(self):
        self.svc = DnsReconService()

    def test_lookup_success(self):
        dig_output = b""";; ANSWER SECTION:
example.com.\t\t300\tIN\tA\t93.184.216.34

"""
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(dig_output, b""))
        mock_proc.returncode = 0

        async def run_test():
            with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                result = await self.svc.lookup("example.com", ["A"])

            self.assertEqual(result["domain"], "example.com")
            self.assertIn("A", result["records"])
            self.assertEqual(result["total_records"], 1)
            self.assertEqual(result["errors"], [])

        asyncio.run(run_test())

    def test_lookup_validation_error(self):
        async def run_test():
            with self.assertRaises(DnsReconValidationError):
                await self.svc.lookup("")

        asyncio.run(run_test())

    def test_lookup_timeout(self):
        async def run_test():
            with patch(
                "asyncio.create_subprocess_exec",
                return_value=MagicMock(
                    communicate=AsyncMock(side_effect=asyncio.TimeoutError),
                    kill=MagicMock(),
                ),
            ):
                result = await self.svc.lookup("example.com", ["A"])

            self.assertEqual(result["domain"], "example.com")
            self.assertIsNotNone(result["errors"])
            self.assertTrue(any("Timeout" in e for e in result["errors"]))

        asyncio.run(run_test())

    def test_lookup_multiple_types(self):
        dig_output = b""";; ANSWER SECTION:
example.com.\t\t300\tIN\tA\t93.184.216.34

"""
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(dig_output, b""))
        mock_proc.returncode = 0

        async def run_test():
            with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                result = await self.svc.lookup("example.com", ["A", "AAAA"])

            self.assertEqual(result["record_types_queried"], ["A", "AAAA"])

        asyncio.run(run_test())


# ---------------------------------------------------------------------------
# NET-203: the queries run at the same time, a failed dig is an error, and every
# child is reaped. On the G11, 7 types one after another took 15 s on a slow
# resolver and the web proxy (10 s) reported "Daemon unreachable".
# ---------------------------------------------------------------------------

ANSWERS = {
    "A": "example.com.\t300\tIN\tA\t93.184.216.34",
    "MX": "example.com.\t300\tIN\tMX\t10 mail.example.com.",
}


class FakeDig:
    """A dig child: `communicate` waits for `release`, then answers with `out` and `code`."""

    def __init__(self, rtype, release=None, out=None, code=0):
        self.rtype = rtype
        self.release = release
        self.out = (
            out
            if out is not None
            else f";; ANSWER SECTION:\n{ANSWERS.get(rtype, '')}\n\n"
        )
        self.code = code
        self.returncode = None
        self.kill = MagicMock(side_effect=self._killed)
        self.wait = AsyncMock()

    def _killed(self):
        self.returncode = -9

    async def communicate(self):
        if self.release is not None:
            await self.release.wait()
        self.returncode = self.code
        return self.out.encode(), b""


class TestConcurrentLookup(unittest.TestCase):
    """NET-203: lookup() runs one dig per type at the same time."""

    def setUp(self):
        self.svc = DnsReconService()

    def test_queries_run_at_the_same_time_and_keep_the_requested_order(self):
        async def run_test():
            release = asyncio.Event()
            started = []

            def fake_exec(*args, **kwargs):
                started.append(args[-1])
                if len(started) == 2:
                    release.set()  # only once both are running: one after another would hang
                return FakeDig(args[-1], release)

            with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
                result = await asyncio.wait_for(
                    self.svc.lookup("example.com", ["MX", "A"]), timeout=2
                )

            self.assertEqual(started, ["MX", "A"])
            self.assertEqual(list(result["records"]), ["MX", "A"])
            self.assertEqual(result["total_records"], 2)
            self.assertEqual(result["errors"], [])

        asyncio.run(run_test())

    def test_dig_retries_a_slow_resolver_sooner(self):
        async def run_test():
            calls = []

            def fake_exec(*args, **kwargs):
                calls.append(args)
                return FakeDig(args[-1])

            with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
                await self.svc.lookup("example.com", ["A"])

            self.assertIn("+time=2", calls[0])
            self.assertIn("+tries=2", calls[0])
            self.assertEqual(calls[0][-2:], ("example.com", "A"))

        asyncio.run(run_test())

    def test_repeated_types_start_one_dig_each(self):
        self.assertEqual(
            self.svc.validate_record_types(["a", "A", "MX", "mx", " a "]), ["A", "MX"]
        )

        async def run_test():
            started = []

            def fake_exec(*args, **kwargs):
                started.append(args[-1])
                return FakeDig(args[-1])

            with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
                result = await self.svc.lookup(
                    "example.com", ["A"] * 1000 + ["mx", "MX"]
                )

            self.assertEqual(started, ["A", "MX"])
            self.assertEqual(result["record_types_queried"], ["A", "MX"])

        asyncio.run(run_test())

    def test_a_failed_dig_is_an_error_not_an_empty_answer(self):
        async def run_test():
            def fake_exec(*args, **kwargs):
                if args[-1] == "MX":
                    return FakeDig(
                        "MX",
                        out=";; connection timed out; no servers could be reached\n",
                        code=9,
                    )
                return FakeDig(args[-1])

            with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
                result = await self.svc.lookup("example.com", ["A", "MX"])

            self.assertEqual(list(result["records"]), ["A"])
            self.assertEqual(
                result["errors"],
                ["MX: connection timed out; no servers could be reached"],
            )

        asyncio.run(run_test())

    def test_a_failed_dig_with_no_diagnostic_names_its_exit_code(self):
        async def run_test():
            with patch(
                "asyncio.create_subprocess_exec",
                side_effect=lambda *a, **k: FakeDig(a[-1], out="", code=10),
            ):
                result = await self.svc.lookup("example.com", ["TXT"])

            self.assertEqual(result["errors"], ["TXT: dig exited with code 10"])

        asyncio.run(run_test())

    def test_an_empty_answer_is_no_records_and_no_error(self):
        async def run_test():
            with patch(
                "asyncio.create_subprocess_exec",
                side_effect=lambda *a, **k: FakeDig(a[-1], out=";; Got answer:\n"),
            ):
                result = await self.svc.lookup("example.com", ["AAAA"])

            self.assertEqual(result["records"], {})
            self.assertEqual(result["errors"], [])

        asyncio.run(run_test())

    def test_one_type_timing_out_keeps_the_others_and_reaps_its_child(self):
        async def run_test():
            hung = []

            def fake_exec(*args, **kwargs):
                if args[-1] == "TXT":
                    child = FakeDig("TXT", release=asyncio.Event())  # never released
                    hung.append(child)
                    return child
                return FakeDig(args[-1])

            with (
                patch("services.dns_recon_service.QUERY_TIMEOUT", 0.05),
                patch("asyncio.create_subprocess_exec", side_effect=fake_exec),
            ):
                result = await self.svc.lookup("example.com", ["A", "TXT", "MX"])

            self.assertEqual(list(result["records"]), ["A", "MX"])
            self.assertEqual(result["errors"], ["Timeout querying TXT records"])
            hung[0].kill.assert_called_once()
            hung[0].wait.assert_awaited_once()

        asyncio.run(run_test())

    def test_a_cancelled_lookup_kills_and_reaps_every_child(self):
        async def run_test():
            children = []

            def fake_exec(*args, **kwargs):
                child = FakeDig(args[-1], release=asyncio.Event())  # never released
                children.append(child)
                return child

            with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
                task = asyncio.create_task(
                    self.svc.lookup("example.com", ["A", "MX", "NS"])
                )
                for _ in range(50):
                    if len(children) == 3:
                        break
                    await asyncio.sleep(0)
                self.assertEqual(len(children), 3)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

            for child in children:
                child.kill.assert_called_once()
                child.wait.assert_awaited_once()

        asyncio.run(run_test())


class TestLookupCap(unittest.TestCase):
    """NET-203: each lookup starts up to 9 digs, so only MAX_CONCURRENT_LOOKUPS run at once."""

    def test_a_lookup_past_the_cap_is_refused_without_starting_dig(self):
        async def run_test():
            svc = DnsReconService()
            release = asyncio.Event()
            started = []

            def fake_exec(*args, **kwargs):
                started.append(args[-1])
                return FakeDig(args[-1], release)

            with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
                running = [
                    asyncio.create_task(svc.lookup("example.com", ["A"]))
                    for _ in range(MAX_CONCURRENT_LOOKUPS)
                ]
                for _ in range(50):
                    if len(started) == MAX_CONCURRENT_LOOKUPS:
                        break
                    await asyncio.sleep(0)
                self.assertEqual(len(started), MAX_CONCURRENT_LOOKUPS)

                with self.assertRaises(DnsReconBusyError):
                    # bounded: a lookup that queued for a slot instead would time out here
                    await asyncio.wait_for(svc.lookup("example.com", ["MX"]), timeout=1)
                self.assertNotIn("MX", started)

                release.set()
                await asyncio.gather(*running)
                # the slots come back once the running lookups finish
                result = await svc.lookup("example.com", ["MX"])
                self.assertEqual(result["total_records"], 1)

        asyncio.run(run_test())


class TestDnsReconRouteBusy(AioHTTPTestCase):
    """NET-203: the route answers 503 with a plain reason when the cap is reached."""

    async def get_application(self):
        self.dns_recon = MagicMock()
        self.dns_recon.lookup = AsyncMock(side_effect=DnsReconBusyError(LOOKUPS_BUSY))
        app = web.Application()
        register_tools_routes(
            app, self.dns_recon, MagicMock(), MagicMock(), MagicMock()
        )
        return app

    async def test_busy_is_503_with_the_reason(self):
        resp = await self.client.post(
            "/api/tools/dns-recon", json={"domain": "example.com"}
        )
        self.assertEqual(resp.status, 503)
        self.assertEqual(await resp.json(), {"error": LOOKUPS_BUSY})


if __name__ == "__main__":
    unittest.main()
