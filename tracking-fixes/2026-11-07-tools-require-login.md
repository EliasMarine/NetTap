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
- The public paths are matched exactly (a `Set`), not as prefixes. Any other path under `/api/auth` (`/api/auth/other`, `/api/auth/me/x`) would fall through to the catch-all proxy, which forwards it to the daemon with the daemon token. The deep review and the security engineer raised this. The daemon has no `/api/auth` routes, so it wasn't exploitable today.
- A SvelteKit remote-function call without a session is refused with 401 before any path rule runs, because its pathname comes from the client's `x-sveltekit-pathname` header (security engineer, informational). The app has no remote functions yet.
- First-run paths match whole path segments (`isUnder`), so a future `/setupx` would not open during first run.
- Without a session, a tools or lookup page or API redirects to `/login`, as every other route does.

## Files

- web/src/hooks.server.ts
- web/src/hooks.server.test.ts
- scripts/remote/deploy-tools-login.sh
- scripts/remote/deploy-pr110-review-fixes.sh (its MAC lookup step called the tool anonymously; it now calls the daemon with its token)

## Tests

- `hooks.server.test.ts`:
  - each of ten tools and lookup paths (pages and APIs) redirects to `/login` without a session, and passes with one;
  - `/loginx`, `/api/authx` and `/api/auth-tokens` are not public;
  - `/api/auth`, `/api/auth/other`, `/api/auth/me/x`, `/api/auth/login/x`, `/login/x` and `/api/auth/..%2Ftools%2Fping` are not public;
  - a remote-function call without a session gets 401 whatever path it claims, and passes with one;
  - the three auth routes still are;
  - during first run, `/tools/ping` goes to setup;
  - `/setupx` during first run goes to setup, not through.
- The old "allows /tools without auth" test is kept as OLD CODE. The JWT test that used `/tools` for an invalid token now uses `/login`.

## Device check

`deploy-tools-login.sh` sends each tools and lookup path, plus `/api/auth/other` and `/api/auth/..%2Ftools%2Fping`, with no cookie and needs `302 /login`. Then it needs `200` from `/login` and `/api/health`, and `401` from `/api/auth/me` (the route answers for itself).

## Lessons

A path made public "so the page works" needs the question: does any page before sign-in call it? Here none did.

## Reviews

- `/deep-review` (auth agent): no findings. It raised the `/api/auth/*` fall-through, now closed (`security-reviews/fix-tools-require-login/`).
- security-engineer: no Critical, High or Medium findings.
  - Low: `/api/auth/<route>/x` fell through to the proxy. Fixed by exact matching.
  - Informational: remote-function pathname. Guarded.
  - Informational: `/cyberchef/` has no `auth_request` in `docker/nginx.conf`. Left as it is: CyberChef is a static browser app and makes the appliance do nothing.
- typescript-reviewer: approved. Its test notes are applied: the bare tools pages, the first-run redirect for tools, and a real bad token.
