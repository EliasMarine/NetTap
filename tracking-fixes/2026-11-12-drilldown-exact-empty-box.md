# Drill-down exact lists and the empty box, 2026-11-12

**Linear:** NET-185, NET-184, NET-182
**Branch:** `fix/drilldown-exact-lists-and-empty-box` (from `main` 32e90fd2)
**Plan:** `.codex-review/2026-11-12-174221-drilldown-exact-empty-box/PLAN.md` (Codex: round 1 REVISE, round 2 APPROVED)
**Status:** built and tested locally; not yet deployed to the G11.
**Debugging log:** `Debugging/DEPLOYMENT-ISSUES.md` Chain 32 (NET-182).

## Why

A figure on a page has to equal the list its link opens, and a box with no data yet has to show zeros, not errors.

## What changed

**NET-185: a category's figures open their own lists.**
- **Cause 1:** the category page kept its range in local state and ignored the URL. A category bar on Alerts opened it at 24 hours whatever window the bar counted.
- **Cause 2:** the category's Top signatures put a rule named "Unknown" and alerts with no `rule.name` into one "Unknown" bar. Neither link held that figure.
- **Fix:**
  - `/alerts/[category]` reads `range`, `from` and `to` from the URL. A link with `from`/`to` opens as "Custom"; a range pill writes `?range=` and clears it.
  - The category bar on Alerts carries the window its counts used.
  - `_every_signature` keeps no-name alerts as `null`. `GET /api/alerts` takes `no_rule_name=true|false` (anything else is a 400) and the proxy forwards it unchanged. The row reads "No rule name" and links with `no_rule_name=true`; Alerts shows it as a chip.
  - Alert rows, their row labels and the drawer say "No rule name" too, where they said "Unknown" (a rule can really be named that).

**NET-184: a top source or destination bar opens exactly its figure.**
- **Cause:** the bar counted `source.ip` (or `destination.ip`) over the card's window, but its link searched `ip` (either side) over a fresh window, with the page's other filters still on.
- **Fix:**
  - The bar opens a `source.ip:"…"` or `destination.ip:"…"` search over the card's own window, with the query, DNS, excluded sources and log type cleared. The chip reads Source or Destination.
  - Sorting keeps the search's window.
  - The daemon answers 502 when a shard cut either bar list short, instead of returning an estimate.

**NET-182: a box with no index answers zeros, and the device cap says why.**
- **Cause:** with no `arkime_sessions3-*` index yet, OpenSearch answers `_shards.total` 0 with no `aggregations`. Checked reads take that as incomplete, so Devices, the device count, risk scores and protocols said "incomplete" on a fresh box.
- **Fix:**
  - `ExactTermsOpenSearch.search` gives that reply the empty aggregations its body would get from an empty index (`with_empty_aggregations` in `storage/exact_terms.py`). The empty forms were captured from the G11's OpenSearch. Any kind without a known empty form (`date_range`, `date_histogram`, a composite's later page, `filters` with an other bucket) leaves the reply unchanged, so it still fails closed.
  - A device read stopped at 20,000 LAN sources writes a `device_cap_reached` Changelog event, at most once a day. A failed write is retried after 5 minutes. The Changelog labels it "Device limit reached".

## Device script

`scripts/remote/deploy-drilldown-exact-empty-box.sh` rebuilds web and daemon, then checks over a 24-hour window that ended 2 hours ago:
- every category bar = its page's total = its list's total, and every Top signatures bar = its list (including no rule name);
- `no_rule_name=maybe` is a 400;
- the top 3 source and destination bars = their one-sided searches;
- a search of a missing index through the daemon's own client returns empty aggregations;
- the Changelog types include `device_cap_reached`, and the device reads answer 200.

A dry run against the current (unfixed) daemon passed every check that doesn't need the fix and failed the three that do.

## Verification (local)

- daemon pytest: 4682 passed, 4 skipped, 2 failed. Both failures are in `test_cert_monitor.py` and fail on `main` too.
- Vitest: 354 files, 4558 passed. svelte-check: 0 errors, 2 warnings (same as `main`). `check:colors`: clean.
- The new tests fail with the old code.

## Lessons

- A count and its list must share three things: the window, the filter, and the field. NET-184 had the first right in the URL and the other two wrong.
- "No value" and a value named like a placeholder ("Unknown") are different rows. Never merge them for display.
- A search of no index is complete and empty, not partial. Fill only the shapes you know; fail closed on the rest.

## Next steps

- Deploy with the script above and close the issues.
- Follow-ups: the category page's table links a row by its shown signature, not its `rule.name` as Alerts does; Alerts' own Top signatures and the Suricata page could link their no-name rows with `no_rule_name=true`; the category page has no "You clicked N" line; drill-down pages that page with a PIT (address, domain, Suricata, certificates) are untested on a box with no index.
