# Sidebar

The floating navigation panel: brand, capture mode, grouped links, and storage and account in the foot.

**Use**
- `sidebar-w` wide, `surface-1`, `r-xl`, sticky at the top of the viewport.
- Under the brand, a `.mode-chip` shows the capture mode and interface with a pulsing `ok` dot ("Mirror mode · enp3s0").
- Links are grouped under `.nav-label` eyebrows: Overview, Investigate, Devices, System. Each link is an icon plus a label; the current page is `aria-current="page"` (`surface-3` fill, inset `line-strong` ring, accent icon).
- A `.count` badge (High severity tint) shows open alerts on the Alerts link.
- The foot shows storage use as a `.meter` and the signed-in user with a ghost sign-out button.
- Below `bp-phone` it hides; a menu button in `.m-top` opens it as a drawer over `scrim` with `shadow-pop`.

**Consumer provides**: the nav groups and current page, the alert count, capture mode, storage figures and user.
