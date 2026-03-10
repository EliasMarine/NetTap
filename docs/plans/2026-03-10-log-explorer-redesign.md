# Log Explorer Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform the Log Explorer from a basic spreadsheet into a Network Activity Intelligence Dashboard with aggregate insights, visualizations, and click-to-drill interactivity.

**Architecture:** Add 6 new aggregation endpoints to `daemon/api/logs.py`, 6 SvelteKit proxy routes, a new `web/src/lib/api/logs.ts` client module, and a complete frontend redesign of `web/src/routes/logs/+page.svelte` with hero stats, SVG timeline chart, protocol breakdown, top talkers, top destinations, top DNS queries, and an enhanced log table with active filter badges.

**Tech Stack:** Python/aiohttp + OpenSearch aggregations (backend), SvelteKit + Svelte 5 runes + SVG (frontend), Vitest (frontend tests), pytest/aiohttp (backend tests)

---

## Task 1: Backend — Add 6 Aggregation Endpoints to `daemon/api/logs.py`

**Files:**
- Modify: `daemon/api/logs.py`
- Test: `daemon/tests/test_logs_api.py`

### Step 1: Write failing tests for all 6 new endpoints

Add these test methods to `daemon/tests/test_logs_api.py` inside `TestLogSearchAPI`:

```python
# --- Stats endpoint ---

async def test_stats_returns_aggregates(self):
    """GET /api/logs/stats returns total_events, unique_sources, protocol_count, total_bytes."""
    self.mock_client.search.return_value = {
        "hits": {"total": {"value": 5000}},
        "aggregations": {
            "unique_sources": {"value": 42},
            "protocol_count": {"value": 7},
            "total_source_bytes": {"value": 1024000},
            "total_dest_bytes": {"value": 2048000},
        },
    }
    resp = await self.client.request("GET", "/api/logs/stats")
    self.assertEqual(resp.status, 200)
    data = await resp.json()
    self.assertEqual(data["total_events"], 5000)
    self.assertEqual(data["unique_sources"], 42)
    self.assertEqual(data["protocol_count"], 7)
    self.assertEqual(data["total_bytes"], 3072000)

async def test_stats_with_time_range(self):
    """Stats endpoint respects from/to params."""
    self.mock_client.search.return_value = {
        "hits": {"total": {"value": 100}},
        "aggregations": {
            "unique_sources": {"value": 5},
            "protocol_count": {"value": 2},
            "total_source_bytes": {"value": 100},
            "total_dest_bytes": {"value": 200},
        },
    }
    resp = await self.client.request(
        "GET", "/api/logs/stats?from=2026-03-01T00:00:00Z&to=2026-03-05T00:00:00Z"
    )
    self.assertEqual(resp.status, 200)
    call_body = self.mock_client.search.call_args[1]["body"]
    time_filter = call_body["query"]["bool"]["filter"][0]
    self.assertIn("range", time_filter)

# --- Timeline endpoint ---

async def test_timeline_returns_buckets(self):
    """GET /api/logs/timeline returns time-series buckets by log type."""
    self.mock_client.search.return_value = {
        "hits": {"total": {"value": 0}},
        "aggregations": {
            "over_time": {
                "buckets": [
                    {
                        "key_as_string": "2026-03-05T12:00:00Z",
                        "doc_count": 100,
                        "by_type": {
                            "buckets": [
                                {"key": "conn", "doc_count": 60},
                                {"key": "dns", "doc_count": 30},
                                {"key": "http", "doc_count": 10},
                            ]
                        },
                    }
                ]
            }
        },
    }
    resp = await self.client.request("GET", "/api/logs/timeline")
    self.assertEqual(resp.status, 200)
    data = await resp.json()
    self.assertIn("buckets", data)
    self.assertEqual(len(data["buckets"]), 1)
    self.assertEqual(data["buckets"][0]["conn"], 60)
    self.assertEqual(data["buckets"][0]["dns"], 30)

async def test_timeline_validates_interval(self):
    """Invalid interval falls back to 1h."""
    self.mock_client.search.return_value = {
        "hits": {"total": {"value": 0}},
        "aggregations": {"over_time": {"buckets": []}},
    }
    resp = await self.client.request("GET", "/api/logs/timeline?interval=evil")
    self.assertEqual(resp.status, 200)
    data = await resp.json()
    self.assertEqual(data["interval"], "1h")

# --- Top Talkers endpoint ---

async def test_top_talkers_returns_ips(self):
    """GET /api/logs/top-talkers returns source IP aggregation."""
    self.mock_client.search.return_value = {
        "hits": {"total": {"value": 0}},
        "aggregations": {
            "top_talkers": {
                "buckets": [
                    {"key": "192.168.1.100", "doc_count": 500},
                    {"key": "192.168.1.101", "doc_count": 300},
                ]
            }
        },
    }
    resp = await self.client.request("GET", "/api/logs/top-talkers")
    self.assertEqual(resp.status, 200)
    data = await resp.json()
    self.assertEqual(len(data["talkers"]), 2)
    self.assertEqual(data["talkers"][0]["ip"], "192.168.1.100")

# --- Protocol Breakdown endpoint ---

async def test_protocol_breakdown_returns_protocols(self):
    """GET /api/logs/protocol-breakdown returns event.dataset aggregation."""
    self.mock_client.search.return_value = {
        "hits": {"total": {"value": 0}},
        "aggregations": {
            "by_protocol": {
                "buckets": [
                    {"key": "conn", "doc_count": 1000},
                    {"key": "dns", "doc_count": 500},
                    {"key": "http", "doc_count": 200},
                ]
            }
        },
    }
    resp = await self.client.request("GET", "/api/logs/protocol-breakdown")
    self.assertEqual(resp.status, 200)
    data = await resp.json()
    self.assertEqual(len(data["protocols"]), 3)
    self.assertEqual(data["protocols"][0]["protocol"], "conn")

# --- Top Destinations endpoint ---

async def test_top_destinations_returns_ips(self):
    """GET /api/logs/top-destinations returns destination IP aggregation."""
    self.mock_client.search.return_value = {
        "hits": {"total": {"value": 0}},
        "aggregations": {
            "top_destinations": {
                "buckets": [
                    {"key": "8.8.8.8", "doc_count": 400},
                    {"key": "1.1.1.1", "doc_count": 200},
                ]
            }
        },
    }
    resp = await self.client.request("GET", "/api/logs/top-destinations")
    self.assertEqual(resp.status, 200)
    data = await resp.json()
    self.assertEqual(len(data["destinations"]), 2)
    self.assertEqual(data["destinations"][0]["ip"], "8.8.8.8")

# --- Top DNS endpoint ---

async def test_top_dns_returns_queries(self):
    """GET /api/logs/top-dns returns DNS query aggregation."""
    self.mock_client.search.return_value = {
        "hits": {"total": {"value": 0}},
        "aggregations": {
            "top_queries": {
                "buckets": [
                    {"key": "google.com", "doc_count": 300},
                    {"key": "github.com", "doc_count": 100},
                ]
            }
        },
    }
    resp = await self.client.request("GET", "/api/logs/top-dns")
    self.assertEqual(resp.status, 200)
    data = await resp.json()
    self.assertEqual(len(data["queries"]), 2)
    self.assertEqual(data["queries"][0]["domain"], "google.com")

# --- Error handling ---

async def test_stats_opensearch_error(self):
    """Stats endpoint returns 502 on OpenSearch error."""
    from opensearchpy import OpenSearchException
    self.mock_client.search.side_effect = OpenSearchException("timeout")
    resp = await self.client.request("GET", "/api/logs/stats")
    self.assertEqual(resp.status, 502)
```

