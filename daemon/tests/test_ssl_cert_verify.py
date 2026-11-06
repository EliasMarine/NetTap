"""S1 and S3: the SSL tool reports s_client's own trust verdict and the name fields."""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.tools import register_tools_routes
from services.ssl_cert_service import SslCertService

PEM = b"-----BEGIN CERTIFICATE-----\nMIIFake\n-----END CERTIFICATE-----\n"
X509 = b"""Subject: C=US, O=Test, Inc., CN=selfsigned.local
Issuer: C=US, O=Test, Inc., CN=selfsigned.local
notBefore=Nov  6 07:07:49 2026 GMT
notAfter=Dec  6 07:07:49 2026 GMT
"""
# What OpenSSL 3 prints for a self-signed certificate asked for under the wrong name
SELF_SIGNED_STDOUT = (
    PEM
    + b"Verification error: hostname mismatch\n    Verify return code: 62 (hostname mismatch)\n"
)
SELF_SIGNED_STDERR = b"""depth=0 C=US, O=Test, Inc., CN=selfsigned.local
verify error:num=18:self-signed certificate
verify return:1
depth=0 C=US, O=Test, Inc., CN=selfsigned.local
verify error:num=62:hostname mismatch
verify return:1
"""
TRUSTED_STDOUT = PEM + b"Verification: OK\n    Verify return code: 0 (ok)\n"


def _procs(stdout: bytes, stderr: bytes):
    s_client = MagicMock(communicate=AsyncMock(return_value=(stdout, stderr)))
    x509 = MagicMock(communicate=AsyncMock(return_value=(X509, b"")))
    return [s_client, x509]


def _inspect(host: str, stdout: bytes, stderr: bytes = b""):
    with patch(
        "asyncio.create_subprocess_exec", side_effect=_procs(stdout, stderr)
    ) as run:
        result = asyncio.run(SslCertService().inspect(host, 443))
    return result, run.call_args_list[0].args


def test_untrusted_certificate_lists_every_reason_not_only_the_last():
    result, _ = _inspect("example.com", SELF_SIGNED_STDOUT, SELF_SIGNED_STDERR)
    assert result["verify_code"] == 62
    assert result["verify_errors"] == ["self-signed certificate", "hostname mismatch"]
    assert result["name_match"] is False


def test_trusted_certificate():
    result, _ = _inspect("example.com", TRUSTED_STDOUT)
    assert (result["verify_code"], result["verify_errors"], result["name_match"]) == (
        0,
        [],
        True,
    )


def test_no_verify_result_means_not_checked():
    result, _ = _inspect("example.com", PEM)
    assert result["verify_code"] is None
    assert result["name_match"] is None


def test_a_host_name_is_checked_as_a_dns_name_and_an_ip_as_an_ip():
    _, args = _inspect("example.com", TRUSTED_STDOUT)
    assert args[-2:] == ("-verify_hostname", "example.com")
    _, args = _inspect("192.0.2.10", TRUSTED_STDOUT)
    assert args[-2:] == ("-verify_ip", "192.0.2.10")


def test_parse_dn_keeps_a_comma_inside_a_value():
    assert SslCertService.parse_dn("C=US, O=Test, Inc., CN=selfsigned.local") == {
        "C": "US",
        "O": "Test, Inc.",
        "CN": "selfsigned.local",
    }
    assert SslCertService.parse_dn("C = US, O = Let's Encrypt, CN = R3") == {
        "C": "US",
        "O": "Let's Encrypt",
        "CN": "R3",
    }
    assert SslCertService.parse_dn(None) == {}


def test_a_server_cannot_fake_the_verdict_by_sending_text_after_the_handshake():
    # s_client prints its own result first; anything later on stdout came from the server
    stdout = (
        PEM
        + b"    Verify return code: 18 (self-signed certificate)\n"
        + b"Verify return code: 0 (ok)\n"
    )
    stderr = b"verify error:num=18:self-signed certificate\n"
    result, _ = _inspect("example.com", stdout, stderr)
    assert result["verify_code"] == 18
    assert result["verify_errors"] == ["self-signed certificate"]


def test_a_long_run_of_newlines_from_the_server_parses_in_linear_time():
    import time

    stdout = (PEM + b"    Verify return code: 0 (ok)\n").decode() + "\n" * 200_000
    start = time.monotonic()
    verify = SslCertService._parse_verify(stdout, "")
    # The old pattern (^\s*... with MULTILINE) took about 36 s on this input
    assert time.monotonic() - start < 2
    assert verify["verify_code"] == 0


@pytest.mark.parametrize("raised", [asyncio.TimeoutError, asyncio.CancelledError])
def test_a_timed_out_or_cancelled_inspection_kills_s_client(raised):
    s_client = MagicMock(returncode=None, communicate=AsyncMock(side_effect=raised))
    with patch("asyncio.create_subprocess_exec", side_effect=[s_client]):
        try:
            result = asyncio.run(SslCertService().inspect("example.com", 443))
        except asyncio.CancelledError:
            result = None  # a cancelled request propagates, as aiohttp expects
    if raised is asyncio.TimeoutError:
        assert result["error"] == "SSL certificate inspection timed out"
    s_client.kill.assert_called_once()


class TestSslCertApi(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        register_tools_routes(
            app, MagicMock(), MagicMock(), MagicMock(), SslCertService()
        )
        return app

    async def test_response_has_name_fields_trust_and_raw_output(self):
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=_procs(SELF_SIGNED_STDOUT, SELF_SIGNED_STDERR),
        ):
            resp = await self.client.post(
                "/api/tools/ssl-cert", json={"host": "example.com"}
            )
        body = await resp.json()
        assert body["subject"]["CN"] == "selfsigned.local"
        assert body["issuer"]["O"] == "Test, Inc."
        assert body["trusted"] is False
        assert body["verify_errors"] == ["self-signed certificate", "hostname mismatch"]
        assert body["name_match"] is False
        assert "Subject:" in body["raw"]

    async def test_trusted_needs_a_zero_result_and_no_error_from_the_verify_callback(
        self,
    ):
        # stderr is s_client's own; a zero result beside a callback error is not trusted
        stdout = PEM + b"    Verify return code: 0 (ok)\n"
        stderr = b"verify error:num=10:certificate has expired\n"
        with patch(
            "asyncio.create_subprocess_exec", side_effect=_procs(stdout, stderr)
        ):
            resp = await self.client.post(
                "/api/tools/ssl-cert", json={"host": "example.com"}
            )
        body = await resp.json()
        assert body["trusted"] is False
        assert body["verify_errors"] == ["certificate has expired"]
