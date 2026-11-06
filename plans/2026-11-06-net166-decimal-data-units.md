# Plan: NET-166 — data sizes in decimal units (1 GB = 1,000,000,000 bytes)
_Round 1 - revised after Codex round 1_

## Goal

NetTap divides byte counts by 1,024 but labels them KB, MB, GB and TB. A 1 TB SSD reads "931.5 GB", and every traffic, PCAP, disk and rate figure is about 2.4% (KB) to 9.9% (TB) smaller than the labels say. The owner decided (2026-11-06): **divide by 1,000 and keep the KB/MB/GB/TB labels** (SI units, as drive makers, ISPs and macOS use). After this change, every labelled data size NetTap shows means exactly what its label says, and charts' axis ticks agree with the figures beside them.

## Approach

### A. Web display formatters → base 1,000 (labels unchanged)

Rule: where a page holds a private copy that prints exactly what `formatBytes` in `web/src/lib/api/logs.ts` prints (one decimal, a space, B/KB/MB/GB/TB), delete the copy and import the shared one (the copy stays as an OLD CODE comment, per the Code Preservation Policy). Where a formatter prints a different style (fewer decimals over 100, no space, `--` for null, rates), keep its style and change only the base. Every changed formatter keeps its call sites and output shape.

1. Shared formatters:
   - `lib/api/logs.ts:239-242` `formatBytes`: thresholds and divisors 1e3, 1e6, 1e9, 1e12. This is the one the copies move to.
   - `routes/home.ts:16-25` `formatBytes` / `formatBytesShort`: `Math.log(1000)` and `1000 ** i` (their precision rules stay).
   - `lib/api/pcap.ts:182-183` `formatBytes`: base 1,000 (its exported name stays; PCAP pages import it).
   - `lib/utils/tshark-helpers.ts:94-96` `formatBytes`: base 1,000 (keeps its `--` for null and its string passthrough).
2. Chart axis: `lib/components/ui/charts/geometry.ts:164` `fitByteAxis`: unit `1000 ** Math.floor(Math.log10(max) / 3)` (for `max >= 1000`), so a 28 GB peak still gets 0, 10, 20, 30 GB ticks. Update the doc comment there and in `AreaChart.svelte:40`.
3. Page-local copies, each switched to the shared formatter or re-based per the rule:
   - `routes/system/+page.svelte:34-35` (disk total/used/free, the Storage stage line).
   - `routes/infrastructure/+page.svelte:136-142`: the page's `formatBytes` goes to base 1,000 (it keeps its `--` for null, non-finite and zero, which its KPIs rely on). That covers the OpenSearch data size (1541), the bridge rate (147) and the Logstash JVM heap (1512): **the heap goes decimal too**, so "GB" has one meaning on every page (a `-Xmx1g` heap reads 1.1 GB, which is what 1,073,741,824 bytes is in GB).
   - `routes/settings/+page.svelte:750-751` (`formatCleanupBytes`: space freed by retention cleanup).
   - `routes/bandwidth/+page.svelte:49-60` (`formatBytes`, `formatGB`, `gb()`: monthly use, projection, daily rate, the cap).
   - Traffic bytes: `traffic/[category]` 503-504, `threats` 339-340, `iot` 502-503, `devices` 301-302, `devices/[ip]` 404-405, `devices/mac/[mac]` 103-104 and 111-112, `connections` 369-371.
   - `lib/components/BridgeStatus.svelte:96-97` (bridge receive/send rate, B/s up to GB/s).
   - `lib/components/tshark/AnalysisPanel.svelte:235-238` (PCAP sizes on Tools → TShark).
   - `routes/system/updates/+page.svelte:237`: `mb / 1000` for the GB form of the download size.
   - `routes/settings/backup/+page.svelte:191`: `(importFile.size / 1000).toFixed(1)} KB`.
   - Not touched: `lib/components/SankeyDiagram.svelte` (only mounted inside commented-out code); `routes/system/+page.svelte:40-44` `formatDriveBytes` (SMART totals, already base 1,000).

### B. OpenSearch index sizes (Infrastructure → Indices table)

