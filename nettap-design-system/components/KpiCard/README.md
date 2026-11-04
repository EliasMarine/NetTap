# KpiCard

A headline number with its label, change and a small supporting visual.

**Use**
- Four in a row (`.c-3`) at the top of a screen; three (`.c-4`) when there are only three.
- `.kpi-top`: the label and an `.ic` icon in `text-3`. `.kpi-num`: the value in `type-kpi`, with an optional `.kpi-unit` (GB).
- `.kpi-meta`: a delta chip ("+48%", `.is-warn` when up is bad) and "vs previous 24 h", or a short source note.
- `.kpi-sub`: one line of breakdown ("↓ 31.8 GB down · ↑ 7.4 GB up").
- `.kpi-foot`: a sparkline with the evening window highlighted, or a `.stackbar` (rounded segments in data colours with a legend).

**Consumer provides**: label, icon, value and unit, the previous value for the delta, and optionally a foot visual.

**Don't**: show more than four KPIs in a row or a KPI without its comparison window.
