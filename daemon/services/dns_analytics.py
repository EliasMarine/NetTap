"""
NetTap DNS Analytics Service

Queries OpenSearch arkime_sessions3-* for DNS data from Zeek logs.
Provides domain aggregation, NXDOMAIN detection, query type distribution,
timeline data, suspicious pattern detection, and DNS tunneling detection.
"""

import logging
import math
import os
from collections import Counter
from typing import Any

logger = logging.getLogger("nettap.services.dns_analytics")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# Zeek DNS event filters for the Malcolm unified index
_ZEEK_DNS_FILTERS = [
    {"term": {"event.provider": "zeek"}},
    {"term": {"event.dataset": "dns"}},
]


def _time_range_filter(from_ts: str, to_ts: str) -> dict:
    """Build an OpenSearch range filter on '@timestamp'."""
    return {
        "range": {
            "@timestamp": {
                "gte": from_ts,
                "lte": to_ts,
                "format": "strict_date_optional_time",
            }
        }
    }


def _base_bool_filter(from_ts: str, to_ts: str) -> list[dict]:
    """Return common filter clauses for DNS queries."""
    return [_time_range_filter(from_ts, to_ts), *_ZEEK_DNS_FILTERS]


class DNSAnalytics:
    """DNS analytics service backed by OpenSearch."""

    def __init__(self, client: Any):
        self._client = client

    def get_top_domains(
        self, from_ts: str, to_ts: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return most-queried domains in the time range."""
        query = {
            "size": 0,
            "query": {"bool": {"filter": _base_bool_filter(from_ts, to_ts)}},
            "aggs": {
                "top_domains": {
                    "terms": {
                        "field": "zeek.dns.query.keyword",
                        "size": limit,
                        "order": {"_count": "desc"},
                    },
                    "aggs": {
                        "unique_clients": {
                            "cardinality": {"field": "source.ip.keyword"}
                        }
                    },
                }
            },
        }

        result = self._client.search(index=NETWORK_INDEX, body=query)
        buckets = (
            result.get("aggregations", {}).get("top_domains", {}).get("buckets", [])
        )

        return [
            {
                "domain": b["key"],
                "count": b["doc_count"],
                "unique_clients": b.get("unique_clients", {}).get("value", 0),
            }
            for b in buckets
        ]

    def get_device_dns(
        self, device_ip: str, from_ts: str, to_ts: str
    ) -> list[dict[str, Any]]:
        """Return all DNS queries for a specific device IP."""
        query = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        *_base_bool_filter(from_ts, to_ts),
                        {"term": {"source.ip.keyword": device_ip}},
                    ]
                }
            },
            "aggs": {
                "domains": {
                    "terms": {
                        "field": "zeek.dns.query.keyword",
                        "size": 200,
                        "order": {"_count": "desc"},
                    },
                    "aggs": {
                        "query_types": {
                            "terms": {
                                "field": "zeek.dns.qtype_name.keyword",
                                "size": 10,
                            }
                        }
                    },
                }
            },
        }

        result = self._client.search(index=NETWORK_INDEX, body=query)
        buckets = (
            result.get("aggregations", {}).get("domains", {}).get("buckets", [])
        )

        return [
            {
                "domain": b["key"],
                "count": b["doc_count"],
                "query_types": [
                    {"type": t["key"], "count": t["doc_count"]}
                    for t in b.get("query_types", {}).get("buckets", [])
                ],
            }
            for b in buckets
        ]

    def get_nxdomain_errors(
        self, from_ts: str, to_ts: str
    ) -> list[dict[str, Any]]:
        """Return domains with NXDOMAIN (rcode=3) responses."""
        query = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        *_base_bool_filter(from_ts, to_ts),
                        {"term": {"zeek.dns.rcode_name.keyword": "NXDOMAIN"}},
                    ]
                }
            },
            "aggs": {
                "nxdomains": {
                    "terms": {
                        "field": "zeek.dns.query.keyword",
                        "size": 100,
                        "order": {"_count": "desc"},
                    },
                    "aggs": {
                        "clients": {
                            "terms": {
                                "field": "source.ip.keyword",
                                "size": 10,
                            }
                        }
                    },
                }
            },
        }

        result = self._client.search(index=NETWORK_INDEX, body=query)
        buckets = (
            result.get("aggregations", {}).get("nxdomains", {}).get("buckets", [])
        )

        return [
            {
                "domain": b["key"],
                "count": b["doc_count"],
                "clients": [
                    c["key"] for c in b.get("clients", {}).get("buckets", [])
                ],
            }
            for b in buckets
        ]

    def get_query_type_distribution(
        self, from_ts: str, to_ts: str
    ) -> list[dict[str, Any]]:
        """Return counts by DNS query type (A, AAAA, CNAME, MX, TXT, etc.)."""
        query = {
            "size": 0,
            "query": {"bool": {"filter": _base_bool_filter(from_ts, to_ts)}},
            "aggs": {
                "query_types": {
                    "terms": {
                        "field": "zeek.dns.qtype_name.keyword",
                        "size": 20,
                    }
                }
            },
        }

        result = self._client.search(index=NETWORK_INDEX, body=query)
        buckets = (
            result.get("aggregations", {}).get("query_types", {}).get("buckets", [])
        )

        return [
            {"type": b["key"], "count": b["doc_count"]} for b in buckets
        ]

    def get_dns_timeline(
        self, from_ts: str, to_ts: str, interval: str = "1m"
    ) -> list[dict[str, Any]]:
        """Return DNS query volume over time."""
        valid_intervals = {
            "1m", "5m", "10m", "15m", "30m", "1h", "3h", "6h", "12h", "1d"
        }
        if interval not in valid_intervals:
            interval = "5m"

        query = {
            "size": 0,
            "query": {"bool": {"filter": _base_bool_filter(from_ts, to_ts)}},
            "aggs": {
                "timeline": {
                    "date_histogram": {
                        "field": "@timestamp",
                        "fixed_interval": interval,
                        "min_doc_count": 0,
                        "extended_bounds": {
                            "min": from_ts,
                            "max": to_ts,
                        },
                    }
                }
            },
        }

        result = self._client.search(index=NETWORK_INDEX, body=query)
        buckets = (
            result.get("aggregations", {}).get("timeline", {}).get("buckets", [])
        )

        return [
            {
                "timestamp": b.get("key_as_string", b.get("key")),
                "count": b.get("doc_count", 0),
            }
            for b in buckets
        ]

    def get_suspicious_dns(
        self, from_ts: str, to_ts: str
    ) -> list[dict[str, Any]]:
        """Detect suspicious DNS patterns: long names, high frequency, TXT abuse."""
        suspicious: list[dict[str, Any]] = []

        # 1. Long domain names (potential DGA/tunneling)
        top = self.get_top_domains(from_ts, to_ts, limit=200)
        for entry in top:
            domain = entry["domain"]
            if len(domain) > 50:
                suspicious.append({
                    "type": "long_domain",
                    "domain": domain,
                    "length": len(domain),
                    "count": entry["count"],
                    "severity": "medium",
                    "description": f"Unusually long domain name ({len(domain)} chars) — potential data exfiltration or DGA",
                })

        # 2. High frequency single-domain queries (beaconing)
        for entry in top:
            if entry["count"] > 500 and entry["unique_clients"] <= 2:
                suspicious.append({
                    "type": "high_frequency",
                    "domain": entry["domain"],
                    "count": entry["count"],
                    "unique_clients": entry["unique_clients"],
                    "severity": "medium",
                    "description": f"High-frequency queries ({entry['count']}) from few clients — potential beaconing",
                })

        # 3. TXT record abuse
        txt_query = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        *_base_bool_filter(from_ts, to_ts),
                        {"term": {"zeek.dns.qtype_name.keyword": "TXT"}},
                    ]
                }
            },
            "aggs": {
                "txt_domains": {
                    "terms": {
                        "field": "zeek.dns.query.keyword",
                        "size": 20,
                        "order": {"_count": "desc"},
                    }
                }
            },
        }

        result = self._client.search(index=NETWORK_INDEX, body=txt_query)
        txt_buckets = (
            result.get("aggregations", {}).get("txt_domains", {}).get("buckets", [])
        )

        for b in txt_buckets:
            if b["doc_count"] > 50:
                suspicious.append({
                    "type": "txt_abuse",
                    "domain": b["key"],
                    "count": b["doc_count"],
                    "severity": "low",
                    "description": f"High TXT query volume ({b['doc_count']}) — TXT records can be used for data tunneling",
                })

        return suspicious

    def detect_dns_tunneling(
        self, from_ts: str, to_ts: str
    ) -> list[dict[str, Any]]:
        """Detect potential DNS tunneling via entropy analysis on query names.

        High-entropy subdomain labels often indicate encoded data (base32/64)
        being exfiltrated through DNS queries.
        """
        detections: list[dict[str, Any]] = []

        top = self.get_top_domains(from_ts, to_ts, limit=200)

        for entry in top:
            domain = entry["domain"]
            parts = domain.split(".")

            # Analyze longest label (usually the data-carrying subdomain)
            if len(parts) < 3:
                continue

            subdomain = parts[0]
            if len(subdomain) < 10:
                continue

            entropy = _shannon_entropy(subdomain)

            if entropy > 3.5:
                detections.append({
                    "domain": domain,
                    "subdomain": subdomain,
                    "entropy": round(entropy, 2),
                    "count": entry["count"],
                    "severity": "high" if entropy > 4.0 else "medium",
                    "description": (
                        f"High entropy ({entropy:.2f}) in subdomain label "
                        f"'{subdomain[:30]}...' — potential DNS tunneling"
                    ),
                })

        return detections

    def get_stats(
        self, from_ts: str, to_ts: str
    ) -> dict[str, Any]:
        """Return hero card stats: total queries, unique domains, NXDOMAIN count."""
        query = {
            "size": 0,
            "query": {"bool": {"filter": _base_bool_filter(from_ts, to_ts)}},
            "aggs": {
                "unique_domains": {
                    "cardinality": {"field": "zeek.dns.query.keyword"}
                },
                "nxdomain_count": {
                    "filter": {
                        "term": {"zeek.dns.rcode_name.keyword": "NXDOMAIN"}
                    }
                },
                "avg_rtt": {
                    "avg": {"field": "zeek.dns.rtt", "missing": 0}
                },
            },
        }

        result = self._client.search(index=NETWORK_INDEX, body=query)
        aggs = result.get("aggregations", {})
        hits_total = result.get("hits", {}).get("total", {})
        total_queries = (
            hits_total.get("value", 0)
            if isinstance(hits_total, dict)
            else hits_total
        )

        return {
            "total_queries": total_queries,
            "unique_domains": aggs.get("unique_domains", {}).get("value", 0),
            "nxdomain_count": aggs.get("nxdomain_count", {}).get("doc_count", 0),
            "avg_resolution_ms": round(
                (aggs.get("avg_rtt", {}).get("value", 0) or 0) * 1000, 2
            ),
        }


def _shannon_entropy(s: str) -> float:
    """Calculate Shannon entropy of a string."""
    if not s:
        return 0.0
    freq = Counter(s)
    length = len(s)
    return -sum(
        (count / length) * math.log2(count / length) for count in freq.values()
    )
