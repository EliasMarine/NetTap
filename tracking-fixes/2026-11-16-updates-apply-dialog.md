# An honest "Apply updates" picker, 2026-11-16

**Linear:** NET-311
**Branch:** `fix/updates-apply-dialog` (from `origin/main` 1afe48e4)
**Status:** implemented and tested locally. Not yet deployed. The plan was approved after 2 Codex rounds.

## Problem

The owner sent a G11 screenshot: "the apply updates container and the checkboxes to update components does not work".
The "Apply updates" picker listed two updates:

- **geoip-db** ("2026-09-29 → newer weekly release")
- **os** ("24.04 → 1 package update", with an `unknown` tag)

Neither checkbox could be ticked, and the button read "Update 0 components". Each row also had a "Changelog" accordion
that opened to a single sentence.

## Root causes and fixes

| # | Root cause | Fix |
|---|---|---|
| 1 | The banner's `Review` button was always shown, and `openUpdatePanel` had no guard. Only `Update all` checked whether anything could be applied. Both G11 updates carry `applies_with`, so Review opened a picker with nothing to pick. | `Review` and `Update all` show only when an update can be applied. Otherwise the banner lists the updates as information: each update's versions, changelog line and how it arrives. A new `panelShown` value keeps the picker off screen whenever nothing on the list can be applied, whatever route led there. |
| 2 | The updates NetTap can't apply got a `disabled` checkbox. `forms.css` has no disabled style for checkboxes, so it looked live and ignored clicks. | The picker lists only updates NetTap can apply, with working checkboxes. The rest sit below under "Can't be updated from here", with no checkbox. |
| 3 | The OS row's `update_type` printed `unknown`. The "Changelog" accordion hid a one-sentence status, and its subtitle repeated `latest_version`. | The tag is hidden when the type is `unknown`. A one-line changelog (no line break, under 160 characters) shows inline. The accordion stays only for multi-line release notes (Malcolm's). |
| 4 | A refresh while the picker was open could leave picks no longer listed, still counted and sent. While the start request was pending, the page fell back to the editable picker (Codex round 1). | The count and the request use only ticked updates still listed. A "Starting the update…" view replaces the picker until the start request answers. The progress list is built from `updateStatus.components`, which is what the daemon started. |

The real checkboxes always worked (`checked=` with `onchange` assigning a new Set). A test now proves it.

## Files

- `web/src/routes/system/updates/+page.svelte`
- `web/src/routes/system/updates/updates-page.test.ts`

## Test results

- Updates page tests: 59 passed. Against the old page, 9 of the new and changed tests fail, so they test the fix.
- Web full suite: 419 files, 5622 tests passed.
- `svelte-check --threshold error`: 0 errors. The 2 warnings were already there, in the drawer components.
- `check:colors`: clean.
- `test:visual` was left to the lead. Its fixture has one update that can be applied, so the banner looks the same.

## Lessons

- A disabled control has to look disabled. Better still, information should not be a control at all: an update NetTap can't
  apply is a line of text, not a checkbox.
- Guard where a view is shown, not only on each button that opens it. Every button had its own guard, and one was missed.
- An async action needs its own pending view. Falling back to the editable form while the request runs lets the user change
  what was already sent.

## Next steps

- Deploy the web container to the G11 and open System › Software updates. With today's geoip-db and os updates, there
  should be no Review button and no picker, and the banner should list both updates with how each arrives.
- `forms.css` still has no disabled style for checkboxes. No checkbox on this page is disabled any more. Check other pages
  if a disabled checkbox turns up.
