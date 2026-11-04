# DataTable

Sortable tables for connections, DNS lookups and the live feed.

**Use**
- The header is a `surface-2` band with pill-rounded ends; header labels are `type-meta` 700 in `text-3`. Every header is a `.th-btn` that sorts; the sorted column shows a chevron in `text-1` and carries `aria-sort`.
- Rows are 11px by `sp-3` cells with a `line` divider and `row-hover` on hover. Numeric columns are `.num`: right-aligned, tabular.
- Device cells use `.who`: an icon, the name in 700 and the IP in mono `text-3` below. Destinations show the host, with the IP in mono below when they differ. Long values truncate with `.trunc` and a `title`.
- Protocols are `.tag`s. Data volume uses `.bytes`: the formatted value over a mini bar on a log scale. Results use `.res`.
- A `.tbl-foot` shows "Showing 1 to 14 of 182,406" and a `.pager`; the current page is the light pill.
- Wrap tables in `.tbl-wrap` so they scroll sideways inside the card on small screens.

**Consumer provides**: columns (label, numeric or not, cell renderer), rows, the initial sort and an `aria-label`.
