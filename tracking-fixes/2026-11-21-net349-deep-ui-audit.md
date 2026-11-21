# NET-349: deep UI audit fixes

**Date:** 2026-11-21 · **Branch:** `fix/deep-ui-audit-2026-11-21` · **Status:** in review

The owner's "NetTap Deep UI Audit 2026-11-21" ran on the live G11 (`0.4.0-alpha.2`) in desktop Chrome and a 400 px phone viewport. It found six problems. It also confirmed the NET-347/348 fixes live: the drive warning at 74 °C, the retention label, the drill-down bounds, the Changelog window, one protocol choice on Connections, and the refused PCAP filter.

The plan went through `/codex-review` (3 rounds, `MAX_ROUNDS=3`): round 1 raised 13 findings, round 2 raised 12 and round 3 raised 6. All were accepted except one fix: round 2's clock tick, which a snapshot design replaced. It stopped at the cap without APPROVED, and no disagreement is open. The plan and log are in the worktree's gitignored `.codex-review/2026-11-21-140741-deep-ui-audit/`.

## What changed (audit finding → fix)

### High: Tab walked the table hidden behind the full-screen log drawer

`lib/components/DetailDrawer.svelte` is the shared drawer for logs, alerts, connections, live, IoT and investigations. It is now a native modal `<dialog>` opened with `showModal()`.
- The browser makes the page behind it inert, including anything added while it's open.
- Focus moves to Close, and Tab wraps at both ends.
- On close, focus returns to whatever opened it, falling back to `#main`. The opener is the element a click landed on, recorded in the capture phase, because Safari and DataTable's forwarded row click don't focus the button.
- Escape arrives as the dialog's `cancel` event. The parent's `open` prop stays the one switch, and a late `close` event from an earlier close is ignored.
- Only a press and a release that both fall outside the panel close it. A drag across the edge doesn't.
- The panel styling moved to an inner `.panel`. `display: flex` and the slide-in apply only to `[open]`, and the dialog's own sizing is reset.

Two related changes:
- **Investigations** (`routes/investigations/+page.svelte`): a failed note save or status change from inside the drawer now shows inside it, kept per investigation id, so one investigation's late failure never replaces or shows in another's.
- **Tests** (`tests/setup.ts`): jsdom has no `showModal`/`close`, so `setup.ts` stubs them. `close` fires its event as a task, as browsers do.

### Medium: a DNS alert's name was only in Raw JSON

`routes/alerts/AlertDetail.svelte` shows "DNS name" in its facts. `dnsNamesOf()` in `routes/alerts/alert-view.ts` reads Suricata's `dns.queries[].rrname` (eve v3, as the G11 stores it), `query[].rrname` and `answer.rrname` (v2), and `rrname` (v1). It removes duplicates and keeps at most five.

### Medium: a device page for a quiet hour showed only the IP and "Unknown", without Watch

In `routes/devices/[ip]/+page.svelte`, when the detail loads with no MAC and 0 connections, a notice says "No connections recorded for this address between … and …".
- If the registry search (`searchRegistry()` in `lib/api/devices-registry.ts`) lists exactly one device at that exact address, the notice names it and links to its MAC page.
- With no match, several matches, a full page of results or a failed lookup, it says NetTap can't tell which device used it.
- The page doesn't take on that device's name or Watch.
- The notice is cleared on a view change. Its dates come from the reply, or from the request's own window. A lookup's answer is accepted only by the load's generation.

### Medium: no search or notification inbox at phone width

- **Correction 10** in `lib/styles/a11y.css`: `system.css` hid `.topbar` below 760 px. It now shows under the menu bar. Search shares its row with Refresh and the bell, and the warning chips wrap. The "Updated" text and the ⌘K hint are hidden on phones.
- **`NotificationBell.svelte`:** its phone panel opens under the bell, no longer pinned over it.
- **`routes/+layout.svelte`:** `<main>` is inert while the phone menu is open, so Ctrl/⌘-K can't pull focus behind it. Focus returns to the menu button after a `tick`.

