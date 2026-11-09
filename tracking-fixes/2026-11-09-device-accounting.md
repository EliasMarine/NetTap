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

Risk scoring still uses started-side bytes; device categories, ports and top destinations stay "where it connected to"; the monthly cap counts local traffic; inter-VLAN routing can show a connection twice on the uplink mirror; bridge mode (NET-225); a server that never starts 3 connections is still not a device.
