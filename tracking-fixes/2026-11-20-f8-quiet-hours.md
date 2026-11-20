# #8: quiet hours, 2026-11-20

**Linear:** NET-330 (roadmap project P-NET-1, slice #8). The daily summary is split out to NET-343.
**Branch:** `feature/f8-quiet-hours` (from `origin/main` 8c13b2f4)
**Plan:** `plans/2026-11-20-f8-quiet-hours.md`. Six Codex rounds, no APPROVED verdict; every later finding was taken, and the owner signed off ("Build it now"). The argument is in `plans/2026-11-20-f8-quiet-hours.review-log.md`.
**Status:** implemented and tested locally; PR, merge and G11 deploy follow.

## Problem

- **Every notification went out the moment it was ready,** at 03:00 as at noon. An owner with a new-device or medium-alert rule got woken up for things that could wait until morning.

## What changed

- **Window** (`daemon/services/quiet_hours.py`, new): the setting `{enabled, start, end, critical_through}` (default off, 22:00 to 07:00, criticals through, decision D3).
  - `problem()` refuses anything but four keys, two booleans and two different ASCII `HH:MM` times. A backup's extra `tz` is allowed and dropped by `of()`.
  - `hold(now, quiet, tz)` reads the window in the owner's zone (F4, `owner_tz`). It compares UTC instants, because two datetimes sharing one ZoneInfo compare as wall times. A window over a clock change is an hour shorter or longer.
- **Dispatcher** (`notification_dispatcher.py`): the clock decides at each send decision, so nothing per window is saved.
  - Inside the window only critical alerts go (when the owner lets them). Everything else stays queued with `"held": true`, and so do retries and the hourly slot's digest.
  - The first send after the window carries everything held under "Notifications held by your quiet hours setting:", data cap warnings first. With 50 held alert types it adds a line pointing to the Alerts page.
  - The 50-alert cut ranks criticals that may go first, then worst first, a held item ahead of a fresh one only at the same severity. The ponytail review found a critical arriving at 07:00 behind 50 held alerts was cut while the morning send failed, and lost; the security review found the same for a high alert. A held alert that worse fresh ones displace still makes the send a release, with the full line.
  - A fresh copy of a queued alert keeps the worse observation, so a critical held overnight isn't reported as the medium that followed.
  - A held-only poll keeps the refusal throttle, so a critical at 22:01 doesn't retry a refused password.
  - Held events' "and N more" count waits for the release. Events held for another cap survive a critical send.
  - The window can't be read → a warning in the log, and notifications go as usual (fail open).
- **Setting** (`notification_hub.py`, `notification_config.py`, `api/notifications_hub.py`): `quiet` lives in `notifications.json` beside channels and rules. Every save keeps it. A hand-broken value reads as off, with one warning. PUT `/api/notifications/config` takes an optional `quiet` (400 with the reason when invalid). GET and PUT replies add `tz`.
- **Backup** (`config_backup.py`): a new `notification_quiet` section exported with the zone. An invalid one refuses the whole import before anything applies. A restore on a box in another zone says the times follow this box's zone.
- **Web:** a Quiet hours block on Settings › Notifications (switch, From and To, "Critical alerts come through", the zone with a link to Display), inline errors that disable Save, and "Quiet hours" on the Backup tab.
- **Deploy:** `scripts/remote/deploy-quiet-hours.sh` checks the running daemon is the image just built. It reads the live config only, then runs `verify_quiet_hours.py` in a throwaway copy of the image with no network and no mounts: two data cap warnings are held at 23:00 and 06:59 London time and released as one webhook POST at 07:00:30, with no second POST at 07:01:30.

## Tests

- **Daemon:** 5,594 passed and 5 skipped (from 5,492). New:
  - `test_quiet_hours.py` (34): validation, the window, clock changes, the skipped and repeated hour, `source`;
  - `test_dispatcher_quiet.py` (36): the plan's §6 cases, plus the reviews' cases: a critical and a high alert at the end of a full night, a held alert displaced by worse ones, a critical failing inside the window, a stale cap flag, the full-queue line and the held overflow count;
  - `test_quiet_hours_config.py`, `test_backup_api.py::TestQuietHoursPreflight`: the hub, quick settings, API, export, preflight, restore.
- **Mutation checks:** each new dispatcher behaviour was broken on purpose and a test failed every time (retry_at kept, held-first cut, merge, heading, cap-first order, held kept after a send, overflow, the fresh clock, critical first, the full-queue count).
- **Lint:** ruff 0.17.3 check and format clean over `daemon/`; shellcheck clean.
- **Web:** vitest 5,849 passed (full suite); svelte-check 0 errors (2 old warnings); `check:colors` and `check:e2e` clean; visual Settings › Notifications 5 passed.

## Gates

- **`/codex-review` on the plan:** 6 rounds; the owner signed off. The design got simpler on the way: no daily mode (NET-343), no saved window state, no alert cut count.
- **`/deep-review`:** no findings (`security-reviews/feature-f8-quiet-hours/`).
- **`/ponytail-review`:** two findings, both fixed: the critical cut at the end of a full night (above), and `_unshown` left live with no caller (now an OLD CODE block).
- **Two-angle review on PR #340:**
  - **Security:** no critical, high or medium. LOW-1 fixed: severity ranks before the held flag. Not taken, all INFO: a MAC flood can push the first real new-device event into the "and N more" count overnight (the count and the Devices page still show it); a backup's zone name is any string, quoted as plain text and bounded by the 16 MiB request cap; a 23-hour window with criticals held is the owner's own choice, as turning channels off is.
  - **Python:** no high or medium. Both LOWs fixed: a test for a critical that fails inside the window (it must keep the night's held alerts and events), and a cap warning kept for another cap now loses its held flag once the window is over, so a later send doesn't carry the quiet hours heading.
  - **TypeScript:** no critical or high. Fixed: the card no longer calls UTC "your time zone" when none is set (the reply adds `tz_set`); the Backup export sentence lists quiet hours; the no-PUT test now clicks a disabled Save; the time fields have a group name and only the wrong one is marked invalid. Not taken: the "overnight" label (the plan's wording) and switch-off bringing back the saved times (the plan's rule, so off can always be saved).

## Lessons

- **"It comes back on the next poll" holds only if the next poll can send.** A ranking rule that relies on the query's 5-minute overlap must not rank a must-send item behind held ones.
- **Load the saved value before any save the load triggers.** The hub's event-rule seed saves at start-up, so loading `quiet` after it wrote the default over the owner's setting.

## Next

- PR, two-angle review, merge, deploy on the G11 with `bash scripts/remote/deploy-quiet-hours.sh`.
- Then F2, the device details store (NET-320).
