# Another site can no longer start daemon work through /api, 2026-11-14

**Linear:** NET-257
**Branch:** `fix/pcap-download-same-origin`
**Status:** merged in #276. Deployed and verified on the G11 2026-11-14 at `35f684d4` (`scripts/remote/deploy-triage-fixes-2026-11-14.sh`, every check passed): cross-site `/api/threats/beaconing` and `/api/pcap/download` got 403, same-origin got 401 (sign-in), `/api/health` 200.
**Plan:** `PLAN.md` (Codex review, 5 rounds, APPROVED: 2 on the first design, 3 after the pre-merge
security review found a bypass).

## Problem

`/api/pcap/download`, `/api/pcap/download-file` and `/api/packets/capture-file` are GET routes. The
session cookie is `SameSite=lax`, so a link on any other site carried it. Any page the signed-in
owner opened could start a download, which held the daemon's single download slot and one of its two
reader slots. The owner's own downloads then got 503 for up to about 4.5 minutes. No data left the box.

## Fix

`web/src/hooks.server.ts`, at the top of the non-public block: an `/api` request whose
`Sec-Fetch-Site` is present and isn't `same-origin` gets 403, "Open this from NetTap itself.", before
any route runs.

- **Every `/api` route, by the route SvelteKit matched (`event.route.id`)**, not the raw path:
  - The first design checked only the catch-all proxy. The pre-merge security review showed an
    explicit route (`logs/fields/[log_type]`) put its decoded param into the daemon path, so
    `..%2F..%2Fpcap%2Fdownload` reached the download without passing the catch-all.
  - About 100 other explicit routes (beaconing scans, WHOIS) had the same gap.
  - Codex then showed that an encoded prefix (`/%61pi/…`) gets past a literal `/api` path test. So
    the check classifies by the matched route.
- **`none` is refused too.** Browsers send it for links opened from mail and chat apps. No NetTap flow
  needs a typed `/api` URL.
- **Allowed:** `same-origin` (every NetTap page, including downloads) and no header (scripts, curl,
  device checks).
- **Untouched:** public paths, so nginx's `auth_request` to `/api/auth/me` for Grafana, CyberChef and
  Dashboards still works, as do login and logout. Pages are untouched too, since they may be linked
  from anywhere.
- **Encoded route params:** `logs/fields/[log_type]` and `suricata/rules/sources/[id]/enable|disable`
  now use `encodeURIComponent`, so a decoded `../` can't steer them to another daemon route.
  - Checked: aiohttp 3.13.3 still matches `et%2Fopen` as `et/open` on the daemon's `{id:.+}` route.
- **Reverted:** the first design's catch-all check (`[...path]/+server.ts`), which was never merged.

## Tests

- `web/src/hooks.server.test.ts`: 19 new cases, all failing before the fix:
  - the download, beaconing, the traversal path and two encoded-prefix paths, each from `cross-site`,
    `same-site` and `none`, get 403 and the route never runs;
  - a cross-site POST gets 403;
  - `same-origin` and no header pass;
  - a page and `/api/auth/me` from another site pass.
- `web/src/routes/api/encoded-params.test.ts`: the three routes keep a `../` inside their own segment.
  This failed before the fix.
- Full Vitest: 5248 passed after the rebase on main (the NET-274 failure is fixed by #277). svelte-check: 0 errors. Build: OK. Colour gate: clean.
- No `+server.test.ts` beside a route: SvelteKit refuses any `+`-prefixed file under `routes/` that it
  doesn't know.

## Reviews

- /ponytail-review: ship.
- /deep-review: no findings on the first design, and no findings on the re-run of this one.
- Two-angle review:
  - Security-engineer: the first review found the bypass that led to this design. The re-review found
    no Critical, High or Medium. Its one Low, a cross-site link to `/packets?<search>` making the
    owner's own page run a search on open, is filed as NET-276.
  - TypeScript reviewer: approve, no Critical, High or Medium. It mutation-tested each condition in the
    guard. Its four Low test nits are fixed in the second commit.

## Lessons

- A Fetch Metadata check belongs where every route passes (the hook), keyed on the matched route, not
  on a literal path. SvelteKit and aiohttp both decode paths before routing.
- Encode every route param you put into a backend path. SvelteKit hands params over decoded.
- `Sec-Fetch-Site: none` is not "the user typed it". Native apps send it too.
