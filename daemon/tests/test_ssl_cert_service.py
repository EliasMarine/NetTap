"""
Tests for daemon/services/ssl_cert_service.py

All tests use mocks -- no openssl binary required.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.ssl_cert_service import (
    SslCertService,
    SslCertValidationError,
)


class TestValidateHost(unittest.TestCase):
    """Tests for SslCertService.validate_host."""

    def setUp(self):
        self.svc = SslCertService()

    def test_valid_hostname(self):
        result = self.svc.validate_host("example.com")
        self.assertEqual(result, "example.com")

    def test_valid_subdomain(self):
        result = self.svc.validate_host("www.example.com")
        self.assertEqual(result, "www.example.com")

    def test_valid_ip(self):
        result = self.svc.validate_host("93.184.216.34")
        self.assertEqual(result, "93.184.216.34")

    def test_strips_whitespace(self):
        result = self.svc.validate_host("  example.com  ")
        self.assertEqual(result, "example.com")

    def test_empty_host(self):
        with self.assertRaises(SslCertValidationError):
            self.svc.validate_host("")

    def test_too_long(self):
        with self.assertRaises(SslCertValidationError):
            self.svc.validate_host("a" * 254)

    def test_shell_metachar(self):
        with self.assertRaises(SslCertValidationError):
            self.svc.validate_host("; rm -rf /")

    def test_spaces(self):
        with self.assertRaises(SslCertValidationError):
            self.svc.validate_host("example .com")


class TestValidatePort(unittest.TestCase):
    """Tests for SslCertService.validate_port."""

    def setUp(self):
        self.svc = SslCertService()

    def test_none_returns_default(self):
        self.assertEqual(self.svc.validate_port(None), 443)

    def test_valid_port(self):
        self.assertEqual(self.svc.validate_port(8443), 8443)

    def test_port_1(self):
        self.assertEqual(self.svc.validate_port(1), 1)

    def test_port_65535(self):
        self.assertEqual(self.svc.validate_port(65535), 65535)

    def test_port_0(self):
        with self.assertRaises(SslCertValidationError):
            self.svc.validate_port(0)

    def test_port_negative(self):
        with self.assertRaises(SslCertValidationError):
            self.svc.validate_port(-1)

    def test_port_too_high(self):
        with self.assertRaises(SslCertValidationError):
            self.svc.validate_port(65536)


class TestParseCertText(unittest.TestCase):
    """Tests for SslCertService._parse_cert_text."""

    def setUp(self):
        self.svc = SslCertService()

    def test_parse_full_cert(self):
        text = """subject=CN = example.com
issuer=C = US, O = Let's Encrypt, CN = R3
Subject: CN = example.com
Issuer: C = US, O = Let's Encrypt, CN = R3
notBefore=Jan  1 00:00:00 2026 GMT
notAfter=Apr  1 00:00:00 2026 GMT
serial=0123456789ABCDEF
sha256 Fingerprint=AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89
            X509v3 Subject Alternative Name:
                DNS:example.com, DNS:www.example.com, IP Address:93.184.216.34
"""
        result = self.svc._parse_cert_text(text)

        self.assertEqual(result["subject"], "CN = example.com")
        self.assertEqual(result["issuer"], "C = US, O = Let's Encrypt, CN = R3")
        self.assertEqual(result["not_before"], "Jan  1 00:00:00 2026 GMT")
        self.assertEqual(result["not_after"], "Apr  1 00:00:00 2026 GMT")
        self.assertEqual(result["serial"], "0123456789ABCDEF")
        self.assertIn("AB:CD:EF", result["fingerprint_sha256"])
        self.assertEqual(len(result["sans"]), 3)
        self.assertIn("example.com", result["sans"])
        self.assertIn("www.example.com", result["sans"])
        self.assertIn("93.184.216.34", result["sans"])

    def test_parse_empty_text(self):
        result = self.svc._parse_cert_text("")
        self.assertNotIn("subject", result)
        self.assertEqual(result["sans"], [])

    def test_parse_no_sans(self):
        text = """Subject: CN = example.com
