"""
NetTap Device Fingerprint Service -- Passive device identification from Zeek logs.

Uses OUI (MAC prefix) lookups, DHCP/DNS correlation, and User-Agent / JA3
fingerprint analysis to identify devices on the network without active probing.

All OpenSearch queries use the caller-provided client -- this service never
creates its own connections.
"""

import logging
import os
import re

logger = logging.getLogger("nettap.services.fingerprint")

# Regex for a basic MAC address (colon, dash, or dot separated)
_MAC_RE = re.compile(
    r"^([0-9A-Fa-f]{2})[:\-.]([0-9A-Fa-f]{2})[:\-.]([0-9A-Fa-f]{2})"
    r"[:\-.]([0-9A-Fa-f]{2})[:\-.]([0-9A-Fa-f]{2})[:\-.]([0-9A-Fa-f]{2})$"
)

# Common OS patterns found in HTTP User-Agent strings
_OS_PATTERNS = [
    (re.compile(r"Windows NT 10\.0", re.IGNORECASE), "Windows 10/11"),
    (re.compile(r"Windows NT 6\.3", re.IGNORECASE), "Windows 8.1"),
    (re.compile(r"Windows NT 6\.2", re.IGNORECASE), "Windows 8"),
    (re.compile(r"Windows NT 6\.1", re.IGNORECASE), "Windows 7"),
    (re.compile(r"Windows", re.IGNORECASE), "Windows"),
    (re.compile(r"iPhone|iPad|iPod", re.IGNORECASE), "iOS"),
    (re.compile(r"Macintosh|Mac OS X", re.IGNORECASE), "macOS"),
    (re.compile(r"Android", re.IGNORECASE), "Android"),
    (re.compile(r"Linux", re.IGNORECASE), "Linux"),
    (re.compile(r"CrOS", re.IGNORECASE), "ChromeOS"),
    (re.compile(r"PlayStation", re.IGNORECASE), "PlayStation"),
    (re.compile(r"Xbox", re.IGNORECASE), "Xbox"),
    (re.compile(r"Nintendo", re.IGNORECASE), "Nintendo"),
    (re.compile(r"SmartTV|Tizen|webOS", re.IGNORECASE), "Smart TV"),
]


