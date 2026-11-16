# Threats page: investigation layout, beaconing and DNS drill-downs, 2026-11-16

**Linear:** created by the lead
**Branch:** `fix/threats-page-drilldowns`
**Status:** on the branch, not merged. Plan approved by Codex (rev 3); review gates still to run.

## Ask

The owner, on /threats: fix the Auto-investigations layout; make a Beaconing row drill down (a new
page if needed); make a DNS anomaly row clickable, with an explanation that fits that anomaly.

## Root cause

- **Layout.** `.inv-body` was one `repeat(auto-fit, minmax(240px, 1fr))` grid holding the three
  sections and the todo, and `.inv-todo` spanned `1 / -1`. A spanning item fills every track, so
  auto-fit never collapsed the empty ones: one or two sections sat in a quarter-width column, and
  their values wrapped letter by letter.
- **Beaconing.** The rows opened nothing, and no endpoint returned one pair's calls or timing.
- **DNS.** The rows opened nothing. The NXDOMAIN row's text ("consistent with DGA domain
  bruteforcing") read the G11's case wrongly: all 364 failures were one DNS service discovery
  name. No endpoint listed one device's failed names.

## Fix

- **Daemon**
  - `services/threat_detection.py`: the DGA and tunnelling checks move into `dns_name_evidence()`,
    which returns what each check measured on the raw stored name. `analyze_dns_anomalies` builds the
    same rows from it.
  - `api/threat_drilldowns.py` (new): `GET /api/threats/beaconing/pair` times one pair with the scan's
    rule and returns `timing.status` (periodic, irregular, too_few, capped), the gaps, the TLS and DNS
    names, and the blocklist state. `GET /api/threats/failed-lookups/{ip}` returns the totals,
    timeline, response codes, and the failed names with their kind. Both count excluded devices, as
    the detectors do, and say so.
  - `api/domains.py`: `?finding=<raw name>` (must canonicalise to the route's name, else 400) counts
    every device, marks the excluded askers, and returns the check's evidence.
  - `api/server.py`: registers the two routes.
- **Web**
  - `routes/threats/+page.svelte`: the sections get their own grid with the todo below it; a narrow
    section stacks label over value; an IPv6 address breaks only after a colon. A beaconing row opens
    its pair; a many-hosts device links to its page; a DNS row opens why it was listed.
  - New pages `routes/threats/beaconing/[device]/[server]/[port]` and
    `routes/threats/failed-lookups/[ip]`.
  - `routes/domain/[name]/+page.svelte`: finding mode ("Why NetTap's DNS check lists this name",
    excluded askers marked, starts on the link's `?range=`).
  - `lib/utils/beacon.ts`, `lib/utils/dns-anomaly.ts` (new): the words, text only over the daemon's
    evidence. Nothing in them clears a finding; the first step is always to find the app.
  - `lib/api/threats.ts`, `lib/api/drilldown.ts`: clients; `routes/api/[...path]/+server.ts`: 30 s
    allowances for both endpoints.

## Files

Daemon: `services/threat_detection.py`, `api/threat_drilldowns.py`, `api/domains.py`, `api/server.py`,
`tests/fake_drill_opensearch.py`, `tests/test_threat_drilldowns_api.py`, `tests/test_domains_api.py`,
`tests/test_threat_detection.py`.
Web: the files above plus their tests, `e2e/visual/fixtures/threats.ts`, `e2e/visual/routes.ts`,
`e2e/visual/threats-layout.visual.ts`.

## Tests

- Daemon: 5104 passed, 5 skipped (whole suite, no failures). New: pair validation, periodic, nine
  calls (too_few), 100 calls in nine slots (too_few), irregular, capped, blocklist states, excluded
  device; failed lookups with kinds, `foo.arpa` as `other`, kinds beyond the 100 listed, a capped read
  that misses a busy name; domain finding mode; `dns_name_evidence` on the G11's DGA name, a
  trailing-dot name and a mixed-case name. The fake's composite date histogram now honours
  `fixed_interval`. ruff 0.17.3 check and format clean.
- Web: Vitest 5433 passed; svelte-check 0 errors; check:colors clean; check:e2e clean.
- Not run here: `npm run test:visual` (the lead runs it; `threats-layout.visual.ts` is new).

## Lessons

- An item spanning `1 / -1` in an auto-fit grid keeps every empty track. Put the full-width item
  outside the grid.
- Explain a detection from the detector's own measurement, returned by the daemon, so the words can
  never drift from the rule.
- A composite read is in key order, not by count: a capped list is the first names alphabetically,
  and the page must say so instead of calling it the busiest.

## Next

- The investigation and kill-chain rule names link to `/alerts/rule/[name]` once that route lands
  (the lead asks for it).
- The investigations form fix was dropped from this branch (lead follow-up).
