# Plan Review Log: NET-160 slice 2b-3 (Devices KPI window)
Started 2026-11-06 (session a60131fc). MAX_ROUNDS=5. Codex session: .codex-review/2026-11-06-164706-slice2b3

## Round 1 - Codex

The plan needs revision in five places. These findings concern consistency within a page and request handling; they do not revisit the pending live-versus-snapshot decision.

1. **High — Total devices can still disagree with its own table.**
   - **Evidence:** Plan B.3 retains `getDeviceCount(win)`, while A.4 introduces the list’s `total`. This contradicts the stated tradeoff: “Within one page, one search should answer both.” The current loader updates list and count independently (`web/src/routes/devices/+page.svelte:220–226`).
   - **Impact:** A device’s third connection arriving between searches produces, for example, 28 rows and “Total devices: 29.” Independent refresh failures can also combine an old list with a new count.
   - **Fix:** Populate Total devices from `DeviceListResponse.total` and update it atomically with the list and its window. Remove the separate total-count request. Test refresh failures and atomic retention/clearing of this state.

2. **High — Failed alert searches can still produce successful, incorrect lists.**
   - **Evidence:** Plan A.3 checks only `_lan_device_buckets`. The alert search remains unchecked at `daemon/api/devices.py:620–638`: it catches transport exceptions but accepts `timed_out`, failed shards, and missing aggregations, defaulting absent counts to zero.
   - **Impact:** A healthy device composite followed by an incomplete alert search returns understated alert figures. With `sort=alerts`, it can select the wrong devices before applying `limit`, despite the plan’s promise that incomplete searches return 502.
   - **Fix:** Validate every alert-count response, including both nested bucket lists, and propagate failures through the handler’s `QueryFailed` response. Add timeout, failed-shard, and missing-aggregation tests specifically for the alert-search stage.

3. **Medium — Online now and table status use different clocks and different reads.**
   - **Evidence:** Plan B.3 captures the cutoff before loading. Table status uses `Date.now()` when evaluated and a strict `< ONLINE_MS` comparison (`web/src/routes/devices/+page.svelte:358–366`); the count uses `last_seen >= cutoff` (`daemon/api/devices.py:1612–1618`).
   - **Impact:** A device last seen 4m59s before loading can count as Online but render Idle after a two-second request. Exact boundary timestamps also disagree. Separate searches introduce another membership race.
   - **Fix:** Return `online_total` and its cutoff from the same pre-limit device buckets, and use that cutoff with identical boundary semantics for table status. Test a delayed response crossing five minutes and a timestamp exactly at the cutoff.

4. **Medium — Home’s new link window has no specified reset on range changes.**
   - **Evidence:** Plan C adds `deviceCountWin` and selects the exact-window link whenever it exists. Home’s existing `changeRange()` clears `deviceCount`, but naturally has no reset for this new state (`web/src/routes/+page.svelte:192–205`). The plan’s Home tests cover initial loading, not subsequent range changes.
   - **Impact:** After loading 24h and selecting 7d, the card can link to the previous 24h window while the new count is pending—or indefinitely if it fails.
   - **Fix:** Store the count and its window together, clearing both on range changes and updating both on guarded success. Test clicking during a subsequent range load and after its failure.

5. **Medium — Deployment verification can pass while browser API requests time out.**
   - **Evidence:** Plan E measures direct daemon calls and checks only the `/devices` HTML route through nginx. Devices APIs receive the default **10-second** proxy timeout (`web/src/lib/server/daemon.ts:46–55`; `web/src/routes/api/[...path]/+server.ts:22–35`). The page fetches its data after mounting.
   - **Impact:** A 12-second list request can pass the direct daemon check and the HTML route check while failing in the actual UI. Printing timing alone does not make this a failed deployment check.
   - **Fix:** Add an authenticated check through nginx/SvelteKit for the actual `/api/devices?from=…&to=…&limit=500` request, including the 30-day window, and require a successful JSON response within the configured timeout.

VERDICT: REVISE
### Claude response

All five taken.

