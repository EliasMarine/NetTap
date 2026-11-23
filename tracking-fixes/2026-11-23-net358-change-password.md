# NET-358: change your password in Settings › Account

**Date:** 2026-11-23 · **Branch:** `feature/change-password` · **Status:** in review · Parent: NET-321 (viewer accounts stay there)

## Problem
The owner couldn't change their password in the dashboard; it took editing `users.json` on the box. Owner request, 23 Nov: "add the option for a user to change their password via the UI".

## Root cause
- Nothing called `updatePassword`.
- Tokens were checked only for signature and expiry, so a password change would have left every other session valid for up to 24 h.
- `updatePassword` awaited the hash between reading and writing the store.
- An older build, reached through a rollback, would trust any token signed with `jwt-secret.txt`.

## What changed
- **Settings › General › Account** (`AccountTab.svelte`):
  - fields for the current password, the new password and a confirmation;
  - one submission at a time;
  - success says other browsers must sign in again, plus a warning line if the save couldn't be confirmed on disk.
  - The sidebar username links to it.
- **`POST /api/account/password`**:
  - signed-in only;
  - the setup wizard's rules, now shared in `passwordProblem`, with a 1,024-character maximum;
  - the current password checked through the login throttle (`attemptLogin`);
  - a compare-and-swap save (409 if it changed elsewhere);
  - a durable write (temp file 0600, fsync, rename, directory fsync);
  - the new cookie for this browser;
  - refused with 409 while `JWT_SECRET` is set.
- **Sessions:** a token carries a stamp of the password hash. `verifyToken` checks it against `users.json` and returns the stored role, so a change signs out every other session. The live notification stream re-checks before each write and closes.
- **A new signing-key epoch** (`session-keys.ts`):
  - this release signs only with `jwt-secret-v2.txt` (no environment override);
  - at every start, `init` replaces the legacy `jwt-secret.txt`, the only key older builds read, before serving;
  - any failure stops the app starting.
  - So a rollback to any build since `aa234d73` (March 2026) trusts no session from before it. Builds older than that sign with a public constant and are not a supported rollback target.
- **Late 401 guard:** the layout re-asks `/api/auth/me` after any password change in flight settles, and only leaves when the session is really gone. The browser that made the change keeps its message.
- **Dev:** `npm run dev` runs `scripts/dev.mjs`, which gives each checkout its own data folder under `~/.nettap-web-dev/`, outside the repository and the Docker build context. Built servers keep `/var/lib/nettap-web`.
- **Scripts:**
  - `mint-session.cjs` mints a 60 s session the same way the server signs one. It replaces the inline minting in three older deploy scripts.
  - `deploy-change-password.sh` ships NET-357 and NET-358. It refuses to run while `JWT_SECRET` is set, and it handles a box with no account yet.
  - `rollback-change-password.sh` restores the image it recorded.

## Plan and reviews
- **`/codex-review`:** approved in round 9. The log is in `.codex-review/2026-11-23-114936-change-password/` (not committed).
- **`/deep-review`:** no findings. The report is in `security-reviews/feature-change-password/`.
- **`/ponytail-review`:** "Ship", with four cuts, all applied (below).
- **Security engineer:** 0 Critical, 0 High, 0 Medium. Its one Low, the unvalidated `NETTAP_SESSION_SECRET`, is resolved by removing it. Its informational note is applied: `current` is capped. Twelve plan guarantees were confirmed.
- **TypeScript reviewer:** 0 Critical, 0 High. Its Mediums (a hung request, the unvalidated env key) and Lows L1–L4 and L6–L8 are applied.
  - Accepted as is: L5 (the changing browser's own notification stream closes and reconnects with the new cookie, so an alert in that gap isn't replayed).
  - Accepted as is: L9 (a full or read-only data volume stops the web app starting, by design, so the old key is always retired).

## Review fixes (two-angle review, ponytail review)
- The `NETTAP_SESSION_SECRET` override is gone: no install set it, it was unvalidated, and its key label was copied in two files. `JWT_SECRET` is still warned about at start and still blocks a password change (409).
- The change request gives up after 30 s and the shell's `/api/auth/me` recheck after 10 s, so a hung request can't hold the shell. A lost answer says the password may or may not have changed.
- Only `/me`'s own 401 sends the shell to sign in; a failed or 502 recheck stays.
- `Retry-After` is sent only when the throttle gives a wait. A current password over 1,024 characters gets the 400 before it is checked, so it spends no login attempt.
- `trackPasswordChange` takes the fetch's promise only. `npm run dev` starts plain `vite`; its test puts a stand-in first on `PATH`.
- `deploy-change-password.sh`: when the new container doesn't start, it points to the log instead of a restart loop, and says when rolling back is safe.

## Deploy
- `bash scripts/remote/deploy-change-password.sh` on the G11. Everyone signs in again once.
- Rollback: `bash scripts/remote/rollback-change-password.sh`. Don't roll back past March 2026 (`aa234d73`).

## Follow-ups
- Proxied Dashboards/Grafana WebSockets survive a password change until they reconnect (nginx checks only at the handshake; sign-out has the same limit).
- The detection-slice-2 rollback deletes the ET Pro credential before it rejects a target (an existing bug).

## Lessons
- A password change is only as strong as the oldest verifier that can come back. Retire the key that verifier reads at every start, not once.
- Each review round found a narrower edge. Rounds 6–9 only added tests, which was the sign the design had settled.
