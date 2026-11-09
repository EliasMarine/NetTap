# Alerts honesty (NET-228, plus B-i, B-j and the Live badge under NET-237)

Date: 2026-11-09 · Branch: `fix/net-228-alerts-honesty` · Status: fixed locally, not deployed

## Problem

The release audit (NET-223) found four ways the alert pages overstate what NetTap knows:

- **B5:** "No alerts", "No actionable threats detected" and Compliance's zero read as good news
  even when Suricata was stopped or no data had arrived for hours.
- **B-i:** every count dropped rules ET rates Informational or Unknown, without saying so. Some of
  those are things the owner can act on, such as "ET INFO Outgoing Basic Auth Base64 HTTP Password
  detected unencrypted".
- **B-j:** generated text stated findings as facts: "IMMEDIATE: Isolate the source host",
  "Potential malware activity detected", "Only this device triggers this alert, may be targeted"
  (shown for every group), and the curated SID descriptions told the owner to isolate devices first.
- **P3 (NET-237):** the Live page kept its pulsing "Live" chip while every poll failed.

## Root cause

- The pages had no input saying whether data was arriving. F2 added `pipeline` to
  `/api/system/health`, but only Home and System read it.
- `ET_ACTIVITY_CLAUSE` dropped every Informational/Unknown record, whatever the rule.
- `generate_assessment` was called with `device_count=1` for every group. The description and
  recommendation tables were written as verdicts.
- `live/+page.svelte` never told `LiveChip` that a poll had failed.

## Fix

- `nothingFound()` in `web/src/lib/api/system.ts`: a "nothing found" title plus "Data pipeline now:
  …". While the pipeline isn't fresh (or the health request failed) the title is "Can't tell…".
  Used on Home (Alerts card and Alert summary), Alerts (severity card, list empty states, threat
  summary), Threats (headline and score foot) and Compliance (the zero finding). Alerts, Threats
  and Compliance now load the health with the page, and it counts in the page's LoadResult.
- The stored-data sentence is now "No counted rule matches in this period", because activity can
  exist when nothing counted. An empty list under a filter says "No alerts match these filters"
  (HON-29).
- Credential exposure counts: a record ET rates only Informational/Unknown whose rule name has
  cleartext/password/passwd/credential (and not "password change"/"expired password") counts as
  medium (3). The query (`CREDENTIAL_EXPOSURE_CLAUSE` inside `ET_ACTIVITY_CLAUSE`) and the Python
  predicate (`alert_findings.is_credential_exposure`, first in `reclassify_severity`) apply the same
  test. A smart-alert group's severity is now the strongest over each ET rating in the group, not
  the newest sample's.
- The Alerts page names what was left out: "N rule matches not counted: ET rates their rules
  Informational or Unknown (M with Suricata priority high) · Show".
- Reworded text: `alert_enrichment` prefixes ("Malware rule matched: …"), recommendations and risk
  notes; 18 curated SIDs in `suricata_descriptions.json` (check first, disconnect only on signs of
  infection); `investigation._generate_recommendation` (no "IMMEDIATE: Isolate", names the LAN
  devices from findings without saying who opened the connection); `generate_assessment` openers
  ("A … rule matched."), a device count true of the results ("Only this device triggered this rule
  in these results.", "Triggered by N devices in these results.", nothing on a device page or with no
  attributed device), and rate sentences that say what `compute_trend` measures.
- `LiveChip` takes `stalled`: "Not updating" as a warning chip; the subtitle says the last refresh
  failed.

Replaced code is kept in `OLD CODE` blocks. JSON has no comments, so the old SID text is in git
history only.

## Files

- web: `src/lib/api/system.ts`, `src/lib/components/ui/LiveChip.svelte`, `src/routes/+page.svelte`,
  `src/routes/alerts/+page.svelte`, `src/routes/threats/+page.svelte`,
  `src/routes/compliance/+page.svelte`, `src/routes/live/+page.svelte`, plus their tests
- daemon: `api/alerts.py`, `services/alert_findings.py`, `services/alert_intelligence.py`,
  `services/alert_enrichment.py`, `services/investigation.py`, `data/suricata_descriptions.json`,
  tests (new `tests/test_credential_exposure.py`; the drill fake learnt `missing` aggregations and
  case-insensitive wildcards)

## Tests

- Fail-before: with the old sources restored, 43 daemon tests failed plus the credential module's
  import error, and 31 web tests failed; all pass on the new code.
- daemon: 4,305 passed, 4 skipped (baseline 4,271). `ruff check daemon/` clean.
- web: vitest 342 files, 4,352 tests passed; svelte-check 0 errors; check:colors clean.
- On the G11 (read-only, 30 days): counted alerts 57,189 → 57,202, exactly the 13 credential
  matches (Basic Auth unencrypted, pwd/otp/pin in cleartext, .htpasswd, SFTP password exposure).
  The count query took about 40 ms longer (90 → 130 ms warm).
- Not run here: `npm run test:visual` (the lead runs it). Home and Alerts empty-state text and the
  Alerts activity line changed, so snapshots that show them will change.

## Lessons

- A zero needs its evidence beside it: the pipeline's current state, labelled as now, not as the
  period's coverage.
