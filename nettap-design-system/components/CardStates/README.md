# CardStates

How a card looks while loading, when it has nothing to show, and when its request fails.

**Use**
- Loading: keep the card head (subtitle "Loading"), replace the body with `.skel` shimmer blocks shaped like the content, and set `aria-busy="true"` and `role="status"`.
- Empty: a `.state` with a 44px icon tile, a heading that names what is missing ("No devices seen yet"), a sentence on when it will appear and what to check, and one button to the place that fixes it.
- Error: `.state.is-error` (critical-tinted icon, `role="alert"`), a heading that says what failed ("Couldn't load alerts: the request failed."), the likely cause and fix, and a "Try again" button with the refresh icon.
- States keep the card's minimum height (230px) so the grid does not jump.

**Consumer provides**: the state, the card title, and for empty and error the message and one action.
