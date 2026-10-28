# ASN-Based Traffic Categories + Sitewide Breadcrumbs — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace broken service-based traffic categories with ASN-based classification, add a per-device drill-down page, and add breadcrumb navigation across all pages.

**Architecture:** Backend rewrites `get_category_stats()` to aggregate by `destination.as.full` ASN field on conn records (single query, accurate bytes). A new `/api/traffic/categories/{category}` endpoint returns per-device breakdown. Frontend adds a `/traffic/[category]` detail page and a sitewide `Breadcrumb.svelte` component in the layout.

**Tech Stack:** Python/aiohttp (daemon), OpenSearch aggregations, SvelteKit 5/TypeScript (web), CSS variables from design system.

---

## Task 1: ASN → Category Mapping Table

**Files:**
- Modify: `daemon/services/traffic_classifier.py` (add after line 38, after CATEGORIES dict)

**Step 1: Add the ASN_CATEGORY_MAP dict**

Add this after the `CATEGORIES` dict (line 38). This maps substrings found in `destination.as.full` (e.g., "AS2906 Netflix Inc") to category keys.

```python
# ---------------------------------------------------------------------------
# ASN Organisation → Category mapping
# Matched by substring against the "destination.as.full" field value.
# Order does not matter — first match wins during iteration.
# ---------------------------------------------------------------------------

ASN_CATEGORY_MAP: dict[str, str] = {
    # ── Streaming ──────────────────────────────────────────────────────────
    "Netflix":          "streaming",
    "Spotify":          "streaming",
    "Hulu":             "streaming",
    "Disney":           "streaming",
    "Twitch":           "streaming",
    "Plex":             "streaming",
    "Roku":             "streaming",
    "Crunchyroll":      "streaming",
    "SoundCloud":       "streaming",
    "Pandora":          "streaming",
    "Deezer":           "streaming",
    "Tidal":            "streaming",
    "Vimeo":            "streaming",
    "DailyMotion":      "streaming",
    "Peacock":          "streaming",
    "Paramount":        "streaming",
    "HBO":              "streaming",
    "Discovery":        "streaming",
    "fuboTV":           "streaming",
    "Sling":            "streaming",
    "Apple TV":         "streaming",
    "iQIYI":            "streaming",

    # ── Gaming ─────────────────────────────────────────────────────────────
    "Valve":            "gaming",
    "Riot Games":       "gaming",
    "Epic Games":       "gaming",
    "Nintendo":         "gaming",
    "Electronic Arts":  "gaming",
    "Activision":       "gaming",
    "Blizzard":         "gaming",
    "Ubisoft":          "gaming",
    "Take-Two":         "gaming",
    "Roblox":           "gaming",
    "Bungie":           "gaming",
    "Mojang":           "gaming",
    "Unity":            "gaming",
    "Supercell":        "gaming",
    "miHoYo":           "gaming",

    # ── Social Media ───────────────────────────────────────────────────────
    "Facebook":         "social",
    "Instagram":        "social",
    "Meta Platforms":   "social",
    "Twitter":          "social",
    "Snap":             "social",
    "Snapchat":         "social",
    "TikTok":           "social",
    "ByteDance":        "social",
    "Reddit":           "social",
    "Pinterest":        "social",
    "LinkedIn":         "social",
    "Tumblr":           "social",

    # ── Communication ──────────────────────────────────────────────────────
    "Zoom":             "communication",
    "Slack":            "communication",
    "Discord":          "communication",
    "Telegram":         "communication",
    "Signal":           "communication",
    "Vonage":           "communication",
    "RingCentral":      "communication",
    "Twilio":           "communication",
    "GoTo":             "communication",
    "Webex":            "communication",

    # ── Work & Productivity ────────────────────────────────────────────────
    "Atlassian":        "work",
    "Notion":           "work",
    "Salesforce":       "work",
    "Dropbox":          "work",
    "Box.com":          "work",
    "Box, Inc":         "work",
    "DocuSign":         "work",
    "Asana":            "work",
    "Monday.com":       "work",
    "Hubspot":          "work",
    "Zendesk":          "work",
    "Freshworks":       "work",
    "Canva":            "work",
    "Figma":            "work",
    "Adobe":            "work",
    "Intuit":           "work",
    "Autodesk":         "work",

    # ── Cloud & Hosting ────────────────────────────────────────────────────
    "Amazon.com":       "cloud",
    "Amazon Web Services": "cloud",
    "Amazon Technologies": "cloud",
    "DigitalOcean":     "cloud",
    "Oracle":           "cloud",
    "IBM":              "cloud",
    "Linode":           "cloud",
    "Vultr":            "cloud",
    "OVH":              "cloud",
    "Hetzner":          "cloud",
    "Rackspace":        "cloud",
    "Heroku":           "cloud",
    "Vercel":           "cloud",
    "Netlify":          "cloud",

    # ── Shopping ───────────────────────────────────────────────────────────
    "Shopify":          "shopping",
    "eBay":             "shopping",
    "Walmart":          "shopping",
    "Etsy":             "shopping",
    "Target":           "shopping",
    "Wayfair":          "shopping",
    "Best Buy":         "shopping",
    "Alibaba":          "shopping",
    "Wish":             "shopping",

    # ── News & Media ───────────────────────────────────────────────────────
    "CNN":              "news",
    "New York Times":   "news",
    "Washington Post":  "news",
    "BBC":              "news",
    "Reuters":          "news",
    "Associated Press": "news",
    "NPR":              "news",
    "Fox":              "news",
    "NBC":              "news",
    "CBS":              "news",
    "Vox Media":        "news",
    "BuzzFeed":         "news",
    "Conde Nast":       "news",
    "Hearst":           "news",
    "Gannett":          "news",
    "Tribune":          "news",

    # ── Ads & Tracking ─────────────────────────────────────────────────────
    "DoubleClick":      "ads",
    "TradeDesk":        "ads",
    "Criteo":           "ads",
    "AppNexus":         "ads",
    "Taboola":          "ads",
    "Outbrain":         "ads",
    "comScore":         "ads",
    "Nielsen":          "ads",
    "IAS":              "ads",
    "Oracle Data Cloud":"ads",

    # ── Updates & Downloads ────────────────────────────────────────────────
    "Canonical":        "updates",
    "Red Hat":          "updates",
    "SUSE":             "updates",
    "CentOS":           "updates",
    "Fedora":           "updates",

    # ── Security & VPN ─────────────────────────────────────────────────────
    "Cloudflare":       "security",
    "Quad9":            "security",
    "OpenDNS":          "security",
    "CrowdStrike":      "security",
    "Palo Alto":        "security",
    "Fortinet":         "security",
    "Zscaler":          "security",
    "NordVPN":          "security",
    "ExpressVPN":       "security",
    "Mullvad":          "security",
    "Let's Encrypt":    "security",
    "DigiCert":         "security",
    "Sectigo":          "security",

    # ── CDN & Infrastructure ───────────────────────────────────────────────
    "Akamai":           "web",
    "Fastly":           "web",
    "Limelight":        "web",
    "StackPath":        "web",
    "KeyCDN":           "web",
    "Edgecast":         "web",

    # ── IoT & Smart Home ──────────────────────────────────────────────────
    "Philips":          "iot",
    "TP-Link":          "iot",
    "Tuya":             "iot",
    "ecobee":           "iot",
    "Wyze":             "iot",
    "Arlo":             "iot",
    "iRobot":           "iot",
    "Sonos":            "iot",
    "Nanit":            "iot",
    "Ring":             "iot",
    "Nest":             "iot",
    "SimpliSafe":       "iot",
    "Honeywell":        "iot",
    "Ubiquiti":         "iot",
    "Netgear":          "iot",

    # ── Big Tech (classified by primary use) ───────────────────────────────
    # Google/YouTube → streaming (YouTube dominates residential bytes)
    "Google":           "streaming",
    "YouTube":          "streaming",
    # Microsoft → work (Office 365, Teams dominate residential use)
    "Microsoft":        "work",
    # Apple → updates (iCloud, Software Update dominate)
    "Apple":            "updates",
    # PayPal/Stripe → shopping (payment processors)
    "PayPal":           "shopping",
    "Stripe":           "shopping",
    "Square":           "shopping",

    # ── Email ──────────────────────────────────────────────────────────────
    "Proton":           "email",
    "Fastmail":         "email",
    "Mailchimp":        "email",
    "SendGrid":         "email",
    "Mailgun":          "email",
    "Postmark":         "email",

    # ── File Transfer ──────────────────────────────────────────────────────
    "WeTransfer":       "file_transfer",
    "Mega":             "file_transfer",
    "MediaFire":        "file_transfer",
    "pCloud":           "file_transfer",
    "Backblaze":        "file_transfer",
}


def classify_asn(asn_full: str) -> str:
    """Map an ASN full string (e.g. 'AS2906 Netflix Inc') to a category key."""
    if not asn_full:
        return "other"
    for substring, category in ASN_CATEGORY_MAP.items():
        if substring.lower() in asn_full.lower():
            return category
    return "other"
```

