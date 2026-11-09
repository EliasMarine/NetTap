# A --defer-bridge install now gets the OpenSearch bootstrap and index templates

**Date:** 2026-11-08
**Branch:** `fix/activate-bridge-bootstrap`
**Linear:** NET-216
**Status:** PR open, not merged. Not verified on a device: the G11 was installed the normal way, so it never took this path. Merging deploys nothing.

## What the owner asked

"Not sure about the arkime_sessions3_template, recommend something." The repo cleanup (NET-214) had kept `deploy-data-accuracy-batch17.sh` because it writes that marker.

## What we found

- **The installer already writes the marker.** `deploy-malcolm.sh` `bootstrap_index_templates` has created it since `3b53849` (2026-11-02). `deploy-data-accuracy-batch17.sh` only matters for boxes installed before that. An earlier note said the installer did not write it; that was wrong (a `git grep | head -5` was filled by old review hits).
- **The real gap is the deferred-bridge path.** `install.sh --defer-bridge` leaves service start to `scripts/install/activate-bridge.sh`. Its `start_services()` ran a bare `docker compose -f docker/docker-compose.yml up -d`. That skipped what a normal install runs: the image build, OpenSearch first, the security bootstrap, `malcolm_template` and the marker.
- **What such a box looks like:** every service gets 403 (Chain 11), Logstash waits for `malcolm_template`, and Malcolm's dashboards-helper waits forever for the marker (`shared-object-creation.sh:300-303` → `opensearch_status.sh:92`, no timeout). Every page is empty.
- **Why the test missed it:** the old bats Test 6 typed out `docker compose up -d` itself instead of running `start_services()`.

## What changed

- **`scripts/install/activate-bridge.sh`:** `start_services()` runs `"${SCRIPT_DIR}/deploy-malcolm.sh" --start-only`. `--start-only` skips the image pull and the config step, then runs preflight and the same `start_services` a normal install runs. The dry-run line names the new command. The old OpenSearch wait after the start is gone: `deploy-malcolm.sh` already waits, and that `curl -skf` sent no credentials, so OpenSearch answered 401 and it always waited the full 5 minutes, then warned "did not become healthy" on a healthy box. All three old blocks are kept as `OLD CODE`.
- **`tests/scripts/test_activate_bridge.bats`:** Tests 6a–6c cut the real `start_services()` out of the script and run it under `set -euo pipefail` against a stub `deploy-malcolm.sh`:
  - 6a: it calls `deploy-malcolm.sh --start-only` and never calls `docker compose` itself.
  - 6b: a failing `deploy-malcolm.sh` fails activation.
  - 6c: `--dry-run` calls nothing.
  - 6a and 6b failed before the fix. The old Test 6 is kept as `OLD CODE`.
- **`Debugging/DEPLOYMENT-ISSUES.md`:** Chain 28, a Known Risks row, a Key Files row, a stack-health row and an issue-map row.

## Test results

- `bats tests/scripts/test_activate_bridge.bats`: 9/9 pass.
- `bats tests/scripts`: 247 pass, none fail (main had 245; the old Test 6 became 6a–6c).
- `shellcheck scripts/install/activate-bridge.sh`: only the existing SC1091 note (it does not follow `common.sh`).

## Follow-ups (NET-216)

- `deploy-malcolm.sh`'s bootstrap functions warn and return 0 when they fail, so an install can report success with auth or the templates missing. Making them fail hard changes the normal install too, so it is left out of this fix.

## Lessons

- Two scripts that start the stack drifted apart. Start it from one place (`deploy-malcolm.sh`) and call that, rather than copying `docker compose up`.
- A test that types out the command it means to check proves nothing. Run the real function.
