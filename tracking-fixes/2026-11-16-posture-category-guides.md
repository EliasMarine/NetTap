# Security posture category pages, 2026-11-16

**Linear:** to be filed by the lead
**Branch:** `feature/posture-category-guides`
**Status:** committed on the branch; not pushed. Daemon change: deploy the daemon and web containers together.

## Ask

The owner: "For the /security-posture page, when a card is clicked for example 'encryption' or 'DNS
security' the user should be taken to a page that provides ample information on what this category is and
how they can improve their security posture. At the moment, this page provides no useful tips, just numbers
and a few findings."

## Root cause

Not a bug. Each card had a score, a one-line description and two or three counts. Nothing said which
devices or services drove the score, what the score can't see, or what to change. The daemon had no query
that tied the Encryption, DNS or Patch figures to devices.

## Fix

- **Daemon** `daemon/api/posture.py` (new): `GET /api/posture/{encryption|dns-security|patch-currency}`.
  Same base query as `/api/traffic/protocols` (window, conn filters, excluded IPs), plus the busiest ten
  LAN devices per figure, plain/DoT resolvers with address scope, the local resolvers' own upstream
  lookups (second search), and fixed Telnet/FTP/HTTP buckets with the exact Log Explorer query for each.
  Unknown category 404, bad window 400, OpenSearch error or incomplete search 502 with fixed text.
- **Web** `web/src/lib/posture/score.ts`: the overview's scoring moved verbatim (OLD CODE kept on the
  overview), so both pages score the same way. `report.ts`, `report-traffic.ts`, `report-network.ts`
  (pure) build each page: KPIs, the formula with live numbers, what is counted and what it can't see,
  findings (severity, devices, count, fix), prioritised steps, and a state per data source (measured, saw
  nothing, couldn't tie to devices, failed). `guides.ts`: plain-English what/why, good habits and learn-more
  links (CISA, NCSC, NIST, EFF, MITRE, Android, Cloudflare, Suricata docs; checked 2026-11-16).
- **Route** `web/src/routes/compliance/[category=posture]/+page.svelte` with a param matcher (other slugs
  404). One snapshot per load over one window, replaced whole; a failed same-category refresh keeps the last
  good one under the stale notice; a late reply for a category the page has left is dropped.
- **Overview**: each card's head has "How to improve", stretched over the whole card; View findings still
  opens. `getRiskScores` takes an optional window; `connLogsHref` takes an optional query (two-argument
  links unchanged).
- **Visual harness**: six routes and empty/populated posture fixtures.

## Scoring limits found (not changed; the pages state them)

1. Encryption counts one-way attempts as unencrypted (the G11 reads 15%; about 77% without them).
   192.168.1.205's BitTorrent ports are 90% of the unencrypted connections.
2. DNS security counts LAN lookups to your own resolver as plain, even when it forwards over DoT.
3. Network segmentation and Monitoring coverage both measure scored ÷ seen devices; both read about 100
   since #96.
4. Alert response is 0 whenever alerts exist and nobody opened an investigation; investigations count all
   time, alerts 24 hours.
5. Patch currency reads no software versions, and counts a two-label connection once per label.

## Tests

- Daemon: `tests/test_posture_api.py` (17); full suite 5,097 passed, 5 skipped, 0 failed. Live read-only
  check of all four query bodies on the G11.
- Web: `score`, `report`, `report-traffic`, `report-network`, `guides`, `api/posture`, `params/posture`,
  `category-page` (loading, sources, failed detail, failed input, stale refresh, DNS after Encryption with a
  failure and with a late reply, rule links, segmentation and monitoring sources), `compliance.test.ts`
  (card links, View findings, no nested interactive), `drilldown.test.ts` (`connLogsHref` old URLs
  unchanged), `risk.test.ts` (window).
- Full web suite 5,436 passed; svelte-check 0 errors; colour gate clean. `test:visual` not run (lead).

## Lessons

- A page made of several requests needs one snapshot replaced whole, or a refresh shows a new score
  beside an old breakdown.
- Say per source what couldn't be measured; one generic empty message hid working sources behind a
  failed one.

## Next steps

- Rule links use main's `ruleHref` (NET-303, #311) over the snapshot window; rules with no name open the
  Alerts list for that row.
- Follow-up issue for the five scoring limits.
