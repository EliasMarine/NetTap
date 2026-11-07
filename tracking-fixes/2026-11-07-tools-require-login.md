# The network tools and lookups need a login (NET-193)

## Problem

`web/src/hooks.server.ts` listed `/api/tools`, `/api/lookup`, `/tools` and `/lookup` in `PUBLIC_PATHS`. Commit `3f4ea9d6` added them on 2026-03-06 "so tools pages work without auth". The web proxy adds the daemon token itself, so anyone on the LAN, without signing in, could:

- make the appliance ping, trace and run DNS recon or SSL checks against any host (`/api/tools/*`);
- look up MAC vendors, which queries OpenSearch for unknown vendors and returns names seen on the network;
- run reverse DNS and WHOIS from the appliance (`/api/lookup/*`).

The PR 2 security review (NET-192, #200) found it.

## Root cause

The tools were made public so their pages would work before anyone signed in. That was never needed: no page that runs before sign-in (login, setup, go-live) calls them.

## Fix

- `PUBLIC_PATHS` is now `['/login', '/api/auth/login', '/api/auth/logout', '/api/auth/me']`; the old list is kept as OLD CODE.
- The three auth routes are named exactly rather than all of `/api/auth/*`. Any other path under it would fall through to the catch-all proxy, which forwards it to the daemon with the daemon token; the deep review raised this. The daemon has no `/api/auth` routes.
- Public and first-run paths match whole path segments (`isUnder`), so `/login` no longer opens `/loginx`, and a future `/api/auth-tokens` or `/setupx` would not be public by accident.
- Without a session, a tools or lookup page or API redirects to `/login`, as every other route does.

## Files

- web/src/hooks.server.ts
- web/src/hooks.server.test.ts
- scripts/remote/deploy-tools-login.sh

## Tests

- `hooks.server.test.ts`:
  - each of ten tools and lookup paths (pages and APIs) redirects to `/login` without a session, and passes with one;
  - `/loginx`, `/api/authx` and `/api/auth-tokens` are not public;
  - `/api/auth`, `/api/auth/other` and `/api/auth/..%2Ftools%2Fping` are not public;
  - the three auth routes still are;
  - during first run, `/tools/ping` goes to setup;
  - `/setupx` during first run goes to setup, not through.
- The old "allows /tools without auth" test is kept as OLD CODE. The JWT test that used `/tools` for an invalid token now uses `/login`.

## Device check

`deploy-tools-login.sh` sends each tools and lookup path, plus `/api/auth/other` and `/api/auth/..%2Ftools%2Fping`, with no cookie and needs `302 /login`. Then it needs `200` from `/login` and `/api/health`, and `401` from `/api/auth/me` (the route answers for itself).

## Lessons

A path made public "so the page works" needs the question: does any page before sign-in call it? Here none did.
