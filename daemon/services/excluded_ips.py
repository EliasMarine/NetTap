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


# ---------------------------------------------------------------------------
# LAN subnet filter — configurable via LAN_SUBNETS env var
# ---------------------------------------------------------------------------
# Restricts source.ip to configured LAN subnets (painless script filter).
# Uses a painless script for proper numeric IP comparison because arkime_sessions3-*
# maps source.ip as keyword type, making range queries lexicographic (which incorrectly
# matches public IPs like 172.217.x.x or 172.234.x.x).
#
# OLD CODE START — hardcoded all-RFC1918 painless filter allowed ISP CGNAT 10.x.x.x IPs (2026-03-05)
# RFC1918_SOURCE_FILTER = {
#     "script": {
#         "script": {
#             "source": """
#                 def ip = doc['source.ip.keyword'].size() > 0 ? doc['source.ip.keyword'].value : '';
#                 if (ip.length() == 0) return false;
#                 def parts = ip.splitOnToken('.');
#                 if (parts.length != 4) return false;
#                 int a = Integer.parseInt(parts[0]);
#                 int b = Integer.parseInt(parts[1]);
#                 if (a == 10) return true;
#                 if (a == 172 && b >= 16 && b <= 31) return true;
#                 if (a == 192 && b == 168) return true;
#                 return false;
#             """,
#             "lang": "painless"
#         }
#     }
# }
# OLD CODE END


def _parse_lan_subnets() -> list[tuple[int, int, int]]:
    """Parse LAN_SUBNETS env var into (a, b, c) tuples for painless script.

    Supports /8, /16, /24 CIDR blocks only (sufficient for home/SMB LANs).
    Default: 192.168.0.0/16

    Environment variable: LAN_SUBNETS (comma-separated CIDR notation)
    Examples:
        LAN_SUBNETS=192.168.1.0/24
        LAN_SUBNETS=192.168.0.0/16,10.0.0.0/8
        LAN_SUBNETS=172.16.0.0/16,192.168.1.0/24
    """
    raw = os.environ.get("LAN_SUBNETS", "192.168.0.0/16,10.10.0.0/16")
    subnets: list[tuple[int, int, int]] = []
    for cidr in raw.split(","):
        cidr = cidr.strip()
        if "/" not in cidr:
            continue
        ip_part, prefix = cidr.split("/", 1)
        octets = ip_part.split(".")
        if len(octets) != 4:
            continue
        a, b, c = int(octets[0]), int(octets[1]), int(octets[2])
        prefix_len = int(prefix)
        if prefix_len == 8:
            subnets.append((a, -1, -1))  # match first octet only
        elif prefix_len == 16:
            subnets.append((a, b, -1))  # match first two octets
        elif prefix_len == 24:
            subnets.append((a, b, c))  # match first three octets
    return subnets


def build_lan_filter() -> dict:
    """Build an OpenSearch painless script filter that only matches IPs in configured LAN subnets.

    Reads the LAN_SUBNETS environment variable (comma-separated CIDR notation).
    Default: 192.168.0.0/16 (matches 192.168.x.x only).

    Returns a dict suitable for use as an OpenSearch query filter clause.
    """
    subnets = _parse_lan_subnets()
    if not subnets:
        # Fallback to 192.168.0.0/16
        subnets = [(192, 168, -1)]

    # Build painless conditions
    conditions = []
    for subnet in subnets:
        a, b, c = subnet
        if b == -1:
            conditions.append(f"(a == {a})")
        elif c == -1:
            conditions.append(f"(a == {a} && b == {b})")
        else:
            conditions.append(f"(a == {a} && b == {b} && c == {c})")

    condition_str = " || ".join(conditions)

    return {
        "script": {
            "script": {
                "source": f"""
                    def ip = doc['source.ip.keyword'].size() > 0 ? doc['source.ip.keyword'].value : '';
                    if (ip.length() == 0) return false;
                    def parts = ip.splitOnToken('.');
                    if (parts.length != 4) return false;
                    int a = Integer.parseInt(parts[0]);
                    int b = Integer.parseInt(parts[1]);
                    int c = Integer.parseInt(parts[2]);
                    return {condition_str};
                """,
                "lang": "painless"
            }
        }
    }


# Module-level constant — built once at import time from LAN_SUBNETS env var
RFC1918_SOURCE_FILTER = build_lan_filter()


def build_excluded_ips_filter(excluded_ips: list[str]) -> list[dict]:
    """Build OpenSearch must_not clauses to exclude IPs from source.ip aggregations.

    Returns a list suitable for insertion into a bool query's must_not array.
    Returns an empty list if no IPs are excluded.
    """
    if not excluded_ips:
        return []
    return [{"terms": {"source.ip": excluded_ips}}]
