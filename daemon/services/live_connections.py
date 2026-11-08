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

import ipaddress
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from opensearchpy import OpenSearch, OpenSearchException

from api.alerts import SURICATA_NOISE_EXCLUSION, rule_categories
from services.excluded_ips import RFC1918_SOURCE_FILTER, lan_subnets_of
from storage.time_slots import histogram_buckets, time_slots

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


def _epoch_ms(value: Any) -> float | None:
    """Epoch ms from Malcolm's epoch-ms text ("1793613468348"), a number, or an ISO date."""
    text = str(value)
    if text.isdigit():
        return float(text)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000
    except ValueError:
        return None


def _duration_seconds(source: dict[str, Any], event: dict[str, Any]) -> float:
    """A session's duration: `length` (end minus start, ms) when present, else end minus start (#144)."""
    length = source.get("length")
    if (
        isinstance(length, (int, float))
        and not isinstance(length, bool)
        and length >= 0
    ):
        return length / 1000
    start, end = _epoch_ms(event.get("start")), _epoch_ms(event.get("end"))
    if start is None or end is None or end < start:
        return 0.0
    return (end - start) / 1000


_RFC1918 = [
    ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
]
_LIMITED_BROADCAST = ipaddress.IPv4Address("255.255.255.255")


def _in_lan(addr: ipaddress.IPv4Address | ipaddress.IPv6Address, subnets: list) -> bool:
    """The LAN filter's rule: IPv4 in a detected subnet ((a, b, c), -1 = any), else RFC1918."""
    if addr.version != 4:
        return False
    if not subnets:
        return any(addr in net for net in _RFC1918)
    a, b, c, _ = addr.packed
    return any(sa == a and sb in (-1, b) and sc in (-1, c) for sa, sb, sc in subnets)


def _is_special(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address, subnets: list
) -> bool:
    """Multicast, link-local, loopback, or a broadcast (limited, or a detected subnet's)."""
    if addr.is_multicast or addr.is_link_local or addr.is_loopback:
        return True
    if addr.version != 4:
        return False
    octets = tuple(addr.packed)
    for subnet in subnets:
        n = 3 - list(subnet).count(-1)  # the subnet's fixed octets
        if octets[:n] == tuple(subnet[:n]) and all(o == 255 for o in octets[n:]):
            return True
    return addr == _LIMITED_BROADCAST


def connection_direction(src: Any, dst: Any, lan_subnets: list) -> str:
    """'local', 'out', 'in' or 'unknown' for one connection, by these rules in order (O2):

    1. either end is multicast, broadcast, link-local or loopback: local
    2. both ends in the LAN: local
    3. a LAN source to an internet destination: out
    4. an internet source to a LAN destination: in
    5. anything else, such as an ISP's private address or IPv6 outside the LAN rule: unknown
    """
    try:
        s, d = ipaddress.ip_address(src), ipaddress.ip_address(dst)
    except (TypeError, ValueError):
        return "unknown"
    if _is_special(s, lan_subnets) or _is_special(d, lan_subnets):
        return "local"
    s_lan, d_lan = _in_lan(s, lan_subnets), _in_lan(d, lan_subnets)
    if s_lan and d_lan:
        return "local"
    if s_lan and d.is_global:
        return "out"
    if d_lan and s.is_global:
        return "in"
    return "unknown"


def country_filter(country: str) -> dict:
    """Rows whose place (see _format_connection) is in this country: the destination's
    country, or the source's when the destination has none."""
    code = country.upper()
    return {
        "bool": {
            "should": [
                {"term": {"destination.geo.country_iso_code": code}},
                {
                    "bool": {
                        "must": [{"term": {"source.geo.country_iso_code": code}}],
                        "must_not": [
                            {"exists": {"field": "destination.geo.country_iso_code"}}
                        ],
                    }
                },
            ],
            "minimum_should_match": 1,
        }
    }