**Step 2: Write the test**

Create file `daemon/tests/test_asn_classifier.py`:

```python
import pytest
from services.traffic_classifier import classify_asn, ASN_CATEGORY_MAP

class TestClassifyAsn:
    def test_netflix_is_streaming(self):
        assert classify_asn("AS2906 Netflix Inc") == "streaming"

    def test_google_is_streaming(self):
        assert classify_asn("AS15169 Google LLC") == "streaming"

    def test_microsoft_is_work(self):
        assert classify_asn("AS8075 Microsoft Corporation") == "work"

    def test_meta_is_social(self):
        assert classify_asn("AS32934 Meta Platforms, Inc.") == "social"

    def test_valve_is_gaming(self):
        assert classify_asn("AS32590 Valve Corporation") == "gaming"

    def test_amazon_is_cloud(self):
        assert classify_asn("AS16509 Amazon.com, Inc.") == "cloud"

    def test_cloudflare_is_security(self):
        assert classify_asn("AS13335 Cloudflare, Inc.") == "security"

    def test_unknown_asn_is_other(self):
        assert classify_asn("AS99999 Unknown ISP") == "other"

    def test_empty_string_is_other(self):
        assert classify_asn("") == "other"

    def test_none_is_other(self):
        assert classify_asn(None) == "other"

    def test_case_insensitive(self):
        assert classify_asn("AS2906 NETFLIX INC") == "streaming"

    def test_all_categories_have_at_least_one_asn(self):
        mapped_categories = set(ASN_CATEGORY_MAP.values())
        # At minimum these categories should have ASN entries
        expected = {"streaming", "gaming", "social", "communication", "work",
                    "cloud", "shopping", "news", "security", "iot"}
        assert expected.issubset(mapped_categories)
```

**Step 3: Run tests**

```bash
cd daemon && python -m pytest tests/test_asn_classifier.py -v
```

Expected: All 12 tests PASS.

**Step 4: Commit**

```bash
git add daemon/services/traffic_classifier.py daemon/tests/test_asn_classifier.py
git commit -m "feat(traffic): add ASN-to-category mapping table with 150+ entries

Maps destination.as.full ASN org names to traffic categories
for accurate byte classification without cross-document joins.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Rewrite `get_category_stats()` to Use ASN Aggregation

**Files:**
- Modify: `daemon/services/traffic_classifier.py` (replace lines 408–579)
- Test: `daemon/tests/test_category_stats.py`

**Step 1: Write the test**

Create `daemon/tests/test_category_stats.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from services.traffic_classifier import get_category_stats, CATEGORIES

def _mock_os_response(asn_buckets):
    """Build a mock OpenSearch response with ASN aggregation buckets."""
    return {
        "aggregations": {
            "asn_breakdown": {
                "buckets": [
                    {
                        "key": asn_name,
                        "doc_count": doc_count,
                        "total_bytes": {"value": total_bytes},
                    }
                    for asn_name, doc_count, total_bytes in asn_buckets
                ]
            }
        }
    }

