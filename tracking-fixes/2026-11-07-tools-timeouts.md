# Tools pages stop saying "Daemon unreachable" when the daemon is only slow (NET-203)

**Date:** 2026-11-07
**Branch:** `fix/tools-timeouts`
**Linear:** NET-203
**Status:** Built and tested. PR, merge and the G11 deploy follow.

## What the owner reported

Tools › DNS reconnaissance for their domain showed "Daemon unreachable: The operation was aborted due to timeout".

## Root causes

The daemon was up. Its log shows `POST /api/tools/dns-recon -> 200 (14950.0ms)`: it answered after 15 s, but the web had already given up. Rerunning the same lookups on the G11 took about 0.3 s for all 7 types, so the 15 s came from a slow moment at the upstream DNS server (Quad9).

1. **DNS recon ran one `dig` per record type, one after another** (`daemon/services/dns_recon_service.py`). Each could take up to 10 s, so 7 types could take up to 70 s. dig's defaults (5 s per try, 3 tries) turn a slow DNS server into seconds per type.
2. **Every Tools proxy route gave the daemon the web's 10 s default** (`web/src/routes/api/tools/*/+server.ts`). That is less than the daemon's own limit for each tool: DNS 10 s per query, ping 15 s, traceroute 30 s, SSL certificate 10 s twice.
3. **`daemonFetch` reported its own timeout as "Daemon unreachable"** (`web/src/lib/server/daemon.ts`), so slow read as down.

## What changed

- **DNS recon runs its lookups at the same time** (`asyncio.gather` over a new `_query`). A request now waits for the slowest single lookup, not the sum.
  - **dig retries sooner.** `+time=2 +tries=2`: dig gives up on a slow server after 2 s, twice. Its worst case, 8 s over two servers, fits inside the unchanged 10 s limit.
  - **Each record type runs once.** Repeats are dropped, so a request starts at most 9 dig processes (the allowed types).
  - **A failed dig is an error, not an empty answer.** A non-zero exit (9 is "no servers could be reached") returns dig's own reason, or its exit code. A successful empty answer (NOERROR with no records, NXDOMAIN) stays empty with no error, as before.
  - **At most 4 lookups run at once** (`MAX_CONCURRENT_LOOKUPS`). Past that, the daemon answers 503 "DNS reconnaissance is busy. Try again in a moment." at once instead of queueing, because a queued wait would count against the web's 15 s limit. Without this cap, many lookups in parallel could each start 9 digs and run the daemon out of file descriptors.
  - **No child process is left behind.** On a timeout, an error or a cancelled request, a still-running dig is killed and reaped. A cancellation still propagates.
  - The old sequential loop is kept as `OLD CODE`.
- **Each Tools route waits 5 s past the daemon's limit** (`TOOL_TIMEOUT_MS` in `daemon.ts`): DNS 15 s, ping 20 s, traceroute 35 s, SSL certificate 25 s. All stay under nginx's 60 s `proxy_read_timeout`.
- **A timeout now says so.** "NetTap took too long to answer. Try again." It stays a 502 with `daemonAvailable: false`, because the answer never reached the web server. Every other failure still reads "Daemon unreachable: …". The change is in `daemonFetch`, so every page that proxies through it (Suricata rules, Go live and others) gets the right message too.

## Reviews

- **`/codex-review` (plan):** approved in round 2. Round 1 found three problems, all fixed in the plan before any code:
  - With unlimited parallelism, 1,000 copies of "A" in one request would start 1,000 processes.
  - A failed dig read as an empty answer.
  - A cancelled lookup left its child processes running.

  The log is in `.codex-review/2026-11-07-tools-timeouts/` (gitignored).
- **`/ponytail-review`:** nothing to cut. No code outside tests reads the old error text.
- **`/deep-review`:** no findings (`security-reviews/fix-tools-timeouts/security-review.md`).
- **Two-angle review:** one LOW finding from each angle, both fixed.
  - **Security:** nothing capped how many lookups run at once, so parallel requests could each start 9 digs. Fixed with the reject-fast cap above.
  - **Language:** no test checked that `daemonFetch` passes its time limit to `AbortSignal.timeout`. Added one.
  - **Checked and clean on both angles:** argument injection, leaks of the token or other data, child-process clean-up, gather and cancellation behaviour, each web limit against the daemon's worst case, and Node 22's `TimeoutError` name.

## Tests

- **Daemon:** 3,959 pass, 4 skipped. `TestConcurrentLookup` in `test_dns_recon_service.py` covers:
  - the queries running at the same time;
  - the request order;
  - the `+time` / `+tries` arguments;
  - dedupe;
  - a failed dig, including one with no diagnostic;
  - an empty answer;
  - one type timing out while the others return, with its child reaped;
  - a cancelled lookup killing and reaping every child;
  - a fifth lookup refused without starting dig while 4 run, with the slots freed afterwards;
  - the route's 503.

  When I broke each behaviour on purpose, its test failed.
- **Web:** 4,066 tests pass (main with #216). svelte-check finds 0 errors, and `check:colors` is clean.
  - `daemon.test.ts`: a `TimeoutError` gives the "took too long" text, and the timeout argument reaches `AbortSignal.timeout`.
  - `tools-timeouts.test.ts`: each route passes its own limit, and the real values sit under 60 s.

## Deploy

`bash /home/nettap/NetTap/scripts/remote/deploy-tools-timeouts.sh` rebuilds the daemon and web. It checks:

- both images carry the change;
- both containers are healthy;
- a DNS lookup for example.com through the daemon API answers in under 10 s with records;
- the sign-in page answers.

## Lessons

- **A proxy's timeout must sit above the slowest answer the service behind it is allowed to give.** Otherwise "slow" reads as "down".
- **Independent lookups belong in parallel.** Seven sequential network calls multiply one slow DNS server by seven.
