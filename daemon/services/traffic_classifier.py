"""
Traffic classification service for NetTap.

Maps raw protocol names and destination domains into human-readable
categories (Streaming, Gaming, Social Media, etc.) for consumer-friendly
traffic breakdowns.
"""

import fnmatch
import logging

logger = logging.getLogger("nettap.services.traffic_classifier")

# ---------------------------------------------------------------------------
# Category definitions
# ---------------------------------------------------------------------------

CATEGORIES = {
    "streaming": "Streaming",
    "gaming": "Gaming",
    "social": "Social Media",
    "communication": "Communication",
    "work": "Work & Productivity",
    "iot": "IoT & Smart Home",
    "cloud": "Cloud Services",
    "file_transfer": "File Transfer",
    "dns": "DNS",
    "email": "Email",
    "web": "Web Browsing",
    "security": "Security & VPN",
    "suspicious": "Suspicious",
    "other": "Other",
}

# ---------------------------------------------------------------------------
# Domain patterns to categories (most specific first)
# ---------------------------------------------------------------------------

DOMAIN_RULES: list[tuple[str, str]] = [
    # Streaming
    ("*.netflix.com", "streaming"),
    ("*.nflxvideo.net", "streaming"),
    ("*.youtube.com", "streaming"),
    ("*.googlevideo.com", "streaming"),
    ("*.hulu.com", "streaming"),
    ("*.disneyplus.com", "streaming"),
    ("*.hbomax.com", "streaming"),
    ("*.max.com", "streaming"),
    ("*.plex.tv", "streaming"),
    ("*.plexapp.com", "streaming"),
    ("*.spotify.com", "streaming"),
    ("*.scdn.co", "streaming"),
    ("*.twitch.tv", "streaming"),
    ("*.ttvnw.net", "streaming"),
    ("*.crunchyroll.com", "streaming"),
    ("*.peacocktv.com", "streaming"),
    ("*.paramountplus.com", "streaming"),
    ("*.apple.com/tv", "streaming"),
    # Gaming
    ("*.steampowered.com", "gaming"),
    ("*.steamcontent.com", "gaming"),
    ("*.valvesoftware.com", "gaming"),
    ("*.epicgames.com", "gaming"),
    ("*.unrealengine.com", "gaming"),
    ("*.xboxlive.com", "gaming"),
    ("*.xbox.com", "gaming"),
    ("*.playstation.com", "gaming"),
    ("*.playstation.net", "gaming"),
    ("*.nintendo.com", "gaming"),
    ("*.riotgames.com", "gaming"),
    ("*.blizzard.com", "gaming"),
    ("*.battle.net", "gaming"),
    ("*.ea.com", "gaming"),
    # Social Media
    ("*.facebook.com", "social"),
    ("*.fbcdn.net", "social"),
    ("*.instagram.com", "social"),
    ("*.twitter.com", "social"),
    ("*.x.com", "social"),
    ("*.tiktok.com", "social"),
    ("*.tiktokcdn.com", "social"),
    ("*.snapchat.com", "social"),
    ("*.reddit.com", "social"),
    ("*.redditmedia.com", "social"),
    ("*.linkedin.com", "social"),
    ("*.pinterest.com", "social"),
    # Communication
    ("*.zoom.us", "communication"),
    ("*.zoom.com", "communication"),
    ("*.teams.microsoft.com", "communication"),
    ("*.skype.com", "communication"),
    ("*.discord.com", "communication"),
    ("*.discordapp.com", "communication"),
    ("*.slack.com", "communication"),
    ("*.slack-msgs.com", "communication"),
    ("*.webex.com", "communication"),
    ("*.whatsapp.com", "communication"),
    ("*.whatsapp.net", "communication"),
    ("*.signal.org", "communication"),
    ("*.facetime.apple.com", "communication"),
    # Work & Productivity
    ("*.github.com", "work"),
    ("*.githubusercontent.com", "work"),
    ("*.gitlab.com", "work"),
    ("*.atlassian.com", "work"),
    ("*.jira.com", "work"),
    ("*.confluence.com", "work"),
    ("*.notion.so", "work"),
    ("*.notion.com", "work"),
    ("*.figma.com", "work"),
    ("*.canva.com", "work"),
    ("*.office.com", "work"),
    ("*.office365.com", "work"),
    ("*.sharepoint.com", "work"),
    ("*.onedrive.com", "work"),
    ("*.docs.google.com", "work"),
    ("*.drive.google.com", "work"),
    # IoT & Smart Home
    ("*.ring.com", "iot"),
    ("*.nest.com", "iot"),
    ("*.home.nest.com", "iot"),
    ("*.wyze.com", "iot"),
    ("*.tp-link.com", "iot"),
    ("*.kasa.com", "iot"),
    ("*.philips-hue.com", "iot"),
    ("*.meethue.com", "iot"),
    ("*.sonos.com", "iot"),
    ("*.ecobee.com", "iot"),
    ("*.smartthings.com", "iot"),
    ("*.tuya.com", "iot"),
    ("*.hubitat.com", "iot"),
    # Cloud Services
    ("*.amazonaws.com", "cloud"),
    ("*.aws.amazon.com", "cloud"),
    ("*.azure.com", "cloud"),
    ("*.azure.net", "cloud"),
    ("*.googleapis.com", "cloud"),
    ("*.gstatic.com", "cloud"),
    ("*.cloudflare.com", "cloud"),
    ("*.cloudflare-dns.com", "cloud"),
    ("*.akamai.com", "cloud"),
    ("*.akamaized.net", "cloud"),
    ("*.fastly.net", "cloud"),
    # File Transfer
    ("*.dropbox.com", "file_transfer"),
    ("*.wetransfer.com", "file_transfer"),
    ("*.mega.nz", "file_transfer"),
    ("*.box.com", "file_transfer"),
    # Security & VPN
    ("*.nordvpn.com", "security"),
    ("*.expressvpn.com", "security"),
    ("*.wireguard.com", "security"),
    ("*.torproject.org", "security"),
    ("*.protonvpn.com", "security"),
    ("*.protonmail.com", "security"),
    # Email
    ("*.gmail.com", "email"),
    ("*.outlook.com", "email"),
    ("*.yahoo.com", "email"),
    ("*.mail.com", "email"),
    # Suspicious (Tor, crypto-mining pools, etc.)
    ("*.onion", "suspicious"),
    ("*.mining.*", "suspicious"),
    ("*.coinhive.com", "suspicious"),
]

