# Capture-mode honesty: bridge mode, encrypted DNS, the DNS median, wizard labels (NET-225)

**Date:** 2026-11-09
**Branch:** `fix/net-225-capture-mode-honesty` (from `fix/release-audit-2026-11` at `e3391970`)
**Linear:** NET-225 (blocker B2, finding A10); P2 items B-n and B-k under NET-237
**Commits:** `ed7330fb` store, `d9af31ca` bridge wording and threat score, `7077ac5f` DNS, `75839924` wizard
**Audit notes:** DEV-1, DNS-1, DNS-3, ALR-3 (`Debugging/release-audit-2026-11/`)
**Status:** Built and tested. Not merged or deployed. Bridge mode can't be bench-tested (the owner has no bench), so bridge behaviour is verified by unit tests only.

## Problem

- **Inline bridge mode (A10).** NetTap sits between the modem and the router, after the router's address translation (NAT), so all of a home's IPv4 traffic carries the router's address. Even so:
  - Devices and Home promised that devices would appear.
  - DNS said a device "made no DNS queries".
  - The threat-score text said attempts from the internet add at most 0.5. In bridge mode they add their full weight.
- **Encrypted DNS (B-k, DNS-1).** No page said that DNS over HTTPS (DoH) and DNS over TLS (DoT) never reach Zeek's `dns.log`. "That's a good sign" and "None of your devices asked for this name" claimed facts from that absence.
- **DNS mean (B-k, DNS-3).** The KPI showed the mean, which a few 20 s retries skew: on the G11 over 24 h the mean was 19.6 ms and the median 6.3 ms. A window where nothing was answered read 0.0 ms.
- **Wizard (B-n).**
  - DHCP gateway was labelled "Recommended", though it has never run on hardware.
  - Inline bridge said "Sees all WAN traffic" without saying that devices can't be told apart.

## Root cause

- The pages never read the capture mode, except Devices for its By type tab.
- The global `captureMode` store guessed `'bridge'` before the reply arrived, on a failure and for an unknown mode. Any page warning about bridge mode would have warned mirror users.
- The threat-score text described only the attributed path. `_finding_points` scores alerts with no LAN-subnet party at full weight, once per signature, source and destination. That covers all IPv6, and nearly all bridge traffic.
- The daemon already computed an exact median (HDR percentiles), but the web type had no field for it.

## Fix

- **Store** (`lib/stores/captureMode.ts`):
  - `null` until the daemon answers. A failure or an unknown mode leaves it `null`.
  - `initCaptureMode()` asks again after a failure and shares one request between concurrent callers.
  - The DNS, Threats and Alerts loaders call it without awaiting, so a startup failure clears on the next refresh.
- **Shared wording:**
  - `BRIDGE_NO_DEVICES` (`lib/api/capture.ts`), qualified to IPv4. Device views are IPv4 only, so IPv6 doesn't fill the gap.
  - `ENCRYPTED_DNS_NOTE` (`lib/api/dns.ts`).
  - `THREAT_SCORE_BRIDGE` (`lib/api/alerts.ts`).
- **Devices:**
  - A note under the page head in bridge mode.
  - A bridge empty state on All devices.
  - By type gives the bridge reason instead of "lists every device NetTap sees".
- **Home:** in bridge mode, the Devices KPI sub and the Top devices empty state give the reason. Home reads `captureHealth.mode`, which it already reloads on every refresh.
- **Threat score:**
  - `THREAT_SCORE_HOW` now states the unattributed rule in every mode.
  - Threats shows `THREAT_SCORE_BRIDGE` as a note in bridge mode.
  - Alerts shows it under the score.
  - The scoring itself is unchanged, by decision. Behind NAT, a LAN device's outbound C2 beacon is unattributed too, so capping unattributed weight would hide real compromise. Telling inbound traffic from outbound would need the WAN address, which the daemon doesn't have.
- **DNS:**
  - A page note: only plain DNS shows. In bridge mode it adds the IPv4 router-address and router-cache sentence.
  - The KPI is now "Median resolution", with "Mean X ms" beside it, and "—" with "No answered lookups to time" when nothing was timed.
  - Honest empty states on DNS by device, NXDOMAIN, the domain page and the device page's DNS card.
- **Daemon** (`services/dns_analytics.py:get_stats`): `avg_resolution_ms` and `median_resolution_ms` are `None` when the aggregation is null, not 0.
- **Wizard:**
  - Mirror says "Tested on hardware".
  - DHCP gateway and inline bridge say "Not yet tested on hardware".
  - DHCP gateway gains "Devices with a fixed IP address bypass NetTap".
  - Inline bridge states the address-translation limit.

## Files

