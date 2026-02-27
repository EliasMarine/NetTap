# Development Environment Setup

This page covers how to set up a development environment for contributing to NetTap.

---

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| **Python** | 3.10+ | Storage/health daemon |
| **Node.js** | 18+ | Web dashboard (SvelteKit) |
| **npm** | 9+ | Package management |
| **Docker** | 24+ | Container runtime |
| **Docker Compose** | v2+ | Multi-container orchestration |
| **Git** | 2.30+ | Version control |

---

## Clone the Repository

```bash
git clone https://github.com/EliasMarine/NetTap.git
cd NetTap

# Set up upstream tracking
git remote add upstream https://github.com/EliasMarine/NetTap.git

# Switch to develop branch
git checkout develop
git pull upstream develop
```

---

## Daemon Development (Python)

The daemon handles storage management, SMART monitoring, and the REST API.

### Setup

```bash
cd daemon

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Running Locally

```bash
# Set environment variables (or use .env file)
export OPENSEARCH_URL=http://localhost:9200
export API_PORT=8880
export LOG_LEVEL=DEBUG

# Run the daemon
python3 main.py
```

The daemon starts an HTTP API server on port 8880 and begins periodic storage and SMART health checks.

### Key Directories

```
daemon/
  main.py              Entry point (async event loop, signal handling)
  api/
    server.py          aiohttp application factory and route registration
    traffic.py         Traffic analysis endpoints
    alerts.py          Alert management endpoints
    devices.py         Device inventory endpoints
    geoip.py           GeoIP lookup endpoints
    risk.py            Risk scoring endpoints
    baseline.py        Device baseline endpoints
    health_monitor.py  Internet health monitoring
    investigations.py  Investigation bookmark endpoints
    settings.py        Settings management
    search.py          Natural language search
    detection_packs.py Community detection pack management
    reports.py         Scheduled report generation
    bridge.py          Bridge health monitoring
    updates.py         Software update endpoints
    nic_identify.py    NIC LED identification
    tshark.py          TShark packet analysis
    cyberchef.py       CyberChef integration
  storage/
    manager.py         StorageManager (retention, disk monitoring)
    ilm.py             ILM policy application
  smart/
    monitor.py         SMART health monitoring
  services/
    tshark_service.py       TShark container integration
    cyberchef_service.py    CyberChef container integration
    geoip_service.py        GeoIP database queries
    risk_scoring.py         Device risk score computation
    device_baseline.py      Known device tracking
    internet_health.py      Internet connectivity monitoring
    investigation_store.py  Investigation persistence
    nl_search.py            Natural language query parser
    detection_packs.py      Detection pack management
    report_generator.py     Periodic report generation
    bridge_health.py        Bridge state monitoring
    version_manager.py      Component version tracking
    update_checker.py       GitHub release checking
    update_executor.py      Update application
```

---

## Web Dashboard Development (SvelteKit)

The web UI is built with SvelteKit and TypeScript.

### Setup

```bash
cd web

# Install dependencies
npm install
```

### Running the Dev Server

```bash
npm run dev
```

The development server starts at `http://localhost:5173` with hot module replacement (HMR).

### Key Commands

```bash
# Development server with HMR
npm run dev

# Type checking
npm run check        # or: npx svelte-check

# Linting
npm run lint

# Run tests
npm test             # or: npx vitest run

# Production build
npm run build
```

### Key Directories

```
web/
  src/
    routes/
      +page.svelte              Dashboard home
      +layout.svelte            App layout (sidebar, navigation)
      alerts/+page.svelte       Alerts page
      devices/+page.svelte      Device inventory
      devices/[ip]/+page.svelte Device detail
      connections/+page.svelte  Connection explorer
      investigations/+page.svelte Investigation bookmarks
      compliance/+page.svelte   Compliance overview
      settings/+page.svelte     System settings
      settings/notifications/+page.svelte  Notification config
      system/+page.svelte       System health
      system/updates/+page.svelte Software updates
      system/cyberchef/+page.svelte CyberChef tool
      setup/+page.svelte        First-run wizard
      login/+page.svelte        Login page
    lib/
      components/               Shared UI components
      styles/                   Global CSS (design system)
    api/                        TypeScript API client modules
```

---

## Development Without Hardware

You can develop and test most components without the full dual-NIC hardware setup:

### Web Dashboard

The web dashboard runs standalone with the SvelteKit dev server. API calls to the daemon will fail gracefully, showing loading states and error banners. You can:

- Work on UI components and styling
- Test page layouts and navigation
- Mock API responses for specific development scenarios

### Daemon

The daemon can be tested with:

- Mock OpenSearch responses (via pytest fixtures)
- Simulated disk metrics
- Test-mode SMART data

### Shell Scripts

Scripts can be tested with `--dry-run` mode, which logs all commands without executing them:

```bash
sudo scripts/install/install.sh --dry-run
sudo scripts/bridge/setup-bridge.sh --wan eth0 --lan eth1 --dry-run
```

---

## Docker Development

### Building Containers Locally

```bash
# Build the daemon container
docker build -f docker/Dockerfile.daemon -t nettap/storage-daemon:dev .

# Build the web container
docker build -f docker/Dockerfile.web -t nettap/web:dev .

# Start the full stack
docker compose -f docker/docker-compose.yml up -d
```

### Running Specific Services

```bash
# Start only OpenSearch (for API development)
docker compose -f docker/docker-compose.yml up -d opensearch

# Start OpenSearch + daemon (for full API testing)
docker compose -f docker/docker-compose.yml up -d opensearch nettap-storage-daemon
```

---

## IDE Setup

### VS Code (Recommended)

Recommended extensions:

- **Svelte for VS Code** --- Svelte language support
- **Python** --- Python language support
- **ESLint** --- JavaScript/TypeScript linting
- **ShellCheck** --- Shell script linting
- **Ruff** --- Python linting and formatting

### Settings

```json title=".vscode/settings.json (suggested)"
{
  "python.defaultInterpreterPath": "./daemon/.venv/bin/python",
  "python.formatting.provider": "none",
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff"
  },
  "svelte.enable-ts-plugin": true
}
```
