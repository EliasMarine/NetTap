# NET-361: concurrent tabs queued health checks while user actions waited

**Date:** 2026-11-24 · **Branch:** `fix/health-poll-queueing` · **Status:** in review · Source: exploratory browser QA, 23 Nov 2026, finding 1

## Problem
With several NetTap tabs open in one browser profile, QA saw:
- up to 10 copies of `/api/system/ping` waiting at once in one tab;
- health polls that waited 44–74 s before the browser sent them;
- an investigation create that waited 41.5 s before it was sent, then got its first byte in 7 ms.

Both tabs reported HTTP/1.1.

## Root cause
1. **Six connections for every tab.** nginx served 443 without HTTP/2, so browsers used HTTP/1.1. Chrome opens at most 6 connections to one site, shared by every tab in a profile. Each tab's notification bell keeps an `EventSource` open for good, so each tab holds one of the 6. With a few tabs and some slow requests, everything else waited inside the browser.
   - Reproduced locally (repo nginx.conf, local nginx, a Node stand-in for nettap-web, Playwright Chromium, one profile). With 8 tabs, only 6 streams opened, and a ping and a POST both timed out at 8 s.
   - With `http2 on`, 8 of 8 and 20 of 20 streams opened. The ping and POST answered in 1–3 ms over `h2`, and a WebSocket still opened.
2. **Polls stacked on themselves.** The shell's 30 s poll sent the ping, capture health and storage again on every tick, whether or not the last ones had answered, and none had a client deadline. The alert-badge refresh started a new count each tick. The bell's fallback poll did the same, in hidden tabs too.
3. **The patched nginx wasn't guaranteed.** HTTP/2 in nginx up to 1.30.6 has CVE-2026-123007 (major, memory corruption) and CVE-2026-123633 (use-after-free), fixed in 1.30.7. The G11 last recorded 1.30.6 on the floating `nginx:1.30-alpine` tag, and compose never re-pulls a cached tag.

**Threats "Couldn't load the threat report"** (same QA pass): cause not confirmed. The likely path is the 125 s client deadline running out while the request waited in the browser. It could also be the daemon's 90 s backstop (503), a handler 500 or a proxy 502. No separate defect found. If it happens again, match the failed request in DevTools with the nginx access line for `/api/threats/report` (status, `rt=`) and the daemon log for that minute.

## What changed
- `docker/nginx.conf`: `http2 on;` in the 443 server. Upstream stays HTTP/1.1. WebSockets use their own HTTP/1.1 connection, because nginx doesn't offer RFC 8441.
- `docker/docker-compose.yml`: `nginx:1.30-alpine` is now `nginx:1.30.8-alpine`. A tag that isn't cached is pulled on `up`. The `SECURITY.md` row now names the new tag.
- `web/src/routes/+layout.svelte`:
  - The ping, capture health and storage each have a 15 s deadline, under the 30 s poll and above the web routes' own daemon budgets.
  - `once()`: one request per kind per shell run. A tick skips a request that is still out, and each kind is skipped separately. A reply or deadline from before a sign-in writes nothing into the new shell.
  - The tick's alert-badge refresh goes through `once()` too.
- `web/src/lib/stores/alertSnapshot.ts`: every count the store asks for has a 15 s deadline.
- `web/src/lib/components/NotificationBell.svelte`:
  - one list request at a time, shared by mount, the dropdown and the poll;
  - a 15 s deadline;
  - no poll while the tab is hidden (the stream still reaches it).
- `getCaptureHealth`, `getStorageStatus`, `getNotifications`, `getAlertCount` and `getCaptureMode` take an optional `AbortSignal`. Other callers are unchanged.
- Review fixes (TypeScript review of #367):
  - `web/src/lib/stores/captureMode.ts`: the shared mode request has a 15 s deadline. Before, one that never settled left `pending` stuck, so every later `initCaptureMode()`/`refreshCaptureMode()` joined it and the chip stayed on "Checking mode…". A timeout reads 'unknown', and the next call asks again.
  - The bell's `/api/notifications/from-alerts` call has the same 15 s deadline, so a hung conversion no longer holds up the first list.

## Files
`docker/nginx.conf`, `docker/docker-compose.yml`, `SECURITY.md`, `web/src/routes/+layout.svelte`, `web/src/lib/components/NotificationBell.svelte`, `web/src/lib/stores/alertSnapshot.ts`, `web/src/lib/api/{capture,system,notifications,alerts}.ts`, `web/src/lib/stores/captureMode.ts`. Tests: `daemon/tests/test_nginx_http2.py` (new), `tests/scripts/test_nginx_conf.bats`, `web/src/routes/layout.test.ts`, `web/src/lib/components/NotificationBell.render.test.ts`, `web/src/lib/stores/alertSnapshot-deadline.test.ts` (new), `web/src/lib/stores/captureMode.test.ts`, `web/src/lib/api/{capture,system,notifications,alerts}.test.ts`, `web/src/routes/infrastructure/infrastructure.test.ts`.

## Tests
- New, each failing without its fix:
  - pytest: `http2 on` in the 443 server; the nginx image is a patch release with both HTTP/2 fixes.
  - layout: one request at a time, each kind on its own; the 15 s deadline and the retry on the next tick; an old run's deadline doesn't clear a new disk-full warning; the shell's alert refresh doesn't stack.
  - bell: one list request at a time; a 15 s deadline; no poll in hidden tabs.
  - store: a count gives up at 15 s.
  - clients: the caller's signal reaches `fetch`.
- Adapted:
  - Two redirect tests now use a sign-in round trip for the newer ping, because one ping at a time makes the old 30 s overlap impossible.
  - The `/me` deadline test asserts on the `/me` signal itself.
  - Five exact-call assertions follow the new `fetch(url, { signal })` shape.
- Results (dev Mac, rebased on main `a35b898a`): vitest 6353 passed (463 files); svelte-check 0 errors; colour gate clean; daemon pytest 6306 passed, 5 skipped; bats `test_nginx_conf.bats` 9/9; ruff clean on the new file; `test:visual` 416 passed, 67 skipped; `vite build` clean.

## Lessons
- An open `EventSource` costs one of six HTTP/1.1 connections per site for every tab, so a page with a permanent stream needs HTTP/2.
- A poll needs a deadline shorter than its interval, plus one request at a time. A deadline alone can still overlap when a late timer callback fires. One request at a time alone freezes if a request hangs.
- A deadline creates a write that a request left hanging never made. Check that the run that asked is still current before applying a reply.
- Compose never re-pulls a cached floating tag. To be sure a fix reaches the box, pin the patch release.

## Next steps
- Deploy, in the lead's script:
  - a one-off container runs `nginx -t` and pulls 1.30.8;
  - build nettap-web;
  - `up -d --no-deps --force-recreate nettap-web nettap-nginx`, not a reload: a single-file bind mount keeps the old inode;
  - check `nginx -v` (1.30.8), `curl --http2 … %{http_version}` (2) and that the running web image ID matches the build.
- Owner acceptance: 8 Home tabs in one profile show `h2`. While Home refreshes are out, an investigation create spends under 1 s queued or stalled and returns `201`.
- Follow-up: the bell's interval is always 30 s, because `stream.isConnected()` is read before the stream opens.
- Follow-up (review Low #2): a ping that times out reads as "Can't reach NetTap", although the box may only be slow, or the browser queue full on an HTTP/1.1 fallback.
- Follow-up (review Low #3): no refresh on `visibilitychange`. A tab coming back from the background waits for the next tick (≤ 30 s) for fresh shell values and notifications.