### Low: the backup card said "every NetTap setting"

In `routes/settings/tabs/BackupTab.svelte`, the subtitle now reads "the settings listed below".

### Low: the default 15-minute packet plan exceeded the 3 GB limit and still offered Find packets

- **One shared check:** `routes/packets/plan-check.ts` is the limit check that both Find packets buttons use.
- **QuestionBuilder:** both buttons are disabled while over the limit, and Enter in the editor is refused.
- **One window:** the window shown is the window searched. A "last N minutes" search first loads the capture list again, so the window ends at the press. If that load fails, nothing is searched. The `/ponytail-review` gate found that the first version reloaded only lists over a minute old, so a search 45 s after loading missed the last 45 s.
- **New default:** 5 minutes.
- **Budget refusal (`ResultsView.svelte`):** a daemon refusal for size now points to "New search", not the filter editor.

### Docs

`web/DESIGN-SYSTEM.md` now covers correction 10 and the modal drawer.

### Deploy

`scripts/remote/deploy-deep-ui-audit.sh` is web only. It tags the running image `nettap/web:rollback-net349` and checks the build's strings. `scripts/remote/rollback-deep-ui-audit.sh` checks the recorded image ID before recreating anything.

## Root cause

All six were display gaps:
- the drawer never managed focus;
- the alert facts never read Suricata's DNS block;
- the device page learned its identity only from traffic in the window;
- the design system hides the top bar on phones;
- the backup card's subtitle overclaimed;
- the packet page computed the limit but never applied it to the button.

## Tests

- **Vitest:** 439 files, 6,031 tests passed. New or updated:
  - `DetailDrawer.render.test.ts` (10)
  - `alert-view.test.ts` (`dnsNamesOf`)
  - `alerts-page.test.ts` (the DNS name visible with Raw JSON closed)
  - `investigations-page.test.ts` (per-investigation failures)
  - `layout.test.ts` (inert `main`)
  - `device-detail-quiet-window.test.ts` (11)
  - `devices-registry.test.ts` (4)
  - `plan-check.test.ts` (5)
  - `packets-page.test.ts`
  - `packets-results.test.ts`
  - the drawer role queries in the IoT and Connections tests
- **Playwright:** `e2e/visual/phone-shell.visual.ts` (5 tests):
  - At 390 and 400 px, search and the inbox fit with both warning chips, and the bell opens and closes the panel.
  - At 400 px, the log drawer fills the screen, 30 Tabs and 30 Shift+Tabs stay inside, and Escape returns focus to the row.
  - On a desktop, a backdrop click closes the drawer, while an edge click and drags in either direction don't.
- **Other checks:** `svelte-check` 0 errors; `check:colors` clean; `shellcheck` clean on both scripts.

## Review gates

- **`/deep-review`:** no findings (`security-reviews/fix-deep-ui-audit-2026-11-21/security-review.md`). No server-side code changed, and the DNS and registry names render as escaped Svelte text.
- **`/ponytail-review`:** two findings, both fixed. The "last N minutes" search now always reloads the capture list first, and the unused `show()` stub is gone.

## Lessons

- **`settle()` waits only for transitions.** A keyframe animation (the drawer's slide-in) needs its own wait, scoped to the element: a page can run an endless animation.
- **jsdom has no `inert` property.** Svelte sets `inert` as a property, which browsers reflect to the attribute and jsdom doesn't. Test the property.
- **Read state after an effect's teardown, not during it.** Svelte returns a prop's old value inside the teardown, so a handler fired synchronously from there sees stale props. Browsers queue the dialog's `close` event, and the stub must too.

## Next steps

- Deploy on the G11 and check the strings and the phone layout.
- **Follow-up:** the certificate and packet drawers are separate `<aside>` components and may have the same focus gap at phone width.