class LiveConnectionTracker:
    """Tracks active connections from OpenSearch with in-memory caching."""

    def __init__(self, client: OpenSearch | None = None) -> None:
        self._client = client
        self._connections: deque[dict[str, Any]] = deque(maxlen=MAX_CONNECTIONS)
        self._rate_timestamps: deque[float] = deque()
        self._last_fetch_time: str | None = None
        # The fetches run in threads; the deques are read and pruned from the loop too
        self._lock = threading.Lock()

    def set_client(self, client: OpenSearch) -> None:
        """Set the OpenSearch client (for deferred initialization)."""
        self._client = client

    def _record_rate(self, count: int) -> None:
        """Record connection fetch count for rate calculation."""
        now = time.monotonic()
        with self._lock:
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
        with self._lock:
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
        with self._lock:  # a fetch in another thread may append while this iterates
            cached = list(self._connections)
        for conn in reversed(cached):
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
        filters.append(
            {
                "range": {
                    "@timestamp": {
                        "gte": "now-5m",
                        "lte": "now",
                    }
                }
            }
        )

        if device:
            filters.append(
                {
                    "bool": {
                        "should": [
                            {"term": {"source.ip": device}},
                            {"term": {"destination.ip": device}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )

        if proto:
            filters.append({"term": {"network.transport": proto.lower()}})

        # OLD CODE START — 2026-11-07 (live globe): destination only, so an inbound row never matched
        # if country:
        #     filters.append(
        #         {"term": {"destination.geo.country_iso_code": country.upper()}}
        #     )
        # OLD CODE END
        if country:
            filters.append(country_filter(country))

        query = {
            "size": min(limit, 500),
            "query": {"bool": {"filter": filters}},
            "sort": [{"@timestamp": {"order": "desc"}}],
        }

        # OLD CODE START — #96: a failure served the in-memory cache (old, or empty) as live
        # try:
        #     result = self._client.search(index=NETWORK_INDEX, body=query)
        # except OpenSearchException as exc:
        #     logger.error("OpenSearch error fetching live connections: %s", exc)
        #     return self.get_active_connections(device, proto, country, limit=limit)
        # OLD CODE END
        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except OpenSearchException as exc:
            logger.error("OpenSearch error fetching live connections: %s", exc)
            raise

        hits = result.get("hits", {}).get("hits", [])
        connections = []
        for hit in hits:
            src = hit.get("_source", {})
            conn = self._format_connection(src)
            connections.append(conn)
            with self._lock:
                self._connections.append(conn)

        self._record_rate(len(connections))
        return connections

    def _format_connection(self, source: dict[str, Any]) -> dict[str, Any]:
        """Format a raw OpenSearch hit _source into a clean connection dict.

        Includes geo coordinates, city, ASN, and org for map visualization. They describe the
        remote end: the destination, or the source when only the source has a country (an
        inbound row); ``geo_ip`` is that end's address, or "" when neither end has a country.
        The ``has_alert`` flag is initialized to False and set by the caller
        after cross-referencing with Suricata alerts.
        """
        # Extract nested fields safely
        src = source.get("source", {}) or {}
        dst = source.get("destination", {}) or {}
        # OLD CODE START — 2026-11-06 (O11): only read by the payload-bytes sum below
        # client_bytes = source.get("client", {}) or {}
        # server_bytes = source.get("server", {}) or {}
        # OLD CODE END
        network = source.get("network", {}) or {}
        event = source.get("event", {}) or {}
        # OLD CODE START — 2026-11-07 (live globe): the destination only, so an inbound row
        # (Malcolm geolocates public addresses only) had no place
        # geo = dst.get("geo", {}) or {}
        # dst_as = dst.get("as", {}) or {}
        # OLD CODE END
        # The row's place: the destination's when it has a country, else the source's when that
        # has one. The dest_* fields keep their names and mean "the remote end" (geo_ip says which).
        dst_geo = dst.get("geo", {}) or {}
        src_geo = src.get("geo", {}) or {}
        use_src = not dst_geo.get("country_iso_code") and bool(
            src_geo.get("country_iso_code")
        )
        place = src if use_src else dst
        geo = src_geo if use_src else dst_geo
        dst_as = place.get("as", {}) or {}
        geo_ip = place.get("ip", "") if geo.get("country_iso_code") else ""

        # OLD CODE START — 2026-11-06 (O11): payload bytes, while the top talkers, bandwidth and
        # the drawer's 24 h total sum source.bytes + destination.bytes
        # # Calculate bytes
        # total_bytes = (client_bytes.get("bytes", 0) or 0) + (
        #     server_bytes.get("bytes", 0) or 0
        # )
        # if total_bytes == 0:
        #     total_bytes = (src.get("bytes", 0) or 0) + (dst.get("bytes", 0) or 0)
        # OLD CODE END
        # One byte basis for the whole Live page (_PAINLESS_BYTE_SUM)
        total_bytes = (src.get("bytes", 0) or 0) + (dst.get("bytes", 0) or 0)

        # OLD CODE START — #144: Malcolm 26.x writes event.start/end as epoch-ms text, which
        # fromisoformat refuses, so every live connection read 0 s
        # # Calculate duration
        # duration = 0.0
        # event_start = event.get("start")
        # event_end = event.get("end")
        # if event_start and event_end:
        #     try:
        #         start_dt = datetime.fromisoformat(
        #             str(event_start).replace("Z", "+00:00")
        #         )
        #         end_dt = datetime.fromisoformat(str(event_end).replace("Z", "+00:00"))
        #         duration = (end_dt - start_dt).total_seconds()
        #     except (ValueError, TypeError):
        #         pass
        # OLD CODE END
        duration = _duration_seconds(source, event)

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
            "geo_ip": geo_ip,
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
    # OLD CODE START — NET-191: a private copy missed ET's informational alerts, which every
    # other page stops counting; the shared rule lives in api/alerts.py
    # _SURICATA_NOISE_EXCLUSION: list[dict] = [
    #     {"prefix": {"rule.name": "SURICATA "}},
    # ]
    # OLD CODE END
    _SURICATA_NOISE_EXCLUSION: list[dict] = SURICATA_NOISE_EXCLUSION

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
        excluded_ips: list[str] | None = None,
        lan_filter: dict | None = None,
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
            conn_filters.append(
                {
                    "bool": {
                        "should": [
                            {"term": {"source.ip": device}},
                            {"term": {"destination.ip": device}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )

        if proto:
            conn_filters.append({"term": {"network.transport": proto.lower()}})

        # OLD CODE START — 2026-11-07 (live globe): destination only, so an inbound row never matched
        # if country:
        #     conn_filters.append(
        #         {"term": {"destination.geo.country_iso_code": country.upper()}}
        #     )
        # OLD CODE END
        if country:
            conn_filters.append(country_filter(country))

        # --- Build must_not clauses (excluded IPs) ---
        must_not_clauses: list[dict] = []
        if excluded_ips:
            must_not_clauses.append({"terms": {"source.ip": excluded_ips}})

        # --- Query 1: Connections + Aggregations ---
        bool_clause: dict[str, Any] = {"filter": conn_filters}
        if must_not_clauses:
            bool_clause["must_not"] = must_not_clauses

        conn_query = {
            "size": min(limit, 500),
            "track_total_hits": True,
            "query": {"bool": bool_clause},
            "sort": [{"@timestamp": {"order": "desc"}}],
            "aggs": {
                "protocols": {
                    "terms": {"field": "network.transport", "size": 10},
                },
                # O6: records with no transport, so the protocol counts add up to the window's total
                "protocols_missing": {"missing": {"field": "network.transport"}},
                # OLD CODE START — 2026-11-06 (O11): every source, so internet hosts and an ISP's
                # gateway ranked as "devices"
                # "top_talkers": {
                #     # OLD CODE START — top-N by doc count then bucket_sort missed the real top-N by bytes
                #     # "terms": {"field": "source.ip.keyword", "size": 5},
                #     # OLD CODE END
                #     "terms": {
                #         "field": "source.ip",
                #         "size": 5,
                #         "order": {"total_bytes": "desc"},
                #     },
                #     "aggs": {
                #         "total_bytes": {
                #             "sum": {
                #                 "script": {
                #                     "source": self._PAINLESS_BYTE_SUM,
                #                     "lang": "painless",
                #                 }
                #             }
                #         },
                #         # OLD CODE START — top-N by doc count then bucket_sort missed the real top-N by bytes
                #         # "bucket_sort": {
                #         #     "bucket_sort": {
                #         #         "sort": [{"total_bytes": {"order": "desc"}}]
                #         #     }
                #         # },
                #         # OLD CODE END
                #     },
                # },
                # OLD CODE END
                # LAN sources only, the same rule as active_devices and the Devices page
                "top_talkers": {
                    "filter": lan_filter or RFC1918_SOURCE_FILTER,
                    "aggs": {
                        "ips": {
                            "terms": {
                                "field": "source.ip",
                                "size": 5,
                                "order": {"total_bytes": "desc"},
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
                            },
                        },
                    },
                },
                "geo_destinations": {
                    "terms": {
                        "field": "destination.geo.city_name",
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
                                "field": "destination.geo.country_name",
                                "size": 1,
                            }
                        },
                        "country_code": {
                            "terms": {
                                "field": "destination.geo.country_iso_code",
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
                        "field": "destination.geo.country_iso_code",
                        "size": 30,
                    },
                    "aggs": {
                        "country_name": {
                            "terms": {
                                "field": "destination.geo.country_name",
                                "size": 1,
                            }
                        },
                        "top_city": {
                            "terms": {
                                "field": "destination.geo.city_name",
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
                "total_bytes_in": {"sum": {"field": "source.bytes", "missing": 0}},
                "total_bytes_out": {
                    "sum": {"field": "destination.bytes", "missing": 0}
                },
                # OLD CODE START — 2026-11-02: every source.ip, so each device counted
                # twice (IPv4 + IPv6 link-local): 79 "devices" for 38 on the G11
                # "active_devices": {"cardinality": {"field": "source.ip"}},
                # OLD CODE END
                # LAN sources only, the same rule as the Devices page
                "active_devices": {
                    "filter": lan_filter or RFC1918_SOURCE_FILTER,
                    "aggs": {"n": {"cardinality": {"field": "source.ip"}}},
                },
                "top_country": {
                    "terms": {
                        "field": "destination.geo.country_name",
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
                        # OLD CODE START — doc['source.ip'] is a text field, so
                        # OpenSearch 400'd this agg and alert flags never showed
                        # "script": {
                        #     "source": (
                        #         "def s = doc.containsKey('source.ip') "
                        #         "&& doc['source.ip'].size()>0 "
                        #         "? doc['source.ip'].value : ''; "
                        #         "def d = doc.containsKey('destination.ip') "
                        #         "&& doc['destination.ip'].size()>0 "
                        #         "? doc['destination.ip'].value : ''; "
                        #         "return s + '>' + d"
                        #     ),
                        #     "lang": "painless",
                        # },
                        # OLD CODE END
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

        # OLD CODE START — #96: a failed connections query showed an all-zero dashboard, and a
        # failed alert query showed every connection as alert-free
        # try:
        #     conn_result = self._client.search(index=NETWORK_INDEX, body=conn_query)
        # except OpenSearchException as exc:
        #     logger.error("OpenSearch error in dashboard connections query: %s", exc)
        #     return self._empty_dashboard_response()
        #
        # try:
        #     alert_result = self._client.search(index=NETWORK_INDEX, body=alert_query)
        # except OpenSearchException as exc:
        #     logger.warning("OpenSearch error in dashboard alert query: %s", exc)
        #     # Degrade gracefully — dashboard still works without alert flags
        #     alert_result = {}
        # OLD CODE END
        conn_result = self._client.search(index=NETWORK_INDEX, body=conn_query)
        alert_result = self._client.search(index=NETWORK_INDEX, body=alert_query)

        # --- Post-processing ---

        # Parse connections from hits
        hits = conn_result.get("hits", {}).get("hits", [])
        lan_subnets = lan_subnets_of(lan_filter or RFC1918_SOURCE_FILTER)
        connections = []
        for hit in hits:
            src_doc = hit.get("_source", {})
            conn = self._format_connection(src_doc)
            # O2: from the LAN subnets, not guessed from the port
            conn["direction"] = connection_direction(
                conn["source_ip"], conn["dest_ip"], lan_subnets
            )
            connections.append(conn)
            with self._lock:
                self._connections.append(conn)

        self._record_rate(len(connections))

        # Build alert pairs set for cross-referencing
        alert_pairs: set[str] = set()
        alert_buckets = (
            alert_result.get("aggregations", {})
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
            hits_total.get("value", 0) if isinstance(hits_total, dict) else hits_total
        )

        # Bandwidth
        bytes_in = aggs.get("total_bytes_in", {}).get("value", 0) or 0
        bytes_out = aggs.get("total_bytes_out", {}).get("value", 0) or 0

        # 5-minute window
        window_seconds = 300.0

        # Active devices
        active_devices = (
            aggs.get("active_devices", {}).get("n", {}).get("value", 0) or 0
        )

        # Top country
        top_country_buckets = aggs.get("top_country", {}).get("buckets", [])
        top_country = top_country_buckets[0]["key"] if top_country_buckets else ""

        # OLD CODE START — 2026-11-06 (O6): percentages, which the page showed as connection counts,
        # and transports past the top 10 or missing altogether fell out of the split
        # # Protocol percentages
        # proto_buckets = aggs.get("protocols", {}).get("buckets", [])
        # total_proto_count = sum(b.get("doc_count", 0) for b in proto_buckets)
        # protocols: dict[str, float] = {
        #     "tcp": 0.0,
        #     "udp": 0.0,
        #     "icmp": 0.0,
        #     "other": 0.0,
        # }
        # for bucket in proto_buckets:
        #     name = bucket.get("key", "").lower()
        #     pct = (
        #         round(bucket["doc_count"] / total_proto_count * 100, 1)
        #         if total_proto_count > 0
        #         else 0.0
        #     )
        #     if name in protocols:
        #         protocols[name] = pct
        #     else:
        #         protocols["other"] = round(protocols["other"] + pct, 1)
        # OLD CODE END
        # Connection counts per transport, a complete split of the window: unrecognised
        # transports (and any past the top 10) are "other", records with none "unknown"
        proto_agg = aggs.get("protocols", {})
        protocols: dict[str, int] = {
            "tcp": 0,
            "udp": 0,
            "icmp": 0,
            "other": proto_agg.get("sum_other_doc_count", 0) or 0,
            "unknown": aggs.get("protocols_missing", {}).get("doc_count", 0) or 0,
        }
        for bucket in proto_agg.get("buckets", []):
            name = str(bucket.get("key", "")).lower()
            key = name if name in ("tcp", "udp", "icmp") else "other"
            protocols[key] += bucket.get("doc_count", 0)

        # Top talkers
        # OLD CODE START — 2026-11-06 (O11): the terms agg now sits under the LAN filter
        # talker_buckets = aggs.get("top_talkers", {}).get("buckets", [])
        # OLD CODE END
        talker_buckets = aggs.get("top_talkers", {}).get("ips", {}).get("buckets", [])
        top_talkers = [
            {
                "ip": b["key"],
                "bytes": b.get("total_bytes", {}).get("value", 0),
                "connections": b.get("doc_count", 0),
            }
            for b in talker_buckets
        ]

        # OLD CODE START — 2026-11-06 (O3): one arc per top-20 city, and a country with any city
        # in that list skipped its own bucket, so its dot was the sum of its listed cities only
        # # Geo arcs (for map visualization)
        # geo_buckets = aggs.get("geo_destinations", {}).get("buckets", [])
        # geo_arcs = []
        # for bucket in geo_buckets:
        #     city = bucket.get("key", "")
        #     count = bucket.get("doc_count", 0)
        #     total_b = bucket.get("total_bytes", {}).get("value", 0)
        #
        #     # Extract country name
        #     country_b = bucket.get("country", {}).get("buckets", [])
        #     country_name = country_b[0]["key"] if country_b else ""
        #
        #     # Extract country code
        #     cc_b = bucket.get("country_code", {}).get("buckets", [])
        #     country_code = cc_b[0]["key"] if cc_b else ""
        #
        #     # Extract lat/lon from top_hits
        #     loc_hits = bucket.get("location", {}).get("hits", {}).get("hits", [])
        #     lat = None
        #     lon = None
        #     if loc_hits:
        #         loc_src = loc_hits[0].get("_source", {})
        #         loc_data = (
        #             loc_src.get("destination", {}).get("geo", {}).get("location", {})
        #         )
        #         if isinstance(loc_data, dict):
        #             lat = loc_data.get("lat")
        #             lon = loc_data.get("lon")
        #
        #     if city and lat is not None and lon is not None:
        #         geo_arcs.append(
        #             {
        #                 "city": city,
        #                 "country": country_name,
        #                 "country_code": country_code,
        #                 "lat": lat,
        #                 "lon": lon,
        #                 "count": count,
        #                 "bytes": total_b,
        #             }
        #         )
        #
        # # Country-level fallbacks: add arcs for countries that have
        # # connections but no city-level entry in the top-20 city list.
        # seen_countries = {arc["country_code"] for arc in geo_arcs}
        # country_buckets = aggs.get("geo_countries", {}).get("buckets", [])
        # for bucket in country_buckets:
        #     cc = bucket.get("key", "")
        #     if cc in seen_countries or not cc:
        #         continue
        #
        #     c_count = bucket.get("doc_count", 0)
        #     c_bytes = bucket.get("total_bytes", {}).get("value", 0)
        #
        #     cn_b = bucket.get("country_name", {}).get("buckets", [])
        #     c_country = cn_b[0]["key"] if cn_b else ""
        #
        #     city_b = bucket.get("top_city", {}).get("buckets", [])
        #     c_city = city_b[0]["key"] if city_b else ""
        #
        #     c_loc_hits = bucket.get("location", {}).get("hits", {}).get("hits", [])
        #     c_lat, c_lon = None, None
        #     if c_loc_hits:
        #         c_loc_src = c_loc_hits[0].get("_source", {})
        #         c_loc_data = (
        #             c_loc_src.get("destination", {}).get("geo", {}).get("location", {})
        #         )
        #         if isinstance(c_loc_data, dict):
        #             c_lat = c_loc_data.get("lat")
        #             c_lon = c_loc_data.get("lon")
        #
        #     if c_lat is not None and c_lon is not None:
        #         geo_arcs.append(
        #             {
        #                 "city": c_city or c_country,
        #                 "country": c_country,
        #                 "country_code": cc,
        #                 "lat": c_lat,
        #                 "lon": c_lon,
        #                 "count": c_count,
        #                 "bytes": c_bytes,
        #             }
        #         )
        # OLD CODE END
        # Geo arcs (for the map): one per country with the country's own totals. The busiest
        # cities only place the dot, at the country's busiest city when that city is listed.
        city_locations: dict[tuple[str, str], tuple[Any, Any]] = {}
        for bucket in aggs.get("geo_destinations", {}).get("buckets", []):
            cc_b = bucket.get("country_code", {}).get("buckets", [])
            if cc_b:
                city_locations[(cc_b[0]["key"], bucket.get("key", ""))] = (
                    self._hit_location(bucket)
                )

        geo_arcs = []
        for bucket in aggs.get("geo_countries", {}).get("buckets", []):
            cc = bucket.get("key", "")
            if not cc:
                continue
            cn_b = bucket.get("country_name", {}).get("buckets", [])
            c_country = cn_b[0]["key"] if cn_b else ""
            city_b = bucket.get("top_city", {}).get("buckets", [])
            c_city = city_b[0]["key"] if city_b else ""
            lat, lon = city_locations.get((cc, c_city), (None, None))
            if lat is None or lon is None:
                lat, lon = self._hit_location(bucket)
            if lat is None or lon is None:
                continue
            geo_arcs.append(
                {
                    "city": c_city or c_country,
                    "country": c_country,
                    "country_code": cc,
                    "lat": lat,
                    "lon": lon,
                    "count": bucket.get("doc_count", 0),
                    "bytes": bucket.get("total_bytes", {}).get("value", 0),
                }
            )

        return {
            "connections": connections,
            "count": len(connections),
            "stats": {
                "connections_per_second": round(total_hits / window_seconds, 2),
                "connections_in_window": total_hits,
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
        geo_ip: str | None = None,
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
            geo_ip: The end to locate (the row's geo_ip); None means dst_ip.

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
                    {
                        "bool": {
                            "must": [
                                {"term": {"source.ip": src_ip}},
                                {"term": {"destination.ip": dst_ip}},
                            ]
                        }
                    },
                    {
                        "bool": {
                            "must": [
                                {"term": {"source.ip": dst_ip}},
                                {"term": {"destination.ip": src_ip}},
                            ]
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        }

        port_filter = {"term": {"destination.port": dst_port}} if dst_port else None

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
                "destination.ip",
                "destination.geo.*",
                "destination.as.*",
                "source.ip",
                "source.geo.*",
                "source.as.*",
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
                "@timestamp",
                "rule.name",
                "rule.category",
                "suricata.alert.signature",
                "suricata.alert.severity",
                "suricata.alert.category",
                "alert.signature",
                "alert.severity",
                "alert.category",
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

        now = datetime.now(timezone.utc)  # the query's now-24h..now, as hourly slots
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
                    # OLD CODE START — #120: OpenSearch 3.5's skip-list date_histogram misplaces records
                    # "date_histogram": {
                    #     "field": "@timestamp",
                    #     "fixed_interval": "1h",
                    #     "min_doc_count": 0,
                    #     "extended_bounds": {"min": "now-24h", "max": "now"},
                    # },
                    # OLD CODE END
                    **time_slots(now - timedelta(hours=24), now, "1h"),
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

        # OLD CODE START — #96: each failure blanked its part, so the drawer read 0 alerts,
        # 0 connections or no location for a pair it never checked
        # session_result = {}
        # try:
        #     session_result = self._client.search(index=NETWORK_INDEX, body=session_query)
        # except OpenSearchException as exc:
        #     logger.error("OpenSearch error in detail session query: %s", exc)
        #
        # alert_result = {}
        # try:
        #     alert_result = self._client.search(index=NETWORK_INDEX, body=alert_query)
        # except OpenSearchException as exc:
        #     logger.warning("OpenSearch error in detail alert query: %s", exc)
        #
        # history_result = {}
        # try:
        #     history_result = self._client.search(index=NETWORK_INDEX, body=history_query)
        # except OpenSearchException as exc:
        #     logger.warning("OpenSearch error in detail history query: %s", exc)
        # OLD CODE END
        session_result = self._client.search(index=NETWORK_INDEX, body=session_query)
        alert_result = self._client.search(index=NETWORK_INDEX, body=alert_query)
        history_result = self._client.search(index=NETWORK_INDEX, body=history_query)

        # --- Parse session geo/ASN ---
        # OLD CODE START — 2026-11-07 (live globe): always the destination, so an inbound row's
        # drawer showed the LAN device instead of the remote end
        # geo_info = self._parse_session_geo(session_result, dst_ip)
        # OLD CODE END
        geo_info = self._parse_session_geo(session_result, geo_ip or dst_ip)

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

        timeline_buckets = histogram_buckets(
            history_aggs.get("over_time")
        )  # date_histogram before #120
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

    @staticmethod
    def _hit_location(bucket: dict) -> tuple[Any, Any]:
        """(lat, lon) of a geo bucket's newest record (its `location` top_hits), or Nones."""
        hits = bucket.get("location", {}).get("hits", {}).get("hits", [])
        loc = (
            hits[0]
            .get("_source", {})
            .get("destination", {})
            .get("geo", {})
            .get("location")
            if hits
            else None
        )
        return (
            (loc.get("lat"), loc.get("lon")) if isinstance(loc, dict) else (None, None)
        )

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

        # OLD CODE START — NET-160 slice 2b-2: no stored rule.category values to link a category by
        # return {
        #     "timestamp": source.get("@timestamp", ""),
        #     "signature": signature,
        #     "severity": severity,
        #     "category": category,
        # }
        # OLD CODE END
        return {
            "timestamp": source.get("@timestamp", ""),
            "signature": signature,
            "severity": severity,
            "category": category,
            # the alert list's rule: the shown category links only when it is one of these
            "rule_category": rule_categories(rule),
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
            "protocols": {"tcp": 0, "udp": 0, "icmp": 0, "other": 0, "unknown": 0},
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
