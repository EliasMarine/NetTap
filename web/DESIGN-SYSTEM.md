# NetTap Design System

> **Canonical Reference** — All pages MUST follow these patterns. The Log Explorer page (`web/src/routes/logs/+page.svelte`) is the reference implementation.

## Design Philosophy

**Dark SIEM Industrial** — Deep void blacks, vibrant cyan accent with subtle glow effects, monospace data density, DM Sans for UI chrome. Every pixel should feel like a mission control terminal for network security professionals.

### Three Pillars

1. **Data Density** — Compact fonts (12-14px), tight spacing, information-rich tables. No wasted space.
2. **Visual Hierarchy** — Multiple background elevation levels, text color tiers (primary → secondary → muted → dim), accent color draws the eye to actionable items.
3. **Immediate Value** — Big numbers first, details on click. Progressive disclosure: overview → category → raw data.

---

## CSS Variables (Design Tokens)

All values are defined in `web/src/lib/styles/global.css`. **NEVER hardcode hex colors, pixel spacing, or font sizes in component styles.** Always use CSS variables.

### Background Hierarchy (deepest → elevated)

| Variable | Value | Usage |
|----------|-------|-------|
| `--bg-void` | `#06080d` | Page background, deepest layer |
| `--bg-primary` | `#0a0e17` | Sidebar, topbar |
| `--bg-secondary` | `#0f1319` | Cards, table backgrounds |
| `--bg-tertiary` | `#141920` | Hover states, alternating rows |
| `--bg-elevated` | `#181d27` | Dropdowns, tooltips, modals |
| `--bg-input` | `#0d1118` | Form inputs |
| `--bg-overlay` | `rgba(0,0,0,0.6)` | Modal overlay |

### Text Hierarchy

| Variable | Value | Usage |
|----------|-------|-------|
| `--text-primary` | `#e8edf5` | Headings, data values, primary content |
| `--text-secondary` | `#8892a4` | Labels, descriptions, secondary content |
| `--text-muted` | `#555f73` | Disabled, placeholder, inactive |
| `--text-dim` | `#3a4255` | Barely visible hints, decorative |
| `--text-link` | `#00d4ff` | Links, interactive text |

### Borders

| Variable | Value | Usage |
|----------|-------|-------|
| `--border-dim` | `#1a1f2e` | Subtle dividers, table row separators |
| `--border-default` | `#222939` | Card borders, input borders, standard |
| `--border-bright` | `#2d3548` | Hover state borders, active elements |

### Accent & Status Colors

| Variable | Hex | Usage |
|----------|-----|-------|
| `--accent` | `#00d4ff` | Primary action, active states, links |
| `--cyan` | `#00d4ff` | Info, primary data viz |
| `--green` | `#00e676` | Success, online, healthy |
| `--amber` | `#ffab00` | Warning, caution |
| `--red` | `#ff4757` | Danger, error, critical |
| `--purple` | `#b388ff` | Secondary data viz |
| `--orange` | `#ff6d00` | Tertiary data viz |
| `--blue` | `#448aff` | Alternative accent |
| `--pink` | `#ff4081` | Data viz accent |
| `--teal` | `#1de9b6` | Data viz accent |

Each color has a `*-dim` variant (12% opacity) for badge/tag backgrounds.

### Spacing Scale (4px base unit)

| Variable | Value | Usage |
|----------|-------|-------|
| `--space-xs` | `4px` | Tight gaps, badge padding |
| `--space-sm` | `8px` | Button groups, inline gaps |
| `--space-md` | `16px` | Card padding, section gaps |
| `--space-lg` | `24px` | Card content padding, major gaps |
| `--space-xl` | `32px` | Section separation |
| `--space-2xl` | `48px` | Page-level separation |
| `--space-3xl` | `64px` | Empty state padding |

### Typography

| Variable | Value | Usage |
|----------|-------|-------|
| `--font-sans` | `'DM Sans', system stack` | All UI text |
| `--font-mono` | `'JetBrains Mono', monospace` | IPs, hashes, data values, code |
| `--text-xs` | `0.75rem` (12px) | Labels, badges, table headers |
| `--text-sm` | `0.8125rem` (13px) | Table cells, dense UI text |
| `--text-base` | `0.875rem` (14px) | Body text |
| `--text-lg` | `1rem` (16px) | Card titles, section headers |
| `--text-xl` | `1.125rem` (18px) | Page title |
| `--text-2xl` | `1.375rem` (22px) | Large section headers |
| `--text-3xl` | `1.75rem` (28px) | Stat card values |
| `--text-4xl` | `2.25rem` (36px) | Hero numbers |

### Border Radius

| Variable | Value | Usage |
|----------|-------|-------|
| `--radius-sm` | `4px` | Buttons, inputs |
| `--radius-md` | `8px` | Cards, dropdowns |
| `--radius-lg` | `12px` | Modals, large panels |
| `--radius-full` | `9999px` | Pills, badges |

### Transitions

| Variable | Value | Usage |
|----------|-------|-------|
| `--transition-fast` | `150ms ease` | Hovers, toggles |
| `--transition-normal` | `250ms ease` | Expansions, slides |
| `--transition-slow` | `400ms ease` | Page transitions |

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
    <span class="stat-value text-cyan">1,234</span>
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

**Every table in the application MUST be sortable.** Use this pattern:

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
  margin-left: 2px;
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

### Bar List (Horizontal Bars)

Used for top-N rankings (IPs, domains, protocols).

```css
.bar-list { display: flex; flex-direction: column; gap: 2px; }

.bar-row {
  display: grid;
  grid-template-columns: minmax(120px, 1.2fr) 1fr auto;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-xs) var(--space-sm);
  border-radius: var(--radius-sm);
  background: none;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all var(--transition-fast);
  text-align: left;
  width: 100%;
}

.bar-row:hover {
  background: var(--bg-tertiary);
  border-color: var(--border-dim);
}
```

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

1. **NEVER hardcode colors** — Always use CSS variables (`var(--red)`, not `#ff4757`)
2. **NEVER hardcode spacing** — Always use spacing vars (`var(--space-md)`, not `16px`)
3. **NEVER hardcode font sizes** — Always use text vars (`var(--text-sm)`, not `0.8125rem`)
4. **NEVER set max-width on page containers** — Pages are always full-width
5. **ALL tables MUST be sortable** — Every column header is clickable
6. **Use global classes first** — `.card`, `.stat-card`, `.data-table`, `.btn`, `.pill`, `.badge` are in global.css
7. **Monospace for data** — IPs, ports, hashes, counts, timestamps use `font-family: var(--font-mono)`
8. **Responsive breakpoints** — 1024px (tablets), 768px (mobile). Grids collapse, headers stack.
9. **Hover states on everything interactive** — Cards, rows, buttons all have `:hover` transitions
10. **Accent color for active/sorted** — `var(--accent)` for sorted columns, active pills, focused inputs
