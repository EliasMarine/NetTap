# Go Live goes to setup until the first admin exists, 2026-11-14

**Linear:** NET-277
**Branch:** `fix/go-live-first-run-setup`
**Status:** done. PR #284 merged (`26432184`), deployed to the G11 at `d39ecfcb`. The G11 has an admin, so only the unchanged signed-out redirect shows there; CI's first-run visual job covers the first-run path.
**Plan:** `PLAN.md` (Codex review, 1 round, APPROVED; log in `PLAN-REVIEW-LOG.md`).

## Problem

On a fresh box, after the setup code is typed but before the admin account exists, `/go-live` opened
on the setup cookie. Its capture-mode call isn't a first-run path, so the hook answered 401 "Sign in
first", and the page said "Couldn't start Go Live — Could not read the capture mode: Sign in first".
The shell's capture, storage and alert calls got 401 too.

NET-259 (#280) stopped the shell sending this page to sign-in, but the page still couldn't work.

## Root cause

`FIRST_RUN_PATHS` in `web/src/hooks.server.ts` listed `/go-live`. The first-run gate therefore let the
page through on the setup cookie, while every call the page makes needs a session. Go Live can't do
anything before an admin exists.

## Fix

The owner decided that before the first admin exists, `/go-live` answers 302 to `/setup`. The wizard
creates the admin and signs them in, and Go Live then works as before. Opening the capture-mode call
behind the setup cookie was turned down.

- `web/src/hooks.server.ts`: `/go-live` is removed from `FIRST_RUN_PATHS` (old line kept as OLD
  CODE). During first run it is now an ordinary page, so it reaches the hook's existing
  `if (firstRun) throw redirect(302, '/setup')`. No new branch.
- After the first admin exists nothing changes. `FIRST_RUN_PATHS` is only read during first run.
- `/api/bridge` stays in `FIRST_RUN_PATHS`. After this change nothing calls it before the first admin
  exists:
  - Go Live now redirects.
  - `BridgeStatus` lives on `/system` and `/infrastructure`, which already go to `/setup`.
  - The wizard calls `/api/bridge/health` only in the Verification step, after the Account step has
    signed the admin in.
  Removing it is safe but buys almost nothing, since only the setup-cookie holder gets through and the
  same cookie already opens `/api/setup/*`. Left as a possible follow-up.
- **Known limit:** a client-side navigation to `/go-live` doesn't run the hook, because the page has
  no server load. The only in-app links to it are in the wizard's Verification step, after the admin
  exists. A typed address or bookmark is a full load and goes through the hook.

## Tests

- `web/src/hooks.server.test.ts`: "sends /go-live to /setup while no users exist, even with the setup
  cookie" and "... even with a leftover valid session". The setup-cookie case failed against the old
  hook (the page resolved instead of 302). The old "resolves with the setup cookie" half is kept as
  OLD CODE.
- `web/src/hooks.server.store.test.ts` (real user store): "/go-live goes to /setup until the first
  admin exists, even with the code typed", with no store and with an empty store. It failed against
  the old hook. The after-setup and damaged-store checks for `/go-live` are unchanged and pass.
- `web/e2e/visual/firstrun.visual.ts`: the `/go-live (empty|error)` sweeps are replaced (OLD CODE) by
  "/go-live goes to /setup before the first admin, even with the code typed". The `/go-live` known
  issue in `known-issues.ts` matched nothing any more and is kept as OLD CODE.
- Hook and layout tests: 163 of 163. Full Vitest: 5257 passed. svelte-check: 0 errors.
  `check:colors`: clean.
- Full `npm run test:visual`: 314 passed, 54 skipped, 1 failed. Every first-run test passed,
  including the new redirect test. The one failure is unrelated: `api-401.visual.ts` "an /api address
  opened as a page goes to /login" gets NET-257's 403 "Open this from NetTap itself." because
  `page.goto` sends `Sec-Fetch-Site: none` (#276). This diff doesn't touch it.
- NET-257 follow-up (separate commit): that visual test now expects the 403 and its body (old
  expectation kept as OLD CODE). `hooks.server.test.ts` gains "a same-origin page load of an /api
  address still goes to /login", because the existing redirect test sent no `Sec-Fetch-Site` and no
  matched route, so it never reached the NET-257 check. Full `npm run test:visual` after it: 315
  passed, 54 skipped, 0 failed. Full Vitest: 5258 passed.

## Security

- **Before the first admin, closed:** `/go-live` with the setup cookie (it rendered the page shell)
  now gets 302 to `/setup`. A leftover valid session cookie gets the same answer.
- **Before the first admin, unchanged:** `/setup` open, `/api/setup/*`, `/api/bridge/*` and the three
  exact wizard requests need the setup cookie. Every other path is refused or sent to `/setup`.
- **After the first admin, unchanged:** `/go-live` needs a session (302 to `/login` without one).
- **Damaged user store, unchanged:** fails closed to `/login`.
- Nothing is opened anywhere.

## Lessons

- A page that is open during first run is only useful if every call it makes is open too. Go Live's
  calls all need a session, so opening the page on the setup cookie only produced an error card.
- The visual harness's first-run `/go-live` shots only ever showed that error card. Go Live has no
  signed-in visual sweep yet.
