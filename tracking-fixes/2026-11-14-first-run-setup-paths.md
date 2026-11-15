# First-run `/api/setup` narrowed to the wizard's exact calls, 2026-11-14

**Linear:** NET-290 (follow-up to NET-280, LOW-1 and LOW-2 of the PR #289 security review)
**Branch:** `fix/first-run-setup-paths-net290`
**Status:** done. PR #295 merged (`3dbfec7e`); deployed to the G11 at `97793a93` (`deploy-triage-fixes-4-2026-11-14.sh`: a signed-out `POST /api/setup/configure` gets 401). The G11 has an admin, so the first-run list itself is covered by CI's first-run tests.

## Problem

Before the first admin existed, the hook's first-run list opened the whole `/api/setup` prefix to a browser
holding the setup cookie.

- **LOW-2:** `POST /api/setup/configure` was open. It can restart the capture containers, put a NIC into
  mirror mode and write UniFi settings. Its only caller, `saveSetupConfig()`, runs after the Account step.
- **LOW-1:** the daemon's real bridge build is `POST /api/setup/bridge`. The wizard's call of the same name is a
  web route that only asks the daemon for the read-only preview. Only that route file stood between a
  setup-cookie holder and the real build: if it were removed, the catch-all proxy would forward the call.

## Root cause

`FIRST_RUN_PATHS` matched `/api/setup` as a prefix, so every present and future route under it opened with the
setup cookie, when the wizard needs four calls.

## What the wizard really calls before the Account step

Checked against every `fetch` in `routes/setup/+page.svelte` and `src/lib` (the issue's list was right):

| Call | Step |
|---|---|
| `GET /api/setup/nics` | Welcome requirements check, Interfaces |
| `GET /api/setup/storage` | Welcome requirements check, Storage |
| `POST /api/setup/storage` | Storage save |
| `POST /api/setup/bridge` | Bridge verify (bridge mode), the read-only preview |

`POST /api/setup/configure` runs in the `form?.success` effect, after `createAdmin` has set the session cookie,
so it needs that session. Each of the five has its own route file. Settings' Retention tab uses
`/api/setup/storage` with a session; `POST /api/bridge/create` calls the daemon's `/api/setup/bridge`
server-side with a session. Neither is affected.

## Fix

- `web/src/hooks.server.ts`: `FIRST_RUN_PATHS = ['/setup']`. The four calls are exact method-and-path entries in
  `FIRST_RUN_REQUESTS`, next to the three that were already there. Any other `/api/setup` path or method gets
  401 `Sign in first` until the first admin exists. Old line kept as OLD CODE.
- `web/src/routes/api/[...path]/+server.ts`: the catch-all answers 404 `Not found` for `setup` or `setup/*`
  and never calls the daemon. It checks `params.path` (SvelteKit's decoded rest-parameter), not
  `url.pathname`, because the daemon decodes `/api/%73etup/bridge` before it routes. Every wizard call has its own
  route, so only a removed or never-existing route reaches it. `params` is a required part of the handler's event
  type (`RequestEvent<{ path: string }>`), so a caller that leaves it out does not compile and cannot skip the
  guard. (An encoded path that matches an existing route, such as `/api/%73etup/bridge`, goes to that route and
  is judged by the hook on the raw path, as before.) The guard (`isSetupPath`) takes the first real segment of
  the matched path, so `//setup`, `;/setup`, `Setup` and `%2573etup` (one more round of decoding) are refused too.
  aiohttp 404s those today (it keeps `%2F` encoded and decodes once); the guard does not rely on it. A segment
  with no letter or digit (`;`, `.`) is skipped, which the first-non-empty-segment form would not have done.
- `web/src/hooks.server.ts`: `/setup` is matched exactly, not as a prefix, in `isFirstRunPath` and in the
  setup-cookie check, so a route file added under `routes/setup/` later is not open before the first admin exists
  without the code (before this it would have answered without it). Nothing the wizard uses is under `/setup`:
  SvelteKit 2.70.3 strips `/__data.json` from the page's data request before the hook runs
  (`respond.js`, `strip_data_suffix`), and form actions are `/setup?/verifyCode`, `/setup?/createAdmin` (the query
  is not in `pathname`). Old code kept as OLD CODE.

Nothing changes after the first admin exists: every call there needs a session, and a session is enough.

## Tests

- `hooks.server.test.ts` (mocked auth) and `hooks.server.store.test.ts` (real user store): the four calls need the
  setup cookie and pass with it; `configure`, an unlisted `/api/setup/other`, wrong methods
  (`POST nics`, `GET bridge`, `PUT storage`) and `POST /api/setup/bridge/preview` get 401 with the cookie (mocked
  auth; real store with no store and with an empty store); after setup all five need a session and a session is
  enough. The existing damaged-store test now also covers the four calls, `configure` and `/api/bridge/create`
  (401, never resolved). 10 of the new tests failed with the old prefix.
- `routes/api/catchall-setup.test.ts`: GET, POST, PUT and DELETE to `setup/bridge`, `setup/configure`,
  `setup/bridge/preview`, `setup`, `setup/other` and the encoded forms (`%73etup`, `%2F`) get 404 and never reach
  the daemon, now also `//setup`, `%2Fsetup`, `;/setup`, `Setup` and `%2573etup` (20 more, failed before the
  change); `/api/setupx` and `/api/dhcp/setup/leases` still proxy. All 28 failed before the guard. That test
  decodes the path itself, so the real router is covered in `e2e/visual/api-401.visual.ts` (below).
- `e2e/visual/firstrun.visual.ts` (first-run instance, real hook and routes): configure and unlisted
  `/api/setup` paths get 401 with the code typed (failed with the old prefix: 500 from the configure route); the
  four wizard calls each return 200 with a field from the response, and 401 `Enter the setup code first.` without
  the code. Two new fixture routes in `e2e/visual/fixtures/setup.ts`: `POST /api/setup/bridge/preview` and
  `POST /api/storage/config`.
- `e2e/visual/api-401.visual.ts` (signed-in app instance): `/api/setup/does-not-exist`,
  `/api/%73etup/does-not-exist`, `/api/%73etup/bridge/preview`, `/api/setup%2Fbridge/preview` and the five other
  spellings above (`/api//setup/...`, `/api/%2Fsetup/...`, `/api/;/setup/...`, `/api/Setup/...`,
  `/api/%2573etup/...`) answer
  `{ error: 'Not found' }` through the real router. The body is compared: with the guard off the fixture daemon
  also answers 404, but with `No fixture for GET ...`, and that is what the test saw fail.
- `hooks.server.test.ts` and `hooks.server.store.test.ts`: `/setup/anything` is redirected to `/setup` before the
  first admin exists, with and without the setup cookie; `/setup?/verifyCode` stays open. `firstrun.visual.ts`
  asserts that the page's own `/setup/__data.json` request still answers `type: 'data'` and that
  `/setup/anything` gets a 302 to `/setup` (404 with the old prefix: the route would have answered open).
- Trailing slash: SvelteKit 308-redirects `/api/setup/storage/` to the canonical address before the hook runs, so
  it is judged there, not refused. The visual test asserts the 308 and the canonical 200.

## Not verified here

A fresh-install run of the real wizard on a device. The vitest wizard suites mock `fetch`; the visual test calls
the four routes for real, but a person walking the wizard on the G11 is the check for a call this list missed.
If a step fails with 401 `Sign in first` after deploy, add that call's exact entry to `FIRST_RUN_REQUESTS`.

## Lessons

An open prefix is only as safe as every route under it, now and later. Open the exact calls a flow makes, and
make the catch-all refuse the name space the flow shares with a more dangerous daemon route.
