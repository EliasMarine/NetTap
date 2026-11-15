# README refresh with new screenshots, 2026-11-14

**Linear:** NET-282
**Branch:** `docs/readme-media-refresh`
**Status:** done. Owner approved the screenshots on 2026-11-14 ("GO GO GO"); PR #288 merged (`dbea628e`).
**Plan gate:** not needed: docs and media, plus a one-line placeholder fix.

## What changed

- **8 new stills** in `.github/assets/media/`: `packets-start.png` (the "What do you want to see?" form), `packets-library.png` (37 ready-made filters), `connections-flow.png` (network flow diagram), `device-live.png` (live bandwidth on one device), `local-services.png`, `changelog.png`, `iot.png` (smart home score) and `tools.png`.
- **The 11 existing stills were re-captured**, because the sidebar changed after 8 November (Local services added, System removed). `nettap-tour.gif` is unchanged and still shows the old sidebar.
- **README:** five new screenshot rows. The "What you get" list now covers what shipped after 8 November. The release line stays `v0.4.0-alpha.1`.
- **`web/e2e/visual/media.capture.spec.ts`:** new STILLS entries and three helpers. The old device-detail line is kept as OLD CODE.
- **App fix:** the Tools search placeholder was cut to "Search tools: ping, cer" in the page head at 1440 px. It is now "Search tools…", in `web/src/routes/tools/+page.svelte`, with the old line kept as an OLD CODE comment.

## How to regenerate

`cd web && npm run capture:media -- -g "<file name>"` (headed, fixture data only).

## Tests

- svelte-check: 0 errors.
- Tools vitest: 156 passed.
- `npm run check:colors`: clean.
- Visual tests matching "tools": 61 passed, 12 skipped.

## Known

- `iot.png` shows the inline-bridge-mode notice, because the fixture runs in bridge mode. Every shot shows the "Bridge mode · br0" chip, as the published ones already did.
- `changelog.png`: the Events table is wider than its card (an app bug; see below).

## Next

These app bugs were spotted while choosing pages, and are filed in Linear:

- `/pcap` timeline y-axis labels repeat.
- `/tools/dhcp-timeline` at 1440 px: the Messages column is cut off, and a space is missing.
- The `/changelog` Events table overflows its card.
- `/packets` "All traffic" text ends with "every packet:".