### Step 2: Run tests to verify they fail

Run: `cd "/Volumes/ExtraStrg_RAID1/Mega Sync/NetTap/daemon" && python -m pytest tests/test_logs_api.py -v`
Expected: All new tests FAIL (404 — routes don't exist yet)

### Step 3: Implement the 6 aggregation handlers in `daemon/api/logs.py`

Add these constants after `_DEFAULT_SIZE = 50` (line 127):

```python
# Allowed intervals for timeline endpoint
_ALLOWED_INTERVALS = {"1m", "5m", "10m", "15m", "30m", "1h", "6h", "12h", "1d"}

# Log type label map for display
_LOG_TYPE_LABELS = {
    "conn": "Connections",
    "dns": "DNS",
    "http": "HTTP",
    "ssl": "TLS",
    "files": "Files",
    "dhcp": "DHCP",
    "smtp": "SMTP",
    "alert": "Suricata",
}
```

Add these handler functions after `handle_log_fields`:

```python
async def handle_log_stats(request: web.Request) -> web.Response:
    """GET /api/logs/stats?from=&to=

    Returns aggregate statistics: total events, unique source IPs,
    distinct protocols, and total bytes transferred.
    """
    storage: StorageManager = request.app["storage"]
    from_ts, to_ts = _parse_time_range(request)

    body = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [{"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}}]
            }
        },
        "aggs": {
            "unique_sources": {"cardinality": {"field": "source.ip"}},
            "protocol_count": {"cardinality": {"field": "event.dataset"}},
            "total_source_bytes": {"sum": {"field": "source.bytes"}},
            "total_dest_bytes": {"sum": {"field": "destination.bytes"}},
        },
    }

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: storage._client.search(index=NETWORK_INDEX, body=body)
        )
    except OpenSearchException as exc:
        logger.error("OpenSearch error in logs/stats: %s", exc)
        return web.json_response({"error": f"Query failed: {exc}"}, status=502)

    aggs = result.get("aggregations", {})
    total = result.get("hits", {}).get("total", {})
    total_events = total.get("value", 0) if isinstance(total, dict) else total

    src_bytes = aggs.get("total_source_bytes", {}).get("value", 0) or 0
    dst_bytes = aggs.get("total_dest_bytes", {}).get("value", 0) or 0

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "total_events": total_events,
        "unique_sources": aggs.get("unique_sources", {}).get("value", 0),
        "protocol_count": aggs.get("protocol_count", {}).get("value", 0),
        "total_bytes": int(src_bytes + dst_bytes),
    })


async def handle_log_timeline(request: web.Request) -> web.Response:
    """GET /api/logs/timeline?from=&to=&interval=

    Returns time-series event counts bucketed by interval and log type.
    """
    storage: StorageManager = request.app["storage"]
    from_ts, to_ts = _parse_time_range(request)
    interval = request.query.get("interval", "1h")
    if interval not in _ALLOWED_INTERVALS:
        interval = "1h"

    body = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [{"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}}]
            }
        },
        "aggs": {
            "over_time": {
                "date_histogram": {
                    "field": "@timestamp",
                    "fixed_interval": interval,
                    "min_doc_count": 0,
                    "extended_bounds": {"min": from_ts, "max": to_ts},
                },
                "aggs": {
                    "by_type": {
                        "terms": {"field": "event.dataset", "size": 10}
                    }
                },
            }
        },
    }

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: storage._client.search(index=NETWORK_INDEX, body=body)
        )
    except OpenSearchException as exc:
        logger.error("OpenSearch error in logs/timeline: %s", exc)
        return web.json_response({"error": f"Query failed: {exc}"}, status=502)

    buckets = []
    for bucket in result.get("aggregations", {}).get("over_time", {}).get("buckets", []):
        entry = {
            "timestamp": bucket.get("key_as_string", ""),
            "total": bucket.get("doc_count", 0),
            "conn": 0, "dns": 0, "http": 0, "ssl": 0,
            "files": 0, "dhcp": 0, "smtp": 0, "alert": 0,
        }
        for type_bucket in bucket.get("by_type", {}).get("buckets", []):
            key = type_bucket.get("key", "")
            if key in entry:
                entry[key] = type_bucket.get("doc_count", 0)
        buckets.append(entry)

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "interval": interval,
        "buckets": buckets,
    })


async def handle_log_top_talkers(request: web.Request) -> web.Response:
    """GET /api/logs/top-talkers?from=&to=&limit=

    Returns the most active source IPs by event count.
    """
    storage: StorageManager = request.app["storage"]
    from_ts, to_ts = _parse_time_range(request)
    limit = min(int(request.query.get("limit", "10")), 50)

    body = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [{"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}}]
            }
        },
        "aggs": {
            "top_talkers": {
                "terms": {"field": "source.ip", "size": limit}
            }
        },
    }

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: storage._client.search(index=NETWORK_INDEX, body=body)
        )
    except OpenSearchException as exc:
        logger.error("OpenSearch error in logs/top-talkers: %s", exc)
        return web.json_response({"error": f"Query failed: {exc}"}, status=502)

    talkers = []
    for bucket in result.get("aggregations", {}).get("top_talkers", {}).get("buckets", []):
        talkers.append({
            "ip": bucket.get("key", ""),
            "count": bucket.get("doc_count", 0),
        })

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "talkers": talkers,
    })


async def handle_log_protocol_breakdown(request: web.Request) -> web.Response:
    """GET /api/logs/protocol-breakdown?from=&to=

    Returns event counts grouped by log type (event.dataset).
    """
    storage: StorageManager = request.app["storage"]
    from_ts, to_ts = _parse_time_range(request)

    body = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [{"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}}]
            }
        },
        "aggs": {
            "by_protocol": {
                "terms": {"field": "event.dataset", "size": 20}
            }
        },
    }

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: storage._client.search(index=NETWORK_INDEX, body=body)
        )
    except OpenSearchException as exc:
        logger.error("OpenSearch error in logs/protocol-breakdown: %s", exc)
        return web.json_response({"error": f"Query failed: {exc}"}, status=502)

    protocols = []
    for bucket in result.get("aggregations", {}).get("by_protocol", {}).get("buckets", []):
        protocols.append({
            "protocol": bucket.get("key", ""),
            "label": _LOG_TYPE_LABELS.get(bucket.get("key", ""), bucket.get("key", "")),
            "count": bucket.get("doc_count", 0),
        })

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "protocols": protocols,
    })


async def handle_log_top_destinations(request: web.Request) -> web.Response:
    """GET /api/logs/top-destinations?from=&to=&limit=

    Returns the most contacted destination IPs.
    """
    storage: StorageManager = request.app["storage"]
    from_ts, to_ts = _parse_time_range(request)
    limit = min(int(request.query.get("limit", "10")), 50)

    body = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [{"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}}]
            }
        },
        "aggs": {
            "top_destinations": {
                "terms": {"field": "destination.ip", "size": limit}
            }
        },
    }

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: storage._client.search(index=NETWORK_INDEX, body=body)
        )
    except OpenSearchException as exc:
        logger.error("OpenSearch error in logs/top-destinations: %s", exc)
        return web.json_response({"error": f"Query failed: {exc}"}, status=502)

    destinations = []
    for bucket in result.get("aggregations", {}).get("top_destinations", {}).get("buckets", []):
        destinations.append({
            "ip": bucket.get("key", ""),
            "count": bucket.get("doc_count", 0),
        })

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "destinations": destinations,
    })


async def handle_log_top_dns(request: web.Request) -> web.Response:
    """GET /api/logs/top-dns?from=&to=&limit=

    Returns the most queried DNS domain names.
    """
    storage: StorageManager = request.app["storage"]
    from_ts, to_ts = _parse_time_range(request)
    limit = min(int(request.query.get("limit", "10")), 50)

    body = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
                    {"term": {"event.provider": "zeek"}},
                    {"term": {"event.dataset": "dns"}},
                ]
            }
        },
        "aggs": {
            "top_queries": {
                "terms": {"field": "zeek.dns.query.keyword", "size": limit}
            }
        },
    }

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: storage._client.search(index=NETWORK_INDEX, body=body)
        )
    except OpenSearchException as exc:
        logger.error("OpenSearch error in logs/top-dns: %s", exc)
        return web.json_response({"error": f"Query failed: {exc}"}, status=502)

    queries = []
    for bucket in result.get("aggregations", {}).get("top_queries", {}).get("buckets", []):
        queries.append({
            "domain": bucket.get("key", ""),
            "count": bucket.get("doc_count", 0),
        })

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "queries": queries,
    })
```

Update `register_log_routes` to register all new endpoints (**static routes BEFORE parameterized routes**):

```python
def register_log_routes(app: web.Application, storage: StorageManager) -> None:
    app["storage"] = storage
    app.router.add_get("/api/logs/search", handle_log_search)
    app.router.add_get("/api/logs/stats", handle_log_stats)
    app.router.add_get("/api/logs/timeline", handle_log_timeline)
    app.router.add_get("/api/logs/top-talkers", handle_log_top_talkers)
    app.router.add_get("/api/logs/protocol-breakdown", handle_log_protocol_breakdown)
    app.router.add_get("/api/logs/top-destinations", handle_log_top_destinations)
    app.router.add_get("/api/logs/top-dns", handle_log_top_dns)
    app.router.add_get("/api/logs/fields/{log_type}", handle_log_fields)
    logger.info("Log search API routes registered (8 endpoints)")
```

### Step 4: Run tests to verify they pass

Run: `cd "/Volumes/ExtraStrg_RAID1/Mega Sync/NetTap/daemon" && python -m pytest tests/test_logs_api.py -v`
Expected: ALL tests PASS

### Step 5: Commit

```bash
git add daemon/api/logs.py daemon/tests/test_logs_api.py
git commit -m "feat(logs): add 6 aggregation endpoints for log explorer dashboard"
```

---

## Task 2: SvelteKit Proxy Routes (6 new routes)

**Files:**
- Create: `web/src/routes/api/logs/stats/+server.ts`
- Create: `web/src/routes/api/logs/timeline/+server.ts`
- Create: `web/src/routes/api/logs/top-talkers/+server.ts`
- Create: `web/src/routes/api/logs/protocol-breakdown/+server.ts`
- Create: `web/src/routes/api/logs/top-destinations/+server.ts`
- Create: `web/src/routes/api/logs/top-dns/+server.ts`

### Step 1: Create all 6 proxy routes

Each follows the same pattern (referencing `web/src/routes/api/alerts/timeline/+server.ts`):

**`stats/+server.ts`:**
```typescript
import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

export const GET: RequestHandler = async ({ url }) => {
	const params = new URLSearchParams();
	for (const key of ['from', 'to']) {
		const val = url.searchParams.get(key);
		if (val) params.set(key, val);
	}
	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/logs/stats${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse response' }));
	return json(data, { status: res.status });
};
```

**`timeline/+server.ts`:**
```typescript
import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

export const GET: RequestHandler = async ({ url }) => {
	const params = new URLSearchParams();
	for (const key of ['from', 'to', 'interval']) {
		const val = url.searchParams.get(key);
		if (val) params.set(key, val);
	}
	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/logs/timeline${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse response' }));
	return json(data, { status: res.status });
};
```

**`top-talkers/+server.ts`:**
```typescript
import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

export const GET: RequestHandler = async ({ url }) => {
	const params = new URLSearchParams();
	for (const key of ['from', 'to', 'limit']) {
		const val = url.searchParams.get(key);
		if (val) params.set(key, val);
	}
	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/logs/top-talkers${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse response' }));
	return json(data, { status: res.status });
};
```

**`protocol-breakdown/+server.ts`:**
```typescript
import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

export const GET: RequestHandler = async ({ url }) => {
	const params = new URLSearchParams();
	for (const key of ['from', 'to']) {
		const val = url.searchParams.get(key);
		if (val) params.set(key, val);
	}
	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/logs/protocol-breakdown${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse response' }));
	return json(data, { status: res.status });
};
```

**`top-destinations/+server.ts`:**
```typescript
import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

export const GET: RequestHandler = async ({ url }) => {
	const params = new URLSearchParams();
	for (const key of ['from', 'to', 'limit']) {
		const val = url.searchParams.get(key);
		if (val) params.set(key, val);
	}
	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/logs/top-destinations${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse response' }));
	return json(data, { status: res.status });
};
```

**`top-dns/+server.ts`:**
```typescript
import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

export const GET: RequestHandler = async ({ url }) => {
	const params = new URLSearchParams();
	for (const key of ['from', 'to', 'limit']) {
		const val = url.searchParams.get(key);
		if (val) params.set(key, val);
	}
	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/logs/top-dns${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse response' }));
	return json(data, { status: res.status });
};
```

### Step 2: Commit

```bash
git add web/src/routes/api/logs/
git commit -m "feat(logs): add 6 SvelteKit proxy routes for log aggregations"
```

---

## Task 3: Client API Module — `web/src/lib/api/logs.ts`

**Files:**
- Create: `web/src/lib/api/logs.ts`
- Test: `web/src/lib/api/logs.test.ts`

### Step 1: Write failing tests

Create `web/src/lib/api/logs.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
	getLogStats,
	getLogTimeline,
	getLogTopTalkers,
	getLogProtocolBreakdown,
	getLogTopDestinations,
	getLogTopDns,
	formatBytes,
	formatCompactNumber,
	protocolColor,
	protocolLabel,
} from './logs.js';

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

beforeEach(() => {
	mockFetch.mockReset();
});

describe('getLogStats', () => {
	it('returns stats on success', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: () => Promise.resolve({
				from: '', to: '', total_events: 5000,
				unique_sources: 42, protocol_count: 7, total_bytes: 3072000,
			}),
		});
		const result = await getLogStats({ from: '2026-03-01T00:00:00Z' });
		expect(result.total_events).toBe(5000);
		expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining('/api/logs/stats'));
	});

	it('returns zeros on failure', async () => {
		mockFetch.mockResolvedValueOnce({ ok: false });
		const result = await getLogStats();
		expect(result.total_events).toBe(0);
	});
});

describe('getLogTimeline', () => {
	it('returns buckets on success', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: () => Promise.resolve({
				from: '', to: '', interval: '1h',
				buckets: [{ timestamp: '2026-03-05T12:00:00Z', total: 100, conn: 60, dns: 30, http: 10, ssl: 0, files: 0, dhcp: 0, smtp: 0, alert: 0 }],
			}),
		});
		const result = await getLogTimeline();
		expect(result.buckets).toHaveLength(1);
		expect(result.buckets[0].conn).toBe(60);
	});

	it('returns empty buckets on failure', async () => {
		mockFetch.mockResolvedValueOnce({ ok: false });
		const result = await getLogTimeline();
		expect(result.buckets).toEqual([]);
	});
});

describe('getLogTopTalkers', () => {
	it('returns talkers on success', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: () => Promise.resolve({
				from: '', to: '', talkers: [{ ip: '192.168.1.100', count: 500 }],
			}),
		});
		const result = await getLogTopTalkers();
		expect(result.talkers).toHaveLength(1);
	});
});

describe('getLogProtocolBreakdown', () => {
	it('returns protocols on success', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: () => Promise.resolve({
				from: '', to: '', protocols: [{ protocol: 'conn', label: 'Connections', count: 1000 }],
			}),
		});
		const result = await getLogProtocolBreakdown();
		expect(result.protocols).toHaveLength(1);
	});
});

describe('getLogTopDestinations', () => {
	it('returns destinations on success', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: () => Promise.resolve({
				from: '', to: '', destinations: [{ ip: '8.8.8.8', count: 400 }],
			}),
		});
		const result = await getLogTopDestinations();
		expect(result.destinations).toHaveLength(1);
	});
});

describe('getLogTopDns', () => {
	it('returns queries on success', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: () => Promise.resolve({
				from: '', to: '', queries: [{ domain: 'google.com', count: 300 }],
			}),
		});
		const result = await getLogTopDns();
		expect(result.queries).toHaveLength(1);
	});
});

describe('formatBytes', () => {
	it('formats bytes correctly', () => {
		expect(formatBytes(0)).toBe('0 B');
		expect(formatBytes(1024)).toBe('1.0 KB');
		expect(formatBytes(1048576)).toBe('1.0 MB');
		expect(formatBytes(1073741824)).toBe('1.0 GB');
	});
});

describe('formatCompactNumber', () => {
	it('formats numbers compactly', () => {
		expect(formatCompactNumber(500)).toBe('500');
		expect(formatCompactNumber(1500)).toBe('1.5K');
		expect(formatCompactNumber(2500000)).toBe('2.5M');
	});
});

describe('protocolColor', () => {
	it('returns colors for known protocols', () => {
		expect(protocolColor('conn')).toBe('var(--cyan)');
		expect(protocolColor('dns')).toBe('var(--green)');
		expect(protocolColor('http')).toBe('var(--orange)');
		expect(protocolColor('alert')).toBe('var(--red)');
	});

	it('returns default for unknown protocols', () => {
		expect(protocolColor('unknown')).toBe('var(--text-muted)');
	});
});

describe('protocolLabel', () => {
	it('returns labels for known protocols', () => {
		expect(protocolLabel('conn')).toBe('Connections');
		expect(protocolLabel('ssl')).toBe('TLS');
		expect(protocolLabel('alert')).toBe('IDS Alerts');
	});
});
```

### Step 2: Implement `web/src/lib/api/logs.ts`

```typescript
/**
 * Client-side API helpers for log explorer endpoints.
 * Calls SvelteKit server proxy routes → daemon.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TimeRangeParams {
	from?: string;
	to?: string;
}

export interface LogStatsResponse {
	from: string;
	to: string;
	total_events: number;
	unique_sources: number;
	protocol_count: number;
	total_bytes: number;
}

export interface LogTimelineBucket {
	timestamp: string;
	total: number;
	conn: number;
	dns: number;
	http: number;
	ssl: number;
	files: number;
	dhcp: number;
	smtp: number;
	alert: number;
}

export interface LogTimelineResponse {
	from: string;
	to: string;
	interval: string;
	buckets: LogTimelineBucket[];
}

export interface LogTalkerEntry {
	ip: string;
	count: number;
}

export interface LogTopTalkersResponse {
	from: string;
	to: string;
	talkers: LogTalkerEntry[];
}

export interface LogProtocolEntry {
	protocol: string;
	label: string;
	count: number;
}

export interface LogProtocolBreakdownResponse {
	from: string;
	to: string;
	protocols: LogProtocolEntry[];
}

export interface LogDestinationEntry {
	ip: string;
	count: number;
}

export interface LogTopDestinationsResponse {
	from: string;
	to: string;
	destinations: LogDestinationEntry[];
}

export interface LogDnsEntry {
	domain: string;
	count: number;
}

export interface LogTopDnsResponse {
	from: string;
	to: string;
	queries: LogDnsEntry[];
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function buildQuery(params: Record<string, string | number | undefined>): string {
	const qs = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value !== undefined && value !== '') qs.set(key, String(value));
	}
	const str = qs.toString();
	return str ? `?${str}` : '';
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

export async function getLogStats(opts: TimeRangeParams = {}): Promise<LogStatsResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/logs/stats${query}`);
	if (!res.ok) return { from: '', to: '', total_events: 0, unique_sources: 0, protocol_count: 0, total_bytes: 0 };
	return res.json();
}

