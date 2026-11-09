"""
NetTap Device Fingerprint Service -- Passive device identification from Arkime sessions.

Uses OUI (MAC prefix) lookups, DHCP/DNS correlation, and User-Agent
fingerprint analysis to identify devices on the network without active probing.

All OpenSearch queries target arkime_sessions3-* and use the caller-provided
client -- this service never creates its own connections.
"""

import logging
import os
import re

logger = logging.getLogger("nettap.services.fingerprint")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# Regex for a basic MAC address (colon, dash, or dot separated)
_MAC_RE = re.compile(
    r"^([0-9A-Fa-f]{2})[:\-.]([0-9A-Fa-f]{2})[:\-.]([0-9A-Fa-f]{2})"
    r"[:\-.]([0-9A-Fa-f]{2})[:\-.]([0-9A-Fa-f]{2})[:\-.]([0-9A-Fa-f]{2})$"
)

# Common OS patterns found in HTTP User-Agent strings
# OLD CODE START — DEV-8: generic names came first, so a Tizen/webOS TV (its UA says Linux)
# read "Linux" and an Xbox (Windows NT 10.0) "Windows 10/11"
# _OS_PATTERNS = [
#     (re.compile(r"Windows NT 10\.0", re.IGNORECASE), "Windows 10/11"),
#     (re.compile(r"Windows NT 6\.3", re.IGNORECASE), "Windows 8.1"),
#     (re.compile(r"Windows NT 6\.2", re.IGNORECASE), "Windows 8"),
#     (re.compile(r"Windows NT 6\.1", re.IGNORECASE), "Windows 7"),
#     (re.compile(r"Windows", re.IGNORECASE), "Windows"),
#     (re.compile(r"iPhone|iPad|iPod", re.IGNORECASE), "iOS"),
#     (re.compile(r"Macintosh|Mac OS X", re.IGNORECASE), "macOS"),
#     (re.compile(r"Android", re.IGNORECASE), "Android"),
#     (re.compile(r"Linux", re.IGNORECASE), "Linux"),
#     (re.compile(r"CrOS", re.IGNORECASE), "ChromeOS"),
#     (re.compile(r"PlayStation", re.IGNORECASE), "PlayStation"),
#     (re.compile(r"Xbox", re.IGNORECASE), "Xbox"),
#     (re.compile(r"Nintendo", re.IGNORECASE), "Nintendo"),
#     (re.compile(r"SmartTV|Tizen|webOS", re.IGNORECASE), "Smart TV"),
# ]
# OLD CODE END
# The first match wins, so specific platforms come before the generic OS names they embed
_OS_PATTERNS = [
    (re.compile(r"PlayStation", re.IGNORECASE), "PlayStation"),
    (re.compile(r"Xbox", re.IGNORECASE), "Xbox"),
    (re.compile(r"Nintendo", re.IGNORECASE), "Nintendo"),
    (re.compile(r"SmartTV|Tizen|webOS", re.IGNORECASE), "Smart TV"),
    (re.compile(r"CrOS", re.IGNORECASE), "ChromeOS"),
    (re.compile(r"Android", re.IGNORECASE), "Android"),
    (re.compile(r"iPhone|iPad|iPod", re.IGNORECASE), "iOS"),
    (re.compile(r"Windows NT 10\.0", re.IGNORECASE), "Windows 10/11"),
    (re.compile(r"Windows NT 6\.3", re.IGNORECASE), "Windows 8.1"),
    (re.compile(r"Windows NT 6\.2", re.IGNORECASE), "Windows 8"),
    (re.compile(r"Windows NT 6\.1", re.IGNORECASE), "Windows 7"),
    (re.compile(r"Windows", re.IGNORECASE), "Windows"),
    (re.compile(r"Macintosh|Mac OS X", re.IGNORECASE), "macOS"),
    (re.compile(r"Linux", re.IGNORECASE), "Linux"),
]


def _mac_from_hit(hit: dict) -> str | None:
    """Read source.mac from a search hit's nested _source (Malcolm may store a list)."""
    source = hit.get("_source", {}).get("source")
    mac = source.get("mac") if isinstance(source, dict) else None
    if isinstance(mac, list):
        mac = next((m for m in mac if m), None)
    return mac or None


