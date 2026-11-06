# 2026-11-05 — Network flow redesign (Connections page)

**Status:** built and tested on `feature/network-flow-redesign`; PR and the G11 check are pending. Linear: NET-151. Mockup: https://claude.ai/artifact/98aEa6fgEjKvZqA9sgzWbX

**Problem**

The owner said the Sankey "looks un-even and just bad over all":
- Each column had its own scale, and every node was at least 20 px tall.
- Links were stroked lines whose width averaged two scales.
- Labels were cut at 14 characters.
- Devices showed only their IP, even when NetTap knew their name.

**Root cause**

- `SankeyDiagram.svelte` scaled each column on its own.
- The destination column holds only the top 10 destinations, so it can never add up to the source column.

**What changed**

- **`ui/charts/flow.ts`:** pure code that builds the chart from the endpoint's response.
  - Totals come from the links, plus an "Other destinations" node, so every column adds up.
  - One shared scale, with each column's real gaps.
  - Flush ribbons.
  - Labels spaced by their measured height, with a connector when a label moves.
  - Fixed protocol colours: TCP `data-1`, UDP `data-2`, ICMP `data-5`.
- **`NetworkFlow.svelte`:** picks one view by its own width.
  - From 640 px up, the chart. Otherwise `NetworkFlowTable.svelte`, a tabbed `DataTable` with no row activation, so the Other row has no button.
  - It also shows the table when the endpoint's two searches disagree beyond rounding. The reported figures are never adjusted.
- **`utils/device-names.ts`:** device names from the registry. Names that are only the manufacturer, the MAC or "Unknown" fall back to the IP. On a shared IP, the device seen most recently wins.
- **Connections page:** loads `getRegistryDevices({ limit: 200 })` alongside the other requests. A failed load keeps the last names and does not count against the refresh.
- **Visual fixture:** a crowded `networkFlow()` with:
  - 10 sources, 4 of them unnamed.
  - One source carrying 60 % of the bytes.
  - Two long destination names.
  - About 19 % of the bytes in Other.
- **`e2e/visual/network-flow.visual.ts`:**
  - One view at 1920, 1100, 900 and 390 px.
  - No overlapping or escaping labels at 1920 and 1100, at 100 % and 125 % text.
  - Naming checks.
  - Other is not a button.
- **Old code:** `SankeyDiagram.svelte` is kept unused (OLD CODE header), and the page's old import and markup are in OLD CODE blocks.

**Review gates**

- `/codex-review`: approved in round 3. All 10 findings were accepted. The main ones:
  - No adjusted figures.
  - Labels spaced by real height.
  - A crowded fixture.
  - One view at every width.
  - The Other row is not a button.
- `/ponytail-review` found two problems, both fixed:
  - The chart went dark when the filtering node left the data, for example after a time-range change.
  - A browser test asserted an IP that was hidden.
- `/deep-review`: no findings. The report is in `security-reviews/feature-network-flow-redesign/`.

**Test results**

- `npx vitest run`: 277 files, 2,896 tests pass.
- `npx svelte-check`: 0 errors, plus 2 warnings that were already there.
- `npm run check:colors`: clean.
- `npm run test:visual`: 187 pass, 0 fail.
- `network-flow.visual.ts`: 8 of 8 pass.

**Lessons**

- Screenshots caught three faults the unit tests passed:
  - The IP squeezed out device names.
  - At 125 % text, the share figure crushed destination names.
  - The phone table's Share column was cut off.
- The fixes:
  - The IP wraps to a hidden second line, so the name always wins.
  - A container query hides the share figure on narrow destination labels.
  - A `width: 100%; max-width: 0` name column ellipsises on phones.
- A focus or selection that no longer matches anything in the data must be dropped. Otherwise it dims the whole chart.

**Known risk**

On a busy device, logs indexed between the endpoint's two searches can make a protocol's outgoing bytes exceed its incoming bytes. The card then shows the table, with a note, until the next refresh. How often this happens on the G11 is not yet measured.
