NetTap is a home network monitor: a passive tap that records every connection, DNS lookup and Suricata alert on a household network and explains them to the person who owns it. The interface is a dark, calm control room. Near-black cards float on pure black, one accent hue carries the brand, and colour is otherwise reserved for data and severity. It should feel precise enough for a security analyst and plain enough for anyone else in the house.

## Voice and content

Write for the person who owns the network, not for the sensor.

- Lead with what happened in plain words, then show the raw detail underneath. The alert title is "Backyard camera tried to break into other devices"; the Suricata signature `ET SCAN Telnet brute-force attempt outbound` sits below it in mono.
- Every alert explains itself in one or two sentences ("Many apps ask ipinfo.io for your public address. The NAS does this for its remote-access feature.") and ends with a **What to do** box. When nothing needs doing, say so: "Nothing. This is how online games normally work."
- Name devices the way the household does: "Living-room TV", "Kitchen iPad", "Office NAS". Never lead with a MAC address or hostname.
- Sentence case everywhere: page titles, card titles, buttons ("View connections", "Find in PCAP", "Export CSV"). Buttons say exactly what happens.
- Card subtitles state the unit and the window: "GB per hour · busiest at 21:00", "Share of 182,406 sessions", "Last 24 hours, by severity". Use the middle dot `·` to join facts on one line.
- Errors say what failed and how to fix it, with no apology: "Couldn't load alerts: the request failed." then "Check that it is running on the System page, then try again."
- Empty states name what will appear and how to get there: "Devices appear here once NetTap sees their traffic."
- UK spelling in copy (colour, behaviour, recognise). No exclamation marks, no emoji, no jokes in alerts.
- Numbers agree across screens. If Home says 37 alerts, Alerts says 37.

## Colour

The palette is semantic tokens with three variants as themes: **Ember** (default: warm black, amber accent), **Graphite** (neutral black, white highlights, ice-blue second series) and **Spectrum** (cool black, violet accent, multi-hue data). All three are dark. A variant only changes surfaces, text tints, `accent`, the chart series and the glows; severity, `ok`, `bg` and the on-colours are shared.

- Paint the page with `bg` (pure black). Raise containers in steps: `surface-1` for the sidebar and inputs, `surface-2` for tracks and table header bands, `surface-3` for chips, tags and icon tiles.
- Cards use the `card-top` to `card-bottom` vertical gradient with a 1px `line` border and the `sheen` top highlight. Hero cards add a `hero-glow` radial glow from the top-left corner. Use at most one or two hero cards per screen.
- Text is `text-1` for headings, names and numbers, `text-2` for supporting copy, `text-3` for metadata, axes and IPs. All three pass 4.5:1 on every surface in every variant.
- `accent` is the only brand colour on screen: the primary button, the brand mark, the active nav icon, meters and sparklines. As text, use `accent-strong`. Text on an accent fill is `on-accent` (black).
- Selected pills, the current page in a pager and chart tooltips are a light pill: `pill-active-bg` with `on-light` text. This inversion is the system's "selected" signal; do not use accent for it.
- Data series use `data-1` to `data-6` in order, always with a legend or direct label.
- Severity uses `sev-critical`, `sev-high`, `sev-medium`, `sev-low`, `sev-info`, and health uses `ok`. These never mean anything else, and they never appear without their shape or word (see SeverityPill). Tinted backgrounds are the severity colour at 12 to 16% over transparent.
- `line-strong` is below 3:1 on the surfaces, so a control that relies on its border also gets a `surface-2` fill.

## Type

Three open-licence families, each with one job:

- **Sora** (`--font-display`) for headings and every big number. Numbers are light (300) and tightly tracked: `type-kpi`, `type-stat`. Titles are 500: `type-page-title`, `type-card-title`, `type-drawer-title`.
- **Manrope** (`--font-body`) for interface text: `type-body` for prose, `type-label` (600) for buttons, pills and nav, `type-meta` for subtitles and legends, `type-eyebrow` for uppercase section labels with 0.08em tracking.
- **JetBrains Mono** (`--font-mono`) for anything a machine wrote: IPs, MACs, ports, domains, hostnames, signatures, protocol tags. Set mono at 0.92em of the surrounding text (`.mono`).
- Every column of digits uses tabular figures (`.num` or `font-variant-numeric: tabular-nums`). Right-align numeric table columns.
- Headings use `text-wrap: balance`.

