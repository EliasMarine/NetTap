# Go Live before the first admin no longer bounces to sign-in, 2026-11-14

**Linear:** NET-259
**Branch:** `fix/go-live-visual-shell`
**Status:** built and tested locally. Deploys with the web image. The behaviour only shows on a box
with no admin yet, so the G11 can't demonstrate it.
**Plan gate:** not needed. The fix is one condition in the browser; no server rule changes.

## Problem

The visual tests `/go-live (empty)` and `/go-live (error)` in the `firstrun` project failed. Their
screenshots showed the Login page ("Sign in with your admin account.") at every width, although the
test had already reached `/go-live`.

A real fresh box had the same problem. After typing the setup code, but before creating the admin,
opening Go Live sent the user to a sign-in page with no account to sign in to.

## Root cause

NET-198 (#248, 2026-11-12). Before the first admin exists, the hook lets `/go-live` through on the
setup cookie, so the shell renders and pings `/api/system/ping`. That path isn't a first-run path, so
the hook answers 401 "Sign in first". NET-198's `checkDaemon` read that as an expired session and
called `goto('/login?next=%2Fgo-live')`.

## Fix

`web/src/routes/+layout.svelte`: on a 401 "Sign in first", the shell sends the user to sign in only
when the layout data has a username, meaning someone was signed in. With no username it stays on the
page and doesn't mark NetTap offline. The old block is kept as OLD CODE.

- **Why a username is the right signal:** the root layout load returns `locals.user?.username`. The
  shell renders without one only on first-run paths during first run. The hook redirects every other
  unauthenticated page.
- **Sign-in still updates the username:** login and the wizard's account step both use
  `use:enhance`, so the layout data reloads with the username after sign-in.
- **A lapsed 24 h session still goes to sign-in:** its username was set at load.

## Tests

- `web/src/routes/layout.test.ts`: "stays on the page, and says nothing is offline, before the first
  admin exists". Against the old layout it fails, with `goto` called once with
  `/login?next=%2Fgo-live`.
- Layout tests: 43 of 43. Full Vitest: 5226 passed. svelte-check: 0 errors. `check:colors`: clean.
- Full `npm run test:visual`: 316 passed, 54 skipped, 0 failed, including both `/go-live` first-run
  shots.

## Security

The change is browser-side only, and `hooks.server.ts` is untouched.

- Before the first admin exists, `/api` calls without a valid setup cookie still get 401 from the
  hook (`hooks.server.store.test.ts`).
- Every other `/api` path still gets 401 "Sign in first" (`hooks.server.test.ts`).
- The browser now stays on the page when nobody was ever signed in, but that loads no data.

## Follow-up (not done)

Go Live is still unusable before the first admin exists. Its capture-mode call gets 401, so the page
says "Couldn't start Go Live". Sending first-run `/go-live` to `/setup`, or opening that call during
first run, is a hook change that needs a security review.

## Lessons

- A client-side "session expired" rule has to tell "expired" from "never signed in". Pages that open
  before any account exists hit the second case.
- Only the visual suite caught this. It isn't in CI yet.
