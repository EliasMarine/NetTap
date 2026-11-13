# Local service browser (NET-264)

**Branch:** `feature/local-service-browser` · **Status:** built, tests green, awaiting review and deploy

## What changed

- New daemon route `GET /api/local-services?from=&to=` (default the last 24 h, at most 7 d). It lists
  the mDNS and SSDP announcements the capture saw, one row per sender (IP, MAC, VLAN as the frames
  show them). The sender is never claimed to own the service, so a router reflecting mDNS between
  VLANs gets rows of its own.
- New page `/local-services` ("Local services", in the sidebar's Devices group). It has range pills
  (1h, 6h, 24h, 7d), one search box over every column, and a sortable table: service (plain name +
  raw type), instance, announced by (name, IP, MAC), protocol, VLAN seen on, last announcement.
  SSDP rows link to Packet analysis (`ssdp && ip.src == …`, last 30 minutes). The page has
  empty, error, stale and truncated states.
- The catch-all web proxy gives `/api/local-services` 30 s, like the other drill-down routes.

## Why the read differs from PLAN.md (deviation, approved by the lead)

PLAN.md §3 asked for composites over (name, zeek.uid, source.ip) capped at 5,000 (name, uid)
pairs, with a budget overrun reported as `truncated: true`. Shipped instead: the bounded join
below, a 20,000-uid cap on the uid-by-uid read plus the 5,000-row cap (both give
`truncated: true`, and the page note names them), and a budget overrun gives the drill-down
runner's 503 "took too long". The earlier reads mean nothing without the later ones, so no
partial answer is sent.

The plan's composites over (name, zeek.uid, source.ip) were measured on the G11 (read-only,
2026-11-13):

| Read | 24 h | 7 d |
|---|---|---|
| plan: query composite | 54 pages, 53,559 buckets, 4.8 s | 247 pages, 67 s |
| plan: answers composite | 130 pages, 129,156 buckets, 21.4 s | not run (about 5× the query composite) |
| one (uid, ip) composite + name sub-terms | 28 pages, 6.4 s | 125 pages, 39 s |
| **bounded design, probe of its reads** | **1.5 s** (46 of 47 IPs single-identity, 1,166 uids joined one by one) | **3.8 s** (6,065 uids) |
| **shipped module's own reads, run against the G11** | **9 searches, 0.9–1.0 s** | **19 searches, 2.4 s** |

(OpenSearch `took` time; the drill-down budget is 20 s.)

The cause is about 27,000 mDNS uids a day. Zeek ends an idle UDP flow after a minute, so every
announcer gets a new uid every few minutes. The plan's 5,000-pair cap would be hit in about two
hours.

The shipped read keeps the plan's rules: MAC and VLAN come from the same-uid conn record, an
unresolved uid is never merged, and rows come from multicast-destination records only.
1. Identities: (IP, MAC, VLAN) of the mDNS conn records in [from − 1 d, to].
2. Open flows: uids announced in the last 15 minutes that have no conn record yet.
3. An IP seen as exactly one (MAC, VLAN) gets its closed flows' names aggregated per IP, under that
   identity (exact: every conn record of that IP names it).
4. Everything else is joined uid by uid. That covers an IP seen with several MACs or VLANs (on
   the G11 the router's link-local, untagged and on VLAN 2), an IP with no conn record, and open
   flows. If a read in steps 1–2 is capped, every uid is joined.

## Files

- `daemon/api/local_services.py` (new), `daemon/api/server.py` (registration)
- `daemon/tests/test_local_services_api.py`, `daemon/tests/fixtures/local_services_names_g11.json`
  (a G11 reply with names anonymised), `daemon/tests/fake_drill_opensearch.py` (regex
  include/exclude on terms)
- `web/src/lib/api/local-services.ts` (+ test), `web/src/routes/local-services/` (page, service
  types, page test), `web/src/routes/api/[...path]/+server.ts` (+ timeout test), nav + layout
  tests, `web/e2e/visual/fixtures/local-services.ts` (+ test), `web/e2e/visual/routes.ts`,
  `web/DESIGN-SYSTEM.md` (21 sidebar links)

## Tests

- Daemon: 18 new tests; full suite 4,834 passed, 0 failed (baseline 4,816). ruff 0.17.3 check
  and format clean.
- Web: the new tests plus the nav, layout and proxy tests; full Vitest green, svelte-check 0
  errors, check:colors clean.
- Mutation checks: merging unresolved uids, dropping the multicast-group filter, dropping the
  open-flow exclusion, treating ambiguous IPs as single, and dropping the rdata exclusion each
  fail a test.

## Lessons

- Zeek's `zeek.dns.answers` holds rdata strings like `NSEC <name> <next>`, which match a naive
  `*._tcp.local` pattern. Exclude `[A-Z][A-Z0-9]* .*` (Zeek lowercases names, so capitals start
  only its own record-type prefixes).
- Measure a composite over uid before planning on it: mDNS makes a new uid per sender every
  few minutes.

## Next steps

- On the G11 after deploy: AirPlay and Hue rows with VLANs (verified against live data through
  the module's own reads before deploy).
- Open flows give a "not yet known" row next to the known sender for a few minutes (16 to 44
  rows at a time on the G11). The plan wants this. A later version could hide them behind a
  toggle if they get in the way.
