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

from services.excluded_ips import CONN_RECORDS, build_excluded_ips_filter
from storage.all_buckets import all_buckets

logger = logging.getLogger("nettap.services.lan_anomaly_detector")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")
# an ARP record where the sender announces its own address (sender IP = target IP)
GRATUITOUS_ARP = {
    "script": {
        "script": {
            "lang": "painless",
            "source": (
                "doc['source.ip'].size() > 0 && doc['destination.ip'].size() > 0 "
                "&& doc['source.ip'].value.equals(doc['destination.ip'].value)"
            ),
        }
    }
}
DHCP_SERVER_PORT = 67
# broadcast and "no address yet": a request to these names no server
NOT_A_HOST = ["255.255.255.255", "0.0.0.0"]


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


# Per IP: how many MACs used it and the 10 busiest of them
_MAC_AGGS = {
    "mac_count": {"cardinality": {"field": "source.mac"}},
    "macs": {"terms": {"field": "source.mac", "size": 10}},
}


def _ips_with_many_macs(client: Any, bool_clause: dict, ip_field: str) -> list[dict]:
    """Every IP of the matching ARP records that more than one MAC used, busiest first."""
    buckets, complete = all_buckets(
        client,
        NETWORK_INDEX,
        {"bool": bool_clause},
        [{"ip": {"terms": {"field": ip_field}}}],
        _MAC_AGGS,
    )
    if not complete:
        logger.warning(
            "ARP scan by %s stopped at %d IPs; result is partial",
            ip_field,
            len(buckets),
        )
    many = [
        {**b, "key": b["key"]["ip"]}
        for b in buckets
        if (b.get("mac_count") or {}).get("value", 0) > 1
    ]
    return sorted(many, key=lambda b: b.get("doc_count", 0), reverse=True)


