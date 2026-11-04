# Card

The basic container: a near-black gradient panel with a hairline border, `r-lg` corners and the `sheen` top highlight.

**Use**
- Every card has a `.card-head`: a `.card-title` (Sora, `type-card-title`) and a `.card-sub` that states the unit and window. Put a `.legend`, a `.link` or pills on the right of the head.
- `.card.hero` adds the corner `hero-glow`. Reserve it for the one or two cards that matter most on a screen (the main chart, the device identity).
- `.card.col` makes the card a column so a `.card-foot` (top rule, `type-meta`) sits at the bottom, holding a `.foot-stat` and a `.meter`.
- Cards sit in `.grid` (12 columns, `sp-4` gap) with span classes `.c-3` to `.c-12`.
- `.eyebrow` labels a sub-section inside a card ("Most common").

**Consumer provides**: title, a subtitle that names the unit or window, body content, and optional head actions or foot.