Issuer: C = US, O = DigiCert, CN = DigiCert SHA2 Secure Server CA
notBefore=Jan  1 00:00:00 2026 GMT
notAfter=Dec 31 23:59:59 2026 GMT
serial=DEADBEEF
sha256 Fingerprint=AA:BB:CC:DD
"""
        result = self.svc._parse_cert_text(text)
        self.assertEqual(result["sans"], [])


class TestParseChain(unittest.TestCase):
    """Tests for SslCertService._parse_chain."""

    def setUp(self):
        self.svc = SslCertService()

    def test_parse_chain(self):
        output = """CONNECTED(00000003)
depth=2 C = US, O = Internet Security Research Group, CN = ISRG Root X1
verify return:1
depth=1 C = US, O = Let's Encrypt, CN = R3
verify return:1
depth=0 CN = example.com
verify return:1
---
Certificate chain
 0 s:CN = example.com
   i:C = US, O = Let's Encrypt, CN = R3
 1 s:C = US, O = Let's Encrypt, CN = R3
   i:C = US, O = Internet Security Research Group, CN = ISRG Root X1
---"""
        chain = self.svc._parse_chain(output)
        self.assertEqual(len(chain), 2)
        self.assertEqual(chain[0]["depth"], 0)
        self.assertEqual(chain[0]["subject"], "CN = example.com")
        self.assertEqual(chain[0]["issuer"], "C = US, O = Let's Encrypt, CN = R3")

    def test_parse_empty_chain(self):
        chain = self.svc._parse_chain("")
        self.assertEqual(chain, [])


class TestInspect(unittest.TestCase):
    """Tests for SslCertService.inspect (async)."""

    def setUp(self):
        self.svc = SslCertService()

    def test_inspect_success(self):
        s_client_output = b"""CONNECTED(00000003)
---
Certificate chain
 0 s:CN = example.com
   i:C = US, O = Let's Encrypt, CN = R3
---
-----BEGIN CERTIFICATE-----
MIIFakeFakeFake
-----END CERTIFICATE-----
"""
        x509_output = b"""Subject: CN = example.com
Issuer: C = US, O = Let's Encrypt, CN = R3
notBefore=Jan  1 00:00:00 2026 GMT
notAfter=Apr  1 00:00:00 2026 GMT
serial=0123456789ABCDEF
sha256 Fingerprint=AB:CD:EF:01:23:45
            X509v3 Subject Alternative Name:
                DNS:example.com
"""

        s_client_proc = MagicMock()
        s_client_proc.communicate = AsyncMock(
            return_value=(s_client_output, b"")
        )

        x509_proc = MagicMock()
        x509_proc.communicate = AsyncMock(
            return_value=(x509_output, b"")
        )

        call_count = 0

        async def mock_create_subprocess(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return s_client_proc
            return x509_proc

        async def run_test():
            with patch(
                "asyncio.create_subprocess_exec",
                side_effect=mock_create_subprocess,
            ):
                result = await self.svc.inspect("example.com", 443)

            self.assertEqual(result["host"], "example.com")
            self.assertEqual(result["port"], 443)
            self.assertIsNone(result["error"])
            self.assertEqual(result["subject"], "CN = example.com")
            self.assertIn("example.com", result["sans"])
            self.assertEqual(len(result["chain"]), 1)

        asyncio.run(run_test())

    def test_inspect_no_cert(self):
        s_client_proc = MagicMock()
        s_client_proc.communicate = AsyncMock(
            return_value=(b"CONNECTED but no cert", b"")
        )

        async def run_test():
            with patch(
                "asyncio.create_subprocess_exec",
                return_value=s_client_proc,
            ):
                result = await self.svc.inspect("example.com")

            self.assertIsNotNone(result["error"])
            self.assertIn("No certificate", result["error"])

        asyncio.run(run_test())

    def test_inspect_validation_error(self):
        async def run_test():
            with self.assertRaises(SslCertValidationError):
                await self.svc.inspect("")

        asyncio.run(run_test())

    def test_inspect_timeout(self):
        async def run_test():
            with patch(
                "asyncio.create_subprocess_exec",
                return_value=MagicMock(
                    communicate=AsyncMock(side_effect=asyncio.TimeoutError),
                ),
            ):
                result = await self.svc.inspect("example.com")

            self.assertIn("timed out", result["error"])

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
