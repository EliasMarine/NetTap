# LAN throughput test on the Tools page, 2026-11-13

**Linear:** NET-266 (child of NET-261)
**Branch:** `feature/lan-throughput-test`
**Status:** built and tested locally. Not yet on the G11. The daemon image gains `iperf3`, so the
daemon container has to be rebuilt before the test can run there.
**Plan:** `PLAN.md` section 5 plus "Shared decisions" (Codex review, 4 rounds, APPROVED).

## Why

NetTap had no way to measure how fast the network is between NetTap and another device on the LAN.
iperf3 is the standard tool for this. The peer runs `iperf3 -s`, and NetTap runs the client.

## What changed

- **Daemon image:** `iperf3` is added to the apt list in `docker/Dockerfile.daemon`, with
  `DEBIAN_FRONTEND=noninteractive` so its debconf question keeps the default and no iperf3 server
  daemon is set up.
- **`daemon/services/host_resolve.py`** (new; the path MTU check, NET-267, adds the identical file):
  - `resolve(name)`: an IP literal is returned as is. A name is resolved with `getent ahosts -- <name>`
    in a child process, with a 3 s limit; on time-out the child is killed and reaped. It never uses
    the default executor, which the drill-down workers share.
  - `route_to(ip)`: runs `ip -j route get <ip>`, then reads sysfs for the outgoing interface: source
    address, Wi-Fi or not, speed and MTU. An unknown speed or MTU is None, never 0 or -1. A `dev`
    that isn't an interface name is refused before it is used as a path.
  - `run(*argv)`: the argv subprocess runner. A child still running when it ends (time-out or
    cancel) is killed and reaped.
- **`daemon/services/throughput_service.py`** (new). `POST /api/tools/throughput
  {host, port?, duration?, direction}`:
  - Validation: the host goes through `NetworkDiagService.validate_target`; port is 1–65535
    (default 5201), duration 1–30 s (default 10), direction is `upload` or `download`.
  - One test at a time. The lock is checked before resolution, and a second request gets 409 "A
    throughput test is already running."
  - Only private, 100.64.0.0/10 and fc00::/7 addresses are tested. Link-local gets its own
    sentence; global, loopback, multicast and unspecified get the plan's sentence. For a name, the
    first local address among those it resolves to is used.
  - One deadline, duration + 20 s, covers resolution, route lookup, iperf3 and clean-up.
  - The command is `iperf3 -c <ip> -p <port> -t <s> --connect-timeout 3000 -J [-R]`. With
    `--connect-timeout`, a wrong address fails after 3 s rather than when the deadline runs out.
  - The rate comes from `end.sum_received` in both directions; upload retransmits come from
    `end.sum_sent` (see "Review fixes").
    "Connection refused" and "server is busy" are turned into plain sentences.
  - `capture` comes from `app["capture_manager"]` (the same source as `/api/capture/mode`).
    `has_ip` comes from `psutil.net_if_addrs()`, where IPv6 link-local doesn't count.
  - One INFO line per test, or WARNING when it failed. The host is logged with `%r`.
- **`daemon/api/tools.py`:** the route, a 400 for bad input or a body that isn't a JSON object, and a
  409 when a test is already running.
- **Web:**
  - Proxy `api/tools/throughput/+server.ts` with `TOOL_TIMEOUT_MS.throughput = 55_000`.
  - Client `throughput()` in `$api/tools`.
  - The wording helper `throughput-summary.ts`.
  - The page `/tools/throughput`: a peer form, a source-interface card (with the mirror-port note
    in mirror mode), upload and download cards, and an "Earlier runs" `DataTable` that lives only
    in page state.
  - A Tools index card.

## Review fixes (two-angle review of PR #266, 2026-11-13)

- **iperf3 is sandboxed (security, MEDIUM).** iperf3 3.12 (bookworm) has CVE-2026-71218 and
  CVE-2026-71217 open ("vulnerable, postponed" on the Debian tracker, fixed in trixie). Both can
  be triggered by the peer, and the client parses the peer's data. The child now runs as:
  - `setpriv --reuid=64000 --regid=64000 --clear-groups --no-new-privs --inh-caps=-all`, then
  - `sh -c 'ulimit -v 262144 && exec "$@"' sh iperf3 …`.

  Why this form:
  - uid 64000 is unused in the container and on the host. 65534 is shared with dnsmasq under
    `pid: host`.
  - `prlimit` isn't in the image, so sh's `ulimit -v` sets the 256 MB cap.
  - On the G11 (read-only), the same prefix running `id` showed uid 64000, all capabilities 0,
    NoNewPrivs 1 and `ulimit -v` 262144.
  - The container's `/tmp` (where iperf3 puts its buffer file) is a 1777 tmpfs, so that uid can
    write to it.
  - If iperf3 is missing, `exec` exits 127; that now reads "iperf3 is not installed in NetTap's
    daemon image."