def _oui_from_hit(hit: dict) -> str | None:
    """Read Malcolm's IEEE vendor name (source.oui) from a search hit, if it has one."""
    source = hit.get("_source", {}).get("source")
    oui = source.get("oui") if isinstance(source, dict) else None
    if isinstance(oui, list):
        oui = next((o for o in oui if o), None)
    return oui or None


# --- Per-IP lookup queries and parsers, shared by the get_* methods and lookup_many ---
_MSEARCH_IPS = 100  # 4 searches per IP: at most 400 in one _msearch request


def _in_range(from_ts: str, to_ts: str) -> dict:
    return {
        "range": {
            "@timestamp": {
                "gte": from_ts,
                "lte": to_ts,
                "format": "strict_date_optional_time",
            }
        }
    }


_MDNS_PORT = 5353
# names in DNS records that aren't a device's hostname (service instances, reverse lookups)
_NOT_HOSTNAMES = ("._tcp.", "._udp.", ".in-addr.arpa", ".ip6.arpa", "_asquic")


def _hostname_query(ip: str, from_ts: str, to_ts: str) -> dict:
    """The DNS names tied to this IP: unicast answers, and mDNS the device sent itself.

    OLD CODE START — #130: any DNS record listing the IP. Arkime keeps a session's names and
    IPs as two lists, and the router reflects mDNS between VLANs with every host's records in
    one session, so 192.168.1.188 (EliasMacStudio) took another Mac's name.
    return {"size": 0, "query": {"bool": {"filter": [_in_range(from_ts, to_ts),
            {"term": {"dns.ip": ip}}, {"term": {"network.protocol": "dns"}}]}},
            "aggs": {"top_hostname": {"terms": {"field": "dns.host", "size": 1}}}}
    OLD CODE END
    """
    return {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    _in_range(from_ts, to_ts),
                    {"term": {"dns.ip": ip}},
                    {"term": {"network.protocol": "dns"}},
                    {
                        "bool": {
                            "should": [
                                {"term": {"source.ip": ip}},
                                {
                                    "bool": {
                                        "must_not": [
                                            {"term": {"destination.port": _MDNS_PORT}},
                                            {"term": {"source.port": _MDNS_PORT}},
                                        ]
                                    }
                                },
                            ],
                            "minimum_should_match": 1,
                        }
                    },
                ]
            }
        },
        # several, so a device's service names ahead of its hostname can be skipped
        "aggs": {"top_hostname": {"terms": {"field": "dns.host", "size": 10}}},
    }


def _dhcp_mac_query(ip: str, from_ts: str, to_ts: str) -> dict:
    """Strategy 1: DHCP logs — source.ip == ip, newest record's source.mac."""
    return {
        "size": 1,
        "query": {
            "bool": {
                "filter": [
                    _in_range(from_ts, to_ts),
                    {"term": {"source.ip": ip}},
                    {"exists": {"field": "dhcp.id"}},
                ]
            }
        },
        "sort": [{"@timestamp": {"order": "desc"}}],
        "_source": ["source.mac", "source.oui"],
    }


def _conn_mac_query(ip: str, from_ts: str, to_ts: str) -> dict:
    """Strategy 2: Connection logs — the MAC most of this IP's conn records carry.

    OLD CODE START — the newest record's MAC: on a mirrored uplink, traffic routed
    between VLANs carries the router's MAC, so IoT devices could read as the UDM (#26)
    conn_query = {"size": 1, ..., "sort": [{"@timestamp": {"order": "desc"}}], ...}
    OLD CODE END
    Every routed flow also has a leg on the device's own VLAN with its real MAC, and
    internet traffic has only that leg, so the device's own MAC is the most common.
    """
    return {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    _in_range(from_ts, to_ts),
                    {"term": {"source.ip": ip}},
                    {"exists": {"field": "source.mac"}},
                ]
            }
        },
        "aggs": {
            "mac": {
                "terms": {"field": "source.mac", "size": 1},
                "aggs": {
                    "hit": {
                        "top_hits": {"size": 1, "_source": ["source.mac", "source.oui"]}
                    }
                },
            }
        },
    }


