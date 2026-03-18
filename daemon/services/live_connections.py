"""
NetTap Live Connection Tracker

Tracks active connections in memory (last 10,000, rotating oldest)
and provides connection rate calculation over a sliding window.
Queries OpenSearch arkime_sessions3-* for recent connection events.
"""

import logging
import os
import time
from collections import deque
from datetime import datetime
from typing import Any

from opensearchpy import OpenSearch, OpenSearchException

logger = logging.getLogger("nettap.services.live_connections")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# Maximum connections to hold in memory
MAX_CONNECTIONS = 10_000

# Rate calculation window in seconds
RATE_WINDOW_SECONDS = 60


class LiveConnectionTracker:
    """Tracks active connections from OpenSearch with in-memory caching."""

    def __init__(self, client: OpenSearch | None = None) -> None:
        self._client = client
        self._connections: deque[dict[str, Any]] = deque(maxlen=MAX_CONNECTIONS)
        self._rate_timestamps: deque[float] = deque()
        self._last_fetch_time: str | None = None

    def set_client(self, client: OpenSearch) -> None:
        """Set the OpenSearch client (for deferred initialization)."""
        self._client = client

    def _record_rate(self, count: int) -> None:
        """Record connection fetch count for rate calculation."""
        now = time.monotonic()
        for _ in range(count):
            self._rate_timestamps.append(now)
        # Prune old timestamps outside the window
        cutoff = now - RATE_WINDOW_SECONDS
        while self._rate_timestamps and self._rate_timestamps[0] < cutoff:
            self._rate_timestamps.popleft()

    def get_connection_rate(self) -> dict[str, Any]:
        """Return current connections/sec over the last 60s window."""
        now = time.monotonic()
        cutoff = now - RATE_WINDOW_SECONDS
        while self._rate_timestamps and self._rate_timestamps[0] < cutoff:
            self._rate_timestamps.popleft()
        count = len(self._rate_timestamps)
        rate = count / RATE_WINDOW_SECONDS if RATE_WINDOW_SECONDS > 0 else 0
        return {
            "connections_per_second": round(rate, 2),
            "total_in_window": count,
            "window_seconds": RATE_WINDOW_SECONDS,
        }

    def get_active_connections(
        self,
        device: str | None = None,
        proto: str | None = None,
        country: str | None = None,
        port_min: int | None = None,
        port_max: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get active connections from the in-memory cache, with optional filters.

        Args:
            device: Filter by source or destination IP.
            proto: Filter by transport protocol (tcp, udp, icmp).
            country: Filter by GeoIP country code.
            port_min: Minimum destination port.
            port_max: Maximum destination port.
            limit: Max results to return.

        Returns:
            List of connection dicts, newest first.
        """
        results: list[dict[str, Any]] = []
        for conn in reversed(self._connections):
            if device:
                src_ip = conn.get("source_ip", "")
                dst_ip = conn.get("dest_ip", "")
                if device not in (src_ip, dst_ip):
                    continue
            if proto:
                if conn.get("protocol", "").lower() != proto.lower():
                    continue
            if country:
                if conn.get("country", "").upper() != country.upper():
                    continue
            if port_min is not None:
                dst_port = conn.get("dest_port", 0)
                if isinstance(dst_port, int) and dst_port < port_min:
                    continue
            if port_max is not None:
                dst_port = conn.get("dest_port", 0)
                if isinstance(dst_port, int) and dst_port > port_max:
                    continue
            results.append(conn)
            if len(results) >= limit:
                break
        return results

    def fetch_from_opensearch(
        self,
        device: str | None = None,
        proto: str | None = None,
        country: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch recent connections from OpenSearch and update in-memory cache.

        Args:
            device: Filter by source or destination IP.
            proto: Filter by transport protocol.
            country: Filter by GeoIP country code.
            limit: Max results to fetch.

        Returns:
            List of formatted connection dicts.
        """
        if not self._client:
            logger.warning("No OpenSearch client configured")
            return self.get_active_connections(device, proto, country, limit=limit)

        filters: list[dict] = [
            {"term": {"event.provider": "zeek"}},
            {"term": {"event.dataset": "conn"}},
        ]

        # Time filter: last 5 minutes for "active" connections
        filters.append({
            "range": {
                "@timestamp": {
                    "gte": "now-5m",
                    "lte": "now",
                }
            }
        })

        if device:
            filters.append({
                "bool": {
                    "should": [
                        {"term": {"source.ip.keyword": device}},
                        {"term": {"destination.ip.keyword": device}},
                    ],
                    "minimum_should_match": 1,
                }
            })

        if proto:
            filters.append({"term": {"network.transport.keyword": proto.lower()}})

        if country:
            filters.append({"term": {"destination.geo.country_iso_code.keyword": country.upper()}})

        query = {
            "size": min(limit, 500),
            "query": {"bool": {"filter": filters}},
            "sort": [{"@timestamp": {"order": "desc"}}],
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except OpenSearchException as exc:
            logger.error("OpenSearch error fetching live connections: %s", exc)
            return self.get_active_connections(device, proto, country, limit=limit)

        hits = result.get("hits", {}).get("hits", [])
        connections = []
        for hit in hits:
            src = hit.get("_source", {})
            conn = self._format_connection(src)
            connections.append(conn)
            self._connections.append(conn)

        self._record_rate(len(connections))
        return connections

    def _format_connection(self, source: dict[str, Any]) -> dict[str, Any]:
        """Format a raw OpenSearch hit _source into a clean connection dict."""
        # Extract nested fields safely
        src = source.get("source", {}) or {}
        dst = source.get("destination", {}) or {}
        client_bytes = source.get("client", {}) or {}
        server_bytes = source.get("server", {}) or {}
        network = source.get("network", {}) or {}
        event = source.get("event", {}) or {}
        geo = dst.get("geo", {}) or {}

        # Calculate bytes
        total_bytes = (
            (client_bytes.get("bytes", 0) or 0) +
            (server_bytes.get("bytes", 0) or 0)
        )
        if total_bytes == 0:
            total_bytes = (
                (src.get("bytes", 0) or 0) +
                (dst.get("bytes", 0) or 0)
            )

        # Calculate duration
        duration = 0.0
        event_start = event.get("start")
        event_end = event.get("end")
        if event_start and event_end:
            try:
                start_dt = datetime.fromisoformat(str(event_start).replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(str(event_end).replace("Z", "+00:00"))
                duration = (end_dt - start_dt).total_seconds()
            except (ValueError, TypeError):
                pass

        return {
            "timestamp": source.get("@timestamp", ""),
            "source_ip": src.get("ip", ""),
            "source_port": src.get("port", 0),
            "dest_ip": dst.get("ip", ""),
            "dest_port": dst.get("port", 0),
            "protocol": network.get("transport", ""),
            "service": network.get("protocol", ""),
            "bytes": total_bytes,
            "duration": round(duration, 3),
            "country": geo.get("country_iso_code", ""),
            "country_name": geo.get("country_name", ""),
            "device_name": "",  # Can be enriched by DeviceRegistry later
        }