Today the table prints OpenSearch's own text ("512kb", "1.2gb": base 1,024, lower case, already rounded), and `table-sort.svelte.ts` `byteSize` turns that text back into bytes to sort. Converting rounded text to decimal would invent precision ("1.2gb" is anywhere from 1.235 to 1.342 GB).
- Daemon `daemon/api/opensearch_cluster.py` `handle_indices`: pass `bytes="b"` to `cat.indices`, and return `store_size` / `pri_store_size` as integers (None when OpenSearch sends nothing or a non-number).
- Web `lib/api/infrastructure.ts`: those two fields become `number | null`. `routes/infrastructure/+page.svelte` 753-754 sort by the number, and 1194-1195 print `formatBytes(n)` or `--`.
- The two index cells format with the **shared** `formatBytes` from `logs.ts` and an explicit null check, `n == null ? '--' : formatBytes(n)`, not the page's helper (which prints `--` for 0): a zero-byte index reads "0 B", an unknown size "--".
- `byteSize` in `table-sort.svelte.ts` then has no caller left. Check with grep; if none, keep it as OLD CODE with the reason.

### C. Daemon fields named in GB or MB

- `daemon/storage/manager.py:1840-1842`: `disk_total_gb` / `disk_used_gb` / `disk_free_gb` = bytes / 1e9. The Setup page prints these with "GB" (`setup/+page.svelte:1291-1299`) and the web fallback in `routes/api/setup/storage/+server.ts` (953.87, a 1,024-based figure) becomes the decimal equivalent.
- `daemon/services/update_checker.py:900`: `size_mb` = bytes / 1e6.
- `daemon/services/malcolm_upgrade.py:435-436`: `df -k` counts 1,024-byte blocks, so the message's GB = `kb * 1024 // 10**9`. The 20 GiB headroom constant (line 79) is internal and unchanged.
- `daemon/services/bandwidth_tracker.py:81`: `monthly_cap_gb` = bytes / 1e9.
- `daemon/services/nl_search.py:489-495` (natural-language search "large traffic"): the filter `client.bytes >= 1048576` is described as ">1MB"; it becomes `{"gt": 1_000_000}` so the filter and its description agree.

### D. Settings the user types in

