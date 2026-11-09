# Device accounting: both sides of a connection, IPv6 by MAC, upload from the LAN side (NET-226)

**Date:** 2026-11-09
**Branch:** `fix/net-226-device-accounting` (from `fix/release-audit-2026-11`)
**Linear:** NET-226 (blocker B3: findings A11, A12), NET-237 (P2 items B-d, B-h)
**Status:** Built and tested. Not merged, not deployed.

## Problem

- **A11.** A device's connections and bytes were only the connections it started. On the G11, device-A (a web server behind a port forward) read 720 connections and 168,900 B for 12:00–13:00 UTC on 2026-11-09. It took part in 5,075 connections and 2,193,024 B: 86% of its connections and 92% of its bytes were missing.
- **A12.** Device views were IPv4 only. 18,171 IPv6 connections a day (link-local and ULA) belonged to no device.
- **B-d.** Upload and download followed the originator, so an inbound connection's download read as upload, and LAN-to-LAN traffic counted as both (8.9% of the G11's bytes).
- **B-h.** Device type and OS were substring guesses shown as fact (a Tizen TV read "Linux", an Xbox "Windows 10/11"; the registry dropped "media"). IoT trust and isolation grades claimed health from inputs that were never observed.

## Root cause

Every device query filtered `source.ip` to the device and summed `source.bytes` as "sent". Nothing looked at `destination.ip`, and the LAN rule is IPv4 only. Network totals used `source.bytes`/`destination.bytes` as up/down whoever started the connection.

## Fix

| Part | What | Files |
|---|---|---|
| Both sides | connections = started + answered. Upload = `source.bytes` where it started + `destination.bytes` where it answered; download the converse. A LAN-to-LAN connection counts for both devices. Membership, first/last seen and Online stay on started connections (≥3), so the count, registry and risk still agree with the list | `daemon/services/device_accounting.py` (new), `api/devices.py`, `api/bandwidth.py` |
| IPv6 by MAC | A device's IPv6 records are the ones with its MAC (started: `source.mac`, answered: `destination.mac`). One owner per MAC: the busiest listed IP, ties to the lowest. A MAC that is a next hop for internet-bound IPv4 (a router) keeps only its link-local IPv6, because on a mirror its MAC is on every frame it forwards. When no internet-bound IPv4 is seen, only link-local folds. Each row reports `ipv6_left_out` and `ipv6_left_out_reason` ("router" or "no_gateway") | same, plus `services/device_registry.py` (MAC page) |
| Network direction | `upload_bytes`, `download_bytes` and `local_bytes` on the traffic summary, the bandwidth series, daily and monthly. Inbound (IPv4 from outside the LAN rule, global IPv6 from a gateway MAC) swaps; LAN to LAN, multicast, broadcast and IPv6 local ranges are local; the rest keeps the originator's direction. `orig_bytes`/`resp_bytes`/`total_bytes` are unchanged | `services/device_accounting.py`, `api/traffic.py`, `services/bandwidth_tracker.py` |
| Guesses | `category_basis` ("name", "os", "vendor") and `os_basis` ("web traffic"); the pages say "Likely phone, from its name". OS patterns check specific platforms first. The registry stores "media" | `api/devices.py`, `services/device_fingerprint.py`, `services/device_registry.py`, web pages |
| IoT | Whole-word vendor matching. Trackers, third parties and protocol checks are "not measured" (None) when no DNS, ASN or port data was seen; isolation with no IoT devices has no grade; the summary says "in the checks NetTap could measure" | `services/iot_monitor.py`, `web/src/routes/iot/+page.svelte`, `lib/api/iot.ts` |
| Web | Home, Bandwidth, Devices, device and MAC pages read upload/download/local, show the IPv6 notes and the guesses | `web/src/lib/utils/{up-down,ipv6-coverage,device-guess}.ts`, pages, API clients, visual fixtures |

Replaced code is kept as `OLD CODE` blocks. `BandwidthTracker.get_per_device_usage` is now unused (OLD CODE); `/api/bandwidth/devices` uses the device list's accounting.

## Tests

- `daemon/tests/test_device_accounting.py` (12 tests, the evaluator fake): both sides on the list, device page and bandwidth devices; shared MAC; a second router; no gateway known; a partial answered reply and a failed gateway check answer 502; network direction on the summary, daily and series; guess basis and OS order. All 12 fail on the old code (old sources restored from HEAD, run, re-applied; log in the scratchpad).
- Also failing on the old code: the MAC page's both-sides test, the registry "media" test, the detail's upload/download test and the list's upload/download tests.
- `tests/fake_drill_opensearch.py`: terms buckets now carry their sub-aggregations, and `msearch` exists.
- Suites: daemon 4,289 passed, 4 skipped (baseline 4,271; 5 tests of the removed method kept as OLD CODE). Web vitest 4,354 passed, svelte-check 0 errors, check:colors clean. Visual baselines for Home, Bandwidth, Devices and IoT will change.

## G11 verification (read-only)

- The branch's own queries over the reconciliation hour, run against the G11's OpenSearch, give device-A exactly the independent both-sides sums: 5,075 connections, upload 998,541 B, download 1,194,483 B. (The hour gained 16 records after the first reconciliation: Zeek logs a connection when it closes, under its start time.)
- 24 h direction split: upload 18.2%, download 72.7%, local 9.1% (originator split was 25.1% / 74.9%).
- Device list, OpenSearch time summed, uncached: 24 h 0.38–0.42 s before, 0.52–0.54 s after; 7 d 1.84–1.92 s before, 2.09–2.24 s after; 30 d 2.19–2.24 s before, 2.30–2.46 s after. Dropping the Painless sum paid for most of the new searches. The gateway check is one `_msearch` of existence checks (0.07–0.38 s; a terms list of next hops took 0.4–1.6 s).
- Home bandwidth series: 24 h 0.13 s → 0.36 s, 7 d and 30 d about 0.5 s → 1.4–1.9 s. Each per-slot filter costs 0.2–0.4 s at 168 slots; a `filters` agg or a `network.direction` term was no cheaper.

