# NetTap Web UI v2 — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete redesign of the NetTap web UI as a guided power-user SIEM tool with Datadog/Grafana aesthetic, including new daemon API endpoints for log exploration, OpenSearch cluster visibility, and Logstash monitoring.

**Architecture:** SvelteKit frontend (keep infra: Docker, nginx, auth, adapter-node) with all pages rebuilt from scratch. Python aiohttp daemon gets 3 new API modules (logs, opensearch cluster, logstash). Frontend uses `$lib/server/daemon.ts` proxy to talk to daemon. All pages dark-themed with colorful data visualizations.

**Tech Stack:** SvelteKit 2 + Svelte 5, TypeScript, aiohttp (daemon), OpenSearch Python client, Vitest + Testing Library, pytest

**Design Doc:** `docs/plans/2026-03-05-webui-v2-redesign.md`

**Mockups:** Each page gets an HTML mockup in `mockups/<page-name>/index.html` for user approval before implementation. Use `frontend-design` skill for each mockup.

---

## Phase 0: Mockups (Approval Gate)

Every page must be mocked up and approved before implementation begins. Mockups are standalone HTML files with inline CSS — no build step needed, just open in browser.

### Task 0.1: Dashboard Mockup

**Files:**
- Create: `mockups/dashboard-v2/index.html`

