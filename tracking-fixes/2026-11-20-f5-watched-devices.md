# NET-331: "device went offline" alerts (roadmap #5)

**Status (2026-11-20, paused at the usage limit):** built and staged on `feature/f5-watched-devices`, not committed. All four reviews are in and their fixes applied: security had no blocking findings, Python said Ship, TypeScript had no High, and ponytail said Ship. A final full test run was started.
**Remaining:**
1. `/deep-review` (mandatory; the run was interrupted at stage 1, no report written);
2. `/verify`;
3. commit, PR, `gh pr checks`, and a squash-merge from this worktree without `--delete-branch`;
4. on the G11: pull main, then `bash scripts/remote/deploy-watched-devices.sh`;
5. Linear NET-331 Done, memory, and a distill.

**Plan:** `plans/2026-11-20-f5-watched-devices.md`. Codex reviewed it for the owner's six-round cap without approving (18, 14, 13, 12, 10 and 5 findings). The design converged on one clock, a precise D4 and one queued item per device. The remaining disagreements are network-level ambiguities, documented as limits in plan §4. Implementation went ahead on the final revision, under the owner's standing rule. The log is `plans/2026-11-20-f5-watched-devices.review-log.md`.

## What the owner gets

- **Watch a device:** a "Watch" option on both device pages: tell me if this device is silent longer than 15 minutes, 30 minutes, 1 hour, 4 hours or 1 day.
- **Messages:** one "Offline" message (high) when a watched device goes quiet, and one "Back online" (low) when it is heard again, with the time away.
- **The card:** a "Watched devices" card on Devices showing each one's state (Online, Offline, Waiting for first sighting), last seen and since when, with "Stop watching".
- **Settings:** a toggle, "Tell me when a watched device goes offline or comes back". The rule editor lists the type, so custom channels can receive it.
- **Bridge mode:** hidden and explained, since every frame carries the router's MAC.

## How it decides

- **One clock:** the last-packet time `event.end` on conn records.
  - A device's `seen_at` is its newest packet, as originator or as a responder that replied.
  - Silence counts only time capture covered (`capture_at − max(seen_at, coverage_since)`), and must pass the owner's time plus `LOG_DELAY` (600 s, Zeek's own writing delay), on two consecutive checks at least 4 minutes of capture time apart.
- **Crossing a boundary needs a new connection.** Enrollment and recovery need a connection that started after the watch began or after the outage was declared, so a peer's late packet or an old record indexed late can't count.
- **NetTap's own failures never produce a message.** That covers a capture that isn't ready (per-mode health), a stale pipeline, a coverage gap, a partial or zero-shard search, lost or unreadable state, a crash mid-commit and a capture scope change. Each of them pauses or misses.
- **Two-phase commit:** the state with `pending`, fsynced, then the journal append, then clear. Incident-scoped event ids, so nothing is journalled twice or without state.
- **Notifications:** one queued item per device (the newest) across every channel. Watch items wait while the journal intake is catching up, and unshown ones carry over.

## Files

- **Daemon:**
  - new: `services/watched_devices.py`, `services/watched_rules.py`, `services/watch_events.py`, `api/devices_watched.py`;
  - changed: `services/device_details.py` (`watch_is`), `services/event_journal.py` (unavailable after a load failure), `services/notification_dispatcher.py`, `services/notification_config.py`, `services/notification_hub.py`, `api/device_custom.py` (watch-only clear), `api/notifications_hub.py`, `api/server.py`;
  - tests: `test_watched_devices.py`, `test_watched_devices_unit.py`, `watched_rig.py`, `test_devices_watched_api.py`, `test_dispatcher_watch_events.py`, plus additions to `test_event_journal.py`, `test_new_device_rule.py`, `test_notification_config.py` and `test_device_details_api.py`.
- **Web:**
  - new: `lib/api/devices-watched.ts`, `routes/devices/WatchedDevicesCard.svelte`;
  - changed: `lib/components/DeviceCustomise.svelte`, both device pages, `routes/devices/+page.svelte`, `NotificationPrefsCard.svelte`, `NotificationsTab.svelte`, `lib/api/devices-registry.ts`, `lib/api/devices.ts`;
  - tests and the visual fixture.
- **Scripts:** `scripts/remote/deploy-watched-devices.sh`, `probe_watched_devices.py`, `verify_watched_devices.py`.

## Known limits (plan §4)

- **A device whose only traffic is one connection** is seen at each `conn_long` checkpoint (10 min, 30 min, 1 h, 12 h, 24 h, 3 d). It can be declared offline in a longer gap. The panel hint suggests a longer time.
- **A sparse heartbeat near its threshold** can be hidden by one lost frame. The hint asks for a time at least twice the device's quietest gap.
- **A router-trunk mirror** can attribute routed replies to the router's MAC.
- **A stall in `conn_long.log` alone** isn't detected.
- **Any skip or failure restarts coverage,** so a device going quiet then needs its full time plus 10 minutes again.
- **Spoofing:** another device sending a watched device's MAC keeps it Online. It reports silence, not tampering.
- **A flapping device** can send many Offline/Back online pairs a day. Past a channel's daily budget they fall back to the hourly digest. No per-device cap in v1.
- **An unreadable state file** stops the job without overwriting the file. The fix: delete `/opt/nettap/data/watched-devices.json` on the box. Every watch then restarts as "Waiting for first sighting".

## Test results

Final run on the staged change (2026-11-20):
- **Daemon pytest:** 6,080 passed, 5 skipped.
- **Web vitest:** 5,944 passed (435 files).
- **svelte-check:** 0 errors (2 old drawer warnings).
- **Other checks:** check:colors clean; ruff check and format clean; shellcheck clean; the verifier printed `WATCHED-DEVICES-OK`.

## Over-engineering review (/ponytail-review)

Verdict: Ship, with no bugs found; about 40 lines could go.

- **Applied:**
  - the unused `seq` field on watch items;
  - the unused return dict from `run`;
  - the duplicated success check in `_pass`;
  - one definition of the event names, imported by `watch_events.py`.
- **Declined, with reasons:**
  - **Merging `_search` into `storage/snapshot_search.search`.** The shared helper stretches its timeout to 1 s even past the deadline. The job's deadline is strict, and it refuses a zero-shard reply. Unifying them would change behaviour for the shared helper's existing callers, in a feature PR.
  - **Looping the three fixed-rule toggles over `_EVENT_RULES` in `notification_config.py`.** That is a refactor of the existing `new_device` and `data_cap` paths, beyond this feature. It is worth doing with the next fixed rule.

## Lessons

- **Six Codex rounds on a passive detector.** Each round found deeper timing edge cases until the model was rebuilt on one clock. Collapsing two clocks into `event.end` removed more findings than any patch added. Rounds 5–6 were about network-level ambiguity, which passive detection can't remove. Writing D4 as "NetTap's own failures never invent; the network's ambiguities are documented limits" is what made it converge.
- **Coalescing beat ordering.** Keeping one queued item per device removed every ordering problem at once: line fitting, character limits, page boundaries and high-only channels.
