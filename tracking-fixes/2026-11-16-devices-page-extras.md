# Devices page extras (PR A), 2026-11-16

**Linear:** NET-316 (follow-up to NET-314)
**Branch:** `feature/devices-page-extras` (from `origin/main` 62790896)
**Status:** implemented and tested locally. Deploy with `scripts/remote/deploy-devices-extras.sh`.
**Plan:** PLAN.md passed /codex-review in 3 rounds. Protocols and First seen are PR B (`feature/device-services`), because they need a daemon change.

## What the owner asked

"implement all of these please", meaning every item on the NET-314 shortlist. This PR is the web-only part.

## Fix

| Item | What it does | Where |
|---|---|---|
| Private tag | A MAC with the locally administered bit set (second hex digit 2, 6, A or E) gets a "Private" tag, with a title saying the device made it up for privacy and it can change. | `lib/utils/mac.ts` `isPrivateMac`, `lib/components/ui/MacAddress.svelte` |
| Copy MAC | A copy button beside the MAC. It uses the Clipboard API, falling back to a hidden textarea, as `IPAddress.svelte` does. Its label switches to "Copied" or "Copy failed" for 1.5 s, with a status line for screen readers. It never opens the row. | `MacAddress.svelte` |
| Both pages | The same component on the Devices table and on both device pages (the both-pages rule). | `devices/+page.svelte`, `devices/[ip]`, `devices/mac/[mac]` |
| Upload and Download | Two sortable columns after Bandwidth, with "—" and sorted last when a figure is missing. | `devices/+page.svelte` |
| Export CSV | Saves the rows the filters show, busiest first, in raw units (bytes, ISO times), with a UTF-8 BOM so Excel reads names like "Elias’s iPhone". Formula-looking cells are escaped, because hostnames come from the network. A renamed device exports its discovered name in its own column, never the alias twice. Status is the table's word ("—" for a window that ended). | `devices/devices-csv.ts` |
| csvCell | Moved unchanged to `lib/utils/csv.ts`. The changelog imports it and re-exports it. | `routes/changelog/changelog-rows.ts` |

## Tests

- New: `mac.test.ts`, `MacAddress.test.ts`, `csv.test.ts`, `devices-csv.test.ts`, plus `devices.test.ts` cases for the Private tag, Copy without opening the row, Upload/Download sorting, the export (filtered rows, BOM, Status) and a past window's "—" Status.
- `npx vitest run`: 423 files, 5682 tests passed. `npx svelte-check`: 0 errors. `check:colors`: clean.
- `/ponytail-review`: one finding (the Excel BOM), fixed.

## Lessons

- DataTable puts the row's button around the first column only. Any interactive control in a later column is safe from nested buttons, but must never move into the first column.
- jsdom's `Response` can't read a jsdom Blob. Read exported bytes with `FileReader`.
- The changelog export has no BOM either, so it would garble the same names in Excel. Not changed here.
