# NET-209: threat and risk scores count only real threats; internet addresses are never devices

**Date:** 2026-11-08 · **Branch:** `fix/threat-score-accuracy` · **Linear:** NET-209 · **Status:** done. PR #223 → `89d09980`, PR #225 → `4ae69e9b`, both deployed on the G11 2026-11-08

## What was wrong

- **An internet scanner showed as a LAN device.** 91.92.40.12, on Spamhaus DROP, probed the port-forwarded
  web server 192.168.1.24 on ports 80, 443 and 3000. The Threats page made a kill chain of it with a
  "Investigate device" button, and its device page read "Windows 10/11, Ubiquiti, risk 58 High". The MAC
  was the UDM Pro's: every routed frame on the uplink mirror carries it. `/api/devices/{ip}` and
  `/api/risk/scores/{ip}` never checked that the address was on the LAN.
- **The threat score counted attempts and noise as threats.** Every (signature, source, destination)
  group added points, so each internet scanner address added points again, and a blocked exploit
  attempt weighed as much as a compromise. Blocklist rules (ET DROP, DShield, CINS, ...) fire on replies
  to connections a device opened too, and they were all counted.
- **Kill chains ignored direction and time.** Any address with alerts in two stages, in any order, over
  the whole window, was a chain.
- **The device risk score used signals with no published basis:** share of internet connections, a
  port list, and the upload/download ratio (11.7 KB "77% upload" scored 15/15 "data exfiltration").
  Its alert factor counted ET INFO activity such as Spotify.
- **Partial reads looked like fewer threats.** A timed-out or partly failed smart-alert page, or the
  page cap, returned what it had.

## What changed

The research and every rule, with citations: `Debugging/THREAT-SCORING.md`.

- **LAN guard.** `GET /api/devices/{ip}` and `GET /api/risk/scores/{ip}` answer 404 "<ip> is not on your
  network" before any search for an address outside the LAN rule. The device page sends a non-LAN address
  to `/address/<ip>`. The kill-chain button links through `$ipHref`.
- **Who acted, per alert** (`daemon/services/alert_findings.py`). Each alert instant is joined to its
  Zeek connection by Community ID and time, and charged to one device as its own traffic or as an attempt
  against it.
- **Severity from ET's own metadata** (`signature_severity`). ET INFO, HUNTING, TOR, P2P, GAMES and CHAT
  are activity. The internal-port boost is gone.
- **Reputation hits** count only when the device started the connection, at medium at most.
- **Threat score:** each (signature, device) once at its highest weight. An attempt adds at most 0.5.
  "Events" are the alerts that score; the rest are "not counted". Baseline snapshots are versioned
  (`counted-v2`), so the old count is never compared with the new one.
- **Kill chains:** per device, real alert times, stages in order, steps of at most 24 h, and at least one
  step from the device's own traffic.
- **Device risk:** alerts 50, connection anomaly 25, upload spike 25, each against the device's own last
  week. The volume factors need a high or critical own alert.
- **Checked reads:** every smart-alert page and history page must be complete, or the request fails
  (500 for the alert APIs, 502 for the risk APIs).
- **Security-review fixes (`fed7f05c`).** F1: an alert with no Zeek record after 10 minutes is a
  connection held open and counts as the device's own traffic, so a C2 session can't hide as an attempt.
  F2: a conn record whose direction Zeek guessed (`^` in the history, or TCP with no SYN first) is
  skipped. F3: alert times are read per minute, so a flood on one connection can't exhaust the page cap.
  F4: a blocklist hit with no LAN party stays listed at medium.

## Follow-up: matching alerts to their connection (branch `fix/alert-conn-matching`)

**Found on the G11 after the PR #223 deploy.** Over 7 days the port-forwarded server .24 still had 49.5
threat points and a kill chain, almost all from internet scanners counted as its own traffic. 30 counted
findings had no matching record. Three causes, traced alert by alert:

- **Suricata's flow-timeout alerts.** Suricata stamps an alert raised when a flow times out with the
  timeout time, 600 s after the last packet on the G11 (`flow-timeouts: tcp: established: 600`). A
  Next.js-bypass probe ran 02:46:06–02:47:31; its last alert is stamped 02:57:33. The match allowed 10 s.
- **Zeek fragments.** Late FINs after a close are logged as one-packet records (`^f`) that named the
  server as opener and "disagreed" with the real record; a disagreement fell through to "no record".
- **F2 skipped scanner probes.** A lone data packet (`D`) or a data-then-handshake probe (`DShR`) does not
  start with `S`, so it was skipped, and F1 then counted the alert as the server's own.

**Fix** (plan approved by Codex after 5 rounds; `.codex-review/2026-11-08-120542-alert-conn-matching/`):
Zeek's history letters are re-oriented after `^` flips and only a pure SYN names a TCP opener. Records
without one are a live session (opener unknown, counted like a held-open connection) or debris (decides
nothing). An alert matches the record its minute is in, else the latest non-debris record that ended up
to 11 minutes before. Records naming different openers make the opener unknown. All alerts of one
Suricata flow (`suricata.flow_id`) share the decision of any record they fall in.

