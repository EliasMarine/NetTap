# AlertDrawer

The detail panel for one alert: what happened, what to do, the facts and the next actions.

**Use**
- A sticky card beside the alert list (4 of 12 columns); below the list under `bp-tablet`. It closes with its close button or Escape.
- Order is fixed: severity pill and close; the plain title in `type-drawer-title` with the full signature wrapped below; one or two sentences of explanation in `text-2`; the `.todo` box; the `.facts` list; the actions.
- `.todo` is an accent-tinted box with a "What to do" label in `accent-strong`. It always has an answer, even if it is "Nothing."
- `.facts` is a two-column definition list: Device (linked, IP in mono), Destination, Port, Category, First seen, Last seen, Times seen. Machine values in mono.
- Actions: one primary ("View connections") and secondary buttons ("Find in PCAP", "Look up destination").

**Consumer provides**: the alert (severity, title, signature, explanation, advice, facts) and the action targets.
