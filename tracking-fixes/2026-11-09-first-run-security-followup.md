# NET-229 follow-up: deliberate 5xx messages, first-run API calls, firewall (2026-11-09)

Branch `fix/net-229-followup`, rebased onto `fix/release-audit-2026-11` at `1ef861c5`. Status: done, not deployed.

## 1. The 5xx middleware hid deliberate messages

- **Problem:** the phase-1 middleware (`daemon/api/error_replies.py`) kept a global allowlist of plain-English 5xx strings and replaced every other 5xx `error` with a generic line. Messages written for the owner were cut too: the NET-224 notification test 502 naming each failed channel, restore failures, rule updates, the DHCP gateway, updates.
- **Root cause:** the middleware guessed from the text which messages were safe. It can't tell a curated sentence from exception text.
- **Fix:** replies written for the owner are marked where they are made. `public_json()` is `web.json_response` plus a marker, and the middleware leaves a marked reply alone. An unmarked 5xx JSON reply, the `f"...: {exc}"` kind, still gets the generic line and its scalar fields, and the original is logged. An unhandled exception is now a logged JSON 500. The allowlist is gone (kept in an OLD CODE block).
  - Marked: 22 literal 5xx replies, the curated helpers (`drilldown_runner.json_error`, `certificates._error`, `device_custom._error`, `packets._error`), and the computed replies above.
  - Leaks fixed at the source, since a marked reply is no longer filtered:
    - packets: a 5xx drops `detail` (raw TShark stderr).
    - device names: the OpenSearch 502 is plain text.
    - rule update: a failed run answers "The rule update failed. The daemon log has the details." The raw output, which can be Docker's own (socket path, container name), goes to the log. A start failure shows only the OS reason.
    - DHCP gateway enable: NetTap's own `RuntimeError` text is shown; any other error is logged and answered with a plain sentence.
    - The capture.env write and the retention warning show only the OS reason.
- **Item 5 (errors inside 200 replies):**
  - System health storage/SMART errors are now plain sentences.
  - The update history's Malcolm, rule-update and GeoIP errors no longer carry exception or command text.
  - DHCP teardown errors no longer carry stderr or container paths.
  - All of it is logged.
  - Capture restart was left alone: its tested messages name the container on purpose.

## 2. The first-run API calls answered the LAN until setup ended

- **Problem:** `/api/setup/*`, `/api/bridge/*` and the three pre-Account calls answered anyone while no admin existed. The setup code guarded only account creation.
- **Fix:**
  - **Welcome step:** the code is now asked for on the Welcome step (`?/verifyCode`, same per-address limit). A right code sets `nettap_setup`, an httpOnly cookie holding an HMAC of the code (not a JWT, so it is never a session).
  - **hooks.server.ts:** while no admin exists, a first-run `/api` path needs that cookie, otherwise 401 `Enter the setup code first.`. The pages stay open.
  - **Account step:** account creation takes the cookie or, for scripts and the test harnesses, the code field.
  - **Existing installs:** the load returns `setupVerified: true` once an admin exists, so they never see the prompt.

### Review additions (round 2)