Security review of the follow-up (security-engineer agent), both fixed with tests:
- **Medium:** a UDP C2 that speaks first after a 61–119 s pause made Zeek start a record naming it as the
  first sender, turning the device's C2 flow into attempts. A UDP/ICMP record starting within 11 minutes of
  the previous one on the same tuple now keeps its opener (the router's NAT mapping links them).
- **Low:** a held-open session resuming with zero-byte keepalives (`Aa`) was debris, so its blocklist hits
  were dropped. A mid-stream minute now takes the opener from the session's handshake record, however old;
  a scanner that handshakes, waits 301 s and then sends payload stays an attempt the same way.

**Simulated on the G11's live data before deploying** (read-only):

| | Deployed (#223) | With the fix |
|---|---|---|
| 24 h score | 50 high | 44 medium |
| 24 h, .24 points | 8 | 2 |
| 7 d, .24 points | 49.5 | 18 (mostly distinct exploit attempts at 0.5 each) |
| 7 d kill chains | .24 (stages 1, 2) | none |
| Counted findings with no record or unknown opener, 7 d | 30 | 9 (packets Zeek never logged) |

## Files

Daemon:
- `services/alert_findings.py` (new)
- `services/alert_intelligence.py`
- `services/risk_scoring.py`
- `services/investigation.py`
- `api/risk.py`
- `api/devices.py`
- `api/alerts.py`
- `api/threats.py`
- `api/drilldown_runner.py` (`lan_cidrs`)

Web:
- `routes/devices/[ip]/+page.svelte`
- `routes/threats/+page.svelte`
- `routes/+page.svelte`
- `lib/api/alerts.ts`

Tests:
- `tests/test_alert_findings.py` (new)
- `tests/test_smart_alert_paging.py`
- `tests/test_smart_alert_totals.py`
- `tests/test_alert_intelligence.py`
- `tests/test_risk_scoring.py`
- `tests/test_risk_api.py`
- `tests/test_devices_api.py`
- `tests/test_et_activity.py`
- `tests/test_beacon_snapshots.py`
- `tests/test_request_loop_free.py`
- the web route tests

Deploy:
- `scripts/remote/deploy-threat-accuracy.sh`
- `scripts/remote/verify_threat_accuracy.py`

## Test results

Dev (macOS), on the merged head `fed7f05c`:
- Daemon pytest: 4067 passed, 4 skipped. `ruff check` and `ruff format --check` (0.17.3) clean.
- Web: Vitest 4131 passed; svelte-check 0 errors; `check:colors` clean; visual 286 passed, 49 skipped.
- ShellCheck clean on `deploy-threat-accuracy.sh`.
- CI on PR #223: all 18 checks passed, including Integration Tests.

Reviews: `/codex-review` approved the plan; `/deep-review` no findings; `/ponytail-review` findings cut
or fixed; two-angle review (security + Python), all findings fixed (F1–F4 above).

G11 (`deploy-threat-accuracy.sh`, every check passed both times):

| | Before | After #223 | After #225 |
|---|---|---|---|
| 24 h threat score | 100 critical | 50 high | 44 medium |
| 7 d threat score | 100 critical | 100 high | 100 high (points ~140, capped) |
| 7 d counted alerts | 2,772 | 471 | 453 |
| 7 d kill chains | 5 internet attackers | .24 | none |
| 91.92.40.12 device and risk | 200, risk 58 high | 404 | 404 |
| .24 device risk (24 h) | 8 | 15 | 0 |

The history cross-check matched independent searches for 192.168.1.44 and 10.10.0.27 (8 day ranges, list and
single). PR #225: 81 tests in `test_alert_findings.py`, daemon 4093 passed, 4 skipped; CI 18/18.

## Lessons

- **On a mirror of the router's uplink, the router's MAC is on every routed frame.** A MAC or vendor
  never proves an address is a LAN device; the LAN subnets do.
- **Suricata's `severity` is a classtype priority, not a verdict.** ET's `signature_severity` metadata is
  the vendor's own rating.
- **Reputation rules without `flow:` keywords fire both ways.** "Inbound" in the name does not mean the
  internet started the connection.
- **Suricata stamps a flow-timeout alert with the timeout time,** up to 600 s after the last packet. Any
  join from alerts to Zeek records by time needs that window.
- **Zeek's history letters say who opened a connection; its originator does not always.** Only a pure SYN
  proves it. A late FIN after a close is logged as its own record, flipped.
- **Simulate a scoring change on the device's live data before deploying it.** A read-only script that
  swaps in the new module found these flaws in minutes, where the unit tests had passed.
- **Score findings, not alert groups.** One signature on one host is one finding, however many addresses
  it touches.
