# NET-355: evidence in the alert drawer

**Date:** 2026-11-23 · **Branch:** `feature/alert-evidence` · **Status:** in review

## What the owner asked
Clicking a high alert showed the matched rule and a CVE, but no way to dig deeper: "There has to be a way to see the packets in question or just the evidence right up front after the alert has been clicked."

## What was missing
- The drawer showed the rule, the explanation, the advice and the facts.
  - The packets: **View in Log Explorer** opened a generic log search, and nothing reached the packet capture.
  - The protocol fields Suricata records with an alert (TLS server name, JA4, HTTP request, user agent, file name) were only under Raw JSON.
- The pieces already existed:
  - the packet search API (`/api/packets/search`, 30-minute windows, two reader slots);
  - `connectionFilter()`, which turns a five-tuple into an exact TShark filter;
  - the log search, with the community ID Malcolm stamps on Zeek and Suricata records.

## What changed
- **`web/src/routes/alerts/alert-evidence.ts`** (pure helpers):
  - the alert's time (ISO, numeric or digit-string ms);
  - its five-tuple, with canonical IPv4/IPv6 addresses;
  - the packet search (exact tuple, a minute either side);
  - the fields Suricata recorded (fixed allowlist);
  - what Suricata saw;
  - the Zeek community-ID query (strict v1 regex);
  - the empty-result wording;
  - the download name.
- **`web/src/routes/alerts/AlertEvidence.svelte`**, placed between the explanation and "What to do":
  - **What Suricata saw:** both ends with the owner of each address, and no claim about who opened the connection.
  - **Fields Suricata recorded:** if none, it says the alert doesn't show which bytes matched.
  - **Zeek records sharing this community ID:**
    - one log search on open, newest first, 10 rows;
    - a note that a reused ID can include other connections;
    - Open all in Log Explorer.
  - **Packets near the alert time:**
    - a **Show packets** button, so browsing alerts never holds the reader. The results are a sortable table in a capped scroller.
    - One status line that never says "no match" unless a file was read to the end. The order is: skipped files, then deadline, then no capture read, then no match.
    - Capture-index context after zero rows.
    - Open in Packets, on the effective window.
    - Download, as a fetch so a 409 stays in the drawer and re-arms the button.
    - "Search the 11 minutes before", for alerts raised at flow timeout.
    - A refusal links to the blank `/packets` builder.
- `AlertDetail.svelte`:
  - inserts the block;
  - the NET-349 "DNS name" fact moved into it as "DNS names", so it shows once (kept as an OLD CODE comment).
- `packet-query.ts`: `connectionFilter` takes a `ConnectionTuple` (`Pick` of the five fields it reads). `connection-ref.ts`: `port()` is exported.
- `scripts/remote/deploy-alert-evidence.sh` and `rollback-alert-evidence.sh`:
  - Before any git or Docker change, the deploy script tags the running web image `nettap/web:rollback-net355` and records it. The three IDs must match when the record is first created; later runs only need record = tag.
  - Rollback restores that exact image locally and checks its ID and health.

## Tests
- `alert-evidence.test.ts`: 22 tests.
- `AlertEvidence.test.ts`: 16 tests.
  - only the Zeek search on open;
  - the exact search body;
  - deadline, skipped files and no-file wording;
  - effective window;
  - busy, refused and 409 handling;
  - download name.
- `alerts-page.test.ts`: Evidence sits between the explanation and What to do; the DNS name moved.
- Visual: `e2e/visual/alert-evidence.visual.ts`.
- Full suite: 6,153 tests in 448 files. svelte-check: 0 errors. check:colors: clean.
- Deploy script, checked locally with a `sudo` stub: an unwritable record stops it before any git or compose call; a branch-then-main sequence passes; a mismatched tag stops it.

## Reviews
- Plan: `/codex-review`, approved in round 7.
- `/deep-review`: no findings.
- `/ponytail-review`: Zeek sort newest first (fixed), reuse `srcPortOf`/`dstPortOf`, coverage copy.

## Lessons
- Any "nothing found" claim has to name what was actually read. A search that read no file, or skipped one, isn't evidence of absence.
- A form post that is fine on a full page (Packets' download) loses the drawer when it fails. Inside a drawer, failures need a fetch.

## Next
- Per-alert Zeek attribution in the daemon (the uid that matches the alert's flow), instead of community-ID matches over a day.
- Eve payload logging, so "Fields Suricata recorded" can show the matched bytes. Owner decision: disk use and privacy.
