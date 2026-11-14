# First-run visual tests run in CI, 2026-11-14

**Linear:** NET-278
**Branch:** `chore/ci-firstrun-visual-tests`
**Status:** CI-only change. Nothing to deploy. The new job is not a required status check yet.

## Problem

NET-259 (Go Live bounced to /login before the first admin existed) was caught only by a manual
`npm run test:visual`. CI ran Vitest and svelte-check but not the visual harness.

## Fix

`.github/workflows/ci.yml` has a new job, `Visual tests (first run)` (`test-visual-firstrun`):

- It follows `test-web`: checkout, Node 22 with npm cache, `npm ci`, `needs: lint-web`.
- `npx playwright install --with-deps chromium`. The config uses only Desktop Chrome.
- `npm run test:visual -- --project=firstrun`. The config's webServers start the fixture daemon,
  build the app into `.visual-build`, and serve the `firstrun` instance, so CI needs no extra env.
- On failure it uploads `web/test-results/visual/` (screenshots, error context), kept for 7 days.

It runs only the `firstrun` project (5 tests). The full suite takes about 8 minutes. Triggers and
existing job names are unchanged. `docker-build` does not wait for the new job.

## Tests

- Locally, as CI runs it (`CI=1`): 5 passed in 19.3 s, about 20 s including the build. Exit 0.
- With the NET-259 fix in `+layout.svelte` reverted, `/go-live (empty)` and `/go-live (error)` fail
  (exit 1, sidebar and `h1.page-title` missing). The fix was restored afterwards.
- `yaml.safe_load` passes. actionlint is not installed here.

## CI risks

- The suite stores no baseline screenshots. It saves screenshots to the output folder and checks
  DOM facts (theme accent, black body, no horizontal scroll, shell present), so there are no
  `-darwin`/`-linux` baselines to keep in sync.
- Fonts are self-hosted (`/fonts/...`), so font metrics should match on Linux. The horizontal-scroll
  check is the one most likely to differ if a fallback font were ever used.
- Setup and Go Live don't use the WebGL globe, so the SwiftShader launch args don't matter here.
- A fresh checkout has no `.svelte-kit/`; `npm ci` runs `prepare` (`svelte-kit sync`), and the build
  passed here from a worktree without it too (only a tsconfig warning).

## Lessons

A harness that runs only by hand catches a regression only when someone remembers to run it. Put
the cheap slice of it in CI.
