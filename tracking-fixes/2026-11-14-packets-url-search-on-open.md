# A packet search opened from outside NetTap waits for Run, 2026-11-14

**Linear:** NET-276
**Branch:** `fix/packets-url-search-on-open`
**Status:** fixed; PR open (reviews: TypeScript reviewer approve, /ponytail-review Ship).
**Plan:** `PLAN.md` (Codex review, 2 rounds, APPROVED). Log: `PLAN-REVIEW-LOG.md`.

## Problem

NET-257 refuses `/api` requests that another site starts. Pages stay open to links from anywhere, though,
and the Packets page ran the search in its URL as soon as it opened. A link from another site to
`/packets?<search>` made the owner's own page call `/api/packets/search`, and that call is same-origin, so
NET-257 let it through. One search holds one of the daemon's two shared packet-reader slots for up to about
48 s. A popup re-opened twice could hold both, and the owner's download then got 503.

## Root cause

`web/src/routes/packets/+page.svelte` loaded from an `$effect` on the URL's query string. The effect ran on
any URL, however the page was reached, and `load()` searched whenever the URL held a search.

## Fix

The owner's decision: a page opened from outside NetTap waits for Run; a search started inside NetTap runs
straight away.

- `+page.svelte`: SvelteKit's `afterNavigate` drives the load now (the effect is kept in an OLD CODE block).
  It runs on mount and after every navigation to a URL. Its `type` is `'enter'` for a full load (bookmark,
  pasted link, another site, a new tab); `link`, `goto`, `popstate` and `form` are navigations inside NetTap.
  A page from another site can only cause an `'enter'`, with one exception: a `/login?next=/packets?…`
  link. If the owner is signed out and signs in there, the login form's `enhance` follows the redirect
  with `goto`, so the search arrives as `'goto'` and runs. That is one search per sign-in, which can't
  hold both reader slots; a second popup with a session is sent from `/login` to `/`. Accepted (reviews).
- `held` starts `true` (nothing searches by default) and is set to `type === 'enter'` on each new search.
  While held, `load()` still loads the capture files and device names, not the search. The top bar's
  Refresh leaves it waiting.
- `rerun()` clears `held`. Every caller is an owner click: the new Run button, Try again, and the drawer's
  "captures changed" action.
- `ResultsView.svelte`: a waiting search shows "This search hasn't run yet" in the Packets card
  (`CardState`, one line, "Run the search" button). The question card above it already shows the search as
  the URL holds it, with Edit filter.
- In-app links into `/packets?…` all stay in-app (plain `<a href>`, none open a new tab): Connections and both
  connection drawers, Local services, DHCP timeline, Moment, and the Packets page's own links.

## Tests

- `web/src/routes/packets/packets-results.test.ts`: a router stand-in (afterNavigate on mount, plus a
  `navigate()` that moves the page and runs the callbacks; `goto` uses it). Five new tests:
  - a full load makes no search, shows the search and Run, and Refresh still makes none (failed before the fix);
  - Run searches once with the URL's search (failed before);
  - an edited search after waiting runs once, with the new filter (failed before: two searches);
  - an in-app arrival runs straight away, and a mounted page runs a link's search and Back's search, but not
    a hash-only or same-search navigation. These two guard behaviour that must not change, so they passed
    before; with `held` forced to `true` they fail.
- `packets-page.test.ts`: the mock gains `afterNavigate` (a full load).
- `web/e2e/visual/packets.visual.ts` (production build, real router): every `page.goto` is a full load, so
  the results tests click Run. New: a full load makes no search until Run, and an edited search runs once;
  Moment's "Search packets in this window" runs at once, then a conversation link, Back and Forward each run
  their search. `media.capture.spec.ts` clicks Run too (not run here: headed, needs ffmpeg).

## Results

- Vitest: 5260 passed (395 files). svelte-check: 0 errors (2 old warnings in drawer components).
  Colour gate: clean.
- Visual: the packets spec passes, all 7 tests including the 3 changed and 2 new. The full suite had 316
  passed and 2 failed: the first run of the new in-app test (it checked the path before the client-side
  navigation finished; fixed with `toHaveURL`, then passed), and `api-401.visual.ts` "an /api address opened
  as a page goes to /login". That one is unrelated: since NET-257 (#276) a typed `/api` address
  (`Sec-Fetch-Site: none`) gets 403 instead of the sign-in redirect, and this change touches no hook or API code.

## Review notes

- TypeScript reviewer: approve. Fixed: the waiting card said "opened from outside NetTap", which is wrong for
  a reload, a new tab or the owner's own bookmark; it now says "A search opened from a link, a bookmark or a
  reload waits for you to run it." Fixed: a comment on the page test's one-shot router stand-in.
  Not changed: Refresh on a waiting page says "Updated" (the captures and names did update, and the card says
  the search hasn't run); focus falls to the page body after Run (the same as Try again).
- /ponytail-review: Ship. Its should-fix was the `/login?next=` exception, now written under Fix above.

## Lessons

- A same-origin check on `/api` can't see who opened the page. A page that starts slow server work from its
  URL has to tell a full load from an in-app navigation itself; `afterNavigate`'s `type` is the documented signal.

## Next steps

- Candidates with the same shape (they load from their URL on open and use the daemon's two `drill_slots`,
  a separate pool from the packet reader): `/address/[ip]`, `/domain/[name]`, `/moment`,
  `/tools/dhcp-timeline`, `/local-services`, device compare. Not changed here.
