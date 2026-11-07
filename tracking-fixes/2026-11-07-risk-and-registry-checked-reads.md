# 2026-11-07: Risk scores and the device registry never take a partial read as complete

**Status:** branch `fix/device-lists-checked`. This follows NET-160 slice 2b-3 (PR #191).
- **Plan:** `plans/2026-11-07-risk-and-registry-checked-reads.md`. Codex approved it in round 3, and the review log sits beside it.

## Problem

PR #191 made the device list and the device count return 502 when a search came back incomplete. That covers a timeout, a failed shard, a missing aggregation and the 20,000-IP cap. Other readers of the same data still took a partial reply as the whole answer:

- **`GET /api/risk/scores`, shown on the Compliance page.**
  - The device population set the network baseline and decided which devices were ranked, and it was unchecked.
  - The unsafe-port lists were unchecked too. A port read that hit its cap only logged a warning.
  - So were the alert counts.
  - Any of these could give a device a lower score, or leave it off the list, behind a 200.
- **`GET /api/risk/scores/{ip}`, shown on the device page.**
  - Its connection total was read loosely: `.get("value", 0)` with any relation, so a lower bound counted as exact.
  - Its alert total was read the same way.
  - Its baseline and port reads were unchecked.
- **The device registry refresh.**
  - Its connection read was unchecked. A partial page can name the wrong most-common MAC for an IP, and `drop_reassigned_ips` would then remove that IP from its real device.
  - The DHCP, mDNS and SSDP lookups call `register_device` with an IP (Codex round 2). A partial reply could re-add an old lease's IP to a MAC after the clean-up had run.
- **`all_buckets` checked mode.** It took a page with no bucket list as `[]`, which ended the paging as complete (Codex round 1). It also took a full page with no `after_key` as the end.

## Fix

- **`daemon/api/risk.py`:**
  - The list passes `what="risk scores"` to `_lan_device_buckets`.
  - `_all_unsafe_ports` passes `what=` to `all_buckets`, and its cap raises `QueryFailed`.
  - Each alert chunk goes through `checked(..., ("by_ip",))` with a list check on `buckets`.
  - The single-device handler checks its connection reply against the query's own aggregation names, and reads both totals with `total_hits()`. Its baseline passes `what=`.
  - Every block catches `QueryFailed` and returns `_incomplete`, the same 502 as the device list ("The device search was incomplete"). The reason is logged on the server.
- **`daemon/storage/all_buckets.py`:** in checked mode, a page whose `buckets` is not a list, or a full page with no `after_key`, raises `QueryFailed`. Unchecked callers keep their old behaviour.
- **`daemon/api/devices_v2.py`:** the refresh passes `what="device registry refresh"`. A partial connection read raises before any write, the loop in `daemon/main.py` logs it, and the next interval tries again.
- **`daemon/services/device_registry.py`:**
  - `enrich_from_dhcp`, `enrich_from_mdns` and `enrich_from_ssdp` wrap their search in `checked()` and catch `(OpenSearchException, QueryFailed)`.
  - A partial reply applies nothing for that source in that cycle.
- **`scripts/remote/deploy-drill-down.sh`, Step 7e:** over a settled 24 h window it checks that:
  - OpenSearch's device count before ≤ the devices scored ≤ OpenSearch's count after;
  - the top-scored device's scored connections fall between OpenSearch's `_count`s.
- **No web change.** `getRiskScores` and both `getDeviceRiskScore` functions already throw on any non-OK status, and the Compliance and device pages show their error states.

## Not covered (deliberate)

- **Nested sub-aggregations inside each scoring bucket are not shape-checked** (Codex round 1 #2, rejected).
  - OpenSearch does not drop a requested sub-aggregation from a successful reply.
  - Reply-level partials (a timeout, a failed shard, a missing aggregation, a broken page) are all caught.
- **The refresh is not one transaction.** If the connection read succeeds and a later lookup fails, the registrations already written stay. They are correct, because they came from a complete read.
- **The 20,000-IP cap now applies to the registry refresh.** It used to read up to 500,000. Above the cap it fails loudly every cycle instead of registering part of the network.

## Tests

- **`test_all_buckets.py`:**
  - In checked mode, a later page with no bucket list raises, and so does a full page with no next key.
  - Unchecked mode is unchanged.
- **`test_risk_api.py` `TestRiskReadsAreChecked`:**
  - **The list returns 502** when:
    - a device page times out;
    - an alert chunk loses a shard;
    - an alert reply has no `buckets`;
    - the port read loses a shard.
  - **The single score returns 502** when:
    - its connection search times out;
    - its alert total is a lower bound;
    - a baseline page loses a shard;
    - its port read loses a shard.
  - Complete replies still score.
- **`test_device_registry_refresh.py`:** a device page with a failed shard stops the refresh before any write.
- **`test_device_registry.py`:**
  - each lookup (DHCP, mDNS, SSDP) given a failed-shard reply registers nothing;
  - the same reply, complete, registers.
- **Swap check:** all 14 failure tests fail on `origin/main` and pass with the fix.
- **Daemon suite:** 3,263 passed, 1 skipped. Ruff check and format are clean (0.17.3), and shellcheck passes on the deploy script.

## Lessons

- **A fix to one reader of a shared helper is half a fix.** `_lan_device_buckets` had five callers. PR #191 checked two of them; the other three kept the old behaviour until this follow-up.
- **"Checked" has to cover the page shape, not only the reply flags.** `checked()` looks at `timed_out`, `_shards` and the top-level aggregation. The bucket list inside the aggregation needs its own check.
