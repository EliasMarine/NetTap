# MAC address column on Devices, 2026-11-16

**Linear:** NET-314
**Branch:** `feature/devices-mac-column` (from `origin/main` aca89d5f), PR #330
**Status:** implemented and tested locally. Deployed to the G11 with `scripts/remote/deploy-devices-mac.sh` after merge.

## Problem

The owner asked for each device's MAC address on the Devices page. The All devices table showed the IP, name,
type and figures, but no MAC. You had to open each device to see it.

## Root cause

`/api/devices` has always sent `mac` on every row (`web/src/lib/api/devices.ts`, `Device.mac`). The table had no
column for it. No daemon change was needed.

## Fix

- A **MAC address** column right after IP address, in the same mono style. It uses `DataTable`'s default sort, which
  ignores case and puts a missing MAC ("—") last both ways (`table-sort.svelte.ts`).
- The search box matches on MAC as well, ignoring case.
- The IP device page already showed the MAC (`devices/[ip]/+page.svelte`, the identity list), so both device pages
  now show it.

## Files

- `web/src/routes/devices/+page.svelte`: the column, its cell and the search clause
- `web/src/routes/devices/devices.test.ts`: the header count (10 → 11) and a new test for the column, sorting both
  ways and search
- `scripts/remote/deploy-devices-mac.sh`: a web-only deploy that checks the built page carries the column

## Tests

- `npx vitest run`: 419 files, 5649 tests passed
- `npx svelte-check`: 0 errors (2 old warnings in drawer components)
- `npm run check:colors`: clean
- `npm run test:visual`: 381 passed, 0 failed, no baseline changes

## Lessons

- Check the API reply first. The data was already there, so the change is three lines.
- The deploy check has to match the column's own definition (`key: "mac", label: "MAC address"`). The page's IPv6
  note already says "by its MAC address", so a plain grep would pass on the old build.
