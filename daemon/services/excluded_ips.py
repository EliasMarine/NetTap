"""
Excluded IPs service for NetTap.

Manages a configurable list of IP addresses to exclude from device-centric
views (device inventory, top talkers, risk scores) while keeping them
visible in raw log search, alerts, and connection listings.

Also provides LAN subnet auto-detection: queries OpenSearch for the most
common RFC1918 source IP subnets to automatically identify the user's
actual LAN without any manual configuration.
"""

import json
import logging
import os

logger = logging.getLogger("nettap.services.excluded_ips")

DEFAULT_EXCLUDED_IPS_FILE = "/opt/nettap/data/excluded_ips.json"

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")


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
# RFC1918 helpers
# ---------------------------------------------------------------------------


def _is_rfc1918(a: int, b: int) -> bool:
    """Check if first two octets belong to an RFC1918 range."""
    if a == 10:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 192 and b == 168:
        return True
    return False


# ---------------------------------------------------------------------------
# LAN subnet auto-detection from OpenSearch traffic data
# ---------------------------------------------------------------------------


def detect_lan_subnets(client) -> list[tuple[int, int, int]]:
    """Auto-detect LAN subnets by querying OpenSearch for common source IPs.

    Strategy: aggregate source.ip from recent zeek conn logs, extract the
    /24 subnet of each top IP, keep only RFC1918 subnets, and return them
    sorted by frequency. This correctly identifies the user's actual LAN
    regardless of their subnet scheme (192.168.1.x, 10.0.1.x, 172.16.x.x, etc.).

    Args:
        client: OpenSearch client instance.

    Returns:
        List of (a, b, c) tuples representing detected /24 subnets.
        Empty list if detection fails.
    """
    try:
        # Only count source IPs that make OUTBOUND connections (to non-RFC1918
        # destinations). This filters out ISP CGNAT IPs (e.g. 10.181.x.x) which
        # are RFC1918 but only appear as source in INBOUND traffic to the user's
        # router. Real LAN devices initiate connections to external destinations.
        query = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"event.provider": "zeek"}},
                        {"term": {"event.dataset": "conn"}},
                        # Exclude connections to RFC1918 destinations (inbound/LAN-to-LAN)
                        # Only keep outbound connections to public IPs
                        {
                            "script": {
                                "script": {
                                    "source": """
                                        def ip = doc['destination.ip.keyword'].size() > 0 ? doc['destination.ip.keyword'].value : '';
                                        if (ip.length() == 0) return false;
                                        def parts = ip.splitOnToken('.');
                                        if (parts.length != 4) return false;
                                        int a = Integer.parseInt(parts[0]);
                                        int b = Integer.parseInt(parts[1]);
                                        if (a == 10) return false;
                                        if (a == 172 && b >= 16 && b <= 31) return false;
                                        if (a == 192 && b == 168) return false;
                                        return true;
                                    """,
                                    "lang": "painless"
                                }
                            }
                        },
                    ]
                }
            },
            "aggs": {
                "top_sources": {
                    "terms": {
                        "field": "source.ip.keyword",
                        "size": 500,
                    }
                }
            },
        }

        result = client.search(index=NETWORK_INDEX, body=query)
        buckets = result.get("aggregations", {}).get("top_sources", {}).get("buckets", [])

        if not buckets:
            logger.warning("LAN detection: no source IPs found in OpenSearch")
            return []

        # Count connections per /24 subnet (only RFC1918)
        subnet_counts: dict[tuple[int, int, int], int] = {}
        for bucket in buckets:
            ip = bucket["key"]
            count = bucket["doc_count"]
            parts = ip.split(".")
            if len(parts) != 4:
                continue
            try:
                a, b, c = int(parts[0]), int(parts[1]), int(parts[2])
            except ValueError:
                continue

            if not _is_rfc1918(a, b):
                continue

            subnet = (a, b, c)
            subnet_counts[subnet] = subnet_counts.get(subnet, 0) + count

        if not subnet_counts:
            logger.warning("LAN detection: no RFC1918 source IPs found")
            return []

        # Sort by connection count descending, take top subnets
        sorted_subnets = sorted(subnet_counts.items(), key=lambda x: x[1], reverse=True)

        # Only keep subnets with meaningful traffic (>10% of the top subnet's traffic)
        top_count = sorted_subnets[0][1]
        threshold = top_count * 0.10
        detected = [s for s, c in sorted_subnets if c >= threshold]

        logger.info(
            "LAN detection: found %d subnet(s): %s",
            len(detected),
            ", ".join(f"{a}.{b}.{c}.0/24" for a, b, c in detected),
        )
        return detected

    except Exception as exc:
        logger.warning("LAN subnet detection failed: %s", exc)
        return []


def _parse_manual_subnets() -> list[tuple[int, int, int]]:
    """Parse LAN_SUBNETS env var as manual override.

    Supports /8, /16, /24 CIDR blocks.
    Returns empty list if env var is not set (triggers auto-detection).
    """
    raw = os.environ.get("LAN_SUBNETS", "")
    if not raw.strip():
        return []  # No manual override — use auto-detection

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
            subnets.append((a, -1, -1))
        elif prefix_len == 16:
            subnets.append((a, b, -1))
        elif prefix_len == 24:
            subnets.append((a, b, c))

    if subnets:
        logger.info(
            "LAN subnets from env override: %s",
            ", ".join(
                f"{a}.{'*' if b == -1 else b}.{'*' if c == -1 else c}.0"
                for a, b, c in subnets
            ),
        )
    return subnets


def build_lan_filter(subnets: list[tuple[int, int, int]]) -> dict:
    """Build an OpenSearch painless script filter matching only given subnets.

    Args:
        subnets: List of (a, b, c) tuples. -1 means wildcard for that octet.
            e.g. (192, 168, 1) matches 192.168.1.x
                 (10, -1, -1)   matches 10.x.x.x

    Returns:
        OpenSearch query filter clause.
    """
    if not subnets:
        # Fallback: match all RFC1918 (broad, but safe default)
        return {
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

    conditions = []
    for a, b, c in subnets:
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


def detect_and_build_lan_filter(client) -> dict:
    """Auto-detect LAN subnets from traffic data and build the filter.

    Priority order:
    1. LAN_SUBNETS env var (manual override) — if set, use it
    2. Auto-detect from OpenSearch traffic data
    3. Fall back to all RFC1918 if detection fails

    Args:
        client: OpenSearch client instance (can be None if not available yet).

    Returns:
        OpenSearch query filter clause for LAN source IPs.
    """
    # Check for manual override first
    manual = _parse_manual_subnets()
    if manual:
        return build_lan_filter(manual)

    # Auto-detect from traffic data
    if client is not None:
        detected = detect_lan_subnets(client)
        if detected:
            return build_lan_filter(detected)

    # Fallback: all RFC1918
    logger.info("LAN filter: using broad RFC1918 fallback (auto-detection unavailable)")
    return build_lan_filter([])


# Module-level fallback — used only until auto-detection runs in create_app()
# After startup, devices.py and risk.py read from request.app["lan_filter"]
RFC1918_SOURCE_FILTER = build_lan_filter(_parse_manual_subnets())


def build_excluded_ips_filter(excluded_ips: list[str]) -> list[dict]:
    """Build OpenSearch must_not clauses to exclude IPs from source.ip aggregations.

    Returns a list suitable for insertion into a bool query's must_not array.
    Returns an empty list if no IPs are excluded.
    """
    if not excluded_ips:
        return []
    return [{"terms": {"source.ip": excluded_ips}}]
