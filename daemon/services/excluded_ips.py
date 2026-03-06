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


# Filter to restrict source.ip to RFC1918 private address ranges (LAN devices only).
# Uses a painless script for proper numeric IP comparison because arkime_sessions3-*
# maps source.ip as keyword type, making range queries lexicographic (which incorrectly
# matches public IPs like 172.217.x.x or 172.234.x.x).
# OLD CODE START — replaced lexicographic range queries with painless script (2026-03-05)
# RFC1918_SOURCE_FILTER = {
#     "bool": {
#         "should": [
#             {"range": {"source.ip": {"gte": "10.0.0.0", "lte": "10.255.255.255"}}},
#             {"range": {"source.ip": {"gte": "172.16.0.0", "lte": "172.31.255.255"}}},
#             {"range": {"source.ip": {"gte": "192.168.0.0", "lte": "192.168.255.255"}}},
#         ],
#         "minimum_should_match": 1,
#     }
# }
# OLD CODE END
RFC1918_SOURCE_FILTER = {
    "script": {
        "script": {
            "source": """
                def ip = doc['source.ip.keyword'].size() > 0 ? doc['source.ip.keyword'].value : '';
                if (ip.length() == 0) return false;
                def parts = ip.splitOnToken('.');
                if (parts.length != 4) return false;
                int a = Integer.parseInt(parts[0]);
                int b = Integer.parseInt(parts[1]);
                if (a == 10) return true;
                if (a == 172 && b >= 16 && b <= 31) return true;
                if (a == 192 && b == 168) return true;
                return false;
            """,
            "lang": "painless"
        }
    }
}


def build_excluded_ips_filter(excluded_ips: list[str]) -> list[dict]:
    """Build OpenSearch must_not clauses to exclude IPs from source.ip aggregations.

    Returns a list suitable for insertion into a bool query's must_not array.
    Returns an empty list if no IPs are excluded.
    """
    if not excluded_ips:
        return []
    return [{"terms": {"source.ip": excluded_ips}}]
