# 2026-11-03 — UI redesign (pure black, Ember default)

**Status:** PR 1 (foundation) in progress on `feature/ui-redesign-foundation`. Linear: NET-144 (parent), NET-145 (PR 1).

**Plan:** `PLAN.md` (repo root). Codex approved it after 4 rounds (19 findings: 6 High, 13 Medium; all taken on, one narrowed). The review log is in `.codex-review/2026-11-03-144402-ui-redesign/` (gitignored).
**Visual reference:** `mockups/redesign-2026-11/index.html` (owner-approved 2026-11-03).

## Owner decisions (2026-11-03)

- **Background:** pure black (#000) on every page.
- **Variants:** Ember is the default. Graphite and Spectrum ship too, picked in Settings → Display.
- **Navigation:** grouped left sidebar; a menu button on phones.
- **Replaced code:** CSS and markup are deleted, with git history as the record. Replaced logic keeps OLD CODE START/END.
- **Density:** balanced, for a 1920 px monitor; must work at 1440 and 390.

## Phases and branches

Each phase gets a fresh branch from `main`, created after the previous PR merges. Branches are never reused.

| Phase | Branch | PR | Linear | Status |
|---|---|---|---|---|
| PR 1 foundation | `feature/ui-redesign-foundation` | — | NET-145 | In progress |
| PR 2 shell | `feature/ui-redesign-shell` | — | — | Not started |
| PR 3 shared components | `feature/ui-redesign-components` | — | — | Not started |
| PR 4a–4g pages | `feature/ui-redesign-<batch>` | — | — | Not started |

## PR 1: foundation

**What changes**
- **Tokens:** `global.css` has a new token block for Ember, Graphite and Spectrum. Every legacy token maps onto it, so the whole app goes black at once.
- **Severity:** each severity has its own token (`--sev-*`), the same in every variant. The per-file audit is listed in the PR body.
- **Hard-coded colours:** about 310 across 49 files are replaced by tokens. Email HTML keeps its literals, with a per-line exemption.
- **Fonts:** Sora, Manrope and JetBrains Mono are bundled (OFL, `web/static/fonts/`). The Google Fonts links are gone.
- **Theme:** a bootstrap script in `app.html` applies the saved theme before first paint. `$lib/stores/theme` and `ThemePicker.svelte` live in Settings → Display.
- **GeoMap:** canvas colours come from tokens via `resolveToken`, and are re-read when the theme changes. Drawing and scheduling are split (`arc-scheduler.ts`), so reduced motion keeps the static arcs.
- **Colour gate:** `npm run check:colors`, run in the CI Lint Web job before svelte-check.
- **Visual harness:** `npm run test:visual`, with fixtures type-checked by `npm run check:e2e` (also in CI).
- **Contrast test:** `src/tests/token-contrast.test.ts`. Every text and severity token is AA on every surface, in every variant.
- **Deploy script:** `scripts/remote/deploy-ui-redesign.sh` rebuilds only `nettap-web`, then checks the bootstrap, the fonts and the new stylesheet.

**Test results:** to be filled in before the PR.

## Lessons

- In Playwright 1.58, `webServer` entries start before `globalSetup`. Anything the servers need (temp dirs, a fixture daemon) has to exist by the time the config loads, or be a `webServer` itself.
- A Svelte store notifies its subscribers synchronously. Anything that reads computed CSS when the theme changes needs the DOM attribute set *before* the store publishes.

## Next steps

1. Finish PR 1. Gates: `/ponytail-review`, `/deep-review`, then the PR, `gh pr checks`, a G11 deploy, and a check in Chrome in all three variants.
2. PR 2 (shell) on a fresh branch after PR 1 merges.