- Check a name-based predicate against the whole enabled ruleset, not only the matches seen: 42
  enabled rules hit the credential words, and 4 of them were admin events.
- A query clause and its Python twin need one table test that runs both on the same records.

## Next

- Deploy: rebuild daemon and web only (`scripts/remote/deploy-release-audit.sh`, lead's script). No
  data or compose change. Stored credential matches count at once.
- Still open: the category label for promoted credential groups, and the Home and traffic trend
  windows (TRF-6, traffic area).

## Follow-up (same day): the items first listed as out of scope

- **Threat intel (ALR-12 in part):** `ThreatIntelService.enrich_alerts` had no caller outside tests
  and called a list hit "confirmed malicious infrastructure"; retired in an OLD CODE block. The feed
  NetTap fills from Suricata's COMPROMISED/DROP/CINS/DShield rule matches is now labelled "Suricata
  blocklist rules", not "ET Compromised IPs". The address page says when the address was listed:
  named by a rule in this window, named on an earlier Threats scan (the cache keeps no date), or
  cached while this window couldn't all be checked (`threat_intel.in_window`: true, false, null).
- **Kill chains (ALR-18):** the assessment calls stages NetTap's reading of rule matches and says
  only the gap between successive stages is bounded by 24 hours. The Threats page says "Possible
  kill chains", "N found", "Rule matched" and "Not in this chain".
- **Trends:** the device page's Rising/Falling icon is gone, because `compute_trend` is a rate with no
  comparison window. The Alerts page category trend (`api.alerts.category_trend`) drops the partial
  first and last slots and the oldest slot of an odd count. It needs 4 whole slots, 20 alerts and
  alerts in both halves, or it says "not enough data".
- **Device page empty list:** "No alert groups to review for this device in this period" beside the
  pipeline state, or "Can't tell if this device has any alert to review" while data isn't arriving.
  It says groups, because suppressed and context groups are left out.
- **HON-49:** a failed 24 h alert count shows a muted "?" badge with "Couldn't load the alert count"
  for screen readers; zero still shows no badge.
- Tests: with the old sources restored, 9 daemon tests fail plus an import error in
  `test_category_trend.py`, and 12 web tests fail. Daemon 4,316 passed, 4 skipped. Web 4,362
  passed. svelte-check 0 errors. check:colors clean. Codex: 1 round, REVISE, all 5 points taken.
  The visual fixtures for the address and Threats pages carry the new label, and the address fixture
  carries `in_window`.

## Follow-up (same day): Home and traffic category trends (TRF-6)

- **Problem:** Home's Bandwidth, Connections and Alerts deltas, and the Traffic category page's
  deltas, compared the window ending now with the window before it. Zeek writes a connection when it
  ends, stamped with its start. So the newest minutes of the current window were still filling in,
  and every delta leaned down, most on 1h and 6h. A previous window from before NetTap had data was
  compared against a gap ("new", or a big rise). The category page also kept the last previous
  reply when a refresh's previous request failed.
- **Fix (web only):** `web/src/lib/utils/window-trend.ts`. `trendWindow(hours, now)` gives two
  back-to-back windows of `hours` each. They end at the last slot boundary at or before now − 15 min,
  in slots of at least 12 a window (1h→5m, 6h→30m, 24h→1h, 7d→12h, 30d→1d), aligned to the UTC epoch
  as `time_slots` is. `compareHalves` keeps the slots in [from, to). It wants every slot present with
  at least one connection, and an even count, or it says "not enough data". With `zeroIsUnknown`
  (alerts), a half with no alerts is not enough data, because Zeek coverage doesn't prove Suricata's.
  Home asks for `/api/traffic/bandwidth` and `/api/alerts/timeline` over that window, in place of the
  second summary and count. The request count is unchanged. Alerts are gated by the connections in
  the same slot. The category page asks for its own bandwidth series and gates on the category's own
  connections. Its devices delta ("+N new") is dropped, because distinct devices don't add up across
  slots. A failed comparison says "Couldn't load the comparison", and "not enough data" says "Not
  enough data to compare". A real comparison says "vs previous 24 hours, up to 13:00".
  `computePreviousPeriod` and the category page's `computePrevTimeParams` are in OLD CODE blocks.
- **Alerts visual fixture:** each category's `trend` is what `category_trend` returns for its
  sparkline. Malware's sparkline is now [1, 2, 3, 6, 9, 10], still 31 in all, so the snapshot keeps
  one real "increasing". Reconnaissance, Exploit and Credential abuse are `not_enough_data`.
- **Tests:** `window-trend.test.ts` (7), `home-trends.test.ts` rewritten (5), `home.test.ts` (+1),
  and the category page (1 rewritten, 2 new). With the old sources restored, 9 fail. Home's refresh
  and link tests now stub `/api/alerts/timeline`. Web 4,440 passed. svelte-check 0 errors.
  check:colors and check:e2e clean. Codex: 1 round, REVISE, 2 of 3 points taken (the `timed_out`
  point is left to B-f's partial-results flag).
- **Lessons:** a minimum connection count adds nothing once every slot must hold a connection and
  every window has 24 slots or more. An alert count of 0 can't vouch for itself.
- **Next:** the counting-at-start data model (TRF-6's root) is out of scope. The KPI values still
  cover the window up to now; only the deltas use settled windows.