# ---------------------------------------------------------------------------
# Port-based fallback classification
# ---------------------------------------------------------------------------

PORT_RULES: dict[int, str] = {
    80: "web",
    443: "web",
    53: "dns",
    22: "security",
    25: "email",
    465: "email",
    587: "email",
    993: "email",
    143: "email",
    21: "file_transfer",
    3389: "work",
    5060: "communication",
    5061: "communication",
}

# ---------------------------------------------------------------------------
# Zeek service field to category
# ---------------------------------------------------------------------------

SERVICE_RULES: dict[str, str] = {
    "http": "web",
    "ssl": "web",
    "dns": "dns",
    "ssh": "security",
    "smtp": "email",
    "ftp": "file_transfer",
    "imap": "email",
    "pop3": "email",
    "sip": "communication",
    "rdp": "work",
    "dhcp": "other",
    "ntp": "other",
}

# DNS index for category stats queries
ZEEK_DNS_INDEX = "zeek-dns-*"
ZEEK_CONN_INDEX = "zeek-*"


# ---------------------------------------------------------------------------
# Classification functions
# ---------------------------------------------------------------------------


def classify_domain(domain: str) -> str:
    """Match a domain against DOMAIN_RULES using glob-style matching.

    Performs case-insensitive matching. Returns the category key if a
    rule matches, otherwise returns "other".
    """
    if not domain:
        return "other"

    domain_lower = domain.lower().strip()

    for pattern, category in DOMAIN_RULES:
        if fnmatch.fnmatch(domain_lower, pattern.lower()):
            return category

    return "other"


def classify_by_service(service: str) -> str:
    """Look up a Zeek service field in SERVICE_RULES.

    Returns the category key if found, otherwise "other".
    """
    if not service:
        return "other"

    return SERVICE_RULES.get(service.lower().strip(), "other")


def classify_by_port(port: int) -> str:
    """Look up a port number in PORT_RULES.

    Returns the category key if found, otherwise "other".
    """
    if port is None:
        return "other"

    return PORT_RULES.get(port, "other")


def classify_connection(
    service: str | None = None,
    domain: str | None = None,
    port: int | None = None,
) -> str:
    """Classify a network connection using the best available signal.

    Priority order: domain > service > port > "other".
    Tries domain classification first (most specific), then falls back
    to Zeek service name, then port number, and finally "other".
    """
    # Try domain first (most specific)
    if domain:
        result = classify_domain(domain)
        if result != "other":
            return result

    # Fall back to Zeek service field
    if service:
        result = classify_by_service(service)
        if result != "other":
            return result

    # Fall back to port number
    if port is not None:
        result = classify_by_port(port)
        if result != "other":
            return result

    return "other"


