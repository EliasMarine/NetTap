# DNS domain askers and the Suricata rule page, 2026-11-16

**Branch:** `fix/dns-suricata-drilldowns` (base `9ce4f415`)
**Linear:** to be created by the lead
**Status:** Implemented and tested locally; not deployed, not yet checked against the G11's data

## Why
The owner asked for two drill-downs:
1. "For DNS domains, when clicked, they should show what devices queried those domains."
2. "When a Suricata rule is clicked, it should show me what the affected devices or culprit devices are and provide an explanation for the rule and what it is and an external link to learn more about the risk from credible sources."

Before this, a domain click on the DNS page only highlighted the row, and a rule click opened the Alerts list filtered to that rule, with no explanation and no device view.

## What changed

### DNS page: "Devices that looked it up"
- A pick in any list (top domains bars and table, NXDOMAIN, suspicious patterns, a device's lookups) loads `GET /api/domains/{name}` (the domain page's own endpoint) over **the window that list counted**.
- The new card `web/src/routes/dns/DomainAskers.svelte` lists each device (registry name or address), its lookups and when it last asked. It also holds the selected-domain chips (open domain page, copy, clear), which moved there from "DNS by device".
- A Refresh asks again within the same refresh and counts it in the outcome (askers failing makes the refresh `partial`). A pick follows its list's new window only when that list refreshed; if the list failed, the pick keeps the window the list still shows.
- Only the newest pick writes (`askersGen`). A new range or Custom window clears the pick.

### Rule page: `/alerts/rule/{name}`
- **Daemon:** `GET /api/alerts/rule/{name}?from&to&interval&activity` (`daemon/api/suricata_rule.py`). It is keyed by the exact `rule.name`, as the Alerts list's `signature=` filter is, and counted with the list's own query, so every figure equals the list it links to.
  - Facts are per SID, from each SID's newest alert: ET ratings, categories, ATT&CK techniques and tactics, CVEs, CISA KEV, IPFire DBL lists, and whether it is a credential rule. A SID's facts are never mixed with another SID's. They reach the page-level explanation only when every SID agrees (`rules_complete` and no alert without a SID).
  - Addresses: one terms list per side finds them. Each shown row is then counted exactly with per-address filters. Shown rows are a bounded selection (100 devices, 20 remote, 20 IPv6), picked by source count plus destination count. The page says so and never calls it a top list. IPv6 addresses are "Locality unknown", because the LAN rule covers IPv4 only.
- **Explanations:** `daemon/services/rule_explainer.py` explains a rule by its name's family: the ET/GPL class word, IPFire DBL, reputation lists, Suricata's own checks, or your own rules (SID 1,000,000 to 1,999,999). Curated SID texts come from `AlertEnrichment.sid_text`. The IPFire DBL text says NetTap did not block the traffic.
- **Learn more links:** built only from templates with validated ids: NVD for a CVE, the CISA KEV catalogue, MITRE ATT&CK techniques and tactics, IPFire DBL lists, SANS ISC, CINS, Spamhaus, CISA phishing and malware guidance, and the Suricata rules docs. Every URL pattern returned HTTP 200 on 2026-11-15. At most 6 links; they open in a new tab with `rel="noopener noreferrer"`, and the web client rejects any link that isn't https.
- **Web:** `web/src/routes/alerts/rule/[name]/+page.svelte`. KPIs (alerts, your devices, remote addresses, last seen), a pickable timeline, "What this rule means", per-SID details, and the devices and remote-address tables. A switch picks the counted or the activity list; an empty list offers the other. Every figure opens the exact Alerts list over the response's own window.
- **Click sites switched to the rule page** (old links kept as OLD CODE): the Alerts table, Top signatures (name to the rule page, count to the list; rows are no longer a filter toggle), the alert drawer, the Suricata category and alert category pages, Home and device smart alerts (the ×N keeps the exact list), the MAC page, the moment page, and both connection drawers. `ruleHref(name, window?, {activity})` is exported for the posture and threats work.

## Files
- Daemon: `api/suricata_rule.py` (new), `services/rule_explainer.py` (new), `services/alert_enrichment.py` (`sid_text`), `api/server.py` (registration), tests `tests/test_suricata_rule_page.py`, `tests/test_rule_explainer.py`.
- Web: `lib/api/drilldown.ts` (`getSuricataRule` + types), `lib/utils/drilldown.ts` (`ruleHref`), `routes/api/[...path]/+server.ts` (30 s for `/api/alerts/rule/`), `routes/alerts/rule/[name]/*` (new), `routes/dns/DomainAskers.svelte` (new), `routes/dns/+page.svelte`, and the click sites above. Visual: `e2e/visual/fixtures/suricata-rule.ts`, `routes.ts`, `drilldown.visual.ts`.

## Tests
- Daemon: `pytest` 5154 passed, 5 skipped (whole suite); ruff 0.17.3 check and format clean on `daemon/`.
- Web: `vitest run` 402 files, 5411 passed; `svelte-check --threshold error` 0 errors; `check:colors` clean.
- Visual sweep (`test:visual`) not run here: the lead runs it.

## Lessons
- A rule name can belong to several SIDs with different metadata. Explain the name, and show each SID's own facts beside it. Promote one SID's advice only when it speaks for every alert.
- "Top N" wording is wrong for a selection ranked by source plus destination counts (self-alerts weigh twice). Say how the rows were picked.

## Next steps
- Deploy, then check the rule page on the G11 against `/alerts?signature=…` for a DBL rule, a Dshield rule and a credential rule.
- The connection drawers and the MAC page link by the shown signature, as they did before. When the shown signature differs from `rule.name`, the rule page is empty, as the list was.
