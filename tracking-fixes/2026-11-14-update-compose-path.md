# Dead compose path retired, Versions loses two "unknown" rows, 2026-11-14

**Linear:** NET-288
**Branch:** `fix/update-compose-path-net288`
**Status:** done. PR #291 merged (`3886583c`); verified on the G11 at `f10eee24` (`deploy-triage-fixes-3-2026-11-14.sh`: a fresh scan's core rows are `nettap-daemon` only, `GET /api/system/versions/nettap-config` is 404).

## Problem

`UpdateExecutor` ran `docker compose -f /opt/nettap/docker/docker-compose.yml pull|up` for image
updates and rollbacks, and `VersionManager` looked for `web/package.json` relative to the same path.
That path never exists in the daemon container: compose mounts no repo there and never sets
`COMPOSE_FILE`. Found by the host-assumption audit during the Unraid research.

## Root cause

- The compose calls (`_update_docker_images`, `_rollback_docker`) were dead code. `_apply_batch` and
  `rollback()` already had those calls commented out, only tests called them, and the Updates page
  only offers `malcolm`, `suricata-rules` and `geoip-db`. `MalcolmUpgrade` replaced the compose path:
  it reads the project from the daemon's own container labels and runs compose in a helper container.
- The visible defect was in `VersionManager`. On the G11, `/api/system/versions` showed
  `nettap-web = unknown` and `nettap-config = unknown`, and the core `nettap-web` row collided with
  the Docker scan's `nettap-web` row.

## Fix

- The two compose methods, the `compose_file` parameter (UpdateExecutor, VersionManager) and the
  `COMPOSE_FILE` read in `create_app()` are retired, kept as OLD CODE.
- `_scan_core` reports `nettap-daemon` only. The Docker scan's `nettap-web` row stays.
- Intended API change: `GET /api/system/versions/nettap-config` now returns 404.
- Rejected: mounting the repo into the root daemon (it would expose `docker/.env`), and reading the
  web version through `docker exec` (more docker.sock use for a display row).

## Tests

- New, each seen failing first: no compose path left in UpdateExecutor; VersionManager takes no
  compose path; core rows are only what the container can read; scan names are unique;
  `nettap-config` is 404; a real `create_app()` wiring test builds both services without a path.
- Kept executable and re-driven with `suricata-rules`: completion clearing and history bounding.
- Full daemon pytest: 5029 passed, 5 skipped, 0 failed. ruff format/check clean on the changed files.
- Plan: `/codex-review` approved in 2 rounds.

## Next

- `_create_backup`'s docker-image branch is now unreachable; retire it in a follow-up.
- `web/package.json` says 0.3.0 while `NETTAP_VERSION` is 0.4.0.
- After deploy: `GET /api/system/versions` shows `nettap-daemon` as the only core row, `nettap-web`
  once, and no `unknown` row.

## Lessons

When a code path moves to a new mechanism (here MalcolmUpgrade's helper container), retire the old
one in the same change. Dead code with a wrong path looked like a live bug for months.
