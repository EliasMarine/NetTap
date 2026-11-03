# PCAP Collection Controls — Design Document

**Date:** 2026-03-20
**Status:** Approved
**Branch:** phase-4/pcap-controls

## Overview

Two features for PCAP collection management:
1. **100MB per-file cap** — Each PCAP file rotates at 100MB (was 4096MB). User-configurable via Settings.
2. **On/off toggle** — Users can enable/disable PCAP collection. Stops/starts the `nettap-pcap-capture` container.

## Requirements

- Per-file size cap defaults to 100MB, configurable (10–10000 MB)
- Toggle stops the capture container; existing PCAPs remain accessible
- Settings persist across reboots via `/opt/nettap/data/.env`
- Quick toggle on PCAP page header; full config in Settings > Capture tab

## Backend: Capture Control API

**New file:** `daemon/api/capture_control.py`

| Endpoint | Method | Body/Params | Response |
|----------|--------|-------------|----------|
| `/api/capture/status` | GET | — | `{enabled, maxFileSizeMB, containerRunning, containerStatus}` |
| `/api/capture/toggle` | PUT | `{enabled: bool}` | `{enabled, containerRunning}` |
| `/api/capture/settings` | PUT | `{maxFileSizeMB: number}` | `{maxFileSizeMB, restarted}` |

### Toggle Mechanism

- **ON:** `docker start nettap-pcap-capture`
- **OFF:** `docker stop nettap-pcap-capture` (graceful SIGTERM, container preserved)
- Docker interaction via `asyncio.create_subprocess_exec` (no SDK dependency)

### Config Persistence

Two env vars in `/opt/nettap/data/.env`:
- `PCAP_CAPTURE_ENABLED=true|false` (default: `true`)
- `PCAP_ROTATE_MB=100` (default: `100`)

Reuses `_load_env_file` / `_save_env_file` from `daemon/api/settings.py`.

### Startup Behavior

On daemon startup, read `PCAP_CAPTURE_ENABLED`. If `false`, stop the capture container. This ensures the setting survives reboots.

### File Size Change

Updates `PCAP_ROTATE_MB` in env file. If capture is currently enabled, auto-restarts the container to apply (`docker restart nettap-pcap-capture`).

## Frontend: PCAP Page Toggle

**Location:** Top of `/pcap` page header.

- Green dot + "Capture Active" / Red dot + "Capture Stopped" + toggle switch
- Loading spinner during start/stop
- On mount: `GET /api/capture/status`
- Toggle: `PUT /api/capture/toggle`
- Rest of PCAP page still works when capture is off (browse/search/download existing files)

## Frontend: Settings > Capture Tab

**New tab** in `/settings` between "Retention" and "API Keys".

Contents:
1. **PCAP Collection** toggle (synced with PCAP page)
2. **Max File Size** — number input, "MB" suffix, default 100, min 10, max 10000
3. **Save** button — `PUT /api/capture/settings`, auto-restarts container if size changed
4. **Status card** — container status, current file size, total PCAP disk usage

## Docker Compose Change

```yaml
PCAP_ROTATE_MEGABYTES: "${PCAP_ROTATE_MB:-100}"  # was 4096
```

Default changes to 100MB for new deployments. Existing deployments with `PCAP_ROTATE_MB` in env keep their value.

## API Client

**New file:** `web/src/lib/api/capture.ts`

```typescript
getCaptureStatus(): Promise<CaptureStatus>
toggleCapture(enabled: boolean): Promise<CaptureToggleResult>
updateCaptureSettings(settings: CaptureSettings): Promise<CaptureSettingsResult>
```

## Testing

| Layer | File | Coverage |
|-------|------|----------|
| Daemon | `daemon/tests/test_capture_control.py` | Mock subprocess, test toggle, settings persistence, startup enforcement |
| API Client | `web/src/lib/api/capture.test.ts` | Mock fetch, test params, test responses |
| Components | `web/src/routes/pcap/pcap.test.ts` | Toggle states, loading, error |
| Components | `web/src/routes/settings/settings.test.ts` | Capture tab, form validation (min/max) |

## Files Changed

| File | Change |
|------|--------|
| `daemon/api/capture_control.py` | **New** — capture control API endpoints |
| `daemon/api/server.py` | Register capture control routes |
| `web/src/lib/api/capture.ts` | **New** — TypeScript API client |
| `web/src/routes/pcap/+page.svelte` | Add capture toggle to header |
| `web/src/routes/settings/+page.svelte` | Add "Capture" tab |
| `docker/docker-compose.yml` | Change default `PCAP_ROTATE_MB` from 4096 to 100 |
| `daemon/tests/test_capture_control.py` | **New** — pytest tests |
| `web/src/lib/api/capture.test.ts` | **New** — Vitest tests |