export async function getLogTimeline(
	opts: TimeRangeParams & { interval?: string } = {}
): Promise<LogTimelineResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to, interval: opts.interval });
	const res = await fetch(`/api/logs/timeline${query}`);
	if (!res.ok) return { from: '', to: '', interval: opts.interval || '1h', buckets: [] };
	return res.json();
}

export async function getLogTopTalkers(
	opts: TimeRangeParams & { limit?: number } = {}
): Promise<LogTopTalkersResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to, limit: opts.limit });
	const res = await fetch(`/api/logs/top-talkers${query}`);
	if (!res.ok) return { from: '', to: '', talkers: [] };
	return res.json();
}

export async function getLogProtocolBreakdown(
	opts: TimeRangeParams = {}
): Promise<LogProtocolBreakdownResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/logs/protocol-breakdown${query}`);
	if (!res.ok) return { from: '', to: '', protocols: [] };
	return res.json();
}

export async function getLogTopDestinations(
	opts: TimeRangeParams & { limit?: number } = {}
): Promise<LogTopDestinationsResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to, limit: opts.limit });
	const res = await fetch(`/api/logs/top-destinations${query}`);
	if (!res.ok) return { from: '', to: '', destinations: [] };
	return res.json();
}

export async function getLogTopDns(
	opts: TimeRangeParams & { limit?: number } = {}
): Promise<LogTopDnsResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to, limit: opts.limit });
	const res = await fetch(`/api/logs/top-dns${query}`);
	if (!res.ok) return { from: '', to: '', queries: [] };
	return res.json();
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

export function formatBytes(bytes: number): string {
	if (bytes === 0) return '0 B';
	const units = ['B', 'KB', 'MB', 'GB', 'TB'];
	const i = Math.floor(Math.log(bytes) / Math.log(1024));
	return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

export function formatCompactNumber(n: number): string {
	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
	if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
	return String(n);
}

const _PROTOCOL_COLORS: Record<string, string> = {
	conn: 'var(--cyan)',
	dns: 'var(--green)',
	http: 'var(--orange)',
	ssl: 'var(--purple)',
	files: 'var(--yellow, #ffd600)',
	dhcp: 'var(--pink, #ff80ab)',
	smtp: 'var(--teal, #64ffda)',
	alert: 'var(--red)',
};

const _PROTOCOL_LABELS: Record<string, string> = {
	conn: 'Connections',
	dns: 'DNS',
	http: 'HTTP',
	ssl: 'TLS',
	files: 'Files',
	dhcp: 'DHCP',
	smtp: 'SMTP',
	alert: 'IDS Alerts',
};

export function protocolColor(protocol: string): string {
	return _PROTOCOL_COLORS[protocol] || 'var(--text-muted)';
}

export function protocolLabel(protocol: string): string {
	return _PROTOCOL_LABELS[protocol] || protocol;
}
```

