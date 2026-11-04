# Pills

A segmented control: a `surface-2` track holding pill buttons, one of which is selected.

**Use**
- Time ranges (1h, 24h, 7d, 30d), list groupings ("By category" / "All alerts"), protocol filters (All, TCP, UDP, ICMP) and variant switches.
- The selected pill is `aria-pressed="true"` (or `aria-current="page"` for navigation) and shows as the light pill: `pill-active-bg` fill with `on-light` text. Unselected pills are `text-2`, `text-1` on hover.
- Wrap the group in `role="group"` with an `aria-label` naming what it chooses.

**Consumer provides**: two to five short options and the selected one.

**Don't**: use pills for actions, or mark the selected pill with accent.
