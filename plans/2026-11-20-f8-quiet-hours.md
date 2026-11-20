# #8: Quiet hours, 2026-11-20

**Linear:** NET-330 · **Roadmap:** `plans/2026-11-18-feature-roadmap.md` §8 #8, decision D3 · **Depends on:** F1 (#336), F4 (#337), #6 (#339)
**Branch:** `feature/f8-quiet-hours` (from `origin/main` 8c13b2f4) · _Simplified after Codex round 3 (§12), revised after rounds 4–6 (§13–§15). Rounds 1–2 (§10–§11) designed for a daily summary as well; most of their mechanisms are gone with it._

## 1. What the owner gets

- **Quiet hours.** Settings › Notifications › Notification preferences gets a "Quiet hours" block:
  - a switch, "Hold notifications overnight", with From [22:00] and To [07:00];
  - "Critical alerts come through" (on by default, D3). A critical alert is sent at once and held notifications stay held;
  - times in the owner's time zone, which the card names and links to (Settings › Display, F4).
- **One message when quiet hours end.** Everything held (alerts, new devices, data cap warnings) arrives as one message starting "Notifications held by your quiet hours setting:".
  - It goes on the first eligible poll after the end time. Polls run a minute apart, and the channel's failure back-off and the daily limit's hourly slot still apply.
