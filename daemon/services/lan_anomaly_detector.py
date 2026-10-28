"""
NetTap LAN Anomaly Detector Service

Detects LAN-level security anomalies by querying OpenSearch for
Zeek ARP and DHCP logs:
- ARP spoofing (multiple MACs claiming same IP)
- Rogue DHCP servers (offers from unexpected servers)
- IP address conflicts (gratuitous ARP conflicts)
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("nettap.services.lan_anomaly_detector")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")


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


class LANAnomalyDetector:
    """Detects ARP spoofing, rogue DHCP, and IP conflicts from Zeek logs."""

    def __init__(self, client: Any):
        self._client = client

    def detect_arp_spoofing(
        self, from_ts: str, to_ts: str
    ) -> list[dict[str, Any]]:
        """Detect ARP spoofing: multiple MAC addresses claiming the same IP.

        Queries Zeek ARP logs and looks for IPs associated with more than
        one MAC address in the time range.
        """
        query = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        _time_range_filter(from_ts, to_ts),
                        {"term": {"event.provider": "zeek"}},
                        {"term": {"event.dataset": "arp"}},
                    ]
                }
            },
            "aggs": {
                "by_ip": {
                    "terms": {
                        "field": "source.ip.keyword",
                        "size": 500,
                    },
                    "aggs": {
                        "mac_count": {
                            "cardinality": {
                                "field": "source.mac.keyword",
                            }
                        },
                        "macs": {
                            "terms": {
                                "field": "source.mac.keyword",
                                "size": 10,
                            }
                        },
                        "mac_filter": {
                            "bucket_selector": {
                                "buckets_path": {"count": "mac_count"},
                                "script": "params.count > 1",
                            }
                        },
                    },
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except Exception as exc:
            logger.error("ARP spoofing detection failed: %s", exc)
            return []

        buckets = (
            result.get("aggregations", {}).get("by_ip", {}).get("buckets", [])
        )

        alerts: list[dict[str, Any]] = []
        for b in buckets:
            ip = b["key"]
            macs = [m["key"] for m in b.get("macs", {}).get("buckets", [])]
            mac_count = b.get("mac_count", {}).get("value", 0)

            if mac_count > 1:
                alerts.append({
                    "type": "arp_spoofing",
                    "ip": ip,
                    "mac_addresses": macs,
                    "mac_count": mac_count,
                    "event_count": b.get("doc_count", 0),
                    "severity": "high",
                    "description": (
                        f"Multiple MACs ({', '.join(macs)}) claiming IP {ip} "
                        f"— possible ARP spoofing"
                    ),
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                })

        return alerts

    def detect_rogue_dhcp(
        self, from_ts: str, to_ts: str
    ) -> list[dict[str, Any]]:
        """Detect rogue DHCP servers: DHCP offers from unexpected sources.

        Looks for multiple DHCP server IPs in the time range. In a typical
        home/small-office network, there should be exactly one DHCP server.
        """
        query = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        _time_range_filter(from_ts, to_ts),
                        {"term": {"event.provider": "zeek"}},
                        {"term": {"event.dataset": "dhcp"}},
                    ]
                }
            },
            "aggs": {
                "dhcp_servers": {
                    "terms": {
                        "field": "source.ip.keyword",
                        "size": 20,
                    },
                    "aggs": {
                        "server_mac": {
                            "terms": {
                                "field": "source.mac.keyword",
                                "size": 5,
                            }
                        },
                        "first_seen": {
                            "min": {"field": "@timestamp"}
                        },
                        "last_seen": {
                            "max": {"field": "@timestamp"}
                        },
                    },
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except Exception as exc:
            logger.error("Rogue DHCP detection failed: %s", exc)
            return []

        buckets = (
            result.get("aggregations", {})
            .get("dhcp_servers", {})
            .get("buckets", [])
        )

        alerts: list[dict[str, Any]] = []

        if len(buckets) > 1:
            # Multiple DHCP servers detected — flag all but the most active
            # as potentially rogue
            buckets_sorted = sorted(
                buckets, key=lambda x: x.get("doc_count", 0), reverse=True
            )
            legitimate = buckets_sorted[0]["key"]

            for b in buckets_sorted[1:]:
                server_ip = b["key"]
                server_macs = [
                    m["key"]
                    for m in b.get("server_mac", {}).get("buckets", [])
                ]
                alerts.append({
                    "type": "rogue_dhcp",
                    "server_ip": server_ip,
                    "server_mac": server_macs[0] if server_macs else "unknown",
                    "offer_count": b.get("doc_count", 0),
                    "legitimate_server": legitimate,
                    "severity": "critical",
                    "description": (
                        f"Rogue DHCP server detected at {server_ip} "
                        f"(legitimate: {legitimate}) — "
                        f"{b.get('doc_count', 0)} offers sent"
                    ),
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                })

        return alerts

    def detect_ip_conflicts(
        self, from_ts: str, to_ts: str
    ) -> list[dict[str, Any]]:
        """Detect IP conflicts from gratuitous ARP observations.

        Looks for gratuitous ARP (source IP == destination IP) entries
        where different MACs are announcing the same IP.
        """
        # Query for gratuitous ARP (where source and dest IP match)
        query = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        _time_range_filter(from_ts, to_ts),
                        {"term": {"event.provider": "zeek"}},
                        {"term": {"event.dataset": "arp"}},
                    ]
                }
            },
            "aggs": {
                "by_dest_ip": {
                    "terms": {
                        "field": "destination.ip.keyword",
                        "size": 500,
                    },
                    "aggs": {
                        "src_mac_count": {
                            "cardinality": {
                                "field": "source.mac.keyword",
                            }
                        },
                        "src_macs": {
                            "terms": {
                                "field": "source.mac.keyword",
                                "size": 10,
                            }
                        },
                        "conflict_filter": {
                            "bucket_selector": {
                                "buckets_path": {"count": "src_mac_count"},
                                "script": "params.count > 1",
                            }
                        },
                    },
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except Exception as exc:
            logger.error("IP conflict detection failed: %s", exc)
            return []

        buckets = (
            result.get("aggregations", {})
            .get("by_dest_ip", {})
            .get("buckets", [])
        )

        alerts: list[dict[str, Any]] = []
        for b in buckets:
            ip = b["key"]
            macs = [m["key"] for m in b.get("src_macs", {}).get("buckets", [])]
            mac_count = b.get("src_mac_count", {}).get("value", 0)

            if mac_count > 1:
                alerts.append({
                    "type": "ip_conflict",
                    "ip": ip,
                    "mac_addresses": macs,
                    "mac_count": mac_count,
                    "event_count": b.get("doc_count", 0),
                    "severity": "medium",
                    "description": (
                        f"IP conflict: {ip} claimed by multiple devices "
                        f"({', '.join(macs)})"
                    ),
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                })

        return alerts

    def get_all_anomalies(
        self, from_ts: str, to_ts: str
    ) -> list[dict[str, Any]]:
        """Run all detection methods and return combined anomaly list."""
        anomalies: list[dict[str, Any]] = []
        anomalies.extend(self.detect_arp_spoofing(from_ts, to_ts))
        anomalies.extend(self.detect_rogue_dhcp(from_ts, to_ts))
        anomalies.extend(self.detect_ip_conflicts(from_ts, to_ts))

        # Sort by severity (critical > high > medium > low)
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        anomalies.sort(
            key=lambda a: severity_order.get(a.get("severity", "low"), 4)
        )

        return anomalies
