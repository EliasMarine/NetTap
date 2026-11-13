# Path MTU check on the Ping page, 2026-11-13

**Linear:** NET-267 (child of NET-261)
**Branch:** `feature/path-mtu-check`
**Status:** built and tested locally. The probe algorithm was run read-only inside the G11 daemon
container against real targets (see below). The branch itself is not deployed. No image change.
**Plan:** `PLAN.md` section 6 plus "Shared decisions" (Codex review, 4 rounds, APPROVED). There is one
deviation, `-M do` instead of `-M probe`; see below.

## Why

"Small pings work, big transfers stall" is a common VPN and tunnel problem, and NetTap had no
quick way to find the largest packet that reaches a host.

## Deviation from the plan: `-M do`, because this ping has no `-M probe`

The daemon's ping is iputils 20221126 (Debian bookworm). On the G11,
`ping -4 -M probe …` answers `ping: invalid -M argument: probe` and exits 2. Its source
(ping.c:480) accepts only `do`, `dont` and `want`. `-M do` is the only option that sets DF.

The difference: with `-M do`, the kernel refuses to send a probe above a limit it already holds for
the path, either an earlier router report (cached up to 10 minutes) or a route MTU. ping then prints
`local error: message too long, mtu=N` (`mtu: N` for IPv6). The check handles it like this:
- That probe is `local_error` with its N. N is shown as NetTap's own limit, never as a router
  report, and it never makes the upper limit known.
- For the binary search it counts as a failed size, and the next probe is exactly N.
- If N replies and no router report in this run explains it, the status is `local_limit`: "NetTap
  would not send larger packets: it still holds an N-byte limit for this path …, so the upper limit
  is unknown."
- In one run, a router report of N makes the kernel refuse sizes above N. The search goes straight
  to N, and if N replies the status is `icmp_bound` (consistent with the report).

Reported to the lead before building, with this recommendation. No answer came before the build.

## What changed

- **`daemon/services/host_resolve.py`**: byte-for-byte the same as on `feature/lan-throughput-test`
  (resolve with a killable `getent ahosts`, `route_to`, the `run` subprocess helper).
- **`daemon/services/path_mtu_service.py`** (new). `POST /api/tools/mtu {target}`:
  - Validation and limits:
    - `validate_target`; the family comes from the resolved address.
    - Two checks at a time, checked before resolution; beyond that, 503 "Two MTU checks are
      already running. Try again in a moment."
    - One 25 s deadline and at most 16 probed sizes.
  - Sizes:
    - IP packet sizes; the overhead is 28 bytes (IPv4) or 48 bytes (IPv6).
    - The floor is 576 or 1280.
    - The ceiling is the interface MTU, capped at 65535.
  - Probe: `ping -4|-6 -M do -c 1 -W 1 -s <payload> <ip>`. Each result is `reply`,
    `icmp_too_big` (with the router's MTU), `local_error` (with NetTap's own MTU, or none for
    another ping error) or `no_reply`. A no_reply counts only after 2 pings.
  - Algorithm, in plan order:
    - Probe a small size, then the floor, then the ceiling.
    - Binary search; after a router report or local limit of N, the next probe is exactly N. A
      reported N equal to a size that replied ends the search.
    - Re-probe the largest confirmed size.
    - A cap or deadline returns `stopped` with what is confirmed.
  - Statuses: `interface`, `icmp_bound`, `unanswered_above`, `local_limit`, `floor_unanswered`,
    `no_ping_reply`, `unreliable`, `stopped`, `ping_error`. Upper limit known only for `interface`
    and `icmp_bound`. A report contradicted by the probes (a reply above it, or its own size
    unanswered) is kept as `icmp_reported_mtu` but not trusted.
  - One INFO line per check, or WARNING on an error or a stop.
- **`daemon/api/tools.py`:** the route. 400 for bad input or a body that isn't a JSON object, 503
  with the fixed busy sentence (`tests/test_error_replies.py` forbids exception text in a public 5xx).
- **Web:**
  - Proxy `api/tools/mtu/+server.ts` with `TOOL_TIMEOUT_MS.mtu = 35_000`.
  - Client `pathMtu()` in `$api/tools`.
  - The wording helper `tools/ping/mtu-summary.ts`.
  - A third "MTU" tab on `/tools/ping`, with a "Check MTU" button, the result line, and a probe
    `DataTable` (probe, size, result). Ping and Traceroute are unchanged.

## Files

- `daemon/services/host_resolve.py`, `daemon/services/path_mtu_service.py`, `daemon/api/tools.py`
- `daemon/tests/test_host_resolve.py`, `daemon/tests/test_path_mtu_service.py`
- `web/src/lib/server/daemon.ts`, `web/src/lib/api/tools.ts` (+ test)
- `web/src/routes/api/tools/mtu/+server.ts` (+ `server.test.ts`),
  `web/src/routes/api/tools/tools-timeouts.test.ts`
- `web/src/routes/tools/ping/{+page.svelte, mtu-summary.ts}` (+ `mtu-summary.test.ts`,
  `ping-page.test.ts`)

## Real output used

- Captured in the G11 daemon container:
  - `ping -4 -M do` reply (1472 to 9.9.9.9), local error (1473: `mtu=1500`) and no reply
    (192.0.2.1).
  - `ping -6 -M do` reply and local error (`mtu: 65536`).
  - `ping: connect: Network is unreachable`.
  - `ip -j route get`, `getent ahosts`.
- **From the format, not captured:** the IPv4 "Frag needed and DF set (mtu = N)" and IPv6 "Packet
  too big: mtu=N" lines. No G11 path sent one. They follow the exact iputils 20221126 format
  strings (ping.c `pr_icmph`, ping6_common.c `print_icmp`, with the "From %s icmp_seq=%u " prefix).
- The algorithm, run read-only in the G11 daemon container (streamed in by stdin; nothing written
  or restarted):
  - 192.168.1.1, 9.9.9.9 and one.one.one.one: `interface`, 1500, four probes.
  - 192.0.2.1: `no_ping_reply` after 2 s.
  - 2606:4700:4700::1111: "NetTap has no route to …".

## Test results

- Daemon:
  - New tests: 22 for the service and route, plus 12 for the resolver.
  - Full suite: 0 failures. The first full run caught a public 503 built from `str(e)`, which the
    error-replies guard forbids; it now sends the fixed sentence.
- Web: full vitest 4873 tests passed; svelte-check 0 errors (2 old warnings); `check:colors`
  clean.

## Lessons

- Check that a tool option exists in the binary the container ships, not only in the current
  upstream man page. `-M probe` is missing from iputils 20221126.
- A public 5xx reply must carry a fixed sentence, not `str(exc)`. `tests/test_error_replies.py`
  checks this by AST.

## Next steps

- Lead: decide on the `-M do` deviation. Deploy and check 192.168.1.1 and 9.9.9.9 from the MTU tab.
- If `-M probe` matters later, a newer iputils (trixie) or a small raw-socket prober with
  IP_PMTUDISC_PROBE would remove the cached-limit case.
