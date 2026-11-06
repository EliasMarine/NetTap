# 2026-11-06 — Drill down from every IP and domain (NET-160, slice 1)

**Status:** built on `feature/drill-down-links`. The PR and the G11 check are pending.

**Problem**

The owner, 2026-11-06: "If it makes sense for an entry or feature for a user to be able to drill down and get to the information they need, they should be able to drill down to granular levels."

Before this change:
- IPs on most pages were plain text, behind a right-click menu few people find.
- Domains were never links.
- Some links went to the wrong place:
  - Alerts' top destinations opened a device page for internet hosts.
  - The Connections menu sent `src_ip`/`dst_ip` parameters the page ignored.
- No page answered "what is this internet address?" or "what is this domain?".

**The owner's decisions (2026-11-06)**
- A LAN device IP goes to `/devices/<ip>`.
- An internet address goes to a new address page.
- A domain goes to a new domain page.
- Investigations and Security posture are added to the nav.

**Plan**

`plans/2026-11-06-net160-drill-down-slice1.md`, approved by Codex in 5 rounds. Its 24 findings were all accepted; the log is in `.codex-review/2026-11-06-081500-drilldown/`. The accuracy rules it set:
- Every list is complete or flagged, and a KPI is withheld when its list isn't complete.
- One point-in-time snapshot per request, and every reply is checked (timeouts, failed shards, missing aggs).
- A byte total that wasn't recorded shows "Not measured" or "at least", never 0.
- Domain names match ignoring case and a trailing dot.
- DNS figures use the DNS page's own filters.
- The domain alerts metric is "tagged with this name", always shown with its coverage, or "Not recorded".
- Certificates are filtered in the daemon before tallying, and the link carries the window.
- The Connections IP filter is an exact either-side filter, not free text.

**Daemon (branch `feature/drill-down-daemon`, 5 commits)**
- `storage/snapshot_search.py`: the PIT, budget and checked-reply code, extracted from the certificate pass, plus composite paging that reports completeness. `cert_overview.py` imports it and its 37 tests are unchanged.
- `api/drilldown_runner.py`: worker thread, two at a time, queue time counted in the 25 s budget, and the permit held until the worker ends.
- `GET /api/network/lan`: the daemon's LAN rule, IPv4 only.
- `GET /api/addresses/{ip}` gives the address's:
  - connections, and data to and from it, with coverage;
  - peers and the ports reached on it;
  - the TLS names it served, with validation;
  - alerts and threat intel.
- `GET /api/domains/{name}`:
  - lookups, the devices that asked, and the answers (IP, name or other);
  - response codes and TLS servers, clients and statuses;
  - HTTP requests;
  - alerts tagged with the name, with coverage.
- `/api/certificates/overview` takes `site` and `server`.
- `/api/traffic/connections` takes an exact `ip`.
- `services/hostnames.py`: canonical names, both-forms case-insensitive matching, and the keyword-mapping check.
- `services/threat_intel.py`: an `available` property.
- `scripts/remote/deploy-drill-down.sh` checks on the device.

**Web (branch `feature/drill-down-web`, 12 commits)**
- `lib/stores/lan.ts`: the daemon's LAN rule, fetched once and every 5 minutes. Until it loads, an IP links nowhere rather than guessing.
- `IPAddress.svelte`: every IP is a link (LAN → `/devices/<ip>`, otherwise `/address/<ip>`). The right-click menu sits beside the link, not inside it, so there is no nested interactive element. `linked={false}` keeps plain text where a link makes no sense.
- `lib/utils/drilldown.ts`: `ipHref`, `domainHref`, `certificatesHref`, used by every page.
- New pages `/address/[ip]` and `/domain/[name]`. Every list says when it stopped at its cap, a withheld KPI says why, and a byte total nobody recorded reads "Not measured".
- Connections sends `ip` as its own parameter and reads `?ip=` when the URL changes.
- Certificates opens on `?site=&server=&from=&to=`.
- Links fixed: Alerts' top destinations, the Connections menu, DNS recon `?domain=`.
- The sidebar gains Investigations and Security posture.
- The catch-all proxy gives `/api/addresses` and `/api/domains` 30 s; the explicit `/api/traffic/connections` proxy forwards `ip`.
- Visual fixtures for both pages; DESIGN-SYSTEM.md states the link rules.

**Tests**
- Daemon: 3,112 passed, 1 skipped (was 3,053). ruff clean.
- Web: 3,118 passed (was 3,006). svelte-check 0 errors. Colour gate clean. e2e tsc ok.

**Still to do**
- `/deep-review`, `/ponytail-review`, the two-angle review, the PR, then the device check.

**Lessons**
- An explicit proxy with a parameter allowlist silently drops new parameters. Check every `+server.ts` between the page and the daemon when an API gains one. Codex caught this in round 4.
- `complete_terms` discards its completeness flag. Use composite paging when the page presents a list as whole.
