# Rename from All devices, list-only By type, and a search that opens pages (NET-201, NET-202)

**Date:** 2026-11-07
**Branch:** `fix/devices-rename-all-devices-list-view`
**Linear:** NET-201 (devices), NET-202 (search)
**Status:** Merged (PR #216, squash `0baac9bb`) and deployed to the G11 on 2026-11-07. Every check passed.

## What the owner reported

1. A device opened from **By type** had **Rename** and **Change picture**. The same device opened from the **All devices** table had neither.
2. They asked to drop the card view on `/devices` By type and keep only the list.
3. Searching an IP address opened Log Explorer. They wanted that address's traffic and everything else about it.

## Root causes

1. All devices rows open `/devices/<IP>`, the IP-keyed device page. NET-200 (PR #214) added the name and picture panel only to `/devices/mac/<MAC>`.
2. Not a bug: NET-180 had made Cards the default, with a Cards / List switch.
3. `searchTarget()` in `web/src/lib/components/shell/topbar.ts` sent every IP to `/logs?ip=` and all other text to `/logs?query=`. The suggestions were the daemon's canned example sentences, such as "show connections from 192.168.1.1 …", not the owner's devices.

## What changed

### NET-201: devices

- **The name and picture panel is shared.** `DeviceCustomise` moved from `routes/devices/mac/[mac]/` to `web/src/lib/components/`, together with its test. Its `device` prop now takes any device with a MAC.
- **The IP page has Rename and Change picture** (`web/src/routes/devices/[ip]/+page.svelte`) whenever the device has a MAC. Names are kept by MAC, so a device without one gets no buttons.
  - **A save shows at once.** `withOwner()` lays the saved name, icon and picture onto the page the way the daemon's `present()` does. The owner's name replaces the hostname, and the network's name stays visible.
  - **A refresh that began before the save can't bring the old name back.** Saves are kept per MAC with a revision number. A reply read before the save gets the save laid over it. Its fresh traffic, and any other device now at that address, still show.
  - **One save per device at a time.** A range change remounts the panel, so the page itself holds this lock.
  - **The Hostname row** never shows the owner's name as the network hostname, even when the daemon sent no discovered name.
  - **The Name hint** shows the network's name on this page too.
- **By type is the list only** (`web/src/routes/devices/+page.svelte`). The Cards / List switch, the card markup and its styles are kept as `OLD CODE`. The `nettap-devices-layout` key a browser may have saved is now ignored.

### NET-202: search

- **Enter in the search box** (`topbar.ts`, `TopBar.svelte`):
  - **An IP** opens its own page by the app's LAN rule (NET-160): the device page on the LAN, the address page otherwise. Only real addresses count: strict IPv4, and IPv6 must pass the browser's own URL parser. A MAC is never treated as an IP.
  - **A device's exact name or MAC** opens that device. This only happens when exactly one device matches; when several share the name, the list shows just those to pick from.
  - **A domain** opens its domain page.
  - **Anything else** goes to Log Explorer as before.
- **The suggestions** are your registry devices whose name, hostname, IP or MAC contains the text. There are at most 6, with name matches first. Each shows "IP · MAC" and opens its device page.
  - The device list is fetched once a minute. Keystrokes and Enter share it.
  - Enter on non-IP text waits for that list, and a newer keystroke cancels the wait.
- **The LAN rule loads when the search box gets focus**, not when a page loads. Loading it on page load sent the request from the sign-in and setup pages too, which got a 401.

## Reviews

- **`/codex-review` on the plan, 3 rounds.** Every finding was accepted. It caught these problems:
  - discarding a whole reply on save would have hidden fresh traffic and a different device at the address;
  - a save that finished during a range change was lost;
  - overlapping saves for the same or different devices could show the wrong name;
  - a MAC passed the old IPv6 check;
  - an exact name could open an arbitrary device when several shared it.

  The log is in `.codex-review/2026-11-07-devices-rename-list/` (gitignored).
- **`/ponytail-review`:** one finding, the Name hint missing the network's name on the IP page. Fixed.
- **`/deep-review`:** web-client-only diff, no findings.

## Tests

- **Web:** 4,057 tests pass before the last two fixes, plus 1 focus test and 1 hint test after them. Type-checking finds 0 errors, and `check:colors` is clean.
- **New tests:**
  - `devices/[ip]/device-detail-customise.test.ts` (11): the buttons, save, clear, no hostname, the Name hint, and four deferred-reply orderings. When I removed the guards on purpose, 4 of them failed.
  - `devices-by-type.test.ts`: moved from cards to rows, and a stored Cards layout is ignored.
  - `topbar.test.ts`: the search rules, the races, and the LAN rule loading only on focus.
- **Visual:** `devices-layout.visual.ts` now checks the list in every theme from 1440 down to 390 px. The cards' line-up checks are kept as `OLD CODE`. `firstrun.visual.ts` passes again after the focus fix.

## Deploy

`bash /home/nettap/NetTap/scripts/remote/deploy-devices-rename-search.sh` (web only).

**Result on the G11 (2026-11-07), every check passed:**

- web healthy;
- the build carries Rename on the IP device page;
- search opens devices, IPs and domains;
- By type has no Cards / List switch;
- the sign-in page answers HTTP 200.

## Lessons

- **Two pages show the same thing.** When a feature is added to one of the device pages (by IP, by MAC), check the other.
- **Reading a Svelte store in a component's top-level script subscribes it on every page that renders the component.** For something only search needs, read it when search gets focus.