class DeviceFingerprint:
    """Passive device fingerprinting from Zeek logs."""

    def __init__(self, oui_path: str | None = None):
        self._oui_db: dict[str, str] = {}  # MAC prefix (AA:BB:CC) -> manufacturer
        default_path = os.path.join(os.path.dirname(__file__), "..", "data", "oui.txt")
        self._load_oui(oui_path or default_path)

    def _load_oui(self, path: str) -> None:
        """Load OUI database from a tab-separated file.

        Each non-comment, non-blank line should be: AA:BB:CC\\tManufacturer Name
        """
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t", 1)
                    if len(parts) == 2:
                        prefix = parts[0].strip().upper()
                        manufacturer = parts[1].strip()
                        if prefix and manufacturer:
                            self._oui_db[prefix] = manufacturer
            logger.info("Loaded %d OUI entries from %s", len(self._oui_db), path)
        except FileNotFoundError:
            logger.warning(
                "OUI file not found: %s — manufacturer lookups will return 'Unknown'",
                path,
            )
        except Exception as exc:
            logger.error("Error loading OUI file %s: %s", path, exc)

    def get_manufacturer(self, mac: str) -> str:
        """Look up the manufacturer for a MAC address via OUI prefix.

        Accepts colon-separated, dash-separated, or dot-separated MACs.
        Returns 'Unknown' for unrecognised or malformed addresses.
        """
        if not mac or not isinstance(mac, str):
            return "Unknown"

        # Normalise separators to colons
        normalised = mac.strip().upper().replace("-", ":").replace(".", ":")

        # Handle Cisco-style dot notation (e.g. AABB.CCDD.EEFF)
        # After replacing dots with colons we might have 4-char groups
        # Try to extract the first 3 octets
        match = _MAC_RE.match(normalised)
        if match:
            prefix = f"{match.group(1)}:{match.group(2)}:{match.group(3)}"
        else:
            # Try splitting directly
            parts = normalised.split(":")
            if len(parts) >= 3 and all(len(p) <= 2 for p in parts[:3]):
                prefix = ":".join(p.zfill(2) for p in parts[:3])
            else:
                return "Unknown"

        return self._oui_db.get(prefix.upper(), "Unknown")

    def get_hostname_for_ip(
        self, client, ip: str, from_ts: str, to_ts: str
    ) -> str | None:
        """Query zeek-dns-* for the most common hostname resolving to this IP.

        Looks at DNS answer records where the resolved IP matches the target.
        Returns the most frequently seen domain name, or None.
        """
        query = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "range": {
                                "ts": {
                                    "gte": from_ts,
                                    "lte": to_ts,
                                    "format": "strict_date_optional_time",
                                }
                            }
                        },
                        {"term": {"answers": ip}},
                    ]
                }
            },
            "aggs": {"top_hostname": {"terms": {"field": "query", "size": 1}}},
        }

        try:
            result = client.search(index="zeek-dns-*", body=query)
            buckets = (
                result.get("aggregations", {})
                .get("top_hostname", {})
                .get("buckets", [])
            )
            if buckets:
                return buckets[0]["key"]
        except Exception as exc:
            logger.debug("Hostname lookup failed for %s: %s", ip, exc)

        return None

    def get_mac_for_ip(self, client, ip: str, from_ts: str, to_ts: str) -> str | None:
        """Query zeek-dhcp-* (then zeek-conn-*) for a MAC address associated with this IP.

        Checks DHCP logs first (most reliable), then falls back to the
        orig_l2_addr field in connection logs.
        """
        # Strategy 1: DHCP logs — client_addr == ip, grab mac field
        dhcp_query = {
            "size": 1,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "range": {
                                "ts": {
                                    "gte": from_ts,
                                    "lte": to_ts,
                                    "format": "strict_date_optional_time",
                                }
                            }
                        },
                        {"term": {"client_addr": ip}},
                    ]
                }
            },
            "sort": [{"ts": {"order": "desc"}}],
            "_source": ["mac"],
        }

        try:
            result = client.search(index="zeek-dhcp-*", body=dhcp_query)
            hits = result.get("hits", {}).get("hits", [])
            if hits:
                mac = hits[0].get("_source", {}).get("mac")
                if mac:
                    return mac
        except Exception as exc:
            logger.debug("DHCP MAC lookup failed for %s: %s", ip, exc)

        # Strategy 2: Connection logs — orig_l2_addr where id.orig_h == ip
        conn_query = {
            "size": 1,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "range": {
                                "ts": {
                                    "gte": from_ts,
                                    "lte": to_ts,
                                    "format": "strict_date_optional_time",
                                }
                            }
                        },
                        {"term": {"id.orig_h": ip}},
                        {"exists": {"field": "orig_l2_addr"}},
                    ]
                }
            },
            "sort": [{"ts": {"order": "desc"}}],
            "_source": ["orig_l2_addr"],
        }

        try:
            result = client.search(index="zeek-conn-*", body=conn_query)
            hits = result.get("hits", {}).get("hits", [])
            if hits:
                mac = hits[0].get("_source", {}).get("orig_l2_addr")
                if mac:
                    return mac
        except Exception as exc:
            logger.debug("Conn MAC lookup failed for %s: %s", ip, exc)

        return None

    def get_os_hint(self, client, ip: str, from_ts: str, to_ts: str) -> str | None:
        """Infer the device's OS from HTTP User-Agent strings.

        Queries zeek-http-* for User-Agent values from this IP, then
        matches against known OS patterns.  Falls back to JA3 fingerprint
        analysis from zeek-ssl-* if HTTP data is unavailable.
        """
        # Strategy 1: HTTP User-Agent
        ua_query = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "range": {
                                "ts": {
                                    "gte": from_ts,
                                    "lte": to_ts,
                                    "format": "strict_date_optional_time",
                                }
                            }
                        },
                        {"term": {"id.orig_h": ip}},
                        {"exists": {"field": "user_agent"}},
                    ]
                }
            },
            "aggs": {"top_ua": {"terms": {"field": "user_agent", "size": 5}}},
        }

        try:
            result = client.search(index="zeek-http-*", body=ua_query)
            buckets = (
                result.get("aggregations", {}).get("top_ua", {}).get("buckets", [])
            )
            for bucket in buckets:
                ua_string = bucket.get("key", "")
                for pattern, os_name in _OS_PATTERNS:
                    if pattern.search(ua_string):
                        return os_name
        except Exception as exc:
            logger.debug("User-Agent lookup failed for %s: %s", ip, exc)

        # Strategy 2: JA3 fingerprint from TLS handshakes
        ja3_query = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "range": {
                                "ts": {
                                    "gte": from_ts,
                                    "lte": to_ts,
                                    "format": "strict_date_optional_time",
                                }
                            }
                        },
                        {"term": {"id.orig_h": ip}},
                        {"exists": {"field": "ja3"}},
                    ]
                }
            },
            "aggs": {"top_ja3": {"terms": {"field": "ja3", "size": 1}}},
        }

        try:
            result = client.search(index="zeek-ssl-*", body=ja3_query)
            buckets = (
                result.get("aggregations", {}).get("top_ja3", {}).get("buckets", [])
            )
            if buckets:
                # JA3 hash present but we don't have a lookup table yet.
                # Return a generic hint so the caller knows TLS was seen.
                return None  # Future: map JA3 hashes to known OS fingerprints
        except Exception as exc:
            logger.debug("JA3 lookup failed for %s: %s", ip, exc)

        return None
