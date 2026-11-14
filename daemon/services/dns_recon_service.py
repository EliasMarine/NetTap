"""
NetTap DNS Reconnaissance Service

Runs structured DNS lookups via the `dig` command using asyncio subprocess.
Returns parsed records grouped by type (A, AAAA, CNAME, MX, NS, TXT, SOA, PTR, SRV).

Security:
    - Domain names validated against strict regex (no shell metacharacters)
    - Record types validated against an explicit whitelist
    - Commands run via asyncio.create_subprocess_exec (NEVER shell=True)
    - 10 second timeout per query; the queries of one lookup run at the same time (NET-203)
    - Record types deduplicated, so a lookup starts at most one dig per allowed type
    - Resolver compare (NET-262): resolvers are IP literals only, passed as dig's @server
"""

import asyncio
import contextlib
import ipaddress
import logging
import re
import time
from typing import Any

logger = logging.getLogger("nettap.dns_recon")

# --- Constants ---
ALLOWED_RECORD_TYPES = {"A", "AAAA", "CNAME", "MX", "NS", "TXT", "SOA", "PTR", "SRV"}
DEFAULT_RECORD_TYPES = ["A", "AAAA", "CNAME", "MX", "NS", "TXT", "SOA"]
DOMAIN_PATTERN = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-\.]*[a-zA-Z0-9])?$")
MAX_DOMAIN_LENGTH = 253
QUERY_TIMEOUT = 10  # seconds
# NET-203: each lookup starts up to 9 dig processes at once, so cap the lookups too
MAX_CONCURRENT_LOOKUPS = 4
LOOKUPS_BUSY = "DNS reconnaissance is busy. Try again in a moment."

# NET-262: resolver compare
MAX_COMPARE_RESOLVERS = 6
# Seconds dig waits for its one try: Quad9 from the G11 can take 2-4 s; stays under QUERY_TIMEOUT
COMPARE_DIG_TIME = 4
NO_REPLY = "No reply from NetTap"
# Answers kept per reply; a longer answer is cut and says so (truncated)
MAX_COMPARE_ANSWERS = 100
# dig names an unknown rcode RESERVED<n>
_STATUS = re.compile(r"->>HEADER<<-.*\bstatus: ([A-Z0-9]+),")
_QUERY_TIME = re.compile(r"^;; Query time: (\d+) msec", re.MULTILINE)
# The RDATA fields that are domain names; names compare case-insensitively (RFC 4343)
_NAME_FIELDS = {
    "CNAME": (0,),
    "NS": (0,),
    "PTR": (0,),
    "DNAME": (0,),
    "MX": (1,),
    "SRV": (3,),
    "SOA": (0, 1),
}


def _dns_name(name: str) -> str:
    return name.lower().rstrip(".")


def _answer_key(record: dict[str, Any]) -> str:
    """Owner, class, type and RDATA without the TTL: two answers are the same record when their keys
    are equal (NET-262). Names and addresses are normalised; TXT and other RDATA stay byte for byte."""
    rtype = str(record["type"]).upper()
    rdata = str(record["value"])
    if rtype in ("A", "AAAA"):
        with contextlib.suppress(ValueError):
            rdata = str(ipaddress.ip_address(rdata))
    elif rtype in _NAME_FIELDS:
        rdata = " ".join(
            _dns_name(field) if i in _NAME_FIELDS[rtype] else field
            for i, field in enumerate(rdata.split())
        )
    owner = _dns_name(str(record["name"]))
    return " ".join((owner, str(record["class"]).upper(), rtype, rdata))


def _scope(record: dict[str, Any]) -> dict[str, str]:
    """{"scope": ...} for an A or AAAA answer, else nothing. 0.0.0.0 and :: (a blocked name on
    Pi-hole and AdGuard) and loopback get their own scope, so they never read as a private answer."""
    if record["type"] not in ("A", "AAAA"):
        return {}
    try:
        address = ipaddress.ip_address(record["value"])
    except ValueError:
        return {}
    # OLD CODE: return {"scope": "public" if address.is_global else "private"} (0.0.0.0 read as private)
    if address.is_unspecified:
        return {"scope": "unspecified"}
    if address.is_loopback:
        return {"scope": "loopback"}
    return {"scope": "public" if address.is_global else "private"}


