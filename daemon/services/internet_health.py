"""
Internet Health Monitor for NetTap.

Monitors internet connectivity health by tracking latency, DNS resolution
time, and packet loss via async subprocess calls to system ping and DNS
resolution via socket.getaddrinfo.

Provides rolling history, status determination (healthy/degraded/down),
and aggregate statistics over the monitoring window.
"""

import asyncio
import logging
import re
import socket
import statistics
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

logger = logging.getLogger("nettap.internet_health")


@dataclass
class HealthCheck:
    """Result of a single health check cycle."""

    timestamp: str  # ISO format
    latency_ms: float | None  # ping RTT in ms, None if unreachable
    dns_resolve_ms: float | None  # DNS lookup time in ms
    packet_loss_pct: float  # 0-100%
    status: str  # 'healthy', 'degraded', 'down'

    def to_dict(self) -> dict:
        return asdict(self)


class InternetHealthMonitor:
    """Monitors internet health via latency, DNS, and packet loss metrics.

    Runs asynchronous health checks against configurable ping and DNS
    targets, stores results in a bounded history buffer, and computes
    aggregate statistics for the monitoring window.
    """

    # Default targets for health checks
    DEFAULT_PING_TARGETS = ["8.8.8.8", "1.1.1.1", "208.67.222.222"]
    DEFAULT_DNS_TARGETS = ["google.com", "cloudflare.com", "example.com"]

    def __init__(
        self,
        ping_targets: list[str] | None = None,
        dns_targets: list[str] | None = None,
        history_size: int = 288,  # 24h at 5min intervals
    ):
        self._ping_targets = ping_targets or self.DEFAULT_PING_TARGETS
        self._dns_targets = dns_targets or self.DEFAULT_DNS_TARGETS
        self._history: list[HealthCheck] = []
        self._history_size = history_size

    async def check_latency(self, target: str, timeout: float = 5.0) -> float | None:
        """Ping a target and return RTT in ms, or None if unreachable.

        Uses asyncio subprocess to run 'ping -c 3 -W {timeout}'.
        Parses the avg RTT from ping output.
        """
        try:
            timeout_sec = str(int(timeout))
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", "3", "-W", timeout_sec, target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=timeout + 5
            )
            if proc.returncode != 0:
                return None

            output = stdout.decode("utf-8", errors="replace")
            # Parse avg from: rtt min/avg/max/mdev = 1.234/5.678/9.012/1.234 ms
            match = re.search(
                r"(?:rtt|round-trip)\s+min/avg/max/(?:mdev|stddev)\s*=\s*"
                r"[\d.]+/([\d.]+)/[\d.]+/[\d.]+",
                output,
            )
            if match:
                return float(match.group(1))
            return None
        except (asyncio.TimeoutError, OSError) as exc:
            logger.debug("Latency check to %s failed: %s", target, exc)
            return None

    async def check_dns(self, domain: str, timeout: float = 5.0) -> float | None:
        """Resolve a domain and return resolution time in ms, or None if failed.

        Uses socket.getaddrinfo wrapped in asyncio.to_thread for
        non-blocking resolution.
        """
        try:
            loop = asyncio.get_running_loop()
            start = time.monotonic()
            await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: socket.getaddrinfo(domain, 80, socket.AF_INET),
                ),
                timeout=timeout,
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            return round(elapsed_ms, 2)
        except (asyncio.TimeoutError, socket.gaierror, OSError) as exc:
            logger.debug("DNS check for %s failed: %s", domain, exc)
            return None

    async def check_packet_loss(
        self, target: str, count: int = 10, timeout: float = 10.0
    ) -> float:
        """Send multiple pings and return packet loss percentage (0-100).

        Uses asyncio subprocess to run 'ping -c {count} -W {timeout}'.
        Parses the loss percentage from ping summary output.
        """
        try:
            timeout_sec = str(int(timeout))
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", str(count), "-W", timeout_sec, target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=timeout + 10
            )

            output = stdout.decode("utf-8", errors="replace")
            # Parse: "3 packets transmitted, 2 received, 33.3333% packet loss"
            match = re.search(r"([\d.]+)%\s+packet\s+loss", output)
            if match:
                return float(match.group(1))
            # If ping completely failed (returncode != 0 and no parse), 100% loss
            if proc.returncode != 0:
                return 100.0
            return 0.0
        except (asyncio.TimeoutError, OSError) as exc:
            logger.debug("Packet loss check to %s failed: %s", target, exc)
            return 100.0

    def _determine_status(
        self,
        latency: float | None,
        dns: float | None,
        packet_loss: float,
    ) -> str:
        """Determine health status from check results.

        - 'down': latency is None AND dns is None, OR loss >= 50%
        - 'degraded': latency >= 100ms, OR dns >= 500ms, OR loss >= 5%
        - 'healthy': latency < 100ms, dns < 500ms, loss < 5%
        """
        # Down conditions
        if (latency is None and dns is None) or packet_loss >= 50:
            return "down"

        # Degraded conditions
        if latency is not None and latency >= 100:
            return "degraded"
        if dns is not None and dns >= 500:
            return "degraded"
        if packet_loss >= 5:
            return "degraded"
        # One metric missing but the other is OK => degraded
        if latency is None or dns is None:
            return "degraded"

        return "healthy"

    async def run_check(self) -> HealthCheck:
        """Run a complete health check cycle.

        1. Ping all targets concurrently, take median latency
        2. DNS resolve all targets concurrently, take median time
        3. Packet loss check on first ping target
        4. Determine status
        5. Store in history (bounded by history_size)
        """
        # Latency checks (concurrent)
        latency_tasks = [
            self.check_latency(t) for t in self._ping_targets
        ]
        latency_results = await asyncio.gather(*latency_tasks)
        valid_latencies = [r for r in latency_results if r is not None]
        median_latency = (
            round(statistics.median(valid_latencies), 2)
            if valid_latencies
            else None
        )

        # DNS checks (concurrent)
        dns_tasks = [self.check_dns(d) for d in self._dns_targets]
        dns_results = await asyncio.gather(*dns_tasks)
        valid_dns = [r for r in dns_results if r is not None]
        median_dns = (
            round(statistics.median(valid_dns), 2) if valid_dns else None
        )

        # Packet loss check
        packet_loss = await self.check_packet_loss(self._ping_targets[0])

        # Determine status
        status = self._determine_status(median_latency, median_dns, packet_loss)

        check = HealthCheck(
            timestamp=datetime.now(timezone.utc).isoformat(),
            latency_ms=median_latency,
            dns_resolve_ms=median_dns,
            packet_loss_pct=round(packet_loss, 2),
            status=status,
        )

        # Store in history with size limit
        self._history.append(check)
        if len(self._history) > self._history_size:
            self._history = self._history[-self._history_size:]

        return check

    def get_current_status(self) -> dict:
        """Return most recent health check result, or a default if none."""
        if not self._history:
            return {
                "timestamp": None,
                "latency_ms": None,
                "dns_resolve_ms": None,
                "packet_loss_pct": None,
                "status": "unknown",
            }
        return self._history[-1].to_dict()

    def get_history(self, limit: int = 288) -> list[dict]:
        """Return recent health check history, newest first."""
        entries = self._history[-limit:]
        return [h.to_dict() for h in reversed(entries)]

    def get_statistics(self) -> dict:
        """Compute statistics over the current history buffer.

        Returns a dict with avg/p95/min/max latency, avg DNS time,
        avg packet loss, uptime percentage, total check count, and
        the time span of the history in hours.
        """
        if not self._history:
            return {
                "avg_latency_ms": None,
                "p95_latency_ms": None,
                "min_latency_ms": None,
                "max_latency_ms": None,
                "avg_dns_ms": None,
                "avg_packet_loss_pct": None,
                "uptime_pct": None,
                "total_checks": 0,
                "history_span_hours": 0,
            }

        latencies = [
            h.latency_ms for h in self._history if h.latency_ms is not None
        ]
        dns_times = [
            h.dns_resolve_ms for h in self._history if h.dns_resolve_ms is not None
        ]
        losses = [h.packet_loss_pct for h in self._history]

        # Uptime = percentage of checks that are NOT 'down'
        non_down = sum(1 for h in self._history if h.status != "down")
        uptime_pct = round((non_down / len(self._history)) * 100, 2)

        # History span in hours
        try:
            first_ts = datetime.fromisoformat(self._history[0].timestamp)
            last_ts = datetime.fromisoformat(self._history[-1].timestamp)
            span_hours = round(
                (last_ts - first_ts).total_seconds() / 3600, 2
            )
        except (ValueError, TypeError):
            span_hours = 0

        return {
            "avg_latency_ms": (
                round(statistics.mean(latencies), 2) if latencies else None
            ),
            "p95_latency_ms": (
                round(
                    sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0,
                    2,
                )
                if latencies
                else None
            ),
            "min_latency_ms": (
                round(min(latencies), 2) if latencies else None
            ),
            "max_latency_ms": (
                round(max(latencies), 2) if latencies else None
            ),
            "avg_dns_ms": (
                round(statistics.mean(dns_times), 2) if dns_times else None
            ),
            "avg_packet_loss_pct": round(statistics.mean(losses), 2),
            "uptime_pct": uptime_pct,
            "total_checks": len(self._history),
            "history_span_hours": span_hours,
        }
