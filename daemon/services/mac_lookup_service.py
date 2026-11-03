"""
NetTap MAC Address OUI Lookup Service

Looks up the vendor/manufacturer for a given MAC address using a bundled
OUI (Organizationally Unique Identifier) database.

The first 3 octets (24 bits) of a MAC address identify the manufacturer.
This service normalizes various MAC formats and matches against known OUIs.
"""

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger("nettap.mac_lookup")

# --- Constants ---
# Match 6 hex pairs separated by colons, dashes, or nothing
MAC_COLON_PATTERN = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
MAC_DASH_PATTERN = re.compile(r"^([0-9A-Fa-f]{2}-){5}[0-9A-Fa-f]{2}$")
MAC_RAW_PATTERN = re.compile(r"^[0-9A-Fa-f]{12}$")

OUI_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "oui_database.json")
NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")


class MacLookupValidationError(Exception):
    """Raised when MAC address validation fails."""

    pass


class MacLookupService:
    """Looks up vendor information for MAC addresses via a bundled OUI database."""

    def __init__(self, oui_db_path: str | None = None, opensearch_client: Any = None):
        self._oui_db_path = oui_db_path or OUI_DB_PATH
        self._oui_db: dict[str, str] | None = None
        # Malcolm's full IEEE table reaches us as source.oui on captured records (#26)
        self._client = opensearch_client

    def _vendor_seen_on_network(self, oui_prefix: str) -> str | None:
        """Malcolm's IEEE vendor name for a prefix any captured device has used.

        shortcut: only knows prefixes seen on this network; bundle the full IEEE table if
        lookups must answer for arbitrary MACs.
        """
        if self._client is None or int(oui_prefix[:2], 16) & 0x02:
            return None  # no OpenSearch, or a locally administered (randomized) MAC: no vendor
        body = {
            "size": 1,
            "query": {
                "bool": {
                    "filter": [
                        {"prefix": {"source.mac": oui_prefix.lower()}},
                        {"exists": {"field": "source.oui"}},
                    ]
                }
            },
            "_source": ["source.oui"],
        }
        try:
            hits = self._client.search(index=NETWORK_INDEX, body=body)["hits"]["hits"]
        except Exception as exc:
            logger.warning(
                "OUI fallback to OpenSearch failed for %s: %s", oui_prefix, exc
            )
            return None
        oui = hits[0].get("_source", {}).get("source", {}).get("oui") if hits else None
        if isinstance(oui, list):
            oui = next((o for o in oui if o), None)
        return oui or None

    def _load_oui_db(self) -> dict[str, str]:
        """Load the OUI database from disk (lazy, cached)."""
        if self._oui_db is not None:
            return self._oui_db

        try:
            with open(self._oui_db_path, "r") as f:
                self._oui_db = json.load(f)
        except FileNotFoundError:
            logger.warning("OUI database not found at %s", self._oui_db_path)
            self._oui_db = {}
        except json.JSONDecodeError:
            logger.error("OUI database is corrupt: %s", self._oui_db_path)
            self._oui_db = {}

        return self._oui_db

    def normalize_mac(self, mac: str) -> str:
        """Normalize a MAC address to AA:BB:CC:DD:EE:FF format.

        Accepts colon-separated, dash-separated, or raw hex formats.
        Raises MacLookupValidationError on invalid input.
        """
        if not mac:
            raise MacLookupValidationError("MAC address is required")

        mac = mac.strip().upper()

        if MAC_COLON_PATTERN.match(mac):
            return mac
        elif MAC_DASH_PATTERN.match(mac):
            return mac.replace("-", ":")
        elif MAC_RAW_PATTERN.match(mac):
            pairs = [mac[i : i + 2] for i in range(0, 12, 2)]
            return ":".join(pairs)
        else:
            raise MacLookupValidationError(
                f"Invalid MAC address format: {mac!r} — "
                "expected AA:BB:CC:DD:EE:FF, AA-BB-CC-DD-EE-FF, or AABBCCDDEEFF"
            )

    def lookup(self, mac: str) -> dict:
        """Look up the vendor for a MAC address.

        Returns {mac, oui_prefix, vendor, found}.
        """
        normalized = self.normalize_mac(mac)
        oui_prefix = normalized[:8]  # First 3 octets: "AA:BB:CC"

        db = self._load_oui_db()
        vendor = db.get(oui_prefix) or self._vendor_seen_on_network(oui_prefix)

        return {
            "mac": normalized,
            "oui_prefix": oui_prefix,
            "vendor": vendor,
            "found": vendor is not None,
        }
