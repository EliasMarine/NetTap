# Plan: NET-168 — an amber "incomplete" state on the health strips
_Round 2 - revised after Codex round 2_

## Goal

NET-159 (S5) made the daemon report system health as one of three states: `healthy`, `problem`, or `incomplete` (some checks couldn't run, such as an unreadable drive). The web shows `incomplete` as a grey "Unknown" pipeline stage, and on System as a neutral chip. "Unknown" is wrong: NetTap did check, and part of the check couldn't run, which the user should look at. The owner chose (2026-11-06): **a new amber state**, using `--sev-medium`, keeping `.chip.is-warn` orange (`--sev-high`, the design system's "bad change" tone).

## Approach

1. `web/src/lib/components/ui/Pipeline.svelte`:
   - `StageStatus = 'ok' | 'warn' | 'failing' | 'unknown'`.
   - `LOOK.warn = { icon: 'warn', word: 'Warning' }`. The word is the icon's accessible name; the stage's own `detail` carries the specific words ("Incomplete · some checks couldn't run").
   - Class `is-warn` on `.pipe-k` for that status, and `.pipe-k.is-warn :global(.ic) { color: var(--sev-medium); }`.
   - Update the header comment ("Healthy", "Warning", "Failing" or "Unknown").
2. `web/src/lib/api/system.ts`: `HEALTH_STAGE.incomplete.status` becomes `'warn'`, and the structural type gains `'warn'`. Home (`home.ts` `systemStage`) and System (`system/+page.svelte` daemon stage) both read this map, so both strips change together.
3. `web/src/lib/styles/forms.css` (the one extension file; `system.css` is a verbatim copy and is never hand-edited): `.chip.is-caution { color: var(--sev-medium); background: color-mix(in srgb, var(--sev-medium) 14%, transparent); }`, beside the existing `.chip.is-bad`, with a one-line comment.
4. `web/src/routes/system/+page.svelte`: `OVERVIEW_CHIP.incomplete = ['Incomplete', 'is-caution']`; the old value is kept as OLD CODE.
5. `web/DESIGN-SYSTEM.md`: list `.chip.is-caution` beside `.chip.is-bad` in the forms.css row, and note the pipeline's warn state: amber is "a check couldn't run / needs a look", orange `is-warn` stays "bad change", red `is-bad` "failed".
6. Tests:
   - `Pipeline.test.ts`: a `warn` stage renders the `warn` icon named "Warning", the `.pipe-k` has `is-warn`, and not `is-failing`/`is-unknown`.
   - `home.test.ts:138`: `incomplete` → `status: 'warn'` (the old expectation kept as OLD CODE per policy).
   - `system/system.test.ts:270-271`: the NetTap stage reads word "Warning"; the "Incomplete" chip has class `is-caution`.
   - `home-system-health.test.ts:64-69`: also assert the stage's icon is named "Warning", not "Unknown".
7. A browser test that checks the rendered colour (Codex round 1): `web/e2e/visual/health-incomplete.visual.ts`. For each theme (Ember, Graphite, Spectrum):
   - `setMode('populated')`, `stubUpstreams`, then `page.route('**/api/system/health', …)` fetches the fixture daemon's real reply with `route.fetch()` and fulfils it with `status: 'incomplete', healthy: null`, so every other field stays real.
   - Open `/` and `/system`, apply the theme with `setVariant`.
   - Resolve `--sev-medium` to an `rgb(…)` string in the page (a probe span styled `color: var(--sev-medium)`, read with `getComputedStyle`).
   - Assert the health stage's icon (the `img` named "Warning" inside the `.pipe-item` whose `.pipe-k` reads the stage label) has that computed `color`. The label differs by page: `/` → `System` (`home.ts` `systemStage`), `/system` → `NetTap` (`system/+page.svelte`).
   - On `/system`, assert the "Incomplete" chip's computed `color` equals the same value, and that it is not the `--sev-high` value (so `is-warn` orange can't satisfy it).
   - The test fails on the old code (grey clock "Unknown", neutral chip) and fails if either CSS rule is left out.

## Key decisions & tradeoffs

- **Icon shape:** the icon set has no square or circle-with-bang. The `warn` triangle in amber, with the visible detail "Incomplete · …", is distinct from failing (the same triangle in orange, detail "Reports a problem") by colour and word. Reusing the grey clock (Unknown) would keep the wrong meaning. Adding a new icon means changing the design system's asset set, which the owner owns.
- **A generic `warn` stage, not `incomplete`:** the Pipeline is a shared component; the status names a tone, the detail names the cause. Only health uses it today.
- **No change to other stages:** the drive stage's "Couldn't read the drive" stays Unknown (NetTap couldn't read it at all, so it has no reading); Storage's pruning-line case stays ok with its "above the 70% pruning line" detail (pruning is the daemon working as designed). Only the aggregate `incomplete` changes.
- **Chip name `is-caution`:** `is-warn` is taken by the system with a different colour; `is-medium` would read as a severity pill.

## Risks / open questions

- Contrast: all three themes (Ember, Graphite, Spectrum) are dark; `--sev-medium` (#f5c84c) is already used as text-on-tint in `.notice.is-warn` icons and SeverityPill, so it is legible.
- Visual regression snapshots: a visual fixture that renders `incomplete` would change; check `web/e2e/visual` and update the baseline only for that case.

## Verification plan

- `cd web && npx vitest run`, `npx svelte-check --threshold error`, `npm run check:colors` (new CSS uses tokens only), `npm run test:visual` (which runs the new colour test).
- Tests above fail on the old code (warn → unknown, chip with no tone).

## Rollback / migration safety

Web only, no daemon or API change. Revert the PR to roll back.

## Observability

None needed; a pure display change.

## Out of scope

- NET-166 (storage units), NET-160 slice 2.
- Other places that might deserve amber (retention "attention" in Settings already uses `is-warn`; left alone).
