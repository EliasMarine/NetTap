# Plan: roadmap #5, "device went offline" alerts (NET-331)

_Final revision after round 6, 2026-11-20. Not approved within the owner's six-round cap (findings: 18, 14, 13, 12, 10, 5). Implementation proceeds on this revision under the owner's standing rule (take the recommendation). Branch `feature/f5-watched-devices` from `main` `a6668fd9`. Changes from round 0 are in §9–§14._

## 1. Goal

The owner can say "tell me if this device goes quiet" on either device page. NetTap then sends one message when a watched device has been silent longer than the owner's chosen time, and one "back online" when it is heard again. A "Watched devices" card on Devices shows each watched device's state.

- **Passive only** (decision D5): no ping.
- **Modes:** it works in mirror and DHCP gateway mode. Bridge mode can't tell devices apart (every frame carries the router's MAC), so there it is hidden and explained.
- **The rule above all others (D4):** every failure, gap or doubt may delay or miss a message, but must never invent one.

Roadmap source: `plans/2026-11-18-feature-roadmap.md` §8 #5.

## 2. Approach

### 2.1 What already exists (reused, not rebuilt)

- **F2 `DeviceDetailsStore`:**
  - `watch_after_min` is one of 15, 30, 60, 240 or 1440, with at most 50 watched;
  - a partial `PUT /api/devices/registry/{mac}/details`;
  - `export()`/`get()`, with `StoreUnavailable` when the file is damaged.
- **F1:** `Scheduler`/`Job`, and `EventJournal.append`, which is idempotent on `(type, key, instance)` and is the commit point (the data-cap pattern).
- **The dispatcher:** `event_item`, `_after_send`, `_trim`, the digest sort (`_cap_first`/`_worst_first`), and quiet hours, which hold every event.
- **Wire MACs** are lower case (`device_registry.py:731`). `terms` with both `size` and `include` is the existing pattern (`device_accounting.py:155`).
- **Predicates:** `_RESPONDED` (`devices.py`), `ESTABLISHED_STATES`, `CONN_RECORDS` and `CONN_ACCOUNTING` (`excluded_ips.py`).
- **The index:** `NETWORK_INDEX` (`pipeline_health.py`).
- **The capture mode:** `app["capture_manager"].mode` (a `CaptureMode` enum).
- **Fixed event rules:** `notification_config._EVENT_RULES`, the prefs card toggles and the rule editor's type list.

### 2.2 One clock: the last packet (`event.end`)

Round 4 replaced the two-clock table. Every conn record carries `event.end`, the time of its last packet: `@timestamp` + duration. Malcolm sets it on final and interim (`conn_long`) records alike, and the Live page already selects by it (`live_connections.py` `LIVE_WINDOW_FILTER`, NET-237). Every decision uses it, on conn records only (`CONN_RECORDS`). Every exchange has a conn record; DNS, DHCP and NTP records add nothing a conn record lacks.

| Value | Definition |
|---|---|
| `capture_at` | the newest `event.end` on a final conn record (`CONN_ACCOUNTING`, i.e. `conn.log`) in the last hour, at or before `now`: the newest packet capture has made searchable. Only `conn.log`: Filebeat reads that one file in order, so a record from late in it being searchable means earlier lines were shipped first. A slow batch for one device can't be overtaken by unrelated `conn.log` records beyond Logstash's worker reordering, which `LOG_DELAY` covers (round 5, finding 2) |
| `seen_at` (per device) | the newest `event.end` of the device's evidence: records it originated, plus records it answered (§2.3 step 6). It is used only for silence |
| `started_at` (per device) | the newest `@timestamp` (connection start) of the same evidence. It is used only to cross a boundary (round 5, finding 1) |
| `coverage_since` | the `capture_at` of the first successful check after any skip, failure or gap (§2.3 step 5) |

- **A backlog can't fake anything.** A drained backlog carries old `event.end` values, so it moves neither `capture_at` nor a device's `seen_at` past the real activity. A stopped or stub capture produces no new packets.
- **Recovery and enrollment need a connection that started after the boundary,** originated or answered by the device: `started_at > declared_at`, or `started_at ≥ enrolled_at`.
  - A peer's late packet on an older connection (a client still sending to an unplugged NAS) moves `event.end` but not the start, so it can't enroll or recover a device.
  - Old records indexed late fail both tests.
- **Every search has an upper bound,** `≤ now`, with `now` frozen once per run, so a record dated in the future after a clock correction can't count (round 5, finding 6).
- **Silence** = `capture_at − max(seen_at, coverage_since)`. It counts only time that capture actually covered (round 4, finding 2).
- **Writing delay** (round 4, finding 1). A packet at time *t* becomes a searchable record only when Zeek writes one: when the connection closes (TCP after at most its 5-minute inactivity timeout, UDP within a minute), or at the first `conn_long` checkpoint 10 minutes after the start, whichever comes first. So a device can look silent for up to `LOG_DELAY = 600 s` while it is active in a connection not yet written. An outage needs `silence > threshold + LOG_DELAY`. A 15-minute watch then fires 25 minutes after the last packet, plus the second check. One constant, grounded in Zeek's own timers.