- **Go Live:** `/go-live` needs the setup cookie too during first run (it redirects to `/setup`). Only `/setup` itself stays open, so the code can be typed. The UniFi pre-Account calls were already behind the cookie.
- **L4, the setup code's limit:** it shared the login's per-address bucket, and behind Docker's IPv6 proxy every client can arrive from one address. So one LAN host could lock the owner out of both, or the limit meant nothing. Chosen: the code has its own limit, apart from the login's. The right code is checked first and always works; past 50 wrong codes overall (any address), wrong ones get 429 and one warning line. The ~59 bits are the protection. A first version refused every code after 50 failures until a restart; Codex pointed out that any LAN client could then block setup indefinitely, so it was changed.
- **L5, unreachable daemon logging:** `web/src/lib/server/daemon.ts` logged a line per call while the daemon was down (Live and the shell poll every few seconds). It now logs once when it goes down and once when it answers again. A caller's own abort (the packet download deadline) doesn't count as the daemon going down.
- **Capped scans:** NET-237's capped scans and part replies raise `PartialResultsError`, which the DNS, IoT, LAN, MAC, traffic-category and alert routes answered as exception text, so the page got the generic line. They now answer a public "The <x> search was incomplete" 502 (`api.error_replies.incomplete`), with the detail logged. Other routes still answer a shard-failure part reply with the generic line.
- **Found, not fixed (NET-237 area):** `storage/all_buckets.py` `complete_terms()` drops the completeness flag, so a capped IoT anomaly scan (`iot_monitor.py` ~1451) can still answer 200 with part of the findings (Codex round 3).
- **Rebase:** the combined branch had added the GeoIP lookup-failed message to the allowlist; it is now marked with `public_json` instead. The DNS recon and live bandwidth busy 503s (plain constants) are marked too. A third guard fails a curated exception sent unmarked.

## 3. The firewall script cut nettap-web off from the daemon

- **Problem:** `setup-firewall.sh --enable` sets `default deny incoming` and denies 8880. nettap-web reaches the host-network daemon through `host.docker.internal`, which arrives from the compose network, so the dashboard lost the daemon.
- **Fix:** before the deny, allow 8880 from each subnet of `docker_default`, read with `docker network inspect`.
  - The rule uses the subnet, not the `br-<id>` interface, because `docker compose down` + `up` gives the network a new id but the same free pool.
  - If the network doesn't exist yet, nothing is opened and the script says to re-run it.

## 4. Malcolm's `api` service: left in place

On the G11 (read-only), only its own healthcheck connects to it, and NetTap code never calls it. But Malcolm's dashboards-helper points an OpenSearch notification channel at it, and the update flow stops, backs up and restarts it. Removing it would change the tested update and rollback path. It publishes no port. Recorded in SECURITY.md's accepted risks.

## Files

- **Daemon:**
  - `api/error_replies.py`
  - the API modules that now use `public_json` (alerts, bandwidth, bridge, certificates, device_custom, devices, devices_v2, dhcp_gateway, drilldown_runner, home_location, live_bandwidth, logstash, notifications_hub, offload, packets, server, setup, suricata_rules, traffic)
  - `services/dhcp_gateway.py`, `services/dhcp_gateway_host.py`, `services/suricata_rules.py`, `services/update_executor.py`
- **Web:**
  - `src/lib/server/auth.ts`, `src/lib/server/middleware.ts`
  - `src/hooks.server.ts`
  - `src/routes/setup/+page.server.ts`, `src/routes/setup/+page.svelte`
  - `e2e/setup-wizard.spec.ts`
- **Install:** `scripts/install/setup-firewall.sh`
- **Docs:** `SECURITY.md`, `README.md`

## Tests

- **Daemon:**
  - `tests/test_error_replies.py`, rewritten: middleware behaviour, the real app for storage, packets, rule update, notification test and system health, and two AST guards. One guard fails a literal 5xx sent unmarked. The other fails a marked reply that shows a caught exception, unless the exception class is curated.
  - New producer tests in `test_rules_update_status.py`, `test_dhcp_gateway.py` (enable, teardown) and `test_update_executor.py`.
- **Web:**
  - `setup-action.test.ts`: verifyCode, cookie-only account creation, a stale cookie, the load.
  - `hooks.server.test.ts` and `hooks.server.store.test.ts`: API without, with, and with a stale cookie; the cookie is not a session.
  - New `setup-code-step.test.ts` for the Welcome UI.
- **Scripts:** new `tests/scripts/test_setup_firewall.bats`.
- **Fail-before:** every new test failed on the old code, with the source diff saved to the scratchpad, the old files restored, and the diff re-applied.

## Lessons

- A filter that judges text can't tell curated from leaked. Mark intent where the reply is built, and guard it with a test that reads the source.
- A firewall rule keyed on a Docker bridge name breaks on the next `docker compose down`. Key it on the subnet.
