# Detail Drawer Design — Unified Slide-Out Panel

**Date:** 2026-03-11
**Branch:** `phase-5/mirror-span-mode`
**Status:** Approved, implementing

## Summary

Replace ALL 5 expanded row implementations with a unified UniFi-style slide-out drawer. 480px wide, slides from right, tabbed interface per page context, action buttons in footer.

## Key Decisions

1. **Single shared shell + five thin content components** — DetailDrawer.svelte owns chrome; each page passes tab config and data through props
2. **No Svelte stores for drawer state** — each page owns a local `drawerXxx` variable (matches existing AlertDetailPanel pattern)
3. **Mirror mode store** — singleton `captureMode` store fetched once at app startup; "Block IP" hidden/disabled in mirror mode
4. **TShark inline in drawer** — no navigation to `/tools/tshark`; analysis runs in the Connections drawer TShark tab
5. **HEX fix** — second TShark call with `-T text` format for selected packet; daemon already supports it
6. **Log Explorer URL params** — fix `?filter=`/`?ip=`/`?query=` to be read on mount

## Per-Page Tabs

| Page | Tab 1 | Tab 2 | Tab 3 |
|------|-------|-------|-------|
| Logs | Fields | Raw JSON | — |
| Connections | Details | TShark Analysis | Raw JSON |
| Alerts | Summary | Related Events | Raw JSON |
| Devices | Overview | Connections | Traffic |
| Investigations | Details | Notes | Linked Items |

## Action Buttons

| Page | Actions |
|------|---------|
| Logs | View Source Device, WHOIS Lookup |
| Connections | View Source Device, View Dest Device, WHOIS Lookup, Block IP (disabled in mirror mode) |
| Alerts | Acknowledge, View Source Device, View Dest Device, View in Log Explorer |
| Devices | View Full Device Page, WHOIS Lookup, View in Log Explorer |
| Investigations | Change Status, Delete Investigation |

## New Files (16 + 10 tests)

- `web/src/lib/stores/captureMode.ts`
- `web/src/lib/api/lookup.ts`
- `web/src/lib/components/DetailDrawer.svelte`
- `web/src/lib/components/drawer/DrawerSection.svelte`
- `web/src/lib/components/drawer/KVRow.svelte`
- `web/src/lib/components/drawer/content/{Log,Connection,Alert,Device,Investigation}DrawerContent.svelte`
- `daemon/services/capture_mode_stub.py`
- Tests for all of the above

## Modified Files (7)

- `web/src/routes/+layout.svelte` — initCaptureMode()
- `web/src/routes/{logs,connections,alerts,devices,investigations}/+page.svelte` — replace expanded rows
- `daemon/api/server.py` — set capture_manager stub

## Build Sequence

1. **Phase 1 — Foundation**: stores, API client, shell components, backend stub
2. **Phase 2 — Content Components**: 5 drawer content components
3. **Phase 3 — Page Migrations**: replace expanded rows on all 5 pages
4. **Phase 4 — Tests**: all test files

## Bugs Fixed Along the Way

- TShark HEX never loads (three-layer bug)
- Log Explorer ignores ?filter= URL params
- /api/capture/* returns 503 (capture_manager never set)
- Mirror mode "Block IP" button shown when not applicable
