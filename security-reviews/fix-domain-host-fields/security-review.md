# Security review: fix/domain-host-fields (NET-178)

## Review metadata
- Branch: `fix/domain-host-fields` @ 2e9135c, against `origin/main` (commit date 2026-11-06).
- Scope:
  - `daemon/api/domains.py`
  - `daemon/services/hostnames.py`
  - `scripts/remote/deploy-drill-down.sh`
  - `web/src/lib/api/drilldown.ts`
  - `web/src/routes/domain/[name]/domain-view.ts`
  - `web/src/routes/domain/[name]/+page.svelte`
  - Tests and docs were read for context only.

## Findings
No findings.

## Coverage summary
- **Domain name (URL) → query:** still checked by `canonical_name` (RFC 1123 labels, 253 characters at most). It reaches OpenSearch only as a term value through the existing `name_match`. The field names in the new aggregation come from the fixed `_HOST_FIELDS` list, plus `.keyword`. Mapping content only chooses among those fixed paths and never supplies a field name.
- **Mapping read:** one bounded `get_field_mapping` call for 8 fixed fields. It has the same budget check, timeout and error handling as before. The new warning log carries only mapping types and `ignore_above`.
- **Deploy script:**
  - Every new use of `$NAME` sits inside the existing `^[a-z0-9._-]+$` guard.
  - `HOST_FIELDS` is the daemon's constant and must start with `[`.
  - Text derived from the mapping reaches Python only as data (stdin or argv) or is printed.
  - The values pasted into Python code are built from the fixed field list and four fixed tags.
- **Web:** the new optional fields are type-checked (a boolean, and arrays of strings). The note is rendered as escaped Svelte text, and the page has no `{@html}`.
- **Auth:** no new route. The token middleware is unchanged.

## Limitations
- Run as a reduced pass: one independent high-effort reviewer plus the coordinator's own read, because the diff adds no new input surface.
- Not checked: how `page_vs_raw` splits a label containing `|`. That matters only if the `NAME` guard is ever loosened.
