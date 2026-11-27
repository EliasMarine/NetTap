# Wide-desktop layout streamline (NET-375)

**Started:** 2026-11-27 · **Source:** the wide-desktop layout review of 27 Nov 2026 (NetTap 0.4.0-beta.1, 1920 × 1080 and 2560 × 1440), re-measured on the G11 and checked against the code.

## Status

| Phase | Linear | What | Status | PR | On the G11 |
|---|---|---|---|---|---|
| 1 | NET-376 | Short cards stay short beside long tables | In progress | — | — |
| 2 | NET-377 | Records first on Connections and Log Explorer; Alert summary beside Home's chart | Todo | — | — |
| 3 | NET-378 | DNS and PCAP keep a selection in view; remove DNS's duplicate card | Todo | — | — |
| 4 | NET-379 | Detail panel beside the list instead of a modal on wide screens (Live first) | Todo | — | — |

Update this table, and the Linear issue, when a phase starts, merges and is verified on the G11.

## Root problems

1. **Short cards stretch to their tall neighbour.** The design system's `.grid` (`web/src/lib/styles/system.css:165`) leaves `align-items` at stretch, so every card in a row takes the tallest card's height.
2. **Pages for browsing records follow the dashboard recipe** (KPI row → hero chart → details), so the list sits 1,500–1,900 px down on Connections and Log Explorer.
3. **Opening a row's details is modal.** `DetailDrawer` is a native modal `<dialog>`, so you can't scan the list while a row is open. Alerts uses a panel beside the list instead.

A wider screen doesn't help, because nothing reflows. Every card's distance from the top of the page was identical at 1920 and at 2560 wide.

## Owner decisions (recommended options taken, 27 Nov)

- Keep cards as the building block. The review's divider-only sections are not used.
- Allow a records-first recipe on pages for browsing records, as Alerts already does.
- Try the side detail panel on Live first, then decide for Connections and Log Explorer.
- Remove DNS's duplicate "Most looked-up domains" card. It shows the same data as the Domains table.

## How to measure

The scratchpad script `g11-layout-measure.cjs` (Playwright, read-only) takes a 60-second session minted on the box via `scripts/remote/mint-session.cjs` on stdin, and never prints the token. For each card it reports its top, its height and its **stretch**: its height minus its height at `align-self: start`. Measure in batches of 8 pages or fewer per session.

### Before (G11, main `ff896092`, 1920 wide)

| Page | Card | Stretch |
|---|---|---|
| Live | Top talkers, Protocols | +4,984 px each (Protocols starts at 6,575 px) |
| DNS | Query types | +1,769 |
| DNS | Suspicious DNS patterns | +673 |
| PCAP | Protocols in preview | +1,752 |
| Infrastructure | Logstash pipeline | +1,565 |
| Alerts | Alert categories | +714 |
| IoT | Smart home health | +686 |
| Threats | DNS anomalies | +449 |
| System | Services | +273 |

Records sit at 1,918 px (Connections › Sessions), 1,483 px (Log Explorer › Log entries) and 3,291 px (DNS › Devices that looked it up). Hero charts that stretch about 200–275 px to their side card are intended: the chart fills the height.

## Phase 1: short cards stay short (NET-376)

**Branch:** `fix/layout-short-cards`

- **Correction 11 (`a11y.css`):** a `.fit` card keeps its own height (`align-self: start`). It goes on both cards of a pair whose heights depend on the data.
- **Live:** Top talkers and Protocols share one column beside the feed. Previously the feed spanned two grid rows, which split its height between the two side cards. Below 1100 px, the two cards still pair up side by side.
- **Flat Live map:** capped at the globe's 640 px height.
- **Tests:** `e2e/visual/short-cards.visual.ts` checks that a short card's height doesn't change when its neighbour grows, at 1920 and 2560. `live.visual.ts` checks the flat-map cap.
- **Deploy:** `scripts/remote/deploy-layout-streamline.sh` (web only; reused by later phases).

**Results:** pending.

## Phase 2: records first (NET-377)

Not started.

## Phase 3: selection keeps its context (NET-378)

Not started. Also check the NXDOMAIN errors table, which is 4,384 px tall on the G11.

## Phase 4: fewer modals (NET-379)

Not started. Out of scope: the floating panels in Tools › TShark.

## Lessons

- Measure stretch as the height minus the height at `align-self: start`. Empty space under a card's children misses a `col` card whose donut grows into the free height (correction 9).
