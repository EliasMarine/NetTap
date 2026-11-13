# DNS resolver compare on the DNS page, 2026-11-13

**Linear:** NET-262 (child of NET-261)
**Branch:** `feature/dns-resolver-compare`
**Status:** built and tested locally. Not deployed yet; the lead deploys.
**Plan:** `PLAN.md` section 1 (Codex review, 4 rounds, APPROVED).

## Why

The DNS page could only ask NetTap's own resolver. To see split DNS (the router answers a private
address, a public resolver answers a public one or NXDOMAIN), a VPN resolver that cannot be reached,
or a filtering resolver that answers differently, you had to run `dig @server` by hand against each one.

## What changed

- **Daemon** (`daemon/services/dns_recon_service.py`, `daemon/api/tools.py`):
  - `DnsReconService.compare(name, record_type, resolvers)` and `POST /api/tools/dns-compare`.
  - Validation at the boundary: `validate_domain`, one type from `ALLOWED_RECORD_TYPES` (default A),
    and 1 to 6 resolver IP literals (v4 or v6, no scope id), normalised and each kept once.
  - It takes one of the existing lookup slots, so a busy daemon answers 503 before any dig starts.
  - One dig per resolver, all at the same time:
    `dig @<ip> +noall +answer +comments +stats +time=2 +tries=1 -t <type> -q <name>`.
    Each has a 10 s hard limit (`QUERY_TIMEOUT`) and is killed and reaped in `finally`.
  - Each reply has a status (from the `->>HEADER<<-` line), its answers, the lowest TTL and the
    query time. No reply (exit 9, "timed out", "no servers could be reached", or the 10 s limit)
    gives status null and "No reply from NetTap".
  - Each answer has a canonical `key`: owner, class, type and data, without the TTL. Names are lower
    case without the trailing dot, addresses go through `ipaddress`, and TXT stays byte for byte.
    A and AAAA answers also say `scope: private | public` (`is_global`).
  - One INFO line per compare (inputs, statuses, duration) and one WARNING per failed dig.
- **Web:**
  - `/api/tools/dns-compare` proxy with `TOOL_TIMEOUT_MS['dns-compare'] = 15_000`.
  - `dnsCompare()` in `$api/tools`.
  - The DNS page has two tabs: Lookup (unchanged) and Compare resolvers (`CompareResolvers.svelte`).
  - Up to six resolver rows, each an address and an optional label. Labels stay in the browser, and
    the last list compared is kept in localStorage (every access in try/catch).
  - The verdict (`dns-compare.ts`) is judged only over replies that came back. Answers compare as
    sets of keys, so TTL and order never count. Cases: no reply at all, one reply, agreement,
    disagreement with "This looks like split DNS." when a private answer sits beside NXDOMAIN or a
    public answer, and a VPN note for each resolver that did not reply.
  - A sortable DataTable lists the replies (resolver, status, answers, TTL, latency).
  - The Tools index card mentions the compare.

## Deviation from the plan

- dig gets the name as `-t <type> -q <name>`, not as `<name> <type>`. On the G11,
  `dig @192.168.1.1 ns A` asked for `. NS`: a name that is also a type or class word was read as
  the type. With `-q` the name is always the name, and it is still the last argument.
  The existing Lookup tab still has this quirk (out of scope; follow-up candidate).

## Verified against the G11 (read-only, 2026-11-13)

- Real dig output captured inside `nettap-storage-daemon` is in `daemon/tests/dig_compare_fixtures.py`.
- Real split DNS: `setup.ui.com` is `192.168.1.1` from the router, four public addresses from
  1.1.1.1. `nettap` is `192.168.1.199` from the router and NXDOMAIN (with an EDE line) from 9.9.9.9.
- No reply: `@192.0.2.53` (exit 9, "communications error … timed out") and
  `@2606:4700:4700::1111` (exit 9, "network unreachable"; the G11 has no IPv6 route). Everything
  dig wrote went to stdout.
- 9.9.9.9 sometimes did not answer within 2 s (google.com TXT, example.com SOA, setup.ui.com A),
  so with `+time=2 +tries=1` a slow public resolver can read as "did not reply".
- `unifi` from the router returns the same A record twice. Keys handle that.

## Tests

- `daemon/tests/test_dns_compare.py` (22): resolver validation, argv, every real fixture, no reply,
  other dig failures, canonical keys (TTL, case, IPv6 forms, TXT case, owners), concurrency,
  time-out kill and reap, cancellation, the shared slot and busy, and the route (200, 400, 503).
- `web/src/routes/tools/dns-recon/dns-compare.test.ts` (12): verdicts and storage.
- `web/src/routes/tools/dns-recon/compare-resolvers-page.test.ts` (6): tabs, loading, results,
  error, adding and removing rows, and the saved list.
- `web/src/lib/api/tools.test.ts` (+3) and `web/src/routes/api/tools/tools-timeouts.test.ts` (+2).
- Full daemon pytest 4838 passed, 0 failed. Full vitest passed. svelte-check 0 errors. Colour gate clean.

## Lessons

- Pass a dig name with `-q`. A bare positional name is read as a type or class when it is one ("ns", "mx", "in").
- Quad9 from the G11 often takes more than 2 s. Read "did not reply" with that in mind.

## Next steps

- Deploy, then compare 192.168.1.1 with 9.9.9.9 for `nettap` and `setup.ui.com` on the G11.
- Consider giving the Lookup tab's dig `-q` as well.
