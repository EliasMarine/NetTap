"""
NetTap Live Connection Tracker

Tracks active connections in memory (last 10,000, rotating oldest)
and provides connection rate calculation over a sliding window.
Queries OpenSearch arkime_sessions3-* for recent connection events.

Extended in Phase 1 of the Live Network Monitor Redesign to add:
- Geo coordinates, city, ASN, org in _format_connection()
- Consolidated dashboard endpoint via fetch_dashboard_data()
- Connection detail endpoint via fetch_connection_detail()
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


def _flatten(value: Any) -> str:
    """Flatten OpenSearch multi-valued fields (arrays) to a single string."""
    if isinstance(value, list):
        return value[0] if value else ""
    return value if isinstance(value, str) else str(value) if value else ""


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
        """Format a raw OpenSearch hit _source into a clean connection dict.

        Includes geo coordinates, city, ASN, and org for map visualization.
        The ``has_alert`` flag is initialized to False and set by the caller
        after cross-referencing with Suricata alerts.
        """
        # Extract nested fields safely
        src = source.get("source", {}) or {}
        dst = source.get("destination", {}) or {}
        client_bytes = source.get("client", {}) or {}
        server_bytes = source.get("server", {}) or {}
        network = source.get("network", {}) or {}
        event = source.get("event", {}) or {}
        geo = dst.get("geo", {}) or {}
        dst_as = dst.get("as", {}) or {}

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

        # Extract geo coordinates for map visualization
        location = geo.get("location", {}) or {}
        dest_lat = location.get("lat") if isinstance(location, dict) else None
        dest_lon = location.get("lon") if isinstance(location, dict) else None

        # Extract ASN organization name — may be nested dict or string
        org_name = dst_as.get("organization", {})
        if isinstance(org_name, dict):
            org_name = org_name.get("name", "")
        org_name = org_name or ""

        # OLD CODE START — original return dict without geo/ASN fields
        # return {
        #     "timestamp": source.get("@timestamp", ""),
        #     "source_ip": src.get("ip", ""),
        #     "source_port": src.get("port", 0),
        #     "dest_ip": dst.get("ip", ""),
        #     "dest_port": dst.get("port", 0),
        #     "protocol": network.get("transport", ""),
        #     "service": network.get("protocol", ""),
        #     "bytes": total_bytes,
        #     "duration": round(duration, 3),
        #     "country": geo.get("country_iso_code", ""),
        #     "country_name": geo.get("country_name", ""),
        #     "device_name": "",
        # }
        # OLD CODE END

        return {
            "timestamp": source.get("@timestamp", ""),
            "source_ip": src.get("ip", ""),
            "source_port": src.get("port", 0),
            "dest_ip": dst.get("ip", ""),
            "dest_port": dst.get("port", 0),
            "protocol": _flatten(network.get("transport", "")),
            "service": _flatten(network.get("protocol", "")),
            "bytes": total_bytes,
            "duration": round(duration, 3),
            "country": geo.get("country_iso_code", ""),
            "country_name": geo.get("country_name", ""),
            "device_name": "",  # Can be enriched by DeviceRegistry later
            # --- Live Monitor Redesign: geo + ASN fields ---
            "dest_lat": dest_lat,
            "dest_lon": dest_lon,
            "dest_city": geo.get("city_name", ""),
            "dest_asn": dst_as.get("number"),
            "dest_org": org_name,
            "has_alert": False,
        }

    # ------------------------------------------------------------------
    # Live Monitor Redesign: Consolidated Dashboard Endpoint
    # ------------------------------------------------------------------

    # Zeek conn event filters (same as traffic.py _ZEEK_CONN_FILTERS)
    _ZEEK_CONN_FILTERS: list[dict] = [
        {"term": {"event.provider": "zeek"}},
        {"term": {"event.dataset": "conn"}},
    ]

    # Suricata alert filters (same as alerts.py _SURICATA_ALERT_FILTERS)
    _SURICATA_ALERT_FILTERS: list[dict] = [
        {"term": {"event.provider": "suricata"}},
        {"term": {"event.dataset": "alert"}},
    ]

    # Exclude Suricata decoder/stream noise (same as alerts.py)
    _SURICATA_NOISE_EXCLUSION: list[dict] = [
        {"prefix": {"rule.name": "SURICATA "}},
    ]

    # Painless byte-sum script (matches traffic.py pattern)
    _PAINLESS_BYTE_SUM = (
        "(doc.containsKey('source.bytes') && doc['source.bytes'].size()>0 "
        "? doc['source.bytes'].value : 0) + "
        "(doc.containsKey('destination.bytes') && doc['destination.bytes'].size()>0 "
        "? doc['destination.bytes'].value : 0)"
    )

    def fetch_dashboard_data(
        self,
        device: str | None = None,
        proto: str | None = None,
        country: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Fetch complete live dashboard payload with connections + aggregations.

        Runs two OpenSearch queries:
        1. Zeek connections (last 5m) with aggregations for protocols,
           top talkers, geo destinations, bandwidth, active devices, top country.
        2. Suricata alert IP pairs (last 5m) for cross-referencing has_alert.

        Args:
            device: Filter by source or destination IP.
            proto: Filter by transport protocol.
            country: Filter by GeoIP country code.
            limit: Max connection hits to return.

        Returns:
            Dashboard payload dict with connections, stats, protocols,
            top_talkers, and geo_arcs.
        """
        if not self._client:
            logger.warning("No OpenSearch client configured for dashboard")
            return self._empty_dashboard_response()

        # --- Build filters for the Zeek connections query ---
        conn_filters: list[dict] = [
            *self._ZEEK_CONN_FILTERS,
            {"range": {"@timestamp": {"gte": "now-5m", "lte": "now"}}},
        ]

        if device:
            conn_filters.append({
                "bool": {
                    "should": [
                        {"term": {"source.ip.keyword": device}},
                        {"term": {"destination.ip.keyword": device}},
                    ],
                    "minimum_should_match": 1,
                }
            })

        if proto:
            conn_filters.append(
                {"term": {"network.transport.keyword": proto.lower()}}
            )

        if country:
            conn_filters.append(
                {"term": {"destination.geo.country_iso_code.keyword": country.upper()}}
            )

        # --- Query 1: Connections + Aggregations ---
        conn_query = {
            "size": min(limit, 500),
            "track_total_hits": True,
            "query": {"bool": {"filter": conn_filters}},
            "sort": [{"@timestamp": {"order": "desc"}}],
            "aggs": {
                "protocols": {
                    "terms": {"field": "network.transport.keyword", "size": 10},
                },
                "top_talkers": {
                    "terms": {"field": "source.ip.keyword", "size": 5},
                    "aggs": {
                        "total_bytes": {
                            "sum": {
                                "script": {
                                    "source": self._PAINLESS_BYTE_SUM,
                                    "lang": "painless",
                                }
                            }
                        },
                        "bucket_sort": {
                            "bucket_sort": {
                                "sort": [{"total_bytes": {"order": "desc"}}]
                            }
                        },
                    },
                },
                "geo_destinations": {
                    "terms": {
                        "field": "destination.geo.city_name.keyword",
                        "size": 20,
                    },
                    "aggs": {
                        "total_bytes": {
                            "sum": {
                                "script": {
                                    "source": self._PAINLESS_BYTE_SUM,
                                    "lang": "painless",
                                }
                            }
                        },
                        "country": {
                            "terms": {
                                "field": "destination.geo.country_name.keyword",
                                "size": 1,
                            }
                        },
                        "country_code": {
                            "terms": {
                                "field": "destination.geo.country_iso_code.keyword",
                                "size": 1,
                            }
                        },
                        "location": {
                            "top_hits": {
                                "size": 1,
                                "_source": ["destination.geo.location"],
                                "sort": [{"@timestamp": {"order": "desc"}}],
                            }
                        },
                    },
                },
                "geo_countries": {
                    "terms": {
                        "field": "destination.geo.country_iso_code.keyword",
                        "size": 30,
                    },
                    "aggs": {
                        "country_name": {
                            "terms": {
                                "field": "destination.geo.country_name.keyword",
                                "size": 1,
                            }
                        },
                        "top_city": {
                            "terms": {
                                "field": "destination.geo.city_name.keyword",
                                "size": 1,
                            }
                        },
                        "total_bytes": {
                            "sum": {
                                "script": {
                                    "source": self._PAINLESS_BYTE_SUM,
                                    "lang": "painless",
                                }
                            }
                        },
                        "location": {
                            "top_hits": {
                                "size": 1,
                                "_source": ["destination.geo.location"],
                                "sort": [{"@timestamp": {"order": "desc"}}],
                            }
                        },
                    },
                },
                "total_bytes_in": {
                    "sum": {"field": "source.bytes", "missing": 0}
                },
                "total_bytes_out": {
                    "sum": {"field": "destination.bytes", "missing": 0}
                },
                "active_devices": {
                    "cardinality": {"field": "source.ip.keyword"}
                },
                "top_country": {
                    "terms": {
                        "field": "destination.geo.country_name.keyword",
                        "size": 1,
                    }
                },
            },
        }

        # --- Query 2: Suricata alert IP pairs (last 5m) ---
        alert_query = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        *self._SURICATA_ALERT_FILTERS,
                        {"range": {"@timestamp": {"gte": "now-5m", "lte": "now"}}},
                    ],
                    "must_not": self._SURICATA_NOISE_EXCLUSION,
                }
            },
            "aggs": {
                "alert_pairs": {
                    "terms": {
                        "script": {
                            "source": (
                                "def s = doc.containsKey('source.ip') "
                                "&& doc['source.ip'].size()>0 "
                                "? doc['source.ip'].value : ''; "
                                "def d = doc.containsKey('destination.ip') "
                                "&& doc['destination.ip'].size()>0 "
                                "? doc['destination.ip'].value : ''; "
                                "return s + '>' + d"
                            ),
                            "lang": "painless",
                        },
                        "size": 500,
                    }
                }
            },
        }

        try:
            conn_result = self._client.search(
                index=NETWORK_INDEX, body=conn_query
            )
        except OpenSearchException as exc:
            logger.error("OpenSearch error in dashboard connections query: %s", exc)
            return self._empty_dashboard_response()

        try:
            alert_result = self._client.search(
                index=NETWORK_INDEX, body=alert_query
            )
        except OpenSearchException as exc:
            logger.warning("OpenSearch error in dashboard alert query: %s", exc)
            # Degrade gracefully — dashboard still works without alert flags
            alert_result = {}

        # --- Post-processing ---

        # Parse connections from hits
        hits = conn_result.get("hits", {}).get("hits", [])
        connections = []
        for hit in hits:
            src_doc = hit.get("_source", {})
            conn = self._format_connection(src_doc)
            connections.append(conn)
            self._connections.append(conn)

        self._record_rate(len(connections))

        # Build alert pairs set for cross-referencing
        alert_pairs: set[str] = set()
        alert_buckets = (
            alert_result
            .get("aggregations", {})
            .get("alert_pairs", {})
            .get("buckets", [])
        )
        for bucket in alert_buckets:
            alert_pairs.add(bucket.get("key", ""))

        # Flag connections with matching alerts
        for conn in connections:
            pair_key = f"{conn['source_ip']}>{conn['dest_ip']}"
            reverse_key = f"{conn['dest_ip']}>{conn['source_ip']}"
            if pair_key in alert_pairs or reverse_key in alert_pairs:
                conn["has_alert"] = True

        # Extract aggregation results
        aggs = conn_result.get("aggregations", {})

        # Total hits (for connections_per_second calculation)
        hits_total = conn_result.get("hits", {}).get("total", {})
        total_hits = (
            hits_total.get("value", 0)
            if isinstance(hits_total, dict)
            else hits_total
        )

        # Bandwidth
        bytes_in = aggs.get("total_bytes_in", {}).get("value", 0) or 0
        bytes_out = aggs.get("total_bytes_out", {}).get("value", 0) or 0

        # 5-minute window
        window_seconds = 300.0

        # Active devices
        active_devices = aggs.get("active_devices", {}).get("value", 0) or 0

        # Top country
        top_country_buckets = aggs.get("top_country", {}).get("buckets", [])
        top_country = top_country_buckets[0]["key"] if top_country_buckets else ""

        # Protocol percentages
        proto_buckets = aggs.get("protocols", {}).get("buckets", [])
        total_proto_count = sum(b.get("doc_count", 0) for b in proto_buckets)
        protocols: dict[str, float] = {"tcp": 0.0, "udp": 0.0, "icmp": 0.0, "other": 0.0}
        for bucket in proto_buckets:
            name = bucket.get("key", "").lower()
            pct = (
                round(bucket["doc_count"] / total_proto_count * 100, 1)
                if total_proto_count > 0
                else 0.0
            )
            if name in protocols:
                protocols[name] = pct
            else:
                protocols["other"] = round(protocols["other"] + pct, 1)

        # Top talkers
        talker_buckets = aggs.get("top_talkers", {}).get("buckets", [])
        top_talkers = [
            {
                "ip": b["key"],
                "bytes": b.get("total_bytes", {}).get("value", 0),
                "connections": b.get("doc_count", 0),
            }
            for b in talker_buckets
        ]

        # Geo arcs (for map visualization)
        geo_buckets = aggs.get("geo_destinations", {}).get("buckets", [])
        geo_arcs = []
        for bucket in geo_buckets:
            city = bucket.get("key", "")
            count = bucket.get("doc_count", 0)
            total_b = bucket.get("total_bytes", {}).get("value", 0)

            # Extract country name
            country_b = bucket.get("country", {}).get("buckets", [])
            country_name = country_b[0]["key"] if country_b else ""

            # Extract country code
            cc_b = bucket.get("country_code", {}).get("buckets", [])
            country_code = cc_b[0]["key"] if cc_b else ""

            # Extract lat/lon from top_hits
            loc_hits = (
                bucket
                .get("location", {})
                .get("hits", {})
                .get("hits", [])
            )
            lat = None
            lon = None
            if loc_hits:
                loc_src = loc_hits[0].get("_source", {})
                loc_data = (
                    loc_src
                    .get("destination", {})
                    .get("geo", {})
                    .get("location", {})
                )
                if isinstance(loc_data, dict):
                    lat = loc_data.get("lat")
                    lon = loc_data.get("lon")

            if city and lat is not None and lon is not None:
                geo_arcs.append({
                    "city": city,
                    "country": country_name,
                    "country_code": country_code,
                    "lat": lat,
                    "lon": lon,
                    "count": count,
                    "bytes": total_b,
                })

        # Country-level fallbacks: add arcs for countries that have
        # connections but no city-level entry in the top-20 city list.
        seen_countries = {arc["country_code"] for arc in geo_arcs}
        country_buckets = aggs.get("geo_countries", {}).get("buckets", [])
        for bucket in country_buckets:
            cc = bucket.get("key", "")
            if cc in seen_countries or not cc:
                continue

            c_count = bucket.get("doc_count", 0)
            c_bytes = bucket.get("total_bytes", {}).get("value", 0)

            cn_b = bucket.get("country_name", {}).get("buckets", [])
            c_country = cn_b[0]["key"] if cn_b else ""

            city_b = bucket.get("top_city", {}).get("buckets", [])
            c_city = city_b[0]["key"] if city_b else ""

            c_loc_hits = (
                bucket.get("location", {}).get("hits", {}).get("hits", [])
            )
            c_lat, c_lon = None, None
            if c_loc_hits:
                c_loc_src = c_loc_hits[0].get("_source", {})
                c_loc_data = (
                    c_loc_src
                    .get("destination", {})
                    .get("geo", {})
                    .get("location", {})
                )
                if isinstance(c_loc_data, dict):
                    c_lat = c_loc_data.get("lat")
                    c_lon = c_loc_data.get("lon")

            if c_lat is not None and c_lon is not None:
                geo_arcs.append({
                    "city": c_city or c_country,
                    "country": c_country,
                    "country_code": cc,
                    "lat": c_lat,
                    "lon": c_lon,
                    "count": c_count,
                    "bytes": c_bytes,
                })

        return {
            "connections": connections,
            "count": len(connections),
            "stats": {
                "connections_per_second": round(total_hits / window_seconds, 2),
                "bandwidth_bytes_per_second": round(
                    (bytes_in + bytes_out) / window_seconds, 2
                ),
                "active_devices": active_devices,
                "top_country": top_country,
            },
            "protocols": protocols,
            "top_talkers": top_talkers,
            "geo_arcs": geo_arcs,
        }

    def fetch_connection_detail(
        self,
        src_ip: str,
        dst_ip: str,
        dst_port: int | None = None,
    ) -> dict[str, Any]:
        """Fetch detailed information for a specific src→dst connection pair.

        Runs three OpenSearch queries:
        A. Latest session with full geo/ASN fields (size 1)
        B. Related Suricata alerts (last 24h, size 20, exclude decoder noise)
        C. Connection history (last 24h) with date_histogram (1h) + bytes sum

        Args:
            src_ip: Source IP address.
            dst_ip: Destination IP address.
            dst_port: Optional destination port filter.

        Returns:
            Detail payload dict with geo, alerts, alert_count, and history.
        """
        if not self._client:
            logger.warning("No OpenSearch client configured for detail")
            return self._empty_detail_response()

        # Shared IP pair filter: match traffic in either direction
        ip_pair_filter = {
            "bool": {
                "should": [
                    {"bool": {"must": [
                        {"term": {"source.ip.keyword": src_ip}},
                        {"term": {"destination.ip.keyword": dst_ip}},
                    ]}},
                    {"bool": {"must": [
                        {"term": {"source.ip.keyword": dst_ip}},
                        {"term": {"destination.ip.keyword": src_ip}},
                    ]}},
                ],
                "minimum_should_match": 1,
            }
        }

        port_filter = (
            {"term": {"destination.port": dst_port}} if dst_port else None
        )

        # --- Query A: Latest session with full geo/ASN ---
        session_filters: list[dict] = [
            *self._ZEEK_CONN_FILTERS,
            {"range": {"@timestamp": {"gte": "now-24h", "lte": "now"}}},
            ip_pair_filter,
        ]
        if port_filter:
            session_filters.append(port_filter)

        session_query = {
            "size": 1,
            "query": {"bool": {"filter": session_filters}},
            "sort": [{"@timestamp": {"order": "desc"}}],
            "_source": [
                "destination.ip", "destination.geo.*", "destination.as.*",
                "source.ip", "source.geo.*", "source.as.*",
                "@timestamp",
            ],
        }

        # --- Query B: Related Suricata alerts (last 24h) ---
        alert_filters: list[dict] = [
            *self._SURICATA_ALERT_FILTERS,
            {"range": {"@timestamp": {"gte": "now-24h", "lte": "now"}}},
            ip_pair_filter,
        ]
        alert_query = {
            "size": 20,
            "query": {
                "bool": {
                    "filter": alert_filters,
                    "must_not": self._SURICATA_NOISE_EXCLUSION,
                }
            },
            "sort": [{"@timestamp": {"order": "desc"}}],
            "_source": [
                "@timestamp", "rule.name", "rule.category",
                "suricata.alert.signature", "suricata.alert.severity",
                "suricata.alert.category",
                "alert.signature", "alert.severity", "alert.category",
                "suricata.severity",
            ],
        }

        # --- Query C: Connection history (last 24h) with date_histogram ---
        history_filters: list[dict] = [
            *self._ZEEK_CONN_FILTERS,
            {"range": {"@timestamp": {"gte": "now-24h", "lte": "now"}}},
            ip_pair_filter,
        ]
        if port_filter:
            history_filters.append(port_filter)

        history_query = {
            "size": 0,
            "track_total_hits": True,
            "query": {"bool": {"filter": history_filters}},
            "aggs": {
                "total_bytes": {
                    "sum": {
                        "script": {
                            "source": self._PAINLESS_BYTE_SUM,
                            "lang": "painless",
                        }
                    }
                },
                "over_time": {
                    "date_histogram": {
                        "field": "@timestamp",
                        "fixed_interval": "1h",
                        "min_doc_count": 0,
                        "extended_bounds": {
                            "min": "now-24h",
                            "max": "now",
                        },
                    },
                    "aggs": {
                        "bytes": {
                            "sum": {
                                "script": {
                                    "source": self._PAINLESS_BYTE_SUM,
                                    "lang": "painless",
                                }
                            }
                        },
                    },
                },
            },
        }

        # Execute queries — each with independent error handling
        session_result = {}
        try:
            session_result = self._client.search(
                index=NETWORK_INDEX, body=session_query
            )
        except OpenSearchException as exc:
            logger.error("OpenSearch error in detail session query: %s", exc)

        alert_result = {}
        try:
            alert_result = self._client.search(
                index=NETWORK_INDEX, body=alert_query
            )
        except OpenSearchException as exc:
            logger.warning("OpenSearch error in detail alert query: %s", exc)

        history_result = {}
        try:
            history_result = self._client.search(
                index=NETWORK_INDEX, body=history_query
            )
        except OpenSearchException as exc:
            logger.warning("OpenSearch error in detail history query: %s", exc)

        # --- Parse session geo/ASN ---
        geo_info = self._parse_session_geo(session_result, dst_ip)

        # --- Parse alerts ---
        alert_hits = alert_result.get("hits", {}).get("hits", [])
        alerts = []
        for hit in alert_hits:
            src_doc = hit.get("_source", {})
            alert_entry = self._parse_alert_entry(src_doc)
            if alert_entry:
                alerts.append(alert_entry)

        # --- Parse history ---
        history_aggs = history_result.get("aggregations", {})
        history_total = history_result.get("hits", {}).get("total", {})
        connection_count = (
            history_total.get("value", 0)
            if isinstance(history_total, dict)
            else history_total
        )
        total_bytes = history_aggs.get("total_bytes", {}).get("value", 0) or 0

        timeline_buckets = (
            history_aggs.get("over_time", {}).get("buckets", [])
        )
        timeline = [
            {
                "timestamp": b.get("key_as_string", b.get("key")),
                "bytes": b.get("bytes", {}).get("value", 0) or 0,
                "connections": b.get("doc_count", 0),
            }
            for b in timeline_buckets
        ]

        return {
            "geo": geo_info,
            "alerts": alerts,
            "alert_count": len(alerts),
            "history": {
                "total_bytes": total_bytes,
                "connection_count": connection_count,
                "timeline": timeline,
            },
        }

    # ------------------------------------------------------------------
    # Private helpers for dashboard / detail
    # ------------------------------------------------------------------

    def _parse_session_geo(
        self, session_result: dict, target_ip: str
    ) -> dict[str, Any]:
        """Extract geo/ASN info from a session query result for target_ip."""
        hits = session_result.get("hits", {}).get("hits", [])
        if not hits:
            return {
                "ip": target_ip,
                "country": "",
                "country_code": "",
                "city": "",
                "lat": None,
                "lon": None,
                "asn": None,
                "organization": "",
            }

        src_doc = hits[0].get("_source", {})
        dst_data = src_doc.get("destination", {}) or {}
        src_data = src_doc.get("source", {}) or {}

        # Determine which side is the target
        if dst_data.get("ip") == target_ip:
            geo = dst_data.get("geo", {}) or {}
            as_info = dst_data.get("as", {}) or {}
        elif src_data.get("ip") == target_ip:
            geo = src_data.get("geo", {}) or {}
            as_info = src_data.get("as", {}) or {}
        else:
            # Fallback: use destination geo (common case)
            geo = dst_data.get("geo", {}) or {}
            as_info = dst_data.get("as", {}) or {}

        location = geo.get("location", {}) or {}
        lat = location.get("lat") if isinstance(location, dict) else None
        lon = location.get("lon") if isinstance(location, dict) else None

        org_name = as_info.get("organization", {})
        if isinstance(org_name, dict):
            org_name = org_name.get("name", "")
        org_name = org_name or ""

        return {
            "ip": target_ip,
            "country": geo.get("country_name", ""),
            "country_code": geo.get("country_iso_code", ""),
            "city": geo.get("city_name", ""),
            "lat": lat,
            "lon": lon,
            "asn": as_info.get("number"),
            "organization": org_name,
        }

    def _parse_alert_entry(self, source: dict) -> dict[str, Any] | None:
        """Parse a single Suricata alert hit into a normalized dict.

        Handles the multiple field paths that Malcolm/ECS use for alert data
        (same normalization approach as alerts.py _normalize_alert_source).
        """
        rule = source.get("rule", {}) or {}
        suricata = source.get("suricata", {}) or {}
        suricata_alert = suricata.get("alert", {}) if isinstance(suricata, dict) else {}
        suricata_alert = suricata_alert or {}
        existing_alert = source.get("alert", {}) or {}

        signature = (
            existing_alert.get("signature")
            or rule.get("name")
            or suricata_alert.get("signature")
            or ""
        )

        if not signature:
            return None

        # Severity: try multiple paths, default to 3 (low)
        severity = (
            existing_alert.get("severity")
            or suricata_alert.get("severity")
            or suricata.get("severity")
            or rule.get("severity")
        )
        try:
            severity = int(severity)
        except (TypeError, ValueError):
            severity = 3

        raw_category = (
            existing_alert.get("category")
            or rule.get("category")
            or suricata_alert.get("category")
            or ""
        )
        if isinstance(raw_category, list):
            category = raw_category[0] if raw_category else ""
        else:
            category = raw_category

        return {
            "timestamp": source.get("@timestamp", ""),
            "signature": signature,
            "severity": severity,
            "category": category,
        }

    @staticmethod
    def _empty_dashboard_response() -> dict[str, Any]:
        """Return an empty but structurally valid dashboard payload."""
        return {
            "connections": [],
            "count": 0,
            "stats": {
                "connections_per_second": 0,
                "bandwidth_bytes_per_second": 0,
                "active_devices": 0,
                "top_country": "",
            },
            "protocols": {"tcp": 0, "udp": 0, "icmp": 0, "other": 0},
            "top_talkers": [],
            "geo_arcs": [],
        }

    @staticmethod
    def _empty_detail_response() -> dict[str, Any]:
        """Return an empty but structurally valid detail payload."""
        return {
            "geo": {
                "ip": "",
                "country": "",
                "country_code": "",
                "city": "",
                "lat": None,
                "lon": None,
                "asn": None,
                "organization": "",
            },
            "alerts": [],
            "alert_count": 0,
            "history": {
                "total_bytes": 0,
                "connection_count": 0,
                "timeline": [],
            },
        }
