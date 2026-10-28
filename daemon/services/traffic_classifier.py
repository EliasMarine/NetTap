"""
Traffic classification service for NetTap.

Maps raw protocol names and destination domains into human-readable
categories (Streaming, Gaming, Social Media, etc.) for consumer-friendly
traffic breakdowns.
"""

import fnmatch
import logging
import os

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
    "shopping": "Shopping",
    "news": "News & Media",
    "ads": "Ads & Tracking",
    "updates": "Updates & Downloads",
    "suspicious": "Suspicious",
    "other": "Other",
}

# ---------------------------------------------------------------------------
# ASN organisation → category mapping (substring match on destination.as.full)
# ---------------------------------------------------------------------------

ASN_CATEGORY_MAP: dict[str, str] = {
    # Streaming
    "Netflix": "streaming", "Spotify": "streaming", "Hulu": "streaming",
    "Disney": "streaming", "Twitch": "streaming", "Plex": "streaming",
    "Roku": "streaming", "Crunchyroll": "streaming", "SoundCloud": "streaming",
    "Pandora": "streaming", "Deezer": "streaming", "Tidal": "streaming",
    "Vimeo": "streaming", "DailyMotion": "streaming", "Peacock": "streaming",
    "Paramount": "streaming", "HBO": "streaming", "Discovery": "streaming",
    "fuboTV": "streaming", "Sling": "streaming", "Apple TV": "streaming",
    "iQIYI": "streaming", "YouTube": "streaming",
    # Gaming
    "Valve": "gaming", "Riot Games": "gaming", "Epic Games": "gaming",
    "Nintendo": "gaming", "Electronic Arts": "gaming", "Activision": "gaming",
    "Blizzard": "gaming", "Ubisoft": "gaming", "Take-Two": "gaming",
    "Roblox": "gaming", "Bungie": "gaming", "Mojang": "gaming",
    "Unity": "gaming", "Supercell": "gaming", "miHoYo": "gaming",
    # Social Media
    "Facebook": "social", "Instagram": "social", "Meta Platforms": "social",
    "Twitter": "social", "Snap": "social", "Snapchat": "social",
    "TikTok": "social", "ByteDance": "social", "Reddit": "social",
    "Pinterest": "social", "LinkedIn": "social", "Tumblr": "social",
    # Communication
    "Zoom": "communication", "Slack": "communication", "Discord": "communication",
    "Telegram": "communication", "Signal": "communication", "Vonage": "communication",
    "RingCentral": "communication", "Twilio": "communication",
    "GoTo": "communication", "Webex": "communication",
    # Work & Productivity
    "Atlassian": "work", "Notion": "work", "Salesforce": "work",
    "Dropbox": "work", "Box, Inc": "work", "DocuSign": "work",
    "Asana": "work", "Monday.com": "work", "Hubspot": "work",
    "Zendesk": "work", "Freshworks": "work", "Canva": "work",
    "Figma": "work", "Adobe": "work", "Intuit": "work", "Autodesk": "work",
    # Cloud & Hosting
    "Amazon.com": "cloud", "Amazon Web Services": "cloud",
    "Amazon Technologies": "cloud", "DigitalOcean": "cloud",
    "Oracle": "cloud", "IBM": "cloud", "Linode": "cloud",
    "Vultr": "cloud", "OVH": "cloud", "Hetzner": "cloud",
    "Rackspace": "cloud", "Heroku": "cloud", "Vercel": "cloud", "Netlify": "cloud",
    # Shopping
    "Shopify": "shopping", "eBay": "shopping", "Walmart": "shopping",
    "Etsy": "shopping", "Target": "shopping", "Wayfair": "shopping",
    "Best Buy": "shopping", "Alibaba": "shopping", "Wish": "shopping",
    # News & Media
    "CNN": "news", "New York Times": "news", "Washington Post": "news",
    "BBC": "news", "Reuters": "news", "Associated Press": "news",
    "NPR": "news", "Fox": "news", "NBC": "news", "CBS": "news",
    "Vox Media": "news", "BuzzFeed": "news", "Conde Nast": "news",
    "Hearst": "news", "Gannett": "news", "Tribune": "news",
    # Ads & Tracking
    "DoubleClick": "ads", "TradeDesk": "ads", "Criteo": "ads",
    "AppNexus": "ads", "Taboola": "ads", "Outbrain": "ads",
    "comScore": "ads", "Nielsen": "ads",
    # Updates & Downloads
    "Canonical": "updates", "Red Hat": "updates", "SUSE": "updates",
    # Security & VPN
    "Cloudflare": "security", "Quad9": "security", "OpenDNS": "security",
    "CrowdStrike": "security", "Palo Alto": "security", "Fortinet": "security",
    "Zscaler": "security", "NordVPN": "security", "ExpressVPN": "security",
    "Mullvad": "security", "Let's Encrypt": "security", "DigiCert": "security",
    # CDN & Infrastructure
    "Akamai": "web", "Fastly": "web", "Limelight": "web",
    "StackPath": "web", "Edgecast": "web",
    # IoT & Smart Home
    "Philips": "iot", "TP-Link": "iot", "Tuya": "iot", "ecobee": "iot",
    "Wyze": "iot", "Arlo": "iot", "iRobot": "iot", "Sonos": "iot",
    "Nanit": "iot", "Ring": "iot", "Nest": "iot", "SimpliSafe": "iot",
    "Honeywell": "iot", "Ubiquiti": "iot", "Netgear": "iot",
    # Big Tech (classified by primary residential use)
    "Google": "streaming",  # YouTube dominates residential bytes
    "Microsoft": "work",  # Office 365, Teams
    "Apple": "updates",  # iCloud, Software Update
    "PayPal": "shopping", "Stripe": "shopping", "Square": "shopping",
    # Email
    "Proton": "email", "Fastmail": "email", "Mailchimp": "email",
    "SendGrid": "email", "Mailgun": "email",
    # File Transfer
    "WeTransfer": "file_transfer", "Mega": "file_transfer",
    "MediaFire": "file_transfer", "Backblaze": "file_transfer",
}