### 2.3 Daemon: `daemon/services/watched_devices.py` (new)

**State file:** `/opt/nettap/data/watched-devices.json`, env `WATCHED_DEVICES_FILE`, mode 0600. It is written with `write_file_atomic` followed by an fsync of its directory.

```json
{"version": 1,
 "check": {"attempt_at", "success_at", "capture_at", "coverage_since",
           "skipped": null|"mode"|"pipeline"|"store", "error": null|"<fixed text>"},
 "devices": {"aa:bb:…": {
     "enrolled_at": "…", "after_min": 15, "state": "unknown|up|down", "since": "…|null",
     "seen_at": "…|null", "silent_from": "…|null",
     "incident": null | {"seen_at": "…", "declared_at": "…"},
     "pending": null | {"type", "key", "instance", "observed_at", "data"}}}}
```

**Loading the file:**
- **Missing:** start empty.
- **Unreadable, wrong version or wrong shape:** the job records `error`, changes nothing, and never overwrites it. The API reports it, and the card shows it. The fix, deleting the file, is in the tracking doc.

**A fix in the shared journal** (round 4, finding 9). Today, `EventJournal._load()` swallows a non-`FileNotFoundError` read error and starts from sequence 1 with no ids. A later append would then reuse sequence numbers in an existing journal, and could duplicate a pending watch event. The fix: such an error marks the journal unavailable.
- **Writers:** `append` raises `OSError` and retries the load until it succeeds. F1's producers already handle an `OSError` from `append` by retrying.
- **Readers** (round 5, finding 7): `after()` raises `OSError` too, and a new `available` property lets the dispatcher's `_take_events` return its queues and cursor unchanged while the journal is unavailable. Each such poll first tries `journal.reload()` off the loop, so recovery doesn't wait for a producer's append (round 6, finding 3). It never treats an unread journal as a reset (`last_seq < seq`), so neither the replay floor nor the cursor moves until a reload gives the real sequence.

**The job, `watched-devices`:** "Watched devices", every 300 s, with a 60 s deadline. `run(deadline)` follows the F1 contract:
- both searches use a client with `max_retries=0, retry_on_timeout=False`, with server-side and transport timeouts from `deadline − time.monotonic()`;
- it always ends by saving `check` (except when the file is unreadable), then re-raises any failure.

1. **Finish pending transitions:** append exactly what `pending` holds, including `observed_at`. A duplicate returns `None`. Then clear and save.
   - A pending whose `observed_at` is more than 24 hours old is dropped with a log line, not appended. A transition that couldn't be journalled for a day is no longer news (D4: miss).
   - A failed append raises; nothing new is evaluated while one is unfinished.
2. **Reconcile the watch list, before any gate** (round 4, finding 10):
   - read `details.export()`; `StoreUnavailable` gives `skipped: "store"`;
   - prune MACs no longer watched;
   - enroll new ones with `enrolled_at = now`;
   - record a changed `after_min`, which resets that MAC's `silent_from`.

   With no watches left: save a successful `check` and return before any search.
3. **Capture readiness** (round 4, finding 3), from the manager's own health (`get_health()`, run on the app loop from the job thread with a 5 s timeout):
   - **mirror:** `link_up` and `promisc_enabled`, and status neither `down` nor `not_configured`;
   - **DHCP gateway:** `link_up`, `routing_active` and status `normal` (round 5, finding 3). Its `degraded` includes a missing gateway address, route or firewall chain, so client traffic may not pass. Mirror keeps "not `down`": the G11's mirror logs ring-buffer warnings that aren't loss of coverage;
   - **bridge, the start-up `CaptureManagerStub` (`not_configured`), any other mode, or a health call that fails or times out:** `skipped: "mode"`.

   Presence isn't evaluated while not ready.
4. **Capture freshness:** `capture_at` must be within 600 s of now, or `skipped: "pipeline"`.
4a. **Capture scope** (round 5, finding 4).
   - `check.scope` = `"{mode}|{capture interface}"`, plus, in gateway mode, the gateway's subnet.
   - When it differs from the saved one, every watch is re-baselined: `unknown`, `enrolled_at = now`, the streak dropped, and coverage restarted. That only misses (D4).
   - A down device keeps its `incident` through the reset. When it is first heard under the new scope, `unknown → up` with a carried incident journals `device_online` for that incident. It is really seen, and the item supersedes a held "Offline" through the one-item-per-device rule (round 6, finding 4).
   - The scope is read again just before the commit; a change since the search drops the run's transitions.
5. **Coverage:** any skip or failure (steps 2–4 or the search) marks coverage broken, and clears every `silent_from`.
   - The next successful check sets `coverage_since = capture_at`. So does one whose `capture_at` is more than 900 s after the previous successful check's, which covers a daemon that was down.
   - Silence never includes time before `coverage_since`.