- **Unchanged:** test sends, the in-app bell, the daily message limit and retries. Quiet hours apply to every channel; there are no per-channel quiet hours (roadmap "Out").
- **Moved to a follow-up issue:** "one summary a day instead of instant messages" (the roadmap's optional daily digest). See §3.1.

## 2. Facts (code at 8c13b2f4)

- **Dispatcher** (`daemon/services/notification_dispatcher.py`):
  - `_deliver` (`:728`) builds the channel's candidates from fresh alerts plus `st["pending"]`, merged by signature (`:761-768`). It truncates them to `MAX_PENDING = 50`, worst first, and silently drops the rest (`:806`).
  - **One channel-wide `retry_at`** (`:847`) gates every send: the failure back-off, the hourly slot past `DAILY_BUDGET`, or the refusal throttle (`:994`). The early return keeps it only while candidates, offered events or the budget remain (`:886`). Every candidate goes in the same message (`:920`).
  - **Journal events** (new devices, data cap warnings) wait in a per-channel queue in `notification-events.json`, are never given up, and are trimmed past 500 with a counted `overflow`.
    - `cap_queue` (`:408`) returns `events` (all kept, including cap warnings held for another cap) and `offered` (the subset that may go now).
    - On a successful send the returned queue is `_unshown(events, rendered)` (`:958`): only unshown data cap warnings stay.
  - **Polling:** `poll_once` (`:652`) samples `now` once, then awaits the OpenSearch query and the journal page before `_deliver`. The journal is read every poll, quiet or not.
- **Hub** (`notification_hub.py`): `_commit(channels, rules)` (`:272`) writes only those two keys, so another key in `notifications.json` is lost on the next save. `_load_config` (`:199`) ignores unknown keys. With no config file, the hub seeds channels and rules from the environment (`:225`).
- **Quick settings:** `quick_view` / `apply_quick_settings` (`notification_config.py:258/429`), served by GET/PUT `/api/notifications/config` (`api/notifications_hub.py:156/162`). The card applies the PUT reply as the saved state (`NotificationPrefsCard.svelte:192`).
- **Owner time zone:** `owner_tz.read()` returns `{"tz", "set", "ok"}`, UTC until set, and UTC (with one warning) when the file is unreadable. It isn't in a config backup.
- **Backup:** `validate_import` (`config_backup.py:351`) only previews sections. `import_config` restores section by section, and a failed notification restore is an error while other sections still apply.
- **Construction:** `create_app` builds the dispatcher at `daemon/api/server.py:1444`, without a reference on `app`.
- **Severities:** alerts 1 (critical) to 4; `new_device` 3; `data_cap` 2 or 3. Only an alert can be critical.

## 3. Decisions

1. **Overnight quiet hours only; the daily summary is a follow-up.**
   - The roadmap's decided default (D3) is "critical comes through; summary at the end of quiet hours"; the daily digest is listed as optional.
   - In Codex rounds 1–3 every hard case came from daily windows running back to back: a release that must happen inside the next window, exactly once, across restarts, backlogs and edits. Overnight windows have a gap, so the clock alone decides, with no per-window state to keep in step.
   - **Stated behaviour:** held items go in the open interval between two windows. If no eligible send happens there (the channel throttled for the whole gap, or a gap shorter than a poll), they wait for the next open interval. Very long windows are allowed but not offered as a daily summary (Codex r4 #8).
   - Follow-up Linear issue: "feat: one notification summary a day".
2. **The owner's time zone (F4), not a `tz` of its own.** One zone for everything the owner sees, set in one place. A zone change moves quiet hours with it.
3. **Stored shape:** `quiet: {"enabled": bool, "start": "HH:MM", "end": "HH:MM", "critical_through": bool}`, the roadmap's fields minus `tz` and `daily_digest`. The default is `{false, "22:00", "07:00", true}`.
4. **The clock decides; nothing per window is saved.** At every send decision:
   - inside the window, only critical-through alerts are due and everything else is held;
   - outside it, everything is due.

   That gives the roadmap's rules directly:
   - a retry or hourly slot falling inside the window is held;
   - a critical is sent alone;
   - a restart, a recovered channel or an edited window follow the clock at once;
   - a window releases once, because sent items leave the queue and the next window is hours away.
5. **The decision uses a fresh clock reading per channel,** taken just before the send. `poll_once`'s `now` is sampled before the slow reads.
6. **Critical through is for alerts with severity 1 only.** It never skips the channel's `retry_at`: a failure back-off follows a send that failed in the last 1 to 15 minutes, and the hourly slot is the daily limit's design (security delta D3).
7. **Fail open.** If the window can't be computed, the dispatcher logs it and sends. For a security tool, a message at night beats a held critical alert.

## 4. Design

### 4.1 Window (`daemon/services/quiet_hours.py`, new, pure)

- `DEFAULT = {"enabled": False, "start": "22:00", "end": "07:00", "critical_through": True}`.
- `problem(raw) -> str | None`: why `raw` isn't a valid `quiet`.
  - Exactly the four keys, plus an optional `tz` string in a backup section, which is stripped before checking.
  - `enabled` and `critical_through` must be bools.
  - `start` and `end` must be strings that `re.fullmatch(r"[0-2][0-9]:[0-5][0-9]", v, re.ASCII)` accepts and `time.fromisoformat` parses (which rules out 24:00). The parsed times must differ (Codex r4 #7).
- `of(raw) -> dict`: the four validated fields, else `DEFAULT`.
- `Hold = NamedTuple(end: datetime, critical_through: bool)`.
- `hold(now, quiet, tz) -> Hold | None`: the window containing `now`, or None.
  - None when not enabled.
  - For local date `d` in (yesterday, today): `s = local(d, start)`, and `e = local(d, end)` if `end > start`, else `local(d + 1, end)`. Return `Hold(e, ct)` if `s <= now < e`.
  - **Every boundary** is built with `datetime.combine(d, t, tzinfo=ZoneInfo(tz))`, converted with `.astimezone(timezone.utc)`, and compared with `now` in UTC. Two datetimes sharing one `ZoneInfo` compare as wall times, which is wrong on the repeated autumn hour.
  - A time skipped by a spring change resolves one hour later (fold=0: 02:30 → 03:30). A repeated autumn time resolves to its first occurrence. That night's window is an hour shorter or longer.
- `source(hub, tz_path=None) -> Callable[[datetime], Hold | None]`: `lambda now: hold(now, hub.quiet(), owner_tz.read(tz_path)["tz"])`. This is what `create_app` wires.

### 4.2 Config, API and backup

- **Hub:**
  - `self._quiet = dict(DEFAULT)` is set in `__init__` **before** `_load_config`, so the environment seed's first `_commit` has it (Codex r4 #5).
  - At load, an absent `quiet` key (every config before this change) keeps the default silently. A present but invalid value logs one warning and reads as `DEFAULT`.
  - `_commit(channels, rules, quiet=None)` writes all three keys; `None` keeps `self._quiet`, so every caller (channel, rule, quick settings, seed, restore) preserves `quiet`.
  - `quiet()` returns a copy under the lock.
- **Quick settings:**
  - `quick_view(..., quiet)` adds `"quiet"`.
  - `apply_quick_settings` takes an optional `quiet`: absent keeps the saved value; invalid raises ValueError with `problem()`'s reason (400). It returns `(channels, rules, quiet)`.
- **API:** **both** GET and PUT `/api/notifications/config` add `"tz": owner_tz.read()["tz"]`, so the card's state after a save names the zone. The exact-reply test in `test_notification_config.py:695` gains `quiet`.
- **Backup:**
  - A new section, `notification_quiet`, exports `of(saved quiet)` plus `"tz"`, the owner zone at export. A hand-edited bad value exports as the default, never as something this version would refuse.
  - **Preflight:** `validate_import` runs `problem()` on it. A bad section makes the whole import invalid before anything applies.
  - **Restore:** `restore_backup` applies the four fields. If the section's `tz` differs from this box's owner zone, the report notes: "Quiet hours in this backup were set for <tz>; this NetTap uses <tz>. Times follow this NetTap's zone (Settings › Display)."
  - A backup without the section keeps the box's own setting.
  - It is added to `_VALID_SECTIONS`, `_restore_notifications`' list and `SECTION_LABELS` ("Quiet hours").

### 4.3 Dispatcher

- **Constructor:**
  - New arguments: `quiet: Callable[[datetime], Hold | None] | None = None` and `clock: Callable[[], datetime] = <utc now>`.
  - With `quiet=None`, nothing is ever held, so existing behaviour and tests are unchanged.
  - `create_app` passes `quiet_hours.source(notification_hub)` and keeps the dispatcher as `app["alert_dispatcher"]`.
- **Per channel, at the send decision:** `hold = self._quiet(self._clock())`. An exception is logged and read as None (fail open).
- **`_due(item, hold)`:** due if `hold` is None, or if `hold.critical_through` and the item is an alert (no `"event"` key) with severity 1. Otherwise held.
  - A held item gets `"held": true`, a plain JSON bool, kept by the merge by signature.
  - An item queued before this change has no flag and is classified by the same rule.
- **Alerts:** `due_alerts` / `held_alerts` are split from the merged, trimmed candidates.
  - **One `MAX_PENDING` cut over both,** so `pending` never exceeds 50 and a rollback to the old daemon cuts nothing (Codex r6).
    - The cut orders by rank, then worst first. Rank 0: alerts due inside a window (criticals coming through). Rank 1: held items. Rank 2: everything else.
    - So inside a window a critical is never cut for a held item. At the release, held items are kept ahead of fresh ones, and a fresh one that is cut comes back on the next poll, because it is still inside the 5-minute overlap.
    - With no quiet hours there is nothing held, and the cut is exactly today's.
  - A cut signature is not recorded and can come back on a re-read, exactly as today. That happens only while its alerts are still inside the next query's window, which overlaps by 5 minutes. After downtime, a 51st critical older than that is on the Alerts page only, as today (Codex r4 #2, #4; r5 #3).
  - **Stated limit:** past 50 distinct alert signatures held in one night, the least severe aren't in the release. They are on the Alerts page, where every message points.
  - **The merge keeps the worst observation whole** (Codex r4 #3, r5 #2).
    - When a fresh copy replaces a queued one, it keeps the queued copy's `attempts` and `held`.
    - If the queued severity was worse, the queued copy's `severity`, `signature`, `example`, `count` and `pairs` all stay together, and only `last_seen` moves on (for the cooldown).
    - So a critical held at 23:00 isn't reported as medium in the morning because a milder occurrence came at 04:00, and its line never pairs the critical's hosts with the medium's count.
    - This also stops a queued retry being downgraded today.
- **Events:** `events` is cap_queue's full kept list. `due_events` is `offered` filtered by `_due`, which inside a window is none, since no event is critical.
- **Send:** the existing logic runs on the due lists only:
  - the `retry_at` gate;
  - the early return and the post-limit status text;
  - the digest;
  - attempts, give-up and retry pace, computed from the items tried.

  Held items are carried over, flag and all, on every path.
- **The early return keeps `retry_at` while held items remain,** as it does for due ones. So a held-only poll can't clear a refusal throttle or the hourly slot, and a critical arriving later still waits for it (Codex r3 #4).
- **Release message:** when `hold` is None and any item in the due batch (alerts or events) has `"held"`, the message is a release. That is decided before the lines are fitted (Codex r4 #1). Held items are kept first by the cut, so a release can't lose them to fresh arrivals (Codex r5 #1).
  - When the release carries 50 held alerts (the queue was full, so the night may have had more), its footer adds "Quiet hours keep at most 50 alert types; see the Alerts page for all." The line is part of the tail that `digest` measures before choosing lines, so Pushover's 1,024 characters hold (Codex r6 #3).
  - It starts "Notifications held by your quiet hours setting:", taken off the `body_limit` room as the daily-limit notice is.
  - It lists data cap warnings first, then the rest worst first. At most 3 cap warnings are offered at once (one cap, one month; others are held by `cap_queue`), and 3 × 140 characters fit Pushover's 1,024. So a release never leaves an unshown cap warning to go one poll later.
  - Held items that don't fit the ten lines are in its "and N more", under the preamble.
  - A critical sent inside the window has no preamble, even if it was escalated from a held copy.
- **After a successful send:**
  - `pending = held_alerts`.
  - The event queue becomes `events` minus the due events this send acknowledged: the rendered ones, plus unrendered non-cap ones counted in "and N more". Cap warnings held by `cap_queue` and events held by quiet hours stay.
  - `overflow` goes with, and resets after, the first message that offers events.
- **Backlogs after the end:** the journal is read every poll, quiet or not, so held events are already queued when the window ends.
  - Only entries journaled in the last minute, or a backlog after downtime, arrive later. Those follow today's rule of up to 200 a poll, one message a poll, exactly as a burst does outside quiet hours.
- **Month end (stated limit):** a cap warning held on the month's last night is dropped by `cap_queue` at local midnight, before the morning release. As F6 decision 5, a warning for a month that is over can't change anything; the month's figure is on the Bandwidth page.

### 4.4 Web (`web/src/routes/settings/tabs/NotificationPrefsCard.svelte`)

- **The "Quiet hours" block,** below the switches:
  - the "Hold notifications overnight" switch;
  - when on, `input type="time"` From and To fields and the "Critical alerts come through" switch;
  - help text naming `tz`, with a link to `?tab=display`, saying held notifications arrive as one message when quiet hours end.
- **Wiring:**
  - `notifForm()` includes the four fields.
  - `applyNotificationConfig` reads `quiet` and `tz` from GET and PUT alike; the PUT sends `quiet`.
  - With the switch on, From equal to To, or a cleared field, shows an inline error and disables Save.
  - Turning the switch off puts back the last saved valid times, so `enabled: false` can always be saved (Codex r4 #6).
- **Design system:** existing `switch-row`, `field`, `input` and `field-help` classes only.

## 5. Failure model

| What fails | Result |
|---|---|
| `quiet` in the file is invalid (hand edit) | Read and exported as the default (off), with one warning at load. |
| Owner time zone file unreadable | UTC (owner_tz's one warning). Quiet hours shift until it is fixed. |
| `quiet` callable raises | Logged; everything is due (fail open). |
| Crash between a send and the saves | The message repeats, as today. Nothing is lost. |
| Restart or long downtime | The clock decides at the first poll: still inside a window, held; outside, released. |
| A release that keeps failing into the next night | Its items are held again for that night, then released in the morning. |
| Restore with a bad `notification_quiet` | Refused in preflight; nothing applies. |
| Rollback to a pre-#8 daemon | The old `_commit` drops `quiet` at its next save (quiet hours off until re-set). The old dispatcher ignores `"held"` and sends held items at the next poll. `pending` never exceeds its limit of 50, so nothing is cut. |

## 6. Tests

- **`test_quiet_hours.py` (new):**
  - Validation: each field, extra keys, `24:00`, start equal to end, a backup `tz` stripped, Arabic-Indic digits (`0٠:0٠`), and a trailing newline. The last two are also run through PUT and backup preflight.
  - `of()` falls back on bad input.
  - Across midnight: 23:30 and 01:00 inside, 07:00 and 12:00 outside, and the end on the right date. A same-day window (13:00–15:00). Disabled means None.
  - **Clock changes** in `America/New_York` and `Europe/London`:
    - a window spanning the change is an hour shorter in spring and longer in autumn;
    - an end inside the skipped hour, and instants on both sides of it;
    - an end on the repeated autumn hour, checked with UTC instants on its first and second occurrence (the window closes after the first).
- **`test_dispatcher_quiet.py` (new),** with a fake hub and a webhook channel, injected `clock` and `quiet`, and real JSON state files in `tmp_path`:
  1. An alert and a new device arriving inside the window are held: no send, `"held": true` on disk.
  2. A failure at 21:59 whose retry falls at 22:00 is held, with `attempts` unchanged.
  3. Past the daily limit, the hourly slot inside the window holds. A critical with `critical_through` off stays held.
  4. **A critical alert during a hold** is sent alone, without the preamble. Held items keep their flags, and an ordinary alert waiting on its retry is still queued, also across a restart.
  5. A refusal throttle set at 21:59, then a held-only poll at 22:00, then a critical at 22:01: the critical waits for the throttle, also across a restart.
  6. **At the end,** held alerts, new devices and data cap warnings go as **one** message starting with the held line, cap lines first.
     - A clipped Pushover channel with 2 cap warnings and 15 alerts gets exactly one POST across two polls.
     - With ten fresh high alerts at 07:00 and one held device or cap warning ranked eleventh, the message still has the preamble, and the cap warning is listed.
  7. **Edits:** quiet hours turned off mid-window release at the next poll; an end moved earlier releases at the new end; an owner zone change moves the window.
  8. **Restarts:**
     - a new dispatcher on the saved files, mid-window, keeps holding and releases once;
     - stopped at 06:55 and restarted at 23:00: held until 07:00;
     - a morning release failing until 23:00: held for the night, released the next morning.
  9. A held new-device event survives a critical send that didn't render it. Cap A changed to B during a hold, a critical sent, then A restored: A's warning is still queued and sent at the release.
  10. **Budget and merge:**
      - 60 held alerts: `pending` keeps the worst 50.
      - 51 distinct criticals mid-window, with a time-range-aware query fixture: 50 go; a 51st still inside the 5-minute overlap goes on the next poll, and one that has aged out doesn't.
      - A held critical (A → B, 1 event) whose signature recurs at 04:00 as medium (C → D, 800 events) is rendered, after a restart, as `- [critical] <sig>: 1 event, A → B`.
      - One held medium alert plus 50 fresh high alerts at 07:00: the medium is kept and the message has the preamble. The one fresh alert cut goes on the next poll.
      - A release with 50 held alerts on a Pushover channel: the payload has the full queue-limit line and stays within 1,024 characters.
  11. **Upgrade:** a pre-change `notification-dispatch.json` and `notification-events.json` (no flags) load and follow the rule.
  12. A `quiet` that raises means the item is sent. A slow alert query crossing 22:00: the decision uses the clock at send time.
  13. **Production wiring:** through `create_app`, with temp `notifications.json` (quiet hours on) and `owner-timezone.json` (`America/New_York`). `app["alert_dispatcher"]._quiet(t)` holds at 23:00 New York time and not at 23:00 UTC.
- **Existing tests:** dispatcher, hub, config and backup tests pass with `quiet=None`, except the quick-view exact reply, which gains `quiet`.
- **Hub, config, API and backup:**
  - `_commit` keeps `quiet` across channel, rule, quick and restore saves; an invalid file value reads as the default with one warning.
  - A config without `quiet` loads with no warning. A first start seeded from the environment writes the default `quiet`.
  - PUT with `quiet` absent keeps it; an invalid one is a 400 with the reason; GET and PUT both return `quiet` and `tz`.
  - Export of a valid and a hand-broken value.
  - Preflight refuses a bad section alongside a valid cap (`applied == []`, cap file unchanged).
  - Restore notes a zone mismatch; a missing section keeps the setting.
- **Web (Vitest):**
  - `notification-prefs-card.test.ts`: load, the switch showing the fields, the PUT body, unsaved detection, the From = To error, and the zone named after a save on a non-UTC box.
  - An invalid draft, then the switch turned off, then a save that works.
  - The BackupTab label.
  - The visual fixture's `CONFIG` gains `quiet` and `tz`; the Settings › Notifications snapshot is updated.

## 7. Gates

`/codex-review` (this plan) → build → `/deep-review` (daemon/api, backup) + `/ponytail-review` → two-angle review (security-engineer, Python and TypeScript reviewers) → `/verify` → PR → `gh pr checks` → merge → G11 deploy.

## 8. Deploy and G11 check (`scripts/remote/deploy-quiet-hours.sh`)

The live daemon is only read. Delivery is exercised in isolation, so no live config, cap, channel or journal is touched.

1. Baseline, pull `main`, build web and daemon. Recreate both containers and **stop if recreation fails**, then health-check (template).
2. **Image identity:** the running daemon's immutable image ID (`docker inspect nettap-storage-daemon --format '{{.Image}}'`) must equal the ID just built (`docker image inspect nettap/storage-daemon:latest --format '{{.Id}}'`) (Codex r3 #10).
3. **Live, read-only:**
   - `zoneinfo` works in the daemon container;
   - GET `/api/notifications/config` prints only `quiet` and `tz`;
   - the daemon log shows no quiet-hours warning.
4. **Isolated exercise:**
   - **Where it runs:** `docker run --rm -i --network none --entrypoint python3 <that image ID> - < scripts/remote/verify_quiet_hours.py`, with no mounts and no compose environment, loopback only.
   - **Setup, all in a temp directory:**
     - a prewritten `notifications.json`, so the hub never seeds from the environment, with only a webhook channel to the sink and a `data_cap` rule;
     - an empty env file;
     - an `EventJournal`;
     - an owner zone file (`Europe/London`);
     - an `AlertDispatcher` with injected `clock` and `quiet_hours.source(hub, tz_path)` (quiet hours 22:00–07:00);
     - an in-process HTTP sink on `127.0.0.1:0`, which records each POST's count, time and parsed `message`.
   - **Run:**
     1. Append 80% and 100% data cap events for a test cap, with `data_cap_now` matching.
     2. Poll at 23:00 and 06:59 London time: 0 POSTs, and both events queued with `"held"`.
     3. Poll at 07:00:30: exactly 1 POST, starting with the held line and containing both cap lines.
     4. Poll at 07:01:30: still 1 POST.
   - **Pass:** the script prints `QUIET-HOURS-OK` only after the last assertion, and the deploy script passes only on that line.
   - **A critical alert sent alone** needs OpenSearch alerts, so unit tests cover it (§6, case 4).
5. Daemon memory (`docker top`, after 5 min, per the F1/F4 lesson), logs, container status.

## 9. Risks

- **Clock-change nights.** Covered by the window tests (UTC instants, fold=0).
- **When the release goes:** on the first eligible poll after the end; polls run a minute apart, and the back-off and hourly slot apply.
- **A held alert's line shows the latest poll's count,** as a retried alert does today, but keeps its worst severity; the message points to the Alerts page.
- **More than 50 distinct alert signatures in one night:** the least severe aren't in the release, as today's queue limit. The release says the queue keeps at most 50, and they are on the Alerts page.
- **No eligible send in the open interval** (the channel throttled through it): the batch waits for the next one.
- **A blocked release after a full night** (50 held alert types, and the morning send fails, is refused or waits for the hourly slot for more than 5 minutes): fresh *non-critical* alerts that the cut leaves out drop out of the query's overlap and aren't sent; they stay on the Alerts page. Criticals always rank first when they may go (ponytail review), so a critical is never cut behind held items.
- **Owner time zone unreadable means UTC** until fixed.

**Effort:** S.

## 10. Round 1 changes (15 findings)

Taken, and still in the plan:
- **#2:** the next event queue comes from cap_queue's full kept list.
- **#4:** cap lines first in a release; the month-end drop is stated.
- **#6:** a fresh clock reading per channel.
- **#7:** UTC comparisons.
- **#9:** the held flag is plain JSON.
- **#10, #11:** backup preflight; validated export plus the zone note.
- **#13:** `tz` in GET and PUT.
- **#14, #15:** the isolated G11 check with a parsing sink.

Settled by §3.1 (no daily windows): #1, #3, #8.

Rejected:
- **#5 (summary vs hourly slot or back-off):** both are the channel's own limits.
- **#12 (destination change):** it is the owner's own action, behind the admin session.

## 11. Round 2 changes (11 findings)

Taken, and still in the plan:
- **#1–#3:** the back-off bypass is withdrawn.
- **#7:** one 50-alert cut.
- **#9:** the throwaway container and success marker.
- **#10:** wiring through `create_app`.
- **#11:** "first eligible poll" wording.

Settled by §3.1: #4 and #8 (no `released_through`, no `held_since`, no intake wait).

Rejected:
- **#5 (event trimming):** F1's count rule stands.
- **#6 (a signature crossing the cutoff):** the release tells the owner; the cooldown follows as for any delivered alert.

## 12. Round 3 changes (10 findings): simplified

- **The daily summary moved to a follow-up (§3.1).** That removes, with no replacement needed:
  - `held_since`;
  - `released_through` and its disk and upgrade contract;
  - the intake catch-up wait and its bound;
  - the two-group trimming with dated counts.

  This settles #1 (escalation consuming a release), #2 (the intake gate defeating due-first trimming), #5 (backlogs read after the cutoff), #6 (the unbounded wait), #7 (the empty cutoff), #8 (the `released_through` format) and #9 (a torn acknowledgement of the watermark).
- **#3 held counts** → in round 4, the alert cut count was dropped altogether; see §13.
- **#4 throttle cleared by a held-only poll** → the early return keeps `retry_at` while held items remain (§4.3, test 5).
- **#10 image identity** → the recreation must succeed, the running container's `.Image` ID must equal the built ID, and the verifier runs from that ID (§8).

## 13. Round 4 changes (8 findings, all taken)

- **#1 release detected too late** → decided from the whole due batch before sorting and fitting (§4.3, test 6).
- **#2, #4 the cut's `done` records** → the alert cut count is dropped. Trimming stays exactly as today: no record, re-read eligible, so the 51st critical goes on a later poll and no state grows. Past 50 signatures in a night is a stated limit (§4.3, §9, test 10).
- **#3 severity downgrade on merge** → the merge keeps the worse severity and its example (§4.3, test 10).
- **#5 hub start-up** → `_quiet` is set before loading; an absent key is silent; a present bad one warns (§4.2).
- **#6 hidden invalid times** → switching off puts back the last saved valid pair (§4.4).
- **#7 non-ASCII digits** → `fullmatch` with ASCII `[0-9]`, then `time.fromisoformat`, then compare (§4.1).
- **#8 the workaround** → removed; the open-interval behaviour is stated (§3.1, §9).

## 14. Round 5 changes (3 findings, all taken; the 5-round cap was reached)

- **#1 the trim erasing the release** → taken in round 5 as `held_cut`; replaced in round 6 by keeping held items first in the cut (§15).
- **#2 the merge mixing observations** → the worst observation's severity, signature, example, count and pairs are kept together; only `last_seen` advances (§4.3, test 10).
- **#3 the 51st critical's re-read** → the claim is qualified: it comes back only inside the 5-minute overlap, else it is on the Alerts page as today. The test uses a time-range-aware fixture for both cases (§4.3, test 10).

## 15. Round 6 changes (3 findings, all taken; the owner allowed this extra round)

All three were in `held_cut`, so it is removed instead of patched:
- **#1:** a count-only summary stranded with nothing queued.
- **#2:** overcounting when a cut signature comes back on the overlapping read.
- **#3:** its line clipped on Pushover.

**Replacement:** the cut keeps held items ahead of fresh ones (rank order, §4.3), so the overnight items reach the release. A fresh item that is cut returns on the next poll, inside the overlap.

**Disclosure** needs no counter. A release carrying a full queue of 50 held alerts adds a fixed line, measured by `digest`, saying the queue keeps at most 50 and where to see all.
