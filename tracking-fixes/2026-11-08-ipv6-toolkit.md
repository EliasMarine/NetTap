# NET-218: an IPv6 toolkit on the Tools page

**Date:** 2026-11-08 · **Branch:** `feature/ipv6-toolkit` · **Linear:** NET-218 · **Status:** in review

## Why

IPv6 addresses are hard to read: long, compressed with `::`, and full of special ranges. The Tools page had an IPv4-only subnet calculator and nothing for IPv6. The owner approved an interactive mockup on 2026-11-08 and asked for two changes: copy buttons, and a collapsible ranges table.

## What changed

- **`/tools/ipv6`**, a new Network tool that runs in the browser:
  - **Address inspector:** the type and reach in plain English, the short (RFC 5952) and full forms, the ip6.arpa name, the neighbour-discovery group, and any IPv4 address inside (mapped, NAT64, 6to4, Teredo). Every bad input gets its own message.
  - **Block:** first and last address, the count of /64 networks, the address count, and a note for common sizes.
  - **Device part:** whether the address matches the EUI-64 pattern (a candidate MAC, and the maker of that MAC from the daemon's lookup, debounced and generation-guarded) or has no MAC pattern. This is worded as a pattern, never as proof (RFC 7136).
  - **MAC to IPv6 (SLAAC):** refuses group MACs, lengths other than /64, prefixes with host bits set, and non-unicast prefixes.
  - **Address ranges:** a sortable `DataTable` in a `<details>`, closed by default.
  - **Copy buttons** on every machine value.
  - `?address=` keeps the address in the URL (shallow `replaceState`).
- **Classification** (`web/src/lib/utils/ipv6-ranges.ts`) covers all 25 rows of the IANA IPv6 Special-Purpose Address Registry, plus multicast, site-local and global unicast, matched by longest prefix. The registry's own CSV is checked in (`iana-ipv6-special-registry.csv`, downloaded 2026-11-08). A test fails if a row has no range, or if its "globally reachable" flag disagrees.
- **A network in CIDR** (prefix ≤ 64 and every later bit zero, e.g. `2001:db8:abcd:1200::/56`) reads as a network. `/127` and `/128` are always addresses.
- **Copy icon** added to the design system (`nettap-design-system/assets/Icons/copy.svg`, listed in its README) and to `icons.ts`; `icons.test.ts` keeps them equal.
- The **Subnet calculator** sends an IPv6 address to the toolkit instead of calling it invalid.
- **Visual harness:** a `/tools/ipv6` route, a targeted spec (`ipv6.visual.ts`: shared link, hydration, maker, ranges), and a fixture route for `/api/tools/mac-lookup`. Without it the maker lookup 404s in the harness, and the spec only passed because it finished before the 400 ms debounce.

## Plan gate

`/codex-review`, 3 rounds, APPROVED. Round 1 raised 7 points:

- rollback target
- missing IANA ranges
- `/127` and `/128` read as networks
- interface-ID wording claimed proof
- SLAAC prefix contract
- A→B→A lookup race
- a deploy check that passed when the route was absent

Round 2 raised 2: the rest of the registry, and testing every bit after the prefix. All were accepted.

## Verification

- `npx vitest run`: 334 files, 4,195 tests pass (94 in `ipv6.test.ts`, 13 in `ipv6-page.test.ts`, including the A→B→A reorder test).
- `npx svelte-check`: 0 errors, 2 warnings, the same as `main`.
- `npm run check:colors` clean, `npm run check:e2e` clean.
- Visual harness (production build, real sign-in): 6 tests for `/tools/ipv6` pass in empty, error and populated mode, in every theme at 1920, 1440 and 390 px.

## Deploy

Web only. `scripts/remote/deploy-ui-redesign.sh` (BRANCH=main) rebuilds `nettap-web`. Record the device HEAD first; roll back with `rollback-ui-redesign.sh <recorded-sha>`.
