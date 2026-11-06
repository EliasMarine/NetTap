# 2026-11-06 — The domain page answers when an alert host field is mapped as text (NET-178)

**Status:** fixed on `fix/domain-host-fields`, not yet verified on the G11. The PR is pending. Plan: `.codex-review/2026-11-06-134602-domain-host-fields/PLAN.md` (Codex approved, round 4). Deployment log: Chain 26 in `Debugging/DEPLOYMENT-ISSUES.md`.

**Problem**
- On the G11, `GET /api/domains/ip.qurl.in` answered 502 in 0 s, so every domain page showed only its error state.
- The same run found PCAP capture stopped for 21 hours. That part is NET-179, handled by `scripts/remote/fix-pcap-capture-stopped.sh` (PR #183).

**Root cause**
- `domain_figures` (`daemon/api/domains.py`) ran `require_keyword` on the three Zeek name fields and the four Suricata alert host fields (`related.hosts`, `dns.question.name`, `tls.client.server_name`, `url.domain`).
- The four host fields only feed "Alerts tagged with this name", but a failure on one of them failed the whole page.
- On the G11, `tls.client.server_name` is mapped `text` in every `arkime_sessions3-*` index, `dns.question.name` is unmapped, and the others are keyword.
- A term query on a text field matches words, not whole values, so the field can't just be queried instead.

**Fix**
- `daemon/services/hostnames.py`:
  - `_field_types` reads the mapping once (type and `ignore_above` per index), with the old timeout, error and malformed-reply handling.
  - `require_keyword` keeps its behaviour, built on it.
  - New `keyword_paths(client, fields, budget)` returns (matched paths, unmatched fields):
    - the field, when every index that maps it has it as keyword with `ignore_above` absent or at least 254 (a 253-character name plus the trailing dot);
    - else `<field>.keyword`, when that holds for the subfield in every index that maps the field;
    - else the field is unmatched, with a warning naming it and its mapping;
    - a field no index maps is in neither list.
- `daemon/api/domains.py`:
  - `require_keyword` now covers only the three Zeek fields (the page's own figures stay strict).
  - The host fields go through `keyword_paths`.
  - "Carrying a host name" = `exists` on the four fields plus every matched path (a `.keyword` can hold what its parent's `ignore_above` drops).
  - "Tagged" searches only the matched paths. With an unmatched field it is an exact lower bound: `tagged_partial: true` and `unmatched_fields`. With no matched path it is `null` with `tagged_partial: true`. No alert carrying a host name stays `null`, not partial ("Not recorded").
  - The reply always carries `matched_fields` and `unmatched_fields`.
- Web:
  - `web/src/lib/api/drilldown.ts`: the three fields are optional in the type, so an older daemon's reply still loads; when present they must be well-formed.
  - `web/src/routes/domain/[name]/domain-view.ts`: `taggedFigure` ("At least N", "Can't be counted on this NetTap", "Not recorded" or the number) and `unmatchedNote` (names the fields in words: "TLS names are stored on this NetTap in a way that can't be matched exactly, so alerts that name this domain only there aren't counted.").
  - `+page.svelte` shows both; the note is a warning notice in the alerts card.
- `scripts/remote/deploy-drill-down.sh`:
  - Step 4 checks only the Zeek name fields strictly. It reads the host field list from the daemon (`api.domains._HOST_FIELDS`), prints each field's and subfield's types and `ignore_above`, and works out each field's path with the rule written out again (not the daemon's code).
  - Step 6 checks three more figures against OpenSearch, read before and after the page: alerts in the window, alerts carrying a host name, and alerts tagged with the busiest name. It also checks that the page's matched and unmatched fields equal Step 4's, that unmapped fields are in neither list, and that `tagged` is withheld and `tagged_partial` set only when they should be.
- Not changed: Malcolm's index template (it would only reach new daily indices; Chain 24 says the daemon queries Malcolm's field names).

**Files**
- `daemon/services/hostnames.py`, `daemon/api/domains.py`
- `daemon/tests/test_hostnames.py`, `daemon/tests/test_domains_api.py`, `daemon/tests/fake_drill_opensearch.py`
- `web/src/lib/api/drilldown.ts`, `web/src/lib/api/drilldown.test.ts`
- `web/src/routes/domain/[name]/domain-view.ts`, `domain-view.test.ts`, `+page.svelte`, `domain-page.test.ts`
- `scripts/remote/deploy-drill-down.sh`
- `Debugging/DEPLOYMENT-ISSUES.md` (Chain 26, stack health, key files, known risks, lessons 174–176)

**Tests**
- The fake OpenSearch now models mappings: a type, `{type, ignore_above}` or unmapped, per index if needed. A `.keyword` path is absent unless set, takes its values from the parent, and `ignore_above` drops long values from term and `exists` alike.
- `test_hostnames.py` (5 new): the field matched as it is (and one mapping call for fields and subfields); `.keyword` used for text or `ignore_above` 253; unmatched for text with no subfield, a field keyword one day and text the next, a subfield missing one day, and a subfield with `ignore_above` 8; unmapped in neither list; errors still TooSlow or QueryFailed.
- `test_domains_api.py` (10 new, 2 updated for the new reply keys): text TLS field answers with an exact lower bound and is never queried by term; matched through a `.keyword` (256); unmatched with a subfield of 8 or one missing from an index; no matchable field gives `null` + partial; all unmapped gives "Not recorded"; unmapped plus text fields gives `null` + partial, not "at least 0"; an unmatched field but no alert carrying a host name stays "Not recorded"; a name only the subfield holds is tagged and carried; a 253-character name with its dot is tagged through a subfield.
- Web: validator rejects malformed partial fields (3 cases); `taggedFigure` and `unmatchedNote` (4); the page shows "At least 1" with the notice, and "Can't be counted on this NetTap" instead of "Not recorded" (2).
- Each new test fails on `origin/main`'s version of the file it covers (swap check): the domain tests with main's `domains.py` (11 failed, the 12th added after), the hostname tests with main's `hostnames.py` (import error), the validator, view and page tests with main's files. Mutating each rule in `keyword_paths` and `_alerts` makes at least one test fail.
- Daemon: 3,183 passed, 1 skipped. Ruff format and check clean on the changed files.
- Web: vitest 3,219 passed; svelte-check 0 errors (2 old warnings in drawer components); colours clean; check:e2e ok. Visual tests not run.
- Script: shellcheck clean. Step 4's and Step 6's new lines were run locally with stubbed `docker` on a G11-shaped mapping; the script's rule gave the same lists as `keyword_paths`, and the checks failed on a reply that disagreed.

**Lessons**
- Check strictly only the fields a page's main figures need. An optional figure uses what it can match exactly and says it is partial.
- `ignore_above` limits exact matching as much as the type does: read it with the type, and count coverage over every path the match uses.

**Next steps**
- Owner, on the G11: `bash /home/nettap/NetTap/scripts/remote/fix-pcap-capture-stopped.sh`; then, once this is on `main`, `bash /home/nettap/NetTap/scripts/remote/deploy-drill-down.sh` (Step 4 and Step 6 with no ✗ lines). Paste back any ✗ lines.
