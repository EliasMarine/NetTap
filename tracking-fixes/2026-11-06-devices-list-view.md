# 2026-11-06 — Devices By type: cards whose stats line up, and a compact List layout (NET-180)

**Status:** built on `feature/devices-list-view`. The PR is pending. Plan: `.codex-review/2026-11-06-135108-devices-list-view/PLAN.md` (Codex approved in round 2 after 3 findings).

**Problem**
- The owner, with a screenshot of /devices By type: some cards had Traffic, Connections and Last seen higher than the cards beside them, and By type had no list view with compact rows.

**Cause**
- A card showed its maker line only when the registry had a manufacturer. A card with none (DESKTOP-1H4Q4HV, a Mac) was a line shorter, and its stats followed its content, so they sat higher than its neighbours'.
- The "(N of M addresses listed)" note came after the stats, and a wrapping maker or a wrapping figure moved the stats too.

**Fix** (`web/src/routes/devices/+page.svelte`)
- Every card has the same three rows: top; the maker line, always shown ("Maker unknown" when the lookup found none) with the addresses note under it; the stats.
- Each card spans three rows of its group's grid and uses them as a subgrid (`grid-template-rows: subgrid`), so a row of cards shares each row's height and every card's stats start at the same height. Without subgrid support, the stats sit at the bottom of equal-height cards.
- A Cards / List switch (Pills, "Layout") beside the By type note. List shows one sortable `DataTable` per type group under the same group head: Device (type icon, name, New chip), Address (first address, "+N", "2 of 3 listed"), Maker, Traffic, Connections, Last seen.
  - The cells use the card's own helpers (`cardBytes`, `cardConnections`, `timeAgo`), so the two layouts show the same figures, unknown "—" and real "0 B" included.
  - Unknown traffic, connections and maker sort last in both directions, never as 0. Traffic sorts by bytes, Connections by count, Last seen by time.
  - The default sort is Last seen, newest first: the cards' order, so switching layouts keeps it.
  - A row opens the device page (`/devices/mac/<mac>`) through the table's row button.
- The choice is kept in `localStorage` (`nettap-devices-layout`). A missing, unknown or unreadable value is Cards; blocked storage still switches for the session.
- **Changes from the approved plan:**
  - Three rows per card, not four with an empty span for the note: an empty grid row still has a gap on each side, which would have doubled the space above the stats on almost every card. The note now sits in the maker row, still above the stats.
  - The List's Device cell uses the 16 px type icon (as All devices' Type column), not a small `DeviceTile`: the tile has no small size, and a 36 px tile would make the rows tall.

**Files**
- `web/src/routes/devices/+page.svelte`
- `web/src/routes/devices/devices-by-type.test.ts`
- `web/e2e/visual/devices-layout.visual.ts` (new), `web/e2e/visual/fixtures/devices.ts` (`BY_TYPE_LAYOUT`)
- `web/DESIGN-SYSTEM.md` (one line)

**Tests**
- Vitest (8 new, each fails on `origin/main`'s page):
  - every card has the same three rows in order, "Maker unknown" for no maker, the note above the stats;
  - List shows the cards' devices in the cards' order (the most recent first, though another has more traffic) with identical maker, address, traffic, connections and last seen, for a real zero, unknown figures and partial address coverage;
  - every List column sorts both ways, figures by value, unknowns last;
  - a row opens `/devices/mac/<mac>`;
  - a failed refresh keeps the same figures in both layouts;
  - the layout is remembered, an unknown stored value is Cards, blocked storage falls back to Cards and still switches;
  - no link or button nested in another, in either layout.
- Playwright (`devices-layout.visual.ts`): in mirror mode with a band of a no-maker card, an addresses note, a wrapping maker and a wrapping count beside a short one, every card's first stats label in each band is within 1 px of its neighbours', at 1440 px and 12 px either side of the grid's two breakpoints, in all three themes. Against `origin/main`'s page it reports DESKTOP-1H4Q4HV's labels 30 px higher than its neighbours'. The List pass checks one table per group, no horizontal scroll at 1440 and 390 px, and saves screenshots.

**Lessons**
- Equal-height cards don't line up their insides. Shared rows (subgrid) do; `margin-top: auto` only lines up the bottoms.
- An empty grid row still costs both its gaps: put optional lines inside a row that is always there.
- The grid's breakpoints are on the app container, not the viewport: measure the inset before picking widths either side of them.
