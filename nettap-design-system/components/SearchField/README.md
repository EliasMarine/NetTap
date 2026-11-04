# SearchField

A pill-shaped search input with a leading icon, used in the top bar and in table toolbars.

**Use**
- Top bar: `.search` up to 480px wide, 40px tall, with a `⌘K` `kbd` hint, placeholder "Search IPs, domains, devices…". To its right, `.top-right` holds "Updated 12 s ago" in `type-meta`, a refresh icon button and the notifications button.
- Toolbars: 36px tall, up to 360px, beside protocol pills and filter buttons ("Filter by IP, domain or port").
- The wrapping `<label>` holds a visually hidden name (`.sr-only`). Focus brightens the border to `line-strong`.

**Consumer provides**: the placeholder naming what can be searched, and a stable `id` on the input.
