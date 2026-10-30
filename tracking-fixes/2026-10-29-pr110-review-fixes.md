# PR #110 Pre-Merge Review Fixes (2026-10-29)

**Status:** Gates green locally; PR into `phase-4/infrastructure-redesign`; device check pending
**Type:** fix / security
**Branch:** `fix/pr110-review` → `phase-4/infrastructure-redesign`
**Plan:** `.codex-review/2026-10-29-193328-pr110-review-fixes/PLAN.md` (approved by Codex in round 4, items 1–20)

## Problem
The two-angle pre-merge review of PR #110 found one CRITICAL issue and a long tail of wrong-data and false-success bugs.

- **CRITICAL:** the daemon runs with `network_mode: host`, so its API on `0.0.0.0:8880` was open to the whole LAN. It had no auth and sent CORS `*`. Any device on the network could tear down the bridge, change retention or read the UniFi key (DEPLOYMENT-ISSUES Chain 20).
- **HIGH:** setup and bridge routes stayed public after the first admin existed, and two first-run requests could both create an admin.
- **HIGH:** UniFi `configure` would send the stored API key to a new controller URL. A slow poll for the old controller could overwrite the new one's status.
- **HIGH:** ILM saves applied out of order, so an older save could win.
- **HIGH:** excluded IPs hid real alerts, log search results and LAN detections. Excluding the router hid ARP spoofing of the router.
- **MEDIUM:** about 15 web pages showed placeholder data or "saved" when the daemon had failed.

## Root causes
- The move to host networking (to reach the UniFi controller) silently turned a container-internal API into a LAN endpoint.
- Auth was gated on route prefixes, with no check for whether first-run was still in progress.
- Many web API clients swallowed daemon errors and returned defaults, so the UI could not tell "empty" from "failed".

## Fix
33 commits. Every plan item 1–20, plus four found in the final review:

- **Security:** `520a5b6` daemon token, `ac3f6e6` empty-store gate, `44f2ed7` serialized first admin, `11bea76` first-run exact routes, `844884f` UniFi key redirect and generation counter.
- **Daemon:** `91b4f6c` revision-aware ILM worker, `fccc68c` `8827c87` excluded IPs filter only device views, `7c1f7a9` single-IP validation, `43b0394` keyword category, `68b129b` IoT executor, `fe33cab` `.keyword` live script, `665ce1f` rounding, `fd05119` storage-cycle executor, `256a299` top-by-bytes order.
- **Web:** `bc91632` `123a9c7` `b9e6ce6` `053011d` `38399ab` `f34269a` `384343b` `97aa7e7` `8c11fff` `c77f75b` `c2aad88` `c8a73f8` (real results, honest errors).
- **Final-review fixes:** `c775232` Settings never saves the mock retention defaults, `fbacf06` the wizard reports a failed UniFi test as failed, `b7533b3` a new controller doesn't inherit the old site, `d6211c1` page test for the suppress fix.
- **Docs and device:** `3c998b3` docs call the daemon with its token, `af7104a` `scripts/remote/deploy-pr110-review-fixes.sh`.

## Test results
- ruff 0.17.3 check and format: clean
- pytest: 2070 passed
- svelte-check: 0 errors (44 warnings, unchanged)
- vitest: 1826 passed
- Each of the four final-review tests fails with its fix reverted and passes with it.

## Reviews
- `/deep-review`: no high-confidence findings (`security-reviews/fix-pr110-review/security-review.md`).
- `ponytail-review`: no Must fix. Should-fix 1 and Nice-to-have 2, 3 and 6 are fixed above. 4 and 5 (lean only) are deferred.

## Device verification
```bash
bash scripts/remote/deploy-pr110-review-fixes.sh
```
It checks the token is in the daemon and web containers and not in tshark. It checks for 401 without the token on the LAN address and on loopback, 200 on `/api/health`, no CORS header, and 200 with the token. It also checks the OUI lookup works through the app, and that setup and bridge GETs are refused when logged out.

## Lessons
- Moving a container to host networking publishes every port it listens on. Add auth before the move, not after.
- A web client that returns defaults on error makes every page lie the same way. Throw, and let the page show the error.
- "Reload to check" advice is only safe if the reload shows real data. Check where a fallback lands before you point users at it.

## Next steps (out of scope here)
- 45 older `scripts/remote/*.sh` lines curl `:8880` without the token. Update a script before reusing it.
- Lean: drop the ignored `excluded_ips` parameters in `threat_detection.py`, `threat_intel.py` and `investigation.py`, and the `IlmApplyError` class.
- `POST /api/ilm/apply` still applies the static policy outside the ILM worker's lock and revision.
- `risk.py`, `cert_monitor.py` and `dns_analytics.py` still filter excluded IPs.
- Capture settings have no effect, the PCAP cleanup path, the setup wizard's separate `RetentionConfigManager`, the IoT registry only grows, connections filters, live monitor defects, GeoMap CDN tiles.
- TLS web→daemon, UniFi cert pinning, web `/api/health` passes daemon system health unauthenticated, login 500 on a damaged user store, public `/api/tools`.
- 802.1X EAPOL passthrough (`group_fwd_mask`) for AT&T fiber.