def get_category_label(key: str) -> str:
    """Convert a category key to its human-readable display name.

    Returns the display name from CATEGORIES, or the key itself
    with title-casing if the key is not found.
    """
    return CATEGORIES.get(key, key.replace("_", " ").title())


async def get_category_stats(client, from_ts: str, to_ts: str) -> list[dict]:
    """Query OpenSearch for traffic grouped by category.

    Strategy:
    1. Get top domains from zeek-dns-* indices
    2. Classify each domain into a category
    3. Aggregate bytes and connection counts per category

    Returns a list of dicts with keys: name, label, total_bytes,
    connection_count, top_domains.
    """
    time_filter = {
        "range": {
            "ts": {
                "gte": from_ts,
                "lte": to_ts,
                "format": "strict_date_optional_time",
            }
        }
    }

    # Step 1: Get top domains with their query counts from DNS logs
    dns_query = {
        "size": 0,
        "query": {"bool": {"filter": [time_filter]}},
        "aggs": {
            "top_domains": {
                "terms": {
                    "field": "query",
                    "size": 500,
                },
            }
        },
    }

    try:
        dns_result = client.search(index=ZEEK_DNS_INDEX, body=dns_query)
    except Exception as exc:
        logger.error("OpenSearch error fetching DNS domains: %s", exc)
        return []

    domain_buckets = (
        dns_result.get("aggregations", {}).get("top_domains", {}).get("buckets", [])
    )

    # Step 2: Also get connection-level stats with service and port info
    conn_query = {
        "size": 0,
        "query": {"bool": {"filter": [time_filter]}},
        "aggs": {
            "by_service": {
                "terms": {"field": "service", "size": 50, "missing": "unknown"},
                "aggs": {
                    "total_bytes": {
                        "sum": {
                            "script": {
                                "source": (
                                    "(doc['orig_bytes'].size() > 0 ? doc['orig_bytes'].value : 0)"
                                    " + (doc['resp_bytes'].size() > 0 ? doc['resp_bytes'].value : 0)"
                                ),
                                "lang": "painless",
                            }
                        }
                    },
                },
            }
        },
    }

    try:
        conn_result = client.search(index=ZEEK_CONN_INDEX, body=conn_query)
    except Exception as exc:
        logger.error("OpenSearch error fetching connection stats: %s", exc)
        return []

    service_buckets = (
        conn_result.get("aggregations", {}).get("by_service", {}).get("buckets", [])
    )

    # Step 3: Build category aggregation
    # Map: category_key -> {total_bytes, connection_count, top_domains: {domain: count}}
    category_data: dict[str, dict] = {}

    for cat_key in CATEGORIES:
        category_data[cat_key] = {
            "total_bytes": 0,
            "connection_count": 0,
            "top_domains": {},
        }

    # Classify DNS domains
    for bucket in domain_buckets:
        domain = bucket.get("key", "")
        count = bucket.get("doc_count", 0)
        cat = classify_domain(domain)

        if cat not in category_data:
            category_data[cat] = {
                "total_bytes": 0,
                "connection_count": 0,
                "top_domains": {},
            }

        category_data[cat]["connection_count"] += count
        category_data[cat]["top_domains"][domain] = (
            category_data[cat]["top_domains"].get(domain, 0) + count
        )

    # Classify by service (for bytes aggregation)
    for bucket in service_buckets:
        service_name = bucket.get("key", "")
        # OLD CODE START — doc_count was extracted but never used (F841)
        # doc_count = bucket.get("doc_count", 0)
        # OLD CODE END
        total_bytes = bucket.get("total_bytes", {}).get("value", 0) or 0
        cat = classify_by_service(service_name)

        if cat not in category_data:
            category_data[cat] = {
                "total_bytes": 0,
                "connection_count": 0,
                "top_domains": {},
            }

        category_data[cat]["total_bytes"] += total_bytes

    # Step 4: Build response
    result = []
    for cat_key, data in category_data.items():
        if data["total_bytes"] == 0 and data["connection_count"] == 0:
            continue

        # Sort top domains by count, take top 10
        sorted_domains = sorted(
            data["top_domains"].items(), key=lambda x: x[1], reverse=True
        )[:10]

        result.append(
            {
                "name": cat_key,
                "label": get_category_label(cat_key),
                "total_bytes": data["total_bytes"],
                "connection_count": data["connection_count"],
                "top_domains": [{"domain": d, "count": c} for d, c in sorted_domains],
            }
        )

    # Sort by total_bytes descending
    result.sort(key=lambda x: x["total_bytes"], reverse=True)

    return result
