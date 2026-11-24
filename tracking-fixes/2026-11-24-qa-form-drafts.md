# NET-365, NET-366, NET-367: form drafts and autofill (23 Nov QA, findings 5–7)

**Date:** 2026-11-24 · **Branch:** `fix/qa-form-drafts` · **Status:** in review · Plan gate: `/codex-review` APPROVED in 3 rounds

## NET-365: Cancel kept the new channel and rule drafts (Settings › Notifications)

**Root cause**
- The Add channel / Cancel header button only toggled `showAddForm`. The type, name and config survived into the next open.
- The success path reset the name and config, not the type.
- The rule form had the same bug: event type, ticked channels and severity survived Cancel, and its success path reset only the channels.
- Also found and fixed:
  - Deleting the last channel disabled the rule form's Cancel, which reads "Cancel" while the form is open.
  - The `dirty` check called `.trim()` on every config value. The email channel's SMTP port binds as a number, so typing only a port threw inside the effect.

**Solution**
- `closeAddForm()` and `closeRuleForm()` reset each form to its defaults: Discord, Alert, medium and above, nothing ticked. Cancel and the success path share them, so a reopened form starts fresh either way.
- Cancel is off while its own create runs, and through the refresh after it, so a slow create can't clear the next draft.
- The success message names the channel that was sent.
- The rule button is off for zero channels only when opening the form.
- The emptiness check is `String(v ?? '').trim()`.

**Tests** (`notifications-tab.test.ts`, `settings-hub.test.ts`)
- Cancel and reopen show the defaults, for both channels and rules.
- A saved channel or rule leaves the next form at the defaults.
- Cancel is held while a create runs.
- Deleting the last channel leaves Cancel usable.
- A cancelled-then-reopened channel form doesn't hold a tab switch.
- A port-only draft holds one, with no throw.

## NET-366: Cancel kept the new investigation's details (Investigations)

**Root cause:** Cancel only set `showNewForm = false`. The header "New investigation" button toggled the form, so a second click hid it the same way. Only a successful create reset the four fields.

**Solution**
- `closeNewForm()`, shared by Cancel and the successful create, clears title, description and tags and puts severity back to Medium.
- The header button only opens the form now. A button labelled "New investigation" no longer discards a draft.
- Both buttons are off while a create and its refresh run.

**Tests** (`investigations-page.test.ts`)
- Cancel and reopen show the defaults.
- A second header click keeps the draft.
- With the POST and then the refresh held, Cancel and New investigation stay off until both land. The next form is fresh and its Cancel works.

## NET-367: Chrome autofill marked untouched Settings tabs as changed

**Root cause**
- `dirty` was already a value diff. Integrations compares the form with the loaded snapshot, and API keys and the ET Pro code count any typed secret, since saved secrets never reach the page.
- Chrome's password manager filled the saved NetTap login into those secret fields.
- Chromium's form parser has no branch for `autocomplete="off"`, so the UniFi key and the ET Pro code (both `off`) were filled anyway. The MaxMind key, SMTP password and the email channel's SMTP password had no autocomplete at all.
- Chrome shows the page an autofilled password only after a user gesture, so the click on the next tab is what turned the tab dirty.
- Autofill input events are `isTrusted`, so the page can't tell them from typing.

**Solution**
- Every secret field that isn't the NetTap login gets `autocomplete="one-time-code"`: UniFi API key (Settings and Setup), MaxMind key, SMTP password, ET Pro code, and the email channel's SMTP password.
- Chromium maps that token to `kOneTimeCode`, and `IsNotPasswordField` returns true for it. A form whose password fields are all like that is `only_for_fallback`, which `password_form.h` defines as "declined … for normal saving, updating, or filling", so it is filled only by a manual pick.
- **Why not `new-password`:** two `new-password` fields in one form owner (MaxMind and SMTP) are parsed as password plus confirmation. Accepting Chrome's generated password in one could fill the other, and the shared Save would overwrite a working SMTP password. It also offers "Suggest strong password" and save prompts.
- Settings › Account's change-password form and `/login` are unchanged (`current-password` / `new-password`).

**Tests**
- `settings-hub.test.ts`: on Integrations, API keys and Suricata rules, every password input is `one-time-code` (at least one per tab), and the loaded, untouched tab doesn't hold a switch.
- `notifications-tab.test.ts`: the email channel's SMTP password.
- `setup-wizard.test.ts`: the Setup UniFi key.
- `suricata-rules-etpro.test.ts`: the assertion moved from `off` to `one-time-code`.

## Files
- `web/src/routes/settings/tabs/NotificationsTab.svelte`
- `web/src/routes/investigations/+page.svelte`
- `web/src/routes/settings/tabs/IntegrationsTab.svelte`
- `web/src/routes/settings/tabs/ApiKeysTab.svelte`
- `web/src/routes/settings/tabs/SuricataRulesTab.svelte`
- `web/src/routes/setup/+page.svelte`
- The tests above.

## Test results
- `npx vitest run`: 461 files, 6,333 tests, all pass.
- `npx svelte-check`: 0 errors. The 2 warnings were already there, in files this change doesn't touch.
- `npm run check:colors`: clean.
- `npm run test:visual`: 415 passed, 67 skipped.
- `/ponytail-review`: no findings.
- Every new test was run against the original components and failed (16 tests).

## Lessons
- `autocomplete="off"` does nothing for Chrome's password manager. For a secret that isn't a login, use a token the parser excludes (`one-time-code`). `new-password` pairs fields as password and confirmation within one form owner.
- A form's Cancel and its successful save should share one reset, so the next open starts fresh whichever way it closed.
- A button that opens a form shouldn't also close it silently. Discarding belongs to Cancel.

## Next steps
- **Owner, before merge:** check in the dedicated Chrome profile with the saved NetTap login, as set out step by step in the PR.
  - On main: Integrations, a neutral click, then API keys. The bar appears.
  - On this branch: direct loads and in-app switches across Integrations, API keys and Suricata rules (wait for the ET Pro code field), Notifications › Add channel › Email. No field gets filled and no bar appears.
- **Follow-ups, not in this PR:**
  - Changing the channel type inside an open form keeps values typed for the earlier type, and hidden ones are sent.
  - Separate form owners for MaxMind and SMTP, so Chrome's manual context-menu "Suggest password" can't pair them.
