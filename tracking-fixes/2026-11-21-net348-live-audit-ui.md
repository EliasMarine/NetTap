# NET-348 (PR B): live-audit UI fixes

**Date:** 2026-11-21 · **Branch:** `fix/live-audit-ui` · **Status:** in review

## What changed (audit finding → fix)
- **Drive shows Healthy at 74 °C** (`routes/system/+page.svelte`): System health's Drive row is now amber (`warn`) when SMART passes but reports warnings. It is red (`failing`) only when SMART fails.
- **Partial Home refresh leaves cards unmarked:**
  - Files: `routes/+page.svelte`, `lib/utils/load-failed.ts`, `lib/stores/alertSnapshot.ts`.
  - Each kept card's stale note says when its figures landed: "showing figures from 20:41" today, or "19 Nov, 23:58" for another day.
  - Alert groups stay on screen with a note instead of blanking.
  - Kept alert counts keep their own window and time, not the failed attempt's.
  - A range change clears the range-dependent alert groups too.
- **Carried window reads "Custom"** (`lib/utils/drilldown.ts`, `lib/components/ui/Pills.svelte`): the pill is named by its window ("19:02 to 20:02, 20 Nov"). On a phone, the track scrolls the selected pill into view, on mount and on a new selection only.
- **"5-day retention" unclear** (`lib/components/shell/status.ts`, `Sidebar.svelte`): the sidebar now says "5-day log and alert retention", and the storage foot links to `/settings?tab=retention`.
- **Connections protocol conflict** (`routes/connections/+page.svelte`):
  - The pills, the flow chart's protocol click and the query now share one protocol choice. Clicking the chart's protocol again returns to All.
  - A transport is queried on `network.transport`. TLS uses the protocols endpoint's own query (`TLS_QUERY`, shared with Home's drill-down).
  - A chart-only transport (ipv6-icmp) gets its own pill while it is picked.
- **Changelog link opens 7 days** (`routes/changelog/ChangelogDetail.svelte`): the links keep the loaded window, as NET-160 decided. Their text now names the address searched and the window: "Records for 192.168.1.233, …".
- **CI teardown error** (`routes/dns/+page.svelte`): the scroll timer is cleared on destroy. It was "document is not defined" in PR #345's Vitest job.
- `web/DESIGN-SYSTEM.md`: the stale-note text and the window-named pill.

## Root cause
Each was a display gap:
- the drive status read only the SMART pass flag
- stale notes had no time
- the carried pill had a fixed label
- the retention text was vague
- two separate protocol filters were ANDed
- link text that didn't say which window or address it searched
- an uncleared timer

## Test results
- Vitest: 5944 → 5961, all passing.
- svelte-check: 0 errors, plus the 2 known warnings.
- `check:colors` clean, `check:e2e` passes.
- `test:visual`: 391 passed, 0 failed.
- New cases:
  - System: 74 °C with every other check healthy.
  - Home refresh: 1h → 1h across a minute boundary keeps the note; 1h → 24h failure shows unavailable.
  - Alert snapshot: the kept window.
  - Pills: a trailing selected pill.
  - Connections: UDP → TCP, unmapped → All, and the TLS query.
  - Changelog: a two-address row names the address searched.
  - DNS: two teardown cases.
- Device (G11, 2026-11-21, `main` @ `ba4a3178`, via `deploy-live-audit-fixes.sh`): both containers healthy, `/login` 200, `/api/auth/me` 401 without a session.
  - The served build carries the new copy: "log and alert retention", "showing figures from", "Records for" and the `settings?tab=retention` link each appear in the web image's `/app/build`.
  - The drive finding's condition is live: SMART reports `healthy: true` at 73 °C with "Drive temperature 73C exceeds warning threshold 70C", the case System now shows amber.
  - Not checked in a browser on the device: the G11's self-signed certificate stops automated Chrome, so the six screens rest on the visual suite (391 passed on `a78fe1e2`).

## Lessons
- A count's link should say which window and address it searches, not only that it is "this range".
- Two filters for the same dimension in one page (pill plus chart) will eventually be ANDed. Keep one state.

## Next steps
Deploy with `bash /home/nettap/NetTap/scripts/remote/deploy-live-audit-fixes.sh` with PRs A (#346) and C.
