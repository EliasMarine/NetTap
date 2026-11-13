# IoT checks score only measured data; the unused classify route is gone, 2026-11-12

**Linear:** NET-171 (Bug), NET-174 (Improvement)
**Branch / PR:** `fix/iot-measured-only-checks`, PR #253
**Status:** built and tested; not yet deployed. Deploy with `bash scripts/remote/deploy-iot-measured-only.sh`.
**Plan:** `.codex-review/2026-11-12-173457-iot-measured-only/PLAN.md` (gitignored). Codex approved it in round 2.

## Why

NET-158 had already stopped the fixed fallbacks from scoring: the behaviour checks, telemetry and firmware were all sent as "unavailable" (None), and the scorer left them out of the sum. Two things were still wrong:

- Telemetry and firmware stayed in the model, though nothing in NetTap can measure them. The device drawer said "from 5 of 11 checks (55 of 100 points)", as if six checks and 45 points were waiting for data. Any caller that passed `telemetry_bytes=0` or `firmware_age_signal="current"` still earned 10 or 5 points.
- The page drew an unmeasured pillar (Behaviour, every time) as "—" beside an empty bar, which reads as a score of 0.

Separately, `POST /api/iot/devices/{mac}/classify` had no caller. The device it added was dropped on the next range request, because discovery rebuilds the IoT set each time (NET-158, D2).

## G11 before the change (read-only, main 32e90fd, 2026-11-12)

- `/api/iot/fleet-summary`, last 24 h: 7 devices, 5 scored, fleet score 89. Every device had `behavior_score: null`, `checks_total: 11`, and coverage of 55 or less. No fixed fallback reached any score.
- `GET /api/iot/devices/AA:BB:CC:DD:EE:FF/classify` answered 405 (the route existed for POST). An unknown sibling path answered 404.

## What changed

**NET-171: telemetry and firmware leave the model.**
- `daemon/services/iot_trust_scorer.py`: their weights, scoring code and breakdown keys are commented out as OLD CODE. There are now nine checks worth 85 points (privacy 20, security 35, behaviour 30). If a caller passes `telemetry_bytes` or `firmware_age_signal`, it is ignored.
- `MIN_COVERAGE` stays at 50 points. Today's five measurable checks make 55 points, so a device still needs all five, and no device on the G11 gains or loses a score. The values of every score, pillar and coverage figure are unchanged; only `checks_total` (11 → 9) and the breakdown keys change.
- `daemon/services/iot_monitor.py` `_build_device_stats()`: stops sending the two keys.
- The behaviour checks stay unavailable until baselines exist (NET-170). Their old formulas stay commented out; the docstring says why each was wrong.

**NET-171: the page says "Not measured".**
- `web/src/routes/iot/+page.svelte`: a null pillar shows a dim label and no bar.
  - Device drawer: "Not measured" (a device pillar is null only when none of its checks was measured).
  - Fleet card: "Not enough measured" when an unscored device has a value for that pillar (the fleet averages scored devices only); otherwise "Not measured".
- The drawer's "Measured" row reads "from N of 9 checks". It no longer gives "of 100 points", since the scale isn't 100 any more and the page shouldn't hard-code 85.

**NET-174: the classify route is gone.**
- `daemon/api/iot.py`: the handler and route registration are commented out as OLD CODE. The log line says 10 endpoints.
- `daemon/services/iot_monitor.py`: `classify_as_iot` is commented out; the handler was its only caller.
- `web/src/lib/api/iot.ts`: `classifyDevice()` is commented out.

## Files

- `daemon/services/iot_trust_scorer.py`, `daemon/services/iot_monitor.py`, `daemon/api/iot.py`
- `web/src/routes/iot/+page.svelte`, `web/src/lib/api/iot.ts`, `web/e2e/visual/fixtures/iot.ts` (nine checks, behaviour null, trust score weighted like the daemon's)
- Tests: `daemon/tests/test_iot_trust_scorer.py`, `test_iot_api.py`, `test_iot_monitor.py`, `test_iot_unmeasured.py`; `web/src/routes/iot/iot-page.test.ts`, `web/src/routes/iot/iot.test.ts`, `web/src/lib/api/iot.test.ts`, `web/src/tests/server-proxy.test.ts`
- `scripts/remote/deploy-iot-measured-only.sh` (new)
- `Debugging/DEPLOYMENT-ISSUES.md` (Key Files row, lesson 181, quick-reference rows)

## Tests

Each new test fails on the old code.

- **Daemon:**
  - A stats dict carrying `telemetry_bytes=0` and firmware "current" scores the same as one without them. The old scorer gave it a score of 100 from 55 points.
  - Nine checks give 85 points, and a perfect device scores 100.
  - `POST` and `GET` on `/api/iot/devices/{mac}/classify` both answer 404, and the monitor is never called.
- **Web:**
  - "Not measured" with no bar for a null pillar, and the bar kept for measured ones.
  - "Not enough measured" vs "Not measured" on the fleet card.
  - The drawer's Behaviour row reads "Not measured".
  - The drawer says "from 5 of 9 checks".

**Results:**

| Suite | Before | After |
|---|---|---|
| Daemon pytest | 4661 passed, 2 failed (`test_cert_monitor.py`, date drift, fixed on main in #249), 4 skipped | 4659 passed, the same 2 failed, 4 skipped (5 classify tests retired, 3 added) |
| Web Vitest | 354 files, 4548 tests | 354 files, 4548 tests (2 classify tests retired, 2 added) |
| `svelte-check` | 0 errors, 2 warnings | 0 errors, 2 warnings |
| `check:colors` | clean | clean |
| `test:visual` | not run | 295 passed, 50 skipped |
| ruff check / format | clean | clean |
| `shellcheck` (deploy script) | — | clean |

## Device checks (`deploy-iot-measured-only.sh`)

1. On `/api/iot/fleet-summary`:
   - every device has `checks_total == 9`;
   - no device and not the fleet has a behaviour score;
   - coverage is between 0 and 85;
   - no device has a score below 50 points;
   - a device with nothing measured has no score and no pillar.
2. `/api/iot/privacy-report` and `/api/iot/manufacturer-profiles` answer.
3. `POST` and `GET` on the classify path answer 404 (405 would mean the route still exists).

The expressions were dry-run against today's G11 reply: the 9-checks check fails as `[11]` before the deploy and passes on a reply with `checks_total` 9.

## Lessons

- A check that no data source can feed belongs out of the score. Leaving it in as "unavailable" forever still distorts the totals the page shows, and still pays any caller that passes a value. (DEPLOYMENT-ISSUES lesson 181.)
- When you remove a route, also look at tests that use its path as an example. `server-proxy.test.ts` used the classify path to test POST forwarding. It now uses `/api/notifications/channels/{id}/test`, which no route of its own serves, so it really goes through the catch-all (a first choice, `/api/investigations/{id}/notes`, has its own `+server.ts`).
- Test data and the visual fixture must match what the daemon can return. The fixture showed behaviour scores (for example 96) after the daemon stopped measuring behaviour, so the README media would have shown a bar no real device can have. PR #253's review caught it.

## Next steps

- NET-170 (auto-baselines). Then rewrite the four behaviour checks against real baselines, and decide whether `MIN_COVERAGE` should change once behaviour adds 30 points.
- The visual fixture now matches a nine-check reply (behaviour null, trust score weighted 20/35 like the daemon). The README media were not regenerated; that needs the owner's media review.
- `get_activity_timeline` returns `baseline_avg_hourly_bytes: 0` without a baseline. No page reads it; NET-170 should make it None.
