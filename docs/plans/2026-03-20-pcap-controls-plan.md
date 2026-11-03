# PCAP Collection Controls — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a 100MB per-file PCAP size cap (user-configurable) and an on/off toggle for PCAP capture that starts/stops the Docker container.

**Architecture:** Backend API (`daemon/api/capture_control.py`) controls the `nettap-pcap-capture` container via `asyncio.create_subprocess_exec("docker", ...)`. Settings persist to `/opt/nettap/data/.env` using the existing `_load_env_file`/`_save_env_file` helpers from `daemon/api/settings.py`. Frontend adds a toggle to the PCAP page header and a "Capture" tab to Settings.

**Tech Stack:** Python/aiohttp (daemon), SvelteKit 5 with Svelte 5 runes (web), Docker CLI for container control, Vitest + aiohttp test utils for tests.

**Design Doc:** `docs/plans/2026-03-20-pcap-controls-design.md`

---

## Task 1: Backend — Capture Control API (tests first)

**Files:**
- Create: `daemon/tests/test_capture_control.py`
- Create: `daemon/api/capture_control.py`
- Modify: `daemon/api/server.py:66` (add import) and `daemon/api/server.py:648` (register routes)

### Step 1: Write failing tests for capture control API

Create `daemon/tests/test_capture_control.py`. Pattern matches `daemon/tests/test_settings_api.py` — uses `AioHTTPTestCase` with `unittest_run_loop`.

Tests cover:
- GET /api/capture/status — reads env file + mocks container state
- PUT /api/capture/toggle — mocks docker start/stop, verifies env persistence
- PUT /api/capture/settings — mocks docker restart, validates min/max
- Invalid JSON and missing fields return 400

### Step 2: Run tests to verify they fail

Run: `cd daemon && python -m pytest tests/test_capture_control.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.capture_control'`

### Step 3: Write the capture control API

Create `daemon/api/capture_control.py` with:
- `_read_capture_config(env_file)` — reads PCAP_CAPTURE_ENABLED and PCAP_ROTATE_MB from env
- `_docker_cmd(action, container)` — async subprocess for docker start/stop/restart
- `_get_container_status(container)` — async subprocess for docker inspect
- `handle_capture_status` — GET endpoint
- `handle_capture_toggle` — PUT endpoint (persists + starts/stops container)
- `handle_capture_settings` — PUT endpoint (persists + restarts if running)
- `enforce_capture_state` — startup function to stop container if disabled
- `register_capture_control_routes` — route registration

### Step 4: Run tests to verify they pass

Run: `cd daemon && python -m pytest tests/test_capture_control.py -v`
Expected: All tests PASS.

### Step 5: Wire up routes in server.py

1. Add import: `from api.capture_control import register_capture_control_routes`
2. Add registration: `register_capture_control_routes(app, env_file=env_file)`

### Step 6: Verify full daemon test suite

Run: `cd daemon && python -m pytest tests/ -v --timeout=30`
Expected: All existing + new tests PASS.

### Step 7: Commit

Type: `feat(capture)` — "add PCAP capture control API"

---

## Task 2: Docker Compose Default Change

**Files:**
- Modify: `docker/docker-compose.yml:468`

### Step 1: Change default PCAP_ROTATE_MB from 4096 to 100

Line 468: `PCAP_ROTATE_MEGABYTES: "${PCAP_ROTATE_MB:-4096}"` → `"${PCAP_ROTATE_MB:-100}"`

### Step 2: Commit

Type: `chore(capture)` — "change default PCAP rotation to 100MB"

---

## Task 3: TypeScript API Client

**Files:**
- Create: `web/src/lib/api/capture.ts`
- Create: `web/src/lib/api/capture.test.ts`

### Step 1: Write failing tests

Tests for `getCaptureStatus`, `toggleCapture`, `updateCaptureSettings` with mocked fetch.

### Step 2: Verify tests fail

Run: `cd web && npx vitest run src/lib/api/capture.test.ts`

### Step 3: Write the API client

Types: `CaptureStatus`, `CaptureToggleResult`, `CaptureSettings`, `CaptureSettingsResult`.
Functions: `getCaptureStatus`, `toggleCapture`, `updateCaptureSettings`.

### Step 4: Verify tests pass

Run: `cd web && npx vitest run src/lib/api/capture.test.ts`

### Step 5: Commit

Type: `feat(capture)` — "add TypeScript API client for capture control"

---

## Task 4: PCAP Page — Capture Toggle

**Files:**
- Modify: `web/src/routes/pcap/+page.svelte`

### Step 1: Add capture imports and state

Import `getCaptureStatus`, `toggleCapture` from `$lib/api/capture`.
State: `captureEnabled`, `captureLoading`, `captureStatus`.
Functions: `loadCaptureStatus()`, `handleCaptureToggle()`.
Call `loadCaptureStatus()` in `onMount`.

### Step 2: Add toggle UI to header

Inside `.header-right`, before the pills div:
- Status dot (green=active, red=stopped)
- "Capture Active" / "Capture Stopped" label
- Toggle switch button with loading animation

### Step 3: Add CSS

Uses design system vars: `--green`, `--red`, `--bg-elevated`, `--text-secondary`, etc.
Toggle is 36x20px with 14px knob, pulse animation while loading.

### Step 4: Verify build

Run: `cd web && npx svelte-check`

### Step 5: Commit

Type: `feat(pcap)` — "add capture on/off toggle to PCAP page header"

---

## Task 5: Settings Page — Capture Tab

**Files:**
- Modify: `web/src/routes/settings/+page.svelte`

### Step 1: Add capture to TabId and state

Change TabId union to include `'capture'`.
Import capture API functions.
Add state: `captureEnabled`, `captureMaxFileSize`, `captureContainerRunning`, etc.
Add functions: `loadCaptureSettings()`, `handleCaptureToggle()`, `saveCaptureSettings()`.

### Step 2: Add tab button

Insert "Capture" button between "Retention" and "API Keys" tabs.

### Step 3: Add tab content

Between retention and api-keys content blocks:
- Container status badge (running/stopped)
- On/off toggle (same synced state as PCAP page)
- Max file size number input with "MB" unit (min=10, max=10000)
- Field help text with defaults and range
- Save button with restarted feedback

### Step 4: Add CSS

Status badges use `--green-dim`/`--red-dim` backgrounds.
Toggle is larger (44x24px) for settings context.
All sizing uses CSS vars from design system.

### Step 5: Verify build

Run: `cd web && npx svelte-check`

### Step 6: Commit

Type: `feat(settings)` — "add Capture tab for PCAP collection controls"

---

## Task 6: Final Verification

### Step 1: Run all daemon tests

Run: `cd daemon && python -m pytest tests/ -v --timeout=30`

### Step 2: Run all web tests

Run: `cd web && npx vitest run`

### Step 3: Run svelte-check

Run: `cd web && npx svelte-check`

### Step 4: Design system compliance check

Verify no hardcoded hex colors, spacing, or font sizes in changed files.
Verify button text colors use CSS vars.

---

## Summary of All Files

| File | Action | Task |
|------|--------|------|
| `daemon/api/capture_control.py` | Create | 1 |
| `daemon/tests/test_capture_control.py` | Create | 1 |
| `daemon/api/server.py` | Modify (2 lines) | 1 |
| `docker/docker-compose.yml` | Modify (1 line) | 2 |
| `web/src/lib/api/capture.ts` | Create | 3 |
| `web/src/lib/api/capture.test.ts` | Create | 3 |
| `web/src/routes/pcap/+page.svelte` | Modify | 4 |
| `web/src/routes/settings/+page.svelte` | Modify | 5 |
