# Security posture score formulas, 2026-11-16

**Linear:** NET-308 (the lead files the fix issue)
**Branch:** `fix/posture-score-formulas`
**Status:** committed on the branch; not pushed. Daemon and web change together: deploy both containers.

## Ask

The owner approved fixing the five formula flaws #313 found and stated on the category pages.

## Root causes

1. **Encryption** counted every eligible connection. On the G11 most of them were one-way attempts
   (BitTorrent peers from 192.168.1.205): 917,850 unencrypted, of which 46,505 carried data both ways.
2. **DNS security** counted lookups to your own resolvers (192.168.1.174, .6, .1) as plain, though .174
   and .6 forward over DNS-over-TLS.
3. **Network segmentation** used the same scored ÷ seen device count as Monitoring coverage.
4. **Alert response** was 0 whenever alerts existed and nobody opened an investigation, and divided all-time
   investigations against 24 hours of alerts. No page could link an alert to an investigation.
5. **Patch currency** summed service labels, so a two-label connection counted twice.

## Fix

- **Encryption:** only connections with data both ways are scored (`PAYLOAD_BOTH`, the NET-222 rule, now
  defined once in `daemon/services/excluded_ips.py`). `/api/traffic/protocols` reports `encryption.one_way`,
  what that leaves out. The posture detail and its Log Explorer links read the same set.
- **DNS security:** plain lookups and DoT connections to private or local-scope addresses are left out on
  both sides (`dns.local`), so a resolver is judged by what it sends out. Unknown scope still counts.
- **Network segmentation:** scored from IoT isolation (`/api/iot/network-isolation`). A pair costs points
  only if it reached the host (data both ways); an attempt with no data back stays a finding, worded
  "reachability not confirmed". The IoT page reads the same score. The web checks the reply's shape, so a
  malformed one reads "Couldn't compute", never 100.
- **Alert response:** new `GET /api/posture/alert-response`. The score is the share of high-severity
  (Suricata priority 1) counted rule groups with an investigation open during the window that links one of
  the rule's alerts. Linking an alert now stores the rule name the daemon reads at link time
  (`alert_rules`), so coverage survives the alert's index expiring. `alert_ids` and `alert_id` are
  validated (a non-string was a 500). The alert drawer has "Open an investigation".
- **Patch currency:** `protocols.patch` counts each connection once.
- One 24-hour window for all six requests on the overview.

## G11 simulation (read-only, 2026-11-16, 24 h)

| Score | Before | After |
|---|---|---|
| Encryption | 15 | 74 |
| DNS security | 33 | 52 |
| Network segmentation | 100 | 100 (isolation A) |
| Patch currency | 98 | 98 |
| Alert response | 0 | 0 (0 of 13 high rules investigated) |
| Monitoring coverage | 100 | 100 |
| Overall | 53 F | 71 C (86 B once the 13 rules are investigated) |

## Tests

Daemon: `test_traffic_api.py` (score inputs, DNS split on documents), `test_posture_api.py`,
`test_posture_alert_response.py` (new), `test_investigation_alert_links.py` (new),
`test_investigation_rules_store.py` (new), the isolation tests (real aggs on conn documents). Web:
`score.test.ts`, `report-*.test.ts`, `posture.test.ts`, the overview and category page tests, the alert
drawer and `alert-view` tests. `tests/fake_drill_opensearch.py` learnt the `ids` query.

## Lessons

- A share needs a denominator that the numerator can reach: one-way attempts can never be encrypted.
- Exclude the same scope on both sides of a ratio, or a local hop scores as a win or a loss.
- Two scores built from one figure aren't two measurements.
- A score that reads 0 because no page can produce the input is a missing feature, not a finding.

## Next

- Deploy, then check the six scores on the G11 against the table above.
- Re-linking an alert to an existing investigation is API-only (no button yet).
