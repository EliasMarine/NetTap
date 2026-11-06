# Plan: three small accuracy follow-ups from the NET-155 audit (NET-164, NET-169, NET-173)
_Round 2 - APPROVED by Codex (round 1: 4 findings accepted)_

## Goal

Three figures or controls in NetTap still state something they can't back up. Fix each with the smallest change, so every number shown says what it measures:
- **NET-164:** the Alerts page threat score reads as a bare number ("42 · threat score"), with no scale and no word on how it is worked out. Threats already shows "/100" but also not how.
- **NET-169:** when ping is interrupted or fails early, it prints a header but no statistics line. `_tool_error` returns None because stdout is not empty, and `api/tools.py:135` defaults `packet_loss_pct` to 100, so the page shows a made-up "100% loss" with blank round trips and no reason.
- **NET-173:** the Changelog filter offers 8 event types, but only `device_joined` (`services/device_registry.py:420-432`) and `storage_pruned` (`api/server.py:337-369`) are ever written. `get_event_types` aggregates `terms` on `event_type`, which is dynamically mapped as text (no template for `nettap-changelog-*`), so the query fails and the fallback returns all 8.

Load: one household, one daemon. Out of scope: NET-168 (amber "incomplete" needs an owner design decision: the existing `.chip.is-warn` is orange, the failure colour).

## Approach

1. **NET-164 — state the scale and the method.**
   - `web/src/lib/api/alerts.ts`: one exported constant `THREAT_SCORE_HOW = 'Each alert group adds 10 (critical), 5 (high), 2 (medium) or 0.5 (low), rounded down and capped at 100. A busier-than-usual window adds 15 while the score is under 75. The level never exceeds the worst alert.'` (mirrors `alert_intelligence.py:1545-1593`: `SEVERITY_WEIGHTS`, `int()` truncation at 1548, the +15 baseline boost only when the pre-bonus score is < 75 at 1584, `_cap_level`; info-severity groups are excluded) (Codex 1).
   - Alerts (`routes/alerts/+page.svelte:1123`): drop `label="threat score"` so `Ring` shows its default "of 100"; add the constant as a line under the chips (existing muted text class).
   - Threats (`routes/threats/+page.svelte:403`): pass the constant as the `KpiCard` `sub`.
   - Daemon tests pin every rule the sentence states, with explicit expected values (Codex 1): one low group → 0, two low → 1; one group of each of critical/high/medium → 17; eleven critical → 100 (cap); with the baseline mocked anomalous, a pre-bonus 74 → 89 and a pre-bonus 75 → 75 (no bonus); the level of eleven medium groups (score 22… use enough to reach ≥ 75) is capped at medium.
2. **NET-169 — say ping didn't finish.**
   - `services/network_diag_service.py` `ping()` only (traceroute shares `_tool_error` and is unchanged): after parsing, `if error is None and "packets_transmitted" not in parsed["stats"]: error = stderr text or "Ping didn't finish: it printed no summary"`. The page already shows an error card whenever `error` is set (`routes/tools/ping/+page.svelte:212`), so no figures are shown.
   - `api/tools.py`: unchanged (with `error` set the figures aren't rendered); OLD CODE not needed.
   - Tests: header-only stdout + stderr `ping: sendmsg: Network is unreachable` + exit 1 → that error; header-only + empty stderr → the "didn't finish" text; the existing 100%-loss-with-summary test stays an ok result.
   - Page regression test (Codex 3): an **HTTP 200** reply carrying `error` plus the API's default figures (`packets_sent: 0`, `packet_loss_pct: 100`, null RTTs, and one partial reply) shows the error text, and no loss figure, round-trip figures or reply rows. If the page does show them, the page is fixed to hide figures whenever `error` is set.
3. **NET-173 — offer only what is recorded.**
   - `services/changelog.py`: `CHANGELOG_EVENT_TYPES = {"device_joined", "storage_pruned"}` (old set kept as OLD CODE); the `terms` aggregation uses `event_type.keyword` (dynamic mapping's keyword sub-field). If the sub-field doesn't exist the aggregation returns no buckets and the fallback is the two recorded types, so the filter is honest either way.
   - Backdated index: keep writing to today's index and document the effect in a `shortcut:` comment on `_index_name` (Codex 4): events are filed by the day they were written, not their `@timestamp`, so a backdated `device_joined` can sit in the next day's index and a manual date-based cleanup (`storage/manager.py:1316-1326`) removes it a day later than its timestamp suggests. Changelog indices have no automatic retention tier (`_parse_index_tier` → unknown), and the comment says so rather than implying one. The page searches by `@timestamp`, so what it shows is unaffected.
   - Web: the 8 labels/icons in `routes/changelog/+page.svelte:37-69` stay (harmless; options come from the daemon).
   - Tests (Codex 2): the empty-aggregation and search-failure fallbacks assert the literal `["device_joined", "storage_pruned"]`, not `sorted(CHANGELOG_EVENT_TYPES)`; the aggregation body uses `event_type.keyword`; the existing aggregation-result test keeps real types from data.

## Key decisions & tradeoffs

- **Constant sentence in the web, not a daemon field.** The method changes only with the daemon code; one constant plus a daemon test pinning the weights is less than a new API field.
- **Ping: error instead of figures.** A run with no summary has no loss figure to show; "100%" was invented.
- **Changelog: trim the list rather than record six new event types.** Recording them is a feature (owner's call); offering filters that can never match is the bug.
- **No index-name change.** The only effect is on manual date-based cleanup, at most a day for an event stamped across midnight; a comment is enough at this load.

## Risks / open questions

- `event_type.keyword` is an inference (no template found). Either outcome gives an honest filter (real types from data, or the two recorded types).
- The threat sentence is long for a KPI sub; if it wraps badly at phone width the visual overflow check will say so.

## Verification plan

- Daemon: the new ping tests, changelog tests, a threat-weight test; full `python3 -m pytest`, ruff.
- Web: vitest for the Alerts and Threats pages (the "of 100" label and the sentence), svelte-check, check:colors, check:e2e, test:visual (wrapping at phone width).
- Device: none needed beyond the next deploy; the Changelog filter shows only types present (or the two recorded) — checkable by eye.

## Rollback / migration safety

All three are display/wording or a parser branch; no data or schema change. Revert the PR to undo.

## Observability

None needed; ping errors already come back in the response.

## Out of scope

NET-168 (design decision), NET-166, NET-163, NET-170/171/172 (features), recording the six unused changelog event types.
