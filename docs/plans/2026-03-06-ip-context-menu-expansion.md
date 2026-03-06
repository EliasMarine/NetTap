# IP Context Menu Expansion — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make every IP address across all NetTap pages interactive with a rich right-click context menu that includes lookup tools (WHOIS, DNS) with dedicated result pages, plus fix existing bugs.

**Architecture:** Extend the existing IPAddress + ContextMenu component system. Add daemon API endpoints for WHOIS and DNS lookups. Create new frontend pages at /lookup/whois/[ip] and /lookup/dns/[ip]. Add IPAddress component to the 3 pages that currently render IPs as plain text.

**Tech Stack:** Python aiohttp (daemon API), SvelteKit (frontend pages + proxy routes), Svelte 5 runes

---

## Task Overview

| # | Task | Track | Dependencies |
|---|------|-------|-------------|
| 1 | Add new icons to ContextMenu | Frontend | None |
| 2 | Fix IPAddress menu items + add new actions | Frontend | Task 1 |
| 3 | Create daemon lookup API (WHOIS + DNS) | Backend | None |
| 4 | Create SvelteKit proxy routes for lookups | Frontend | None |
| 5 | Create WHOIS lookup page | Frontend | Task 4 |
| 6 | Create DNS lookup page | Frontend | Task 4 |
| 7 | Add IPAddress to Device Inventory page | Frontend | None |
| 8 | Add IPAddress to Log Explorer page | Frontend | None |
| 9 | Add IP filter support to Alerts page/API | Full-stack | None |
| 10 | Update tests | Tests | Tasks 1-9 |

---

### Task 1: Add New Icons to ContextMenu

**Files:**
- Modify: `web/src/lib/components/ContextMenu.svelte` (iconPath function, ~line 124)

Add icon cases to the iconPath() switch for whois, dns, alert.
Update the icon type comment on line 16.

---

### Task 2: Fix IPAddress Menu Items + Add New Actions

**Files:**
- Modify: `web/src/lib/components/IPAddress.svelte` (menuItems, ~line 68)

Bug fix: Both "Filter from" and "Filter to" use identical URLs.
- "from" uses /connections?src_ip={ip}
- "to" uses /connections?dst_ip={ip}

New menu items: WHOIS lookup, DNS lookup, View alerts for this IP.

---

### Task 3: Create Daemon Lookup API (WHOIS + DNS)

**Files:**
- Create: `daemon/api/lookup.py`
- Modify: `daemon/main.py` (register routes)
- Modify: `docker/Dockerfile.daemon` (add whois package)

WHOIS endpoint: GET /api/lookup/whois/{ip}
- Uses asyncio.create_subprocess_exec for the whois command
- Parses raw output into structured fields
- 15 second timeout

DNS endpoint: GET /api/lookup/dns/{ip}
- Uses socket.gethostbyaddr() for reverse DNS
- Uses socket.getaddrinfo() for forward lookup
- Returns hostname, aliases, addresses

---

### Task 4: Create SvelteKit Proxy Routes for Lookups

**Files:**
- Create: `web/src/routes/api/lookup/whois/[ip]/+server.ts`
- Create: `web/src/routes/api/lookup/dns/[ip]/+server.ts`

Simple proxy pass-throughs to the daemon.

---

### Task 5: Create WHOIS Lookup Page

**Files:**
- Create: `web/src/routes/lookup/whois/[ip]/+page.svelte`

Layout: Back button, search bar, parsed fields card, raw output collapsible.
Follow the GeoIP page pattern.

---

### Task 6: Create DNS Lookup Page

**Files:**
- Create: `web/src/routes/lookup/dns/[ip]/+page.svelte`

Layout: Back button, search bar, reverse DNS card, forward DNS card.

---

### Task 7: Add IPAddress to Device Inventory Page

**Files:**
- Modify: `web/src/routes/devices/+page.svelte`

Replace plain text IPs with IPAddress component in:
- Table row IP cell (line 374)
- Expanded detail IP (line 409)
- Expanded connections dest IP (line 487)

---

### Task 8: Add IPAddress to Log Explorer Page

**Files:**
- Modify: `web/src/routes/logs/+page.svelte`

Add conditional rendering: if column is an IP_FIELD, use IPAddress component instead of plain text.

---

### Task 9: Add IP Filter Support to Alerts Page/API

**Backend:** Add optional ip query parameter to handle_alerts_list that filters on source.ip OR destination.ip.

**Frontend:** Read ip from URL search params, pass to getAlerts(), display active filter badge.

---

### Task 10: Update Tests

- IPAddress.test.ts — update menu items, fix for new actions
- ContextMenu.test.ts — add tests for new icon paths
- test_lookup_api.py — tests for WHOIS + DNS endpoints
- test_alerts_api.py — test IP filter param

---

## Parallel Agent Assignment

| Agent | Tasks | Description |
|-------|-------|-------------|
| agent-backend | 3 | Daemon lookup API + Dockerfile |
| agent-components | 1, 2 | ContextMenu icons + IPAddress menu fixes |
| agent-pages | 4, 5, 6 | Proxy routes + WHOIS/DNS lookup pages |
| agent-integration | 7, 8 | Add IPAddress to devices + logs pages |
| agent-alerts | 9 | Alerts IP filter (backend + frontend) |
| agent-tests | 10 | All test updates (runs after others) |
