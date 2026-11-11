# Release-audit follow-ups, 2026-11-11

**Linear:** NET-238, NET-239, NET-240, NET-242, NET-243 (the open children of NET-223)
**Branch / PR:** `fix/audit-followups-2026-11`, PR #247
**Status:** deployed to the G11 from the PR branch and verified there.

## Why

These were the five open children of the November release audit. Each one made a page look fine when it wasn't, or go blank when data existed.

## What changed

**NET-242: pipeline problems show on Alerts and Threats.**
- **Cause:** NET-228 put the pipeline state only beside empty results. A window with older alerts never read it.
- **Fix:** `pipelineProblem()` (`web/src/lib/api/system.ts`) drives a warning at the top of both pages: "Data pipeline now: Suricata stopped. What this page shows may be out of date." A failed check reads "Couldn't check".

**NET-238: capped detection scans say so instead of going blank.**
- **Cause:** NET-237 made a capped scan raise an error. For a detection, that let the watched host hide every match by flooding past the cap.
- **Fix:** these return `(result, complete)` and send `complete` to the page:
  - `dns_analytics._all_domains`, `get_suspicious_dns` and `detect_dns_tunneling`;
  - `threat_intel.scan_suricata`.
- **On the pages:** the DNS and Threats cards say where the scan stopped, and threat-intel counts read "at least N". An empty capped scan reads "Nothing suspicious in the names checked" or "No matches in the pairs checked", never "none".
- **Still fail-closed:** IoT isolation, rogue DHCP and the ARP scan, each with a comment saying why.

**NET-239: the score's hidden inputs are shown.**
- **Fix:** `_smart_alerts` returns the suppressed parts. The summary adds:
  - `suppressed_findings`: scoring keys that only suppressions removed;
  - `busier_window_points`: 0 or 15.
- **Baseline:** adds `ready` and `earlier_hours`.
- **On the pages:** `scoreInputs()` writes them under "How the score is worked out". The Threats KPI no longer says "1× vs baseline" while the baseline is still learning.

**NET-240: lateral movement counts open connections.**
- **Decision:** lateral movement reads interim `conn_long` records. Beaconing doesn't, because the interim records of one open connection would look periodic.
- **Fix:**
  - **Window:** a connection counts if it was active in the window (`@timestamp <= to` and either `lastPacket >= from` or `@timestamp >= from`).
  - **Count:** distinct `zeek.uid`, plus one per record without a uid.
  - **Last seen:** the later of the newest record and the last packet.
- **Kept as designed:** `first_seen` can fall before the window and `last_seen` after it; both are the connection's own times.

**NET-243: alerts are searchable sooner.**
- **Cause:** Filebeat 9.5's memory queue holds a partial batch until 1,600 events or `queue.mem.flush.timeout` (10 s). A home network never fills one.
- **Fix:** `config/filebeat/flush-timeout.sh` sets the timeout to 2 s with `yq` in the image's own config, then runs the image's own ENTRYPOINT and CMD, which compose restates.
- **Checked on the G11:**
  - The 26.10.0 and 26.02.0 (rollback) images have the same ENTRYPOINT and CMD, and both ship `yq`.
  - The patched config is identical apart from `queue`, and `filebeat test config` passes.
- **Guard:** a bats test fails on any `TESTED_MALCOLM_TAG` bump until someone re-checks.

## Device scripts

- `scripts/remote/deploy-audit-followups.sh` deploys and checks each fix through the API.
- `scripts/remote/measure-alert-latency.sh` measures latency:
  - **Triggers:** 12 single triggers, each a UDP datagram carrying `uid=0(root)` to 192.0.2.1, sent from the daemon container.
  - **Why UDP:** the HTTP version failed 10 of 12 times, because the UDM's IPS blocks example.com after the first matches. The mirror sees a datagram before the router can drop it.
  - **Also measured:** `event.ingested` − `@timestamp` over all alerts since `SINCE`, and ten minutes of disk and OpenSearch writes.

## Verification

**Local:**
- daemon pytest: 4663 passed;
- Vitest: all passed;
- svelte-check: 0 errors;
- check:colors: clean;
- visual: 295 passed;
- bats: 0 failures;
- ruff check and ruff format: clean.

**G11, deployed from the PR branch (2026-11-11 23:04 UTC):**
- `deploy-audit-followups.sh`: every check passed.
  - The wrapper set 2 s, and Filebeat is RUNNING.
  - `complete` is on both routes.
  - The summary has the new keys (score 56, 0 suppressed findings, +0).
  - Lateral movement: 7 pairs, complete.
- `smoke-test-release.sh`: 29 passed, 0 failed.
- NET-242: Suricata was stopped at 23:04:53 UTC.
  - `/api/system/health` read `sensor_stopped` within 20 s.
  - After the start at 23:06:07 it was back to `fresh` within 20 s.
  - The page notice that this state drives is covered by the page tests. The logged-in browser pass wasn't run, because it needs the owner's sign-in.

**Latency (NET-243):**

| Run | Single triggers (12) | Real alerts: median / p90 / p99 / max | Over 10 s | Disk per 10 min | OpenSearch writes |
|---|---|---|---|---|---|
| Before, 48 h sample | — | 5.2 / 11.3 / 13.6 / 14.4 s (2,000) | 16.5% | about 1 GB | — |
| Before, 2026-11-11 | 4.8 to 9.0 s, 12/12 under 10 s | 7.3 / 11.7 / 13.5 / 14.4 s (2,951) | 22.5% | 352 MiB | 0.39 a second |
| After, 2026-11-11 (since 23:07 UTC) | 2.0 to 3.3 s, 12/12 | 2.0 / 4.3 / 4.7 / 6.5 s (1,019) | 0% | 473 MiB | 1.17 a second |

A single trigger waits only for the rest of the current 10 s flush window, so the trigger test passed before the fix too. The real-alert distribution is the measure.

**What it costs:** OpenSearch bulk writes rose from 0.39 to 1.17 a second, because Filebeat now sends smaller batches more often. Disk writes are dominated by PCAP capture (352 to 473 MiB per 10 minutes across the three runs), so the extra index writes don't stand out.

## Reviews

- **`/codex-review`:** plan APPROVED in round 4.
- **`/deep-review`:** no findings.
- **`/ponytail-review`:** three tripwire tests added (the Malcolm tag, `SCAN_CAP`, the baseline warm-up).
- **Two-angle review:**
  - **Security engineer:** no findings. It caught the deploy check passing when the daemon was unreachable; fixed.
  - **TypeScript:** an empty capped scan read as "none" (fixed), the "not busier" wording (fixed), and the KPI note while learning (fixed).
  - **Python:** added a test for partial suppression within one group.

## Lessons

- **Test with the network's own defences in mind.** A test trigger that crosses the router meets its IPS. Send it as a datagram that nothing needs to answer.
- **A single trigger can't show a batching fix.** It waits for the rest of a window, not a whole one. Measure the distribution over real traffic.
- **Every constant copied across a boundary needs a tripwire test.** That covers a restated image entrypoint, a scan cap and a warm-up length.
- **Failing closed has to suit what the number is used for.** It is right for totals. It is wrong for detections, where the watched party controls the cap.

## Next

- Set NET-238/239/240/242/243 to Done when #247 merges.
- Add a note on NET-215: when its page is built, the ARP and IP-conflict scans should apply the capped-scan rule.
- Re-check the restated Filebeat entrypoint on the next Malcolm bump. The bats test enforces it.
