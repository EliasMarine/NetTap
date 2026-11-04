# Chip

Small rounded labels for metadata, deltas and status beside a number or title.

**Use**
- `.chip` (`surface-3`, `text-2`) for neutral facts: device type, "IoT device", alert counts with an icon.
- `.chip.is-warn` (`sev-high` text on its tint) when the change is bad: alerts up, "3 trackers", a C trust score.
- `.chip.is-ok` (`ok` on its tint) for good news: "2 new today".
- Delta chips carry an up or down arrow icon and a signed percentage, followed by the comparison in `type-meta`: "+48% vs previous 24 h".
- `.live-chip` with a `.live-dot` shows a live stream; add `.is-paused` when paused (the dot stops and greys).
- `.tag` (mono, `r-xs`) is the flat sibling for protocols and categories inside tables: TCP, UDP, Tracking.

**Consumer provides**: one to three words, an optional leading icon, and the tone.
