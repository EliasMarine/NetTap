"""
GeoIP lookup service for NetTap.

Provides IP-to-location resolution using multiple strategies:
1. RFC1918/private IP detection (always available, no external DB)
2. MaxMind GeoLite2-City database via maxminddb package (optional)
3. OpenSearch enriched traffic data (queries Malcolm's GeoIP-enriched sessions)
4. Built-in well-known IP database for common services (fallback)
"""

import ipaddress
import logging
import os
from functools import lru_cache

logger = logging.getLogger("nettap.geoip")

# ---------------------------------------------------------------------------
# Well-known IP ranges for fallback when no other source is available.
# ---------------------------------------------------------------------------

WELL_KNOWN_IPS: dict[str, dict] = {
    # Google Public DNS
    "8.8.8.8": {
        "country": "United States",
        "country_code": "US",
        "city": "Mountain View",
        "org": "Google LLC",
        "asn": 15169,
    },
    "8.8.4.4": {
        "country": "United States",
        "country_code": "US",
        "city": "Mountain View",
        "org": "Google LLC",
        "asn": 15169,
    },
    # Cloudflare DNS
    "1.1.1.1": {
        "country": "United States",
        "country_code": "US",
        "city": "San Francisco",
        "org": "Cloudflare, Inc.",
        "asn": 13335,
    },
    "1.0.0.1": {
        "country": "United States",
        "country_code": "US",
        "city": "San Francisco",
        "org": "Cloudflare, Inc.",
        "asn": 13335,
    },
    # Cisco OpenDNS
    "208.67.222.222": {
        "country": "United States",
        "country_code": "US",
        "city": "San Francisco",
        "org": "Cisco OpenDNS",
        "asn": 36692,
    },
    "208.67.220.220": {
        "country": "United States",
        "country_code": "US",
        "city": "San Francisco",
        "org": "Cisco OpenDNS",
        "asn": 36692,
    },
    # Quad9
    "9.9.9.9": {
        "country": "United States",
        "country_code": "US",
        "city": "Berkeley",
        "org": "Quad9",
        "asn": 19281,
    },
    "149.112.112.112": {
        "country": "United States",
        "country_code": "US",
        "city": "Berkeley",
        "org": "Quad9",
        "asn": 19281,
    },
    # Comodo Secure DNS
    "8.26.56.26": {
        "country": "United States",
        "country_code": "US",
        "city": "Jersey City",
        "org": "Comodo Group",
        "asn": 30060,
    },
    "8.20.247.20": {
        "country": "United States",
        "country_code": "US",
        "city": "Jersey City",
        "org": "Comodo Group",
        "asn": 30060,
    },
    # AdGuard DNS
    "94.140.14.14": {
        "country": "Cyprus",
        "country_code": "CY",
        "city": "Limassol",
        "org": "AdGuard Software Ltd",
        "asn": 212772,
    },
    "94.140.15.15": {
        "country": "Cyprus",
        "country_code": "CY",
        "city": "Limassol",
        "org": "AdGuard Software Ltd",
        "asn": 212772,
    },
    # CleanBrowsing DNS
    "185.228.168.9": {
        "country": "United States",
        "country_code": "US",
        "city": None,
        "org": "CleanBrowsing",
        "asn": 398085,
    },
    "185.228.169.9": {
        "country": "United States",
        "country_code": "US",
        "city": None,
        "org": "CleanBrowsing",
        "asn": 398085,
    },
    # Verisign Public DNS
    "64.6.64.6": {
        "country": "United States",
        "country_code": "US",
        "city": "Reston",
        "org": "Verisign, Inc.",
        "asn": 7342,
    },
    "64.6.65.6": {
        "country": "United States",
        "country_code": "US",
        "city": "Reston",
        "org": "Verisign, Inc.",
        "asn": 7342,
    },
    # Level3 DNS
    "4.2.2.1": {
        "country": "United States",
        "country_code": "US",
        "city": None,
        "org": "Level 3 Communications",
        "asn": 3356,
    },
    "4.2.2.2": {
        "country": "United States",
        "country_code": "US",
        "city": None,
        "org": "Level 3 Communications",
        "asn": 3356,
    },
    # Akamai CDN common anycast
    "23.0.0.1": {
        "country": "United States",
        "country_code": "US",
        "city": None,
        "org": "Akamai Technologies",
        "asn": 16625,
    },
    # Amazon AWS us-east-1 common IP
    "54.239.28.85": {
        "country": "United States",
        "country_code": "US",
        "city": "Ashburn",
        "org": "Amazon.com, Inc.",
        "asn": 16509,
    },
    # Microsoft Azure front
    "13.107.4.50": {
        "country": "United States",
        "country_code": "US",
        "city": "Redmond",
        "org": "Microsoft Corporation",
        "asn": 8075,
    },
    # Apple
    "17.253.144.10": {
        "country": "United States",
        "country_code": "US",
        "city": "Cupertino",
        "org": "Apple Inc.",
        "asn": 714,
    },
    # Facebook / Meta
    "157.240.1.35": {
        "country": "United States",
        "country_code": "US",
        "city": "Menlo Park",
        "org": "Meta Platforms, Inc.",
        "asn": 32934,
    },
    # Twitter / X
    "104.244.42.1": {
        "country": "United States",
        "country_code": "US",
        "city": "San Francisco",
        "org": "X Corp.",
        "asn": 13414,
    },
    # Fastly CDN
    "151.101.1.69": {
        "country": "United States",
        "country_code": "US",
        "city": None,
        "org": "Fastly, Inc.",
        "asn": 54113,
    },
    # Let's Encrypt OCSP
    "23.43.125.82": {
        "country": "United States",
        "country_code": "US",
        "city": None,
        "org": "Akamai Technologies",
        "asn": 16625,
    },
}


