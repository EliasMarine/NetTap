# NET-198: a lapsed session sends you to sign in, 2026-11-12

**Linear:** NET-198
**Branch / PR:** `fix/session-expiry-sign-in` (the lead opens the PR)
**Status:** code and tests done, review follow-ups applied; device deploy and click-through pending.
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
- **`next` handling** (`web/src/lib/server/login.ts` `safeNextPath`, used by `login/+page.server.ts`): only a path to one of the web app's own pages is followed, else `/` (see the review follow-ups below). The result is the URL parser's own form, checked again, because `/a/..//evil.com` and `/%2e//evil.com` normalise to `//evil.com`. The form has no `action`, so `use:enhance` posts to the page's own address and `?next=` survives; a test pins that.
- **Notification stream:** no behaviour change. The bell lives in the shell, which `/login` (a bare route) unmounts and closes the stream with; signing in lands on a shell page and opens a new one. A layout test proves it. Only the wrong comment was fixed.
- `hooks.server.ts`: a comment on `unauthorised()` saying the shell matches its error text.

## Review follow-ups (PR #248, after /deep-review and the two-angle review)

- **One constant for the error text.** `SIGN_IN_FIRST` lives in `web/src/lib/auth-errors.ts`; the hook, the shell's ping check and their tests all read it, so rewording it can't silently break the redirect. (`LiveBandwidthCard.test.ts` and `LogDrawerContent.test.ts` still model the reply with the literal text; they don't depend on the redirect.)
- **`next` goes only to this app's own pages.** nginx serves `/grafana/`, `/dashboards/` and `/cyberchef/` on the same origin, and `/api/` is the daemon proxy, so a same-origin check alone let a sign-in link open Grafana (the reviewer flagged the Grafana we run as likely open to CVE-2025-4123, an open redirect; I did not check the version) or an API address. `safeNextPath` now also needs the first path segment to be one of the segments of `src/routes/**/+page.svelte`, read with `import.meta.glob` when the app is built, so new pages work with no list to keep. `/` and detail routes (`/devices/10.0.0.5`, `/domain/example.com`, `/alerts/suricata/…`) are kept. An encoded slash or backslash in the path is refused too, because a proxy in front can decode `/devices/..%2fgrafana/` into another app. nginx's own redirect for a signed-out `/grafana/` visit is a plain `/login` with no `next`, so nothing there changes. Limit (a code comment says so): a route group `(x)` or a dynamic first segment `[x]` would fall back to `/`.
- **Tests that were missing.** The `catch` guard in `checkDaemon` (`run === shellRun && !redirecting`) now has two tests, one per clause: a ping that fails after the redirect started, and one that fails after the shell restarted. Removing either clause alone fails a test (checked for all four guard clauses). The "already on its way" test no longer waits on a real timer; it uses fake timers.
- **Typing.** The parsed ping body is typed `{ error?: unknown; status?: unknown } | null` instead of `any`.
- **Skipped on purpose:**
  - The final re-parse check in `safeNextPath` (`new URL(out, base).origin`) is redundant today. It stays as the exact invariant the tests assert, and costs one clause.
  - There is still no ping when a hidden tab becomes visible; that predates this change (the tick that follows runs within 30 seconds).

## Files

`web/src/lib/auth-errors.ts` (new), `web/src/routes/+layout.svelte`, `web/src/lib/server/login.ts`, `web/src/routes/login/+page.server.ts`, `web/src/lib/api/notification-stream.ts` (comment), `web/src/hooks.server.ts` (the constant), `scripts/remote/deploy-session-expiry.sh`. Tests: `web/src/routes/layout.test.ts`, `web/src/lib/server/login.test.ts`, `web/src/routes/login/login-server.test.ts`, `web/src/routes/login/login-page.test.ts`, `web/src/hooks.server.test.ts`, `web/src/hooks.server.store.test.ts`.

## Test results

- Before: vitest 354 files / 4548 tests pass; svelte-check 0 errors, 2 warnings (DrawerSection, KVRow; unchanged).
- After: 354 files / 4615 tests pass (+67); svelte-check unchanged; `npm run check:colors` clean. No markup or style change, so `test:visual` was not run.
- Each guard was removed in turn and its tests failed: the stale-reply checks (each clause on its own, in the reply guard and the catch guard), the flag release, the body match (status only), the paused ticks, the output re-check, the route-segment check and the encoded-separator check in `safeNextPath`.

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
