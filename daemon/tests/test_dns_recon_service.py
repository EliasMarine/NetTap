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

from services.dns_recon_service import (
    DnsReconService,
    DnsReconValidationError,
    ALLOWED_RECORD_TYPES,
    DEFAULT_RECORD_TYPES,
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
            self.assertIsNone(result["errors"])

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


if __name__ == "__main__":
    unittest.main()
