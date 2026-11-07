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

from opensearchpy import NotFoundError, OpenSearchException

from services.device_fingerprint import _mac_from_hit
from services.excluded_ips import CONN_RECORDS
from storage.snapshot_search import QueryFailed, checked

logger = logging.getLogger("nettap.services.device_registry")


def record_time(epoch_ms: Any) -> str | None:
    """An OpenSearch date (epoch ms, as a sort value or max aggregation returns it) as ISO, or None."""
    if not isinstance(epoch_ms, (int, float)) or isinstance(epoch_ms, bool):
        return None
    return datetime.fromtimestamp(epoch_ms / 1000, timezone.utc).isoformat()


def hit_time(hit: dict) -> str | None:
    """The record time of a hit from a search sorted on @timestamp."""
    sort = hit.get("sort") or [None]
    return record_time(sort[0])


def _later(current: str | None, seen_at: str) -> str:
    """The later of a stored last_seen and a record time; an unreadable stored value gives way."""
    try:
        if current and datetime.fromisoformat(current) >= datetime.fromisoformat(
            seen_at
        ):
            return current
    except (TypeError, ValueError):
        pass
    return seen_at


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

    def __init__(self, client: Any, changelog: Any = None):
        self._client = client
        # ChangelogService; when set, a device's first write logs "device_joined"
        self._changelog = changelog
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
        # OLD CODE START — #76: kept every octet, so an 8-byte DHCP chaddr became a second device
        # return mac.strip().upper().replace("-", ":").replace(".", ":")
        # OLD CODE END
        octets = mac.strip().upper().replace("-", ":").replace(".", ":").split(":")
        # Zeek prints a DHCP chaddr at the client's own length; a UniFi AP sent 8 bytes on a VLAN
        return ":".join(octets[:6])

    def register_device(
        self,
        mac: str,
        ip: str | None = None,
        source: str = "unknown",
        metadata: dict | None = None,
        seen_at: str | None = None,
    ) -> dict:
        """Upsert a device record, merging enrichment data.

        Args:
            mac: MAC address (any format — normalized internally).
            ip: IP address currently associated with this device.
            source: Enrichment source name (e.g. "dhcp", "arp", "mdns", "unifi").
            metadata: Additional enrichment data from this source.
            seen_at: Time of the network record this comes from. Only a record moves
                last_seen; vendor and OS lookups (no record) leave it alone.

        Returns:
            The updated device document dict.
        """
        mac = self._normalize_mac(mac)
        metadata = metadata or {}
        now = datetime.now(timezone.utc).isoformat()

        # OLD CODE START — 2026-11-01: get_device() returns None on any error, so a timeout made a known device look new (first_seen reset, duplicate changelog event)
        # existing = self.get_device(mac)
        # OLD CODE END
        existing = self._get_existing(mac)

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
            if (
                metadata.get("category")
                and doc.get("category", CATEGORY_UNKNOWN) == CATEGORY_UNKNOWN
            ):
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

            # OLD CODE START — every update, a vendor or OS lookup included, made the device
            # "last seen" at the moment the registry ran: Home said "4m ago" for devices
            # last heard 24 min (or 17 h) earlier
            # # Update last_seen
            # doc["last_seen"] = now
            # OLD CODE END
            if seen_at:
                doc["last_seen"] = _later(doc.get("last_seen"), seen_at)

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
                "friendly_name": metadata.get("unifi_alias")
                or metadata.get("friendly_name"),
                # OLD CODE START — unchecked, unlike the merge branch above: a "media" vendor
                # category would land in a group the device grid doesn't have (#26)
                # "category": metadata.get("category", CATEGORY_UNKNOWN),
                # OLD CODE END
                "category": metadata.get("category")
                if metadata.get("category") in VALID_CATEGORIES
                else CATEGORY_UNKNOWN,
                # OLD CODE START — registration time, up to a refresh window after the record
                # "first_seen": now,
                # "last_seen": now,
                # OLD CODE END
                "first_seen": seen_at or now,
                "last_seen": seen_at or now,
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
                # OLD CODE START — every write waited ~1 s for a refresh, so a registry refresh
                # took ~1 min; readers of the search side call refresh_index() once per pass
                # refresh="wait_for",
                # OLD CODE END
            )
        except OpenSearchException as exc:
            logger.error("Failed to upsert device %s: %s", mac, exc)
            raise

        if existing is None and self._changelog is not None:
            self._log_new_device(doc, source)

        return doc

    def set_category(self, device: dict, category: str) -> bool:
        """Store a category on a known device without touching last_seen or its sources."""
        if category not in VALID_CATEGORIES or device.get("category") == category:
            return False
        try:
            # OLD CODE START — wait_for per write (see register_device)
            # self._client.index(
            #     index=DEVICES_INDEX, id=device["mac"], body={**device, "category": category}, refresh="wait_for"
            # )
            # OLD CODE END
            self._client.index(
                index=DEVICES_INDEX,
                id=device["mac"],
                body={**device, "category": category},
            )
            return True
        except OpenSearchException as exc:
            logger.error("Failed to set category on %s: %s", device["mac"], exc)
            return False

    def correct_last_seen(self) -> int:
        """Move back each last_seen that is later than the device's newest network record.

        Before seen_at, any update (a vendor or OS lookup included) stamped last_seen with the
        time it ran, and last_seen only moves forward, so a quiet device kept "13 h ago" for a
        last record 17 h old. No device is seen after its newest record, so a later value is
        wrong; a device whose records have all aged out is left alone. A failed search raises.
        Returns the number corrected.
        """
        fixed = 0
        for device in self.get_all_devices(limit=1000):
            mac, stored = device.get("mac"), device.get("last_seen")
            if not mac or not stored:
                continue
            body = {
                "size": 0,
                "query": {
                    "bool": {
                        "should": [
                            {"terms": {"source.ip": device.get("ips") or []}},
                            {"term": {"source.mac": mac.lower()}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "aggs": {"newest": {"max": {"field": "@timestamp"}}},
            }
            reply = self._client.search(index=NETWORK_INDEX, body=body)
            newest = record_time(
                (reply.get("aggregations") or {}).get("newest", {}).get("value")
            )
            if newest is None or _later(newest, stored) == newest:
                continue  # last_seen is no later than the newest record
            first = device.get("first_seen")
            self._client.index(
                index=DEVICES_INDEX,
                id=mac,
                body={
                    **device,
                    "last_seen": newest,
                    "first_seen": newest
                    if not first or _later(first, newest) == first
                    else first,
                },
            )
            fixed += 1
        return fixed

    def drop_reassigned_ips(self, assigned: dict[str, str]) -> int:
        """Remove each just-seen IP from every device other than the one it was seen on (#26).

        An IPv4 address belongs to one MAC at a time, so an IP left on another device is a
        DHCP reassignment or an old mis-filing (routed traffic carrying the router's MAC).
        0.0.0.0 (a DHCP client's address before it has one) is dropped everywhere.

        Returns:
            Number of devices updated.
        """
        owner = {ip: self._normalize_mac(mac) for ip, mac in assigned.items()}
        count = 0
        self.refresh_index()  # the devices registered just before must be searchable
        for device in self.get_all_devices(limit=1000):
            mac, ips = device.get("mac"), device.get("ips") or []
            keep = [ip for ip in ips if ip != "0.0.0.0" and owner.get(ip, mac) == mac]
            if len(keep) == len(ips):
                continue
            try:
                # OLD CODE START — wait_for per write (see register_device)
                # self._client.index(index=DEVICES_INDEX, id=mac, body={**device, "ips": keep}, refresh="wait_for")
                # OLD CODE END
                self._client.index(
                    index=DEVICES_INDEX, id=mac, body={**device, "ips": keep}
                )
                count += 1
            except OpenSearchException as exc:
                logger.error("Failed to drop moved IPs from %s: %s", mac, exc)
        return count

    def merge_long_macs(self) -> int:
        """Fold entries stored under a MAC longer than 6 octets into their real device (#76).

        Keeps the long entry's IPs and names; the real device's last_seen is left alone.

        Returns:
            Number of entries merged.
        """
        self.refresh_index()
        count = 0
        for device in self.get_all_devices(limit=1000):
            long_mac = device.get("mac") or ""
            if len(long_mac.split(":")) <= 6:
                continue
            mac = self._normalize_mac(long_mac)
            try:
                real = self._get_existing(mac)
                if real is None:
                    merged = {**device, "mac": mac}
                else:
                    merged = {
                        **real,
                        "ips": list(
                            dict.fromkeys(
                                (real.get("ips") or []) + (device.get("ips") or [])
                            )
                        ),
                        "hostnames": list(
                            dict.fromkeys(
                                (real.get("hostnames") or [])
                                + (device.get("hostnames") or [])
                            )
                        ),
                    }
                self._client.index(index=DEVICES_INDEX, id=mac, body=merged)
                self._client.delete(index=DEVICES_INDEX, id=long_mac)
                count += 1
                logger.info("Merged registry entry %s into %s", long_mac, mac)
            except OpenSearchException as exc:
                logger.error("Failed to merge registry entry %s: %s", long_mac, exc)
        return count

    def refresh_index(self) -> None:
        """Make every write so far visible to searches (get by id never needs this).

        Writes don't wait for a refresh, so a pass that lists devices calls this once first.
        """
        try:
            self._client.indices.refresh(index=DEVICES_INDEX)
        except OpenSearchException as exc:
            # The index refreshes itself within a second anyway; the pass just reads older data
            logger.warning("Failed to refresh %s: %s", DEVICES_INDEX, exc)

    def _get_existing(self, mac: str) -> dict | None:
        """The stored device doc, or None only when OpenSearch says it does not exist.

        Any other error raises, so a failed lookup never re-creates a known device.
        """
        try:
            return self._client.get(index=DEVICES_INDEX, id=mac).get("_source")
        except NotFoundError:
            return None

    def _log_new_device(self, doc: dict, source: str) -> None:
        """Record a device's first sighting on the Changelog page."""
        ip = doc["ips"][0] if doc["ips"] else None
        where = f" at {ip}" if ip else ""
        self._changelog.log_event(
            "device_joined",
            f"New device {doc['mac']}",
            f"First seen{where} (source: {source})",
            {"mac": doc["mac"], "ip": ip, "source": source},
            # NET-158: the device's first record, not when this refresh registered it
            timestamp=doc["first_seen"],
        )

    def get_device(self, mac: str) -> dict | None:
        """Retrieve a device by MAC address.

        Returns:
            Device document dict, or None if not found. Any other error raises (#96).
        """
        mac = self._normalize_mac(mac)
        # OLD CODE START — #96: any failure read as "Device not found" (404)
        # try:
        #     result = self._client.get(index=DEVICES_INDEX, id=mac)
        #     return result.get("_source")
        # except OpenSearchException:
        #     return None
        # OLD CODE END
        try:
            result = self._client.get(index=DEVICES_INDEX, id=mac)
        except NotFoundError:
            return None
        return result.get("_source")

    def get_devices(self, macs: list[str]) -> dict[str, dict]:
        """{normalized MAC: device} for the MACs the registry knows, in one request."""
        ids = sorted({self._normalize_mac(m) for m in macs if m})
        if not ids:
            return {}
        try:
            result = self._client.mget(index=DEVICES_INDEX, body={"ids": ids})
        except NotFoundError:
            return {}
        return {
            d["_id"]: d["_source"] for d in result.get("docs", []) if d.get("found")
        }

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

        # OLD CODE START — #96: [] read as "no devices known"
        # try:
        #     result = self._client.search(index=DEVICES_INDEX, body=query)
        #     return [hit["_source"] for hit in result.get("hits", {}).get("hits", [])]
        # except OpenSearchException as exc:
        #     logger.error("Failed to list devices: %s", exc)
        #     return []
        # OLD CODE END
        result = self._client.search(index=DEVICES_INDEX, body=query)
        return [hit["_source"] for hit in result.get("hits", {}).get("hits", [])]

    def count_first_seen_since(self, since: str) -> int:
        """How many devices NetTap first saw at or after `since` (an ISO timestamp)."""
        result = self._client.count(
            index=DEVICES_INDEX,
            body={"query": {"range": {"first_seen": {"gte": since}}}},
        )
        return int(result.get("count", 0))

    def get_device_traffic(self, mac: str, from_ts: str, to_ts: str) -> dict:
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
            {"term": {"source.mac": mac}},
            {"term": {"source.mac": mac.lower()}},
        ]
        for ip in ips:
            should_clauses.append({"term": {"source.ip": ip}})

        query = {
            "size": 0,
            # hits.total is shown as a count; without this OpenSearch stops at 10,000
            "track_total_hits": True,
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
                        # connection_count counts connections, not DNS/SSL logs or alerts
                        CONN_RECORDS,
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
                # #89: the MAC page shows in/out and per-destination bytes; without these it read 0
                "outbound_bytes": {"sum": {"field": "source.bytes", "missing": 0}},
                "inbound_bytes": {"sum": {"field": "destination.bytes", "missing": 0}},
                "protocols": {"terms": {"field": "network.transport", "size": 10}},
                # OLD CODE START — #89: connection counts only
                # "top_destinations": {"terms": {"field": "destination.ip", "size": 20}},
                # OLD CODE END
                # Ranked by bytes: the MAC page draws byte bars with ranks (by connection count
                # its #1 read 673 KB and its #8 507 MB)
                "top_destinations": {
                    # #90: ordered by a sum, so each shard must return every destination to rank exactly
                    "terms": {
                        "field": "destination.ip",
                        "size": 20,
                        "order": {"bytes": "desc"},
                        "shard_size": 10_000,
                    },
                    "aggs": {
                        "bytes": {
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
                    },
                },
            },
        }

        # OLD CODE START — #96: a failure read as a device with no traffic
        # try:
        #     result = self._client.search(index=NETWORK_INDEX, body=query)
        # except OpenSearchException as exc:
        #     logger.error("Failed to get traffic for device %s: %s", mac, exc)
        #     return {"mac": mac, "total_bytes": 0, "inbound_bytes": 0, "outbound_bytes": 0,
        #             "connection_count": 0, "protocols": [], "top_protocols": [], "top_destinations": []}
        # OLD CODE END
        result = self._client.search(index=NETWORK_INDEX, body=query)

        aggs = result.get("aggregations", {})
        hits_total = result.get("hits", {}).get("total", {})
        connection_count = (
            hits_total.get("value", 0) if isinstance(hits_total, dict) else hits_total
        )

        protocol_buckets = aggs.get("protocols", {}).get("buckets", [])
        protocols = [b["key"] for b in protocol_buckets]
        # OLD CODE START — #89: connections only, so the MAC page drew every bar as 0 bytes
        # top_destinations = [
        #     {"ip": b["key"], "connections": b["doc_count"]}
        #     for b in aggs.get("top_destinations", {}).get("buckets", [])
        # ]
        # OLD CODE END
        top_destinations = [
            {
                "ip": b["key"],
                "connections": b["doc_count"],
                "bytes": int(b.get("bytes", {}).get("value") or 0),
            }
            for b in aggs.get("top_destinations", {}).get("buckets", [])
        ]

        return {
            "mac": mac,
            "total_bytes": aggs.get("total_bytes", {}).get("value", 0) or 0,
            "inbound_bytes": int(aggs.get("inbound_bytes", {}).get("value") or 0),
            "outbound_bytes": int(aggs.get("outbound_bytes", {}).get("value") or 0),
            "connection_count": connection_count,
            "protocols": protocols,
            # the shape the MAC page reads; `protocols` stays for other callers
            "top_protocols": [
                {"name": b["key"], "count": b["doc_count"]} for b in protocol_buckets
            ],
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

        # OLD CODE START — #96: [] read as "no device matches"
        # try:
        #     result = self._client.search(index=DEVICES_INDEX, body=query)
        #     return [hit["_source"] for hit in result.get("hits", {}).get("hits", [])]
        # except OpenSearchException as exc:
        #     logger.error("Device search failed for '%s': %s", query_str, exc)
        #     return []
        # OLD CODE END
        result = self._client.search(index=DEVICES_INDEX, body=query)
        return [hit["_source"] for hit in result.get("hits", {}).get("hits", [])]

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

    def get_name(self, device: dict) -> str | None:
        """The name Home shows for a device, or None where it would show the vendor or MAC."""
        name = self.get_display_name(device)
        return (
            None
            if name in (device.get("manufacturer"), device.get("mac", "Unknown"))
            else name
        )

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
                        # OLD CODE START — 2026-11-01: Malcolm fills dhcp.id from zeek.dhcp.trans_id, which dhcp.log never has, so this matched nothing
                        # {"exists": {"field": "dhcp.id"}},
                        # OLD CODE END
                        # Malcolm tags Zeek dhcp.log and ja4d.log records with service "dhcp"
                        {"term": {"network.protocol": "dhcp"}},
                        {"exists": {"field": "source.mac"}},
                    ]
                }
            },
            # OLD CODE START — 2026-11-01: dhcp.ip is Arkime-only; Malcolm merges the assigned IP into dhcp.host, so dhcp.host[0] can be an IP
            # "_source": [
            #     "source.mac",
            #     "source.ip",
            #     "dhcp.host",
            #     "dhcp.ip",
            # ],
            # OLD CODE END
            "_source": [
                "source.mac",
                "source.ip",
                "zeek.dhcp.host_name",
                "zeek.dhcp.assigned_ip",
            ],
            "sort": [{"@timestamp": {"order": "desc"}}],
        }

        count = 0
        try:
            result = checked(
                self._client.search(index=NETWORK_INDEX, body=query), "DHCP enrichment"
            )
            seen_macs: set[str] = set()
            for hit in result.get("hits", {}).get("hits", []):
                src = hit.get("_source", {})
                # OLD CODE START — 2026-11-01: Malcolm stores source.mac as a list, which crashed the set lookup below
                # mac = src.get("source.mac") or src.get("source", {}).get("mac")
                # OLD CODE END
                mac = _mac_from_hit(hit)
                if not mac or mac in seen_macs:
                    continue
                seen_macs.add(mac)

                # OLD CODE START — 2026-11-01: read Malcolm's zeek.dhcp fields, see the _source note above
                # # Arkime stores DHCP fields under nested "dhcp" object
                # dhcp_obj = src.get("dhcp", {})
                # dhcp_ip_val = dhcp_obj.get("ip")
                # # dhcp.ip may be a list in Arkime
                # if isinstance(dhcp_ip_val, list):
                #     dhcp_ip_val = dhcp_ip_val[0] if dhcp_ip_val else None
                # ip = (
                #     dhcp_ip_val
                #     or src.get("source.ip")
                #     or src.get("source", {}).get("ip")
                # )
                # dhcp_host_val = dhcp_obj.get("host")
                # if isinstance(dhcp_host_val, list):
                #     dhcp_host_val = dhcp_host_val[0] if dhcp_host_val else None
                # hostname = dhcp_host_val
                # OLD CODE END
                zeek_dhcp = src.get("zeek", {}).get("dhcp", {})
                ip = zeek_dhcp.get("assigned_ip") or src.get("source", {}).get("ip")
                if (
                    ip == "0.0.0.0"
                ):  # a DISCOVER/REQUEST from a client with no address yet
                    ip = None
                hostname = zeek_dhcp.get("host_name")
                # vendor_class not reliably available in Arkime DHCP data
                vendor_class = None

                metadata: dict[str, Any] = {}
                if hostname:
                    metadata["hostname"] = hostname
                if vendor_class:
                    metadata["vendor_class"] = vendor_class

                self.register_device(
                    mac=mac,
                    ip=ip,
                    source="dhcp",
                    metadata=metadata,
                    seen_at=hit_time(hit),
                )
                count += 1

        except (OpenSearchException, QueryFailed) as exc:
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
                    "terms": {"field": "source.mac", "size": 500},
                    "aggs": {
                        "ips": {"terms": {"field": "source.ip", "size": 10}},
                    },
                }
            },
        }

        count = 0
        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
            buckets = (
                result.get("aggregations", {}).get("by_mac", {}).get("buckets", [])
            )
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
                        {"wildcard": {"dns.host": "*.local"}},
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
            result = checked(
                self._client.search(index=NETWORK_INDEX, body=query), "mDNS enrichment"
            )
            seen_macs: set[str] = set()
            for hit in result.get("hits", {}).get("hits", []):
                src = hit.get("_source", {})
                # OLD CODE START — 2026-11-01: Malcolm stores source.mac as a list, which crashed the set lookup below
                # mac = src.get("source.mac") or src.get("source", {}).get("mac")
                # OLD CODE END
                mac = _mac_from_hit(hit)
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
                    hostname = (
                        dns_query.split(".")[0] if "." in dns_query else dns_query
                    )

                    self.register_device(
                        mac=mac,
                        ip=ip,
                        source="mdns",
                        metadata={"hostname": hostname, "mdns_query": dns_query},
                        seen_at=hit_time(hit),
                    )
                    count += 1

        except (OpenSearchException, QueryFailed) as exc:
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
            result = checked(
                self._client.search(index=NETWORK_INDEX, body=query), "SSDP enrichment"
            )
            seen_macs: set[str] = set()
            for hit in result.get("hits", {}).get("hits", []):
                src = hit.get("_source", {})
                # OLD CODE START — 2026-11-01: Malcolm stores source.mac as a list, which crashed the set lookup below
                # mac = src.get("source.mac") or src.get("source", {}).get("mac")
                # OLD CODE END
                mac = _mac_from_hit(hit)
                if not mac or mac in seen_macs:
                    continue
                seen_macs.add(mac)

                ip = src.get("source.ip") or src.get("source", {}).get("ip")
                user_agent = src.get("http.useragent") or src.get("http", {}).get(
                    "useragent"
                )

                metadata: dict[str, Any] = {}
                if user_agent:
                    metadata["ssdp_user_agent"] = user_agent
                    # Try to extract a friendly name from UPnP user agent
                    # e.g. "Google-Home/1.0" -> "Google Home"
                    parts = user_agent.split("/")
                    if parts:
                        metadata["hostname"] = parts[0].replace("-", " ")

                self.register_device(
                    mac=mac,
                    ip=ip,
                    source="ssdp",
                    metadata=metadata,
                    seen_at=hit_time(hit),
                )
                count += 1

        except (OpenSearchException, QueryFailed) as exc:
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
        self.refresh_index()  # names and IPs from this refresh's enrichers must be searchable
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