- **Deviation from PLAN.md:** the rate is `end.sum_received` in both directions (the plan said
  `sum_sent` for upload). `sum_sent` counts what NetTap wrote into its socket, so a short test to a
  Wi-Fi peer reads high. Upload retransmits still come from `sum_sent`.
- **`host_resolve.py` (shared, byte-identical with #267):**
  - `check_name` refuses input made only of digits and dots that is not an IP address, with a 400.
    getent reads `192.168.001.010` as octal (192.168.1.8) and `1234` as 0.0.4.210.
  - `route_to` now takes the smallest of three MTUs: the link MTU, IPv6's own MTU for the link
    (`/proc/sys/net/ipv6/conf/<dev>/mtu`) and a route's own `mtu`. A cached router report, which
    carries `expires`, is not a ceiling.
- A missing binary: the reply says "NetTap could not start the test (No such file or directory)."
  The full exception is logged with `%r`.
- The 409 is a plain `web.json_response` (`public_json` only matters for 5xx).
- Page:
  - The inputs are disabled while a test runs, and both directions use the values the run
    started with.
  - An emptied port or duration sends the defaults (5201, 10).
  - Leaving the page mid-upload skips the download and the history row (`onDestroy`).
  - "wired" only with a known link speed, so a tunnel says neither wired nor Wi-Fi.
  - A missing retransmit count shows no suffix; the history column is "Upload retransmits".
  - The help line is tied to the inputs with `aria-describedby`; the card sub reads "A device on
    your own network or VPN (a private address) running iperf3 -s".
- `/tools/throughput` is in `e2e/visual/routes.ts`; `npm run test:visual -g "/tools/throughput"`
  gives 6 passed, 1 skipped.

## Files

- `docker/Dockerfile.daemon`
- `daemon/services/host_resolve.py`, `daemon/services/throughput_service.py`, `daemon/api/tools.py`
- `daemon/tests/test_host_resolve.py`, `daemon/tests/test_throughput_service.py`,
  `daemon/tests/fixtures/iperf3_{upload,download,refused,busy}.json`
- `web/src/lib/server/daemon.ts`, `web/src/lib/api/tools.ts` (+ test)
- `web/src/routes/api/tools/throughput/+server.ts` (+ `server.test.ts`),
  `web/src/routes/api/tools/tools-timeouts.test.ts`
- `web/src/routes/tools/throughput/{+page.svelte, throughput-summary.ts}` (+ tests),
  `web/src/routes/tools/+page.svelte`, `web/src/routes/tools/tools-index.test.ts`

## Real output used

- iperf3 3.22 on the dev Mac: `-J` upload, `-J -R` download, refused (closed port) and server busy.
  The hostname in `system_info` is redacted. The JSON shape is the same on Linux, and iperf3 3.12
  (Debian bookworm) has `--connect-timeout` (checked in its source).
- G11 daemon container: `getent ahosts one.one.one.one`, `ip -j route get 9.9.9.9 / 192.168.1.1`,
  `RTNETLINK answers: Network is unreachable`, and the host sysfs (`/host/sys/class/net/eno1`:
  speed 1000, mtu 1500, no `wireless`).
- `psutil.net_if_addrs()` on the G11: enp4s0 has only AF_PACKET (so `has_ip` is false); eno1 has
  192.168.1.199. `/api/capture/mode` returns `mirror` / `enp4s0`.

## Test results

- Daemon: new tests 28 passed (now 34 for the service and route, 16 for the resolver after the
  review fixes). Full suite after the review fixes: 4851 passed, 0 failures.
  `ruff format --check` and `ruff check` (0.17.3) pass on the whole `daemon/`.
- Web: full vitest 372 files / 4878 tests passed after the review fixes; svelte-check 0 errors (2 old warnings);
  `check:colors` clean.

## Lessons

- A JSON body can be a list. The route checks it is an object before calling `.get`.
- `<input type="number" bind:value>` gives `null` when the field is emptied, so the page's text
  must not print the bound value as it is.

## Next steps

- Lead: rebuild the daemon image on the G11 and run against the dev Mac (`iperf3 -s`), or check the
  refused path if no server is running.
