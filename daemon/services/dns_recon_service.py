"""
NetTap DNS Reconnaissance Service

Runs structured DNS lookups via the `dig` command using asyncio subprocess.
Returns parsed records grouped by type (A, AAAA, CNAME, MX, NS, TXT, SOA, PTR, SRV).

Security:
    - Domain names validated against strict regex (no shell metacharacters)
    - Record types validated against an explicit whitelist
    - Commands run via asyncio.create_subprocess_exec (NEVER shell=True)
    - 10 second timeout per query
"""

import asyncio
import logging
import re
from typing import Any

logger = logging.getLogger("nettap.dns_recon")

# --- Constants ---
ALLOWED_RECORD_TYPES = {"A", "AAAA", "CNAME", "MX", "NS", "TXT", "SOA", "PTR", "SRV"}
DEFAULT_RECORD_TYPES = ["A", "AAAA", "CNAME", "MX", "NS", "TXT", "SOA"]
DOMAIN_PATTERN = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-\.]*[a-zA-Z0-9])?$")
MAX_DOMAIN_LENGTH = 253
QUERY_TIMEOUT = 10  # seconds


class DnsReconValidationError(Exception):
    """Raised when DNS recon input validation fails."""
    pass


class DnsReconService:
    """Performs structured DNS lookups via the dig command."""

    def validate_domain(self, domain: str) -> str:
        """Validate and normalize a domain name.

        Raises DnsReconValidationError on invalid input.
        """
        if not domain:
            raise DnsReconValidationError("Domain name is required")

        domain = domain.strip().lower()

        if len(domain) > MAX_DOMAIN_LENGTH:
            raise DnsReconValidationError(
                f"Domain name too long (max {MAX_DOMAIN_LENGTH} chars)"
            )

        if not DOMAIN_PATTERN.match(domain):
            raise DnsReconValidationError(
                f"Invalid domain name: {domain!r} — only alphanumeric, hyphens, and dots allowed"
            )

        return domain

    def validate_record_types(self, record_types: list[str] | None) -> list[str]:
        """Validate and normalize record types against the whitelist.

        Returns DEFAULT_RECORD_TYPES if none provided.
        Raises DnsReconValidationError on invalid types.
        """
        if not record_types:
            return list(DEFAULT_RECORD_TYPES)

        validated = []
        for rt in record_types:
            rt_upper = rt.strip().upper()
            if rt_upper not in ALLOWED_RECORD_TYPES:
                raise DnsReconValidationError(
                    f"Invalid record type: {rt_upper!r} — "
                    f"allowed: {', '.join(sorted(ALLOWED_RECORD_TYPES))}"
                )
            validated.append(rt_upper)

        return validated

    def _parse_dig_output(self, stdout: str) -> list[dict[str, Any]]:
        """Parse dig ANSWER SECTION lines into structured records.

        Each record is: {name, ttl, class, type, value}
        """
        records = []
        in_answer = False

        for line in stdout.split("\n"):
            stripped = line.strip()

            # Detect ANSWER SECTION header
            if stripped == ";; ANSWER SECTION:":
                in_answer = True
                continue

            # End of section (blank line or next section header)
            if in_answer and (not stripped or stripped.startswith(";;")):
                in_answer = False
                continue

            if in_answer and stripped:
                parts = stripped.split(None, 4)
                if len(parts) >= 5:
                    records.append({
                        "name": parts[0],
                        "ttl": int(parts[1]) if parts[1].isdigit() else parts[1],
                        "class": parts[2],
                        "type": parts[3],
                        "value": parts[4],
                    })

        return records

    async def lookup(
        self,
        domain: str,
        record_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run DNS lookups for the given domain and record types.

        Returns {domain, records, total_records, record_types_queried, errors}.
        """
        domain = self.validate_domain(domain)
        record_types = self.validate_record_types(record_types)

        all_records: dict[str, list[dict]] = {}
        errors: list[str] = []

        for rtype in record_types:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "dig", "+noall", "+answer", "+authority", "+comments",
                    domain, rtype,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=QUERY_TIMEOUT
                )
                stdout = stdout_bytes.decode("utf-8", errors="replace")
                parsed = self._parse_dig_output(stdout)
                if parsed:
                    all_records[rtype] = parsed

            except asyncio.TimeoutError:
                logger.warning("dig query timed out for %s %s", domain, rtype)
                errors.append(f"Timeout querying {rtype} records")
                try:
                    proc.kill()  # type: ignore[possibly-undefined]
                except ProcessLookupError:
                    pass

            except Exception as exc:
                logger.exception("dig query failed for %s %s", domain, rtype)
                errors.append(f"Error querying {rtype}: {exc}")

        total = sum(len(recs) for recs in all_records.values())

        return {
            "domain": domain,
            "records": all_records,
            "total_records": total,
            "record_types_queried": record_types,
            "errors": errors,
        }
