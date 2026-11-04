# Charts

Hand-drawn SVG charts styled only by tokens: area lines, donuts, gauges, rings, sparklines, stacked bars, radar and the dot-grid map.

**Use**
- Area chart: 2px monotone lines in `data-1` (download) and `data-2` (upload), each over a gradient fill from 32% to 0. Gridlines in `line`, dashed above zero; axis labels `type-axis` in `text-3` on round steps; every fourth hour labelled.
- Mark the headline point: a `band` column, dots ringed in `bg`, and a pill tooltip (`pill-active-bg`, `on-light`, 700) stating the values. Hover moves the tooltip with a dashed `line-strong` guide.
- Donut: 12px segments with gaps, the total in the centre (`type-stat` over `type-meta`), a `.kv` list beside it.
- Severity gauge: 36 ticks over 270° coloured by severity share. Trust ring: a single accent arc over a `surface-3` track, "of 100" under the score.
- Sparklines in KPI feet: accent line, the evening window as an accent band, ring dots at both ends.
- Every chart has a role="img" and an `aria-label` with the headline numbers, and redraws to its container width.

**Consumer provides**: series values, labels, the series colour index, the point to highlight and an accessible summary.