6. **One presence search,** on `NETWORK_INDEX`, `size: 0`: `CONN_RECORDS` and `event.end ≥ now−48h`, with `should` on two sides.
   - **`sent`:** filter `terms source.mac: [watched]` → `terms source.mac`, `size: len(watched)`, `include: [watched]` → `max event.end` and `max @timestamp`.
   - **`answered`:** filter `terms destination.mac: [watched]` and (`destination.packets > 0` or `destination.bytes > 0` or `conn_state ∈ ESTABLISHED_STATES`) → `terms destination.mac`, with the same size and include → the same two maxima. The query range is `now−48h ≤ event.end ≤ now`.
     - On an interim record, a cumulative reply counter with a recent `event.end` may come from the other side's retransmissions to a dead responder. That only delays an outage, by at most until Zeek gives up on the connection.
   - **The reply is refused, with no state change,** on `timed_out`, `_shards.failed > 0`, `_shards.total == 0`, or missing aggregations.
   - `capture_at` is a second, separate `max event.end` search over final conn records (`CONN_ACCOUNTING`), `now−1h ≤ event.end ≤ now`, on the same index (§2.2).
7. **Per MAC:** `seen_new` = the max `event.end`, and `started_new` = the max `@timestamp`, over both sides; then `step` (§2.4).
8. **Commit, serialised with watch edits:**
   - `DeviceDetailsStore.watch_is(mac, after_min)` holds the store's lock and yields whether the watch still has the value used;
   - inside it, either drop the transition, or save the state with `pending` and fsync the directory;
   - the lock is released before the journal append.
9. **Then** append to the journal (which fsyncs), and clear `pending` and save.

### 2.4 The state machine (`step`)

`threshold = after_min × 60 s + LOG_DELAY`, with `silence = capture_at − max(seen_at, coverage_since)`.

| From | Condition | To | Journal |
|---|---|---|---|
| `unknown` | `started_new ≥ enrolled_at` | `up`, `seen_at = seen_new`, `since = now`, `incident = null` | `device_online` only if an incident was carried through a scope reset; otherwise none |
| `unknown` | otherwise | `unknown` | none |
| `up` | `silence ≤ threshold` (after `seen_at = max(seen_at, seen_new)`) | `up`, `silent_from = null` | none |
| `up` | over threshold, `silent_from` null | `up`, `silent_from = capture_at` | none |
| `up` | over threshold, `silent_from` set in this coverage, `capture_at − silent_from ≥ 240 s` | `down`, `since = now`, `incident = {seen_at, declared_at: now}` | `device_offline` |
| `up` | over threshold, `capture_at` advanced less than 240 s | unchanged | none |
| `down` | `started_new > incident.declared_at` | `up`, `since = now`, `seen_at = seen_new`, `incident = null` | `device_online` |
| `down` | otherwise | `down` (incident frozen) | none |

- **Event ids:**
  - `device_offline`: key = the upper-case MAC, instance `"down|" + incident.seen_at`;
  - `device_online`: instance `"up|" + incident.seen_at`.
- **Event data:**
  - `device_offline`: `{mac, name, after_min, seen_at}`;
  - `device_online`: `{mac, name, after_min, seen_at: incident.seen_at, back_at: started_new, away_min}`.
  - `back_at` is the qualifying connection's start, `started_new`.
  - `away_min` = `back_at − incident.seen_at` in whole minutes. It is positive by construction: `back_at > declared_at > seen_at`.
  - `name` is the owner's own name or null.
  - `observed_at` is frozen in `pending`.

### 2.5 Notifications

- **`notification_config`:** event type `watched_device`; fixed rule `QUICK_WATCHED = "settings-watched"` in `_EVENT_RULES`, on by default at `min_severity: 4`; a `watched_device` flag in `quick_view` and `apply_quick_settings`.
- **`notification_hub.delete_rule`** keeps a disabled record for every `_EVENT_RULES` key, so a deleted rule stays off.
- **Web Settings:**
  - the prefs card gets the toggle "Tell me when a watched device goes offline or comes back";
  - the rule editor lists `watched_device` as a fixed-severity type (min 4), so owners with custom channels only can route it.
- **`event_item`** maps `device_offline` and `device_online` to `watch_item(entry)` in `watched_devices.py`. Items carry `seq` (journal order) and their own time in the line:
  - **offline:** severity 2, "Offline: {label}", "{label}: no sighting since {seen_at short}, longer than its {after} limit";
  - **online:** severity 4, "Back online: {label}", "{label}: seen again at {back_at short}, {away} after the last confirmed sighting".
  - **`label`:** the owner's name, re-checked as one line with no control or bidi characters and clipped to 64, plus the MAC; or the MAC alone. Device-supplied DHCP or mDNS names are never used.
  - A wrong-shaped `data` gives `None`.
