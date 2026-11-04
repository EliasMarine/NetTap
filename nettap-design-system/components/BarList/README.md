# BarList

Ranked horizontal bars with the value beside the label, plus the plain meter.

**Use**
- `.bars` for category or protocol breakdowns: label left, value right ("21.4 GB · 44%", the number in `text-1` 600), then an 8px pill track in `surface-3` with a fill that fades from 45% to full series colour. Bars are scaled to the largest item.
- `.score-rows` reuses the bar for scored factors (Privacy 48, Security 71).
- `.meter` is a 6px accent bar for a single share (storage used, encrypted sessions) with `role="meter"` and its values.
- `.kv` lists pair a swatch, label, value and percentage beside a donut or gauge.

**Consumer provides**: items with a label, value, display text and data colour index; or a single percentage for a meter.
