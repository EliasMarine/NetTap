# #6: data cap warnings, 2026-11-18 → 2026-11-20

**Linear:** NET-339 (roadmap project P-NET-1, slice #6)
**Branch:** `feature/f6-data-cap-warnings` (from `origin/main` 966fe873)
**Plan:** `plans/2026-11-18-f6-data-cap-warnings.md`. Codex APPROVED it in round 5 of 5; the full argument is in `plans/2026-11-18-f6-data-cap-warnings.review-log.md`.
**Status:** implemented and tested locally; PR, merge and G11 deploy follow.

## Problem

- **The owner had no warning before going over an ISP data cap.** The cap existed (`PUT /api/settings/bandwidth-cap`), but no page set it and nothing watched it.
- **Delivery could lose a warning.** A sent message acknowledged its whole queue, including events it never listed, and a service's length clip could cut a listed one.

## What changed

- **Producer** (`daemon/services/data_cap.py`, new): the `data-cap` job (every 900 s, 30 s deadline) reads the owner month from the usage-ledger snapshot (no OpenSearch query) and appends `data_cap` warnings to the event journal:
  - `"80"` at 80% of the cap, `"100"` at 100%, `"projected"` when the ledger projects the month over the cap, from day 3, and only while under the cap;
  - instance `"<YYYY-MM>|<cap bytes>"`, so each warning is sent once a month for each cap. A new cap re-arms; returning to an earlier cap sends nothing again;
  - thresholds use `bytes.lower_bound` (days counted under the current exclusions only, `usage_report._lower_bound`), so an exclusions change can't fake a crossing.
- **Journal** (`event_journal.py`): `compact()` keeps `data_cap` lines from the last 62 days even past the line cap.
- **Dispatcher** (`notification_dispatcher.py`, `notification_hub.body_limit`):
  - a `data_cap` branch in `event_item` (titles, severity 3/2/3, decimal GB line ≤ 140 characters, "at least: counted since D Mon" for a ledger that began after the month's first day);
  - every journal event line is clipped to 300 characters;
  - `digest()` fits lines to the channel's body limit (Pushover 1,024; Discord 4,096; Telegram 4,096 − 300) and returns what it rendered. Data cap warnings a send didn't render go in the next message; other events stay in its "and N more", as in F1;
  - the `MAX_EVENTS` trim never drops a `data_cap` item; before each send, `data_cap_now()` holds items for a cap the owner has left, drops items for a month that is over, and keeps at most 12 per queue.
- **Settings and rules** (`notification_config.py`, `notification_hub.py`): fixed rule `settings-datacap` (on by default, D1), `data_cap` in quick settings and `EVENT_TYPES`; deleting it turns it off; both fixed event rules are now always written, so an opt-out made before any channel exists is kept (fixes F1's new-device rule too).
- **Cap save** (`bandwidth_tracker.save_cap`, `api/bandwidth.py`): atomic write under a lock, then the live value; a failed write returns 500 "Couldn't save the cap" with both caps unchanged. `GET /api/bandwidth/cap` adds `lower_bound_bytes` and `first_day`.
- **Web:** a "Monthly data cap" card on Settings › Network (`DataCapCard.svelte`), "No cap set" linking to it on Bandwidth, a "Tell me when I near my data cap" switch on Settings › Notifications, and "Data cap" in the rule form.
- **Deploy:** `scripts/remote/deploy-data-cap-warnings.sh`.

## Tests

- **Daemon:** 5,492 passed and 5 skipped (from 5,434). New: `test_data_cap.py` (14), dispatcher cases in `test_dispatcher_events.py` (item lines and floors, fitting per service with the real payloads, only cap warnings carried over, flood, held/dropped/A→B→A, 12-item bound, 300-character clip, malformed data, `data_cap_now` failure), and cases in `test_event_journal.py`, `test_new_device_rule.py`, `test_bandwidth_tracker.py`, `test_usage_ledger.py` and `test_usage_api.py`.
- **Lint:** ruff 0.17.3 check and format are clean over `daemon/`; shellcheck is clean on the deploy script.
- **Web:** vitest 5,837 passed; svelte-check 0 errors (2 old warnings); `check:colors` and `check:e2e` clean; `test:visual` on the touched routes: 16 passed, 3 skipped by the harness's reduced-motion rule.

## Gates

- **`/codex-review` on the plan:** APPROVED in round 5 after 23 findings (7 + 6 + 6 + 4). Round 3 simplified the design: no state file, no previous-month reconciliation.
- **`/deep-review`:** no findings. The report is in `security-reviews/feature-f6-data-cap-warnings/`.
- **`/ponytail-review`:** two findings, both fixed:
  1. **The deploy script's cap restore wasn't retried on failure:** the trap was removed after a restore attempt in a subshell. `restore_cap` now clears its state only on success and the trap stays.
  2. **A ledger begun on the 1st read "counted since 1 Nov"** in the message; it now follows the card's rule (`since` after the month's first day).
- **Two-angle review (PR #339):**
  - **Security (2 LOW, both fixed):** carrying every unshown event over turned a burst of new MACs into dozens of messages, so only data cap warnings carry over now (new devices go back to F1's "and N more"). The deploy check's synthetic crossing runs only when no notification channel exists, so a test warning can't reach one.
  - **Web (1 MEDIUM, 4 LOW fixed):** "at least" figures floor to 0.1 GB (82.46 GB read "at least 82.5"); the input is locked during a save; the GB field takes "1,200" and refuses "0x10"; the error text must be a string; "some days aren't counted" replaces "still being counted" (a gap is never counted).
  - **Python:** no findings; it noted the same burst behaviour independently.

## Stated limits

- A crossing first accounted after the month's last local midnight is not warned about; the final figure is on the Bandwidth page.
- A queued warning for a past month is dropped after the month ends.

## Lessons

- **The session hit the weekly usage limit mid-build** (2026-11-18 23:07). The web half was finished; the daemon half was built but its §6 tests were not. Recovery read the transcript tail to find exactly which instructions had landed (`first_day` on the web side, not on the daemon).
- **Keep only what must not be lost.** Fitting a digest to a service's limit only helps when the dispatcher keeps the unrendered events, but keeping *every* unrendered event turned bursts into message floods. Data cap warnings are bounded (at most 12 a queue) and must arrive; new devices are summarised in "and N more".

## Next steps

- Merge, deploy on the G11 with `deploy-data-cap-warnings.sh`, and confirm the synthetic crossing.
- Next on the roadmap: #8, quiet hours and a daily digest.