def _dig_failure(stdout: str, stderr: bytes, code: int) -> str:
    """dig's own reason for a failed query: its first ';;' or 'dig:' line, else its exit code."""
    text = stdout + "\n" + stderr.decode("utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith((";;", "dig:")):
            return line.lstrip("; ").strip()
    return f"dig exited with code {code}"


class DnsReconValidationError(Exception):
    """Raised when DNS recon input validation fails."""

    pass


class DnsReconBusyError(Exception):
    """Raised when MAX_CONCURRENT_LOOKUPS lookups are already running (NET-203)."""


class DnsReconService:
    """Performs structured DNS lookups via the dig command."""

    def __init__(self) -> None:
        # Rejects instead of queueing: a wait here would count against the web's 15 s limit
        self._slots = asyncio.Semaphore(MAX_CONCURRENT_LOOKUPS)

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

        validated: list[str] = []
        for rt in record_types:
            rt_upper = rt.strip().upper()
            if rt_upper not in ALLOWED_RECORD_TYPES:
                raise DnsReconValidationError(
                    f"Invalid record type: {rt_upper!r} — "
                    f"allowed: {', '.join(sorted(ALLOWED_RECORD_TYPES))}"
                )
            # NET-203: each type once, first occurrence first; the queries run at the same time,
            # so a repeated type would start another dig process
            if rt_upper not in validated:
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
                    records.append(
                        {
                            "name": parts[0],
                            "ttl": int(parts[1]) if parts[1].isdigit() else parts[1],
                            "class": parts[2],
                            "type": parts[3],
                            "value": parts[4],
                        }
                    )

        return records

    async def _query(
        self, domain: str, rtype: str
    ) -> tuple[list[dict[str, Any]], str | None]:
        """One dig query: its records, or no records and the reason (NET-203).

        A child still running when this ends (a timeout, an error, a cancelled lookup) is
        killed and reaped; a cancellation still propagates.
        """
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "dig",
                "+noall",
                "+answer",
                "+authority",
                "+comments",
                # a slow resolver is retried after 2 s, twice, so dig gives up (8 s over two
                # servers) inside QUERY_TIMEOUT instead of after its default 5 s x 3 tries
                "+time=2",
                "+tries=2",
                # OLD CODE START — NET-268: bare `dig ns A` read the name "ns" as a type
                # domain,
                # rtype,
                # OLD CODE END
                # -q/-t: a name that is also a type or class word ("ns", "mx") stays the name
                "-q",
                domain,
                "-t",
                rtype,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=QUERY_TIMEOUT
            )
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            if proc.returncode != 0:
                reason = _dig_failure(stdout, stderr_bytes, proc.returncode)
                logger.warning("dig failed for %s %s: %s", domain, rtype, reason)
                return [], f"{rtype}: {reason}"
            return self._parse_dig_output(stdout), None
        except asyncio.TimeoutError:
            logger.warning("dig query timed out for %s %s", domain, rtype)
            return [], f"Timeout querying {rtype} records"
        except Exception as exc:
            logger.exception("dig query failed for %s %s", domain, rtype)
            return [], f"Error querying {rtype}: {exc}"
        finally:
            if proc is not None and proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()

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

        # OLD CODE START — NET-203: one dig after another, so 7 types took up to 70 s and the web
        # proxy (10 s) said "Daemon unreachable"; a failed dig read as an empty answer
        # all_records: dict[str, list[dict]] = {}
        # errors: list[str] = []
        #
        # for rtype in record_types:
        #     try:
        #         proc = await asyncio.create_subprocess_exec(
        #             "dig",
        #             "+noall",
        #             "+answer",
        #             "+authority",
        #             "+comments",
        #             domain,
        #             rtype,
        #             stdout=asyncio.subprocess.PIPE,
        #             stderr=asyncio.subprocess.PIPE,
        #         )
        #         stdout_bytes, stderr_bytes = await asyncio.wait_for(
        #             proc.communicate(), timeout=QUERY_TIMEOUT
        #         )
        #         stdout = stdout_bytes.decode("utf-8", errors="replace")
        #         parsed = self._parse_dig_output(stdout)
        #         if parsed:
        #             all_records[rtype] = parsed
        #
        #     except asyncio.TimeoutError:
        #         logger.warning("dig query timed out for %s %s", domain, rtype)
        #         errors.append(f"Timeout querying {rtype} records")
        #         try:
        #             proc.kill()  # type: ignore[possibly-undefined]
        #         except ProcessLookupError:
        #             pass
        #
        #     except Exception as exc:
        #         logger.exception("dig query failed for %s %s", domain, rtype)
        #         errors.append(f"Error querying {rtype}: {exc}")
        # OLD CODE END
        if self._slots.locked():  # checked first, so acquiring below never waits
            raise DnsReconBusyError(LOOKUPS_BUSY)
        async with self._slots:
            results = await asyncio.gather(
                *(self._query(domain, rtype) for rtype in record_types)
            )
        all_records = {
            rtype: records
            for rtype, (records, _) in zip(record_types, results)
            if records
        }
        errors = [error for _, error in results if error]

        total = sum(len(recs) for recs in all_records.values())

        return {
            "domain": domain,
            "records": all_records,
            "total_records": total,
            "record_types_queried": record_types,
            "errors": errors,
        }

    # -- Resolver compare (NET-262) -------------------------------------------------------------

    def validate_resolvers(self, resolvers: Any) -> list[str]:
        """1 to MAX_COMPARE_RESOLVERS IP literals (v4 or v6, no scope id), normalised, each once."""
        if not isinstance(resolvers, list) or not resolvers:
            raise DnsReconValidationError("Add at least one resolver IP address.")
        if len(resolvers) > MAX_COMPARE_RESOLVERS:
            raise DnsReconValidationError(
                f"Compare at most {MAX_COMPARE_RESOLVERS} resolvers at a time."
            )
        validated: list[str] = []
        for raw in resolvers:
            text = raw.strip() if isinstance(raw, str) else ""
            try:
                if "%" in text:  # a scoped link-local address names an interface
                    raise ValueError(text)
                address = str(ipaddress.ip_address(text))
            except ValueError:
                raise DnsReconValidationError(
                    f"Resolver {raw!r} is not an IP address."
                ) from None
            if address not in validated:
                validated.append(address)
        return validated

    async def _ask(self, resolver: str, name: str, rtype: str) -> dict[str, Any]:
        """One resolver's reply (NET-262). A child still running when this ends is killed and reaped."""
        reply: dict[str, Any] = {
            "resolver": resolver,
            "status": None,
            "answers": [],
            "ttl": None,
            "latency_ms": None,
            "error": None,
            "truncated": False,
        }
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "dig",
                f"@{resolver}",
                "+noall",
                "+answer",
                "+comments",
                "+stats",
                # OLD CODE: "+time=2", (a Quad9 reply in 2-4 s read as "did not reply")
                f"+time={COMPARE_DIG_TIME}",
                "+tries=1",
                "-t",
                rtype,
                # -q: a name that is also a type or class word ("ns", "mx") stays the name
                "-q",
                name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=QUERY_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.warning("dig @%s timed out for %s %s", resolver, name, rtype)
            return {**reply, "error": NO_REPLY}
        except Exception:
            logger.exception("dig @%s could not run for %s %s", resolver, name, rtype)
            return {**reply, "error": "dig could not run"}
        finally:
            if proc is not None and proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        status = _STATUS.search(stdout)
        if status is None:
            reason = _dig_failure(stdout, stderr_bytes, proc.returncode)
            logger.warning(
                "dig @%s failed for %s %s: %s", resolver, name, rtype, reason
            )
            # dig exits 9 when no reply came back
            no_reply = (
                proc.returncode == 9
                or "timed out" in stdout
                or "no servers could be reached" in stdout
            )
            return {**reply, "error": NO_REPLY if no_reply else reason}
        answers = [
            {**record, "key": _answer_key(record), **_scope(record)}
            for record in self._parse_dig_output(stdout)
        ]
        truncated = len(answers) > MAX_COMPARE_ANSWERS
        if truncated:
            # sorted first, so two resolvers with the same records keep the same 100
            answers = sorted(answers, key=lambda a: a["key"])[:MAX_COMPARE_ANSWERS]
        ttls = [a["ttl"] for a in answers if isinstance(a["ttl"], int)]
        latency = _QUERY_TIME.search(stdout)
        return {
            **reply,
            "status": status.group(1),
            "answers": answers,
            "ttl": min(ttls, default=None),
            "latency_ms": int(latency.group(1)) if latency else None,
            "truncated": truncated,
        }

    async def compare(
        self, name: Any, record_type: Any, resolvers: Any
    ) -> dict[str, Any]:
        """Ask each resolver the same question at the same time (NET-262).

        Returns {name, record_type,
        results: [{resolver, status, answers, ttl, latency_ms, error, truncated}]}.
        """
        name = self.validate_domain(name if isinstance(name, str) else "")
        # OLD CODE: if not record_type: (0, [] and {} also meant A)
        if record_type is None or record_type == "":
            record_type = "A"
        if not isinstance(record_type, str):
            raise DnsReconValidationError("Record type must be text, such as A or MX.")
        rtype = self.validate_record_types([record_type])[0]
        resolvers = self.validate_resolvers(resolvers)

        if self._slots.locked():  # checked first, so acquiring below never waits
            raise DnsReconBusyError(LOOKUPS_BUSY)
        started = time.monotonic()
        async with self._slots:
            results = await asyncio.gather(
                *(self._ask(resolver, name, rtype) for resolver in resolvers)
            )
        logger.info(
            "DNS compare %s %s via %s: %s in %.1f s",
            name,
            rtype,
            ", ".join(resolvers),
            ", ".join(str(r["status"] or r["error"]) for r in results),
            time.monotonic() - started,
        )
        return {"name": name, "record_type": rtype, "results": results}