def classify_asn(asn_full: str) -> str:
    """Map an ASN full string (e.g. 'AS2906 Netflix Inc') to a category key."""
    if not asn_full:
        return "other"
    for substring, category in ASN_CATEGORY_MAP.items():
        if substring.lower() in asn_full.lower():
            return category
    return "other"


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
    ("*.pandora.com", "streaming"),
    ("*.deezer.com", "streaming"),
    ("*.tidal.com", "streaming"),
    ("*.roku.com", "streaming"),
    ("*.fubo.tv", "streaming"),
    ("*.sling.com", "streaming"),
    ("*.vudu.com", "streaming"),
    ("*.britbox.com", "streaming"),
    ("*.discoveryplus.com", "streaming"),
    ("*.curiositystream.com", "streaming"),
    ("*.video.cdn.*.com", "streaming"),
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
    ("*.ubisoft.com", "gaming"),
    ("*.ubi.com", "gaming"),
    ("*.rockstargames.com", "gaming"),
    ("*.activision.com", "gaming"),
    ("*.mojang.com", "gaming"),
    ("*.unity3d.com", "gaming"),
    ("*.roblox.com", "gaming"),
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
    ("*.tumblr.com", "social"),
    ("*.mastodon.*", "social"),
    ("*.threads.net", "social"),
    ("*.bsky.app", "social"),
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
    # Shopping & E-Commerce
    ("*.amazon.com", "shopping"),
    ("*.amazon.co.*", "shopping"),
    ("*.ebay.com", "shopping"),
    ("*.etsy.com", "shopping"),
    ("*.shopify.com", "shopping"),
    ("*.walmart.com", "shopping"),
    ("*.target.com", "shopping"),
    ("*.bestbuy.com", "shopping"),
    ("*.aliexpress.com", "shopping"),
    ("*.wish.com", "shopping"),
    ("*.wayfair.com", "shopping"),
    ("*.newegg.com", "shopping"),
    ("*.stripe.com", "shopping"),
    ("*.paypal.com", "shopping"),
    # News & Media
    ("*.cnn.com", "news"),
    ("*.bbc.com", "news"),
    ("*.bbc.co.uk", "news"),
    ("*.nytimes.com", "news"),
    ("*.washingtonpost.com", "news"),
    ("*.reuters.com", "news"),
    ("*.apnews.com", "news"),
    ("*.foxnews.com", "news"),
    ("*.nbcnews.com", "news"),
    ("*.abcnews.com", "news"),
    ("*.theguardian.com", "news"),
    ("*.wsj.com", "news"),
    ("*.medium.com", "news"),
    ("*.substack.com", "news"),
    ("*.techcrunch.com", "news"),
    ("*.theverge.com", "news"),
    ("*.arstechnica.com", "news"),
    ("*.wired.com", "news"),
    # Ads & Tracking
    ("*.doubleclick.net", "ads"),
    ("*.googlesyndication.com", "ads"),
    ("*.googleadservices.com", "ads"),
    ("*.google-analytics.com", "ads"),
    ("*.googletagmanager.com", "ads"),
    ("*.facebook.net", "ads"),
    ("*.fbsbx.com", "ads"),
    ("*.adsrvr.org", "ads"),
    ("*.adnxs.com", "ads"),
    ("*.criteo.com", "ads"),
    ("*.criteo.net", "ads"),
    ("*.taboola.com", "ads"),
    ("*.outbrain.com", "ads"),
    ("*.scorecardresearch.com", "ads"),
    ("*.quantserve.com", "ads"),
    ("*.rubiconproject.com", "ads"),
    ("*.pubmatic.com", "ads"),
    ("*.openx.net", "ads"),
    ("*.hotjar.com", "ads"),
    ("*.segment.io", "ads"),
    ("*.segment.com", "ads"),
    ("*.mixpanel.com", "ads"),
    ("*.amplitude.com", "ads"),
    ("*.branch.io", "ads"),
    ("*.adjust.com", "ads"),
    ("*.appsflyer.com", "ads"),
    # Updates & Downloads
    ("*.windowsupdate.com", "updates"),
    ("*.windows.com", "updates"),
    ("*.microsoft.com/update*", "updates"),
    ("*.download.microsoft.com", "updates"),
    ("*.apple.com/software*", "updates"),
    ("*.swcdn.apple.com", "updates"),
    ("*.updates.cdn-apple.com", "updates"),
    ("*.mesu.apple.com", "updates"),
    ("*.appldnld.apple.com", "updates"),
    ("*.swdist.apple.com", "updates"),
    ("*.ubuntu.com", "updates"),
    ("*.debian.org", "updates"),
    ("*.fedoraproject.org", "updates"),
    ("*.npmjs.org", "updates"),
    ("*.npmjs.com", "updates"),
    ("*.pypi.org", "updates"),
    ("*.registry.npmjs.org", "updates"),
    ("*.docker.io", "updates"),
    ("*.docker.com", "updates"),
    ("*.ghcr.io", "updates"),
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

