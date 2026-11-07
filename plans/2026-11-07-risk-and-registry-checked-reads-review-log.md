# Plan review log: risk scores and device registry checked reads

Codex thread `01a1b3ab-9f29-7310-bd6a-2da9299aaaa3`, read-only, MAX_ROUNDS=5. Approved in round 3.

## Round 1 - Codex

The plan needs revision: reusing these helpers does not yet establish the promised completeness checks.

1. **High — Malformed composite pages still count as complete.**  
   **Evidence:** [all_buckets.py:45](daemon/storage/all_buckets.py:45) checks only that `aggregations.all` is a dictionary. Lines 55–61 convert a missing/non-list `buckets` into `[]` and return `complete=True`.  
   **Impact:** A malformed second page returns only the first page, successfully. Risk scores can omit devices or unsafe ports; registry refresh proceeds instead of skipping. I reproduced this with the existing helper.  
   **Fix:** In checked mode, make `all_buckets` raise `QueryFailed` for missing/non-list buckets. Add first-page and later-page regression tests, including registry assertions that no registration, merge, drop, or enrichment runs.

2. **High — Required nested score data remains unchecked.**  
   **Evidence:** [snapshot_search.py:78](daemon/storage/snapshot_search.py:78) validates only named aggregation dictionaries. [risk.py:109](daemon/api/risk.py:109) and [risk.py:162](daemon/api/risk.py:162) default missing nested ports, byte values, and external counts to empty/zero. The list’s composite check does not validate per-device aggregations at all.  
   **Impact:** `ports_used: {}` passes the proposed single-device check, suppresses the port fallback, and produces “no ports.” Empty byte and external aggregations similarly become lower figures. The list remains vulnerable even when entire per-device aggregations are absent.  
   **Fix:** Validate each scoring bucket before consuming it, including `ports_used.ports.buckets`, truncation metadata, metric values, and external `doc_count`. Reuse existing `metric()`/`doc_count()` where appropriate. Test missing nested aggregations on both endpoints, while preserving valid empty port lists and zero values.

3. **Medium — The proposed alert validation raises 500 for missing buckets.**  
   **Evidence:** [plan:28](plans/2026-11-07-risk-and-registry-checked-reads.md:28) directly indexes `["by_ip"]["buckets"]` before checking its type. `checked()` accepts `{"aggregations": {"by_ip": {}}}`.  
   **Impact:** Missing `buckets` raises `KeyError`, bypassing `except QueryFailed` and the promised controlled 502 response. This is reproducible from the proposed expression.  
   **Fix:** Retrieve buckets with `.get("buckets")`, then validate inside the guarded block. Add a missing-buckets test—not merely missing `by_ip`—and assert the sanitized 502 body.

4. **Medium — The registry’s whole-cycle guarantee exceeds the proposed protection.**  
   **Evidence:** [devices_v2.py:251](daemon/api/devices_v2.py:251) registers devices before merging, dropping IPs, and enrichment. Those operations still consume unchecked searches: [device_registry.py:488](daemon/services/device_registry.py:488), [device_registry.py:772](daemon/services/device_registry.py:772), and [device_registry.py:921](daemon/services/device_registry.py:921).  
   **Impact:** A complete connection read followed by a timed-out DHCP reply still registers returned DHCP records and reports a successful refresh. The claim that any partial read skips the cycle before writes is false.  
   **Fix:** Explicitly narrow the guarantee to the initial connection/ownership read and document enrichment as separate, best-effort work; check enrichment replies before applying their records. If whole-cycle atomicity is required, stage and validate reads before mutations. Add a failure-after-successful-connection-read test to establish the intended boundary.

No files were modified. The three helper/validation failures above were verified with read-only probes.

VERDICT: REVISE
### Claude response

- #1 accepted: all_buckets checked mode raises on a missing/non-list bucket list and on a full page with no after_key.
- #2 rejected: OpenSearch does not drop requested sub-aggregations from a successful reply; reply-level partials are covered by checked() and #1; a missing nested key is a code bug caught by query-shape tests. Reason logged in the plan.
- #3 accepted: `.get("buckets")` then list check inside the guarded block; test with `by_ip: {}`.
- #4 accepted as a narrowing: the guarantee covers the conn/ownership read only; enrichment only adds names and vendors and stays best-effort.


## Round 2 - Codex

One material issue remains in the revised rationale. The missing-buckets and alert `KeyError` fixes address the previous findings; I accept deferring exhaustive nested validation for this scope.

**Severity: Medium — Enrichment still changes device/IP associations.**

**Evidence:** [Plan line 42](<plans/2026-11-07-risk-and-registry-checked-reads.md:42>) says enrichment only adds names/vendors to existing devices. However:

- DHCP passes `ip=ip` into `register_device` at [device_registry.py:817](<daemon/services/device_registry.py:817>); mDNS and SSDP do likewise.
- `register_device` adds IPs to existing records at [line 154](<daemon/services/device_registry.py:154>) and creates new devices at [line 206](<daemon/services/device_registry.py:206>).
- Enrichment runs **after** `drop_reassigned_ips`, at [devices_v2.py:254](<daemon/api/devices_v2.py:254>).

**Impact:** A partial DHCP search can omit a MAC’s newest lease and return an older assignment. Enrichment can then re-add that old IP to the MAC after the connection-based cleanup assigned it elsewhere. The remaining risk includes incorrect IP associations and new registry records, beyond temporarily missing names.

**Fix:** Keep the narrowed implementation scope, but replace the metadata-only claim in the plan and response log with an explicit limitation: only the initial connection read is protected; enrichment remains unchecked and can create devices or add IP associations. Record enrichment validation as deferred work. This resolves the inaccurate safety justification without requiring a whole-cycle transaction.

VERDICT: REVISE
### Claude response

- Accepted, and fixed rather than documented. The DHCP, mDNS and SSDP enrichment searches go through checked(), and each except also catches QueryFailed, so a partial reply applies nothing for that source this cycle. That is 2 lines per method. The plan states what stays unguaranteed: the refresh is not a transaction.

## Round 3 - Codex

No material issues remain in the revised plan.

The enrichment guards validate replies before registration, catch `QueryFailed` including timeouts, and let other sources continue. The plan now accurately describes the refresh’s nontransactional behavior and includes tests for rejected enrichment reads.

Approval covers the plan; implementation and test results remain to be reviewed.

VERDICT: APPROVED