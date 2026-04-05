"""
NetTap Device Registry Service — Central device inventory backed by OpenSearch.

Maintains a ``nettap-devices`` index keyed by MAC address. Each document
stores every known IP, hostname, manufacturer, category, enrichment data,
and first/last seen timestamps. Enrichment sources (DHCP, ARP, mDNS, SSDP,
OUI, JA3, UniFi) are merged incrementally — no data is ever overwritten,
only appended or updated if newer.

Name priority (highest wins):
    1. UniFi alias (user-set in controller UI)
    2. User-set friendly name (via API)
    3. DHCP hostname (option 12)
    4. mDNS name (.local domain)
    5. OUI manufacturer fallback
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

from opensearchpy import OpenSearchException

logger = logging.getLogger("nettap.services.device_registry")

DEVICES_INDEX = "nettap-devices"
NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# Device categories
CATEGORY_UNKNOWN = "unknown"
VALID_CATEGORIES = {"computer", "phone", "iot", "infrastructure", "unknown"}

# Index mapping for nettap-devices
_DEVICES_INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "mac": {"type": "keyword"},
            "ips": {"type": "keyword"},
            "hostnames": {"type": "keyword"},
            "manufacturer": {"type": "keyword"},
            "friendly_name": {"type": "keyword"},
            "category": {"type": "keyword"},
            "first_seen": {"type": "date"},
            "last_seen": {"type": "date"},
            "is_new": {"type": "boolean"},
            "enrichment_sources": {"type": "object", "enabled": False},
        }
    },
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
    },
}


class DeviceRegistry:
    """Central device registry backed by OpenSearch.

    All methods accept a raw opensearch-py client. The registry upserts
    device documents using the MAC address as the document ID.
    """

    def __init__(self, client: Any):
        self._client = client
        self._ensure_index()

    def _ensure_index(self) -> None:
        """Create the nettap-devices index if it does not exist."""
        try:
            if not self._client.indices.exists(index=DEVICES_INDEX):
                self._client.indices.create(
                    index=DEVICES_INDEX, body=_DEVICES_INDEX_MAPPING
                )
                logger.info("Created %s index", DEVICES_INDEX)
        except OpenSearchException as exc:
            logger.error("Failed to ensure %s index: %s", DEVICES_INDEX, exc)

    @staticmethod
    def _normalize_mac(mac: str) -> str:
        """Normalize MAC to uppercase colon-separated format."""
        return mac.strip().upper().replace("-", ":").replace(".", ":")

    def register_device(
        self,
        mac: str,
        ip: str | None = None,
        source: str = "unknown",
        metadata: dict | None = None,
    ) -> dict:
        """Upsert a device record, merging enrichment data.

        Args:
            mac: MAC address (any format — normalized internally).
            ip: IP address currently associated with this device.
            source: Enrichment source name (e.g. "dhcp", "arp", "mdns", "unifi").
            metadata: Additional enrichment data from this source.

        Returns:
            The updated device document dict.
        """
        mac = self._normalize_mac(mac)
        metadata = metadata or {}
        now = datetime.now(timezone.utc).isoformat()

        existing = self.get_device(mac)

        if existing:
            # Merge into existing record
            doc = existing

            # Merge IPs
            ips = set(doc.get("ips") or [])
            if ip:
                ips.add(ip)
            doc["ips"] = sorted(ips)

            # Merge hostnames
            hostnames = set(doc.get("hostnames") or [])
            new_hostname = metadata.get("hostname")
            if new_hostname:
                hostnames.add(new_hostname)
            doc["hostnames"] = sorted(hostnames)

            # Update manufacturer if provided and not already set
            if metadata.get("manufacturer") and not doc.get("manufacturer"):
                doc["manufacturer"] = metadata["manufacturer"]

            # Update category if provided and current is unknown
            if metadata.get("category") and doc.get("category", CATEGORY_UNKNOWN) == CATEGORY_UNKNOWN:
                cat = metadata["category"]
                if cat in VALID_CATEGORIES:
                    doc["category"] = cat

            # Update friendly_name based on priority
            if metadata.get("unifi_alias"):
                doc["friendly_name"] = metadata["unifi_alias"]
            elif metadata.get("friendly_name") and not doc.get("friendly_name"):
                doc["friendly_name"] = metadata["friendly_name"]

            # Merge enrichment sources
            enrichment = doc.get("enrichment_sources") or {}
            enrichment[source] = {
                **metadata,
                "last_updated": now,
            }
            doc["enrichment_sources"] = enrichment

            # Update last_seen
            doc["last_seen"] = now

            # No longer new after first update
            doc["is_new"] = False

        else:
            # New device
            hostnames = []
            if metadata.get("hostname"):
                hostnames.append(metadata["hostname"])

            doc = {
                "mac": mac,
                "ips": [ip] if ip else [],
                "hostnames": hostnames,
                "manufacturer": metadata.get("manufacturer"),
                "friendly_name": metadata.get("unifi_alias") or metadata.get("friendly_name"),
                "category": metadata.get("category", CATEGORY_UNKNOWN),
                "first_seen": now,
                "last_seen": now,
                "is_new": True,
                "enrichment_sources": {
                    source: {
                        **metadata,
                        "last_updated": now,
                    }
                },
            }

        try:
            self._client.index(
                index=DEVICES_INDEX,
                id=mac,
                body=doc,
                refresh="wait_for",
            )
        except OpenSearchException as exc:
            logger.error("Failed to upsert device %s: %s", mac, exc)
            raise

        return doc

    def get_device(self, mac: str) -> dict | None:
        """Retrieve a device by MAC address.

        Returns:
            Device document dict, or None if not found.
        """
        mac = self._normalize_mac(mac)
        try:
            result = self._client.get(index=DEVICES_INDEX, id=mac)
            return result.get("_source")
        except OpenSearchException:
            return None

    def get_all_devices(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """List all known devices with pagination.

        Returns:
            List of device document dicts.
        """
        query = {
            "size": limit,
            "from": offset,
            "query": {"match_all": {}},
            "sort": [{"last_seen": {"order": "desc"}}],
        }

        try:
            result = self._client.search(index=DEVICES_INDEX, body=query)
            return [hit["_source"] for hit in result.get("hits", {}).get("hits", [])]
        except OpenSearchException as exc:
            logger.error("Failed to list devices: %s", exc)
            return []

    def get_device_traffic(
        self, mac: str, from_ts: str, to_ts: str
    ) -> dict:
        """Get traffic summary for a device by MAC address.

        Queries arkime_sessions3-* for connections where source.mac matches.

        Returns:
            Dict with total_bytes, connection_count, protocols, top_destinations.
        """
        mac = self._normalize_mac(mac)

        # Also look up all known IPs for this device to query by IP as well
        device = self.get_device(mac)
        ips = device.get("ips", []) if device else []

        # Build should clauses: match by MAC or any known IP
        should_clauses: list[dict] = [
            {"term": {"source.mac.keyword": mac}},
            {"term": {"source.mac.keyword": mac.lower()}},
        ]
        for ip in ips:
            should_clauses.append({"term": {"source.ip": ip}})

        query = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "range": {
                                "@timestamp": {
                                    "gte": from_ts,
                                    "lte": to_ts,
                                    "format": "strict_date_optional_time",
                                }
                            }
                        },
                    ],
                    "should": should_clauses,
                    "minimum_should_match": 1,
                }
            },
            "aggs": {
                "total_bytes": {
                    "sum": {
                        "script": {
                            "source": (
                                "(doc['source.bytes'].size() > 0 ? doc['source.bytes'].value : 0)"
                                " + (doc['destination.bytes'].size() > 0 ? doc['destination.bytes'].value : 0)"
                            ),
                            "lang": "painless",
                        }
                    }
                },
                "protocols": {
                    "terms": {"field": "network.transport.keyword", "size": 10}
                },
                "top_destinations": {
                    "terms": {"field": "destination.ip.keyword", "size": 20}
                },
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except OpenSearchException as exc:
            logger.error("Failed to get traffic for device %s: %s", mac, exc)
            return {
                "mac": mac,
                "total_bytes": 0,
                "connection_count": 0,
                "protocols": [],
                "top_destinations": [],
            }

        aggs = result.get("aggregations", {})
        hits_total = result.get("hits", {}).get("total", {})
        connection_count = (
            hits_total.get("value", 0) if isinstance(hits_total, dict) else hits_total
        )

        protocols = [
            b["key"]
            for b in aggs.get("protocols", {}).get("buckets", [])
        ]
        top_destinations = [
            {"ip": b["key"], "connections": b["doc_count"]}
            for b in aggs.get("top_destinations", {}).get("buckets", [])
        ]

        return {
            "mac": mac,
            "total_bytes": aggs.get("total_bytes", {}).get("value", 0) or 0,
            "connection_count": connection_count,
            "protocols": protocols,
            "top_destinations": top_destinations,
        }

    def search_devices(self, query_str: str) -> list[dict]:
        """Search devices by name, IP, MAC, or manufacturer.

        Uses a multi_match query across key fields.

        Returns:
            List of matching device document dicts.
        """
        query = {
            "size": 50,
            "query": {
                "bool": {
                    "should": [
                        {"wildcard": {"mac": f"*{query_str.upper()}*"}},
                        {"wildcard": {"ips": f"*{query_str}*"}},
                        {"wildcard": {"hostnames": f"*{query_str.lower()}*"}},
                        {"wildcard": {"manufacturer": f"*{query_str}*"}},
                        {"wildcard": {"friendly_name": f"*{query_str}*"}},
                    ],
                    "minimum_should_match": 1,
                }
            },
        }

        try:
            result = self._client.search(index=DEVICES_INDEX, body=query)
            return [hit["_source"] for hit in result.get("hits", {}).get("hits", [])]
        except OpenSearchException as exc:
            logger.error("Device search failed for '%s': %s", query_str, exc)
            return []

    def get_display_name(self, device: dict) -> str:
        """Resolve the best display name for a device using priority rules.

        Priority: UniFi alias > user-set friendly_name > DHCP hostname >
                  mDNS name > manufacturer fallback
        """
        # Check enrichment sources for UniFi alias
        enrichment = device.get("enrichment_sources") or {}
        unifi_data = enrichment.get("unifi", {})
        if unifi_data.get("unifi_alias"):
            return unifi_data["unifi_alias"]

        # User-set friendly name
        if device.get("friendly_name"):
            return device["friendly_name"]

        # DHCP hostname
        dhcp_data = enrichment.get("dhcp", {})
        if dhcp_data.get("hostname"):
            return dhcp_data["hostname"]

        # mDNS name
        mdns_data = enrichment.get("mdns", {})
        if mdns_data.get("hostname"):
            return mdns_data["hostname"]

        # Hostnames list
        hostnames = device.get("hostnames") or []
        if hostnames:
            return hostnames[0]

        # Manufacturer fallback
        if device.get("manufacturer"):
            return device["manufacturer"]

        return device.get("mac", "Unknown")

    # ------------------------------------------------------------------
    # Passive enrichment methods
    # ------------------------------------------------------------------

    def enrich_from_dhcp(self, from_ts: str, to_ts: str) -> int:
        """Query DHCP logs and register/update devices.

        Extracts: hostname (option 12), vendor class (option 60), IP assignment.

        Returns:
            Number of devices enriched.
        """
        query = {
            "size": 500,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "range": {
                                "@timestamp": {
                                    "gte": from_ts,
                                    "lte": to_ts,
                                    "format": "strict_date_optional_time",
                                }
                            }
                        },
                        {"exists": {"field": "dhcp.id"}},
                        {"exists": {"field": "source.mac"}},
                    ]
                }
            },
            "_source": [
                "source.mac",
                "source.ip",
                "dhcp.host",
                "dhcp.ip",
            ],
            "sort": [{"@timestamp": {"order": "desc"}}],
        }

        count = 0
        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
            seen_macs: set[str] = set()
            for hit in result.get("hits", {}).get("hits", []):
                src = hit.get("_source", {})
                mac = src.get("source.mac") or src.get("source", {}).get("mac")
                if not mac or mac in seen_macs:
                    continue
                seen_macs.add(mac)

                # Arkime stores DHCP fields under nested "dhcp" object
                dhcp_obj = src.get("dhcp", {})
                dhcp_ip_val = dhcp_obj.get("ip")
                # dhcp.ip may be a list in Arkime
                if isinstance(dhcp_ip_val, list):
                    dhcp_ip_val = dhcp_ip_val[0] if dhcp_ip_val else None
                ip = (
                    dhcp_ip_val
                    or src.get("source.ip")
                    or src.get("source", {}).get("ip")
                )
                dhcp_host_val = dhcp_obj.get("host")
                if isinstance(dhcp_host_val, list):
                    dhcp_host_val = dhcp_host_val[0] if dhcp_host_val else None
                hostname = dhcp_host_val
                # vendor_class not reliably available in Arkime DHCP data
                vendor_class = None

                metadata: dict[str, Any] = {}
                if hostname:
                    metadata["hostname"] = hostname
                if vendor_class:
                    metadata["vendor_class"] = vendor_class

                self.register_device(mac=mac, ip=ip, source="dhcp", metadata=metadata)
                count += 1

        except OpenSearchException as exc:
            logger.error("DHCP enrichment query failed: %s", exc)

        logger.info("DHCP enrichment: processed %d devices", count)
        return count

    def enrich_from_arp(self, from_ts: str, to_ts: str) -> int:
        """Query conn logs for IP-MAC mappings (ARP-like snooping).

        Returns:
            Number of devices enriched.
        """
        query = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "range": {
                                "@timestamp": {
                                    "gte": from_ts,
                                    "lte": to_ts,
                                    "format": "strict_date_optional_time",
                                }
                            }
                        },
                        {"exists": {"field": "source.mac"}},
                    ]
                }
            },
            "aggs": {
                "by_mac": {
                    "terms": {"field": "source.mac.keyword", "size": 500},
                    "aggs": {
                        "ips": {"terms": {"field": "source.ip.keyword", "size": 10}},
                    },
                }
            },
        }

        count = 0
        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
            buckets = result.get("aggregations", {}).get("by_mac", {}).get("buckets", [])
            for bucket in buckets:
                mac = bucket["key"]
                ip_buckets = bucket.get("ips", {}).get("buckets", [])
                for ip_bucket in ip_buckets:
                    ip = ip_bucket["key"]
                    self.register_device(mac=mac, ip=ip, source="arp", metadata={})
                    count += 1
        except OpenSearchException as exc:
            logger.error("ARP enrichment query failed: %s", exc)

        logger.info("ARP enrichment: processed %d MAC-IP pairs", count)
        return count

    def enrich_from_mdns(self, from_ts: str, to_ts: str) -> int:
        """Query DNS logs for .local domains (mDNS) and extract device names.

        Returns:
            Number of devices enriched.
        """
        query = {
            "size": 200,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "range": {
                                "@timestamp": {
                                    "gte": from_ts,
                                    "lte": to_ts,
                                    "format": "strict_date_optional_time",
                                }
                            }
                        },
                        {"term": {"network.protocol": "dns"}},
                        {"wildcard": {"dns.host.keyword": "*.local"}},
                        {"exists": {"field": "source.mac"}},
                    ]
                }
            },
            "_source": [
                "source.mac",
                "source.ip",
                "dns.host",
            ],
            "sort": [{"@timestamp": {"order": "desc"}}],
        }

        count = 0
        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
            seen_macs: set[str] = set()
            for hit in result.get("hits", {}).get("hits", []):
                src = hit.get("_source", {})
                mac = src.get("source.mac") or src.get("source", {}).get("mac")
                if not mac or mac in seen_macs:
                    continue
                seen_macs.add(mac)

                ip = src.get("source.ip") or src.get("source", {}).get("ip")
                # Arkime stores dns.host as a list
                dns_host_val = src.get("dns.host") or src.get("dns", {}).get("host")
                if isinstance(dns_host_val, list):
                    # Find the .local entry in the list
                    dns_query = next(
                        (h for h in dns_host_val if h.endswith(".local")), None
                    )
                else:
                    dns_query = dns_host_val

                if dns_query and dns_query.endswith(".local"):
                    # Extract friendly name from mDNS (e.g. "iPhone._tcp.local" -> "iPhone")
                    hostname = dns_query.split(".")[0] if "." in dns_query else dns_query

                    self.register_device(
                        mac=mac,
                        ip=ip,
                        source="mdns",
                        metadata={"hostname": hostname, "mdns_query": dns_query},
                    )
                    count += 1

        except OpenSearchException as exc:
            logger.error("mDNS enrichment query failed: %s", exc)

        logger.info("mDNS enrichment: processed %d devices", count)
        return count

    def enrich_from_ssdp(self, from_ts: str, to_ts: str) -> int:
        """Query HTTP logs for SSDP/UPnP discovery traffic.

        Returns:
            Number of devices enriched.
        """
        query = {
            "size": 200,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "range": {
                                "@timestamp": {
                                    "gte": from_ts,
                                    "lte": to_ts,
                                    "format": "strict_date_optional_time",
                                }
                            }
                        },
                        {"term": {"network.protocol": "http"}},
                        {"exists": {"field": "source.mac"}},
                    ],
                    "should": [
                        {"match": {"http.uri": "ssdp"}},
                        {"match": {"http.useragent": "UPnP"}},
                        {"term": {"destination.port": 1900}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "_source": [
                "source.mac",
                "source.ip",
                "http.useragent",
                "http.uri",
            ],
            "sort": [{"@timestamp": {"order": "desc"}}],
        }

        count = 0
        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
            seen_macs: set[str] = set()
            for hit in result.get("hits", {}).get("hits", []):
                src = hit.get("_source", {})
                mac = src.get("source.mac") or src.get("source", {}).get("mac")
                if not mac or mac in seen_macs:
                    continue
                seen_macs.add(mac)

                ip = src.get("source.ip") or src.get("source", {}).get("ip")
                user_agent = (
                    src.get("http.useragent")
                    or src.get("http", {}).get("useragent")
                )

                metadata: dict[str, Any] = {}
                if user_agent:
                    metadata["ssdp_user_agent"] = user_agent
                    # Try to extract a friendly name from UPnP user agent
                    # e.g. "Google-Home/1.0" -> "Google Home"
                    parts = user_agent.split("/")
                    if parts:
                        metadata["hostname"] = parts[0].replace("-", " ")

                self.register_device(mac=mac, ip=ip, source="ssdp", metadata=metadata)
                count += 1

        except OpenSearchException as exc:
            logger.error("SSDP enrichment query failed: %s", exc)

        logger.info("SSDP enrichment: processed %d devices", count)
        return count

    def enrich_with_oui(self, mac_lookup_service: Any) -> int:
        """Enrich all devices with OUI manufacturer lookup.

        Args:
            mac_lookup_service: A MacLookupService instance.

        Returns:
            Number of devices enriched.
        """
        devices = self.get_all_devices(limit=1000)
        count = 0

        for device in devices:
            if device.get("manufacturer"):
                continue  # Already has manufacturer

            mac = device.get("mac")
            if not mac:
                continue

            try:
                result = mac_lookup_service.lookup(mac)
                if result.get("found") and result.get("vendor"):
                    self.register_device(
                        mac=mac,
                        source="oui",
                        metadata={"manufacturer": result["vendor"]},
                    )
                    count += 1
            except Exception as exc:
                logger.debug("OUI lookup failed for %s: %s", mac, exc)

        logger.info("OUI enrichment: updated %d devices", count)
        return count

    def enrich_with_ja3(
        self,
        device_fingerprint: Any,
        from_ts: str,
        to_ts: str,
    ) -> int:
        """Enrich devices with OS hint from JA3/JA4 TLS fingerprinting.

        Args:
            device_fingerprint: A DeviceFingerprint instance.
            from_ts: Start of time range (ISO format).
            to_ts: End of time range (ISO format).

        Returns:
            Number of devices enriched.
        """
        devices = self.get_all_devices(limit=1000)
        count = 0

        for device in devices:
            ips = device.get("ips") or []
            mac = device.get("mac")
            if not ips or not mac:
                continue

            # Check if we already have an OS hint
            enrichment = device.get("enrichment_sources") or {}
            if enrichment.get("ja3", {}).get("os_hint"):
                continue

            for ip in ips:
                os_hint = device_fingerprint.get_os_hint(
                    self._client, ip, from_ts, to_ts
                )
                if os_hint:
                    self.register_device(
                        mac=mac,
                        source="ja3",
                        metadata={"os_hint": os_hint},
                    )
                    count += 1
                    break  # One OS hint per device is enough

        logger.info("JA3 enrichment: updated %d devices", count)
        return count
