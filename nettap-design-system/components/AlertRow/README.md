# AlertRow

One alert in a list: severity, a plain-language title over the raw signature, device, count and last seen.

**Use**
- A full-width button (`aria-current="true"` when its details are open) on a six-column grid: severity pill, title block, device, ×count, last-seen time, chevron.
- `.alert-title` is the plain description in 700; `.sig` under it is the Suricata signature in mono `text-3`, truncated with a `title`.
- Group rows under `.alert-group` headings (category name in `type-group-title`, count on the right) with a one-sentence `.group-plain` explanation of what the category means.
- Sort by severity, then by count. On phones the device, count and time columns hide (`.hide-sm`).

**Consumer provides**: severity, plain title, signature, device name and icon, count, last-seen time, selected state.
