# Button

Pill-shaped actions in three forms: the default button, the primary button and the round icon button.

**Use**
- `.btn` for secondary actions ("Find in PCAP", "More filters"). `.btn.primary` for the one main action in a card or page head ("View connections", "Export CSV"); never two primaries side by side.
- `.icon-btn` (36px circle) for refresh, notifications, menu, close and sign out. It always has an `aria-label`. Add `.ghost` to drop the border and fill where it sits inside a panel. A count goes in `.badge-dot` (accent fill, `on-accent` text).
- Put a 16px `.ic` icon before the label when it names the object the action opens.

**Consumer provides**: the label (sentence case, a verb that says what happens), an optional leading icon, and an `aria-label` for icon buttons.

**Don't**: use accent for a secondary action, or use a button where the target is a place (use `.link` for "View alerts").
