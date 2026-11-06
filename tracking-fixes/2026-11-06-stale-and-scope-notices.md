# 2026-11-06 — Log Explorer says it counts excluded devices; Live says when filtered figures are stale (NET-165, NET-162)

**Status:** fixed on `fix/log-explorer-excluded-note`. The PR is pending.

**NET-165: Log Explorer's top domains ignore the excluded IPs setting**
- **Problem:**
  - "Top DNS queries" counts lookups from devices excluded in Settings. The DNS page leaves them out.
  - So the same domain can rank differently on the two pages, and nothing explains why.
- **Root cause:** a deliberate rule, not a bug in the query.
  - Settings promises that excluded IPs "remain visible in Log Explorer".
  - Every Log Explorer card follows that rule; the OLD CODE blocks in `daemon/api/logs.py` record it.
  - The page never said so.
- **Fix:**
  - The page subtitle now says that devices excluded in Settings are counted there too, so figures can differ from the DNS and Devices pages (`web/src/routes/logs/+page.svelte`).
  - Filtering the query instead would break the Settings promise.

**NET-162: Live's filtered view doesn't say when a refresh failed**
- **Problem:** with a filter on, a failed refresh left the last filtered top talkers and protocols on screen with no notice, so they read as current.
- **Root cause:**
  - `filteredDashboard` keeps the last good filtered reply for the same filters.
  - The cards render it before they check `filteredFailed`.
  - The error state only appeared when there was nothing to show.
- **Fix:** while a filter is on, the filtered refresh failed and older filtered figures are showing, the shared stale notice appears: "Couldn't refresh the filtered figures; showing the last figures loaded." (`web/src/routes/live/+page.svelte`). The next good refresh clears it.

**Tests**
- New tests: `logs.test.ts` checks for the subtitle note. `live.page.test.ts` covers the whole sequence: a filtered load, a failed refresh (the old figures stay and the notice shows), then a good refresh (the notice clears).
- Both failed before the fix.
- Web: 3,183 passed. svelte-check 0 errors, colours clean, e2e ok, visual 207 passed.

**Lesson**
- A card that keeps its last good figures must say so when a refresh fails, whatever path loaded them. Check every path, filtered views included.