class GeoIPResult:
    """Result of a GeoIP lookup."""

    def __init__(
        self,
        ip: str,
        country: str = "Unknown",
        country_code: str = "XX",
        city: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        asn: int | None = None,
        organization: str | None = None,
        is_private: bool = False,
    ):
        self.ip = ip
        self.country = country
        self.country_code = country_code
        self.city = city
        self.latitude = latitude
        self.longitude = longitude
        self.asn = asn
        self.organization = organization
        self.is_private = is_private

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "ip": self.ip,
            "country": self.country,
            "country_code": self.country_code,
            "city": self.city,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "asn": self.asn,
            "organization": self.organization,
            "is_private": self.is_private,
        }


class GeoIPService:
    """GeoIP lookup with OpenSearch enrichment data + MaxMind DB + fallback.

    Resolution order:
    1. RFC1918 / private range check
    2. MaxMind GeoLite2 database (if loaded)
    3. OpenSearch enriched sessions (Malcolm adds GeoIP to traffic data)
    4. Built-in well-known IP database
    5. Unknown (country="Unknown", country_code="XX")
    """

    def __init__(self, db_path: str | None = None, opensearch_client=None):
        self._reader = None
        self._db_available = False
        self._os_client = opensearch_client
        # In-memory cache for OpenSearch lookups (TTL managed by LRU eviction)
        self._os_cache: dict[str, GeoIPResult] = {}
        self._OS_CACHE_MAX = 2048

        # Try to load MaxMind database
        if db_path is None:
            db_path = os.environ.get(
                "GEOIP_DB_PATH", "/opt/nettap/data/GeoLite2-City.mmdb"
            )

        try:
            import maxminddb

            if os.path.exists(db_path):
                self._reader = maxminddb.open_database(db_path)
                self._db_available = True
                logger.info("GeoLite2 database loaded from %s", db_path)
            else:
                logger.warning(
                    "GeoLite2 database not found at %s, using fallback", db_path
                )
        except ImportError:
            logger.warning("maxminddb package not installed, using fallback GeoIP")
        except Exception as exc:
            logger.warning("Failed to load GeoLite2 database: %s", exc)

        if self._os_client:
            logger.info("GeoIP OpenSearch enrichment lookup enabled")

    @property
    def db_available(self) -> bool:
        """Whether the MaxMind GeoLite2 database was successfully loaded."""
        return self._db_available

    def is_private(self, ip: str) -> bool:
        """Check if IP is in a private/reserved range (RFC1918, link-local, loopback)."""
        try:
            addr = ipaddress.ip_address(ip)
            return (
                addr.is_private
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_reserved
            )
        except ValueError:
            return False

    def _lookup_opensearch(self, ip: str) -> GeoIPResult | None:
        """Query OpenSearch for GeoIP data enriched by Malcolm's logstash pipeline.

        Malcolm enriches traffic sessions with GeoIP fields:
        - source.geo.country_name, destination.geo.country_name
        - source.geo.city_name, destination.geo.city_name
        - source.geo.country_iso_code, destination.geo.country_iso_code
        - source.geo.location (lat/lon)
        - source.as.number, source.as.organization.name

        We query for any recent session where this IP appears as source or
        destination and extract the geo fields.
        """
        if not self._os_client:
            return None

        # Check in-memory cache first
        if ip in self._os_cache:
            return self._os_cache[ip]

        try:
            # Search for this IP in recent sessions, try both source and destination
            body = {
                "size": 1,
                "sort": [{"@timestamp": {"order": "desc"}}],
                "query": {
                    "bool": {
                        "should": [
                            {"term": {"source.ip": ip}},
                            {"term": {"destination.ip": ip}},
                        ],
                        "minimum_should_match": 1,
                        # Only look at docs that have geo data
                        "filter": {
                            "bool": {
                                "should": [
                                    {"exists": {"field": "source.geo.country_name"}},
                                    {"exists": {"field": "destination.geo.country_name"}},
                                ],
                                "minimum_should_match": 1,
                            }
                        },
                    }
                },
                "_source": [
                    "source.ip", "destination.ip",
                    "source.geo.*", "destination.geo.*",
                    "source.as.*", "destination.as.*",
                ],
            }

            resp = self._os_client.search(index="arkime_sessions3-*", body=body)
            hits = resp.get("hits", {}).get("hits", [])
            if not hits:
                return None

            src = hits[0].get("_source", {})

            # Determine which side (source/destination) has this IP
            src_ip = src.get("source", {}).get("ip")
            dst_ip = src.get("destination", {}).get("ip")

            if src_ip == ip:
                geo = src.get("source", {}).get("geo", {})
                as_info = src.get("source", {}).get("as", {})
            elif dst_ip == ip:
                geo = src.get("destination", {}).get("geo", {})
                as_info = src.get("destination", {}).get("as", {})
            else:
                return None

            country = geo.get("country_name")
            if not country:
                return None

            location = geo.get("location", {})
            lat = location.get("lat") if isinstance(location, dict) else None
            lon = location.get("lon") if isinstance(location, dict) else None
            # Fall back to top-level latitude/longitude if location dict missing
            if lat is None:
                lat = geo.get("latitude")
            if lon is None:
                lon = geo.get("longitude")

            # Parse ASN from Malcolm's "as.full" field: "AS16509 Amazon.com, Inc."
            asn_number = as_info.get("number")
            org_name = as_info.get("organization")
            if isinstance(org_name, dict):
                org_name = org_name.get("name")
            as_full = as_info.get("full", "")
            if as_full and (asn_number is None or org_name is None):
                # Parse "AS16509 Amazon.com, Inc." → (16509, "Amazon.com, Inc.")
                if as_full.upper().startswith("AS"):
                    parts = as_full.split(" ", 1)
                    if len(parts) >= 1 and asn_number is None:
                        try:
                            asn_number = int(parts[0][2:])
                        except ValueError:
                            pass
                    if len(parts) == 2 and org_name is None:
                        org_name = parts[1]

            result = GeoIPResult(
                ip=ip,
                country=country,
                country_code=geo.get("country_iso_code", "XX"),
                city=geo.get("city_name"),
                latitude=lat,
                longitude=lon,
                asn=asn_number,
                organization=org_name,
            )

            # Cache the result
            if len(self._os_cache) >= self._OS_CACHE_MAX:
                # Evict oldest entries (simple strategy: clear half)
                keys = list(self._os_cache.keys())
                for k in keys[: len(keys) // 2]:
                    del self._os_cache[k]
            self._os_cache[ip] = result

            return result

        except Exception as exc:
            logger.debug("OpenSearch GeoIP lookup failed for %s: %s", ip, exc)
            return None

    @lru_cache(maxsize=4096)
    def lookup(self, ip: str) -> GeoIPResult:
        """Look up GeoIP data for a single IP address.

        Resolution order:
        1. RFC1918 / private range check
        2. MaxMind GeoLite2 database (if loaded)
        3. OpenSearch enriched session data
        4. Built-in well-known IP database
        5. Unknown (country="Unknown", country_code="XX")
        """
        # Check private ranges first
        if self.is_private(ip):
            return GeoIPResult(
                ip=ip,
                country="Private Network",
                country_code="XX",
                is_private=True,
            )

        # Try MaxMind database
        if self._db_available and self._reader:
            try:
                record = self._reader.get(ip)
                if record:
                    country_info = record.get("country", {})
                    city_info = record.get("city", {})
                    location = record.get("location", {})
                    traits = record.get("traits", {})

                    return GeoIPResult(
                        ip=ip,
                        country=country_info.get("names", {}).get("en", "Unknown"),
                        country_code=country_info.get("iso_code", "XX"),
                        city=city_info.get("names", {}).get("en"),
                        latitude=location.get("latitude"),
                        longitude=location.get("longitude"),
                        asn=traits.get("autonomous_system_number"),
                        organization=traits.get("autonomous_system_organization"),
                    )
            except Exception as exc:
                logger.debug("MaxMind lookup failed for %s: %s", ip, exc)

        # Try OpenSearch enrichment data
        os_result = self._lookup_opensearch(ip)
        if os_result:
            return os_result

        # Fallback: check well-known IPs
        if ip in WELL_KNOWN_IPS:
            info = WELL_KNOWN_IPS[ip]
            return GeoIPResult(
                ip=ip,
                country=info["country"],
                country_code=info["country_code"],
                city=info.get("city"),
                organization=info.get("org"),
                asn=info.get("asn"),
            )

        # Unknown public IP
        return GeoIPResult(ip=ip)

    def lookup_batch(self, ips: list[str]) -> list[dict]:
        """Look up GeoIP data for multiple IPs.

        Caps at 50 IPs to prevent abuse. Returns a list of dicts
        (serialised GeoIPResult).
        """
        return [self.lookup(ip).to_dict() for ip in ips[:50]]

    def close(self):
        """Close the MaxMind database reader."""
        if self._reader:
            self._reader.close()