- **Monthly bandwidth cap** (`daemon/api/bandwidth.py:266, 277`): `cap_bytes = int(float(cap_gb) * 10**9)` and the echoed `monthly_cap_gb` / 1e9, so the GB a user types means the same GB the page shows (ISPs state caps in decimal GB). No page calls `setBandwidthCap` today; a cap can only arrive through the API or a backup restore, and it is stored as bytes, so a cap saved before this change keeps its bytes and reads about 7% higher (1,000 GiB → 1,073.7 GB). `shortcut:` comment on the conversion naming that, to upgrade by converting stored caps if a page ever sets one before this ships.
- **PCAP max file size** (`settings/+page.svelte:1185-1192`): the number goes straight to netsniff-ng as `PCAP_ROTATE_MB`, which counts mebibytes (`daemon/services/capture_config.py:66`). NetTap does not convert it. Relabel the field's unit "MiB", change the help's "Range: 10–10,000 MB" to "Range: 10–10,000 MiB", and add: "1 MiB is 1,048,576 bytes, so a 256 MiB file shows as 268.4 MB on the PCAP page." This keeps the capture config unchanged (no device risk) and states the truth.
- **Setup disk check** (`setup/+page.svelte:66, 412`): "100 GB+" against `disk_free_gb >= 100`, now decimal on both sides, so the check and its label agree (it passes at 93.1 GiB instead of 100 GiB; the PRD's target drive is 1 TB).

### E. Tests

- Update every expected string the agent survey found (list in "Verification").
- Tests that check a private copy of a formatter are replaced by tests of the **production code they copied**: where the copy was of a formatter now deleted in favour of the shared one, test the shared one; where the production formatter stays (BridgeStatus's rate, the updates page's `formatSizeMB`, ConnectionDrawerContent, the IoT page), render the real component or page and assert its text (e.g. a bridge rate of 1,000,000 B/s renders "1.0 MB/s"; an update of 1,000 MB renders "1.0 GB"), which the old 1,024 code fails.
- New tests that fail on the old code:
  - `logs.test.ts`: `formatBytes(1_000_000_000) === '1.0 GB'` and `formatBytes(1_000_000_000_000) === '1.0 TB'` (a 1 TB drive reads 1.0 TB, not 931.3 GB); `formatBytes(999) === '999 B'`.
  - `geometry.test.ts`: `fitByteAxis(28e9)` ticks are whole GB (0, 10e9, 20e9, 30e9).
  - Daemon: `disk_total_gb` for 1e12 bytes is 1000.0; `size_mb` for 15e6 bytes is 15.0; bandwidth cap of 1,000 GB stores 1e12 bytes; `handle_indices` passes `bytes="b"` and returns integers.
  - Infrastructure page: an index of 524,288 bytes shows "524.3 KB" and sorts by bytes; an index of 0 bytes shows "0 B"; a null size shows "--" and sorts last.
  - Daemon `handle_indices`: a non-numeric or missing `store.size` from OpenSearch returns None.
  - Daemon `nl_search`: "large traffic" produces `{"gt": 1000000}` and says ">1MB".
  - Settings: the PCAP field reads MiB with the help sentence.

## Key decisions & tradeoffs

- **Memory goes decimal too** (Codex round 1): a label must mean one thing on every page; the heap's bytes are shown in decimal GB like everything else.
- **Rates go decimal too** (B/s): they come from the same byte counters, and two units on one page would contradict each other.
- **Merge copies where identical, re-base where not**: deleting ~10 identical copies is the lean fix ("merge: near-copies that must change together"); forcing one style on all pages would change precision on pages nobody asked about.
- **Index sizes come from OpenSearch in bytes** rather than converting its rounded text.
- **PCAP setting relabelled, not converted**: converting MB→MiB for netsniff would change the capture config on the device (bridge/capture path) for a cosmetic gain.

## Risks / open questions

- Many expected strings change; a missed formatter would leave one page in binary. Mitigation: after the change, `grep -rn "1024\|1_024\|1048576\|1_048_576\|1073741824\|1_073_741_824\|Math.log(1024)" web/src daemon` must show only comments/OLD CODE, port/key-size numbers (`< 1024` ports, "1024-bit RSA"), `df -k` maths and the internal Malcolm headroom constant.
- The e2e fixture `e2e/fixtures.ts:37` and `dashboard.spec.ts:78` ("1.0GB") and the visual fixtures built with 1,024 constants (`e2e/visual/fixtures/storage.ts`, `infrastructure.ts`, `net-world.ts`, `net-connections.ts`, `tools.ts`) need their values or comments updated so they still show what they claim; no screenshot PNGs are committed.
- `routes/api/setup/storage/+server.ts` fallback values (953.87) are mock figures; recompute them so the Setup mock reads consistently.

## Verification plan

- `cd web && npx vitest run && npx svelte-check --threshold error && npm run check:colors && npm run check:e2e && npm run test:visual`.
- `cd daemon && .venv/bin/python -m pytest -q` (existing failures set unchanged) and `uvx ruff@0.17.3 check` / `format --check` on changed files.
- The grep in Risks shows no stray 1,024 conversion.
- Expected-string updates (from the survey): `logs.test.ts:281-289`, `pcap.test.ts:202-210`, `routes/pcap/pcap.test.ts:105-106, 383, 388`, `tshark-helpers.test.ts:248-264`, `drilldown.test.ts:14, 20`, `shell/status.test.ts:59, 63`, `NetworkFlow.test.ts:41, 114`, `BridgeStatus.render.test.ts:123`, `infrastructure.test.ts:416`, `geometry.test.ts:174-178`, `live.page.test.ts:367-370`, `category-page.test.ts:94, 98`, `bandwidth.test.ts:76, 116`, `address-page.test.ts:97, 98, 126, 316, 318`, `devices-by-type.test.ts:76, 187`, `device-detail.test.ts:208, 211`, `device-mac.test.ts:65, 71, 162`, `e2e/dashboard.spec.ts:78`; copy-of-formatter tests `BridgeStatus.test.ts:285-295`, `SankeyDiagram.test.ts:61-63`, `ConnectionDrawerContent.test.ts:181-190`, `iot.test.ts:605-614`, `UpdateSystem.test.ts:280-284`; daemon `test_update_checker.py:825-829`, `test_bandwidth_tracker.py:69-73`.
- Device: the next deploy of main shows the G11's 1 TB drive as about 1.0 TB on System and Setup; no separate device script (display-only, plus a read-only `_cat` parameter).

## Rollback / migration safety

- Display-only except the bandwidth cap input conversion; no stored data changes. A cap saved earlier keeps its bytes (see D). Revert the PR to roll back.

## Observability

None needed beyond the tests; no new runtime paths.

## Out of scope

- Install scripts (`scripts/install/validate-hardware.sh:71`, `deploy-malcolm.sh:85`): they print GiB as "GB" during install. Filed as a follow-up issue; they sit on the high-stakes install path.
- SMART totals' "kB" spelling and two decimals (already base 1,000).
- Showing rates in bits per second.
