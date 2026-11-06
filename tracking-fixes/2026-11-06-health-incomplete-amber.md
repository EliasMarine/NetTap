# 2026-11-06 — An incomplete health check is amber (NET-168)

**Status:** fixed on `fix/health-incomplete-amber`; PR pending. Plan: `plans/2026-11-06-net168-health-incomplete-amber.md` (Codex approved in round 3 after 2 findings, both about the new browser test).

**Problem**
- NET-159 (S5) made the daemon report system health as healthy, problem or incomplete (some checks couldn't run, such as an unreadable drive).
- The health strips on Home and System showed incomplete as a grey "Unknown" stage, and System's overview chip had no tone. NetTap did check, and part of the check needs a look, so "Unknown" said the wrong thing.

**Fix** (owner's decision, 2026-11-06: a new amber state; the system's orange `.chip.is-warn` keeps its meaning, "bad change")
- `Pipeline.svelte`: a `warn` stage status. Its icon is the warn triangle in `--sev-medium` (amber), named "Warning". The stage's detail carries the specific words: "Incomplete · some checks couldn't run".
- `api/system.ts`: `HEALTH_STAGE.incomplete` is `warn`. Home and System both read this one map.
- `forms.css`: `.chip.is-caution` (amber). System's overview chip uses it for "Incomplete".
- `DESIGN-SYSTEM.md`: the chip and the four Pipeline states are listed.

**Not changed, by design**
- The drive stage's "Couldn't read the drive" stays Unknown: NetTap has no reading at all there.
- Storage above the pruning line stays ok with its "above the 70% pruning line" detail: pruning is the daemon working as designed.

**Tests**
- Unit: a `warn` Pipeline stage has its own class and icon name; Home's `systemStage` maps incomplete to `warn`; the Home and System renders show "Warning" and the chip has `is-caution`. These fail with the map set back to `unknown`.
- Browser (`e2e/visual/health-incomplete.visual.ts`): in all three themes, on `/` (stage "System") and `/system` (stage "NetTap"), the icon's painted colour is `--sev-medium`, and on `/system` the "Incomplete" chip's is too. It fails with either new CSS rule removed (checked both).

**Lessons**
- A class assertion can't catch a missing CSS rule. When the fix is a colour, check the painted colour in the browser (Codex round 1).