- **One queued item per device, the newest** (round 3, findings 6 and 7, replacing round 2's ordering).
  - When `_take_events` admits a watch item for a MAC, any older watch item for that MAC is removed from **every** channel's queue *before* the new item is routed (round 4, finding 6). So a channel that takes only high alerts can't keep an "Offline" whose low "Back online" was routed elsewhere.
  - **Catch-up guard** (round 4, finding 7; round 5, finding 8): watch items are released only by a poll whose journal read succeeded and returned fewer than `INTAKE` entries, so it reached the end. A full page, a read error or an unavailable journal holds them. Alerts and other events are unaffected. So an "Offline" never goes out before a "Back online" that is already journalled.
  - So a channel never holds two transitions for one device, and no message can report them out of order, whatever the line fitting or character limit does.
  - Overnight, "offline 01:00, back 02:00, offline 03:00" becomes one morning line, "Offline" since 03:00. "Offline 01:00, back 02:00" becomes "Back online at 02:00, 61 minutes after the last confirmed sighting", which says it was away.
  - Every transition is still in the journal (for #1) and on the card.
- **Carry-over:**
  - `_after_send` keeps unshown items whose event is in `CARRY_OVER = {"data_cap", "watched_device"}`, so a full message can't silently retire a device's item. There is at most one per watched MAC, at most 50.
  - The digest keeps its ordinary severity order (`_worst_first`), so recoveries (low) never push out a medium or high security alert.
  - `_trim` still applies.
- **Quiet hours** hold them overnight, as for every event.

### 2.6 API

**`GET /api/devices/watched`** (new `daemon/api/devices_watched.py`).

```json
{"check": {…}, "devices": [{"mac", "name", "after_min", "state", "seen_at", "since"}]}
```

- **The list** comes from the details store, merged with state, read off the loop. `since` is the state-entry time. `seen_at` is the last confirmed sighting: the incident's when down.
- **There is no registry lookup** (round 2, finding 12): the card always links to `/devices/mac/<mac>`, which already handles a MAC it doesn't know.
- **Errors:** a damaged store gives a fixed 503; an unreadable state file gives `check.error`, with devices listed as `unknown`.

**The watch-only clear:** in `device_custom.handle_set_details`, a body of exactly `{"watch_after_min": null}` skips the "device must be known" check, so a watch restored from a backup can be cleared and its slot freed. Group, owner and notes are untouched. Every other details PUT still needs a known device.

### 2.7 Web

- **`web/src/lib/api/devices-watched.ts`** (new): `getWatchedDevices()`, `setWatch(mac, minutes | null)`.
- **`DeviceCustomise.svelte`**, on both device pages:
  - a "Watch" button and an inline panel: Off, 15 minutes, 30 minutes, 1 hour, 4 hours, 1 day;
  - a hint that devices with long quiet spells or single long transfers need a longer time;
  - a randomised-MAC note;
  - hidden in bridge mode, with the reason.
  - **Writes use the canonical MAC:** the IP page passes F2's `registry_mac`.
  - **Both page callbacks merge the returned `watch_after_min`,** including `null`, through their existing "same device" guard.
- **`web/src/routes/devices/WatchedDevicesCard.svelte`** (new), presentational. `devices/+page.svelte`'s existing guarded loader fetches the data and passes it in; the card never calls `registerPageRefresh`.
  - **Table:** a sortable `DataTable` with Device, State, Alert after, Last seen, Since, and "Stop watching".
  - **States:** `CardState` for loading, empty and error.
  - **Banners:**
    - **Stale or error:** when `success_at` is more than 15 minutes old, or `error` is set;
    - **Paused:** for `skipped: "pipeline"` ("no new traffic has been indexed for 10 minutes") and `skipped: "mode"` ("capture isn't ready: {reason}"), shown at once, even before any successful check, with "Stop watching" still available (round 4, finding 11);
    - **Bridge mode:** the card is hidden, with the reason.
- **Design system:** `web/DESIGN-SYSTEM.md` first, tokens only, then `check:colors` and the visual tests.

### 2.8 Deploy and G11 check

**`scripts/remote/deploy-watched-devices.sh`,** in the mandatory template. It never forces a run on the live daemon, never writes a watch, and sends nothing.

1. **Before:** `free -m`, `docker stats`, and the settled daemon memory.
2. **Pull, build, recreate:** image IDs, health.
3. **Production, read only:**
   - poll `GET /api/jobs` for a `watched-devices` run that finished after the recreate, for up to 7 minutes. It must have no `last_error`;
   - then `GET /api/devices/watched`: 200 and the shape. `check.attempt_at` must be after the recreate, with either `success_at` equal to it or an expected skip (`mode`, `pipeline`, or no watches) printed. A `check.error` fails (round 3, finding 11);
   - `GET /api/notifications/config`: the `watched_device` flag is present.
4. **Live probe on the real index, in memory only:** `scripts/remote/probe_watched_devices.py` in the daemon container.
   - **Samples** (round 5, finding 10; round 6, finding 5): from raw final conn hits with `event.end` in the last 5 minutes, `@timestamp` at or after the probe's `enrolled_at` (15 minutes back), and six-octet MACs. A connection that started earlier but ended recently is printed as an expected `unknown` (negative case). Up to 3 originators (`source.mac`) and up to 3 responders (`destination.mac` on a record with replies), never from the registry or other datasets. A side with no sample is reported as inconclusive, not a failure.
   - **Setup:** temp details store, temp journal, temp state with `enrolled_at` 15 minutes back. No dispatcher.
   - **It checks:**
     - the real search succeeds;
     - every sample is `up`, with `seen_at` within 10 minutes;
     - the bucket keys come back lower case;
     - an unused locally administered MAC stays `unknown`;
     - the datasets carrying the samples are printed.
5. **Isolated verifier:** `scripts/remote/verify_watched_devices.py`, in a throwaway image copy with no network, against a stub client. It covers every `step` row, the two-phase crash cases, the skips, refused replies, the streak gap, the threshold change, and the watch-only clear. It prints `WATCHED-DEVICES-OK`.
6. **After:** settled memory, logs, status.

**Owner check:** watch a smart plug at 15 minutes, and wait until the card shows it "Online". Then unplug it and time the alert: expect about 30–35 minutes (15 minutes, plus the 10-minute writing allowance, plus two checks). Plug it back in for "Back online".

## 3. Key decisions and trade-offs

- **D1:** a state file with a two-phase commit and directory fsync, beside the journal.
- **D2:** a Settings toggle, so the rule can be turned back on, consistent with the other two.
- **D3, one clock:** the last-packet time `event.end`, on conn records (§2.2). Silence counts only covered time, and allows Zeek's own writing delay.
- **D4, made precise in round 4.** NetTap's own failures must never produce a message: a stalled or backlogged pipeline, a capture that isn't ready, a coverage gap, lost or unreadable state, a partial search, a crash. Those all pause or miss.
  Ambiguities in the network itself are accepted limits (§4), handled by the owner's choice of time, and measured on the G11 before any ping (decision D5) is considered. Those are a device whose only traffic is one connection outliving every checkpoint, or replies attributed to a router on a trunk mirror. The roadmap took passive detection on that basis.
- **D5:** the answered side uses every conn record with a reply. A cumulative counter on an interim record can only delay an outage.
- **D6:** one hub event type, with severity per item.
- **D7:** only the owner's own name goes into messages.
- **D8:** one queued item per device (the newest), carried over, in ordinary severity order.
- **D9, simplicity over completeness.** Packet-count deltas (round 2, finding 6), a synthetic index on the device (round 2, finding 14) and per-line ordering inside the fitter (round 3, finding 6) were each replaced by something smaller: crediting interim records only toward "still up", and coalescing to one item per device.

## 4. Risks and accepted limits

- **A device whose only traffic is one connection** is seen at each `conn_long` checkpoint (10 min, 30 min, 1 h, 12 h, 24 h, 3 d, then none: `tracking-fixes/2026-11-09-net-237-data-honesty.md`). It can be declared offline in a gap longer than its watch, most of all between 24 h and 3 d. Deferring outages for open connections would need a join on `zeek.uid` between interim and final records, rejected under D9. The panel hint covers it.
- **A router-trunk mirror** can attribute a routed reply to the router's MAC (`tests/test_answer_only_devices.py`). A device that only ever answers requests routed from another VLAN is then never credited. Suppressing that by IP-to-MAC association is a topology-specific mechanism, rejected under D9. The G11 is a plain uplink mirror.
- **Activity between the owner's click and the first run** isn't counted toward the first sighting.
- **Spoofing** (security review, I1): a LAN host sending frames with a watched device's MAC keeps it Online, or produces "Back online", which also supersedes a held "Offline". The feature reports silence, not tampering; the panel hint says so.
- **A flapping device** (security review, L2): a device that sleeps just past its threshold sends "Offline" and "Back online" each cycle, up to about 80 a day on a 15-minute watch. Past the channel's daily budget, messages fall back to the hourly digest, so they're delayed, not lost. The owner sees the noise and lengthens or stops the watch. No per-device cap in v1.
- **A device whose only traffic is one sparse heartbeat** (one-way UDP every 59 minutes on a 1-hour watch) can be declared offline when a single frame is lost. The G11's NIC misses a few frames under load. The panel hint asks for a time at least twice the device's quietest gap. Gating outages on loss counters overlapping a silence interval was rejected under D9 (round 6, finding 2).
- **A stall in the `conn_long.log` feed alone,** while `conn.log` stays current, can let a long transfer's checkpoints arrive late. Filebeat ships both files from one container and one pipeline, so a stall that hits one file only is unusual. Per-file indexing progress isn't available to the daemon, so it isn't gated (round 6, finding 1). The capture-freshness check still catches a whole-pipeline stall.
- **A watch turned off and on between two runs** keeps its state.
- **8-octet DHCP `chaddr`:** conn records carry the 6-octet MAC.
- **Phones that sleep, randomised MACs:** documented in the panel.
- **The first-ever creation of the journal file** isn't directory-synced. F1 created it on every existing box.

## 5. Verification plan

**Daemon pytest:**
- **`tests/test_watched_devices.py`:**
  - every §2.4 row;
  - the §2.2 cases: a backlog with old `event.end` values doesn't make capture live, recover a device, or enroll one; interim `conn_long` records on either side keep a device up;
  - the streak is cleared by a skip, a failure and a capture gap over 900 s;
  - a restart straight into a fresh pipeline needs two new checks;
  - a manual run seconds later doesn't count as a check;
  - enrollment: activity before the first run that sees the watch doesn't count; the first sighting after it does;
  - the mixed-delay timeline: last packet 12:00, active in a connection 12:14–12:22 written at 12:23, other traffic advancing `capture_at`, checks at 12:16 and 12:21 → no offline (the `LOG_DELAY` allowance);
  - a peer's late packet: NAS replies at 12:00 and is unplugged, the watch begins 12:01, the client sends at 12:02 on the same connection → the NAS stays unknown; likewise no recovery after a declaration;
  - a future-dated record and a valid current one: the future one is ignored;
  - gateway `degraded` with fresh traffic → skipped; a scope change (mirror → gateway) re-baselines every watch;
  - a journal unavailable at start-up: a dispatcher poll before any producer append keeps its cursor and replay floor; a page-two read error holds watch items while alerts still go;
  - a scope reset while down: the first sighting under the new scope journals `device_online` for the carried incident;
  - the journal recovers without any producer append: the next dispatcher poll reloads it and delivers;
  - the coverage gap: a 1-hour watch last seen 11:55, capture down 12:00–14:00, checks at 14:05 and 14:10 → no offline (silence starts at `coverage_since`);
  - readiness: mirror with promiscuous mode off but fresh broadcasts → skipped; gateway with routing off → skipped; a `CaptureManagerStub` → skipped; a health call timeout → skipped;
  - a skip still prunes a removed watch and enrolls a new one;
  - no watches: zero searches, successful `check`;
  - a stub manager, and gateway mode with routing off: skipped, streaks cleared;
  - a pending older than 24 hours is dropped;
  - a NAS whose only evidence is `conn_long` interim records with replies stays up;
  - the lock, in both orders, with barriers: an edit committed first suppresses the transition; with `watch_is` acquired first, one transition persists under the old value, then the waiting edit completes (round 4, finding 12);
  - the journal load failure: a non-`FileNotFoundError` read error at start-up makes `append` raise until a reload succeeds, so a pending replay can't write sequence 1 into an existing journal (round 4, finding 9).
  - one run through the real `Scheduler` with its deadline;
  - a threshold change and a clear during the search drop the transition;
  - the crash cases: before the append, after the append, a failed first save, a restart while down (the frozen incident gives the same recovery id);
  - an unreadable state file is never overwritten;
  - refused replies: timeout, shard failure, zero shards, missing aggregations;
  - the query body has `size` and `include` on both sides, lower case;
  - A→B: B not credited; a `conn_long` cumulative responder isn't credited; S0 isn't.
- **`tests/test_dispatcher_events.py`:**
  - severities and lines, label fallback, bad data;
  - quiet hours;
  - down → up → down for one MAC while held leaves one queued item, the newest;
  - 11 outages at a 1,024-character limit (Pushover): the unshown ones go out in the next message;
  - a high-only channel and an all-severity channel: offline then online for one MAC leaves no "Offline" queued on the high-only channel;
  - journal entries 200 (offline) and 201 (online) read across two polls: no "Offline" is sent before 201 is read.
  - 10 recoveries plus one medium alert: the alert's line is rendered;
  - a flapping device is trimmed.
- **Notification config and hub:** the default rule; the flag; delete → restart → still off → the toggle turns it back on; delivery through a custom-channel rule.
- **`tests/test_devices_watched_api.py`** and the details API's watch-only clear.

**Web Vitest:**
- the API client;
- `DeviceCustomise`;
- both device pages: save, clear, reopen, `registry_mac`;
- `WatchedDevicesCard`: rows, sort, stop, stale, paused, bridge, empty, error;
- the devices page refresh reloads both the inventory and the card;
- the prefs card and rule editor.

**Visual:** the devices layout with the populated fixture.

**Gates:** all suites, svelte-check, check:colors, shellcheck, `/deep-review`, `/ponytail-review`, the two-angle review, and the G11 deploy.

## 6. Rollback and migration safety

**No migration.** The new things are `watched-devices.json`, two journal types, one fixed rule and a toggle.

**After a downgrade to the previous daemon** (round 2, finding 11, corrected):
- **Unread journal entries** of the new types are skipped: its `event_item` returns `None`.
- **Watch items already in a channel's saved queue** go out through the surviving rule by its rules. A message shows up to ten lines, and any further due events are counted in "and N more" and dropped, because the old dispatcher carries over only data-cap warnings. A crash between its send and its save can repeat one message; that's its existing behaviour (`notification_dispatcher.py` module docstring).
- **A `pending` transition in the state file** (only after a crash mid-commit) is ignored by the old daemon. When #5 returns, it is appended with its original `observed_at` if that is under 24 hours old, and dropped otherwise (§2.3 step 1).

Not tested against the old code: it isn't in the suite. The rule left in `notifications.json` is harmless (`rule_ok`, shape-only backup checks).

## 7. Observability

- **`check`** in the state file, shown by the card and API.
- **The job record.**
- **Logs:** transitions at INFO, MAC and state only; skips once per change of reason; failures at WARNING.
- **Journal entries:** the UI says "journalled", not "sent".

## 8. Out of scope

- Ping (D5).
- Schedules.
- Devices without a MAC.
- #9's groups and owner UI.
- #1's counts.
- Bridge mode.
- Escaping device-supplied text per channel.
- The dispatcher's replay shortcut, a separate slice.

## 9. Round 1 changes (Codex round 1, 18 findings)

| # | Finding | Change |
|---|---|---|
| 1 | Crash windows lose or repeat a recovery | `pending` two-phase commit, finished first; the recovery id is tied to the incident |
| 2 | `mode == "bridge"` is never true; a read failure proceeds | `capture_manager.mode` must be MIRROR or DHCP_GATEWAY; anything else skips |
| 3 | Late-indexed records fake a recovery; cumulative `conn_long` counters | Recovery by activity time after `declared_at`; final conn only on the answered side |
| 4 | Two checks over a stalled pipeline; manual runs | Superseded by round 2: capture time from `@timestamp`, 240 s apart, streak rules |
| 5 | Case, buckets, A→B credit | Lower case, `size` and `include`, a full predicate per aggregation, a live probe |
| 6 | Index override, zero-shard reply | Shared `NETWORK_INDEX`; refused replies |
| 7 | Enrollment identity | `enrolled_at` (backdated one interval in round 2); a commit check |
| 8 | "And N more" drops watch events | Carry-over (ordered in round 2) |
| 9 | Custom-channel owners | The rule editor type |
| 10 | Delete recreates the rule | `delete_rule` uses `_EVENT_RULES`; the toggle |
| 11 | Replay shortcut | Out of scope |
| 12 | Discovered names in markup | Only the owner's name |
| 13 | Child page refresh | The parent loader |
| 14 | `onsave` MAC and stale watch | `registry_mac`; merge including null |
| 15 | Orphan watch | Watch-only clear; "Stop watching" |
| 16 | Stale "Online" | `check` saved on every run; stale banner |
| 17 | G11 check writes watches | Read only, plus a probe with temp stores |
| 18 | Rollback outcomes | Documented (corrected in round 2) |

## 10. Round 2 changes (Codex round 2, 14 findings)

| # | Finding | Change |
|---|---|---|
| 1 | Incident state lost on restart; `last_heard` advances while down | `incident {seen_at, declared_at}` persisted and frozen while down; `observed_at` in `pending`; times stated, not subtracted |
| 2 | Enrollment at the first poll; pre-enrollment traffic | `enrolled_at = first run − 300 s`; enrollment needs activity time (`@timestamp`) at or after it |
| 3 | Commit under a changed threshold | The commit check compares `after_min`; a change resets the streak; the microsecond window is accepted |
| 4 | A draining backlog advances ingest time; stub mode | `capture_at` from `@timestamp`: a backlog or stub can't make capture look live |
| 5 | The streak survives gaps | Cleared by any skip or failure, and by a gap over 900 s between successful runs |
| 6 | Responder in one long transfer | Packet deltas rejected. Superseded in round 3: interim records count toward "still up" (§11 #4) |
| 7 | `answered` default size 10 | `size: len(watched)` on both sides |
| 8 | Reordered transitions across a digest | Superseded in round 3: one queued item per device (§11 #6) |
| 9 | An unreadable state erases `pending` | Only a missing file starts empty; an unreadable one is never overwritten |
| 10 | No directory fsync | fsync the directory after each state save |
| 11 | Downgrade claim wrong | Corrected in §6 for all three persisted forms. **Rejected:** a test against the pinned old code |
| 12 | Registry failure hides the card | No registry lookup; always link to the MAC page |
| 13 | Smoke check forces a real run | Poll for a natural run; forced runs only in the probe |
| 14 | Probe samples from the registry | Samples from the index's recent `source.mac`; too few is reported, not failed. **Rejected:** a disposable index on the device, since writing to OpenSearch there is a side effect |

## 11. Round 3 changes (Codex round 3, 13 findings)

| # | Finding | Change |
|---|---|---|
| 1 | Wall-clock silence under indexing lag | `silence = capture_at − seen_at`; the ingest-time claim corrected |
| 2 | Backdated enrollment invents a sighting | `enrolled_at` = the first run; the owner check waits for "Online" |
| 3 | Fresh records with an inactive mode | Skip the stub, and gateway mode with routing off; streaks cleared |
| 4 | The rejected responder case exceeds every threshold | Taken: interim records with replies count toward "still up" (delay only) |
| 5 | The settings race gives a second message | `DeviceDetailsStore.watch_is` holds the store lock over the check and the pending save |
| 6 | Line fitting reorders a device's transitions | One queued item per device, the newest |
| 7 | A watch block outranks security alerts | Ordinary severity order kept |
| 8 | Compaction defeats pending dedupe | A pending older than 24 hours is dropped |
| 9 | An empty watch list builds an invalid query | Return before any search |
| 10 | The `run(deadline)` contract | Specified: deadline-derived timeouts, a non-retrying client, a test through the Scheduler |
| 11 | The smoke gate passes a failed run | No `last_error`; `check.attempt_at` after the recreate, with success or an expected skip |
| 12 | The duration was dropped | `away_min` from the frozen values, always positive |
| 13 | "Since" duplicated "Last seen" | A state-entry `since` |

## 12. Round 4 changes (Codex round 4, 12 findings)

| # | Finding | Change |
|---|---|---|
| 1 | One fresh stream doesn't bound another's writing delay | One clock, `event.end`, plus the `LOG_DELAY = 600 s` allowance grounded in Zeek's timers (§2.2) |
| 2 | A known coverage gap counts as silence | Silence starts at `coverage_since` |
| 3 | A failed mirror setup passes readiness | The manager's health: `link_up` and `promisc_enabled` for mirror, `routing_active` for gateway; the stub is `not_configured` |
| 4 | No daily checkpoint; ingest time as "sighting" | `event.end` replaces ingest time everywhere. The 24 h–3 d gap is documented. **Rejected:** deferring for open connections (needs a `zeek.uid` join) |
| 5 | Router-trunk mirror attributes replies to the router | **Rejected** as a topology-specific mechanism; documented (D4 made precise) |
| 6 | A high-only channel keeps a stale "Offline" | Coalesce across every channel before routing |
| 7 | Journal page boundary | Watch items wait while intake is behind |
| 8 | Pending expiry vs compaction | §6 wording fixed. **Rejected:** a journal-position check; a just-appended id is the newest line and can't be evicted within one 5-minute retry unless 50,000 lines arrive in between |
| 9 | Journal load failure reuses sequences | Shared fix: unavailable until a reload succeeds |
| 10 | A mode pause stretches the off/on race | Reconcile watches before any gate |
| 11 | The card hides a mode pause | A paused banner for `mode`, shown at once |
| 12 | The impossible lock-test ordering | Both orders, with barriers |

## 13. Round 5 changes (Codex round 5, 10 findings)

| # | Finding | Change |
|---|---|---|
| 1 | A peer's packet enrolls or recovers a device | Boundaries need a connection that started after them (`started_at`, from `@timestamp`); silence keeps `event.end` |
| 2 | `LOG_DELAY` doesn't bound indexing | **Rejected as a mechanism.** `capture_at` uses `conn.log` records only, a single file Filebeat ships in order, so a later line being searchable means earlier lines were shipped first. Logstash worker reordering is seconds, within `LOG_DELAY` |
| 3 | Gateway `degraded` passes | Gateway needs `normal`; mirror keeps "not `down`" (the G11's ring-buffer warnings) |
| 4 | A capture reconfiguration keeps old baselines | `check.scope`; a change re-baselines every watch and drops in-flight transitions |
| 5 | Packet-loss counters ignored | **Rejected.** The G11's NIC routinely misses a few frames under load (`device-live-bandwidth` notes). An outage needs every one of a device's records over 25 minutes or more to vanish, which a small loss rate can't do, and gating on any increase would stop the feature. A collapsed capture shows in health and freshness |
| 6 | Future-dated evidence | `≤ now` on both searches, `now` frozen per run |
| 7 | The journal fix lets the dispatcher reset its cursor | `available` property; `after()` raises; `_take_events` leaves the cursor and replay floor alone |
| 8 | A failed second page releases an "Offline" | Release only after a successful read that reached the end |
| 9 | Compaction during a downgrade | **Rejected again, with the corrected reason.** Compaction drops lines older than 120 days or beyond the newest 50,000. A pending is replayed only within 24 hours, and evicting a line that young needs 50,000 newer lines in a day; a home network produces hundreds |
| 10 | Probe samples the wrong population | Raw final conn hits with six-octet MACs, originators and responders separately; a missing side is inconclusive |

## 14. Round 6 changes (Codex round 6, 5 findings; final round)

| # | Finding | Change |
|---|---|---|
| 1 | A stalled `conn_long.log` feed with a current `conn.log` | **Documented limit** (§4). Per-file indexing progress isn't observable from the daemon |
| 2 | One lost heartbeat on a sparse device | **Documented limit** with the panel hint (time at least twice the quietest gap). Loss-counter gating was rejected under D9 |
| 3 | A recovered journal can stay unavailable | The dispatcher's poll tries `reload()` while unavailable |
| 4 | A held "Offline" survives a scope reset | The incident is carried through the reset; the first sighting journals `device_online`, superseding the held item |
| 5 | The probe samples connections that started before its enrollment | Positive samples need `@timestamp ≥ enrolled_at`; early-start, recent-end is the negative case |
