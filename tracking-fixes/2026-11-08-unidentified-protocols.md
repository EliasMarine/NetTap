# Most connections showed as Unidentified, and QUIC never appeared (NET-219)

**Date:** 2026-11-08
**Branch:** `fix/unidentified-protocols` (PR #233)
**Linear:** NET-219
**Status:** Built, tested and reviewed. The G11 deploy (`deploy-protocol-identification.sh`) runs after the merge.

## What the owner saw

"Why are there SO MANY unidentified network protocols? … I don't even see QUIC as a protocol." Home's Network protocols card showed Unidentified as the biggest bar, 57% of connections on the G11.

## Root cause (measured on the G11, 24 h)

Of 434.6k unlabelled connections:

- **65% exchanged no data in at least one direction.** Most came from a BitTorrent client on 192.168.1.205 (the owner confirmed it), about 206k unanswered connections a day. Nothing can name a protocol that never sent a byte.
- **19% was local chatter.**
- **6% was QUIC (6 GB).** Malcolm's image ships with `ZEEK_DISABLE_SPICY_QUIC` set, so Zeek never ran its QUIC analyzer.
- **5% was ICMP**, which has no application layer.
- **The ICS analyzers** (bacnet, enip, profinet, iec104, hart_ip) gave 31 false labels a day on a home network.

Counting only real conversations, Unidentified is 15%; with QUIC on it should fall to about 6%.

## Fix

- **`docker/docker-compose.yml` (zeek-live):** `ZEEK_DISABLE_SPICY_QUIC: "false"` and `ZEEK_DISABLE_ICS_ALL: "true"`. Malcolm's `local.zeek` treats only a `true` value as disabled. QUIC connections get a `quic` label (`network.protocol` `["quic","ssl"]`) and their server name in ssl.log.
- **`GET /api/traffic/protocols` (`daemon/api/traffic.py`):**
  - Exact filter counts replace the `quic`, `ssl` (without QUIC) and `unknown` entries, so a QUIC connection counts once.
  - `services` keeps its meaning, because the Compliance page adds it up.
  - New `unidentified: {conversations, one_way, icmp}`. One way means both payload counters exist and one is 0.
  - An incomplete search is a 502, never zeros.
- **Home (`web/src/routes/+page.svelte`):** the Unidentified bar shows conversations only, sorted into its real place. A note gives the one-way and ICMP counts it leaves out.
- **Device scripts:**
  - `deploy-protocol-identification.sh`: records a rollback point, samples Zeek CPU before and after, waits 10 minutes, then runs `verify_protocols.py` (the API against direct OpenSearch counts).
  - `rollback-protocol-identification.sh`: restores the rollback point.

## Review fixes (pre-merge, 2026-11-09)

- **Rollback guard (security L1):** the rollback refused nothing, so weeks later it would have rebuilt the daemon and web from the old revision and undone every later fix. The deploy now records the revision it leaves (`~/.nettap-deploys/protocol-identification.deployed`). The rollback lists what it would undo and refuses once the checkout has moved on, unless `--force` is given.
- **Zeek restarts (security L2):** Malcolm restarts a crashed Zeek inside the container, so `RestartCount` stays 0. The deploy now compares zeek's PIDs (`docker top`) from 2 minutes after the recreate to the end.
- **Web (TypeScript review):**
  - a test pins sort-before-slice with nine services;
  - only the daemon's own `unknown` bucket is split;
  - the note says "unidentified" (the bar's word) and "ICMP exchanges" (Zeek logs one record per exchange);
  - the replaced lines are kept as OLD CODE.
- **Follow-up: NET-220.** zeek-live's privileges (`NET_ADMIN`, `NET_RAW` via file capabilities, no memory limit) predate this change.

## Tests

- **Daemon:** `test_traffic_api.py` (`TestProtocolsUnidentified`), `test_zeek_analyzers.py`, `test_verify_protocols.py`.
- **Web:** `home-services.test.ts` (8 tests) and the visual fixture.
- **Scripts:** `tests/scripts/test_protocol_identification.bats` (7 tests: the rollback point and the rollback guard).

## Lessons

- **Measure before relabelling.** Two thirds of "Unidentified" was traffic with nothing to identify; no analyzer would have fixed that, so the chart now says so.
- **A container's restart count doesn't show restarts its supervisor handles.** Check the processes inside.
- **A rollback script must know what it undoes.** Record what the deploy left, and refuse when the device has moved on.
