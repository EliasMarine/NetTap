# 2026-11-06 — Data accuracy audit after the redesign

**Status:** fixed and tested on `fix/data-accuracy-audit-2026-11-06`. The PR and the G11 check are pending.
- Linear: NET-155 (umbrella), NET-156 (Overview), NET-157 (Investigate), NET-158 (Devices), NET-159 (System).
- Follow-ups: NET-161 to NET-174.

**Problem**

The owner's goal is that NetTap's figures are factually accurate, so people can use it to solve problems and investigate issues. After the redesign (NET-147), four audit agents read every page against the daemon queries behind it. They found 49 figures or sentences that didn't match what was measured: O1 to O11, I1 to I14, D1 to D12 and S1 to S12.

**What was wrong, by area (highlights)**

- **Overview**
  - The Bandwidth projection counted one day too many (O1).
  - Live guessed direction from the port number (O2).
  - Live summed country totals from the top 20 cities (O3).
  - Live's protocol legend showed percentages as counts (O6).
  - Home's "to review" fell back to the all-alert total (O9).
- **Investigate**
  - The Alerts "Info" filter showed every alert (I1).
  - Connections' "Has alerts" was never sent (I2).
  - Connections' bytes in and out were swapped (I3).
  - Alert category pages used the re-graded severity, not Suricata's (I4).
  - The Log Explorer timeline summed only 7 types (I5), and its TLS and DHCP columns read fields Malcolm doesn't write (I6).
- **Devices**
  - IoT scores used baselines that never ran, and defaulted to 75 (D1).
  - The IoT device set ignored the time range (D2).
  - "Top destinations by bytes" was ranked by connection count (D3).
  - Device alerts counted one direction only (D4).
  - Download and upload were swapped on inbound rows (D5).
  - The protocol filter only filtered the 25 rows on screen (D6).
- **System**
  - The SSL tool's "Valid" checked only the expiry date (S1).
  - Ping read 33.3% loss as 3333% (S2).
  - The SSL tool's subject and issuer were always "—" (S3).
  - A check that couldn't run showed as "Degraded" (S5).
  - Packet loss ignored NIC misses (S9, O10).

**What changed**

Each area's agent fixed its findings in its own worktree, with tests:
- Overview: 6 commits.
- Investigate: 8 commits.
- System: 4 commits.
- Devices: 4 commits.

The branches were merged into this one with no conflicts. After the merge:
- **Home crash, fixed.** Home's System stage threw when the daemon sent no `status` (an older daemon). It now reads Unknown.
- **Formatting.** ruff format was applied to the daemon files the fixes changed.
- **Deploy script.** `scripts/remote/deploy-data-accuracy-audit.sh` checks the new behaviour on the device, then runs verify-figures.sh and verify-acceptance.sh. The checks cover health states, active_since, the protocol filter and direction, the SSL tool's verdict on good, expired and wrong-host sites, and ping loss and RTT.

**Response shape changes (consumers updated in the same branch)**
- **Live and devices:** `/api/live/dashboard` protocols are counts, with an unknown key. Connections gain `direction`.
- **IoT:** scores, grades and pillars can be null, and coverage fields are added.
- **System health:** `status` is healthy, problem or incomplete, and `healthy` can be null.
- **SSL tool:** subject and issuer are objects, and it adds `trusted`, `verify_errors` and `name_match`. Ping RTT can be null.
- **Device connections:** take `proto` and gain `direction`. The device count takes `active_since`.

**Tests**
- Daemon: 3,047 passed, 1 skipped.
- Web: 3,002 passed.
- svelte-check: 0 errors. The colour and e2e checks are clean.
- Visual: 187 of 187 passed.
- Gates: `/deep-review` found nothing (`security-reviews/fix-data-accuracy-audit-2026-11-06/`). The ponytail and two-angle reviews are before merge.

**Still to do**
- Run `deploy-data-accuracy-audit.sh` on the G11 after merge.
- The follow-ups the fixes couldn't close:
  - auto IoT baselines (NET-170) and the behaviour checks (NET-171);
  - one device identity across IP reassignments (NET-172);
  - the units decision (NET-166);
  - inline-mode threat intel (NET-163);
  - a packet-loss window (NET-167);
  - others: NET-161, 162, 164, 165, 168, 169, 173 and 174.

**Lessons**
- A label must say what the query measures: its cap, its direction, its window and its severity scale. Most of these bugs were a correct query under a wrong label.
- Merging parallel fix branches can break a page none of them touched alone. Run the whole suite after the merge, and read vitest's "unhandled errors" line, not only the pass count.
