# 2026-11-06 — Data sizes in decimal units: every KB, MB, GB and TB means what it says (NET-166)

**Status:** fixed on `fix/decimal-data-units`. /deep-review found nothing (`security-reviews/fix-decimal-data-units/security-review.md`); /ponytail-review said ship. Plan: `plans/2026-11-06-net166-decimal-data-units.md` (Codex approved in round 2 after 4 findings).

**Problem**
- The web formatters and several daemon fields divided byte counts by 1,024 but labelled the result KB, MB, GB or TB.
- A 1 TB drive read 931.5 GB. Every traffic, PCAP, disk and rate figure was 2.4% (KB) to 9.9% (TB) smaller than its label said.
- Chart axis ticks were placed on 1,024-based units.

**Decision:** the owner chose, on 2026-11-06, to divide by 1,000 and keep the labels (SI units, as drive makers, ISPs and macOS use).

**Fix — daemon** (commit "fix(daemon): data sizes in decimal units")
- `storage/manager.py`: `disk_total_gb` / `disk_used_gb` / `disk_free_gb` are bytes / 10⁹.
- `services/update_checker.py`: `size_mb` is bytes / 10⁶.
- `services/malcolm_upgrade.py`: the disk-space message converts `df`/`du`'s 1,024-byte blocks to decimal GB, with one decimal (`_kib_as_gb`).
- **Bandwidth cap:**
  - `services/bandwidth_tracker.py`: `monthly_cap_gb` is bytes / 10⁹.
  - `api/bandwidth.py`: the GB a user types means 10⁹ bytes.
  - `shortcut:` a cap saved earlier keeps its bytes and reads about 7% higher. No page sets a cap yet.
- `services/nl_search.py`: "large traffic" is `client.bytes > 1,000,000`, matching its ">1MB" description. It was `>= 1,048,576`.
- `api/opensearch_cluster.py`: the index list asks OpenSearch for exact bytes (`bytes=b`) and returns integers, or None for anything that isn't digits. OpenSearch's own text ("1.2gb") is 1,024-based and already rounded.

**Fix — web** (commit "fix(web): data sizes in decimal units")
- **Shared formatters on base 1,000:**
  - `lib/api/logs.ts` `formatBytes`, `routes/home.ts`, `lib/api/pcap.ts` and `lib/utils/tshark-helpers.ts`.
  - The chart axis, `fitByteAxis` in `geometry.ts`.
- **Page copies:** identical copies now use the shared `formatBytes`: traffic category, threats, iot, devices, device detail, and settings cleanup. Copies with their own style keep it on the new base: System, Infrastructure (including the JVM heap), Bandwidth, the MAC page, BridgeStatus rates, AnalysisPanel, the updates page's size, and the backup file size.
- **Index table:** it prints the daemon's bytes with the shared formatter, so 0 reads "0 B" and unknown reads "--", and it sorts by the number. `byteSize` (which parsed OpenSearch's text) has no caller left and is kept as OLD CODE.
- **PCAP file size setting:** labelled MiB, with the range "10–10,000 MiB" and help explaining that 256 MiB shows as 268.4 MB on the PCAP page. netsniff-ng counts MiB, and NetTap passes the number through unchanged, so the capture config is unchanged.
- **Setup:** the storage fallback figures are decimal, and the 100 GB check now compares decimal GB with a decimal label.
- **Fixtures:** the e2e and visual fixtures are decimal, except PCAP sizes, which are real MiB.

**Not changed**
- SMART read/written totals were already decimal.
- `SankeyDiagram.svelte` is mounted only inside commented-out code.
- The install scripts still print GiB as "GB". That is NET-177, because they sit on the high-stakes install path.

**Tests**
- **Daemon:** each change has a test that fails on main's version of its file (checked by swapping in main's file, one at a time):
  - a 1,000 GiB drive reads 1,073.74 GB;
  - 15 MB of assets reads 15.0;
  - the Malcolm message reads 23.0 / 1.5 / 10.7 GB;
  - a 1,000 GB cap stores 10¹² bytes;
  - "large traffic" sends `gt: 1000000`;
  - the index list sends `bytes="b"` and returns integers or None.
- **Web:**
  - `formatBytes`: 999 → "999 B", 10⁹ → "1.0 GB", 10¹² → "1.0 TB".
  - `fitByteAxis(28e9)` gives ticks 0, 10, 20 and 30 GB.
  - Index cells: 524,288 → "524.3 KB", 0 → "0 B", null → "--", sorted by bytes.
  - A 1 GiB heap reads "1.1 GB".
  - The PCAP field says MiB.
  - Render tests of the real BridgeStatus (1,000,000 B/s → "1.0 MB/s"), ConnectionDrawerContent, IoT and Updates figures replace tests that checked copies of their formatters.

**Lessons**
- A test of a formatter's copy can pass while the production code is wrong. Test the component that prints the figure.
- An index size sent as human text can't be re-expressed honestly in other units. Ask the source for raw bytes.

**Device check:** `bash /home/nettap/NetTap/scripts/remote/deploy-decimal-units.sh` (after the merge). It checks each `*_gb` is its byte count / 10⁹, that `df` has a filesystem of exactly the daemon's total, and that every index size is whole bytes or null.

**Review follow-ups (PR #181)**
- **Bandwidth cap rounding:** `round()`, not `int()`. 4.1 GB was saved as 4,099,999,999 bytes because of float error.
- **Bad cap values:** `Infinity` now gets a 400; it used to raise OverflowError and return a 500. A negative cap is saved as 0 (off), and the reply now says 0 too.
- **Index sizes:** `_byte_count` uses `isdecimal()`. `isdigit()` accepts "²", which `int()` rejects.
- **Disk-space message:** the need rounds up and the free space rounds down, both in integers, so it can't say "needs 23.0 GB … and 23.0 GB is".
- **Setup check:** the Setup page's "100 GB free" check now means 100 decimal GB, matching its label. A drive with 95 GiB (102 GB) free used to fail and now passes.
