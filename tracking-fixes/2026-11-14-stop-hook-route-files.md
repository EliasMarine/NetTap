# The Stop hook no longer asks for tests SvelteKit can't have, 2026-11-14

**Linear:** none. This is owner-approved tooling config, not a product bug.
**Branch:** `chore/stop-hook-route-files`
**Status:** merged to main. It takes effect in a session once the checkout Claude Code runs in has the new
`.claude/settings.json`.

## Problem

The project's Stop hook is an agent hook in `.claude/settings.json` that checks each edited `.ts` file
has a test. During the 2026-11-14 bug triage it blocked most stops, asking for
`web/src/routes/api/[...path]/+server.ts` to have a `+server.test.ts`.

That demand couldn't be met:
- SvelteKit refuses any unknown `+`-prefixed file under `src/routes/`, so `svelte-kit sync` fails.
- The route was already tested by `web/src/routes/api/catchall-proxy.test.ts`, which imports it.
- The edit had been reverted before merge.
- The worktree had since been removed.

## Fix

Two steps were added after step 2 of the hook prompt:

- **2a:** drop SvelteKit route files, meaning any path under `src/routes/` whose file name starts with `+`.
- **2b:** drop any path that no longer exists on disk, such as files in a removed worktree.

Everything else in the prompt is unchanged. JSON has no comments, so the replaced text is kept here
instead of as OLD CODE. Step 2 itself is unchanged; the new steps sit between it and step 3:

> 2. Search the transcript for all Edit and Write tool calls whose file_path ends in .ts (but NOT .test.ts,
> .spec.ts, .visual.ts, or .d.ts; .visual.ts files are Playwright visual tests). Collect the unique set of
> modified .ts file paths.
> 3. If no .ts files were modified, respond {"ok": true}.

The hook description in `CLAUDE.md`, which is untracked and exists only on the owner's checkout, was
updated to match.

## Tests

- The edited `.claude/settings.json` parses as JSON. The hook is a prompt, so there's no unit test. Its
  real check is the next session that edits a route file.

## Lessons

- A coverage hook needs to know where the framework forbids a test file. Otherwise it asks for an
  impossible file on every stop.
