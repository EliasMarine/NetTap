# NET-198: a lapsed session sends you to sign in, 2026-11-12

**Linear:** NET-198
**Branch / PR:** `fix/session-expiry-sign-in` (the lead opens the PR)
**Status:** code and tests done; device deploy and click-through pending.
**Plan:** `.codex-review/2026-11-12-173311-session-expiry-sign-in/PLAN.md`, approved by Codex in round 2.

## Why

The session lasts 24 hours. On a tab left open past that, the shell polls every 30 seconds and every call gets a 401. The ping check counted any reply that wasn't OK as "offline", so the top bar said "Can't reach NetTap" and nothing sent the user to sign in until they navigated. The notification stream closes on a 401 and stays closed.

## Root cause

- `checkDaemon()` in `web/src/routes/+layout.svelte` read the body only for an OK reply, so a 401 set `daemonOffline = true`.
- Since NET-197 the two 401s can be told apart by their body: the web app's own sign-in check sends `{"error":"Sign in first"}` (`hooks.server.ts`); the daemon's refusal is `{"error": "Unauthorized"}` (`daemon/api/daemon_auth.py`) and passes through the proxy unchanged.
- `/login` did not read `next` at all: the sign-in action always redirected to `/`. There was no existing same-origin check to reuse.
- `notification-stream.ts` said "EventSource auto-reconnects". That holds for a network drop, not for an HTTP error such as a 401, where the browser closes the stream for good.

## What changed

- **Ping check** (`+layout.svelte`): a 401 whose body says "Sign in first" calls `sendToSignIn()`, which goes to `/login?next=<path and query>`. Any other 401 (the daemon's), other status, HTML 200 or network failure still shows "Can't reach NetTap".
- **Quiet polls:** while that navigation runs no new tick starts (`redirecting`). The flag is released when the `goto` ends, so a navigation that was superseded or failed leaves the shell polling and it asks again on the next tick. A ping that began before the shell stopped (`shellRun`, bumped in the effect cleanup) can't redirect a freshly signed-in user or flash "offline" after the redirect started.
- **`next` handling** (`web/src/lib/server/login.ts` `safeNextPath`, used by `login/+page.server.ts`): only a same-origin path is followed, else `/`. The result is the URL parser's own form, checked again, because `/a/..//evil.com` and `/%2e//evil.com` normalise to `//evil.com`. The form has no `action`, so `use:enhance` posts to the page's own address and `?next=` survives; a test pins that.
- **Notification stream:** no behaviour change. The bell lives in the shell, which `/login` (a bare route) unmounts and closes the stream with; signing in lands on a shell page and opens a new one. A layout test proves it. Only the wrong comment was fixed.
- `hooks.server.ts`: a comment on `unauthorised()` saying the shell matches its error text.

## Files

`web/src/routes/+layout.svelte`, `web/src/lib/server/login.ts`, `web/src/routes/login/+page.server.ts`, `web/src/lib/api/notification-stream.ts` (comment), `web/src/hooks.server.ts` (comment), `scripts/remote/deploy-session-expiry.sh`. Tests: `web/src/routes/layout.test.ts`, `web/src/lib/server/login.test.ts`, `web/src/routes/login/login-server.test.ts`, `web/src/routes/login/login-page.test.ts`.

## Test results

- Before: vitest 354 files / 4548 tests pass; svelte-check 0 errors, 2 warnings (DrawerSection, KVRow; unchanged).
- After: 354 files / 4588 tests pass (+40); svelte-check unchanged; `npm run check:colors` clean. No markup or style change, so `test:visual` was not run.
- Each guard was removed in turn and its tests failed: the stale-reply checks, the flag release, the body match (status only), the paused ticks, and the output re-check in `safeNextPath`.

## Device

Read-only on 2026-11-12, before the deploy: through nginx with no cookie `GET /api/system/ping` is 401 `{"error":"Sign in first"}` as JSON; the daemon's own 401 is `{"error": "Unauthorized"}`; the sign-in form is `<form method="POST">` with no action. `deploy-session-expiry.sh` repeats these after the web rebuild and checks the new client code is in the image.

To see the redirect: sign in, open Devices, delete the `nettap_token` cookie in the developer tools, wait up to 30 seconds. The page goes to the sign-in page with `?next=%2Fdevices`; signing in returns to Devices.

## Lessons

- The root layout survives client-side navigation, so state that "resets on the next page" must be released by the thing that set it (here the `goto` promise), not by a mount.
- A guard in a security helper must be applied to the value that is returned, not the value that was checked: URL normalisation can make a safe input into an unsafe output.
- An `EventSource` that gets an HTTP error is closed for good; "auto-reconnect" only covers dropped connections.

## Not done (out of scope)

- A global "session expired" handler for every API caller: a page's own fetch still shows its own failure state until the next ping (30 seconds at most).
- A tab hidden past expiry is redirected on the first tick after it becomes visible again.
- `next` is not honoured for an already signed-in visitor of `/login` (the hook sends them to `/`).
- The sibling polls already in flight when the ping returns may flash their usual "unknown" state for a moment before the page changes.
