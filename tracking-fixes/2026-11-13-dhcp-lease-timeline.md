# DHCP lease timeline (NET-263)

**Branch:** `feature/dhcp-lease-timeline` · **Status:** PR #263 open, review fixes in, not yet deployed · **Plan:** PLAN.md section 2 (NET-261)

## What changed

- Daemon: `GET /api/dhcp/timeline?mac=&from=&to=` (`daemon/api/dhcp_timeline.py`), registered in `api/server.py` on the moment page's no-retry exact-terms client, in the shared drill-down slots and budget.
  - `mac`: colons, hyphens, dots or bare hex, any case → six lowercase colon-separated octets. Anything else is a 400 ("Enter a six-byte MAC address, such as aa:bb:cc:dd:ee:ff."). 8-byte chaddrs (a UniFi AP sends them on a VLAN) are out of scope.
  - Read 1: the device's Zeek dhcp records in the window, newest 200 (`truncated` when more).
  - Read 2: the final conn records of those records' `zeek.uid`s (no time filter: a connection can start before the window). Each one's port 67 side(s), without 0.0.0.0 and 255.255.255.255, are the transaction's `server_endpoints`. `endpoints_complete` is false when any of its uids has no conn record yet.
  - Per transaction: `messages` as counts (a multiset, keys sorted, no order), the addresses, `client_ip` (the address the client sent from), `zeek_server`, the endpoints and the outcome from the plan's table.
- Web:
  - `/tools/dhcp-timeline` (`?mac=`, the standard range pills, Custom from a link). It has a device picker (a datalist of registry devices, which takes a name, IP or MAC) and a sortable table. Each row has a plain-English line (`dhcp-summary.ts`) saying what was observed, never an order of events.
  - A server is named as the sender only when there is exactly one endpoint and every connection has a record. Otherwise the endpoints are listed. Every row (since the review) links "See the captured packets" to Packet analysis with `dhcp && dhcp.hw.mac_addr == <mac>`, ±5 s.
  - API client `lib/api/dhcp-timeline.ts`.
  - Tools index card.
  - A "DHCP history" link on the device page (only when the device has a MAC).
  - The catch-all proxy gives `/api/dhcp/` 30 s.
  - Visual fixture and route.

## PR #263 review fixes (one commit)

- **CI:** ruff 0.17.3 format and check on the three daemon files.
- **Log:** `from` and `to` are logged with `%r`. Python 3.11+ `fromisoformat` takes any character as the date-time separator, newline included.
- **Reading:**
  - The conn read asks for at most 10,000 hits. A uid left out past that counts as not recorded, so its transaction is incomplete. Tests cover more than 10 connections and the cap.
  - Every reply field is its type or None, so one odd record (a string lease time, an invalid address, a non-string uid) can't fail the page.
  - Server endpoints are sorted as addresses (192.168.1.5 before 192.168.1.10).
- **MAC input:** octets of one digit, as macOS `arp` prints them (`0:1b:63:84:45:e6`), are taken and zero-padded.
- **Wording (observed facts):**
  - The Tools card and page say "which server addresses appeared".
  - The column is "Server endpoints".
  - The chips are "No ACK or NAK seen", "No OFFER seen" and "No reply seen".
  - "Newest first" is gone, because the table re-sorts.
- **The packets link is on every row now**, a named sender too: it shows who really sent a reply, a spoofed NAK for example. Each link's accessible name carries the row's time.
- **The Assigned column shows the lease length** ("for 24 h"). `client_software` is left out of the web type, because nothing shows it; the daemon still returns it.
- **Errors:**
  - `getJson` throws `HttpError` with the status.
  - A 400 shows the daemon's own words ("Enter a six-byte MAC address…") with no retry.
  - A failure with no reason shows a fixed sentence instead of loading for ever.
  - `isNullable` is exported from `lib/api/drilldown.ts` and reused.
- **Picker:** the typed text resets only when the URL's MAC changes. Showing the same device again loads it again.
- **New page tests:** a superseded answer is dropped, a failed refresh keeps the rows with the warning, Try again asks again, a 400 has no retry, and a failure with no reason still says what to check.

## Why

To see a device's leases, renewals, NAKs and unanswered requests, with which server took part, from the 7+ days of Zeek dhcp.log already in OpenSearch.

## Files

- `daemon/api/dhcp_timeline.py` (new)
- `daemon/api/server.py`
- `daemon/tests/test_dhcp_timeline_api.py` (new)
- `daemon/tests/test_health_while_blocked.py`
- `web/src/lib/api/dhcp-timeline.ts` (new, + test)
- `web/src/routes/tools/dhcp-timeline/+page.svelte` (new), `dhcp-summary.ts` (new, + test), `dhcp-timeline-page.test.ts`
- `web/src/routes/tools/+page.svelte` (+ test)
- `web/src/routes/devices/[ip]/+page.svelte` (+ test)
- `web/src/routes/api/[...path]/+server.ts`, `web/src/routes/api/catchall-timeout.test.ts`
- `web/e2e/visual/fixtures/dhcp.ts` (new, + test), `fixtures/index.ts`, `routes.ts`

## Tests

- Daemon: 42 new tests. The fixtures are the G11's own dhcp/conn records: the U6-LR's DORA with the shared broadcast connection, its VLAN 40 renewal, and a NAK sent from 192.168.1.1:67 to broadcast with no server_addr. They also cover a relay, a connection with no record yet, the 200 cap, every outcome in the table, MAC notations and failures (503 slow, 502 partial or unreachable).
- Full suite: 4858 passed, 0 failed (baseline 4816).
- Web: the client, the wording helper (every outcome, mixed, DECLINE only, INFORM+ACK, missing fields, the packets window), the page (no device, loading, populated, two endpoints, empty, truncated, error, picker by name, picker with the registry down, range pill), the Tools index, the device link and a 15 s proxy answer.
  - Full vitest: 373 files, 4907 tests passed.
  - svelte-check: 0 errors.
  - check:colors: clean.
- Real data (read-only, via the module's own queries over SSH):
  - U6-LR over 7 days: 43 transactions (26 ack, 10 nak, 6 release, 1 discover_no_offer); every server-side set was one endpoint.
  - Mac (393 transactions): truncated, newest 200. The newest one had no conn record yet, so `endpoints_complete` was false, as the plan's evidence predicted.
  - ~1.1 s per request, including SSH.

## Lessons

- On the G11, NAKs carry no `destination.ip` (server_addr) and no `requested_ip`. The only server evidence is the conn record 192.168.1.1:67 → 255.255.255.255:68, and the only address is the client's own (source.ip). So the reply carries `client_ip` for the NAK and REQUEST sentences.
- dhcp and ja4d records carry `zeek.uid` too. Read 2 must filter on conn records, or a ja4d record would make a missing conn record look present.

## Next steps

- Deploy (the lead), then check the U6-LR on the G11: `/tools/dhcp-timeline?mac=78:45:58:ed:b2:e9`.
