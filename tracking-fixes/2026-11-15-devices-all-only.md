# Devices shows All devices only, 2026-11-15

**Linear:** NET-296
**Branch:** `feature/devices-all-only`
**Status:** PR #304 open; deploy with `scripts/remote/deploy-devices-all-only.sh` after the merge.

## Ask

The owner: "can we get rid of the 'by type' toggle for all devices and show the 'all devices' view as
standard default?" In mirror mode Devices opened on By type, so every visit meant a tab switch.

## Root cause

Not a bug. Devices had two tabs: By type (registry rows grouped by device type, mirror mode only, rows
open `/devices/mac/<mac>`) and All devices (the IP list, rows open `/devices/<ip>`). Mirror mode picked
By type first.

## Fix

- `web/src/routes/devices/+page.svelte`: no tab strip; the All devices card is the page in every mode.
  A link's `?view=` is ignored, and the range pills write only `range`.
- The registry still loads in mirror mode for the new-device banner. By type was where a failed registry
  showed, so the page now shows an amber "Couldn't load new devices" notice itself (found by
  `/ponytail-review`).
- Home's Devices card and Moment's Active devices card drop `view=all` from their links.
- By type's code, styles and tests are kept as OLD CODE. `device-types.ts` and `registry-traffic.ts`
  (and their tests) have no live caller now; kept under the preservation policy.

What changes for the owner: one row per IP, not per MAC; no photos in the list (custom names still
show); rows open the IP page. The MAC page is still reached from the top-bar search, the new-device
banner, Changelog and Moment.

## Tests

- `devices.test.ts`: mirror mode with `?view=type` opens the table with no tabs; a range pill drops the
  old `view`.
- `devices-by-type.test.ts`: By type's own suites are OLD CODE. Live: mirror mode opens the table, rows
  open the IP page, the banner stays; no registry request outside mirror mode; a failed registry says so;
  a failed capture mode shows no bridge notice; loading; bridge and mirror empty states.
- `home-drilldown-links.test.ts`, `moment-page.test.ts`: links without `view`.
- `e2e/visual/devices-layout.visual.ts`: mirror mode opens the table, no tabs, no page scroll at 1440 and
  390 px in every theme.
- Vitest 5375 passed; svelte-check 0 errors; check:colors clean; build passes; visual devices-layout,
  routes, theme, default-range passed.

## Lessons

- The Codex plan gate found two link tests pinning `view: 'all'`, and tests in the By type file that
  covered behaviour that stays. A wholesale retire of that file would have dropped them.
- Removing a view can remove the only place an error was shown. Check what each removed panel reported.

## Next

- Pre-existing, seen in the screenshot: with a very long manufacturer name the All devices table is wider
  than its card at 1440 px and scrolls inside it (the NET-284/285 `nowrap` pattern). Not changed here.
