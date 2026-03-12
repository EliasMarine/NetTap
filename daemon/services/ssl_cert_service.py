"""
NetTap SSL Certificate Inspection Service

Connects to a remote host via openssl s_client to retrieve and parse
TLS certificate details including subject, issuer, validity dates,
serial number, SHA-256 fingerprint, SANs, and certificate chain info.

Security:
    - Host validated against strict regex (no shell metacharacters)
    - Port validated to 1-65535 range
    - Commands run via asyncio.create_subprocess_exec (NEVER shell=True)
    - 10 second timeout
"""

import asyncio
import logging
import re
from typing import Any

logger = logging.getLogger("nettap.ssl_cert")

# --- Constants ---
HOST_PATTERN = re.compile(r"^[a-zA-Z0-9.\-:]+$")
MAX_HOST_LENGTH = 253
CERT_TIMEOUT = 10  # seconds


class SslCertValidationError(Exception):
    """Raised when SSL certificate input validation fails."""
    pass


class SslCertService:
    """Inspects SSL/TLS certificates on remote hosts via openssl."""

    def validate_host(self, host: str) -> str:
        """Validate a hostname or IP for SSL inspection.

        Raises SslCertValidationError on invalid input.
        """
        if not host:
            raise SslCertValidationError("Host is required")

        host = host.strip()

        if len(host) > MAX_HOST_LENGTH:
            raise SslCertValidationError(
                f"Host too long (max {MAX_HOST_LENGTH} chars)"
            )

        if not HOST_PATTERN.match(host):
            raise SslCertValidationError(
                f"Invalid host: {host!r} — only alphanumeric, dots, hyphens, and colons allowed"
            )

        return host

    def validate_port(self, port: int | None) -> int:
        """Validate port number (1-65535, default 443).

        Raises SslCertValidationError on invalid port.
        """
        if port is None:
            return 443

        port = int(port)
        if port < 1 or port > 65535:
            raise SslCertValidationError(
                f"Invalid port: {port} — must be between 1 and 65535"
            )

        return port

    def _parse_cert_text(self, text: str) -> dict[str, Any]:
        """Parse openssl x509 -text output for certificate details."""
        result: dict[str, Any] = {}

        # Subject
        subject_match = re.search(r"Subject:\s*(.+)", text)
        if subject_match:
            result["subject"] = subject_match.group(1).strip()

        # Issuer
        issuer_match = re.search(r"Issuer:\s*(.+)", text)
        if issuer_match:
            result["issuer"] = issuer_match.group(1).strip()

        # Validity dates (from -dates output)
        not_before_match = re.search(r"notBefore=(.+)", text)
        if not_before_match:
            result["not_before"] = not_before_match.group(1).strip()

        not_after_match = re.search(r"notAfter=(.+)", text)
        if not_after_match:
            result["not_after"] = not_after_match.group(1).strip()

        # Serial
        serial_match = re.search(r"serial=([0-9A-Fa-f]+)", text)
        if serial_match:
            result["serial"] = serial_match.group(1).strip()

        # SHA-256 Fingerprint
        fp_match = re.search(r"sha256 Fingerprint=(.+)", text, re.IGNORECASE)
        if fp_match:
            result["fingerprint_sha256"] = fp_match.group(1).strip()

        # Subject Alternative Names
        sans = []
        san_match = re.search(
            r"X509v3 Subject Alternative Name:\s*\n\s*(.+)", text
        )
        if san_match:
            san_line = san_match.group(1).strip()
            for entry in san_line.split(","):
                entry = entry.strip()
                if entry.startswith("DNS:"):
                    sans.append(entry[4:])
                elif entry.startswith("IP Address:"):
                    sans.append(entry[11:])
                else:
                    sans.append(entry)
        result["sans"] = sans

        return result

    def _parse_chain(self, s_client_output: str) -> list[dict[str, str]]:
        """Parse certificate chain from openssl s_client output."""
        chain = []
        # Match: " 0 s:CN = example.com" / " i:C = US, O = Let's Encrypt, CN = R3"
        chain_pattern = re.compile(
            r"^\s*(\d+)\s+s:(.+?)$\n\s*i:(.+?)$",
            re.MULTILINE,
        )
        for match in chain_pattern.finditer(s_client_output):
            chain.append({
                "depth": int(match.group(1)),
                "subject": match.group(2).strip(),
                "issuer": match.group(3).strip(),
            })
        return chain

    async def inspect(
        self,
        host: str,
        port: int | None = None,
    ) -> dict[str, Any]:
        """Inspect the SSL/TLS certificate on a remote host.

        Returns {host, port, subject, issuer, not_before, not_after, serial,
                 fingerprint_sha256, sans, chain, error}.
        """
        host = self.validate_host(host)
        port = self.validate_port(port)

        try:
            # Step 1: Get the PEM certificate and chain info via s_client
            s_client_proc = await asyncio.create_subprocess_exec(
                "openssl", "s_client",
                "-connect", f"{host}:{port}",
                "-servername", host,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            s_client_stdout, s_client_stderr = await asyncio.wait_for(
                s_client_proc.communicate(input=b""),
                timeout=CERT_TIMEOUT,
            )
            s_client_output = s_client_stdout.decode("utf-8", errors="replace")

            # Extract PEM certificate
            pem_match = re.search(
                r"(-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----)",
                s_client_output,
                re.DOTALL,
            )
            if not pem_match:
                return {
                    "host": host,
                    "port": port,
                    "error": "No certificate received from server",
                }

            pem_cert = pem_match.group(1)

            # Parse chain from s_client output
            chain = self._parse_chain(s_client_output)

            # Step 2: Parse the PEM certificate with openssl x509
            x509_proc = await asyncio.create_subprocess_exec(
                "openssl", "x509",
                "-noout", "-subject", "-issuer", "-dates",
                "-serial", "-fingerprint", "-sha256", "-text",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            x509_stdout, x509_stderr = await asyncio.wait_for(
                x509_proc.communicate(input=pem_cert.encode()),
                timeout=CERT_TIMEOUT,
            )
            x509_output = x509_stdout.decode("utf-8", errors="replace")

            parsed = self._parse_cert_text(x509_output)

            return {
                "host": host,
                "port": port,
                "subject": parsed.get("subject"),
                "issuer": parsed.get("issuer"),
                "not_before": parsed.get("not_before"),
                "not_after": parsed.get("not_after"),
                "serial": parsed.get("serial"),
                "fingerprint_sha256": parsed.get("fingerprint_sha256"),
                "sans": parsed.get("sans", []),
                "chain": chain,
                "error": None,
            }

        except asyncio.TimeoutError:
            logger.warning("SSL inspection timed out for %s:%d", host, port)
            return {
                "host": host,
                "port": port,
                "error": "SSL certificate inspection timed out",
            }

        except Exception as exc:
            logger.exception("SSL inspection failed for %s:%d", host, port)
            return {
                "host": host,
                "port": port,
                "error": f"SSL inspection failed: {exc}",
            }
