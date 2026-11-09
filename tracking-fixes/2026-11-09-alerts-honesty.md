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
- Out of scope, listed for the lead: `threat_intel.enrich_alerts` wording ("confirmed malicious
  infrastructure", dead code), kill-chain wording (ALR-18), the Rising/Falling arrow from
  `compute_trend`, the device page's "No actionable alerts for this device.", the sidebar badge
  (HON-49), and the category label for promoted credential groups.