- `daemon/services/dns_analytics.py`, `daemon/tests/test_dns_analytics.py`
- `web/src/lib/stores/captureMode.ts` (+ test), `web/src/lib/api/{capture,dns,alerts}.ts`
- `web/src/routes/+page.svelte`, `devices/+page.svelte`, `devices/[ip]/+page.svelte`, `dns/+page.svelte`, `domain/[name]/+page.svelte`, `threats/+page.svelte`, `alerts/+page.svelte`, `setup/+page.svelte`
- Tests:
  - `home-cards.test.ts`
  - `devices/devices-by-type.test.ts`
  - `devices/devices-count.test.ts`: the selector named the notice by role, because bridge mode's note now comes first.
  - `devices/[ip]/device-detail.test.ts`
  - `dns/dns-honesty.test.ts` (new)
  - `domain/[name]/domain-page.test.ts`
  - `threats/threats-page.test.ts`
  - `alerts/alerts-page.test.ts`
  - `setup/setup-wizard.test.ts`
- Visual fixture `web/e2e/visual/fixtures/dns.ts`: the median added, and empty stats are null.

## Tests

- **Fail-before.** The 15 new web tests fail with the old pages and store restored. The `THREAT_SCORE_HOW` test fails with the old `alerts.ts`. The daemon's `test_no_answered_queries_gives_none` fails on the old code with `assert 0 is None`.
- **Suites:**
  - Daemon: 4,272 passed, 4 skipped. `ruff check` and `ruff format` (0.17.3) are clean.
  - Web: 4,345 passed. svelte-check: 0 errors. The colour gate is clean.
- **Gates:** Codex plan review gave APPROVED in round 3. Ponytail review found one should-fix: the Home sub lacked the IPv4 qualifier. It is fixed.

## Lessons

- A store that guesses a default turns every later mode-aware message into a lie for the other modes. Keep "unknown" as a state.
- Say "IPv4" when describing NAT. Routed IPv6 keeps its own addresses. NetTap misses it for a different reason: its device views are IPv4 only.
- Threat-score text must follow `_finding_points` exactly, including the LAN-subnet test. With double NAT the router's private WAN address can be a LAN subnet, and then the attempt cap applies.

## Follow-up (same day): IoT, device risk score, Go Live, DNS-2

- **IoT page (DEV-1).**
  - Discovery keys on `source.mac` with no LAN filter (`iot_monitor.py:315-320`). After the router's NAT, those MACs are the router's WAN port and the provider's modem.
  - In bridge mode a note now says that this traffic can't be tied to individual smart home devices, and that the router or the provider's equipment may appear as a device.
  - The wording is conditional, not absolute. A historical window can still hold real devices captured before a mode switch.
- **Device risk score.**
  - In bridge mode the card is titled "Risk score for this address". A line says that after the router's IPv4 address translation one address can carry several devices' traffic, so the score can't stand for one device's risk.
  - It makes no whole-network claim, because IPv6 and traffic that bypasses NetTap aren't in it. The weights are unchanged.
- **Go Live.** "All traffic between your modem and router is analysed" becomes what is actually analysed: connection records, DNS and TLS names, and intrusion-detection rules on anything unencrypted. It can't read encrypted content and doesn't see traffic that bypasses the capture point.
- **DNS-2 was an honesty defect, so it is fixed.**
  - The 500-lookup (TXT: 50) thresholds were fixed counts for any window. At 30 days, 17 lookups a day read as "high-frequency … potential beaconing" (medium).
  - The thresholds are now per day, scaled by the window length in days, and never below today's values. The window is measured with `storage/time_slots._epoch`, which reads a time with no zone as UTC.
  - The description now says "few source addresses" and that a router or resolver address can stand for several devices.
- **DNS-4 is left to B-f.** The name scans (`get_suspicious_dns` and `detect_dns_tunneling`, via `DNSAnalytics._all_domains`) call `storage/all_buckets.py:all_buckets` without `what=`, so `checked()` never runs. The other DNS aggregations call `self._client.search` directly.
- **Tests.**
  - Fail before the fix: 3 web tests (IoT, risk, Go Live) and 5 daemon tests (TestThresholdsScaleWithTheWindow). The under-a-day test passes on both, by design.
  - Suites: daemon 4,278 passed, 4 skipped; web 4,350 passed; svelte-check 0 errors; the colour gate is clean.
- **Codex.** One round, REVISE, with 4 points: no whole-network claim, a zoneless timestamp, "clients" really counting addresses, and conditional IoT wording. All four are applied.

## Next steps

- Out of scope, but reported:
  - DNS-4 partial scans (B-f).
  - Go Live runs the bridge flow for mirror mode too. This was an earlier decision, and a test pins it.
- A bridge-mode bench run when hardware exists.