### Step 3: Run tests

Run: `cd "/Volumes/ExtraStrg_RAID1/Mega Sync/NetTap/web" && npx vitest run src/lib/api/logs.test.ts`
Expected: ALL tests PASS

### Step 4: Commit

```bash
git add web/src/lib/api/logs.ts web/src/lib/api/logs.test.ts
git commit -m "feat(logs): add client API module with types, fetch helpers, and formatting utils"
```

---

## Task 4: Frontend Redesign — `web/src/routes/logs/+page.svelte`

**Files:**
- Modify: `web/src/routes/logs/+page.svelte`

### Step 1: Full page rewrite

The page follows the same architecture as the Alerts page redesign. Key sections:

1. **Header** — Title + subtitle + Export CSV + Refresh buttons
2. **Time range pills** — 15m, 1h, 4h, 24h, 7d, 30d
3. **Hero Stats Grid** — 4 cards: Total Events, Active Sources, Protocols Seen, Data Volume
4. **Activity Timeline** — SVG stacked bar chart by log type with hover tooltips
5. **Two-column row**: Protocol Breakdown (horizontal bars) + Top Talkers (IP list)
6. **Two-column row**: Top Destinations + Top DNS Queries
7. **Log type tabs** + Search bar
8. **Active filter badges** (from chart clicks, dismissible)
9. **Enhanced log table** — existing functionality preserved
10. **Load more** button