## Layout

- Desktop: a floating sidebar panel (`sidebar-w`, radius `r-xl`) beside a fluid 12-column grid with `sp-4` gaps. Cards span 3, 4, 5, 6, 7, 8 or 12 columns. A screen reads top to bottom: page head with time-range pills, a row of four KPI cards, one wide hero chart beside a narrower card, then detail cards and tables.
- At `bp-tablet` (1100px) quarter and third cards go half width and wider cards go full width; the alert drawer moves below the list.
- At `bp-phone` (760px) the sidebar becomes a menu button that opens it as a drawer over `scrim`, KPI cards sit two to a row and everything else stacks in the same order. Card padding drops from `sp-5` to `sp-4`.
- Breakpoints are container queries on `.app`, so the same rules work inside a preview frame.
- Keep a 16px side gutter at every width.

## Shape and depth

- Radii by role: `r-lg` cards, `r-xl` sidebar, `r-md` rows and inner boxes, `r-pill` for every control (buttons, pills, chips, search, bar tracks, the ends of table header bands), `r-xs` for tags.
- Depth is borders and the `sheen` highlight, not shadows. `shadow-pop` is only for overlays (the mobile nav drawer).
- Hover is a background step (`surface-2` to `surface-3`, or `row-hover` on rows) over `dur-fast`.
- Focus is `outline: 2px solid var(--focus); outline-offset: 2px` on every interactive element.

## Severity and state

State is always encoded three ways: colour, shape and word.

| Level | Token | Shape |
| --- | --- | --- |
| Critical | `sev-critical` | diamond |
| High | `sev-high` | triangle |
| Medium | `sev-medium` | rounded square |
| Low | `sev-low` | filled circle |
| Info | `sev-info` | hollow circle |

Connection results follow the same idea: Completed (grey dot), Ongoing (`ok` dot), No reply (`sev-medium` square), Reset (`sev-high` triangle). Live data shows a pulsing `ok` dot and a "Live" chip that becomes "Paused" in `text-2`.

## Charts

Charts are hand-drawn SVG with no chart library, styled entirely from tokens:

- Gridlines are `line`; every line above the baseline is dashed `2 5`. Axis labels are `type-axis` in `text-3`, on round steps (1, 2, 2.5, 5 × 10ⁿ).
- Lines are 2px, round caps, monotone-cubic so they never dip below zero. Area fills are the series colour from 32% opacity at the top to 0 at the baseline.
- Mark the most important point (the busiest hour) with a `band` highlight, a dot ringed in `bg`, and a pill tooltip (`pill-active-bg`, `on-light`). On hover the tooltip follows the pointer with a dashed `line-strong` guide.
- Donuts use 12px strokes with gaps between segments and the total in `type-stat` in the centre. The severity gauge is 36 radial ticks coloured by severity share.
- Maps are a dot grid of `map-dot` with `accent` arcs to the busiest destinations and a `text-1` ring for "Your network".
- Every chart has an `aria-label` that states the headline ("Busiest hour 21:00, with 4.7 GB downloaded").

## Iconography

- One outline icon set (Icons asset group): 24px grid, 1.7 stroke, round caps and joins, no fill. In the app they are inline SVG with `stroke="currentColor"` and the `.ic` class (18px), so they take the colour of their text. The uploaded files are drawn in `text-3` grey (#938a80) for reference only.
- Device types have their own icons (tv, laptop, nas, gamepad, phone, tablet, camera, speaker, printer), shown in a 36px `surface-3` tile with an 11px radius.
- Use icons beside labels, not instead of them, except for icon buttons, which always carry an `aria-label`.
- No emoji anywhere.

## Logo

The mark is a rounded `accent` square (radius 9 on 30) with an `on-accent` T-shaped tap line and a dot beneath it, followed by "NetTap" in Sora 600 at `text-lg`. In the app the square takes the current variant's `accent`; the uploaded file is the Ember version.

## Motion

Motion is functional and small: the live-dot pulse (2s), a new feed row flashing in from an accent tint (900ms), map arcs flowing along their dashes, skeleton shimmer. All of it stops under `prefers-reduced-motion`, and the live feed starts paused there.
