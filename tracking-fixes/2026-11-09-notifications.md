# Email and webhook notifications never left a Docker install (NET-224)

**Date:** 2026-11-09
**Branch:** `fix/net-224-notifications` (from `fix/release-audit-2026-11`)
**Linear:** NET-224 (release blocker B1, audit finding A5)
**Status:** Built and tested locally. Not yet deployed to the G11.

## What was broken

- Routing rules never fired: nothing called `NotificationHub.process_event`.
- Alert notifications were sent by the web container, and only while a browser had the dashboard open (`/api/notifications/from-alerts` was polled by the page).
- The web sender needed `nodemailer`, which isn't installed, so email never worked.
- Three sets of names for the same settings: the web loader read `NOTIFY_*` and `SMTP_USER`/`SMTP_PASS`, `.env.example` listed `SMTP_USER`/`SMTP_PASS`/`ALERT_EMAIL`/`WEBHOOK_URL`, Settings › API keys saved `SMTP_USERNAME`/`SMTP_PASSWORD`/`SMTP_SENDER_EMAIL`, and compose forwarded none of them.
- F3 (release audit) made POST `/api/notifications/config` answer 501, so the Settings tab couldn't save anything.
- GET `/api/notifications/channels` returned every secret (SMTP password, Telegram bot token, Discord/Slack URLs with their tokens).

## Root cause

Two half-built dispatchers: the daemon's hub (channels, rules, senders, no trigger) and the web module (a trigger tied to an open page, senders that couldn't run). Neither owned the config.

## Fix

The daemon owns the config and the sending; the web relays.

