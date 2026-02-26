"""
GeoIP lookup service for NetTap.

Provides IP-to-location resolution using MaxMind GeoLite2 database
(when available) with fallback to RFC1918 detection and a built-in
well-known IP database.

Three tiers of lookup:
1. RFC1918/private IP detection (always available, no external DB)
2. MaxMind GeoLite2-City database via maxminddb package (optional)
3. Built-in well-known IP database for common services (fallback)
"""

import ipaddress
import logging
import os
from functools import lru_cache
from typing import Optional

logger = logging.getLogger("nettap.geoip")

# ---------------------------------------------------------------------------
# Well-known IP ranges for fallback when no GeoLite2 DB is available.
# These cover major DNS providers, CDNs, and cloud services.
# ---------------------------------------------------------------------------

WELL_KNOWN_IPS: dict[str, dict] = {
    # Google Public DNS
    "8.8.8.8": {"country": "United States", "country_code": "US", "city": "Mountain View", "org": "Google LLC", "asn": 15169},
    "8.8.4.4": {"country": "United States", "country_code": "US", "city": "Mountain View", "org": "Google LLC", "asn": 15169},
    # Cloudflare DNS
    "1.1.1.1": {"country": "United States", "country_code": "US", "city": "San Francisco", "org": "Cloudflare, Inc.", "asn": 13335},
    "1.0.0.1": {"country": "United States", "country_code": "US", "city": "San Francisco", "org": "Cloudflare, Inc.", "asn": 13335},
    # Cisco OpenDNS
    "208.67.222.222": {"country": "United States", "country_code": "US", "city": "San Francisco", "org": "Cisco OpenDNS", "asn": 36692},
    "208.67.220.220": {"country": "United States", "country_code": "US", "city": "San Francisco", "org": "Cisco OpenDNS", "asn": 36692},
    # Quad9
    "9.9.9.9": {"country": "United States", "country_code": "US", "city": "Berkeley", "org": "Quad9", "asn": 19281},
    "149.112.112.112": {"country": "United States", "country_code": "US", "city": "Berkeley", "org": "Quad9", "asn": 19281},
    # Comodo Secure DNS
    "8.26.56.26": {"country": "United States", "country_code": "US", "city": "Jersey City", "org": "Comodo Group", "asn": 30060},
    "8.20.247.20": {"country": "United States", "country_code": "US", "city": "Jersey City", "org": "Comodo Group", "asn": 30060},
    # AdGuard DNS
    "94.140.14.14": {"country": "Cyprus", "country_code": "CY", "city": "Limassol", "org": "AdGuard Software Ltd", "asn": 212772},
    "94.140.15.15": {"country": "Cyprus", "country_code": "CY", "city": "Limassol", "org": "AdGuard Software Ltd", "asn": 212772},
    # CleanBrowsing DNS
    "185.228.168.9": {"country": "United States", "country_code": "US", "city": None, "org": "CleanBrowsing", "asn": 398085},
    "185.228.169.9": {"country": "United States", "country_code": "US", "city": None, "org": "CleanBrowsing", "asn": 398085},
    # Verisign Public DNS
    "64.6.64.6": {"country": "United States", "country_code": "US", "city": "Reston", "org": "Verisign, Inc.", "asn": 7342},
    "64.6.65.6": {"country": "United States", "country_code": "US", "city": "Reston", "org": "Verisign, Inc.", "asn": 7342},
    # Level3 DNS
    "4.2.2.1": {"country": "United States", "country_code": "US", "city": None, "org": "Level 3 Communications", "asn": 3356},
    "4.2.2.2": {"country": "United States", "country_code": "US", "city": None, "org": "Level 3 Communications", "asn": 3356},
    # Akamai CDN common anycast
    "23.0.0.1": {"country": "United States", "country_code": "US", "city": None, "org": "Akamai Technologies", "asn": 16625},
    # Amazon AWS us-east-1 common IP
    "54.239.28.85": {"country": "United States", "country_code": "US", "city": "Ashburn", "org": "Amazon.com, Inc.", "asn": 16509},
    # Microsoft Azure front
    "13.107.4.50": {"country": "United States", "country_code": "US", "city": "Redmond", "org": "Microsoft Corporation", "asn": 8075},
    # Apple
    "17.253.144.10": {"country": "United States", "country_code": "US", "city": "Cupertino", "org": "Apple Inc.", "asn": 714},
    # Facebook / Meta
    "157.240.1.35": {"country": "United States", "country_code": "US", "city": "Menlo Park", "org": "Meta Platforms, Inc.", "asn": 32934},
    # Twitter / X
    "104.244.42.1": {"country": "United States", "country_code": "US", "city": "San Francisco", "org": "X Corp.", "asn": 13414},
    # Fastly CDN
    "151.101.1.69": {"country": "United States", "country_code": "US", "city": None, "org": "Fastly, Inc.", "asn": 54113},
    # Let's Encrypt OCSP
    "23.43.125.82": {"country": "United States", "country_code": "US", "city": None, "org": "Akamai Technologies", "asn": 16625},
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
    """GeoIP lookup with MaxMind DB + fallback.

    Attempts to load a MaxMind GeoLite2-City database on init.  If the
    ``maxminddb`` package is not installed or the database file is
    missing, the service falls back to RFC1918 detection and a built-in
    well-known IP database -- no exceptions raised, no features lost
    aside from full geo resolution of arbitrary public IPs.
    """

    def __init__(self, db_path: str | None = None):
        self._reader = None
        self._db_available = False

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

    @lru_cache(maxsize=4096)
    def lookup(self, ip: str) -> GeoIPResult:
        """Look up GeoIP data for a single IP address.

        Resolution order:
        1. RFC1918 / private range check
        2. MaxMind GeoLite2 database (if loaded)
        3. Built-in well-known IP database
        4. Unknown (country="Unknown", country_code="XX")
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
