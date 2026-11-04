# NetTap Design System

> **Canonical reference.** Every page must follow these rules. Tokens live in `web/src/lib/styles/global.css`. The approved visual reference is `mockups/redesign-2026-11/index.html`. The redesign lands in phases (`PLAN.md`): PR 1 changed the tokens, fonts and theme; the shell, shared components and page layouts follow. Until a page's phase lands, its layout still uses the patterns further down this file.

## Design Philosophy

**Pure black, warm accent, calm data.** The background is absolute black (#000) on every page. Cards are near-black with hairline borders and generous radius. Numbers are big and light. One accent colour marks what's interactive or selected. Severity has its own fixed colours, so it reads the same in every theme.

### Three Pillars

1. **Device-centric:** organise by "what are my devices doing?", not by log type.
2. **Plain English:** every alert, metric and detection gets a human-readable explanation.
3. **Immediate value:** big numbers first, details on click. Progressive disclosure: overview, then category, then raw data.

---

## Design Tokens

All values are defined in `web/src/lib/styles/global.css`. **Never hard-code colours, spacing or font sizes in components.** The colour gate enforces the colour part in CI (see "Colour gate" below).

### Variants

| Variant | How it's set | Feel |
|---|---|---|
| **Ember** (default) | no attribute on `<html>` | Warm black, amber accent |
| **Graphite** | `<html data-variant="graphite">` | Monochrome |
| **Spectrum** | `<html data-variant="spectrum">` | Violet accent, multi-colour data |

The user picks one in **Settings → Display** (`ThemePicker.svelte`). See "Theme protocol" below.

### Surfaces, lines and text (change per variant)

| Token | Use |
|---|---|
| `--bg` | Page background. Always `#000`, every variant. |
| `--surface-1` | Cards, inputs, sidebar |
| `--surface-2` | Raised areas inside cards, table header row, hover fills |
| `--surface-3` | Popovers, tooltips, the highest layer |
| `--line` | Hairline borders and dividers |
| `--line-strong` | Emphasised borders, input borders on hover |
| `--text-1` | Primary text, big numbers |
| `--text-2` | Secondary text, labels |
| `--text-3` | Muted text, hints, axis labels (still AA on every surface) |
| `--accent` | Interactive, selected, focus, links, the brand |
| `--accent-strong` | Accent hover, link text |
| `--on-accent` | Text or icons on a solid accent or solid severity fill |
| `--focus` | Focus rings |
| `--scrim` | Modal and drawer backdrops |
| `--data-1` … `--data-8` | Categorical chart and legend colours, in order |

### Severity and status (the same in every variant)

| Token | Meaning |
|---|---|
| `--sev-critical` | Critical alerts; errors, failures, "down" |
| `--sev-high` | High alerts |
| `--sev-medium` | Medium alerts; warnings, "degraded" |
| `--sev-low` | Low alerts |
| `--sev-info` | Informational alerts |
| `--ok` | Healthy, success, "up" |
| `--sev-*-muted` | 12% tints of each, for badge backgrounds |

**Severity rules**
- Each severity uses its own token. Never share one colour between two severities, and never show severity in the brand accent.
- Never use colour alone: a severity badge always carries its label (and, where there's room, a shape or icon).
- Informational states (`.badge-info`, `.alert-info`) use `--sev-info`, never the accent: in Ember the accent is orange and would read as high severity.
- Traffic categories are decorative: their colours live in one map, `$lib/utils/category-colors.ts`, on `--data-*` tokens. Only "suspicious" uses a severity token.
- Status that isn't alert severity (online/offline, success/failure) uses `--ok`, `--sev-medium` and `--sev-critical` by meaning.

### Tints and translucency

Build translucent colours from tokens with `color-mix`, never `rgba()`:

```css
background: color-mix(in srgb, var(--sev-critical) 12%, transparent);
border-color: color-mix(in srgb, var(--accent) 30%, transparent);
```

### Legacy token names

Pages written before the redesign use the old names. They still work: each one is mapped onto a new token in `global.css`. Use the new names in new code.

| Legacy | Maps to |
|---|---|
| `--bg-void`, `--bg-primary` | `--bg` |
| `--bg-secondary`, `--bg-input` / `--bg-tertiary` / `--bg-elevated` | `--surface-1` / `--surface-2` / `--surface-3` |
| `--bg-overlay` | `--scrim` |
| `--border-dim`, `--border-muted`, `--border-default` / `--border-bright` | `--line` / `--line-strong` |
| `--text-primary` / `--text-secondary` / `--text-muted`, `--text-dim` | `--text-1` / `--text-2` / `--text-3` |
| `--accent`, `--cyan`, `--info`, `--border-accent` / `--accent-hover`, `--text-link` | `--accent` / `--accent-strong` |
| `--red`, `--danger` / `--orange` / `--amber`, `--warning` / `--blue` / `--green`, `--success` | `--sev-critical` / `--sev-high` / `--sev-medium` / `--sev-low` / `--ok` |
| `--purple` / `--pink` / `--teal` | `--data-4` / `--data-6` / `--data-3` |
| `--chart-1` … `--chart-8` | `--data-1` … `--data-8` |
| every `*-dim` / `*-muted` | a 12% `color-mix` of its mapped colour |

### Spacing (4px base)

| Variable | Value |
|---|---|
| `--space-xs` | 4px |
| `--space-sm` | 8px |
| `--space-md` | 16px |
| `--space-lg` | 24px |
| `--space-xl` | 32px |
| `--space-2xl` | 48px |
| `--space-3xl` | 64px |

### Typography

Fonts are bundled in `web/static/fonts/` (OFL 1.1) and never loaded from a CDN.

| Variable | Font | Use |
|---|---|---|
| `--font-display` | Sora | Page titles, big numbers |
| `--font-sans` | Manrope | All UI text |
| `--font-mono` | JetBrains Mono | IPs, ports, MACs, hashes, timestamps |

| Size | Value |
|---|---|
| `--text-xs` | 0.75rem (12px) |
| `--text-sm` | 0.8125rem (13px) |
| `--text-base` | 0.875rem (14px) |
| `--text-lg` | 1rem (16px) |
| `--text-xl` | 1.125rem (18px) |
| `--text-2xl` | 1.375rem (22px) |
| `--text-3xl` | 1.75rem (28px) |
| `--text-4xl` | 2.25rem (36px) |

### Radius

| Variable | Value | Use |
|---|---|---|
| `--r-xs` | 6px | Tiny chips |
| `--r-sm` (`--radius-sm`) | 8px | Inputs, small buttons |
| `--r-md` (`--radius-md`) | 12px | Buttons, pills, small cards |
| `--r-lg` (`--radius-lg`) | 20px | Cards |
| `--r-xl` (`--radius-xl`) | 26px | Hero cards |
| `--r-pill` (`--radius-full`) | 999px | Pills, dots |

### Motion

| Variable | Value |
|---|---|
| `--transition-fast` | 150ms ease |
| `--transition-normal` | 250ms ease |
| `--transition-slow` | 400ms ease |
| `--ease` | `cubic-bezier(0.2, 0.7, 0.2, 1)` |

Respect `prefers-reduced-motion`: CSS animations stop, and JavaScript animation keeps drawing the static frame and drops only the movement. `GeoMap` + `arc-scheduler.ts` are the pattern.

---

## Colour gate

`npm run check:colors` (`web/scripts/check-colors.mjs`) fails on any colour literal in `web/src`: `#rgb`, `#rrggbb`, `#rrggbbaa`, `rgb()`/`rgba()`, `hsl()`/`hsla()`, and `white`/`black` used as colours. It runs in CI.

- **Where it looks:** all CSS (`.css` files and `<style>` blocks), and quoted strings in TypeScript, `<script>` and markup. Plain text like "PR #147" and `white-space` never trip it.
- **What it skips:** test files, the `/* TOKENS START */` … `/* TOKENS END */` block in `global.css` (the only place literals live), and comments. Commented-out `OLD CODE` is skipped as a comment; live code between `OLD CODE` markers is still checked.
- **One-line exemption:** `// colour-gate: allow-next-line <reason>` on the line before, only for output that can never read CSS variables (for example email HTML in `lib/server/notifications.ts`). The reason is required.
- **Allowlist:** `web/scripts/check-colors.allowlist` holds only files scheduled for a later redesign phase. It must be empty once the shared components phase lands.

### Colours in JavaScript

- For `style=` attributes and SVG `fill`/`stroke`, use `var(--token)` strings: `fill="var(--data-2)"`.
- Canvas and libraries that can't take `var()` read the real value with `resolveToken('--accent')` (`web/src/lib/utils/tokens.ts`), and read it again when the theme changes (subscribe to `theme` from `$lib/stores/theme`).

## Theme protocol

- `src/app.html` has a tiny inline script that reads `localStorage['nettap-theme']` and sets `<html data-variant>` **before first paint**, so a saved theme never flashes Ember.
- `$lib/stores/theme` starts from that attribute and never reads storage itself. `setTheme(v)` is the only writer: attribute first, then the store (so subscribers read the new tokens), then storage. If storage is blocked, the theme still applies for the session.
- Components that render the current theme (the picker) render Ember on the server and adopt the store value in `onMount`, so server and client markup never disagree.
- To preview a variant on one element, add `data-theme-preview="graphite"`: that element gets the variant's tokens.

## Testing the look

- `npm run test:visual` runs the visual harness (`web/e2e/visual/`, `playwright.visual.config.ts`) against a fixture daemon. It logs in for real, opens every route in empty and error mode, and checks the black background, horizontal scroll and console errors in all three variants at 1920, 1440 and 390 px. A redirect to Login or Setup fails the test.
- `npm run check:e2e` type-checks the harness and its fixtures against the API interfaces.
- `src/tests/token-contrast.test.ts` checks every text and severity token is AA (4.5:1) on every surface, in every variant.

---

## Page Layout Rules

### Full-Width Layout (REQUIRED)

Every page uses a full-width layout. **No `max-width` constraints on the page container.** The content should breathe and fill the available space.

```css
/* CORRECT — full width */
.page-container {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
}

/* WRONG — do NOT constrain width */
.page-container {
  max-width: 1400px;  /* NEVER do this */
  margin: 0 auto;     /* NEVER do this */
}
```

The root layout (`+layout.svelte`) handles overall padding. Individual pages should NOT add their own page-level padding.

### Page Header Pattern

Every page starts with a header containing the title, subtitle, and action buttons.

```html
<header class="page-header">
  <div class="header-left">
    <h1>Page Title</h1>
    <p class="subtitle">Brief description of what this page shows</p>
  </div>
  <div class="header-right">
    <!-- Time range pills, refresh button, export, etc. -->
  </div>
</header>
```

```css
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-md);
  flex-wrap: wrap;
}

h1 {
  font-size: var(--text-2xl);
  font-weight: 700;
  margin-bottom: var(--space-xs);
}

.subtitle {
  color: var(--text-secondary);
  font-size: var(--text-sm);
}

.header-right {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  flex-wrap: wrap;
}
```

---

## Component Patterns

### Stat Cards (4-column grid)

```html
<div class="stats-grid">
  <button class="stat-card clickable">
    <span class="stat-label">LABEL</span>
    <span class="stat-value">1,234</span>
    <span class="stat-hint">Description text</span>
  </button>
  <!-- repeat 3 more -->
</div>
```

```css
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-md);
}

/* Use global .stat-card from global.css */

.stat-hint {
  display: block;
  font-size: var(--text-xs);
  color: var(--text-dim);
  margin-top: 2px;
}

@media (max-width: 1024px) {
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 768px) {
  .stats-grid { grid-template-columns: 1fr; }
}
```

### Cards

Use the global `.card` class. Always include a `.card-header` with title.

```html
<section class="card">
  <div class="card-header">
    <h2>Section Title</h2>
    <span class="card-badge">SUBTITLE</span>
  </div>
  <!-- content -->
</section>
```

### Sortable Data Tables (REQUIRED for ALL tables)

**Every table in the application MUST be sortable** — every column, both directions. Use the shared helper in `web/src/lib/utils/table-sort.svelte.ts`:

```typescript
import { TableSort } from '$lib/utils/table-sort.svelte';

// starts on 'bytes', descending; clicking the same column flips it, a new column starts descending
const sort = new TableSort<'name' | 'ip' | 'bytes'>('bytes');

// value(row, key) returns what to sort by; blanks (null, undefined, '') go last both ways
let sorted = $derived(sort.apply(items, (row, key) => row[key]));
```

```html
<div class="table-wrap">
  <table class="data-table">
    <thead>
      <tr>
        <th class="sortable" class:sorted={sort.key === 'name'} onclick={() => sort.toggle('name')}>
          Name<span class="sort-arrow">{sort.arrow('name')}</span>
        </th>
        <!-- more columns -->
      </tr>
    </thead>
    <tbody>
      {#each sorted as item}
        <tr><!-- cells --></tr>
      {/each}
    </tbody>
  </table>
</div>
```

**Comparing values:** a hand-written comparator must use `compareValues(a, b)` from the same file, never `localeCompare` or `<`. Those order text character by character, so `10.10.0.235` lands before `10.10.0.26`, port `80` before `8`, and tshark's `0.000123` after `0.01`. `compareValues` compares numbers (and numeric text) by value and orders the numbers inside text as numbers.

**Sort the rows that exist, not the rows on screen:** when a table is paginated by the daemon, sorting one page is wrong. Send `sort`/`order` to the API and sort in the OpenSearch query instead (see `_connection_sort` in `daemon/api/devices.py` and the Connections table on the device page).

**Rank labels, don't spell them:** severity and risk columns sort by a rank map (`{ critical: 4, high: 3, medium: 2, low: 1 }`), so the first (descending) click puts the worst on top.

<details>
<summary>Previous pattern (kept for reference; text compare was wrong for IPs and numbers)</summary>

```typescript
let sortField = $state('column_name');
let sortDir = $state<'asc' | 'desc'>('desc');

function toggleSort(field: string) {
  if (sortField === field) {
    sortDir = sortDir === 'desc' ? 'asc' : 'desc';
  } else {
    sortField = field;
    sortDir = 'desc';
  }
}

// For client-side sorting:
let sorted = $derived(
  [...items].sort((a, b) => {
    const av = a[sortField], bv = b[sortField];
    const cmp = av < bv ? -1 : av > bv ? 1 : 0;
    return sortDir === 'asc' ? cmp : -cmp;
  })
);
```

```html
<div class="table-wrap">
  <table class="data-table">
    <thead>
      <tr>
        <th class="sortable" class:sorted={sortField === 'name'}
            onclick={() => toggleSort('name')}>
          Name
          {#if sortField === 'name'}
            <span class="sort-arrow">{sortDir === 'desc' ? '↓' : '↑'}</span>
          {/if}
        </th>
        <!-- more columns -->
      </tr>
    </thead>
    <tbody>
      {#each sorted as item}
        <tr><!-- cells --></tr>
      {/each}
    </tbody>
  </table>
</div>
```

</details>

```css
.table-wrap {
  overflow-x: auto;
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
}

/* Use global .data-table styles */

.data-table th.sortable {
  cursor: pointer;
  user-select: none;
}

.data-table th.sortable:hover {
  color: var(--text-primary);
}

.data-table th.sorted {
  color: var(--accent);
}

.sort-arrow {
  color: var(--accent);
  margin-left: var(--space-xs);
}
```

### Two-Column Layout

```css
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-md);
}

@media (max-width: 1024px) {
  .two-col { grid-template-columns: 1fr; }
}
```

### Time Range Pills

```html
<div class="pills">
  {#each TIME_RANGES as tr}
    <button class="pill" class:active={selected === tr.value}
            onclick={() => setRange(tr.value)}>
      {tr.label}
    </button>
  {/each}
</div>
```

### Bar List (Horizontal Bars) — `HorizontalBarList.svelte`

**Canonical component:** `$components/HorizontalBarList.svelte`

Used for top-N rankings (IPs, domains, protocols, categories). All horizontal bar
graphs MUST use this shared component for consistent alignment, sizing, and drill-down.

**Props:**

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `items` | `BarItem[]` | `[]` | Array of bar data items |
| `maxValue` | `number?` | auto | Override max for width calculation |
| `showRank` | `boolean` | `false` | Show 1, 2, 3… rank numbers |
| `showDot` | `boolean` | `false` | Show colored dot before label |
| `labelWidth` | `number` | `140` | Fixed px width for label column |
| `barHeight` | `number` | `12` | Bar track height in px |
| `activeKey` | `string?` | — | Highlight row matching this key |
| `onclick` | `(item, i) => void` | — | Click handler (in-page filtering) |
| `emptyMessage` | `string` | `'No data available.'` | Empty state text |

**BarItem interface:**

```ts
interface BarItem {
  key: string;           // Unique key for {#each} block
  label: string;         // Display label
  value: number;         // Numeric value for bar width
  formattedValue: string;// Display string (e.g., "1.2K", "3.5 GB")
  color?: string;        // CSS colour token (e.g., "var(--data-1)")
  gradient?: string;     // CSS background (overrides color)
  secondaryValue?: string;// Optional secondary display (e.g., "12.3%")
  href?: string;         // Navigation link — row becomes <a>
  mono?: boolean;        // Monospace label font
  isIp?: boolean;        // Render label with IPAddress component
  badgeText?: string;    // Badge between rank and label
  badgeClass?: string;   // Badge CSS class
}
```

**Row rendering:** `<a>` when `href` is set, `<button>` when `onclick` is set, `<div>` otherwise.

**Layout:** CSS grid with a fixed-width label column so all bars start at the
same horizontal position regardless of label content:

```css
grid-template-columns: var(--hbar-label-width) 1fr auto;
/* With secondary values, adds a 4th auto column */
```

**Usage examples:**

```svelte
<!-- Static bars with colored dots -->
<HorizontalBarList items={protocols} showDot={true} labelWidth={100} />

<!-- Ranked list with IP drill-down links -->
<HorizontalBarList items={topIps} showRank={true} labelWidth={130} />

<!-- In-page filtering with active highlight -->
<HorizontalBarList
  items={signatures}
  activeKey={currentFilter}
  onclick={(item) => filterBy(item.key)}
/>
```

**Standard bar height:** 12px (consistent across all pages). Override with
`barHeight` prop only when justified.

### Loading & Empty States

```html
<!-- Loading -->
<div class="loading-state">
  <div class="loading-spinner"></div>
  <p class="text-muted">Loading data...</p>
</div>

<!-- Empty -->
<div class="empty-state">
  <div class="empty-icon"><!-- SVG --></div>
  <p class="empty-text">No data found</p>
  <p class="empty-hint">Try adjusting your filters</p>
</div>
```

---

## Rules

1. **Never hard-code colours.** Use tokens (`var(--sev-critical)`, not `#ff4d6d`). The colour gate fails the build otherwise.
2. **The background is always `--bg` (pure black).** Never put a coloured or gradient background on `body` or a page container.
3. **Severity uses `--sev-*` only,** one token per severity, and is never shown by colour alone.
4. **Never hard-code spacing.** Use spacing vars (`var(--space-md)`, not `16px`).
5. **Never hard-code font sizes.** Use text vars (`var(--text-sm)`, not `0.8125rem`).
6. **Never set max-width on page containers.** Pages are always full width.
7. **Every table is sortable:** every column, both directions.
8. **Global classes first:** `.card`, `.stat-card`, `.data-table`, `.btn`, `.pill` and `.badge` are in `global.css`.
9. **Monospace for data:** IPs, ports, hashes, counts and timestamps use `var(--font-mono)`.
10. **Responsive:** every page works at 1920, 1440 and 390 px with no horizontal scroll.
11. **Hover and focus states on everything interactive.** Focus rings use `--focus`.
12. **Accent for active and sorted:** `var(--accent)` for sorted columns, active pills and focused inputs. `<button>` elements always get an explicit text colour (the browser default is black).
