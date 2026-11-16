# Device protocols and first seen (PR B), 2026-11-16

**Linear:** NET-317 (the follow-up to NET-314 and NET-316)
**Branch:** `feature/device-services`, rebased onto `origin/main` 2db2fdc0 after PR A (#331) merged
**Status:** implemented and tested locally. Deploy with `scripts/remote/deploy-device-services.sh`.
**Plan:** PLAN.md passed /codex-review in 3 rounds. This PR got First seen and the New chip from PR A, because both come from the daemon.

## What the owner asked

"implement all of these please", meaning every item on the NET-314 shortlist. This PR is the part that needs the daemon.

## Fix

| Item | What it does | Where |
|---|---|---|
| `services` | A device's three commonest `network.protocol` values in the window. Both directions are counted (it started the connection or answered it), and IPv4 only. It is one extra aggregation over the listed IPs, at most 500. The side size is 40 and each side is checked for completeness: if a side is cut, that IP gets `null` (unknown), never a short list. A failed or malformed reply sets `null` on every row and the list still answers 200. | `daemon/api/devices.py` `_device_services` |
| `known_since` | The registry's `first_seen` for the row's MAC. The list now reads the registry once (`_registry_known`), and that one read gives both the names and `known_since`. The answer-only devices' bucket MAC counts as well. | `_registry_known`, `_registry_names(known=)`, `handle_device_list` |
| Protocols column | Labels such as TLS, DNS or QUIC, joined with " · ". It sorts by that text. "Unknown" means it couldn't be read, and "—" means none were identified. A note under the table counts the unreadable rows, or says the whole period failed when every row did. | `web/src/routes/devices/+page.svelte` |
| First seen column | "2h ago" style, sorted by time, with a title saying it covers all time, not just this period. "—" when missing or unreadable. | same |
| New chip | The banner's rule (the registry first saw it in the last 24 h), shown beside the name in every name branch. | same, via `isNewDevice` |
| CSV | Protocols as raw keys (`ssl dns`) and First seen as ISO. Blank when unknown. | `devices/devices-csv.ts` |
| Deploy | `deploy-device-services.sh` times `/api/devices` before and after, counts `services`/`known_since` in the reply, and checks the built columns by their key line. The token goes through stdin and is never printed. | `scripts/remote/` |

## Tests

- Daemon: `test_device_services.py` (new) covers:
  - the query shape, merge, top 3 and a cut side;
  - every malformed shape, including dict-for-list;
  - a failed read giving 200 with `null`;
  - known_since, with the registry down and read once;
  - `_registry_names` with or without a reading.
  - Full suite: 5308 passed, 5 skipped.
- Web: `devices.test.ts` covers:
  - Protocols labels and sort, and Unknown vs "—";
  - the note for all and for some;
  - an older daemon without the fields;
  - First seen, including unreadable;
  - the New chip, including beside a UniFi name.
  - `devices-csv.test.ts` is updated.
  - Full vitest run: 423 files, 5686 tests. svelte-check: 0 errors. check:colors: clean.
- Gates:
  - /ponytail-review: clean.
  - /deep-review: no findings (`security-reviews/feature-device-services/`).
  - security-engineer: nothing at any severity.
  - typescript-reviewer: one MEDIUM and four LOW, all fixed.
  - python-review: PASS, with one MEDIUM test gap and LOW items, fixed except two type nits.

## Lessons

- `services: null` is per device, not per request, so a note about it must count the rows.
- In Svelte 5, helpers that `columns` uses must be declared above it, or the page throws a TDZ ReferenceError on load.
- esbuild writes long column objects across lines, so deploy checks grep `key: ?"<field>"` alone.

## Next steps

- On the G11: run the deploy script and compare the `/api/devices` time before and after.
- Shortcut: IPv6 conversations aren't counted in Protocols. Add `source.ip`/`destination.ip` IPv6 terms if the owner wants them.