**What to mock:**
- Stat cards row: bandwidth, connections, alerts, devices, system health
- Area chart: bandwidth over time (24h, 1h buckets) with gradient fill
- Geo map placeholder: world map with connection dots
- Protocol donut chart with legend
- Top talkers horizontal bar chart
- Alert trend sparkline (stacked by severity)
- Dark theme, Datadog/Grafana colors: dark bg (#0d1117), vibrant chart colors
- Auto-refresh indicator, time range selector

**Use:** `frontend-design` skill

### Task 0.2: Log Explorer Mockup

**Files:**
- Create: `mockups/log-explorer/index.html`

**What to mock:**
- Log type tabs/dropdown: Zeek conn, dns, http, tls, files, dhcp, smtp, Suricata, All
- Search bar with field-aware placeholder text
- Time range selector (presets + custom)
- Column picker sidebar (checkboxes, drag to reorder)
- Results table: sortable columns, monospace data, alternating row shading
- Expandable row: click to show raw JSON + field tooltips
- Field statistics panel: top 5 values for selected field
- Pagination controls (cursor-based)
- Export button (CSV/JSON)
- Tooltips: hover any Zeek field name → plain-English description

### Task 0.3: Devices Mockup

**Files:**
- Create: `mockups/devices-v2/index.html`

**What to mock:**
- Device table: IP, hostname, MAC, manufacturer, OS, first/last seen, bytes, connections, risk score
- Risk score colored badge (0-100, green/yellow/red)
- "New device" badge for first seen < 24h
- Search/filter bar
- Click row → device detail panel (bandwidth timeline, protocol pie, recent alerts, log link)
- Device count header stat

### Task 0.4: Alerts Mockup

**Files:**
- Create: `mockups/alerts-v2/index.html`

**What to mock:**
- Alert trend chart (stacked area by severity over time)
- Top triggered rules summary (bar chart)
- Alert table: timestamp, severity badge, signature + tooltip, source, dest, protocol, category
- Severity filter pills (High/Medium/Low/Info)
- Expandable row: full alert detail, related Zeek logs link, PCAP link
- Plain-English explanation tooltip on every signature

### Task 0.5: Connections Mockup

**Files:**
- Create: `mockups/connections-v2/index.html`

**What to mock:**
- Connection table: timestamp, source:port, dest:port, protocol, service, duration, bytes in/out, state
- State badges (established=green, closed=gray, rejected=red, timeout=amber)
- Filter bar: protocol, service, IP, state
- Click row → TShark PCAP analysis panel (packet list, protocol tree)
- Connection count header stat

### Task 0.6: Infrastructure Mockup

**Files:**
- Create: `mockups/infrastructure/index.html`

**What to mock:**
- Three tabs: OpenSearch, Logstash, System

**OpenSearch tab:**
- Cluster health card (green/yellow/red ring, node count, data size, shard counts)
- Index table: name, health dot, doc count, primary size, total size, creation date
- Template list (collapsible)

**Logstash tab:**
- Pipeline status card (running/stopped badge)
- Throughput chart (events in/out per second)
- Error count + recent errors list
- Queue depth gauge
- JVM heap usage bar

**System tab:**
- Container status table: name, image tag, state, uptime, health badge
- Bridge health: br0 status, WAN/LAN NIC carrier, promisc mode
- Storage: disk usage bar, SMART health badge, retention policy summary
- Software versions list

### Task 0.7: Settings Mockup

**Files:**
- Create: `mockups/settings-v2/index.html`

**What to mock:**
- Sections: Notifications, Retention, Display, About
- Notification preferences (alert severity thresholds, email/webhook config)
- Retention policy editor (hot/warm/cold tier days, disk threshold)
- Display: auto-refresh interval, timezone, default time range
- About: version, uptime, license, links

### Task 0.8: Layout Shell Mockup

**Files:**
- Create: `mockups/layout-shell/index.html`

**What to mock:**
- Left sidebar: collapsible, nav items with icons (Home, Log Explorer, Devices, Alerts, Connections, Infrastructure, Settings)
- Active state highlighting
- Top bar: NetTap logo, page title, system status dot, notification bell, user menu
- Collapsed sidebar state (icon-only, wider content area)
- Mobile responsive: hamburger menu, slide-out sidebar

---

## Phase 1: New Daemon API Endpoints

Backend first — every frontend page needs working APIs.

### Task 1.1: Log Search API (`daemon/api/logs.py`)

**Files:**
- Create: `daemon/api/logs.py`
- Create: `daemon/tests/test_logs_api.py`
- Modify: `daemon/api/server.py` (register routes)

**Step 1: Write the test file**

```python
# daemon/tests/test_logs_api.py
"""Tests for daemon/api/logs.py — generic Zeek/Suricata log search."""

import json
import unittest
from unittest.mock import MagicMock, patch
from aiohttp.test_utils import AioHTTPTestCase
from aiohttp import web
from api.logs import register_log_routes

class TestLogSearchAPI(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        storage = MagicMock()
        storage._client = MagicMock()
        register_log_routes(app, storage)
        return app

    async def test_search_default_params(self):
        """GET /api/logs/search returns results with default params."""
        with patch.object(
            self.app["storage"]._client, "search",
            return_value={"hits": {"hits": [], "total": {"value": 0}}}
        ):
            resp = await self.client.request("GET", "/api/logs/search")
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertIn("hits", data)
            self.assertIn("total", data)

    async def test_search_by_log_type(self):
        """GET /api/logs/search?log_type=zeek.dns filters correctly."""
        with patch.object(
            self.app["storage"]._client, "search",
            return_value={"hits": {"hits": [], "total": {"value": 0}}}
        ) as mock_search:
            resp = await self.client.request("GET", "/api/logs/search?log_type=zeek.dns")
            self.assertEqual(resp.status, 200)
            call_body = mock_search.call_args[1]["body"]
            # Should have term filter for event.dataset=dns
            filters = call_body["query"]["bool"]["filter"]
            datasets = [f["term"]["event.dataset"] for f in filters if "event.dataset" in f.get("term", {})]
            self.assertIn("dns", datasets)

    async def test_search_with_query_string(self):
        """GET /api/logs/search?query=google.com uses query_string."""
        with patch.object(
            self.app["storage"]._client, "search",
            return_value={"hits": {"hits": [], "total": {"value": 0}}}
        ) as mock_search:
            resp = await self.client.request("GET", "/api/logs/search?query=google.com")
            self.assertEqual(resp.status, 200)
            call_body = mock_search.call_args[1]["body"]
            self.assertIn("query_string", json.dumps(call_body))

    async def test_search_pagination(self):
        """GET /api/logs/search?size=10 respects size param."""
        with patch.object(
            self.app["storage"]._client, "search",
            return_value={"hits": {"hits": [], "total": {"value": 0}}}
        ) as mock_search:
            resp = await self.client.request("GET", "/api/logs/search?size=10")
            self.assertEqual(resp.status, 200)
            call_body = mock_search.call_args[1]["body"]
            self.assertEqual(call_body["size"], 10)

    async def test_fields_endpoint(self):
        """GET /api/logs/fields/zeek.conn returns field list."""
        resp = await self.client.request("GET", "/api/logs/fields/zeek.conn")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("fields", data)
        # Should have standard Zeek conn fields
        field_names = [f["name"] for f in data["fields"]]
        self.assertIn("source.ip", field_names)
        self.assertIn("destination.ip", field_names)
```

**Step 2: Run test to verify it fails**

Run: `cd daemon && python -m pytest tests/test_logs_api.py -v`
Expected: FAIL (ImportError — api.logs doesn't exist yet)

**Step 3: Implement `daemon/api/logs.py`**

```python
"""
NetTap Log Search API Routes

Generic log browser for Zeek and Suricata logs stored in OpenSearch.
Supports filtering by log type, full-text search, time range,
field projection, sorting, and cursor-based pagination.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from aiohttp import web
from opensearchpy import OpenSearchException

from storage.manager import StorageManager

logger = logging.getLogger("nettap.api.logs")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# Log type → OpenSearch filter mapping
LOG_TYPE_FILTERS = {
    "zeek.conn": [{"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "conn"}}],
    "zeek.dns": [{"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "dns"}}],
    "zeek.http": [{"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "http"}}],
    "zeek.tls": [{"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "ssl"}}],
    "zeek.files": [{"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "files"}}],
    "zeek.dhcp": [{"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "dhcp"}}],
    "zeek.smtp": [{"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "smtp"}}],
    "suricata": [{"term": {"event.provider": "suricata"}}],
}

# Field definitions per log type (name, type, description, example)
FIELD_DEFINITIONS = {
    "zeek.conn": [
        {"name": "@timestamp", "type": "date", "description": "When the connection was observed", "example": "2026-03-05T12:34:56Z"},
        {"name": "source.ip", "type": "ip", "description": "IP address that initiated the connection", "example": "192.168.1.100"},
        {"name": "source.port", "type": "integer", "description": "Port used by the source", "example": "52341"},
        {"name": "destination.ip", "type": "ip", "description": "IP address that received the connection", "example": "8.8.8.8"},
        {"name": "destination.port", "type": "integer", "description": "Port on the destination (e.g. 443 = HTTPS)", "example": "443"},
        {"name": "network.transport", "type": "keyword", "description": "Transport protocol (tcp, udp, icmp)", "example": "tcp"},
        {"name": "network.protocol", "type": "keyword", "description": "Application protocol detected by Zeek", "example": "ssl"},
        {"name": "event.duration", "type": "float", "description": "How long the connection lasted (seconds)", "example": "1.234"},
        {"name": "source.bytes", "type": "long", "description": "Bytes sent by the source", "example": "1024"},
        {"name": "destination.bytes", "type": "long", "description": "Bytes sent by the destination", "example": "2048"},
        {"name": "zeek.conn.state", "type": "keyword", "description": "Connection state (S1=established, SF=finished, REJ=rejected)", "example": "SF"},
        {"name": "zeek.conn.history", "type": "keyword", "description": "Connection history string (ShADFf = SYN/ACK/DATA/FIN)", "example": "ShADFf"},
    ],
    "zeek.dns": [
        {"name": "@timestamp", "type": "date", "description": "When the DNS query was observed", "example": "2026-03-05T12:34:56Z"},
        {"name": "source.ip", "type": "ip", "description": "Device that made the DNS query", "example": "192.168.1.100"},
        {"name": "destination.ip", "type": "ip", "description": "DNS server that answered", "example": "8.8.8.8"},
        {"name": "zeek.dns.query", "type": "keyword", "description": "Domain name that was looked up", "example": "www.google.com"},
        {"name": "zeek.dns.qtype_name", "type": "keyword", "description": "DNS record type (A=IPv4, AAAA=IPv6, CNAME=alias)", "example": "A"},
        {"name": "zeek.dns.rcode_name", "type": "keyword", "description": "Response code (NOERROR=success, NXDOMAIN=not found)", "example": "NOERROR"},
        {"name": "zeek.dns.answers", "type": "keyword", "description": "IP addresses returned in the DNS response", "example": "142.250.80.46"},
        {"name": "zeek.dns.rejected", "type": "boolean", "description": "Whether the query was rejected", "example": "false"},
    ],
    "zeek.http": [
        {"name": "@timestamp", "type": "date", "description": "When the HTTP request was observed", "example": "2026-03-05T12:34:56Z"},
        {"name": "source.ip", "type": "ip", "description": "Device that made the HTTP request", "example": "192.168.1.100"},
        {"name": "destination.ip", "type": "ip", "description": "Web server that responded", "example": "93.184.216.34"},
        {"name": "zeek.http.method", "type": "keyword", "description": "HTTP method (GET, POST, PUT, etc.)", "example": "GET"},
        {"name": "zeek.http.host", "type": "keyword", "description": "Website hostname from the Host header", "example": "www.example.com"},
        {"name": "zeek.http.uri", "type": "keyword", "description": "URL path requested", "example": "/api/data"},
        {"name": "zeek.http.status_code", "type": "integer", "description": "HTTP response code (200=OK, 404=not found, 500=error)", "example": "200"},
        {"name": "zeek.http.user_agent", "type": "keyword", "description": "Browser or app that made the request", "example": "Mozilla/5.0..."},
        {"name": "zeek.http.resp_mime_types", "type": "keyword", "description": "Content type of the response", "example": "text/html"},
    ],
    "zeek.tls": [
        {"name": "@timestamp", "type": "date", "description": "When the TLS handshake was observed", "example": "2026-03-05T12:34:56Z"},
        {"name": "source.ip", "type": "ip", "description": "Device that initiated the TLS connection", "example": "192.168.1.100"},
        {"name": "destination.ip", "type": "ip", "description": "Server that accepted the TLS connection", "example": "93.184.216.34"},
        {"name": "zeek.tls.version", "type": "keyword", "description": "TLS version used (TLSv1.3 is current best)", "example": "TLSv13"},
        {"name": "zeek.tls.server_name", "type": "keyword", "description": "Server Name Indication — the domain being connected to", "example": "www.google.com"},
        {"name": "zeek.tls.cipher", "type": "keyword", "description": "Encryption cipher suite negotiated", "example": "TLS_AES_256_GCM_SHA384"},
        {"name": "zeek.tls.established", "type": "boolean", "description": "Whether the TLS handshake completed successfully", "example": "true"},
        {"name": "zeek.tls.subject", "type": "keyword", "description": "Certificate subject (who the cert was issued to)", "example": "CN=www.google.com"},
        {"name": "zeek.tls.issuer", "type": "keyword", "description": "Certificate Authority that issued the cert", "example": "CN=GTS CA 1C3,O=Google Trust Services LLC"},
    ],
    "zeek.files": [
        {"name": "@timestamp", "type": "date", "description": "When the file transfer was observed", "example": "2026-03-05T12:34:56Z"},
        {"name": "source.ip", "type": "ip", "description": "Device that sent the file", "example": "93.184.216.34"},
        {"name": "destination.ip", "type": "ip", "description": "Device that received the file", "example": "192.168.1.100"},
        {"name": "zeek.files.filename", "type": "keyword", "description": "Name of the file transferred", "example": "document.pdf"},
        {"name": "zeek.files.mime_type", "type": "keyword", "description": "File content type", "example": "application/pdf"},
        {"name": "zeek.files.total_bytes", "type": "long", "description": "Size of the file in bytes", "example": "102400"},
        {"name": "zeek.files.md5", "type": "keyword", "description": "MD5 hash of the file (for identification)", "example": "d41d8cd98f00b204e9800998ecf8427e"},
        {"name": "zeek.files.sha1", "type": "keyword", "description": "SHA1 hash of the file", "example": "da39a3ee5e6b4b0d3255bfef95601890afd80709"},
    ],
    "zeek.dhcp": [
        {"name": "@timestamp", "type": "date", "description": "When the DHCP transaction was observed", "example": "2026-03-05T12:34:56Z"},
        {"name": "source.ip", "type": "ip", "description": "Device requesting an IP address", "example": "0.0.0.0"},
        {"name": "zeek.dhcp.client_addr", "type": "ip", "description": "IP address assigned to the device", "example": "192.168.1.100"},
        {"name": "zeek.dhcp.mac", "type": "keyword", "description": "MAC address of the requesting device", "example": "aa:bb:cc:dd:ee:ff"},
        {"name": "zeek.dhcp.hostname", "type": "keyword", "description": "Hostname the device reported", "example": "johns-iphone"},
        {"name": "zeek.dhcp.msg_types", "type": "keyword", "description": "DHCP message type (DISCOVER, OFFER, REQUEST, ACK)", "example": "ACK"},
        {"name": "zeek.dhcp.lease_time", "type": "long", "description": "Lease duration in seconds", "example": "86400"},
    ],
    "zeek.smtp": [
        {"name": "@timestamp", "type": "date", "description": "When the email transaction was observed", "example": "2026-03-05T12:34:56Z"},
        {"name": "source.ip", "type": "ip", "description": "Device sending the email", "example": "192.168.1.100"},
        {"name": "destination.ip", "type": "ip", "description": "Mail server receiving the email", "example": "74.125.133.26"},
        {"name": "zeek.smtp.mailfrom", "type": "keyword", "description": "Sender email address", "example": "user@example.com"},
        {"name": "zeek.smtp.rcptto", "type": "keyword", "description": "Recipient email address(es)", "example": "recipient@example.com"},
        {"name": "zeek.smtp.subject", "type": "keyword", "description": "Email subject line", "example": "Meeting tomorrow"},
        {"name": "zeek.smtp.tls", "type": "boolean", "description": "Whether TLS encryption was used", "example": "true"},
    ],
    "suricata": [
        {"name": "@timestamp", "type": "date", "description": "When the alert was triggered", "example": "2026-03-05T12:34:56Z"},
        {"name": "source.ip", "type": "ip", "description": "Source IP that triggered the alert", "example": "192.168.1.100"},
        {"name": "destination.ip", "type": "ip", "description": "Destination IP involved in the alert", "example": "45.33.32.156"},
        {"name": "suricata.alert.signature", "type": "keyword", "description": "Name of the IDS rule that matched", "example": "ET SCAN Potential SSH Scan"},
        {"name": "suricata.alert.signature_id", "type": "integer", "description": "Unique rule ID (SID) from the Suricata ruleset", "example": "2001219"},
        {"name": "suricata.alert.severity", "type": "integer", "description": "Severity level (1=high, 2=medium, 3=low)", "example": "2"},
        {"name": "suricata.alert.category", "type": "keyword", "description": "Alert category grouping", "example": "Attempted Information Leak"},
        {"name": "network.transport", "type": "keyword", "description": "Transport protocol (tcp, udp, icmp)", "example": "tcp"},
    ],
}

# Default time range: last 24 hours
_DEFAULT_RANGE_HOURS = 24
_MAX_SIZE = 500
_DEFAULT_SIZE = 50


def _parse_time_range(request: web.Request) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    default_from = (now - timedelta(hours=_DEFAULT_RANGE_HOURS)).isoformat()
    default_to = now.isoformat()
    raw_from = request.query.get("from", "")
    raw_to = request.query.get("to", "")
    if raw_from:
        try:
            datetime.fromisoformat(raw_from.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raw_from = ""
    if raw_to:
        try:
            datetime.fromisoformat(raw_to.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raw_to = ""
    return (raw_from or default_from, raw_to or default_to)


async def handle_log_search(request: web.Request) -> web.Response:
    """GET /api/logs/search — Generic log search across Zeek/Suricata indices."""
    storage: StorageManager = request.app["storage"]
    from_ts, to_ts = _parse_time_range(request)

    log_type = request.query.get("log_type", "")
    query_str = request.query.get("query", "")
    fields = request.query.get("fields", "")
    size = min(int(request.query.get("size", _DEFAULT_SIZE)), _MAX_SIZE)
    sort_param = request.query.get("sort", "@timestamp:desc")
    search_after = request.query.get("search_after", "")

    # Build query
    filters = [{"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}}]

    if log_type and log_type in LOG_TYPE_FILTERS:
        filters.extend(LOG_TYPE_FILTERS[log_type])

    must = []
    if query_str:
        must.append({"query_string": {"query": query_str, "default_operator": "AND"}})

    body: dict = {
        "query": {"bool": {"must": must if must else [{"match_all": {}}], "filter": filters}},
        "size": size,
        "sort": [],
    }

    # Sort
    for part in sort_param.split(","):
        if ":" in part:
            field, order = part.split(":", 1)
            body["sort"].append({field: {"order": order}})
        else:
            body["sort"].append({part: {"order": "desc"}})
    # Always add _id tiebreaker for cursor pagination
    if not any("_id" in s for s in body["sort"]):
        body["sort"].append({"_id": {"order": "desc"}})

    # Cursor pagination
    if search_after:
        try:
            body["search_after"] = json.loads(search_after)
        except (json.JSONDecodeError, ValueError):
            pass

    # Field projection
    if fields:
        body["_source"] = [f.strip() for f in fields.split(",")]

    try:
        import asyncio
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: storage._client.search(index=NETWORK_INDEX, body=body)
        )

        hits = result.get("hits", {})
        documents = []
        last_sort = None
        for hit in hits.get("hits", []):
            doc = hit.get("_source", {})
            doc["_id"] = hit.get("_id")
            doc["_index"] = hit.get("_index")
            documents.append(doc)
            last_sort = hit.get("sort")

        return web.json_response({
            "hits": documents,
            "total": hits.get("total", {}).get("value", 0),
            "search_after": last_sort,
            "size": size,
            "log_type": log_type or "all",
        })
    except OpenSearchException as exc:
        logger.exception("Log search failed")
        return web.json_response({"error": f"Search failed: {exc}"}, status=500)


async def handle_log_fields(request: web.Request) -> web.Response:
    """GET /api/logs/fields/{log_type} — Return field definitions for a log type."""
    log_type = request.match_info.get("log_type", "")

    if log_type not in FIELD_DEFINITIONS:
        return web.json_response(
            {"error": f"Unknown log type: {log_type}", "available": list(FIELD_DEFINITIONS.keys())},
            status=400,
        )

    return web.json_response({"log_type": log_type, "fields": FIELD_DEFINITIONS[log_type]})


import json

def register_log_routes(app: web.Application, storage: StorageManager) -> None:
    app["storage"] = storage
    app.router.add_get("/api/logs/search", handle_log_search)
    app.router.add_get("/api/logs/fields/{log_type}", handle_log_fields)
    logger.info("Log search API routes registered (2 endpoints)")
```

**Step 4: Run tests**

Run: `cd daemon && python -m pytest tests/test_logs_api.py -v`
Expected: All PASS

**Step 5: Register in server.py**

Add to `daemon/api/server.py`:
```python
from api.logs import register_log_routes
# In create_app():
register_log_routes(app, storage)
```

**Step 6: Commit**

```bash
git add daemon/api/logs.py daemon/tests/test_logs_api.py daemon/api/server.py
git commit -m "feat(daemon): add generic log search API for Zeek/Suricata log browser"
```

---

### Task 1.2: OpenSearch Cluster API (`daemon/api/opensearch_cluster.py`)

**Files:**
- Create: `daemon/api/opensearch_cluster.py`
- Create: `daemon/tests/test_opensearch_cluster_api.py`
- Modify: `daemon/api/server.py` (register routes)

**Step 1: Write the test file**

```python
# daemon/tests/test_opensearch_cluster_api.py
"""Tests for daemon/api/opensearch_cluster.py"""

import unittest
from unittest.mock import MagicMock, patch
from aiohttp.test_utils import AioHTTPTestCase
from aiohttp import web
from api.opensearch_cluster import register_opensearch_cluster_routes

class TestOpenSearchClusterAPI(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        storage = MagicMock()
        storage._client = MagicMock()
        register_opensearch_cluster_routes(app, storage)
        return app

    async def test_cluster_health(self):
        with patch.object(
            self.app["storage"]._client.cluster, "health",
            return_value={"status": "green", "number_of_nodes": 1}
        ):
            resp = await self.client.request("GET", "/api/opensearch/cluster")
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertEqual(data["status"], "green")

    async def test_indices_list(self):
        with patch.object(
            self.app["storage"]._client.cat, "indices",
            return_value=[{"index": "arkime_sessions3-260305", "docs.count": "1000", "store.size": "10mb"}]
        ):
            resp = await self.client.request("GET", "/api/opensearch/indices")
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertIn("indices", data)

    async def test_shards(self):
        with patch.object(
            self.app["storage"]._client.cat, "shards",
            return_value=[{"index": "arkime_sessions3-260305", "shard": "0", "state": "STARTED"}]
        ):
            resp = await self.client.request("GET", "/api/opensearch/shards")
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertIn("shards", data)

    async def test_templates(self):
        with patch.object(
            self.app["storage"]._client.cat, "templates",
            return_value=[{"name": "malcolm_template", "index_patterns": "[arkime_sessions3-*]"}]
        ):
            resp = await self.client.request("GET", "/api/opensearch/templates")
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertIn("templates", data)
```

**Step 2: Run test → FAIL**

**Step 3: Implement `daemon/api/opensearch_cluster.py`**

```python
"""
NetTap OpenSearch Cluster API Routes

Provides cluster health, index listing, shard allocation, and template
information from the local OpenSearch instance.
"""

import asyncio
import logging

from aiohttp import web
from opensearchpy import OpenSearchException

from storage.manager import StorageManager

logger = logging.getLogger("nettap.api.opensearch_cluster")


async def handle_cluster_health(request: web.Request) -> web.Response:
    """GET /api/opensearch/cluster — Cluster health + stats."""
    storage: StorageManager = request.app["storage"]
    try:
        loop = asyncio.get_running_loop()
        health = await loop.run_in_executor(None, storage._client.cluster.health)
        stats = await loop.run_in_executor(None, lambda: storage._client.cluster.stats())
        return web.json_response({
            **health,
            "total_indices": stats.get("indices", {}).get("count", 0),
            "total_docs": stats.get("indices", {}).get("docs", {}).get("count", 0),
            "total_size_bytes": stats.get("indices", {}).get("store", {}).get("size_in_bytes", 0),
        })
    except OpenSearchException as exc:
        logger.exception("Failed to get cluster health")
        return web.json_response({"error": str(exc)}, status=500)


async def handle_indices(request: web.Request) -> web.Response:
    """GET /api/opensearch/indices — Index list with details."""
    storage: StorageManager = request.app["storage"]
    try:
        loop = asyncio.get_running_loop()
        indices = await loop.run_in_executor(
            None,
            lambda: storage._client.cat.indices(
                format="json",
                h="index,health,status,docs.count,store.size,pri.store.size,creation.date.string",
                s="index",
            )
        )
        return web.json_response({"indices": indices or [], "count": len(indices or [])})
    except OpenSearchException as exc:
        logger.exception("Failed to list indices")
        return web.json_response({"error": str(exc)}, status=500)


async def handle_shards(request: web.Request) -> web.Response:
    """GET /api/opensearch/shards — Shard allocation details."""
    storage: StorageManager = request.app["storage"]
    try:
        loop = asyncio.get_running_loop()
        shards = await loop.run_in_executor(
            None,
            lambda: storage._client.cat.shards(
                format="json",
                h="index,shard,prirep,state,docs,store,node",
                s="index,shard",
            )
        )
        return web.json_response({"shards": shards or [], "count": len(shards or [])})
    except OpenSearchException as exc:
        logger.exception("Failed to list shards")
        return web.json_response({"error": str(exc)}, status=500)


async def handle_templates(request: web.Request) -> web.Response:
    """GET /api/opensearch/templates — Index template list."""
    storage: StorageManager = request.app["storage"]
    try:
        loop = asyncio.get_running_loop()
        templates = await loop.run_in_executor(
            None,
            lambda: storage._client.cat.templates(
                format="json",
                h="name,index_patterns,order,version",
                s="name",
            )
        )
        return web.json_response({"templates": templates or [], "count": len(templates or [])})
    except OpenSearchException as exc:
        logger.exception("Failed to list templates")
        return web.json_response({"error": str(exc)}, status=500)


def register_opensearch_cluster_routes(app: web.Application, storage: StorageManager) -> None:
    app["storage"] = storage
    app.router.add_get("/api/opensearch/cluster", handle_cluster_health)
    app.router.add_get("/api/opensearch/indices", handle_indices)
    app.router.add_get("/api/opensearch/shards", handle_shards)
    app.router.add_get("/api/opensearch/templates", handle_templates)
    logger.info("OpenSearch cluster API routes registered (4 endpoints)")
```

**Step 4: Run tests → PASS**
**Step 5: Register in server.py**
**Step 6: Commit**

```bash
git commit -m "feat(daemon): add OpenSearch cluster visibility API (health, indices, shards, templates)"
```

---

### Task 1.3: Logstash Monitoring API (`daemon/api/logstash.py`)

**Files:**
- Create: `daemon/api/logstash.py`
- Create: `daemon/tests/test_logstash_api.py`
- Modify: `daemon/api/server.py` (register routes)

**Step 1: Write the test file**

```python
# daemon/tests/test_logstash_api.py
"""Tests for daemon/api/logstash.py — Logstash pipeline monitoring."""

import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from aiohttp.test_utils import AioHTTPTestCase
from aiohttp import web
from api.logstash import register_logstash_routes

class TestLogstashAPI(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        register_logstash_routes(app)
        return app

    @patch("api.logstash._fetch_logstash_api")
    async def test_stats(self, mock_fetch):
        mock_fetch.return_value = {
            "jvm": {"mem": {"heap_used_in_bytes": 500000000, "heap_max_in_bytes": 1000000000}},
            "process": {"cpu": {"percent": 25}},
            "pipelines": {"main": {"events": {"in": 1000, "out": 990, "filtered": 10}}},
        }
        resp = await self.client.request("GET", "/api/logstash/stats")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("jvm", data)
        self.assertIn("pipelines", data)

    @patch("api.logstash._fetch_logstash_api")
    async def test_pipelines(self, mock_fetch):
        mock_fetch.return_value = {
            "pipelines": {
                "main": {
                    "events": {"in": 1000, "out": 990, "filtered": 10, "duration_in_millis": 5000},
                    "plugins": {"inputs": [], "filters": [], "outputs": []},
                }
            }
        }
        resp = await self.client.request("GET", "/api/logstash/pipelines")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("pipelines", data)

    @patch("api.logstash._fetch_logstash_api")
    async def test_stats_unavailable(self, mock_fetch):
        mock_fetch.return_value = None
        resp = await self.client.request("GET", "/api/logstash/stats")
        self.assertEqual(resp.status, 502)
```

**Step 2: Run test → FAIL**

**Step 3: Implement `daemon/api/logstash.py`**

```python
"""
NetTap Logstash Monitoring API Routes

Queries the Logstash monitoring API (port 9600) to report pipeline
status, throughput, JVM stats, and errors.
"""

import asyncio
import logging
import os

import aiohttp
from aiohttp import web

logger = logging.getLogger("nettap.api.logstash")

LOGSTASH_API_URL = os.environ.get("LOGSTASH_API_URL", "http://logstash:9600")


async def _fetch_logstash_api(path: str = "/_node/stats") -> dict | None:
    """Fetch data from Logstash's monitoring API. Returns None on failure."""
    url = f"{LOGSTASH_API_URL}{path}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning("Logstash API returned %d for %s", resp.status, path)
                return None
    except Exception as exc:
        logger.warning("Logstash API unreachable at %s: %s", url, exc)
        return None


async def handle_logstash_stats(request: web.Request) -> web.Response:
    """GET /api/logstash/stats — Logstash node stats (JVM, CPU, pipelines)."""
    data = await _fetch_logstash_api("/_node/stats")
    if data is None:
        return web.json_response(
            {"error": "Logstash monitoring API unreachable", "available": False},
            status=502,
        )
    return web.json_response({
        "available": True,
        "jvm": data.get("jvm", {}),
        "process": data.get("process", {}),
        "pipelines": data.get("pipelines", {}),
        "events": data.get("events", {}),
    })


async def handle_logstash_pipelines(request: web.Request) -> web.Response:
    """GET /api/logstash/pipelines — Per-pipeline breakdown."""
    data = await _fetch_logstash_api("/_node/stats/pipelines")
    if data is None:
        return web.json_response(
            {"error": "Logstash monitoring API unreachable", "available": False},
            status=502,
        )
    pipelines = data.get("pipelines", {})
    result = []
    for name, stats in pipelines.items():
        events = stats.get("events", {})
        result.append({
            "id": name,
            "events": {
                "in": events.get("in", 0),
                "out": events.get("out", 0),
                "filtered": events.get("filtered", 0),
                "duration_ms": events.get("duration_in_millis", 0),
            },
            "plugins": stats.get("plugins", {}),
            "reloads": stats.get("reloads", {}),
        })
    return web.json_response({"pipelines": result, "count": len(result)})


def register_logstash_routes(app: web.Application) -> None:
    app.router.add_get("/api/logstash/stats", handle_logstash_stats)
    app.router.add_get("/api/logstash/pipelines", handle_logstash_pipelines)
    logger.info("Logstash monitoring API routes registered (2 endpoints)")
```

**Step 4: Run tests → PASS**
**Step 5: Register in server.py**
**Step 6: Commit**

```bash
git commit -m "feat(daemon): add Logstash monitoring API (pipeline stats, JVM, throughput)"
```

---

## Phase 2: Frontend — Design System + Layout Shell

### Task 2.1: New Design System CSS

**Files:**
- Modify: `web/src/lib/styles/global.css` (complete rewrite)

Update CSS custom properties for Datadog/Grafana aesthetic. Keep the existing variable names where possible (pages reference them), add new chart-specific colors.

Key changes:
- Add chart color palette (8-10 vibrant colors for data viz)
- Add purple, cyan, orange accent variants
- Tighter data table styles (denser, monospace values)
- Sidebar collapse transition
- Tab component styles

**Commit:** `refactor(web): redesign CSS design system for Datadog/Grafana aesthetic`

### Task 2.2: New Layout Shell

**Files:**
- Rewrite: `web/src/routes/+layout.svelte`

New nav items: Home, Log Explorer, Devices, Alerts, Connections, Infrastructure, Settings
Collapsible sidebar, updated icons, system status in topbar.

**Commit:** `feat(web): new layout shell with collapsible sidebar and updated navigation`

---

## Phase 3: Frontend Pages (one task per page)

Each page follows this pattern:
1. Create SvelteKit API route (`+server.ts`) that proxies to daemon
2. Create page load function (`+page.ts`) or client-side fetch
3. Create page component (`+page.svelte`)
4. Create component tests
5. Commit

### Task 3.1: Dashboard (Home)
### Task 3.2: Log Explorer
### Task 3.3: Devices
### Task 3.4: Alerts
### Task 3.5: Connections
### Task 3.6: Infrastructure (3 tabs)
### Task 3.7: Settings

Each page will be built after its mockup is approved and its daemon endpoints are verified working.

---

## Phase 4: Integration + Polish

### Task 4.1: Run full test suite
Run: `cd daemon && python -m pytest -v` and `cd web && npx vitest run` and `cd web && npx svelte-check`

### Task 4.2: Deploy to N100 and verify all pages
### Task 4.3: Create Linear issues for all changes
### Task 4.4: Update tracking docs

---

## Execution Order

```
Phase 0 (Mockups) — get approval for all 8 mockups
  ↓
Phase 1 (Daemon APIs) — build + test 3 new API modules
  ↓
Phase 2 (Design System + Shell) — CSS + layout
  ↓
Phase 3 (Pages) — one by one, each with tests
  ↓
Phase 4 (Integration) — full test suite, deploy, Linear
```

**Critical path:** Mockup approval gates everything. Daemon APIs gate frontend pages.