def _user_agent_query(ip: str, from_ts: str, to_ts: str) -> dict:
    """Strategy 1 of the OS hint: HTTP User-Agent strings from this IP."""
    return {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    _in_range(from_ts, to_ts),
                    {"term": {"source.ip": ip}},
                    {"exists": {"field": "http.useragent"}},
                    {"term": {"network.protocol": "http"}},
                ]
            }
        },
        "aggs": {"top_ua": {"terms": {"field": "http.useragent", "size": 5}}},
    }


def _hostname_from(result: dict) -> str | None:
    """The most common name that is a hostname, not a service or reverse-lookup name."""
    buckets = result.get("aggregations", {}).get("top_hostname", {}).get("buckets", [])
    # OLD CODE START — #130: the top name, even "_adisk._tcp.local"
    # return buckets[0]["key"] if buckets else None
    # OLD CODE END
    for bucket in buckets:
        name = bucket.get("key", "")
        if (
            name
            and not name.startswith("_")
            and not any(x in name for x in _NOT_HOSTNAMES)
        ):
            return name
    return None


def _dhcp_hit(result: dict) -> dict | None:
    """The DHCP hit, if it carries a MAC.

    OLD CODE START — replaced 2026-11-01: _source is nested, the flat "source.mac" key never exists
    mac = hits[0].get("_source", {}).get("source.mac")
    OLD CODE END
    """
    hits = result.get("hits", {}).get("hits", [])
    return hits[0] if hits and _mac_from_hit(hits[0]) else None


def _conn_hit(result: dict) -> dict | None:
    """A hit carrying the IP's most common conn MAC (same OLD CODE note as _dhcp_hit)."""
    buckets = result.get("aggregations", {}).get("mac", {}).get("buckets", [])
    hits = buckets[0].get("hit", {}).get("hits", {}).get("hits", []) if buckets else []
    return hits[0] if hits and _mac_from_hit(hits[0]) else None


def _os_from(result: dict) -> str | None:
    for bucket in result.get("aggregations", {}).get("top_ua", {}).get("buckets", []):
        ua_string = bucket.get("key", "")
        for pattern, os_name in _OS_PATTERNS:
            if pattern.search(ua_string):
                return os_name
    return None