# OLD CODE START — separate per-log-type indices replaced by unified Malcolm index
# ZEEK_DNS_INDEX = "zeek-dns-*"
# ZEEK_CONN_INDEX = "zeek-*"
# OLD CODE END
NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")


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


async def get_category_stats(
    client, from_ts: str, to_ts: str
) -> list[dict]:
    """Aggregate traffic bytes by ASN organisation, map to categories."""
    query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"event.provider": "zeek"}},
                    {"term": {"event.dataset": "conn"}},
                    {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
                ]
            }
        },
        "aggs": {
            "asn_breakdown": {
                "terms": {
                    "field": "destination.as.full.keyword",
                    "size": 500,
                },
                "aggs": {
                    "total_bytes": {
                        "sum": {
                            "script": {
                                "source": (
                                    "(doc['source.bytes'].size() > 0 ? doc['source.bytes'].value : 0)"
                                    " + (doc['destination.bytes'].size() > 0 ? doc['destination.bytes'].value : 0)"
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
        resp = client.search(index=NETWORK_INDEX, body=query)
    except Exception:
        logger.error("get_category_stats: OpenSearch query failed", exc_info=True)
        return []

    cat_data: dict[str, dict] = {}
    for bucket in resp.get("aggregations", {}).get("asn_breakdown", {}).get("buckets", []):
        asn_full = bucket["key"]
        cat_key = classify_asn(asn_full)
        total_bytes = int(bucket.get("total_bytes", {}).get("value", 0))
        doc_count = bucket.get("doc_count", 0)

        if cat_key not in cat_data:
            cat_data[cat_key] = {
                "name": cat_key,
                "label": CATEGORIES.get(cat_key, cat_key.title()),
                "total_bytes": 0,
                "connection_count": 0,
                "top_services": [],
            }

        cat_data[cat_key]["total_bytes"] += total_bytes
        cat_data[cat_key]["connection_count"] += doc_count

        # Merge services that share the same org name after stripping ASN prefix.
        # e.g. "AS16509 Amazon.com, Inc." and "AS14618 Amazon.com, Inc." both
        # become "Amazon.com, Inc." — their bytes must be summed.
        service_name = asn_full.split(" ", 1)[1] if " " in asn_full else asn_full
        svc_map = cat_data[cat_key].setdefault("_svc_map", {})
        svc_map[service_name] = svc_map.get(service_name, 0) + total_bytes

    for cat in cat_data.values():
        svc_map = cat.pop("_svc_map", {})
        cat["top_services"] = [
            {"name": name, "bytes": total} for name, total in svc_map.items()
        ]
        cat["top_services"].sort(key=lambda s: s["bytes"], reverse=True)
        cat["top_services"] = cat["top_services"][:10]

    result = sorted(cat_data.values(), key=lambda c: c["total_bytes"], reverse=True)
    return result


# OLD CODE START — service/domain-based get_category_stats replaced by ASN-based implementation above
# async def get_category_stats(client, from_ts: str, to_ts: str) -> list[dict]:
#     """Query OpenSearch for traffic grouped by category.
#
#     Strategy:
#     1. Get top domains from zeek-dns-* indices
#     2. Classify each domain into a category
#     3. Aggregate bytes and connection counts per category
#
#     Returns a list of dicts with keys: name, label, total_bytes,
#     connection_count, top_domains.
#     """
#     time_filter = {
#         "range": {
#             "@timestamp": {
#                 "gte": from_ts,
#                 "lte": to_ts,
#                 "format": "strict_date_optional_time",
#             }
#         }
#     }
#
#     # Step 1: Get top domains with their query counts from DNS logs
#     dns_query = {
#         "size": 0,
#         "query": {"bool": {"filter": [
#             time_filter,
#             {"term": {"event.provider": "zeek"}},
#             {"term": {"event.dataset": "dns"}},
#         ]}},
#         "aggs": {
#             "top_domains": {
#                 "terms": {
#                     "field": "zeek.dns.query.keyword",
#                     "size": 500,
#                 },
#             }
#         },
#     }
#
#     try:
#         dns_result = client.search(index=NETWORK_INDEX, body=dns_query)
#     except Exception as exc:
#         logger.error("OpenSearch error fetching DNS domains: %s", exc)
#         return []
#
#     domain_buckets = (
#         dns_result.get("aggregations", {}).get("top_domains", {}).get("buckets", [])
#     )
#
#     # Step 2: Also get connection-level stats with service and port info
#     conn_query = {
#         "size": 0,
#         "query": {"bool": {"filter": [
#             time_filter,
#             {"term": {"event.provider": "zeek"}},
#             {"term": {"event.dataset": "conn"}},
#         ]}},
#         "aggs": {
#             "by_service": {
#                 "terms": {"field": "network.protocol.keyword", "size": 50, "missing": "unknown"},
#                 "aggs": {
#                     "total_bytes": {
#                         "sum": {
#                             "script": {
#                                 "source": (
#                                     "(doc['source.bytes'].size() > 0 ? doc['source.bytes'].value : 0)"
#                                     " + (doc['destination.bytes'].size() > 0 ? doc['destination.bytes'].value : 0)"
#                                 ),
#                                 "lang": "painless",
#                             }
#                         }
#                     },
#                 },
#             }
#         },
#     }
#
#     try:
#         conn_result = client.search(index=NETWORK_INDEX, body=conn_query)
#     except Exception as exc:
#         logger.error("OpenSearch error fetching connection stats: %s", exc)
#         return []
#
#     service_buckets = (
#         conn_result.get("aggregations", {}).get("by_service", {}).get("buckets", [])
#     )
#
#     # Step 3: Build category aggregation
#     category_data: dict[str, dict] = {}
#
#     for cat_key in CATEGORIES:
#         category_data[cat_key] = {
#             "total_bytes": 0,
#             "connection_count": 0,
#             "top_domains": {},
#         }
#
#     # Classify DNS domains
#     for bucket in domain_buckets:
#         domain = bucket.get("key", "")
#         count = bucket.get("doc_count", 0)
#         cat = classify_domain(domain)
#
#         if cat not in category_data:
#             category_data[cat] = {
#                 "total_bytes": 0,
#                 "connection_count": 0,
#                 "top_domains": {},
#             }
#
#         category_data[cat]["connection_count"] += count
#         category_data[cat]["top_domains"][domain] = (
#             category_data[cat]["top_domains"].get(domain, 0) + count
#         )
#
#     # Classify by service (for bytes aggregation)
#     for bucket in service_buckets:
#         service_name = bucket.get("key", "")
#         total_bytes = bucket.get("total_bytes", {}).get("value", 0) or 0
#         cat = classify_by_service(service_name)
#
#         if cat not in category_data:
#             category_data[cat] = {
#                 "total_bytes": 0,
#                 "connection_count": 0,
#                 "top_domains": {},
#             }
#
#         category_data[cat]["total_bytes"] += total_bytes
#
#     # Step 4: Build response
#     result = []
#     for cat_key, data in category_data.items():
#         if data["total_bytes"] == 0 and data["connection_count"] == 0:
#             continue
#
#         sorted_domains = sorted(
#             data["top_domains"].items(), key=lambda x: x[1], reverse=True
#         )[:10]
#
#         result.append(
#             {
#                 "name": cat_key,
#                 "label": get_category_label(cat_key),
#                 "total_bytes": data["total_bytes"],
#                 "connection_count": data["connection_count"],
#                 "top_domains": [{"domain": d, "count": c} for d, c in sorted_domains],
#             }
#         )
#
#     result.sort(key=lambda x: x["total_bytes"], reverse=True)
#
#     return result
# OLD CODE END


def _asn_filters_for_category(category: str) -> list[str]:
    """Return list of ASN org substrings that map to the given category."""
    return [substr for substr, cat in ASN_CATEGORY_MAP.items() if cat == category]


async def get_category_devices(
    client, category: str, from_ts: str, to_ts: str, limit: int = 50,
    fingerprint=None,
) -> list[dict]:
    """Get per-device bandwidth breakdown for a traffic category."""
    asn_substrings = _asn_filters_for_category(category)
    if not asn_substrings:
        return []

    should_clauses = [
        {"wildcard": {"destination.as.full.keyword": f"*{substr}*"}}
        for substr in asn_substrings
    ]

    query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"event.provider": "zeek"}},
                    {"term": {"event.dataset": "conn"}},
                    {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
                ],
                "must": [
                    {"bool": {"should": should_clauses, "minimum_should_match": 1}},
                ],
            }
        },
        "aggs": {
            "devices": {
                "terms": {"field": "source.ip.keyword", "size": limit},
                "aggs": {
                    "total_bytes": {
                        "sum": {
                            "script": {
                                "source": (
                                    "(doc['source.bytes'].size() > 0 ? doc['source.bytes'].value : 0)"
                                    " + (doc['destination.bytes'].size() > 0 ? doc['destination.bytes'].value : 0)"
                                ),
                                "lang": "painless",
                            }
                        }
                    },
                    "download_bytes": {"sum": {"field": "destination.bytes"}},
                    "upload_bytes": {"sum": {"field": "source.bytes"}},
                },
            }
        },
    }

    try:
        resp = client.search(index=NETWORK_INDEX, body=query)
    except Exception:
        logger.error("get_category_devices: OpenSearch query failed for category=%s", category, exc_info=True)
        return []

    devices = []
    for bucket in resp.get("aggregations", {}).get("devices", {}).get("buckets", []):
        devices.append({
            "ip": bucket["key"],
            "total_bytes": int(bucket.get("total_bytes", {}).get("value", 0)),
            "download_bytes": int(bucket.get("download_bytes", {}).get("value", 0)),
            "upload_bytes": int(bucket.get("upload_bytes", {}).get("value", 0)),
            "connections": bucket.get("doc_count", 0),
        })

    if fingerprint:
        for d in devices:
            try:
                hostname = fingerprint.get_hostname_for_ip(client, d["ip"], from_ts, to_ts)
                d["hostname"] = hostname
            except Exception:
                d["hostname"] = None

    devices.sort(key=lambda d: d["total_bytes"], reverse=True)
    return devices


async def get_category_services(
    client, category: str, from_ts: str, to_ts: str, limit: int = 10
) -> list[dict]:
    """Get top services (ASN orgs) within a traffic category, sorted by bytes."""
    asn_substrings = _asn_filters_for_category(category)
    if not asn_substrings:
        return []

    should_clauses = [
        {"wildcard": {"destination.as.full.keyword": f"*{substr}*"}}
        for substr in asn_substrings
    ]

    query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"event.provider": "zeek"}},
                    {"term": {"event.dataset": "conn"}},
                    {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
                ],
                "must": [
                    {"bool": {"should": should_clauses, "minimum_should_match": 1}},
                ],
            }
        },
        "aggs": {
            "services": {
                "terms": {"field": "destination.as.full.keyword", "size": limit},
                "aggs": {
                    "total_bytes": {
                        "sum": {
                            "script": {
                                "source": (
                                    "(doc['source.bytes'].size() > 0 ? doc['source.bytes'].value : 0)"
                                    " + (doc['destination.bytes'].size() > 0 ? doc['destination.bytes'].value : 0)"
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
        resp = client.search(index=NETWORK_INDEX, body=query)
    except Exception:
        logger.error("get_category_services: OpenSearch query failed for category=%s", category, exc_info=True)
        return []

    # Merge buckets that share the same org name after stripping ASN prefix.
    # e.g. "AS16509 Amazon.com, Inc." and "AS14618 Amazon.com, Inc." both
    # become "Amazon.com, Inc." — their bytes and connections must be summed.
    merged: dict[str, dict] = {}
    for bucket in resp.get("aggregations", {}).get("services", {}).get("buckets", []):
        asn_full = bucket["key"]
        # Strip ASN number prefix (e.g., "AS2906 Netflix Inc" → "Netflix Inc")
        service_name = asn_full.split(" ", 1)[1] if " " in asn_full else asn_full
        if service_name not in merged:
            merged[service_name] = {"bytes": 0, "connections": 0}
        merged[service_name]["bytes"] += int(
            bucket.get("total_bytes", {}).get("value", 0)
        )
        merged[service_name]["connections"] += bucket.get("doc_count", 0)

    services = [{"name": name, "bytes": m["bytes"], "connections": m["connections"]} for name, m in merged.items()]
    services.sort(key=lambda s: s["bytes"], reverse=True)
    return services


async def get_category_bandwidth(
    client, category: str, from_ts: str, to_ts: str, interval: str = "15m"
) -> list[dict]:
    """Get bandwidth time-series for a traffic category, broken into download/upload."""
    asn_substrings = _asn_filters_for_category(category)
    if not asn_substrings:
        return []

    should_clauses = [
        {"wildcard": {"destination.as.full.keyword": f"*{substr}*"}}
        for substr in asn_substrings
    ]

    query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"event.provider": "zeek"}},
                    {"term": {"event.dataset": "conn"}},
                    {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
                ],
                "must": [
                    {"bool": {"should": should_clauses, "minimum_should_match": 1}},
                ],
            }
        },
        "aggs": {
            "bandwidth_over_time": {
                "date_histogram": {
                    "field": "@timestamp",
                    "fixed_interval": interval,
                    "min_doc_count": 0,
                    "extended_bounds": {"min": from_ts, "max": to_ts},
                },
                "aggs": {
                    "download_bytes": {"sum": {"field": "destination.bytes"}},
                    "upload_bytes": {"sum": {"field": "source.bytes"}},
                },
            }
        },
    }

    try:
        resp = client.search(index=NETWORK_INDEX, body=query)
    except Exception:
        logger.error("get_category_bandwidth: OpenSearch query failed for category=%s", category, exc_info=True)
        return []

    series = []
    for bucket in resp.get("aggregations", {}).get("bandwidth_over_time", {}).get("buckets", []):
        dl = int(bucket.get("download_bytes", {}).get("value", 0) or 0)
        ul = int(bucket.get("upload_bytes", {}).get("value", 0) or 0)
        series.append({
            "timestamp": bucket.get("key_as_string", bucket.get("key")),
            "download_bytes": dl,
            "upload_bytes": ul,
            "total_bytes": dl + ul,
            "connections": bucket.get("doc_count", 0),
        })

    return series