**Key implementation details:**

- Use `Promise.allSettled` for parallel data fetch (stats, timeline, top-talkers, protocols, destinations, dns) — isolate errors
- `initialized` guard to prevent double-fetch
- Click-to-drill: clicking a protocol bar sets the `logType` tab + refetches table; clicking an IP sets a search query filter; clicking a DNS domain sets search query
- Responsive SVG with `bind:clientWidth`
- Same CSS variable system as Alerts page (dark theme, stat cards, etc.)
- `protocolColor()` and `protocolLabel()` from the API module for consistent coloring
- All existing table functionality preserved (sort, expand, CSV, cursor pagination)

### Step 2: Run type check

Run: `cd "/Volumes/ExtraStrg_RAID1/Mega Sync/NetTap/web" && npx svelte-check`
Expected: No errors

### Step 3: Commit

```bash
git add web/src/routes/logs/+page.svelte
git commit -m "feat(logs): redesign Log Explorer with activity dashboard, charts, and drill-down"
```

---

## Task 5: Frontend Tests — `web/src/routes/logs/logs.test.ts`

**Files:**
- Modify: `web/src/routes/logs/logs.test.ts`

### Step 1: Add component and integration tests

Test the exported `flattenObject` function and verify the component exports properly. The main test coverage comes from the API client tests in Task 3.