class LANAnomalyDetector:
    """Detects ARP spoofing, rogue DHCP, and IP conflicts from Zeek logs."""

    def __init__(self, client: Any):
        self._client = client

    def detect_arp_spoofing(
        self,
        from_ts: str,
        to_ts: str,
        excluded_ips: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Detect ARP spoofing: multiple MAC addresses claiming the same IP.

        Queries Zeek ARP logs and looks for IPs associated with more than
        one MAC address in the time range.
        """
        excluded = build_excluded_ips_filter(excluded_ips or [])
        bool_clause: dict = {
            "filter": [
                _time_range_filter(from_ts, to_ts),
                {"term": {"event.provider": "zeek"}},
                {"term": {"event.dataset": "arp"}},
            ]
        }
        if excluded:
            bool_clause["must_not"] = excluded

        # OLD CODE START — #96: the >1-MAC filter only saw the 500 busiest IPs
        # query = {
        #     "size": 0,
        #     "query": {"bool": bool_clause},
        #     "aggs": {
        #         "by_ip": {
        #             "terms": {
        #                 "field": "source.ip",
        #                 "size": 500,
        #             },
        #             "aggs": {
        #                 "mac_count": {
        #                     "cardinality": {
        #                         "field": "source.mac",
        #                     }
        #                 },
        #                 "macs": {
        #                     "terms": {
        #                         "field": "source.mac",
        #                         "size": 10,
        #                     }
        #                 },
        #                 "mac_filter": {
        #                     "bucket_selector": {
        #                         "buckets_path": {"count": "mac_count"},
        #                         "script": "params.count > 1",
        #                     }
        #                 },
        #             },
        #         }
        #     },
        # }
        #
        # try:
        #     result = self._client.search(index=NETWORK_INDEX, body=query)
        # except Exception as exc:
        #     logger.error("ARP spoofing detection failed: %s", exc)
        #     return []
        #
        # buckets = result.get("aggregations", {}).get("by_ip", {}).get("buckets", [])
        # OLD CODE END
        # OLD CODE START — #96: a failed query read as "no ARP spoofing detected"
        # try:
        #     buckets = _ips_with_many_macs(self._client, bool_clause, "source.ip")
        # except Exception as exc:
        #     logger.error("ARP spoofing detection failed: %s", exc)
        #     return []
        # OLD CODE END
        buckets = _ips_with_many_macs(self._client, bool_clause, "source.ip")

        alerts: list[dict[str, Any]] = []
        for b in buckets:
            ip = b["key"]
            macs = [m["key"] for m in b.get("macs", {}).get("buckets", [])]
            mac_count = b.get("mac_count", {}).get("value", 0)

            if mac_count > 1:
                alerts.append(
                    {
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
                    }
                )

        return alerts

    def detect_rogue_dhcp(
        self,
        from_ts: str,
        to_ts: str,
        excluded_ips: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Detect rogue DHCP servers: more than one device answering DHCP in the time range.

        A home or small-office network should have exactly one DHCP server. A device is a
        server if it sends from UDP port 67, or answers a unicast request on it; one device
        serving several networks (one address per VLAN) is one server, so they group by MAC.
        """
        # OLD CODE START — Zeek's DHCP records name the client, not the server (source.ip is the
        # address the client was given), so every device that renewed a lease, except the
        # busiest, was a "critical" rogue DHCP server (the G11: 192.168.1.89, 10.10.0.108, ...)
        # excluded = build_excluded_ips_filter(excluded_ips or [])
        # bool_clause: dict = {
        #     "filter": [
        #         _time_range_filter(from_ts, to_ts),
        #         {"term": {"event.provider": "zeek"}},
        #         {"term": {"event.dataset": "dhcp"}},
        #     ]
        # }
        # if excluded:
        #     bool_clause["must_not"] = excluded
        #
        # query = {
        #     "size": 0,
        #     "query": {"bool": bool_clause},
        #     "aggs": {
        #         "dhcp_servers": {
        #             "terms": {
        #                 "field": "source.ip",
        #                 "size": 20,
        #             },
        #             "aggs": {
        #                 "server_mac": {
        #                     "terms": {
        #                         "field": "source.mac",
        #                         "size": 5,
        #                     }
        #                 },
        #                 "first_seen": {"min": {"field": "@timestamp"}},
        #                 "last_seen": {"max": {"field": "@timestamp"}},
        #             },
        #         }
        #     },
        # }
        #
        # # OLD CODE START — #96: a failed query read as "no rogue DHCP server"
        # # try:
        # #     result = self._client.search(index=NETWORK_INDEX, body=query)
        # # except Exception as exc:
        # #     logger.error("Rogue DHCP detection failed: %s", exc)
        # #     return []
        # # OLD CODE END
        # result = self._client.search(index=NETWORK_INDEX, body=query)
        #
        # # OLD CODE START — #96: the top 20 servers only; a 21st DHCP server went unreported
        # # buckets = (
        # #     result.get("aggregations", {}).get("dhcp_servers", {}).get("buckets", [])
        # # )
        # # OLD CODE END
        # servers = query["aggs"]["dhcp_servers"]
        # buckets = complete_terms(
        #     self._client, NETWORK_INDEX, query["query"],
        #     result.get("aggregations", {}).get("dhcp_servers", {}),
        #     {"terms": {"field": servers["terms"]["field"]}}, aggs=servers["aggs"],
        # )
        #
        # alerts: list[dict[str, Any]] = []
        #
        # if len(buckets) > 1:
        #     # Multiple DHCP servers detected — flag all but the most active
        #     # as potentially rogue
        #     buckets_sorted = sorted(
        #         buckets, key=lambda x: x.get("doc_count", 0), reverse=True
        #     )
        #     legitimate = buckets_sorted[0]["key"]
        #
        #     for b in buckets_sorted[1:]:
        #         server_ip = b["key"]
        #         server_macs = [
        #             m["key"] for m in b.get("server_mac", {}).get("buckets", [])
        #         ]
        #         alerts.append(
        #             {
        #                 "type": "rogue_dhcp",
        #                 "server_ip": server_ip,
        #                 "server_mac": server_macs[0] if server_macs else "unknown",
        #                 "offer_count": b.get("doc_count", 0),
        #                 "legitimate_server": legitimate,
        #                 "severity": "critical",
        #                 "description": (
        #                     f"Rogue DHCP server detected at {server_ip} "
        #                     f"(legitimate: {legitimate}) — "
        #                     f"{b.get('doc_count', 0)} offers sent"
        #                 ),
        #                 "detected_at": datetime.now(timezone.utc).isoformat(),
        #             }
        #         )
        #
        # OLD CODE END
        excluded = build_excluded_ips_filter(excluded_ips or [])
        servers: dict[str, dict[str, Any]] = {}
        for side, answered in (
            ("source", []),
            ("destination", [{"range": {"destination.packets": {"gt": 0}}}]),
        ):
            query = {
                "bool": {
                    "filter": [
                        _time_range_filter(from_ts, to_ts),
                        CONN_RECORDS,
                        {"term": {"network.transport": "udp"}},
                        {"term": {f"{side}.port": DHCP_SERVER_PORT}},
                        *answered,
                    ],
                    "must_not": [*excluded, {"terms": {f"{side}.ip": NOT_A_HOST}}],
                }
            }
            pairs, complete = all_buckets(
                self._client,
                NETWORK_INDEX,
                query,
                [
                    {
                        "mac": {
                            "terms": {"field": f"{side}.mac", "missing_bucket": True}
                        }
                    },
                    {"ip": {"terms": {"field": f"{side}.ip"}}},
                ],
            )
            if not complete:
                logger.warning(
                    "Rogue DHCP: %s scan stopped at %d MAC/IP pairs", side, len(pairs)
                )
            for b in pairs:
                mac, ip = b["key"]["mac"], b["key"]["ip"]
                seen = servers.get(mac or ip, {"mac": mac, "ips": set(), "count": 0})
                servers[mac or ip] = {
                    **seen,
                    "ips": seen["ips"] | {ip},
                    "count": seen["count"] + b["doc_count"],
                }

        alerts: list[dict[str, Any]] = []
        if len(servers) > 1:
            # the busiest is taken as the network's own; every other one is flagged
            main, *others = sorted(
                servers.values(), key=lambda v: v["count"], reverse=True
            )
            legitimate = sorted(main["ips"])[0]
            for v in others:
                ips = sorted(v["ips"])
                alerts.append(
                    {
                        "type": "rogue_dhcp",
                        "server_ip": ips[0],
                        "server_ips": ips,
                        "server_mac": v["mac"] or "unknown",
                        "offer_count": v["count"],
                        "legitimate_server": legitimate,
                        "severity": "critical",
                        "description": (
                            f"A second DHCP server is answering on your network: {', '.join(ips)}"
                            f" ({v['mac'] or 'MAC unknown'}), {v['count']} DHCP exchanges. "
                            f"Your network's own is {legitimate}. Devices that take an address "
                            f"from it can be sent the wrong gateway or DNS."
                        ),
                        "detected_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
        return alerts

    def detect_ip_conflicts(
        self,
        from_ts: str,
        to_ts: str,
        excluded_ips: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Detect IP conflicts from gratuitous ARP observations.

        Looks for gratuitous ARP (source IP == destination IP) entries
        where different MACs are announcing the same IP.
        """
        excluded = build_excluded_ips_filter(excluded_ips or [])
        bool_clause: dict = {
            "filter": [
                _time_range_filter(from_ts, to_ts),
                {"term": {"event.provider": "zeek"}},
                {"term": {"event.dataset": "arp"}},
            ]
        }
        if excluded:
            bool_clause["must_not"] = excluded

        # OLD CODE START — #96: the >1-MAC filter only saw the 500 busiest IPs
        # # Query for gratuitous ARP (where source and dest IP match)
        # query = {
        #     "size": 0,
        #     "query": {"bool": bool_clause},
        #     "aggs": {
        #         "by_dest_ip": {
        #             "terms": {
        #                 "field": "destination.ip",
        #                 "size": 500,
        #             },
        #             "aggs": {
        #                 "src_mac_count": {
        #                     "cardinality": {
        #                         "field": "source.mac",
        #                     }
        #                 },
        #                 "src_macs": {
        #                     "terms": {
        #                         "field": "source.mac",
        #                         "size": 10,
        #                     }
        #                 },
        #                 "conflict_filter": {
        #                     "bucket_selector": {
        #                         "buckets_path": {"count": "src_mac_count"},
        #                         "script": "params.count > 1",
        #                     }
        #                 },
        #             },
        #         }
        #     },
        # }
        #
        # try:
        #     result = self._client.search(index=NETWORK_INDEX, body=query)
        # except Exception as exc:
        #     logger.error("IP conflict detection failed: %s", exc)
        #     return []
        #
        # buckets = (
        #     result.get("aggregations", {}).get("by_dest_ip", {}).get("buckets", [])
        # )
        # OLD CODE END
        # OLD CODE START — #96: a failed query read as "no IP conflicts"
        # try:
        #     buckets = _ips_with_many_macs(self._client, bool_clause, "destination.ip")
        # except Exception as exc:
        #     logger.error("IP conflict detection failed: %s", exc)
        #     return []
        # OLD CODE END
        # OLD CODE START — every ARP record grouped by target IP, counting sender MACs: everyone
        # who asked "who has 192.168.1.1?" made the router an "IP conflict"
        # buckets = _ips_with_many_macs(self._client, bool_clause, "destination.ip")
        # OLD CODE END
        # gratuitous ARP only (a host announcing its own address: sender IP = target IP), by sender
        announcements = {
            **bool_clause,
            "filter": [*bool_clause["filter"], GRATUITOUS_ARP],
        }
        buckets = _ips_with_many_macs(self._client, announcements, "source.ip")

        alerts: list[dict[str, Any]] = []
        for b in buckets:
            ip = b["key"]
            macs = [m["key"] for m in b.get("macs", {}).get("buckets", [])]
            mac_count = b.get("mac_count", {}).get("value", 0)

            if mac_count > 1:
                alerts.append(
                    {
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
                    }
                )

        return alerts

    def arp_recorded(self, from_ts: str, to_ts: str) -> bool:
        """Whether any ARP record exists in the range. Zeek logs no ARP unless a package adds
        it; without records, ARP spoofing and IP conflicts can't be seen, only not found."""
        reply = self._client.count(
            index=NETWORK_INDEX,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            _time_range_filter(from_ts, to_ts),
                            {"term": {"event.provider": "zeek"}},
                            {"term": {"event.dataset": "arp"}},
                        ]
                    }
                }
            },
        )
        return reply.get("count", 0) > 0

    def get_all_anomalies(
        self,
        from_ts: str,
        to_ts: str,
        excluded_ips: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Run all detection methods and return combined anomaly list."""
        anomalies: list[dict[str, Any]] = []
        anomalies.extend(
            self.detect_arp_spoofing(from_ts, to_ts, excluded_ips=excluded_ips)
        )
        anomalies.extend(
            self.detect_rogue_dhcp(from_ts, to_ts, excluded_ips=excluded_ips)
        )
        anomalies.extend(
            self.detect_ip_conflicts(from_ts, to_ts, excluded_ips=excluded_ips)
        )

        # Sort by severity (critical > high > medium > low)
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        anomalies.sort(key=lambda a: severity_order.get(a.get("severity", "low"), 4))

        return anomalies