- **`daemon/services/notification_config.py` (new):** validation (webhook URLs http/https only, no user info; recipients without whitespace; rules well formed), the secret-free public view (URL hints and `has_<secret>` flags), the Settings tab's quick setup on fixed hub ids (`settings-email`, `settings-webhook`, rule `settings-alerts`), and the first-start seed from `ALERT_EMAIL`, `WEBHOOK_URL`, `ALERT_SEVERITY_THRESHOLD`.
- **`daemon/services/notification_hub.py`:** saves are atomic and mode 600 and swap the live config only after the write; each sender returns the reason it failed; HTTP sends have a 10 s deadline and never follow a redirect; SMTP uses implicit TLS on 465 and STARTTLS otherwise, both verifying the certificate, with a 30 s deadline on the whole transaction; an email channel without its own server uses the one in Settings › API keys; each channel's last delivery is kept and shown; failure reasons never carry a URL.
- **`daemon/services/notification_dispatcher.py` (new):** a background task polls the new Suricata alerts every minute (grouped as the Alerts page groups them), sends each channel one digest of what its rules route to it, retries a failed channel after 1, 5 and 15 minutes, and keeps its state in `notification-dispatch.json` (mode 600) so a restart loses nothing. Re-reading the same alerts never sends them twice; a newer occurrence waits an hour; an escalation goes at once.
- **`daemon/api/notifications_hub.py`:** GET/PUT `/api/notifications/config`, POST `/api/notifications/test` (every enabled channel, each failure named), validation with reasons, 500 with the reason when a save fails.
- **Web:** the config and test routes relay to the daemon (F3's 501 kept as OLD CODE); `sendNotification` keeps only the in-app toast and SSE; the Settings tab saves for real (webhook switch, blank URL keeps the saved one, a notice when no SMTP server is set); the channels page shows each channel's last delivery and the reason a create, rule or test failed; the rule form offers only Alert, the one event NetTap sends.
- **Env names:** one set. `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SENDER_EMAIL` (Settings › API keys wins), plus `ALERT_EMAIL`, `WEBHOOK_URL`, `ALERT_SEVERITY_THRESHOLD` for the first-start seed. Documented in `.env.example`, forwarded to the daemon in `docker/docker-compose.yml`.

## Files

`daemon/services/notification_config.py` (new), `daemon/services/notification_dispatcher.py` (new), `daemon/services/notification_hub.py`, `daemon/api/notifications_hub.py`, `daemon/api/server.py`, `web/src/routes/api/notifications/config/+server.ts`, `web/src/routes/api/notifications/test/+server.ts`, `web/src/routes/api/[...path]/+server.ts`, `web/src/lib/server/notifications.ts`, `web/src/lib/api/notification-hub.ts`, `web/src/routes/settings/+page.svelte`, `web/src/routes/settings/notifications/+page.svelte`, `web/e2e/visual/fixtures/notifications.ts`, `docker/docker-compose.yml`, `.env.example`, `scripts/install/preflight.sh` (comment). Tests: `daemon/tests/test_notification_config.py`, `test_notifications_api.py`, `test_notification_dispatcher.py` (new); web tests for the routes, the client, the server module, the catch-all timeout, the Settings page and the channels page.

## Tests

- Daemon: 4335 passed, 4 skipped (was 4271). `ruff check daemon/` clean.
- Web: 342 files, 4335 tests passed; `svelte-check` 0 errors; `check:colors` clean.
- Fail-before: on the old hub and API the new daemon tests gave 14 failures and 27 errors; on the old web code the new web tests gave 27 failures.

## Lessons

- A feature with a sender and no trigger looks finished in review. Trace each event to a caller.
- `.pyc` files on this volume can outlive a restored source file in the same second; clear `__pycache__` after swapping files for a fail-before run.

## Next steps

- Deploy to the G11: rebuild and recreate `nettap-storage-daemon` and `nettap-web`. The owner then turns email on in Settings › Notifications (the SMTP server is already in API keys).
- Refresh the visual baselines for `/settings` and `/settings/notifications`.

## Follow-up: the P2 leftovers (logged on NET-237)

The backup restore item (a restored `notifications.json` only reaches the daemon after a restart, and is written 644) went to the backup-storage agent, who is rewriting `config_backup.py`. Codex's notes for it: an empty section must clear what is there, and a malformed channel must be refused as a whole, because the dispatcher's `ch["id"]` and the hub's `channel["type"]` would raise on one.

- **SMTP deadline (`daemon/services/notification_hub.py`).** It started after the greeting and stopped before QUIT, so a server trickling either one could hold the worker thread. The connection now opens inside the 30 s window, and the QUIT exchange runs inside it too. smtplib only sets `_host` (the name both TLS modes check the certificate against) when the constructor connects, so it is set by hand. A greeting other than 220 is refused, as the constructor does. Tests run the real smtplib classes against a local server.
- **In-app store (`web/src/lib/server/notifications.ts`).** It wrote to `/var/lib/nettap` on a read-only container, so the bell's history lived only in memory. It now writes to `/var/lib/nettap-web`, the `web-data` volume the image's `nettap` user owns.
- **The bell's alert pass (`web/src/routes/api/notifications/from-alerts/+server.ts`).** A daemon failure read as "0 created". It now answers 502 with the reason. Because the store now survives restarts, a category's top signature notifies once a day instead of on every page load (the bell calls this on each load, over the last 24 h).
- **Installer (`scripts/install/malcolm-config.sh`).** Compose reads only `docker/.env`, and nothing copied the notification names there. They reached the daemon only while the installer ran, and a later `docker compose up` dropped them. `generate_compose_env` now copies the non-empty ones into `docker/.env`, for new and existing files, single-quoted so `$` and `#` stay as written. A value with a quote or line break is skipped with a warning that names the key, never the value.

Tests: each new test fails on the old code (SMTP 2, web 3, bats 3). Without the `_host` line the TLS test fails in both modes. Daemon 4340 passed, 4 skipped. Web 4338 passed, svelte-check 0 errors. `test_malcolm_config.bats` 45/45.

Lesson: `vi.mock('fs')` with `...actual` left the module's default import on the real fs. `notifications.test.ts` had been writing to the real disk, and silently failing, the whole time.

## Follow-up: a backup restore goes through the running hub

**Branch:** `fix/net-224-restore`, from `fix/release-audit-2026-11` after NET-227.

**Before.** NET-227 restored notifications by writing `notifications.json` from the import's worker thread, and the route then called the hub's private `_load_config()`. That left three problems:
- A Settings › Notifications save between the write and the reload put the old config back, while the restore was still reported as applied.
- A channel with no `id`, an unknown `type` or an unparseable URL was stored. The dispatcher then raised every minute, and the channel list GET could fail.
- The report told the owner to "enter them again, then turn them on", which the channels page can't do: it has no edit and no on switch.

**Fix.**
- `NotificationHub.restore_backup(sections)`: a missing section keeps what is there, and an empty one clears it.
  - Channels go through NET-227's `restore_channels`, so the box keeps its own secrets only while the destination is unchanged.
  - Every backup channel must pass the new `notification_config.channel_problem`: an object, an `id` equal to its key, a supported type, a config object, and a usable URL when one is present. Otherwise the whole restore is refused with a reason that names the channel, and nothing changes in memory or on disk.
  - The save goes through `_commit` (atomic, mode 600).
- An `RLock` covers every read-modify-write and the two readers that span channels and rules (`channels_for`, `get_quick_settings`). A routing decision therefore never mixes the old rules with the new channels. Nothing awaits under the lock.
- `_load_config` skips a channel `channel_problem` refuses and logs its key, so a hand-edited file can't stop the dispatcher. `url_hint` and `url_problem` no longer raise on a malformed URL.
- `ConfigBackup` takes `notification_hub` and calls `restore_backup`; `server.py` passes it. The file write and the `_load_config` reload are kept in OLD CODE.
- The warning now depends on the channel. The Settings tab's webhook: turn it on in Settings › Notifications and enter its URL. Any other channel: add it again on the Notification channels page, add its routing rules again (a new channel gets a new id), then delete the old channel and rules.

**Tests.** `daemon/tests/test_notification_restore.py` (16 tests). On the old code: 28 failures and 40 errors across it and the updated backup tests. With the lock taken out of `channels_for` and `configure`, both concurrency tests fail. Daemon suite: 4449 passed, 4 skipped.
