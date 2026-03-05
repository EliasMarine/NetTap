"""
Excluded IPs service for NetTap.

Manages a configurable list of IP addresses to exclude from device-centric
views (device inventory, top talkers, risk scores) while keeping them
visible in raw log search, alerts, and connection listings.

Typical use case: filtering out the ISP gateway's public IP that appears
on every external connection and drowns out actual LAN devices.
"""

import json
import logging
import os

logger = logging.getLogger("nettap.services.excluded_ips")

DEFAULT_EXCLUDED_IPS_FILE = "/opt/nettap/data/excluded_ips.json"


def _get_file_path() -> str:
    return os.environ.get("EXCLUDED_IPS_FILE", DEFAULT_EXCLUDED_IPS_FILE)


def load_excluded_ips(file_path: str | None = None) -> list[str]:
    """Load the excluded IP list from disk.

    Returns an empty list if the file doesn't exist or is malformed.
    """
    path = file_path or _get_file_path()
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [ip for ip in data if isinstance(ip, str) and ip.strip()]
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load excluded IPs from %s: %s", path, exc)
    return []


def save_excluded_ips(ips: list[str], file_path: str | None = None) -> None:
    """Persist the excluded IP list to disk."""
    path = file_path or _get_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(ips, f, indent=2)
    logger.info("Saved %d excluded IPs to %s", len(ips), path)


def build_excluded_ips_filter(excluded_ips: list[str]) -> list[dict]:
    """Build OpenSearch must_not clauses to exclude IPs from source.ip aggregations.

    Returns a list suitable for insertion into a bool query's must_not array.
    Returns an empty list if no IPs are excluded.
    """
    if not excluded_ips:
        return []
    return [{"terms": {"source.ip": excluded_ips}}]