1. **Total devices from the list reply.** The list reply carries `total`. The page's `getDeviceCount` calls go, and its state is one atomic `loaded` object.
2. **The alert-count stage is checked:** `checked(..., ("by_ip", "by_dst"))` plus an `ips.buckets` check, with QueryFailed → 502. There are tests for timed_out, failed shards and missing aggregations, on both the bytes sort and the alerts sort.
3. **One reading for Online now and the table.**
   - The list reply carries `as_of`, `online_since` (`as_of` − 5 min) and `online_total`, all from the daemon's clock, using the count's `>=` rule.
   - The table's status reads `online_since` and `as_of`, not `Date.now()`.
   - Tests cover the boundary and a slow reply.
4. **Home keeps `deviceCountReply` whole.** `deviceCount` is derived from it, and `changeRange()` clears it. Tests cover a click during the next range's load and after it fails.
5. **Step 7d times the 30-day list from inside nettap-web** (the proxy's own leg, with its token), and anything not under 8 s is ✗.
   - **Partly rejected:** a full authenticated nginx round trip. It needs the admin password, or a JWT minted from the secret in a deploy script, which would be an auth-bypass tool on the box.
   - The timeout lives on the nettap-web → daemon leg, which this does measure.

New tradeoff: the list reply grows four fields. All are additive and typed as required.

## Round 2 - Codex

The earlier findings are substantially addressed. Two remaining issues need changes:

1. **Medium — The new Online cutoff lacks a shared precision contract.**
   - **Evidence:** Plan A.4 and B.3 require identical boundary comparisons but do not specify timestamp precision. The referenced daemon calculation preserves fractional milliseconds (`daemon/api/devices.py:1613`), while JavaScript `Date` uses whole milliseconds.
   - **Impact:** I reproduced a disagreement: with cutoff `12:00:00.123456Z` and `last_seen` `12:00:00.123Z`, Python excludes the device, but JavaScript considers it Online. Moving the clock into the response alone does not guarantee equality.
   - **Fix:** Define `as_of` as integer epoch milliseconds, derive `online_since` from that integer, and use those exact values for both counting and serialization. Add a boundary test with a patched daemon clock containing nonzero microseconds.

2. **Medium — The proposed timeout fallback cannot satisfy the deployment gate.**
   - **Evidence:** Plan E.4 requires completion under a fixed **8 seconds**, then prescribes increasing the proxy timeout if that check fails. The latest Claude response confirms that fixed threshold.
   - **Impact:** A correct 12-second request still fails Step 7d after increasing the proxy timeout to 30 seconds. The prescribed remedy therefore cannot meet the plan’s “Step 7d all ✓” acceptance criterion. Also, the direct Node request does not verify that the configured timeout reaches the proxy handler.
   - **Fix:** Define the timing gate relative to the selected `/api/devices` proxy timeout, updating the gate when that timeout changes, and add a proxy unit assertion that this endpoint receives the selected timeout. The bounded web-container measurement is acceptable without adding credentials or JWT generation to the script.

VERDICT: REVISE
### Claude response

Both taken.

1. **One precision contract for the cutoff.**
   - `as_of_ms = time.time_ns() // 1_000_000`, and `online_since = as_of_ms − 300_000`. Both are integers, compared as integers against OpenSearch's epoch-ms `max`.
   - Both are serialised from the integers as ISO with exactly three fractional digits.
   - A patched clock with microseconds is tested on both the daemon and the web side.
2. **The timing gate follows the route's timeout.**
   - **Correction to the evidence:** `/api/devices` is served by its own route, `web/src/routes/api/devices/+server.ts`, not the catch-all. The default 10 s still applied.
   - The route now passes an explicit `DEVICE_LIST_TIMEOUT_MS` to `daemonFetch`. Step 7d declares the same constant and gates at 80% of it.
   - The route's vitest reads the script's value and asserts that both match, so they change together or CI fails.

## Round 3 - Codex

No remaining material findings. The revised precision contract and timeout-linked deployment gate address both outstanding issues, with targeted tests.

Claude’s route correction is also valid: `/api/devices` has its own handler, not the catch-all.

VERDICT: APPROVED
## Result

APPROVED in round 3. Built under the owner's standing instruction to implement the drill-down plans (NET-160).
