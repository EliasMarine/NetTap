# Tools Section Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a `/tools` section with 10 network analysis/utility tools, adding "Tools" to the sidebar nav with a card-grid index page.

**Architecture:** New daemon API module (`daemon/api/tools.py`) with 4 backend services (DNS Recon, MAC Lookup, Ping/Traceroute, SSL Cert). 3 frontend-only tools (Subnet Calculator, Port Reference, Base64/Hex Converter). TShark gets a page mounting existing components. CyberChef moves from `/system/cyberchef` to `/tools/cyberchef`. Tools index page links to all tools plus existing WHOIS/DNS lookup pages.

**Tech Stack:** Python/aiohttp (daemon), SvelteKit 5 with runes (web), asyncio.create_subprocess_exec (subprocess calls), pure JS math (frontend tools)

---

## Execution Strategy

This plan has high parallelism potential. Use agent teams:
- **Backend agents:** Tasks 1-6 (services + API routes + Docker)
- **Frontend API agent:** Tasks 7-8 (API client + proxy routes)
- **Frontend page agents:** Tasks 9-18 (tool pages + sidebar)
- **Mockup agent:** Task 19

Tasks 2-5 (backend services) are fully independent and can run in parallel.
Tasks 9-18 (frontend pages) are mostly independent and can run in parallel after Tasks 7-8.

---

## Task 1: Docker - Add system tools to daemon container

**Files:**
- Modify: `docker/Dockerfile.daemon:10-16`

Add `dnsutils` (dig), `traceroute`, `iputils-ping` to apt-get.

---

## Tasks 2-5: Backend services (parallel)

Each creates a service in `daemon/services/` with tests in `daemon/tests/`.

## Task 6: Backend API routes + server registration

Creates `daemon/api/tools.py` and modifies `daemon/api/server.py`.

## Tasks 7-8: Frontend API client + proxy routes

## Tasks 9-18: Frontend tool pages

## Task 19: Mockups

## Task 20: Integration testing