class DeviceFingerprint:
    """Passive device fingerprinting from Arkime session data."""

    def __init__(self, oui_path: str | None = None):
        self._oui_db: dict[str, str] = {}  # MAC prefix (AA:BB:CC) -> manufacturer
        # Vendors Malcolm's full IEEE table gave for prefixes the bundled table lacks (#26)
        self._learned_oui: dict[str, str] = {}
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

        # OLD CODE START — the bundled table has ~500 prefixes, so Proxmox, the UDM and most
        # devices read "Unknown" (#26); Malcolm's vendor from get_mac_for_ip now fills the gap
        # return self._oui_db.get(prefix.upper(), "Unknown")
        # OLD CODE END
        prefix = prefix.upper()
        return self._oui_db.get(prefix) or self._learned_oui.get(prefix, "Unknown")

    def _learn_oui(self, hit: dict, mac: str) -> None:
        """Remember Malcolm's vendor for this MAC's prefix (a prefix's vendor never changes)."""
        oui = _oui_from_hit(hit)
        if oui:
            self._learned_oui[mac.upper().replace("-", ":")[:8]] = oui

    def _take_mac(self, hit: dict) -> str | None:
        """The hit's MAC, remembering Malcolm's vendor for its prefix."""
        mac = _mac_from_hit(hit)
        if mac:
            self._learn_oui(hit, mac)
        return mac

    def get_hostname_for_ip(
        self, client, ip: str, from_ts: str, to_ts: str
    ) -> str | None:
        """Query unified index for the most common hostname resolving to this IP.

        Looks at DNS answer records where the resolved IP matches the target.
        Returns the most frequently seen domain name, or None.
        """
        try:
            return _hostname_from(
                client.search(
                    index=NETWORK_INDEX, body=_hostname_query(ip, from_ts, to_ts)
                )
            )
        except Exception as exc:
            logger.debug("Hostname lookup failed for %s: %s", ip, exc)
        return None

    def get_mac_for_ip(self, client, ip: str, from_ts: str, to_ts: str) -> str | None:
        """Query unified index for a MAC address associated with this IP.

        Checks DHCP logs first (most reliable), then falls back to the
        source.mac field in connection logs.
        """
        try:
            hit = _dhcp_hit(
                client.search(
                    index=NETWORK_INDEX, body=_dhcp_mac_query(ip, from_ts, to_ts)
                )
            )
            if hit:
                return self._take_mac(hit)
        except Exception as exc:
            logger.debug("DHCP MAC lookup failed for %s: %s", ip, exc)
        try:
            hit = _conn_hit(
                client.search(
                    index=NETWORK_INDEX, body=_conn_mac_query(ip, from_ts, to_ts)
                )
            )
            if hit:
                return self._take_mac(hit)
        except Exception as exc:
            logger.debug("Conn MAC lookup failed for %s: %s", ip, exc)
        return None

    def get_os_hint(self, client, ip: str, from_ts: str, to_ts: str) -> str | None:
        """Infer the device's OS from HTTP User-Agent strings.

        Queries arkime_sessions3-* for User-Agent values from this IP, then
        matches against known OS patterns.  JA3 fingerprint analysis is not
        currently available in Arkime native sessions.
        """
        try:
            return _os_from(
                client.search(
                    index=NETWORK_INDEX, body=_user_agent_query(ip, from_ts, to_ts)
                )
            )
        except Exception as exc:
            logger.debug("User-Agent lookup failed for %s: %s", ip, exc)

        # Strategy 2: JA3 fingerprint from TLS handshakes
        # NOTE: JA3 fields (zeek.ssl.ja3) are not available in Arkime native
        # sessions. Skipping JA3 lookup until Arkime field mapping is confirmed.
        # Future: check for tls.ja3.hash or ja3.string if available.

        return None

    def lookup_many(
        self, client, ips: list[str], from_ts: str, to_ts: str
    ) -> dict[str, tuple[str | None, str | None, str | None]]:
        """{ip: (mac, hostname, os_hint)}: the get_* queries, batched into _msearch requests.

        The device list sent 4 searches per device one at a time: 2.9 s for 53 devices
        on the G11 (#21). A failed batch falls back to the per-IP methods.
        """
        builders = (
            _dhcp_mac_query,
            _conn_mac_query,
            _hostname_query,
            _user_agent_query,
        )
        found: dict[str, tuple[str | None, str | None, str | None]] = {}
        for start in range(0, len(ips), _MSEARCH_IPS):
            chunk = ips[start : start + _MSEARCH_IPS]
            body: list[dict] = []
            for ip in chunk:
                for build in builders:
                    body += [{"index": NETWORK_INDEX}, build(ip, from_ts, to_ts)]
            try:
                responses = client.msearch(body=body)["responses"]
                if not isinstance(responses, list) or len(responses) != len(
                    chunk
                ) * len(builders):
                    raise ValueError(
                        f"msearch returned {type(responses).__name__}, expected {len(body) // 2} responses"
                    )
            except Exception as exc:
                logger.warning(
                    "Batched device lookup failed, querying one IP at a time: %s", exc
                )
                for ip in chunk:
                    found[ip] = (
                        self.get_mac_for_ip(client, ip, from_ts, to_ts),
                        self.get_hostname_for_ip(client, ip, from_ts, to_ts),
                        self.get_os_hint(client, ip, from_ts, to_ts),
                    )
                continue
            for i, ip in enumerate(chunk):
                dhcp, conn, dns, ua = responses[i * 4 : i * 4 + 4]
                hit = _dhcp_hit(dhcp) or _conn_hit(
                    conn
                )  # DHCP first, as get_mac_for_ip
                found[ip] = (
                    self._take_mac(hit) if hit else None,
                    _hostname_from(dns),
                    _os_from(ua),
                )
        return found
