# NetTap Comprehensive Build Plan

**Created:** 2026-02-25
**Status:** Approved
**Linear Issue:** NET-6

---

## Table of Contents

- [Current State Assessment](#current-state-assessment)
- [Phase Dependency Graph](#phase-dependency-graph)
- [Key Architecture Decisions](#key-architecture-decisions)
- [Phase 1: Core Infrastructure](#phase-1-core-infrastructure)
- [Phase 2: Storage Management](#phase-2-storage-management)
- [Phase 3: Onboarding UX](#phase-3-onboarding-ux)
- [Phase 4: Dashboard Polish](#phase-4-dashboard-polish)
- [Phase 5: Community Release](#phase-5-community-release)
- [Risk Matrix](#risk-matrix)
- [Total Effort Summary](#total-effort-summary)

---

## Current State Assessment

The repo is an early scaffold with 3 commits. Here is what exists and its maturity:

| Component | Maturity | Key Gap |
|-----------|----------|---------|
| Bridge script (`setup-bridge.sh`) | ~30% | No persistence, no rollback, no validation |
| Install script (`install.sh`) | ~15% | Malcolm deployment is a `TODO` |
| Python daemon | ~40% | `prune_oldest_indices()` is `NotImplementedError` |
| Docker Compose | ~50% | Needs Malcolm integration + health checks |
| Config files (Zeek/Suricata/ILM) | ~65% | ILM missing warm/cold tiers |
| Web UI | **0%** | Framework not chosen, directories empty |
| Grafana dashboards | **0%** | Empty placeholder dirs |
| Tests | **0%** | No tests of any kind exist |
| CI/CD | **0%** | No `.github/` directory |

### Detailed File-Level Audit

| File | Status | Completeness | Notes |
|------|--------|-------------|-------|
| `scripts/common.sh` | Scaffolded | ~40% | Has `log`, `error`, `require_root`, `check_interface_exists`, `check_command`, `load_env`. Missing: `warn` (non-fatal), retry logic, color output, cleanup traps, lock file management, DRY_RUN support |
| `scripts/bridge/setup-bridge.sh` | Scaffolded | ~30% | Creates bridge with `ip link` commands. Missing: persistence (netplan), rollback on failure, management interface config, connectivity validation, forwarding delay tuning, bridge-nf rules, idempotency |
| `scripts/install/install.sh` | Scaffolded | ~15% | Installs apt dependencies and calls bridge script. Malcolm deployment is a `TODO` comment. Missing: hardware validation, Malcolm clone/configure/pull, auth setup, systemd registration, post-install verification |
| `docker/docker-compose.yml` | Scaffolded | ~50% | Defines `nettap-storage-daemon` and `nettap-web` services. References `malcolm_default` external network. Needs health checks and Malcolm integration |
| `docker/Dockerfile.daemon` | Scaffolded | ~60% | Working but missing `requirements.txt` pip install, healthcheck directive, non-root user |
| `docker/Dockerfile.web` | Stub | ~5% | Two-stage build scaffold only; no actual web assets or nginx config |
| `config/opensearch/ilm-policy.json` | Scaffolded | ~60% | Has hot tier with rollover and 90-day delete. Missing: warm tier for Suricata (180 days), cold tier for PCAP (30 days) |
| `config/suricata/nettap.yaml` | Scaffolded | ~70% | Good af-packet config for `br0`, eve-log outputs. May need adjustment for Malcolm's container config |
| `config/zeek/nettap.zeek` | Scaffolded | ~70% | Good defaults: 30s rotation, JSON logs, protocol loaders |
| `daemon/main.py` | Scaffold | ~40% | Event loop running storage (300s) and SMART (3600s) checks. Lacks signal handling, graceful shutdown, HTTP API |
| `daemon/storage/manager.py` | Partial | ~35% | `RetentionConfig` and `check_disk_usage()` work. `prune_oldest_indices()` raises `NotImplementedError` |
| `daemon/smart/monitor.py` | Functional | ~65% | `smartctl -j` invocation correct. Missing: additional SMART metrics, SATA fallback, alerting integration |
| `.env.example` | Complete | ~80% | Good coverage of all configuration knobs |
| `web/wizard/.gitkeep` | Empty | 0% | No code |
| `web/dashboard/.gitkeep` | Empty | 0% | No code |
| `config/grafana/dashboards/.gitkeep` | Empty | 0% | No dashboard JSON |
| `config/grafana/provisioning/.gitkeep` | Empty | 0% | No provisioning YAML |

---

## Phase Dependency Graph

```
Phase 1: Core Infrastructure  (Weeks 1-4)
    |-- 1A: Bridge hardening ----------------------+
    |-- 1B: Malcolm integration (CRITICAL BLOCKER) |
    |-- 1C: Hardware validation -------------------+
                                                   |
                                                   v
Phase 2: Storage Management  (Weeks 3-5, overlaps with Phase 1)
    |-- 2A: ILM policies (hot/warm/cold)
    |-- 2B: Implement prune_oldest_indices()
    |-- 2C: SMART alerting pipeline
    |-- 2D: Compression tuning
                    |
         +----------+-----------+
         |                      |
         v                      v
Phase 3: Onboarding UX    Phase 4: Dashboard Polish    <-- PARALLEL
  (Weeks 5-8)               (Weeks 7-10)
         |                      |
         +----------+-----------+
                    |
                    v
Phase 5: Community Release  (Weeks 9-11)
```

**Critical Path:** Malcolm Integration -> StorageManager completion -> Web framework setup -> Setup wizard -> Install script finalization

**Parallelism Opportunities:**
- Phase 3 and Phase 4 can be developed concurrently (wizard vs dashboards have independent UI surfaces)
- Within Phase 1: bridge hardening (1A) and hardware validation (1C) can run parallel with Malcolm integration (1B)
- Within Phase 2: ILM policy work (2A) and SMART monitoring (2C) are independent

---

## Key Architecture Decisions

### 1. Malcolm Integration Strategy: Direct Container Images (Option C)

**Decision:** Build a standalone `docker-compose.yml` using Malcolm's published container images with NetTap's own orchestration, rather than scripting Malcolm's installer.

**Rationale:**
- Avoids the fragile approach of scripting Malcolm's interactive `install.py`
- Gives full control over container dependencies, ordering, and health checks
- Pin specific image tags for reproducibility
- Not beholden to Malcolm's install UX changes between versions

**Alternatives rejected:**
- Option A (Fork Malcolm's docker-compose): High maintenance burden, breaks with updates
- Option B (Script Malcolm's installer non-interactively): Fragile, requires reverse-engineering prompts

**Implementation:**
- Pin to Malcolm release `v26.02.0`
- Cherry-pick only needed containers: OpenSearch, Zeek, Suricata, Arkime, Logstash, Dashboards
- NetTap's `docker-compose.yml` becomes the single source of truth for all services
- Config overlays mounted as read-only volumes

### 2. Web Framework: SvelteKit with adapter-node

**Decision:** Use SvelteKit with TypeScript and `adapter-node` for the web UI.

| Factor | SvelteKit | Next.js | Express+React |
|--------|-----------|---------|---------------|
| Runtime memory | **40-80MB** | 150-300MB | 80-150MB |
| Client bundle size | **50-70% smaller** | React hydration overhead | Full React bundle |
| API routes | Built-in `+server.ts` | Built-in | Separate process |
| TypeScript | First-class | First-class | Manual setup |
| SSR + form actions | Native | Native | Manual |

**Rationale:**
- N100 has 16GB total. OpenSearch needs 4GB+, Malcolm services need ~6GB. Web UI must be frugal.
- Svelte compiles to vanilla JS with no runtime shipped to client. Dashboard loads < 3s on LAN.
- Built-in server routes eliminate need for a separate Express server.
- Form actions provide progressive enhancement for the setup wizard.
- `adapter-node` produces a standalone Node.js server for the Docker container.

**Architecture:**
```
web/
  src/
    routes/                 # SvelteKit file-based routing
      +layout.svelte        # Root layout with auth check
      +page.svelte          # Landing/redirect
      setup/                # Wizard routes
        +page.svelte
        steps/
      dashboard/            # Dashboard routes
        +page.svelte
        alerts/+page.svelte
        traffic/+page.svelte
        settings/+page.svelte
        health/+page.svelte
    lib/
      server/               # Server-only code
        opensearch.ts        # OpenSearch query client
        auth.ts              # JWT/auth logic
      components/            # Shared UI components
      types/                 # TypeScript interfaces
  svelte.config.js
  package.json
  tsconfig.json
```

### 3. API Layer: Embed HTTP Server in Python Daemon

**Decision:** Add an aiohttp HTTP server to the existing Python daemon process on port 8880. SvelteKit server routes proxy to it for system/storage/SMART data.

**Architecture:**
```
Browser --> SvelteKit (nettap-web container, port 443)
              |-- /api/traffic/*     --> OpenSearch :9200 (direct from SvelteKit server)
              |-- /api/alerts/*      --> OpenSearch :9200
              |-- /api/system/*      --> nettap-daemon :8880
              |-- /api/storage/*     --> nettap-daemon :8880
              |-- /api/smart/*       --> nettap-daemon :8880
              |-- /ws                --> WebSocket for real-time alerts
              +-- static assets (CSS, JS, images)
```

**Rationale:**
- Daemon already has access to storage/SMART data
- Consolidates two services into one container
- `aiohttp` is lightweight (unlike FastAPI which adds pydantic, uvicorn, starlette)
- HTTP server runs in asyncio alongside existing periodic loop

**Daemon API Endpoints:**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/storage/status` | GET | Disk usage, threshold, last prune time |
| `/api/storage/retention` | GET/PUT | Current retention config |
| `/api/smart/health` | GET | SSD SMART data |
| `/api/indices` | GET | OpenSearch index list with sizes |
| `/api/system/health` | GET | CPU, RAM, disk, uptime |

### 4. Testing Stack

| Layer | Framework | Why |
|-------|-----------|-----|
| Python daemon | pytest + pytest-cov + pytest-mock | Standard Python; daemon is pure Python |
| Shell scripts | bats-core | Structured test output for bash; works in CI |
| Web UI (unit) | Vitest + Svelte Testing Library | Fastest TS test runner; `.test.ts` pattern satisfies stop hook |
| Web UI (E2E) | Playwright | Cross-browser E2E; validates wizard flow |
| Bridge integration | Linux network namespaces + veth pairs | Test bridge in CI without physical hardware |
| Docker integration | Docker Compose test profile | Full stack validation |

### 5. Authentication: JWT with httpOnly Cookies

**Decision:** Simple session-based auth using JWT tokens stored in httpOnly cookies.

- Passwords hashed with argon2 (side-channel resistant, configurable memory cost)
- User store: JSON file in Docker volume (`/var/lib/nettap-web/auth.json`)
- JWT signed with server-generated secret (created at first setup)
- Token expires in 24 hours (configurable)
- Rate limiting: 5 login attempts per minute per IP
- SvelteKit `hooks.server.ts` validates JWT on every request
- Setup routes exempt from auth during first run only

### 6. Bridge Persistence: Netplan + Systemd

**Decision:** Use netplan YAML for bridge persistence and a systemd oneshot service for promiscuous mode.

- `setup-bridge.sh` for initial setup and validation (imperative)
- Generated `/etc/netplan/10-nettap-bridge.yaml` for persistence (declarative)
- `/etc/systemd/system/nettap-bridge-promisc.service` for promisc mode (netplan can't set this)
- `/etc/sysctl.d/99-nettap-bridge.conf` for bridge-nf-call settings

---

## Phase 1: Core Infrastructure

**Timeline:** Weeks 1-4
**Estimated Effort:** 50-70 hours
**Status:** COMPLETE (merged to develop via PRs #1, #2, #3)

### Task Breakdown

| # | Task | Size | Week | Status | Files |
|---|------|------|------|--------|-------|
| 1.1 | Enhance `common.sh` utility library | S | 1 | [x] Done (PR #1) | `scripts/common.sh` |
| 1.2 | Create hardware validation script | M | 1 | [x] Done (PR #1) | `scripts/install/validate-hardware.sh` |
| 1.3 | Bridge pre-flight validation | S | 1 | [x] Done (PR #1) | `scripts/bridge/setup-bridge.sh` |
| 1.4 | Bridge performance tuning | S | 1 | [x] Done (PR #1) | `scripts/bridge/setup-bridge.sh` |
| 1.5 | Bridge persistence (netplan + systemd) | M | 2 | [x] Done (PR #1) | `setup-bridge.sh`, netplan template, systemd unit, sysctl conf |
| 1.6 | Bridge rollback and teardown | M | 2 | [x] Done (PR #1) | `scripts/bridge/setup-bridge.sh` |
| 1.7 | Bridge connectivity validation | S | 2 | [x] Done (PR #1) | `scripts/bridge/setup-bridge.sh` |
| 1.8 | Management interface support | S | 2 | [x] Done (PR #1) | `scripts/bridge/setup-bridge.sh` |
| 1.9 | Pin Malcolm release, document images | S | 3 | [x] Done (PR #2) | `scripts/install/malcolm-versions.conf` |
| 1.10 | Build standalone docker-compose with Malcolm | L | 3 | [x] Done (PR #2) | `docker/docker-compose.yml` |
| 1.11 | Malcolm config patching utility | M | 3 | [x] Done (PR #2) | `scripts/install/malcolm-config.sh` |
| 1.12 | Malcolm deployment script | L | 3 | [x] Done (PR #2) | `scripts/install/deploy-malcolm.sh` |
| 1.13 | Expand install.sh orchestrator | L | 4 | [x] Done (PR #3) | `scripts/install/install.sh` |
| 1.14 | Create systemd service unit | S | 4 | [x] Done (PR #3) | `scripts/install/nettap.service` |
| 1.15 | Configure mDNS/avahi for `nettap.local` | S | 4 | [x] Done (PR #3) | `scripts/install/install.sh` |
| 1.16 | Network namespace test harness | M | 4 | [x] Done (PR #3) | `tests/shell/test-bridge-namespaces.sh` |
| 1.17 | Dry-run test suite for all scripts | M | 4 | [x] Done (PR #3) | `tests/shell/test-phase1.sh` |
| 1.18 | Update `.env.example` with new variables | S | 4 | [x] Done (PR #3) | `.env.example` |

### Task Details

#### 1.1 Enhance `common.sh`
Add: `warn()` non-fatal function, `cleanup_trap()` for signal handling, `retry()` for flaky operations, `check_ubuntu()`, `check_arch()`, color output toggle, lock file (`/var/run/nettap.lock`), `DRY_RUN` support.

#### 1.2 Hardware Validation Script
Checks needed:
- CPU: x86_64 architecture, 4+ cores recommended
- RAM: minimum 8GB required, 16GB recommended
- Disk: minimum 512GB, prefer NVMe (check `/dev/nvme*`)
- NICs: minimum 2 physical NICs (filter out lo, docker, br, veth)
- NIC drivers: flag Intel igc/igb as optimal, warn on Realtek
- NIC speed capability via ethtool
- Kernel bridge module availability
- Virtualization detection (warn about performance differences)

#### 1.3-1.8 Bridge Script Enhancements

**Pre-flight validation (1.3):**
- Verify NICs not already bridged (`/sys/class/net/$iface/master`)
- Verify no conflicting IP addresses on data-path NICs
- Check kernel bridge module (`modprobe bridge`)
- Detect NetworkManager conflicts
- Validate WAN != LAN

**Performance tuning (1.4):**
```bash
# Disable bridge netfilter (avoid iptables overhead)
sysctl -w net.bridge.bridge-nf-call-iptables=0
sysctl -w net.bridge.bridge-nf-call-ip6tables=0
# Set forwarding delay to 0
ip link set br0 type bridge forward_delay 0
# Disable multicast snooping
ip link set br0 type bridge mcast_snooping 0
# Increase NIC ring buffers, disable hardware offloading
ethtool -G $iface rx 4096
ethtool -K $iface tso off gso off gro off lro off
```

**Persistence (1.5):** Generate `/etc/netplan/10-nettap-bridge.yaml` and systemd promisc service.

**Rollback (1.6):** Trap-based ERR rollback using a stack of undo commands. `--teardown` flag to cleanly remove everything.

**New flags:** `--persist`, `--no-persist`, `--validate-only`, `--teardown`, `--detect`, `--mgmt`, `--dry-run`, `-v/--verbose`

#### 1.9-1.12 Malcolm Integration

**Version pin (1.9):** Pin to Malcolm `v26.02.0`. Create `malcolm-versions.conf`.

**Docker Compose rewrite (1.10):** Use Malcolm's published container images directly. Cherry-pick: OpenSearch, Zeek, Suricata, Arkime, Logstash, Dashboards. Add health checks, dependency ordering.

**Config patching (1.11):**
- Set `PCAP_IFACE=br0`
- Enable live capture for Zeek and Suricata
- Set OpenSearch JVM heap from `.env`
- Apply NetTap config overlays (mount Zeek/Suricata configs)

**Deploy script (1.12):** Full sequence: clone by tag, configure, patch env, pull images, start, wait for OpenSearch readiness, apply ILM policy, verify.

#### 1.13 Install Script Expansion

Full step sequence:
1. Pre-flight checks (root, Ubuntu, architecture)
2. Hardware validation
3. System dependencies (apt)
4. Docker configuration
5. Network bridge setup
6. Malcolm deployment
7. NetTap services startup
8. Systemd service registration
9. mDNS/avahi configuration
10. Post-install verification (bridge, containers, OpenSearch health, dashboard accessibility)

---

## Phase 2: Storage Management

**Timeline:** Weeks 3-5 (overlaps with late Phase 1)
**Estimated Effort:** 40-55 hours
**Prerequisite:** OpenSearch running (from Phase 1 task 1.10)
**Status:** COMPLETE (merged to develop via PR #4)

### Task Breakdown

| # | Task | Size | Week | Status | Files |
|---|------|------|------|--------|-------|
| 2.1 | Create `requirements.txt` + `pyproject.toml` | S | 3 | [x] Done (PR #4) | `daemon/requirements.txt`, `daemon/pyproject.toml` |
| 2.2 | Implement `prune_oldest_indices()` | M | 3 | [x] Done (PR #4) | `daemon/storage/manager.py` |
| 2.3 | Expand ILM policies (warm + cold tiers) | S | 3 | [x] Done (PR #4) | `config/opensearch/ilm-policy.json` |
| 2.4 | ILM policy auto-application at startup | S | 3 | [x] Done (PR #4) | `daemon/storage/ilm.py` |
| 2.5 | Tiered pruning logic (cold -> warm -> hot) | M | 4 | [x] Done (PR #4) | `daemon/storage/manager.py` |
| 2.6 | Expand SMART metrics (TBW, temp, SATA fallback) | M | 4 | [x] Done (PR #4) | `daemon/smart/monitor.py` |
| 2.7 | SMART alerting output (webhook/log) | S | 4 | [x] Done (PR #4) | `daemon/smart/monitor.py` |
| 2.8 | Compression config for Zeek/Suricata | S | 4 | [x] Done (PR #4) | `config/zeek/nettap.zeek`, `config/suricata/nettap.yaml` |
| 2.9 | Daemon signal handling + graceful shutdown | S | 4 | [x] Done (PR #4) | `daemon/main.py` |
| 2.10 | Add daemon HTTP API (aiohttp) | M | 5 | [x] Done (PR #4) | `daemon/api/server.py`, `daemon/main.py` |
| 2.11 | Write pytest suite for daemon | M | 5 | [x] Done (PR #4) | `daemon/tests/` (55 tests) |
| 2.12 | Integration test with real OpenSearch | M | 5 | [ ] Deferred | Requires running OpenSearch instance |

### Task Details

#### 2.2 Implement `prune_oldest_indices()`

Use `opensearch-py` client library. Logic:
1. Query `GET /_cat/indices?format=json` to list all indices
2. Parse index names for date components (e.g., `zeek-conn-2026.02.25`)
3. Sort by date, oldest first
4. Delete oldest indices until disk usage drops below threshold
5. Respect tier priority: delete cold (arkime-*) first, then warm (suricata-*), then hot (zeek-*)

#### 2.3 ILM Policy Expansion

Current state: Only `zeek-*` with 90-day hot-to-delete.

Add three separate policies:
- **nettap-hot-policy** (zeek-*): rollover at 10GB or 1 day, delete after 90 days
- **nettap-warm-policy** (suricata-*): rollover at 5GB or 1 day, force_merge to 1 segment, read_only, delete after 180 days
- **nettap-cold-policy** (arkime-*): rollover at 20GB or 1 day, delete after 30 days

#### 2.10 Daemon HTTP API

Add `aiohttp` web server running alongside the existing periodic loop:

```python
# In daemon/main.py, run both concurrently
async def main():
    # Start HTTP API server
    api_task = asyncio.create_task(start_api_server(port=8880))
    # Start periodic monitoring loop
    monitor_task = asyncio.create_task(monitoring_loop())
    await asyncio.gather(api_task, monitor_task)
```

Endpoints: `/api/storage/status`, `/api/storage/retention`, `/api/smart/health`, `/api/indices`, `/api/system/health`

#### 2.11 Pytest Test Suite

Key test files:
- `daemon/tests/test_storage_manager.py`: disk usage checks, pruning logic, retention config
- `daemon/tests/test_smart_monitor.py`: smartctl parsing, threshold checks, SATA fallback
- `daemon/tests/test_main.py`: env var parsing, component initialization
- `daemon/tests/conftest.py`: shared fixtures (mock OpenSearch responses, temp dirs)

---

## Phase 3: Onboarding UX

**Timeline:** Weeks 5-8
**Estimated Effort:** 60-80 hours
**Prerequisite:** Phase 2 core tasks complete (daemon API running)
**Status:** COMPLETE (PR #5, pending merge to develop)

### Task Breakdown

| # | Task | Size | Week | Status | Files |
|---|------|------|------|--------|-------|
| 3.1 | Initialize SvelteKit project | S | 5 | [x] Done (PR #5) | `web/package.json`, `web/svelte.config.js`, etc. |
| 3.2 | Update Dockerfile.web for SvelteKit | S | 5 | [x] Done (PR #5) | `docker/Dockerfile.web` |
| 3.3 | Base layout + CSS design system | M | 5 | [x] Done (PR #5) | `web/src/routes/+layout.svelte`, `global.css` |
| 3.4 | Auth backend (argon2, JWT, rate limiting) | M | 5 | [x] Done (PR #5) | `web/src/lib/server/auth.ts` |
| 3.5 | Login page frontend | S | 6 | [x] Done (PR #5) | `web/src/routes/login/+page.svelte` |
| 3.6 | TLS self-signed cert generation | S | 6 | [x] Done (PR #5) | `scripts/generate-cert.sh` |
| 3.7 | NIC detection API | M | 6 | [x] Done (PR #5) | `web/src/routes/api/setup/nics/+server.ts` |
| 3.8 | Bridge verification API | M | 6 | [x] Done (PR #5) | `web/src/routes/api/setup/bridge/+server.ts` |
| 3.9 | Storage configuration API | S | 6 | [x] Done (PR #5) | `web/src/routes/api/setup/storage/+server.ts` |
| 3.10 | Admin account creation API | S | 7 | [x] Done (PR #5) | `web/src/routes/setup/+page.server.ts` |
| 3.11 | Malcolm health check API | M | 7 | [x] Done (PR #5) | `web/src/routes/api/health/+server.ts` |
| 3.12 | **Setup wizard UI (all 5 steps)** | L | 7 | [x] Done (PR #5) | `web/src/routes/setup/+page.svelte` (1745 lines) |
| 3.13 | First-run detection and routing | S | 7 | [x] Done (PR #5) | `web/src/hooks.server.ts` |
| 3.14 | Admin settings page | M | 8 | [x] Done (PR #5) | `web/src/routes/settings/+page.svelte` |
| 3.15 | Nginx reverse proxy config | S | 8 | [x] Done (PR #5) | `docker/nginx.conf`, `scripts/generate-cert.sh` |
| 3.16 | Vitest setup + component tests | M | 8 | [x] Done (PR #5) | 5 test files, 48 tests passing |

### Additional Deliverables (beyond original plan)

| Feature | Status | Files |
|---------|--------|-------|
| TShark containerized packet analysis | [x] Done | `daemon/services/tshark_service.py`, `daemon/api/tshark.py`, `docker/Dockerfile.tshark` |
| TShark frontend components (4) | [x] Done | `FilterInput`, `PacketTable`, `ProtocolTree`, `AnalysisPanel` |
| CyberChef containerized data toolkit | [x] Done | `daemon/services/cyberchef_service.py`, `daemon/api/cyberchef.py`, `docker/Dockerfile.cyberchef` |
| CyberChef frontend page | [x] Done | `web/src/routes/system/cyberchef/+page.svelte` |
| Connections page (TShark analysis) | [x] Done | `web/src/routes/connections/+page.svelte` |
| Alerts page with severity filters | [x] Done | `web/src/routes/alerts/+page.svelte` |
| System health page | [x] Done | `web/src/routes/system/+page.svelte` |
| 15 SvelteKit proxy routes | [x] Done | `web/src/routes/api/` |
| GPL compliance documentation | [x] Done | `THIRD-PARTY-LICENSES.md`, `docker/licenses/GPL-2.0.txt` |
| Daemon TShark tests (25) | [x] Done | `daemon/tests/test_tshark_service.py` |
| Daemon CyberChef tests (18) | [x] Done | `daemon/tests/test_cyberchef_service.py` |

### Setup Wizard Flow

```
Step 1: Welcome        --> Step 2: NIC Detection  --> Step 3: Bridge Verification
Step 4: Storage Config  --> Step 5: Admin Account  --> [Complete --> Dashboard]
```

**Step 1: Welcome Screen**
- Product introduction, hardware requirements check
- Backend: `GET /api/setup/status` returns `{ firstRun: boolean, currentStep: number }`

**Step 2: NIC Detection**
- API: `GET /api/setup/nics` reads `/sys/class/net/*/` for each physical interface
- Returns: name, MAC, driver, speed, link state, carrier (cable connected)
- UI: Two dropdown selectors for WAN and LAN, visual diagram of `Modem <-- [NetTap] --> Router`
- Auto-suggest based on link state

**Step 3: Bridge Verification**
- API: `POST /api/setup/bridge` triggers `setup-bridge.sh`
- API: `GET /api/setup/bridge/status` checks sysfs for bridge state
- UI: Progress indicator with green checkmarks per validation step

**Step 4: Storage Configuration**
- Sliders for retention per tier with plain-language labels
- Disk usage estimate based on detected disk size
- Emergency pruning threshold slider (70-90%)

**Step 5: Admin Account Creation**
- Username (default "admin"), password with strength meter
- Hashed with argon2, stored in Docker volume

**Post-Setup: Malcolm Health Verification**
- Checks: OpenSearch cluster health, Zeek/Suricata/Arkime container status
- Green/yellow/red indicators per service

### REST API Design

#### Traffic Endpoints (SvelteKit -> OpenSearch)

```
GET  /api/traffic/summary?from=...&to=...
GET  /api/traffic/top-talkers?from=...&to=...&limit=20
GET  /api/traffic/top-destinations?from=...&to=...&limit=20
GET  /api/traffic/protocols?from=...&to=...
GET  /api/traffic/bandwidth?from=...&to=...&interval=5m
GET  /api/traffic/connections?from=...&to=...&page=1&size=50&q=...
```

#### Alert Endpoints

```
GET  /api/alerts?from=...&to=...&severity=1,2&page=1&size=50
GET  /api/alerts/count?from=...&to=...
GET  /api/alerts/:id
POST /api/alerts/:id/acknowledge
```

#### System Endpoints

```
GET  /api/system/health        (CPU, RAM, disk, NIC drops, uptime)
GET  /api/system/storage       (proxy from daemon)
GET  /api/system/services      (Docker container status)
PUT  /api/system/storage       (update retention config)
```

#### Auth Endpoints

```
POST /api/auth/login           (username, password -> JWT httpOnly cookie)
POST /api/auth/logout
GET  /api/auth/me
PUT  /api/auth/password
```

#### Setup Endpoints

```
GET  /api/setup/status
GET  /api/setup/nics
POST /api/setup/nics
POST /api/setup/bridge
GET  /api/setup/bridge/status
GET  /api/setup/storage/defaults
POST /api/setup/storage
POST /api/setup/admin
GET  /api/health/malcolm
```

---

## Phase 4: Dashboard Polish

**Timeline:** Weeks 7-10 (parallel with late Phase 3)
**Estimated Effort:** 80-100 hours
**Prerequisite:** SvelteKit project initialized, API layer functional
**Status:** COMPLETE (PR #7, pending merge to develop)

### Task Breakdown

| # | Task | Size | Week | Status | Files |
|---|------|------|------|--------|-------|
| 4.1 | Traffic API endpoints (OpenSearch queries) | M | 7 | [x] Done (PR #7) | `daemon/api/traffic.py`, `web/src/routes/api/traffic/`, `web/src/lib/api/traffic.ts` |
| 4.2 | Alert API endpoints (OpenSearch queries) | M | 7 | [x] Done (PR #7) | `daemon/api/alerts.py`, `web/src/routes/api/alerts/`, `web/src/lib/api/alerts.ts` |
| 4.3 | System health API endpoints | S | 7 | [x] Done (Phase 3) | `web/src/routes/api/system/health/+server.ts` |
| 4.4 | **Dashboard home page** (live stats/charts) | L | 8 | [x] Done (PR #7) | `web/src/routes/+page.svelte`, SVG chart components |
| 4.5 | Connections explorer page | M | 8 | [x] Done (Phase 3) | `web/src/routes/connections/+page.svelte` (TShark analysis) |
| 4.6 | Alerts page with severity filters | M | 8 | [x] Done (Phase 3) | `web/src/routes/alerts/+page.svelte` |
| 4.7 | WebSocket real-time alert push | M | 9 | [~] Partial — NotificationBell with polling (PR #7) | `web/src/lib/components/NotificationBell.svelte` |
| 4.8 | Add Grafana to Docker Compose | S | 7 | [x] Done (PR #7) | `docker/docker-compose.yml` |
| 4.9 | Grafana: Network Overview dashboard | L | 8 | [x] Done (PR #7) | `config/grafana/dashboards/network-overview.json` |
| 4.10 | Grafana: GeoIP World Map dashboard | M | 9 | [x] Done (PR #7) | `config/grafana/dashboards/geoip-map.json` |
| 4.11 | Grafana: Bandwidth Trending dashboard | M | 9 | [x] Done (PR #7) | `config/grafana/dashboards/bandwidth-trending.json` |
| 4.12 | Grafana: Security Alerts dashboard | M | 9 | [x] Done (PR #7) | `config/grafana/dashboards/security-alerts.json` |
| 4.13 | Grafana: System Health dashboard | M | 10 | [x] Done (PR #7) | `config/grafana/dashboards/system-health.json` |
| 4.14 | Notification system (email/webhook) | M | 9 | [x] Done (PR #7) | `web/src/lib/server/notifications.ts` |
| 4.15 | Notification settings page | S | 10 | [x] Done (PR #7) | `web/src/routes/settings/notifications/+page.svelte` |
| 4.16 | System health page in web UI | M | 10 | [x] Done (Phase 3) | `web/src/routes/system/+page.svelte` |
| 4.17 | Grafana embedding/linking | S | 10 | [x] Done (PR #7) | nginx proxy + compose config |
| 4.18 | E2E integration testing (Playwright) | L | 10 | [ ] Todo | Playwright tests |

### Dashboard Home Page Components

- Total bandwidth stat card (24h)
- Active connections stat card
- Active alerts stat card (with severity coloring)
- Bandwidth time-series chart (in/out)
- Protocol distribution pie chart
- Top 10 source IPs bar chart
- Top 10 destinations bar chart
- Recent connections table
- Auto-refresh every 30 seconds

### Grafana Dashboards

**Dashboard 1: Network Overview (Home)**
| Panel | Type | Query |
|-------|------|-------|
| Total Bandwidth (24h) | Stat | `sum(orig_bytes + resp_bytes)` on `zeek-conn-*` |
| Active Connections | Stat | `count` on `zeek-conn-*` where `ts > now-5m` |
| Active Alerts | Stat | `count` on `suricata-*` where `timestamp > now-24h` |
| Bandwidth Over Time | Time Series | `date_histogram` on `ts`, `sum(orig_bytes)` vs `sum(resp_bytes)` |
| Protocol Distribution | Pie Chart | `terms` aggregation on `service` |
| Top 10 Source IPs | Bar Gauge | `terms` on `id.orig_h`, `sum(bytes)` |
| Top 10 Destinations | Bar Gauge | `terms` on `id.resp_h`, `sum(bytes)` |
| Recent Connections | Table | Last 50 entries from `zeek-conn-*` |

**Dashboard 2: GeoIP World Map**
| Panel | Type | Query |
|-------|------|-------|
| Outbound Connection Map | Geomap | `terms` on `destination.geo.location` |
| Top Countries | Pie Chart | `terms` on `destination.geo.country_name` |
| Top ASNs | Bar Gauge | `terms` on `destination.as.organization.name` |
| Connections by Country | Table | `terms` on country with count + bytes |

**Dashboard 3: Bandwidth Trending**
| Panel | Type | Query |
|-------|------|-------|
| Bandwidth (1h intervals) | Time Series | `date_histogram(1h)`, `sum(bytes)` |
| Peak vs Average | Stat pair | `max_bucket` vs `avg_bucket` |
| Bandwidth by Protocol | Stacked Time Series | `date_histogram` + `terms` on `service` |
| Top Talkers Over Time | Time Series | `date_histogram` + `terms` on `id.orig_h` (top 5) |
| Daily Transfer Totals | Bar Chart | `date_histogram(1d)`, `sum(bytes)` |

**Dashboard 4: Security Alerts**
| Panel | Type | Query |
|-------|------|-------|
| Alert Count (24h) | Stat | `count` on `suricata-*` |
| Alerts by Severity | Pie Chart | `terms` on `alert.severity` |
| Alert Trend | Time Series | `date_histogram`, `count` |
| Top Signatures | Table | `terms` on `alert.signature` |
| Alert Sources | Bar Gauge | `terms` on `src_ip` |
| Alert Destinations | Bar Gauge | `terms` on `dest_ip` |

**Dashboard 5: System Health**
| Panel | Type | Source |
|-------|------|-------|
| CPU Usage | Gauge | daemon `/api/system/health` |
| RAM Usage | Gauge | daemon `/api/system/health` |
| Disk Usage | Gauge | daemon `/api/storage/status` |
| SSD Health | Gauge | daemon `/api/smart/health` |
| NIC Statistics | Table | daemon `/api/system/nics` |
| Service Status | Status map | Docker container status |

### Grafana Provisioning

```yaml
# config/grafana/provisioning/datasources.yaml
apiVersion: 1
datasources:
  - name: OpenSearch
    type: grafana-opensearch-datasource
    access: proxy
    url: http://opensearch:9200
    database: "zeek-*"
    jsonData:
      timeField: "ts"
      version: "2.11.0"
      flavor: "opensearch"
    isDefault: true
  - name: OpenSearch-Suricata
    type: grafana-opensearch-datasource
    access: proxy
    url: http://opensearch:9200
    database: "suricata-*"
    jsonData:
      timeField: "timestamp"
```

### Notification System Architecture

```
Suricata alert --> OpenSearch suricata-* index
    |
    v
[Alert Poller] (SvelteKit server, polls every 5s)
    |-- Filter by severity threshold
    |-- Deduplicate (LRU cache, 5-min window per signature+src+dest)
    |
    v
[Dispatcher]
    |-- Email (nodemailer, SMTP from .env)
    |-- Webhook (POST JSON to configured URL)
    |-- WebSocket (push to connected browsers)
```

Webhook payload includes: alert signature, severity, source/dest IPs, GeoIP data, timestamp, appliance hostname.

Deduplication: In-memory LRU cache keyed by `${signature_id}:${src_ip}:${dest_ip}`. Skip if notified within past 5 minutes.

---

## Phase 5: Community Release

**Timeline:** Weeks 9-11
**Estimated Effort:** 50-70 hours

### CI/CD Pipeline (GitHub Actions)

| Workflow | Trigger | Jobs |
|----------|---------|------|
| `ci.yml` | Push, PR | shellcheck, ruff, eslint/typecheck, pytest, bats, vitest, docker build |
| `integration.yml` | PR to main | Spin up OpenSearch, run integration tests |
| `release.yml` | Tag `v*.*.*` | Build + push Docker images to GHCR, create GitHub Release |
| `security.yml` | Weekly + PR | pip-audit, npm audit, Trivy container scan, CodeQL |
| `docs.yml` | Push to main (docs/**) | Deploy MkDocs to GitHub Pages |
| `stale.yml` | Daily cron | Mark stale issues/PRs after 30 days |

### Documentation (MkDocs Material -> GitHub Pages)

```
docs/
  index.md                          # Landing page
  getting-started/
    requirements.md                 # Hardware + OS requirements
    hardware-guide.md               # Compatibility list with tested models
    installation.md                 # Step-by-step install guide
    first-run-wizard.md             # Wizard walkthrough
    quick-start.md                  # 5-minute quick start
  user-guide/
    dashboard-overview.md           # Panel-by-panel explanation
    alerts.md                       # Managing Suricata alerts
    traffic-analysis.md             # Zeek logs + Arkime investigation
    storage-management.md           # Retention policies
    notifications.md                # Email/webhook setup
    siem-forwarding.md              # Logstash/syslog export
  admin-guide/
    configuration.md                # .env reference
    updating.md                     # Update process
    backup-restore.md               # OpenSearch backup
    tls-certificates.md             # HTTPS configuration
    performance-tuning.md           # JVM, Zeek threads, kernel params
    troubleshooting.md              # Common issues + diagnostics
  developer-guide/
    architecture.md                 # System architecture deep-dive
    contributing.md                 # How to contribute
    dev-setup.md                    # Development environment
    testing.md                      # Running tests locally
    release-process.md              # How releases work
    api-reference.md                # REST API docs
  reference/
    env-reference.md                # Annotated .env reference
    cli-reference.md                # All scripts and flags
    config-files.md                 # Zeek/Suricata/ILM config reference
    hardware-compat.md              # Community-tested hardware
```

### Community Infrastructure

**Discord Server:** NetTap Community
- Categories: General, Support, Development, Showcase
- Channels: #announcements, #installation-help, #hardware, #troubleshooting, #dev-discussion, #pull-requests, #deployments
- Roles: @Maintainer, @Contributor, @Community
- Bots: GitHub webhook for #pull-requests and #ci-builds

**GitHub Templates:**
- Bug report (YAML form): description, expected behavior, steps, version, hardware, logs
- Feature request: motivation, proposed solution, alternatives
- Hardware report: model, specs, NIC chipset, performance observations, config tweaks

**Files to create:**
- `CONTRIBUTING.md` -- dev workflow, commit conventions, PR process, code style
- `CODE_OF_CONDUCT.md` -- Contributor Covenant v2.1
- `SECURITY.md` -- vulnerability reporting, supported versions
- `.github/CODEOWNERS`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/dependabot.yml`
- `cliff.toml` -- changelog automation with git-cliff

### Release Engineering

- **Versioning:** SemVer (`v1.0.0`, `v1.0.1`, `v1.1.0`, etc.)
- **Pre-release:** `v1.0.0-alpha.1`, `v1.0.0-beta.1`, `v1.0.0-rc.1`
- **Docker tags:** `ghcr.io/eliasmarine/nettap-daemon:v1.0.0`, `:v1.0`, `:v1`, `:latest`
- **Commit convention:** Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `ci:`)
- **Changelog:** Auto-generated by git-cliff from commit history
- **Branch protection:** Require PR review, CI pass, up-to-date branch, no force push

### Security Hardening

- Non-root user in Dockerfiles (`USER nettap`)
- Pin base images to SHA digests
- `scripts/generate-secrets.sh` for random password generation
- `gitleaks` scan for secrets in git history
- UFW rules: HTTPS on management interface only
- Disable SSH password auth, require key-based
- Container capabilities: `--cap-drop=ALL --cap-add=NET_RAW` for Suricata
- Automatic security updates (`unattended-upgrades`)
- Content Security Policy headers on dashboard

### Launch Checklist

**Code Completeness:**
- [ ] All Phase 1-4 features implemented and merged
- [ ] `prune_oldest_indices()` fully implemented
- [ ] Web UI (wizard + dashboard) functional
- [ ] `install.sh` handles Malcolm deployment
- [ ] All TODOs resolved or converted to issues

**Testing:**
- [ ] All unit tests passing in CI
- [ ] Integration test with full Docker stack passing
- [ ] Manual E2E install on reference hardware (N100)
- [ ] Bridge verified at 500Mbps sustained, zero packet loss
- [ ] Dashboard loads < 3s on LAN
- [ ] Suricata alerts surface < 10s
- [ ] Storage daemon correctly prunes at 80% threshold
- [ ] Setup wizard completes from scratch

**Security:**
- [ ] Container images scanned, no CRITICAL/HIGH CVEs
- [ ] No hardcoded secrets in codebase
- [ ] Dashboard requires authentication
- [ ] Management interface isolated from capture bridge

**Documentation:**
- [ ] Docs site deployed to GitHub Pages
- [ ] Installation guide complete
- [ ] Hardware compatibility list seeded (3+ models)
- [ ] Troubleshooting guide covers top 10 failures

**Community:**
- [ ] Discord server live with channel structure
- [ ] Issue templates and PR template in place
- [ ] CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md added

**Launch Day:**
- [ ] Blog post (dev.to or personal)
- [ ] Reddit: r/homelab, r/netsec, r/selfhosted
- [ ] Hacker News: Show HN
- [ ] Twitter/X, LinkedIn
- [ ] Monitor Discord and GitHub Issues

---

## Phase 4B: SIEM-Inspired Features (Must-Have + Should-Have)

**Timeline:** After Phase 4, before Phase 5
**Estimated Effort:** 100-140 hours
**Reference:** `plans/siem-features-gameplan.md` for full implementation details
**Status:** TODO

### Sprint 1: Data Foundation (Group A)

| # | Task | Size | Status | Files |
|---|------|------|--------|-------|
| 4B.1 | Device Inventory API (auto-discovery from DHCP/ARP/DNS/JA3) | L | [x] Done | `daemon/api/devices.py`, `daemon/services/device_fingerprint.py`, `daemon/data/oui.txt` (855 entries) |
| 4B.2 | Traffic Categorization API (protocol → human categories) | M | [x] Done | `daemon/services/traffic_classifier.py`, `daemon/api/traffic.py` (+categories endpoint) |
| 4B.3 | Alert Description Enrichment (Suricata SID → plain English) | M | [x] Done | `daemon/services/alert_enrichment.py`, `daemon/data/suricata_descriptions.json` (55 SIDs) |
| 4B.4 | GeoIP Lookup Service (MaxMind GeoLite2 + fallback) | M | [x] Done | `daemon/services/geoip_service.py`, `daemon/api/geoip.py` (26 well-known IPs) |
| 4B.5 | Device Inventory API tests | M | [x] Done | `test_devices_api.py` (22 tests), `test_device_fingerprint.py` (24 tests) |
| 4B.6 | Traffic Classifier + GeoIP tests | M | [x] Done | `test_traffic_classifier.py` (21 tests), `test_geoip_service.py` (37 tests), `test_geoip_api.py` (17 tests) |
| 4B.7 | Alert Enrichment tests | S | [x] Done | `test_alert_enrichment.py` (26 tests) |
| 4B.8 | Web API clients (devices, geoip) + tests | M | [x] Done | `devices.ts` + `devices.test.ts` (12), `geoip.ts` + `geoip.test.ts` (12), `traffic.ts` extended (3) |

### Sprint 2: Core UI Features (Group B)

| # | Task | Size | Status | Files |
|---|------|------|--------|-------|
| 4B.9 | Device Inventory page (/devices) | L | [ ] Todo | `web/src/routes/devices/+page.svelte` |
| 4B.10 | Per-Device Activity page (/devices/[ip]) | L | [ ] Todo | `web/src/routes/devices/[ip]/+page.svelte` |
| 4B.11 | Alert-to-Detail Pivot panel | M | [ ] Todo | `web/src/lib/components/AlertDetailPanel.svelte` |
| 4B.12 | Right-Click Context Menus (IP, domain, port) | M | [ ] Todo | `web/src/lib/components/ContextMenu.svelte`, `IPAddress.svelte` |
| 4B.13 | Enhanced Hero Dashboard (big numbers, trends) | M | [ ] Todo | `web/src/routes/+page.svelte` (rewrite) |
| 4B.14 | Dashboard Template Variables (device/time/protocol filter bar) | M | [ ] Todo | `web/src/lib/components/DashboardFilters.svelte` |
| 4B.15 | Threshold color utility + systematic audit | S | [ ] Todo | `web/src/lib/utils/thresholds.ts` |
| 4B.16 | Component tests for B9-B14 | M | [ ] Todo | 6+ test files |

### Sprint 3: Intelligence Layer (Group C)

| # | Task | Size | Status | Files |
|---|------|------|--------|-------|
| 4B.17 | Device Risk Scoring (0-100 per device) | M | [ ] Todo | `daemon/services/risk_scoring.py` |
| 4B.18 | New Device Alerts (baseline + notifications) | M | [ ] Todo | `daemon/services/device_baseline.py` |
| 4B.19 | Internet Health Monitor (latency/DNS/packet loss) | M | [ ] Todo | `daemon/services/internet_health.py` |
| 4B.20 | Investigation Bookmarks/Notes (lightweight case mgmt) | M | [ ] Todo | `daemon/api/investigations.py`, `web/src/routes/investigations/+page.svelte` |
| 4B.21 | Risk scoring + device baseline tests | M | [ ] Todo | `daemon/tests/test_risk_scoring.py`, `test_device_baseline.py` |
| 4B.22 | Internet health + investigations tests | M | [ ] Todo | `daemon/tests/test_internet_health.py`, `test_investigations.py` |
| 4B.23 | Web tests for C features | M | [ ] Todo | API client + component tests |

### Sprint 4: Visualizations & Polish (Group D)

| # | Task | Size | Status | Files |
|---|------|------|--------|-------|
| 4B.24 | Sankey Traffic Flow Diagram (SVG) | L | [ ] Todo | `web/src/lib/components/charts/SankeyDiagram.svelte` |
| 4B.25 | Visual Network Map (topology SVG) | L | [ ] Todo | `web/src/lib/components/charts/NetworkMap.svelte` |
| 4B.26 | Compliance Posture Summary page | M | [ ] Todo | `web/src/routes/compliance/+page.svelte` |
| 4B.27 | Progressive Disclosure refinement (all pages) | M | [ ] Todo | Refactor existing pages |
| 4B.28 | Visualization + compliance tests | M | [ ] Todo | Component tests |

### Sprint 5: Advanced Features (Group E)

| # | Task | Size | Status | Files |
|---|------|------|--------|-------|
| 4B.29 | Natural Language Search (query parser + UI) | L | [ ] Todo | `daemon/services/nl_search.py`, search component |
| 4B.30 | Community Detection Packs (install/manage/update) | L | [ ] Todo | `daemon/services/detection_packs.py`, settings UI |
| 4B.31 | Scheduled PDF/Email Reports (weekly/monthly) | L | [ ] Todo | `daemon/services/report_generator.py`, settings UI |
| 4B.32 | Advanced feature tests | M | [ ] Todo | All test files for E1-E3 |

---

## v2.0 Roadmap: Nice-to-Have Features

**Status:** Planned for post-v1.0 release. These are ambitious features that push NetTap toward a unique market position.

| # | Feature | Inspired By | Description | Complexity |
|---|---------|-------------|-------------|------------|
| R1 | ML Anomaly Detection | Elastic/Splunk UEBA | Baseline normal behavior per device, alert on deviations (DNS tunneling, beaconing, unusual data volumes). Uses OpenSearch ML. | Very High |
| R2 | MITRE ATT&CK Coverage Map | Elastic Security | Visual grid showing which MITRE techniques NetTap's active rules detect. Educates users about threat landscape. | Medium |
| R3 | Investigation Timeline | Elastic/Security Onion | Drag-and-drop timeline workspace for assembling events from different log sources into chronological incident narratives. | High |
| R4 | Threat Intelligence Feed Integration | Splunk/Wazuh | Automated IOC matching against MISP, OTX, Abuse.ch feeds. Flag connections to known-malicious IPs/domains/hashes in real-time. | Medium |
| R5 | Multi-Site Dashboard | PRTG/Splunk | Centralized view across multiple NetTap deployments for MSP/consultant users. Requires secure log forwarding. | Very High |
| R6 | Mobile-Responsive Dashboard | Firewalla | Fully responsive web UI optimized for phones/tablets. Web push notifications for critical alerts. | Medium |
| R7 | Vulnerability Detection from Traffic | Wazuh/ntopng | Identify vulnerable devices from passive traffic: outdated TLS versions, weak ciphers, HTTP User-Agent indicating unpatched software, JA3 matching. | High |
| R8 | Device Fingerprint Database | PRTG/Firewalla | Community-maintained database of device fingerprints (MAC OUI + DHCP + UA + JA3) to auto-identify device make/model/firmware. | High |
| R9 | Embedded CyberChef Enhancement | Security Onion | Deep CyberChef integration: right-click extracted artifact → decode/deobfuscate in-place. Currently iframe only. | Low |
| R10 | Gamified Security Score | Pi-hole/Wazuh | Persistent A-F network security grade that improves as users address findings. "Fix 3 issues to improve from B to A." | Medium |

---

## Risk Matrix

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Malcolm integration complexity | High | **Blocks everything** | Option C (direct container images) avoids fragile installer scripting |
| OpenSearch OOM on 16GB | High | System crash | Cap JVM at 4GB, auto-detect RAM in install script, warn if < 12GB |
| Bridge failure = internet loss | Medium | User-facing outage | Hardware watchdog, netplan persistence, `--validate-only` checks, document failure behavior |
| SvelteKit memory on N100 | Low | Performance | 40-80MB RSS is safe; benchmark early in Phase 3 |
| Web UI scope creep | High | Timeline slip | MVP: wizard + overview + alerts + settings. Defer GeoIP/Grafana polish to Phase 4 |
| Testing network code in CI | Medium | Can't validate bridge | Network namespaces + veth pairs simulate dual-NIC in GitHub Actions |
| Packet loss at sustained 1Gbps | Medium | Performance target missed | Evaluate AF_XDP/DPDK if kernel bridge insufficient; validate on reference hardware |
| SSD wear from constant writes | Medium | Hardware degradation | Write coalescing, 30s flush intervals, SMART alerting, recommend 600+ TBW drives |
| Malcolm upstream breaking changes | Low | Deployment breaks | Pin to tested release tag, maintain version lock file |

---

## Total Effort Summary

| Phase | Tasks | Hours (est.) | Weeks |
|-------|-------|-------------|-------|
| Phase 1: Core Infrastructure | 18 | 50-70 | 1-4 |
| Phase 2: Storage Management | 12 | 40-55 | 3-5 |
| Phase 3: Onboarding UX | 16 | 60-80 | 5-8 |
| Phase 4: Dashboard Polish | 18 | 80-100 | 7-10 |
| Phase 4B: SIEM Features | 32 | 100-140 | 10-13 |
| Phase 5: Community Release | 42 | 50-70 | 13-15 |
| **Total** | **138 tasks** | **~380-515 hours** | **~15 weeks** |

### Test Coverage Targets

| Phase | Daemon Tests | Web Tests | Total |
|-------|-------------|-----------|-------|
| Phases 1-4 (current) | 140 | 80 | 220 |
| Phase 4B Sprint 1 (Data Foundation) | +80 | +40 | +120 |
| Phase 4B Sprint 2 (Core UI) | — | +60 | +60 |
| Phase 4B Sprint 3 (Intelligence) | +60 | +30 | +90 |
| Phase 4B Sprint 4 (Visualizations) | — | +40 | +40 |
| Phase 4B Sprint 5 (Advanced) | +40 | +20 | +60 |
| **Total at completion** | **~320** | **~270** | **~590** |

### Sprint Breakdown

| Sprint | Weeks | Focus |
|--------|-------|-------|
| Sprint 1 | 1-2 | Bridge hardening, common.sh, hardware validation |
| Sprint 2 | 3-4 | Malcolm integration, install script, bridge tests |
| Sprint 3 | 3-5 | Storage management (overlapping), ILM, daemon completion |
| Sprint 4 | 5-6 | SvelteKit init, auth, daemon API, TLS |
| Sprint 5 | 7-8 | Wizard UI, dashboard APIs, Grafana setup |
| Sprint 6 | 8-9 | Dashboard home, alerts page, connections explorer |
| Sprint 7 | 9-10 | Grafana dashboards, notifications, health page |
| Sprint 8 | 10-11 | CI/CD, docs, community setup, launch prep |

---

## Appendix: Memory Budget (16GB N100)

| Component | Estimated RAM | Notes |
|-----------|--------------|-------|
| OpenSearch JVM | 4.0 GB | Hard cap via OPENSEARCH_JAVA_OPTS |
| OpenSearch off-heap | 2.0 GB | Lucene file cache, network buffers |
| Zeek | 1.0-2.0 GB | Depends on connection table size |
| Suricata | 1.0-2.0 GB | Depends on ruleset size |
| Arkime | 0.5-1.0 GB | Session capture process |
| OpenSearch Dashboards | 0.5 GB | Node.js process |
| Grafana | 0.3 GB | Go process, efficient |
| NetTap daemon + API | 0.2 GB | Python + aiohttp |
| NetTap web (SvelteKit) | 0.05-0.08 GB | Node.js, minimal |
| OS / kernel / buffers | 2.0-3.0 GB | Page cache, network stack |
| **Total** | **~11.5-15 GB** | Tight but feasible |

If RAM < 12GB, install script should reduce OpenSearch heap to 2GB and warn the user.
