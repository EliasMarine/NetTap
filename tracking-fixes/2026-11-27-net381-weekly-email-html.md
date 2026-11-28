# NET-381: branded HTML weekly report email

**Status:** built and tested locally on `feature/weekly-email-html`. Owner preview, PR and G11 deploy are pending.
**Linear:** NET-381 (related to NET-340)

## What changed
- The weekly report email is now multipart/alternative: the plain-text part, tidied, followed by a branded HTML part.
- The HTML part:
  - uses Ember colours, with the logo as an inline cid image;
  - opens with a 2×2 KPI grid;
  - shows severity as colour + shape + word, and alerts per day as bars;
  - prints each worst-rule explanation once;
  - lists new devices as rows;
  - says plainly when no data cap is set.
- The plain-text part:
  - drops the ASCII underlines;
  - prints each rule explanation once, then "Same as rule N";
  - rewords the cap line: "No data cap is set now. Warnings recorded under an earlier cap:";
  - adds a recipient line in place of a "turn it off" line.
- The Settings card says "by email" instead of "as plain-text email".

## Root cause
NET-340 shipped a plain-text renderer only. It printed each rule's full explanation, so one blocklist's four rules repeated the same two paragraphs four times.

## Files
- `daemon/services/report_html.py` (new): the HTML renderer. It reuses report_text's lines and helpers, so the figures and wording match the text part.
- `daemon/services/report_text.py`:
  - `heading`, `explanations`, `day_count` are now shared;
  - the underline is gone;
  - the cap wording and the recipient line are new.
- `daemon/services/notification_hub.py`:
  - `compose_report_message` is a pure composer, used by the sender and the deploy check;
  - `send_report_email(…, html, logo)`.
- `daemon/services/report_generator.py`: `_html_part`. A render failure means the email goes as plain text, and is logged.
- `daemon/assets/report-logo.png`: `nettap-mark.svg` at 96×96.
- `web/src/routes/settings/ReportScheduleCard.svelte` and its test: the copy change.
- `scripts/remote/deploy-weekly-email.sh`, `rollback-weekly-email.sh` and `report-email-preview.py`.
- Tests:
  - `test_report_html.py` (new);
  - `test_report_email.py`: the MIME tree, fallbacks and size;
  - `test_report_text.py`;
  - `test_report_state.py`: the cid wiring, and plain text on a render failure.

## Decisions
- **The HTML part is skipped when it exceeds 90,000 bytes**, and the email goes as plain text. Gmail clips an HTML body past about 102 KB, so only the HTML is measured, not the whole message. The HTML is also bounded by design: at most 50 devices (the report's own cap), 20 outages with "and N more", and 5 rules. A busy week measured 61 KB; the owner's 20–26 Nov week measured 23 KB.
- **Dark only**: `color-scheme: dark`, because the brand has no light theme. Partial-invert clients leave dark designs alone.
- **The logo's alt text is empty**: the "NetTap" wordmark sits beside it, so a screen reader would otherwise read "NetTap NetTap".
- **No dashboard links**: the daemon doesn't know its own URL, so the footer names the pages instead.

## Tests
- daemon: 6,332 passed, 5 skipped, 0 failed. `ruff check` and `ruff format --check` are clean.
- web: ReportScheduleCard 16/16 pass. svelte-check has 0 errors. The colour gate is clean.
- Preview (Chromium): no horizontal overflow at 600 px or 375 px, including a 120-character device name.

## Plan review
`/codex-review`: approved in round 4 of 5. The rounds made these changes:
- The deploy check never sends.
- A composition failure falls back to plain text, with one SMTP attempt.
- Each message gets its own Content-ID, plus the RFC 2387 `type` parameter.
- The cap wording is safe at a month rollover.
- The footer is cadence-neutral.

## Next
1. Get the owner's go on the preview.
2. Commit and open the PR.
3. Run `deploy-weekly-email.sh` on the G11.
4. The first real email arrives at the next scheduled hour.

## Lessons
- **Measure the size budget on a worst-case fixture early.** The first busy fixture was 166 KB, mostly 200 outage rows and the text part.
- **Mirroring the text part's lines kept the figures identical between the two parts for free.**