### Step 2: Run all tests

Run: `cd "/Volumes/ExtraStrg_RAID1/Mega Sync/NetTap/web" && npx vitest run`
Run: `cd "/Volumes/ExtraStrg_RAID1/Mega Sync/NetTap/daemon" && python -m pytest tests/test_logs_api.py -v`
Expected: ALL tests PASS

### Step 3: Commit

```bash
git add web/src/routes/logs/logs.test.ts
git commit -m "test(logs): add tests for log explorer component"
```

---

## Task 6: Verification & Cleanup

### Step 1: Run full test suite

Run: `cd "/Volumes/ExtraStrg_RAID1/Mega Sync/NetTap/daemon" && python -m pytest -v`
Run: `cd "/Volumes/ExtraStrg_RAID1/Mega Sync/NetTap/web" && npx vitest run`
Run: `cd "/Volumes/ExtraStrg_RAID1/Mega Sync/NetTap/web" && npx svelte-check`

### Step 2: Create Linear issue

### Step 3: Update tracking docs (DEPLOYMENT-ISSUES.md, RELIABILITY-TRACKER.md, RELEASE-VERIFICATION.md)

---

## Dependency Graph

```
Task 1 (Backend endpoints) ──┐
                              ├──→ Task 4 (Frontend redesign)
Task 2 (Proxy routes) ───────┤
                              │
Task 3 (Client API) ─────────┘
                                    │
                                    ▼
                              Task 5 (Frontend tests)
                                    │
                                    ▼
                              Task 6 (Verification)
```

**Tasks 1, 2, 3 can run in parallel.** Task 4 depends on all three. Task 5 depends on Task 4. Task 6 is last.