@pytest.mark.asyncio
async def test_empty_response_returns_empty_list():
    client = AsyncMock()
    client.search = AsyncMock(return_value=_mock_os_response([]))
    result = await get_category_stats(client, "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
    assert result == []

@pytest.mark.asyncio
async def test_single_asn_maps_to_category():
    client = AsyncMock()
    client.search = AsyncMock(return_value=_mock_os_response([
        ("AS2906 Netflix Inc", 1000, 5_000_000_000),
    ]))
    result = await get_category_stats(client, "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
    streaming = next((c for c in result if c["name"] == "streaming"), None)
    assert streaming is not None
    assert streaming["total_bytes"] == 5_000_000_000
    assert streaming["connection_count"] == 1000

@pytest.mark.asyncio
async def test_multiple_asns_same_category_aggregate():
    client = AsyncMock()
    client.search = AsyncMock(return_value=_mock_os_response([
        ("AS2906 Netflix Inc", 500, 3_000_000_000),
        ("AS15169 Google LLC", 300, 2_000_000_000),
    ]))
    result = await get_category_stats(client, "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
    streaming = next((c for c in result if c["name"] == "streaming"), None)
    assert streaming is not None
    assert streaming["total_bytes"] == 5_000_000_000  # aggregated
    assert streaming["connection_count"] == 800

@pytest.mark.asyncio
async def test_unknown_asn_goes_to_other():
    client = AsyncMock()
    client.search = AsyncMock(return_value=_mock_os_response([
        ("AS99999 Unknown ISP", 100, 500_000),
    ]))
    result = await get_category_stats(client, "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
    other = next((c for c in result if c["name"] == "other"), None)
    assert other is not None
    assert other["total_bytes"] == 500_000

@pytest.mark.asyncio
async def test_results_sorted_by_bytes_descending():
    client = AsyncMock()
    client.search = AsyncMock(return_value=_mock_os_response([
        ("AS32934 Meta Platforms", 200, 1_000_000),
        ("AS2906 Netflix Inc", 500, 5_000_000),
    ]))
    result = await get_category_stats(client, "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
    assert result[0]["total_bytes"] >= result[-1]["total_bytes"]

@pytest.mark.asyncio
async def test_result_includes_label_from_categories():
    client = AsyncMock()
    client.search = AsyncMock(return_value=_mock_os_response([
        ("AS2906 Netflix Inc", 100, 1_000_000),
    ]))
    result = await get_category_stats(client, "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
    streaming = result[0]
    assert streaming["label"] == CATEGORIES["streaming"]

@pytest.mark.asyncio
async def test_result_includes_top_services():
    client = AsyncMock()
    client.search = AsyncMock(return_value=_mock_os_response([
        ("AS2906 Netflix Inc", 500, 3_000_000_000),
        ("AS15169 Google LLC", 300, 2_000_000_000),
    ]))
    result = await get_category_stats(client, "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z")
    streaming = next(c for c in result if c["name"] == "streaming")
    assert len(streaming["top_services"]) >= 1
    assert streaming["top_services"][0]["name"] == "Netflix Inc"
```

**Step 2: Run test to verify it fails**

```bash
cd daemon && python -m pytest tests/test_category_stats.py -v
```

Expected: FAIL (current `get_category_stats` doesn't return `top_services` and uses different query).

**Step 3: Rewrite `get_category_stats()`**

Replace the existing function (lines 408–579) with:

```python
async def get_category_stats(
    client, from_ts: str, to_ts: str
) -> list[dict]:
    """Aggregate traffic bytes by ASN organisation, map to categories.

    Queries conn records for destination.as.full aggregation with byte sums.
    Maps each ASN bucket to a category via classify_asn(), then aggregates
    per-category totals.
    """
    query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"event.provider": "zeek"}},
                    {"term": {"event.dataset": "conn"}},
                    {
                        "range": {
                            "@timestamp": {
                                "gte": from_ts,
                                "lte": to_ts,
                            }
                        }
                    },
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
        resp = await client.search(index="arkime_sessions3-*", body=query)
    except Exception:
        return []

    # Aggregate ASN buckets into categories
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

        # Strip "ASNNNN " prefix for service name
        service_name = asn_full.split(" ", 1)[1] if " " in asn_full else asn_full
        cat_data[cat_key]["top_services"].append(
            {"name": service_name, "bytes": total_bytes}
        )

    # Sort services within each category by bytes desc, keep top 10
    for cat in cat_data.values():
        cat["top_services"].sort(key=lambda s: s["bytes"], reverse=True)
        cat["top_services"] = cat["top_services"][:10]

    # Sort categories by total bytes descending
    result = sorted(cat_data.values(), key=lambda c: c["total_bytes"], reverse=True)
    return result
```

**Step 4: Run tests**

```bash
cd daemon && python -m pytest tests/test_category_stats.py tests/test_asn_classifier.py -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add daemon/services/traffic_classifier.py daemon/tests/test_category_stats.py
git commit -m "feat(traffic): rewrite get_category_stats to ASN-based aggregation

Replaces broken service-based classification (all HTTPS → 'web')
with ASN org name aggregation from destination.as.full field.
Single query, accurate bytes per organization.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 3: New API Endpoint — Category Device Breakdown

**Files:**
- Modify: `daemon/services/traffic_classifier.py` (add new method)
- Modify: `daemon/api/traffic.py` (add new route handler + register route)
- Test: `daemon/tests/test_category_devices.py`

**Step 1: Write the test**

Create `daemon/tests/test_category_devices.py`:

```python
import pytest
from unittest.mock import AsyncMock
from services.traffic_classifier import get_category_devices, ASN_CATEGORY_MAP

def _mock_device_response(device_buckets):
    """Build mock OpenSearch response for per-device aggregation."""
    return {
        "aggregations": {
            "devices": {
                "buckets": [
                    {
                        "key": ip,
                        "doc_count": conns,
                        "total_bytes": {"value": total},
                        "download_bytes": {"value": dl},
                        "upload_bytes": {"value": ul},
                    }
                    for ip, conns, total, dl, ul in device_buckets
                ]
            }
        }
    }

@pytest.mark.asyncio
async def test_returns_devices_sorted_by_bytes():
    client = AsyncMock()
    client.search = AsyncMock(return_value=_mock_device_response([
        ("192.168.1.10", 100, 5_000_000, 4_500_000, 500_000),
        ("192.168.1.20", 200, 8_000_000, 7_000_000, 1_000_000),
    ]))
    result = await get_category_devices(
        client, "streaming", "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z"
    )
    assert len(result) == 2
    assert result[0]["ip"] == "192.168.1.20"  # higher bytes first
    assert result[0]["total_bytes"] == 8_000_000

@pytest.mark.asyncio
async def test_unknown_category_returns_empty():
    client = AsyncMock()
    client.search = AsyncMock(return_value=_mock_device_response([]))
    result = await get_category_devices(
        client, "nonexistent", "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z"
    )
    assert result == []

@pytest.mark.asyncio
async def test_device_fields_present():
    client = AsyncMock()
    client.search = AsyncMock(return_value=_mock_device_response([
        ("192.168.1.10", 50, 1_000_000, 800_000, 200_000),
    ]))
    result = await get_category_devices(
        client, "streaming", "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z"
    )
    device = result[0]
    assert "ip" in device
    assert "total_bytes" in device
    assert "download_bytes" in device
    assert "upload_bytes" in device
    assert "connections" in device
```

**Step 2: Add `get_category_devices()` to traffic_classifier.py**

Add after `get_category_stats()`:

```python
def _asn_filters_for_category(category: str) -> list[str]:
    """Return list of ASN org substrings that map to the given category."""
    return [substr for substr, cat in ASN_CATEGORY_MAP.items() if cat == category]


async def get_category_devices(
    client, category: str, from_ts: str, to_ts: str, limit: int = 50
) -> list[dict]:
    """Get per-device bandwidth breakdown for a traffic category."""
    asn_substrings = _asn_filters_for_category(category)
    if not asn_substrings:
        return []

    # Build wildcard filters for ASN matching
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
                "terms": {"field": "source.ip", "size": limit},
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
                    "download_bytes": {
                        "sum": {"field": "destination.bytes"}
                    },
                    "upload_bytes": {
                        "sum": {"field": "source.bytes"}
                    },
                },
            }
        },
    }

    try:
        resp = await client.search(index="arkime_sessions3-*", body=query)
    except Exception:
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

    devices.sort(key=lambda d: d["total_bytes"], reverse=True)
    return devices
```

**Step 3: Add API route handler in `daemon/api/traffic.py`**

Add after the existing `handle_traffic_categories` handler (~line 549):

```python
async def handle_category_detail(request: web.Request) -> web.Response:
    """GET /api/traffic/categories/{category} — per-device breakdown."""
    category = request.match_info["category"]

    if category not in traffic_classifier.CATEGORIES:
        return web.json_response({"error": f"Unknown category: {category}"}, status=404)

    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)

    devices = await traffic_classifier.get_category_devices(client, category, from_ts, to_ts)

    # Compute total bytes for percentage calculation
    grand_total = sum(d["total_bytes"] for d in devices)

    for d in devices:
        d["percent"] = round((d["total_bytes"] / grand_total * 100), 1) if grand_total > 0 else 0

    return web.json_response({
        "category": category,
        "label": traffic_classifier.CATEGORIES[category],
        "device_count": len(devices),
        "total_bytes": grand_total,
        "connection_count": sum(d["connections"] for d in devices),
        "devices": devices,
    })
```

Register the route in the `register_routes` function (find `app.router.add_get("/api/traffic/categories"` and add after it):

```python
app.router.add_get("/api/traffic/categories/{category}", handle_category_detail)
```

**Step 4: Run tests**

```bash
cd daemon && python -m pytest tests/test_category_devices.py tests/test_category_stats.py tests/test_asn_classifier.py -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add daemon/services/traffic_classifier.py daemon/api/traffic.py daemon/tests/test_category_devices.py
git commit -m "feat(traffic): add /api/traffic/categories/{category} endpoint

Returns per-device bandwidth breakdown for a traffic category
using ASN-based filtering. Includes download/upload split.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Frontend API Client — Category Detail

**Files:**
- Modify: `web/src/lib/api/traffic.ts` (add types + function)
- Test: `web/src/lib/api/traffic.test.ts` (add test cases)

**Step 1: Add TypeScript types and API function**

Add to `web/src/lib/api/traffic.ts` after the existing `CategoriesResponse` type:

```typescript
export interface CategoryDevice {
	ip: string;
	hostname?: string;
	total_bytes: number;
	download_bytes: number;
	upload_bytes: number;
	connections: number;
	percent: number;
}

export interface CategoryDetailResponse {
	category: string;
	label: string;
	device_count: number;
	total_bytes: number;
	connection_count: number;
	devices: CategoryDevice[];
}
```

Add the function after `getTrafficCategories`:

```typescript
export async function getCategoryDetail(
	category: string,
	opts: TimeRangeParams = {}
): Promise<CategoryDetailResponse> {
	const q = buildQuery(opts);
	const url = `/api/traffic/categories/${encodeURIComponent(category)}${q}`;
	try {
		const res = await fetch(url);
		if (!res.ok) throw new Error(`${res.status}`);
		return await res.json();
	} catch {
		return {
			category,
			label: category,
			device_count: 0,
			total_bytes: 0,
			connection_count: 0,
			devices: [],
		};
	}
}
```

**Step 2: Add test to `web/src/lib/api/traffic.test.ts`**

Add test cases for `getCategoryDetail`:

```typescript
describe('getCategoryDetail', () => {
	it('fetches category detail with time range', async () => {
		const mockData = {
			category: 'streaming',
			label: 'Streaming',
			device_count: 3,
			total_bytes: 5000000,
			connection_count: 1000,
			devices: [{ ip: '192.168.1.10', total_bytes: 3000000, download_bytes: 2500000, upload_bytes: 500000, connections: 600, percent: 60 }],
		};
		globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(mockData) });

		const result = await getCategoryDetail('streaming', { from: '2026-03-01T00:00:00Z' });
		expect(result.category).toBe('streaming');
		expect(result.devices).toHaveLength(1);
		expect(result.devices[0].ip).toBe('192.168.1.10');
	});

	it('returns empty on error', async () => {
		globalThis.fetch = vi.fn().mockResolvedValue({ ok: false, status: 404 });

		const result = await getCategoryDetail('nonexistent');
		expect(result.devices).toEqual([]);
		expect(result.device_count).toBe(0);
	});
});
```

**Step 3: Run tests**

```bash
cd web && npx vitest run src/lib/api/traffic.test.ts
```

Expected: All PASS.

**Step 4: Commit**

```bash
git add web/src/lib/api/traffic.ts web/src/lib/api/traffic.test.ts
git commit -m "feat(web): add getCategoryDetail API client function

Fetches per-device breakdown for a traffic category.
Includes TypeScript types for CategoryDevice and CategoryDetailResponse.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 5: Breadcrumb Component

**Files:**
- Create: `web/src/lib/components/Breadcrumb.svelte`
- Create: `web/src/lib/components/Breadcrumb.test.ts`

**Step 1: Create the component**

Create `web/src/lib/components/Breadcrumb.svelte`:

```svelte
<script lang="ts">
	import { page } from '$app/stores';

	/**
	 * Sitewide breadcrumb navigation.
	 * Generates a trail from the current URL using a static route map.
	 * Hidden on home, login, and setup pages.
	 */

	const ROUTE_MAP: Record<string, { label: string; parent?: string }> = {
		'/': { label: 'Home' },
		'/logs': { label: 'Log Explorer' },
		'/devices': { label: 'Devices' },
		'/alerts': { label: 'Alerts' },
		'/connections': { label: 'Connections' },
		'/live': { label: 'Live Monitor' },
		'/bandwidth': { label: 'Bandwidth' },
		'/dns': { label: 'DNS Analytics' },
		'/iot': { label: 'IoT & LAN' },
		'/changelog': { label: 'Changelog' },
		'/certificates': { label: 'Certificates' },
		'/pcap': { label: 'PCAP Search' },
		'/tools': { label: 'Tools' },
		'/tools/dns-recon': { label: 'DNS Recon', parent: '/tools' },
		'/tools/ping': { label: 'Ping', parent: '/tools' },
		'/tools/traceroute': { label: 'Traceroute', parent: '/tools' },
		'/tools/ssl-cert': { label: 'SSL Cert', parent: '/tools' },
		'/tools/mac-lookup': { label: 'MAC Lookup', parent: '/tools' },
		'/tools/subnet-calc': { label: 'Subnet Calc', parent: '/tools' },
		'/tools/port-reference': { label: 'Port Reference', parent: '/tools' },
		'/tools/base64': { label: 'Base64', parent: '/tools' },
		'/tools/cyberchef': { label: 'CyberChef', parent: '/tools' },
		'/tools/tshark': { label: 'Tshark', parent: '/tools' },
		'/infrastructure': { label: 'Infrastructure' },
		'/settings': { label: 'Settings' },
		'/settings/notifications': { label: 'Notifications', parent: '/settings' },
		'/settings/backup': { label: 'Backup', parent: '/settings' },
		'/settings/suricata-rules': { label: 'Suricata Rules', parent: '/settings' },
		'/traffic': { label: 'Traffic Categories', parent: '/' },
		'/go-live': { label: 'Go Live' },
		'/geoip': { label: 'GeoIP' },
	};

	const CATEGORY_LABELS: Record<string, string> = {
		streaming: 'Streaming',
		gaming: 'Gaming',
		social: 'Social Media',
		communication: 'Communication',
		work: 'Work & Productivity',
		iot: 'IoT & Smart Home',
		cloud: 'Cloud Services',
		file_transfer: 'File Transfer',
		dns: 'DNS',
		email: 'Email',
		web: 'Web Browsing',
		security: 'Security & VPN',
		shopping: 'Shopping',
		news: 'News & Media',
		ads: 'Ads & Tracking',
		updates: 'Updates & Downloads',
		suspicious: 'Suspicious',
		other: 'Other',
	};

	/** Pages where breadcrumbs are hidden */
	const HIDDEN_PATHS = ['/', '/login', '/setup'];

	interface Crumb {
		label: string;
		href?: string;
		mono?: boolean;
	}

	function buildTrail(pathname: string): Crumb[] {
		if (HIDDEN_PATHS.includes(pathname)) return [];

		const crumbs: Crumb[] = [{ label: 'Home', href: '/' }];

		// Exact match in route map
		const exact = ROUTE_MAP[pathname];
		if (exact) {
			// Walk parents
			const chain: { label: string; href: string }[] = [];
			let current: string | undefined = pathname;
			while (current && ROUTE_MAP[current]) {
				const entry = ROUTE_MAP[current];
				chain.unshift({ label: entry.label, href: current });
				current = entry.parent;
			}
			// Skip the Home duplicate (first crumb added above)
			for (const c of chain) {
				if (c.href === '/') continue;
				crumbs.push(c);
			}
			// Last crumb has no link
			if (crumbs.length > 1) {
				delete crumbs[crumbs.length - 1].href;
			}
			return crumbs;
		}

		// Dynamic route matching
		// /devices/{ip}
		const devMatch = pathname.match(/^\/devices\/(.+)$/);
		if (devMatch) {
			crumbs.push({ label: 'Devices', href: '/devices' });
			crumbs.push({ label: decodeURIComponent(devMatch[1]), mono: true });
			return crumbs;
		}

		// /devices/mac/{mac}
		const macMatch = pathname.match(/^\/devices\/mac\/(.+)$/);
		if (macMatch) {
			crumbs.push({ label: 'Devices', href: '/devices' });
			crumbs.push({ label: decodeURIComponent(macMatch[1]), mono: true });
			return crumbs;
		}

		// /traffic/{category}
		const catMatch = pathname.match(/^\/traffic\/(.+)$/);
		if (catMatch) {
			const slug = decodeURIComponent(catMatch[1]);
			crumbs.push({ label: 'Traffic Categories', href: '/traffic' });
			crumbs.push({ label: CATEGORY_LABELS[slug] || slug });
			return crumbs;
		}

		// /geoip/{ip}
		const geoMatch = pathname.match(/^\/geoip\/(.+)$/);
		if (geoMatch) {
			crumbs.push({ label: 'GeoIP', href: '/geoip' });
			crumbs.push({ label: decodeURIComponent(geoMatch[1]), mono: true });
			return crumbs;
		}

		// /lookup/dns/{ip} or /lookup/whois/{ip}
		const lookupMatch = pathname.match(/^\/lookup\/(dns|whois)\/(.+)$/);
		if (lookupMatch) {
			crumbs.push({ label: lookupMatch[1].toUpperCase() + ' Lookup' });
			crumbs.push({ label: decodeURIComponent(lookupMatch[2]), mono: true });
			return crumbs;
		}

		// Fallback: use pathname segments
		const segments = pathname.split('/').filter(Boolean);
		for (let i = 0; i < segments.length; i++) {
			const href = '/' + segments.slice(0, i + 1).join('/');
			const isLast = i === segments.length - 1;
			crumbs.push({
				label: decodeURIComponent(segments[i]).replace(/-/g, ' '),
				href: isLast ? undefined : href,
			});
		}

		return crumbs;
	}

	let trail = $derived(buildTrail($page.url.pathname));
</script>

{#if trail.length > 1}
	<nav class="breadcrumb-bar" aria-label="Breadcrumb">
		<ol class="breadcrumb-trail">
			{#each trail as crumb, i}
				{#if i > 0}
					<li class="separator" aria-hidden="true">/</li>
				{/if}
				<li class="crumb" class:current={!crumb.href}>
					{#if crumb.href}
						<a href={crumb.href}>{crumb.label}</a>
					{:else}
						<span class:mono={crumb.mono}>{crumb.label}</span>
					{/if}
				</li>
			{/each}
		</ol>
	</nav>
{/if}

<style>
	.breadcrumb-bar {
		padding: var(--space-xs) var(--space-lg);
	}

	.breadcrumb-trail {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		list-style: none;
		margin: 0;
		padding: 0;
		font-size: var(--text-sm);
		font-family: var(--font-sans);
	}

	.separator {
		color: var(--text-dim);
		user-select: none;
	}

	.crumb a {
		color: var(--text-muted);
		text-decoration: none;
		transition: color var(--transition-fast);
	}

	.crumb a:hover {
		color: var(--text-link);
	}

	.crumb.current span {
		color: var(--text-secondary);
	}

	.mono {
		font-family: var(--font-mono);
	}
</style>
```

**Step 2: Write the test**

Create `web/src/lib/components/Breadcrumb.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';

/**
 * Tests for Breadcrumb trail building logic.
 * We extract and test the pure buildTrail function since the component
 * depends on SvelteKit's $page store.
 */

const ROUTE_MAP: Record<string, { label: string; parent?: string }> = {
	'/': { label: 'Home' },
	'/logs': { label: 'Log Explorer' },
	'/devices': { label: 'Devices' },
	'/alerts': { label: 'Alerts' },
	'/tools': { label: 'Tools' },
	'/tools/dns-recon': { label: 'DNS Recon', parent: '/tools' },
	'/tools/ping': { label: 'Ping', parent: '/tools' },
	'/settings': { label: 'Settings' },
	'/settings/notifications': { label: 'Notifications', parent: '/settings' },
	'/traffic': { label: 'Traffic Categories', parent: '/' },
};

const CATEGORY_LABELS: Record<string, string> = {
	streaming: 'Streaming',
	gaming: 'Gaming',
};

const HIDDEN_PATHS = ['/', '/login', '/setup'];

interface Crumb {
	label: string;
	href?: string;
	mono?: boolean;
}

function buildTrail(pathname: string): Crumb[] {
	if (HIDDEN_PATHS.includes(pathname)) return [];

	const crumbs: Crumb[] = [{ label: 'Home', href: '/' }];

	const exact = ROUTE_MAP[pathname];
	if (exact) {
		const chain: { label: string; href: string }[] = [];
		let current: string | undefined = pathname;
		while (current && ROUTE_MAP[current]) {
			const entry = ROUTE_MAP[current];
			chain.unshift({ label: entry.label, href: current });
			current = entry.parent;
		}
		for (const c of chain) {
			if (c.href === '/') continue;
			crumbs.push(c);
		}
		if (crumbs.length > 1) {
			delete crumbs[crumbs.length - 1].href;
		}
		return crumbs;
	}

	const devMatch = pathname.match(/^\/devices\/(.+)$/);
	if (devMatch) {
		crumbs.push({ label: 'Devices', href: '/devices' });
		crumbs.push({ label: decodeURIComponent(devMatch[1]), mono: true });
		return crumbs;
	}

	const catMatch = pathname.match(/^\/traffic\/(.+)$/);
	if (catMatch) {
		const slug = decodeURIComponent(catMatch[1]);
		crumbs.push({ label: 'Traffic Categories', href: '/traffic' });
		crumbs.push({ label: CATEGORY_LABELS[slug] || slug });
		return crumbs;
	}

	const segments = pathname.split('/').filter(Boolean);
	for (let i = 0; i < segments.length; i++) {
		const href = '/' + segments.slice(0, i + 1).join('/');
		const isLast = i === segments.length - 1;
		crumbs.push({
			label: decodeURIComponent(segments[i]).replace(/-/g, ' '),
			href: isLast ? undefined : href,
		});
	}

	return crumbs;
}

describe('Breadcrumb — buildTrail', () => {
	it('returns empty for home page', () => {
		expect(buildTrail('/')).toEqual([]);
	});

	it('returns empty for login page', () => {
		expect(buildTrail('/login')).toEqual([]);
	});

	it('returns empty for setup page', () => {
		expect(buildTrail('/setup')).toEqual([]);
	});

	it('builds simple trail for top-level page', () => {
		const trail = buildTrail('/logs');
		expect(trail).toEqual([
			{ label: 'Home', href: '/' },
			{ label: 'Log Explorer' },
		]);
	});

	it('builds nested trail for tool subpage', () => {
		const trail = buildTrail('/tools/dns-recon');
		expect(trail).toEqual([
			{ label: 'Home', href: '/' },
			{ label: 'Tools', href: '/tools' },
			{ label: 'DNS Recon' },
		]);
	});

	it('builds nested trail for settings subpage', () => {
		const trail = buildTrail('/settings/notifications');
		expect(trail).toEqual([
			{ label: 'Home', href: '/' },
			{ label: 'Settings', href: '/settings' },
			{ label: 'Notifications' },
		]);
	});

	it('builds trail for device detail with IP', () => {
		const trail = buildTrail('/devices/192.168.1.5');
		expect(trail).toEqual([
			{ label: 'Home', href: '/' },
			{ label: 'Devices', href: '/devices' },
			{ label: '192.168.1.5', mono: true },
		]);
	});

	it('builds trail for traffic category', () => {
		const trail = buildTrail('/traffic/streaming');
		expect(trail).toEqual([
			{ label: 'Home', href: '/' },
			{ label: 'Traffic Categories', href: '/traffic' },
			{ label: 'Streaming' },
		]);
	});

	it('uses slug as label for unknown category', () => {
		const trail = buildTrail('/traffic/unknown-cat');
		expect(trail).toEqual([
			{ label: 'Home', href: '/' },
			{ label: 'Traffic Categories', href: '/traffic' },
			{ label: 'unknown-cat' },
		]);
	});

	it('last crumb never has href', () => {
		const trail = buildTrail('/tools/ping');
		const last = trail[trail.length - 1];
		expect(last.href).toBeUndefined();
	});

	it('first crumb is always Home with href /', () => {
		const trail = buildTrail('/alerts');
		expect(trail[0]).toEqual({ label: 'Home', href: '/' });
	});
});
```

**Step 3: Run tests**

```bash
cd web && npx vitest run src/lib/components/Breadcrumb.test.ts
```

Expected: All 11 tests PASS.

**Step 4: Commit**

```bash
git add web/src/lib/components/Breadcrumb.svelte web/src/lib/components/Breadcrumb.test.ts
git commit -m "feat(web): add sitewide Breadcrumb component

Route-aware breadcrumb trail with static route map and dynamic
segment matching for /devices/{ip}, /traffic/{category}, etc.
Hidden on home, login, and setup pages.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 6: Integrate Breadcrumb Into Layout

**Files:**
- Modify: `web/src/routes/+layout.svelte`

**Step 1: Add import**

Add after the existing imports (line 6):

```typescript
import Breadcrumb from '$components/Breadcrumb.svelte';
```

**Step 2: Insert component into layout**

Find the content section (around line 193):

```html
<main class="content">
	{@render children()}
</main>
```

Change to:

```html
<Breadcrumb />
<main class="content">
	{@render children()}
</main>
```

**Step 3: Verify with dev server**

```bash
cd web && npm run dev
```

Navigate to `/tools/dns-recon` — should see "Home / Tools / DNS Recon".
Navigate to `/devices/192.168.1.1` — should see "Home / Devices / 192.168.1.1".
Navigate to `/` — should see no breadcrumb.

**Step 4: Commit**

```bash
git add web/src/routes/+layout.svelte
git commit -m "feat(web): integrate Breadcrumb into main layout

Shows navigation trail on all pages except home, login, setup.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 7: Traffic Category Detail Page

**Files:**
- Create: `web/src/routes/traffic/[category]/+page.svelte`

**Step 1: Create the page**

This is a large component. Create `web/src/routes/traffic/[category]/+page.svelte` matching the approved mockup design. Key sections:

1. Category header with icon + label + service list
2. 4 stat cards: Total Bandwidth, Active Devices, Connections
3. Per-device breakdown table (sortable)
4. Top Services sidebar using HorizontalBarList

The page calls `getCategoryDetail(category, timeParams)` on mount and when time range changes.

```svelte
<script lang="ts">
	import { page } from '$app/stores';
	import { getCategoryDetail, getTrafficCategories } from '$api/traffic';
	import type { CategoryDetailResponse, CategoryDevice } from '$api/traffic';
	import HorizontalBarList from '$components/HorizontalBarList.svelte';
	import IPAddress from '$components/IPAddress.svelte';
	import { onMount } from 'svelte';

	const CATEGORY_META: Record<string, { icon: string; color: string }> = {
		streaming: { icon: '▶', color: 'var(--red)' },
		gaming: { icon: '🎮', color: 'var(--purple)' },
		social: { icon: '👥', color: 'var(--blue)' },
		communication: { icon: '💬', color: 'var(--amber)' },
		work: { icon: '💼', color: 'var(--green)' },
		iot: { icon: '📡', color: 'var(--orange)' },
		cloud: { icon: '☁', color: 'var(--cyan)' },
		file_transfer: { icon: '📁', color: 'var(--teal)' },
		dns: { icon: '🌐', color: 'var(--text-muted)' },
		email: { icon: '✉', color: 'var(--pink)' },
		web: { icon: '🔗', color: 'var(--accent)' },
		security: { icon: '🔒', color: 'var(--green)' },
		shopping: { icon: '🛒', color: 'var(--orange)' },
		news: { icon: '📰', color: 'var(--blue)' },
		ads: { icon: '📊', color: 'var(--text-muted)' },
		updates: { icon: '⬇', color: 'var(--teal)' },
		suspicious: { icon: '⚠', color: 'var(--red)' },
		other: { icon: '…', color: 'var(--text-muted)' },
	};

	const TIME_RANGES = [
		{ label: '1h', value: '1h' },
		{ label: '6h', value: '6h' },
		{ label: '24h', value: '24h' },
		{ label: '7d', value: '7d' },
		{ label: '30d', value: '30d' },
	];

	let category = $derived($page.params.category);
	let meta = $derived(CATEGORY_META[category] || { icon: '…', color: 'var(--text-muted)' });

	let selectedRange = $state('24h');
	let data = $state<CategoryDetailResponse | null>(null);
	let loading = $state(true);

	let sortField = $state<keyof CategoryDevice>('total_bytes');
	let sortDir = $state<'asc' | 'desc'>('desc');

	function toggleSort(field: keyof CategoryDevice) {
		if (sortField === field) {
			sortDir = sortDir === 'desc' ? 'asc' : 'desc';
		} else {
			sortField = field;
			sortDir = 'desc';
		}
	}

	let sortedDevices = $derived(() => {
		if (!data?.devices) return [];
		return [...data.devices].sort((a, b) => {
			const av = a[sortField] ?? 0;
			const bv = b[sortField] ?? 0;
			const cmp = av < bv ? -1 : av > bv ? 1 : 0;
			return sortDir === 'asc' ? cmp : -cmp;
		});
	});

	let maxDeviceBytes = $derived(
		data?.devices?.length ? Math.max(...data.devices.map(d => d.total_bytes)) : 0
	);

	// Top services from the category stats
	let services = $state<Array<{ name: string; bytes: number }>>([]);

	function getTimeParams() {
		const now = new Date();
		const hours: Record<string, number> = { '1h': 1, '6h': 6, '24h': 24, '7d': 168, '30d': 720 };
		const from = new Date(now.getTime() - (hours[selectedRange] || 24) * 3600000);
		return { from: from.toISOString(), to: now.toISOString() };
	}

	async function fetchData() {
		loading = true;
		const params = getTimeParams();
		const [detailRes, catRes] = await Promise.all([
			getCategoryDetail(category, params),
			getTrafficCategories(params),
		]);
		data = detailRes;
		// Extract top services from the categories response
		const catInfo = catRes.categories?.find(c => c.name === category);
		services = (catInfo as any)?.top_services || [];
		loading = false;
	}

	function formatBytes(bytes: number): string {
		if (bytes === 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.floor(Math.log(bytes) / Math.log(1024));
		return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
	}

	function formatBytesShort(bytes: number): string {
		if (bytes === 0) return '0';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.floor(Math.log(bytes) / Math.log(1024));
		return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
	}

	onMount(() => {
		fetchData();
	});

	$effect(() => {
		// Re-fetch when range changes
		selectedRange;
		fetchData();
	});
</script>

<svelte:head>
	<title>{data?.label || category} — Traffic Category | NetTap</title>
</svelte:head>

<div class="page-container">
	<!-- Header -->
	<header class="page-header">
		<div class="header-left">
			<a href="/" class="back-link">← Back</a>
			<div class="category-title">
				<span class="category-icon" style="background: {meta.color}20; color: {meta.color}">
					{meta.icon}
				</span>
				<div>
					<h1>{data?.label || category}</h1>
					{#if services.length > 0}
						<p class="subtitle">
							{services.slice(0, 4).map(s => s.name).join(', ')}{services.length > 4 ? `, and ${services.length - 4} more` : ''}
						</p>
					{/if}
				</div>
			</div>
		</div>
		<div class="header-right">
			<div class="pills">
				{#each TIME_RANGES as tr}
					<button class="pill" class:active={selectedRange === tr.value}
							onclick={() => { selectedRange = tr.value; }}>
						{tr.label}
					</button>
				{/each}
			</div>
		</div>
	</header>

	<!-- Stat Cards -->
	<div class="stats-grid">
		<div class="stat-card">
			<span class="stat-label">TOTAL BANDWIDTH</span>
			<span class="stat-value" style="color: {meta.color}">{formatBytes(data?.total_bytes || 0)}</span>
		</div>
		<div class="stat-card">
			<span class="stat-label">ACTIVE DEVICES</span>
			<span class="stat-value text-primary">{data?.device_count || 0}</span>
		</div>
		<div class="stat-card">
			<span class="stat-label">CONNECTIONS</span>
			<span class="stat-value text-primary">{(data?.connection_count || 0).toLocaleString()}</span>
		</div>
	</div>

	<!-- Main content: table + sidebar -->
	<div class="content-grid">
		<!-- Device breakdown table -->
		<section class="card">
			<div class="card-header">
				<h2>Per-Device Breakdown</h2>
			</div>

			{#if loading}
				<div class="loading-state">
					<div class="loading-spinner"></div>
					<p class="text-muted">Loading device data...</p>
				</div>
			{:else if !data?.devices?.length}
				<div class="empty-state">
					<p class="empty-text">No device data found</p>
					<p class="empty-hint">Try expanding the time range</p>
				</div>
			{:else}
				<div class="table-wrap">
					<table class="data-table">
						<thead>
							<tr>
								<th class="sortable" class:sorted={sortField === 'ip'}
									onclick={() => toggleSort('ip')}>
									Device
									{#if sortField === 'ip'}
										<span class="sort-arrow">{sortDir === 'desc' ? '↓' : '↑'}</span>
									{/if}
								</th>
								<th class="sortable" class:sorted={sortField === 'total_bytes'}
									onclick={() => toggleSort('total_bytes')}>
									Total Data
									{#if sortField === 'total_bytes'}
										<span class="sort-arrow">{sortDir === 'desc' ? '↓' : '↑'}</span>
									{/if}
								</th>
								<th class="sortable" class:sorted={sortField === 'download_bytes'}
									onclick={() => toggleSort('download_bytes')}>
									Download
									{#if sortField === 'download_bytes'}
										<span class="sort-arrow">{sortDir === 'desc' ? '↓' : '↑'}</span>
									{/if}
								</th>
								<th class="sortable" class:sorted={sortField === 'upload_bytes'}
									onclick={() => toggleSort('upload_bytes')}>
									Upload
									{#if sortField === 'upload_bytes'}
										<span class="sort-arrow">{sortDir === 'desc' ? '↓' : '↑'}</span>
									{/if}
								</th>
								<th class="sortable" class:sorted={sortField === 'connections'}
									onclick={() => toggleSort('connections')}>
									Connections
									{#if sortField === 'connections'}
										<span class="sort-arrow">{sortDir === 'desc' ? '↓' : '↑'}</span>
									{/if}
								</th>
							</tr>
						</thead>
						<tbody>
							{#each sortedDevices() as device}
								<tr>
									<td class="device-cell">
										<a href="/devices/{device.ip}" class="device-link">
											<IPAddress ip={device.ip} />
										</a>
									</td>
									<td>
										<div class="bytes-cell">
											<div class="bar-track">
												<div class="bar-fill"
													style="width: {maxDeviceBytes > 0 ? (device.total_bytes / maxDeviceBytes * 100) : 0}%; background: {meta.color}"></div>
											</div>
											<span class="bytes-value">{formatBytesShort(device.total_bytes)}</span>
											<span class="bytes-pct">{device.percent}%</span>
										</div>
									</td>
									<td class="mono">{formatBytesShort(device.download_bytes)}</td>
									<td class="mono">{formatBytesShort(device.upload_bytes)}</td>
									<td class="mono">{device.connections.toLocaleString()}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</section>

		<!-- Top Services sidebar -->
		{#if services.length > 0}
			<section class="card services-card">
				<div class="card-header">
					<h2>Top Services</h2>
					<span class="card-badge">BY BANDWIDTH</span>
				</div>
				<HorizontalBarList
					items={services.map(s => ({
						key: s.name,
						label: s.name,
						value: s.bytes,
						formattedValue: formatBytesShort(s.bytes),
						color: meta.color,
					}))}
					labelWidth={120}
					showDot={true}
				/>
			</section>
		{/if}
	</div>
</div>

<style>
	.page-container {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	.back-link {
		color: var(--text-muted);
		font-size: var(--text-sm);
		text-decoration: none;
		transition: color var(--transition-fast);
	}

	.back-link:hover {
		color: var(--text-link);
	}

	.category-title {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		margin-top: var(--space-sm);
	}

	.category-icon {
		width: 48px;
		height: 48px;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: var(--radius-md);
		font-size: 1.5rem;
		flex-shrink: 0;
	}

	h1 {
		font-size: var(--text-2xl);
		font-weight: 700;
		color: var(--text-primary);
		margin: 0;
	}

	.subtitle {
		color: var(--text-secondary);
		font-size: var(--text-sm);
		margin-top: 2px;
	}

	.stats-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: var(--space-md);
	}

	.content-grid {
		display: grid;
		grid-template-columns: 1fr 300px;
		gap: var(--space-md);
	}

	.services-card {
		height: fit-content;
	}

	.bytes-cell {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.bar-track {
		flex: 1;
		height: 8px;
		background: var(--bg-tertiary);
		border-radius: var(--radius-full);
		overflow: hidden;
		min-width: 60px;
	}

	.bar-fill {
		height: 100%;
		border-radius: var(--radius-full);
		transition: width var(--transition-normal);
	}

	.bytes-value {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		color: var(--text-primary);
		min-width: 60px;
		text-align: right;
	}

	.bytes-pct {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--text-muted);
		min-width: 40px;
	}

	.device-link {
		color: var(--text-link);
		text-decoration: none;
		transition: color var(--transition-fast);
	}

	.device-link:hover {
		color: var(--accent);
	}

	.mono {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		color: var(--text-primary);
	}

	@media (max-width: 1024px) {
		.stats-grid { grid-template-columns: 1fr; }
		.content-grid { grid-template-columns: 1fr; }
	}
</style>
```

**Step 2: Commit**

```bash
git add web/src/routes/traffic/
git commit -m "feat(web): add /traffic/[category] detail page

Per-device bandwidth breakdown for traffic categories.
Sortable table with download/upload split, Top Services sidebar.
Matches approved mockup design.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 8: Make Homepage Category Bars Clickable

**Files:**
- Modify: `web/src/routes/+page.svelte` (lines ~717-745)

**Step 1: Add `href` to HorizontalBarList items**

Find the two `HorizontalBarList` components in the categories section. Add `href` to each item mapping:

Change (both left and right column):
```typescript
items={categoriesLeft.map(cat => ({
	key: cat.name,
	label: cat.label,
	value: cat.total_bytes,
	formattedValue: formatBytesShort(cat.total_bytes),
	color: categoryColor(cat.name),
}))}
```

To:
```typescript
items={categoriesLeft.map(cat => ({
	key: cat.name,
	label: cat.label,
	value: cat.total_bytes,
	formattedValue: formatBytesShort(cat.total_bytes),
	color: categoryColor(cat.name),
	href: '/traffic/' + cat.name,
}))}
```

Do the same for `categoriesRight`.

**Step 2: Commit**

```bash
git add web/src/routes/+page.svelte
git commit -m "feat(web): make homepage category bars clickable

Clicking a traffic category navigates to /traffic/{category}
for per-device breakdown.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 9: Run Full Test Suite + Svelte Check

**Step 1: Run daemon tests**

```bash
cd daemon && python -m pytest tests/test_asn_classifier.py tests/test_category_stats.py tests/test_category_devices.py -v
```

Expected: All PASS.

**Step 2: Run web tests**

```bash
cd web && npx vitest run
```

Expected: All PASS.

**Step 3: Run Svelte check**

```bash
cd web && npx svelte-check
```

Expected: 0 errors.

**Step 4: Verify with dev server**

```bash
cd web && npm run dev
```

1. Navigate to `/` — category bars show, clicking one navigates to `/traffic/{cat}`
2. Navigate to `/traffic/streaming` — shows per-device breakdown with services sidebar
3. Breadcrumbs visible on `/tools/dns-recon` → "Home / Tools / DNS Recon"
4. Breadcrumbs visible on `/devices/192.168.1.5` → "Home / Devices / 192.168.1.5"
5. No breadcrumb on `/` (home page)

---

## Task 10: Create Linear Issue

Create a Linear issue documenting all changes:
- Title: `feat: ASN-based traffic categories with drill-down + sitewide breadcrumbs`
- Team: Bourbon Buddy
- Labels: Feature
- Description: Problem, approach, files changed, verification
- State: Done
