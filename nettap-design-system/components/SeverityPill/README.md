# SeverityPill

The alert severity label: colour, a distinct shape and the word, always together.

**Use**
- One pill per alert, at the start of the row, in the drawer header and in summary lists.
- Shapes are fixed: Critical diamond, High triangle, Medium rounded square, Low filled circle, Info hollow circle. They keep severities distinguishable without colour.
- Text is the severity colour on its own 13% tint, which passes 5:1 on every surface.
- Severity counts sit in `.sev-count` tiles: the pill on top, the count below in `type-stat`.
- Connection results use the related `.res` dot style: Completed, `.is-live` Ongoing, `.is-medium` No reply, `.is-high` Reset.

**Consumer provides**: the level (critical, high, medium, low, info).

**Don't**: reuse severity colours for anything decorative, or show the colour without the word.
