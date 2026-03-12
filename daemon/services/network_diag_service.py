"""
NetTap Network Diagnostics Service

Runs ping and traceroute commands via asyncio subprocess for on-demand
network troubleshooting from the web dashboard.

Security:
    - Targets validated against strict regex (no shell metacharacters)
    - Count and max_hops clamped to safe ranges
    - Commands run via asyncio.create_subprocess_exec (NEVER shell=True)
    - Execution timeouts enforced
"""

import asyncio
import logging
import re
from typing import Any

logger = logging.getLogger("nettap.network_diag")

# --- Constants ---
TARGET_PATTERN = re.compile(r"^[a-zA-Z0-9.\-:]+$")
MAX_TARGET_LENGTH = 253
PING_TIMEOUT = 15  # seconds
TRACEROUTE_TIMEOUT = 30  # seconds
MIN_COUNT = 1
MAX_COUNT = 10
MIN_HOPS = 1
MAX_HOPS = 30


class NetworkDiagValidationError(Exception):
    """Raised when network diagnostic input validation fails."""
    pass


class NetworkDiagService:
    """Runs ping and traceroute commands for network diagnostics."""

    def validate_target(self, target: str) -> str:
        """Validate a ping/traceroute target (hostname or IP).

        Raises NetworkDiagValidationError on invalid input.
        """
        if not target:
            raise NetworkDiagValidationError("Target is required")

        target = target.strip()

        if len(target) > MAX_TARGET_LENGTH:
            raise NetworkDiagValidationError(
                f"Target too long (max {MAX_TARGET_LENGTH} chars)"
            )

        if not TARGET_PATTERN.match(target):
            raise NetworkDiagValidationError(
                f"Invalid target: {target!r} — only alphanumeric, dots, hyphens, and colons allowed"
            )

        return target

    def validate_count(self, count: int | None) -> int:
        """Validate and clamp ping count to safe range [1, 10]."""
        if count is None:
            return 4  # default
        return max(MIN_COUNT, min(MAX_COUNT, int(count)))

    def validate_max_hops(self, max_hops: int | None) -> int:
        """Validate and clamp traceroute max_hops to safe range [1, 30]."""
        if max_hops is None:
            return 30  # default
        return max(MIN_HOPS, min(MAX_HOPS, int(max_hops)))

    def _parse_ping_output(self, stdout: str) -> dict[str, Any]:
        """Parse Linux ping output for replies and RTT statistics."""
        lines = stdout.strip().split("\n")
        replies = []
        stats: dict[str, Any] = {}

        for line in lines:
            # Match reply lines: "64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=12.3 ms"
            reply_match = re.match(
                r"(\d+) bytes from ([^:]+): icmp_seq=(\d+) ttl=(\d+) time=([0-9.]+) ms",
                line.strip(),
            )
            if reply_match:
                replies.append({
                    "bytes": int(reply_match.group(1)),
                    "from": reply_match.group(2),
                    "icmp_seq": int(reply_match.group(3)),
                    "ttl": int(reply_match.group(4)),
                    "time_ms": float(reply_match.group(5)),
                })
                continue

            # Match packet loss line: "4 packets transmitted, 4 received, 0% packet loss, ..."
            loss_match = re.match(
                r"(\d+) packets transmitted, (\d+) received.*?(\d+)% packet loss",
                line.strip(),
            )
            if loss_match:
                stats["packets_transmitted"] = int(loss_match.group(1))
                stats["packets_received"] = int(loss_match.group(2))
                stats["packet_loss_percent"] = int(loss_match.group(3))
                continue

            # Match RTT line: "rtt min/avg/max/mdev = 11.123/12.456/13.789/0.543 ms"
            rtt_match = re.match(
                r"rtt min/avg/max/mdev = ([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+) ms",
                line.strip(),
            )
            if rtt_match:
                stats["rtt_min_ms"] = float(rtt_match.group(1))
                stats["rtt_avg_ms"] = float(rtt_match.group(2))
                stats["rtt_max_ms"] = float(rtt_match.group(3))
                stats["rtt_mdev_ms"] = float(rtt_match.group(4))

        return {"replies": replies, "stats": stats}

    def _parse_traceroute_output(self, stdout: str) -> list[dict[str, Any]]:
        """Parse traceroute output into structured hop list."""
        lines = stdout.strip().split("\n")
        hops = []

        for line in lines:
            stripped = line.strip()

            # Skip header line: "traceroute to example.com (93.184.216.34), 30 hops max, ..."
            if stripped.startswith("traceroute to "):
                continue

            # Match hop lines: " 1  gateway (10.0.0.1)  1.234 ms  1.345 ms  1.456 ms"
            # or " 2  * * *"
            hop_match = re.match(r"\s*(\d+)\s+(.*)", stripped)
            if not hop_match:
                continue

            hop_num = int(hop_match.group(1))
            rest = hop_match.group(2)

            if rest.strip() == "* * *":
                hops.append({
                    "hop": hop_num,
                    "host": "*",
                    "ip": None,
                    "rtt_ms": [],
                })
                continue

            # Extract host, IP, and RTT values
            host = None
            ip = None
            rtts = []

            # Match host with IP: "gateway (10.0.0.1)"
            host_match = re.match(r"([^\s(]+)\s+\(([^)]+)\)", rest)
            if host_match:
                host = host_match.group(1)
                ip = host_match.group(2)

            # Extract RTT values (e.g., "1.234 ms")
            rtt_matches = re.findall(r"([0-9.]+)\s+ms", rest)
            rtts = [float(r) for r in rtt_matches]

            hops.append({
                "hop": hop_num,
                "host": host or "*",
                "ip": ip,
                "rtt_ms": rtts,
            })

        return hops

    async def ping(
        self,
        target: str,
        count: int | None = None,
    ) -> dict[str, Any]:
        """Run ping against the target.

        Returns {target, count, output, replies, stats, error}.
        """
        target = self.validate_target(target)
        count = self.validate_count(count)

        try:
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", str(count), "-W", "3", target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=PING_TIMEOUT
            )
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            parsed = self._parse_ping_output(stdout)

            return {
                "target": target,
                "count": count,
                "output": stdout,
                "replies": parsed["replies"],
                "stats": parsed["stats"],
                "error": None,
            }

        except asyncio.TimeoutError:
            logger.warning("ping timed out for %s", target)
            try:
                proc.kill()  # type: ignore[possibly-undefined]
            except ProcessLookupError:
                pass
            return {
                "target": target,
                "count": count,
                "output": "",
                "replies": [],
                "stats": {},
                "error": "Ping timed out",
            }

        except Exception as exc:
            logger.exception("ping failed for %s", target)
            return {
                "target": target,
                "count": count,
                "output": "",
                "replies": [],
                "stats": {},
                "error": f"Ping failed: {exc}",
            }

    async def traceroute(
        self,
        target: str,
        max_hops: int | None = None,
    ) -> dict[str, Any]:
        """Run traceroute against the target.

        Returns {target, max_hops, output, hops, error}.
        """
        target = self.validate_target(target)
        max_hops = self.validate_max_hops(max_hops)

        try:
            proc = await asyncio.create_subprocess_exec(
                "traceroute", "-m", str(max_hops), "-w", "3", target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=TRACEROUTE_TIMEOUT
            )
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            hops = self._parse_traceroute_output(stdout)

            return {
                "target": target,
                "max_hops": max_hops,
                "output": stdout,
                "hops": hops,
                "error": None,
            }

        except asyncio.TimeoutError:
            logger.warning("traceroute timed out for %s", target)
            try:
                proc.kill()  # type: ignore[possibly-undefined]
            except ProcessLookupError:
                pass
            return {
                "target": target,
                "max_hops": max_hops,
                "output": "",
                "hops": [],
                "error": "Traceroute timed out",
            }

        except Exception as exc:
            logger.exception("traceroute failed for %s", target)
            return {
                "target": target,
                "max_hops": max_hops,
                "output": "",
                "hops": [],
                "error": f"Traceroute failed: {exc}",
            }
