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

logger = logging.getLogger("nettap.mac_lookup")

# --- Constants ---
# Match 6 hex pairs separated by colons, dashes, or nothing
MAC_COLON_PATTERN = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
MAC_DASH_PATTERN = re.compile(r"^([0-9A-Fa-f]{2}-){5}[0-9A-Fa-f]{2}$")
MAC_RAW_PATTERN = re.compile(r"^[0-9A-Fa-f]{12}$")

OUI_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "oui_database.json")


class MacLookupValidationError(Exception):
    """Raised when MAC address validation fails."""
    pass


class MacLookupService:
    """Looks up vendor information for MAC addresses via a bundled OUI database."""

    def __init__(self, oui_db_path: str | None = None):
        self._oui_db_path = oui_db_path or OUI_DB_PATH
        self._oui_db: dict[str, str] | None = None

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
            pairs = [mac[i:i + 2] for i in range(0, 12, 2)]
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
        vendor = db.get(oui_prefix)

        return {
            "mac": normalized,
            "oui_prefix": oui_prefix,
            "vendor": vendor,
            "found": vendor is not None,
        }