## Deploy

Rebuild and recreate `nettap-storage-daemon` and `nettap-web`. No migration; the registry starts storing "media" on its next refresh.

## Lessons

- Reconcile against independent sums of both sides, not against another view of the same query.
- A past hour is not closed: long connections arrive later under their start time.
- The test fake's terms buckets had no sub-aggregations, so a sum under a terms bucket read 0 in every fake test until now.

## Out of scope (left as is)

Risk scoring still uses started-side bytes; device categories, ports and top destinations stay "where it connected to"; the monthly cap counts local traffic; inter-VLAN routing can show a connection twice on the uplink mirror; bridge mode (NET-225); a server that never starts 3 connections is still not a device. **All but bridge mode are handled in the follow-up below.**

---

# Follow-up: answer-only devices, the cap without local traffic, started-side labels, inter-VLAN

**Branch:** `fix/net-226-followup` (from `fix/release-audit-2026-11` at `f34530dc`)
**Status:** Built and tested. Not merged, not deployed.

## Problem

1. A LAN server that only answers connections (a NAS, a media server) was never listed: membership needed 3 connections it started. The count, the registry and risk use the same membership.
2. The monthly cap, its projection and the daily rate counted traffic between your own devices, which never crosses the ISP link.
3. The risk factor "N connections" read as all connections; it counts only the ones the device opened.
4. Categories, top services, top destinations and top ports read only the connections the device started, without saying so. The categories still summed bytes with a Painless script per record.
5. On a router-on-a-stick capture, a flow routed between two VLANs is seen twice.

## Root cause

1. `_lan_device_buckets` was one composite over `source.ip`.
2. `get_projected_monthly` and `/api/bandwidth/cap` used `total_bytes`, which includes `local_bytes`.
3–4. Labels written before NET-226 counted both sides.
5. Zeek's connection key has no VLAN, so it merges both legs into one record (same uid): one connection, twice the bytes and packets. On the G11 that was 0.065% of 7 days' bytes.

## Fix

- `_lan_device_buckets` (`daemon/api/devices.py`) runs a second composite over `destination.ip`: the LAN rule and the excluded IPs on the answering side, and only records with `destination.packets > 0`, so a scan of empty addresses makes no device and can't fill the 20,000-IP cap. A device is an IP with 3 started **or** 3 answered connections. Its time bounds (first seen, last seen, the registry's last record, the count's `active_since`) cover both. A device that started none is `answer_only`: its other aggregations (protocols, MAC) are read from its side of the records it answered, 1,000 IPs per search, and a missing IP is a 502. Sums are never read for it.
- Only a row with 3 started connections can own a MAC's IPv6, as the device page's `_ipv6_mac_of` already decided.
- The device page's first and last seen use the list's rule (its IPv4 records, started or answered with a response); protocols and MAC fall back to the answered records.
- The registry reads an answer-only device's MAC and vendor from `destination.*`.
- Risk: an answer-only device has 0 opened connections and is left out of the network baseline; the history's answered side counts answered records only. The factor reads "N connections it opened". Weights unchanged; alerts already count where the device is either party (own traffic only, NET-209).
- Cap: `internet_bytes()` = upload + download. `/api/bandwidth/cap` and the projection use it; `/monthly` passes its usage to the projection instead of reading the month twice. The Bandwidth page's card is "Internet this month".
- Categories: plain sums of both byte fields. The device page's categories, services, destinations and ports cards, and the MAC page's destinations, say "connections it started".
- Inter-VLAN: not detectable from one record cheaply; the device page says it under the chart.

## Limits

- A VLAN whose hosts only answer is found only when `LAN_SUBNETS` lists it: autodetection finds the subnets that start internet connections.
- A device that answers only over IPv6 is not listed.
- Traffic between your devices over global IPv6 still counts as internet in the cap: no LAN IPv6 prefix is configured to prove it local.
- Inter-VLAN routed flows count their bytes twice.

## Tests

`daemon/tests/test_answer_only_devices.py` (fake): NAS listed with both sides in the list, count, bandwidth devices, page, registry and risk; online from answers, not probes; a scan bigger than the cap; 2 started + 3 answered + IPv6; dual-stack last seen; missing and configured subnet; partial responder read and missing answerer are 502; cap and projection leave out local. `test_risk_scoring.py` (text), `test_device_detail_v2.py` (no Painless). Web: bandwidth card and meter, started-side labels and empty states, the inter-VLAN line. All failed on the old code except the missing-subnet control.

## G11 (read-only)

No answer-only device on the G11 today (24 h, 7 d, 30 d). The answering composite adds 46–184 ms of OpenSearch time to the count and 130–210 ms to a 1.8–2.5 s list. Running both composites at once in one `_msearch` was no faster (the N100 is CPU-bound). Home's series are unchanged.

## Lessons

- A responder has to have answered: without `destination.packets > 0` a LAN scan would make hundreds of devices.
- Check every detail field against the list's rule, not only the totals: the page's last seen had included IPv6 since NET-226.
