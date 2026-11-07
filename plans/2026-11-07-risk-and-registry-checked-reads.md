# Plan: risk scores and the device registry never present a partial read as complete

_Round 2, revised after Codex rounds 1 and 2. Follow-up to NET-160 slice 2b-3 (PR #191)._

## Goal

PR #191 made `GET /api/devices` and `/api/devices/count` return 502 when any page of the device search, or any alert-count search, comes back incomplete. That covers timeouts, failed shards, a missing aggregation, and hitting the 20,000-IP cap. Three other callers still read the same data unchecked, so a partial reply silently becomes lower figures:

- **`GET /api/risk/scores`** (`daemon/api/risk.py` `handle_risk_scores`, shown on the Compliance page).
  - The device population is unchecked. It sets the network baseline (mean and standard deviation of connections) and decides which devices get ranked.
  - The unsafe-port lists are unchecked.
  - The per-chunk alert counts are unchecked.
  - Any of these can make a device score lower, or drop it from the list, and still return 200.
- **`GET /api/risk/scores/{ip}`** (`handle_risk_score_single`, shown on the device page).
  - The connection search reads `hits.total` loosely (`.get("value", 0)`, any relation) and is not checked.
  - The baseline device read is unchecked.
  - The port read is unchecked.
  - The alert `hits.total` is read loosely.
- **The device registry refresh** (`daemon/api/devices_v2.py` `refresh_device_registry`, background loop in `daemon/main.py`).
  - The device read is unchecked.
  - A partial page can report the wrong most-common MAC for an IP. `drop_reassigned_ips` would then remove that IP from its real device.

## Approach

1. **The list handler, `handle_risk_scores`:**
   - Call `_lan_device_buckets(..., what="risk scores")`. This gives checked pages and the 20,000 cap, which raises QueryFailed.
   - Change `_all_unsafe_ports(client, bool_query, ips)` to call `all_buckets(..., what="risk score ports")`, and raise `QueryFailed` when `complete` is False (500,000 device-port pairs). The old warning is kept as OLD CODE.
   - For each alert chunk, `by_ip = checked(alert_result, "risk score alert counts", ("by_ip",))["aggregations"]["by_ip"]`, then `got = by_ip.get("buckets")`. Raise QueryFailed if `got` is not a list, so a missing `buckets` is a 502 and not a KeyError 500. This runs inside the guarded block.
   - Add `except QueryFailed as exc: return _incomplete("risk scores", exc)` to the device/port try and to the alert loop. `_incomplete` is imported from `api.devices`, the same 502 body as the device list ("The device search was incomplete"). TooSlow, a QueryFailed subclass, also gives 502, the same as the device list.
2. **The single-device handler, `handle_risk_score_single`:**
   - **The connection search:**
     - `checked(conn_result, "risk score connections", ("total_orig_bytes", "total_resp_bytes", "ports_used", "external_conns"))`;
     - `total_conn = total_hits(conn_result, "risk score connections")`. The query already sets `track_total_hits: True`.
     - The 404 for 0 connections stays.
   - **The ports:** they go through the checked `_all_unsafe_ports`.
   - **The baseline:** `_lan_device_buckets(..., what="risk score baseline")`.
   - **The alert count:** `total_hits(checked(alert_result, "risk score alert count"), ...)`. The query already sets `track_total_hits: True`.
   - Each try catches QueryFailed and returns `_incomplete("risk score", exc)`.
3. **The registry refresh, `refresh_device_registry`:**
   - Call `_lan_device_buckets(..., what="device registry refresh")`.
   - A partial **connection read** (the one that decides which IP belongs to which MAC) raises before any registration, merge or IP drop. The loop's existing `except Exception` logs it, and the next interval retries.
   - **The DHCP, mDNS and SSDP enrichment reads are checked too** (Codex round 2). Each one calls `register_device` with an IP, so a partial reply could re-add an old lease's IP to a MAC after `drop_reassigned_ips` ran.
     - In `daemon/services/device_registry.py`, `enrich_from_dhcp`, `enrich_from_mdns` and `enrich_from_ssdp` change `result = self._client.search(...)` to `result = checked(self._client.search(...), "<X> enrichment")`.
     - Each `except OpenSearchException` becomes `except (OpenSearchException, QueryFailed)`.
     - A partial reply then applies nothing for that source this cycle. It logs the existing ERROR line, and the other sources still run.
     - `enrich_from_arp` is not called by the refresh, so it is left alone.
   - **What stays unguaranteed:** the refresh is not one transaction. If the connection read succeeds and a later enrichment fails, the registrations already written stay. They are correct, because they came from a complete read.
4. **`storage/all_buckets.all_buckets`, checked mode only (`what` set).**
   - A page whose `buckets` is missing or not a list raises `QueryFailed(f"{what}: malformed page")`. Today it reads as `[]`, which ends the paging as complete.
   - So does a full page with no `after_key`, which today ends the paging as complete, possibly early.
   - Unchecked callers keep today's behaviour.
   - This also hardens `/api/devices` and `/api/devices/count` (PR #191), which share the helper.
5. **No web change.** `getRiskScores` and both `getDeviceRiskScore` functions already throw on any non-OK status, and the Compliance and device pages show their error states (#96).

## Key decisions & tradeoffs

- **502, not a partial score with a warning.** A lower risk score presented as complete is a false all-clear. That is the worst failure for a security product, and it is the rule PR #191 applied to the device list.
- **Reuse `what=`, `checked()`, `total_hits()` and `_incomplete`.** No new helpers, so all three call sites fail the same way.
- **The registry refresh skips a cycle rather than writing a partial set.** The cost is a registry that stays one interval stale when OpenSearch has a bad moment. That beats an IP removed from its real device.
- **The 20,000-IP cap now applies to the registry refresh,** which previously read up to 500,000. A household network is far below it. Above it, the refresh fails loudly every cycle instead of registering a silent subset, and the log names the cap.

## Rejected from Codex round 1

- **#2, validating every nested sub-aggregation in each scoring bucket** (`ports_used.ports.buckets`, metric values, `external_conns.doc_count`). Rejected.
  - OpenSearch returns every requested sub-aggregation in every bucket; it does not drop one from a successful reply.
  - The real ways a reply comes back partial are the timeout flag, failed shards and a missing top-level aggregation. `checked()` and the new composite-page check cover all three.
  - A missing nested key would mean NetTap asked for the wrong aggregation name. That is a code bug, and the existing query-shape tests in `TestRiskQueryConsistency` catch it.
  - The `sum` metrics use `missing: 0`, so they never return null.
  - Adding per-bucket shape checks would add code in four places to guard against a reply OpenSearch does not send.
  - The single-device handler still requires its four named aggregations through `checked()`.

## Risks / open questions

- **Existing test fixtures:** they may lack `_shards` or an aggregation that `checked()` now requires. If so, fix the fixture, never relax the check.
- **The 4 conn aggregations required in the single-device handler:** confirm that `_PORTS_AND_EXTERNAL_AGGS` holds exactly `ports_used` and `external_conns`.

## Verification plan

- **pytest, `daemon/tests/test_risk_api.py`:**
  - The list returns 502 when a device page times out, when an alert chunk reply has failed shards, and when the port read is capped.
  - The single score returns 502 when the connection reply times out, when the alert total relation is `gte`, and when a baseline page has failed shards.
  - No 502 body includes the exception text.
- **pytest, `daemon/tests/test_all_buckets.py` (or its existing test file):** in checked mode, a later page with no `buckets` raises, and a full page with no `after_key` raises. Unchecked mode keeps its behaviour.
- **pytest, the alert chunk:** a reply with `by_ip: {}` (no `buckets`) gives a 502 with the fixed body.
- **pytest, each enrichment:** a reply with failed shards registers nothing for that source, and the method returns 0 without raising.
- **pytest, `daemon/tests/test_device_registry_refresh.py`:** a device page with failed shards raises QueryFailed, and no register, merge or drop call runs.
- **The full daemon suite.** Ruff check and format with `uvx ruff@0.17.3`.
- **The device, through `scripts/remote/deploy-drill-down.sh` (daemon rebuild):** a new Step 7e checks that:
  - `/api/risk/scores` returns 200 with devices;
  - `/api/risk/scores/<first ip>` returns 200;
  - the single score's `connection_count` lies between OpenSearch `_count`s for that IP, taken before and after over the same window.

## Rollback / migration safety

There is no stored data and no schema change. Revert the PR and redeploy the daemon.

## Observability

- `_incomplete` logs `Incomplete search in <where>: <reason>` at ERROR.
- The registry loop logs the QueryFailed with a stack trace through its existing `logger.exception`.

## Out of scope

- Moving the risk handlers' blocking searches off the event loop. That is a separate follow-up, with `run_in_slot`.
- Any change to scoring rules.
- Section D, which waits on the owner.
