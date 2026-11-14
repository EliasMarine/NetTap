# Bridge API closed before the first admin exists, 2026-11-14

**Linear:** NET-280
**Branch:** `fix/first-run-bridge-net280`
**Status:** fixed, web only. Deploy: rebuild `nettap-web`.

## Problem

Before the first admin account existed, `/api/bridge/*` was still on the hook's first-run list
(`FIRST_RUN_PATHS` in `web/src/hooks.server.ts`). A browser holding the setup cookie could call
`create`, `teardown`, `bypass/enable` and `bypass/disable`. `create` reaches the daemon's real bridge
build.

## Root cause

The entry was left over from when Go Live opened before the first admin. Since NET-277 (PR #284)
nothing calls `/api/bridge` before the first admin:

- `lib/api/bridge.ts` is used by Go Live, System's BridgeStatus and Infrastructure. All three need a
  session.
- The wizard's one bridge call (`/api/bridge/health` in `runVerification()`) runs after `createAdmin`
  has signed the admin in.
- No install or remote script calls it. `deploy-pr110-review-fixes.sh` only checks that it is refused.

## Fix

`FIRST_RUN_PATHS = ['/setup', '/api/setup']`, with the old line kept as OLD CODE. Before the first
admin exists, a bridge call now gets 401 JSON. A bridge address opened as a page goes to `/setup`
(no users) or `/login`. Nothing changes after the first admin exists. `/api/setup/configure` was not
narrowed: that is a separate, optional follow-up in the issue.

## Tests

- `hooks.server.test.ts`: create, teardown, bypass enable and disable, and health each get 401 with a
  valid setup cookie and no users. The 6 new tests failed with the old list (`expected 200 to be 401`).
- `hooks.server.store.test.ts`: the same with the real user store, both with no store and with an
  empty one.
- `e2e/visual/api-401.visual.ts`: a same-origin link to `/api/bridge/create` on a NetTap page, with
  no session, gets a 302 and lands on `/login`.
- Full Vitest: 5266 passed. svelte-check: 0 errors. Visual suite: 318 passed, 54 skipped.
- `/deep-review`: no findings. `/ponytail-review`: ship.

## Lessons

When a caller stops using an open path, take the path off the open list in the same change. The
first-run list only ever needed to be as wide as the wizard's own calls.
