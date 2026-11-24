# QA 23 Nov: misleading data (NET-362, NET-364, NET-368, NET-371, NET-373)

**Date:** 2026-11-24 · **Branch:** `fix/qa-misleading-data` · **Status:** in review · Source: the 23 Nov exploratory browser QA, findings #2, #4, #8, #11, #13

Plan reviewed by Codex: `VERDICT: APPROVED` in round 5 of 5 (`.codex-review/20261124-095144-qa-data/`).

## NET-362: subnet calculator gave a /31 a broadcast address

- **Problem:** `192.0.2.9/31` listed `192.0.2.9` as the broadcast address while also calling it the last usable IP. A /32 did the same with its only host.
- **Root cause:** the page always printed `network | wildcard` as the broadcast. Usable-host maths already followed RFC 3021, but the broadcast line didn't.
- **What changed:** a /31 reads "None (point-to-point)" and a /32 reads "None (single host)", shown in body text rather than monospace. Every other prefix is unchanged.
- **Files:** `web/src/routes/tools/subnet-calc/+page.svelte`
- **Tests:** `subnet-calc-page.test.ts` covers /31 (first .8, last .9, no broadcast, 2 usable), /32 and /30 (broadcast .11).
- **Lessons:** when one field is fixed for an edge case (usable hosts), check its siblings for the same case.

## NET-364: DNS by device took any text and blamed NetTap

- **Problem:** typing `not-an-address` in DNS by device gave "Check that NetTap is running" with Try again.
- **Root cause:** the page sent the box text as-is, and the daemon put it straight into the OpenSearch `source.ip` term, which failed and became a 502.
- **What changed:**
  - **Daemon:** `GET /api/dns/device/{ip}` parses the address with the existing `parse_single_ip`. Anything that isn't one IP gets 400 "That is not an IP address.", and the canonical form (`2001:DB8::1` → `2001:db8::1`) is what gets queried.
  - **Web:** `getDeviceDns` uses `getJson`, so the daemon's reason reaches the page.
  - The page checks the box with `isSearchIp` before asking. A typo shows an inline error and keeps the current rows.
  - A daemon 400 shows its own reason with no Try again.
  - A range change reloads the device on screen, not the box text.
  - The card says which device it shows.
- **Files:** `daemon/api/dns.py`, `web/src/lib/api/dns.ts`, `web/src/routes/dns/+page.svelte`
- **Tests:**
  - `daemon/tests/test_dns_device_ip.py`: rejects text, out-of-range octets, a CIDR, a zoned address and a leading-zero octet without calling analytics, and passes a padded or upper-case address through canonicalised.
  - `dns.test.ts`: the 400 reason is carried.
  - `dns-page.test.ts`: four tests, covering an invalid IP, a typo after a lookup, a 400 reason, and a range change.
- **Lessons:** a 502 "is NetTap running" for bad input sends the owner to the wrong problem. Validate at the daemon boundary and let the reason through.

## NET-368: Bandwidth showed empty states before the first reply

- **Problem:** on load, Bandwidth showed "No usage this month yet", "No devices yet" and "This month · 0 devices" for a moment, before the data arrived. A failed refresh also dropped the device count.
- **Root cause:** `loading` started `false`, so the first render (including the server render) took the empty branches. The breakdown's subtitle counted `devices.length` even when nothing had been loaded.
- **What changed:**
  - `loading` starts `true`.
  - The breakdown's subtitle only counts once a reply gave the list or rows are on screen.
  - A failed refresh keeps the rows and shows a warning line inside the breakdown.
- **Files:** `web/src/routes/bandwidth/+page.svelte`
- **Tests:**
  - New `bandwidth-ssr.node.test.ts`: the server render shows "Loading…" and none of the empty states. It fails with the old `loading = false`.
  - Three tests in `bandwidth.test.ts`:
    - the subtitle before a reply and after a failure;
    - "0 devices" only on an empty success;
    - rows kept with the note on a failed refresh.
- **Lessons:** a page's first state has to be "loading", not "empty": SSR renders it and sends it to the browser.

## NET-371: Connections called resets "Rejected"

- **Problem:** the Rejected filter listed sessions whose state cell said "Reset" (RSTO/RSTR), so the two words disagreed.
- **Root cause:** the `rejected` filter has always covered REJ, RSTO and RSTR. Only its label was narrow.
- **What changed:** the pill reads **Reset**. With it selected, a help line says what it covers: REJ (refused at the start), RSTO or RSTR (reset by either side). The query value stays `rejected`, so links and the daemon are unchanged.
- **Files:** `web/src/routes/connections/+page.svelte`
- **Tests:** `connections.test.ts` checks the pill labels, that the help line shows only with Reset selected, and that the REJ row reads "Reset". The existing clicks in `connections.test.ts` and `connections.refresh.test.ts` moved to "Reset".
- **Next steps:** the other wording gaps from the same QA pass are a follow-up: Timeout vs "No reply", and Established/Closed vs Completed/Ongoing.

## NET-373: a refused PCAP download opened raw JSON

- **Problem:** "Download filtered" opens a new tab. When the daemon refused before sending a packet (no capture holds the window, too many packets, busy…), the tab showed `{"error": …}` and the PCAP page showed nothing.
- **Root cause:** the tab was a plain navigation to the proxied daemon URL, so the JSON error was the page. The page couldn't check first: the file being written is always pending, so only the real download knows whether the window is empty.
- **What changed:**
  - The page opens the download with `reply=page`.
  - If the daemon refuses, the catch-all proxy returns a short readable HTML page (`lib/server/download-error-page.ts`), not JSON. The page has the daemon's status and `no-store`, and the message is HTML-escaped and script-escaped. Its inline script posts `{type, message}` to `window.opener` at `location.origin`.
  - The PCAP page accepts the message only when all of these hold:
    - it is same-origin;
    - it comes from the exact tab that page opened;
    - it is the right type;
    - it carries a string message;
    - the filter and dates have not been edited since.
  - It then shows the reason beside the dates and closes the tab.
  - A blocked pop-up says so and offers a plain link.
  - Without `reply=page`, and for every other path, the proxy answers as before.
  - It is still one request and one TShark job, nothing is buffered in the browser, and the download/origin guard in `hooks.server.ts` is untouched.
- **Files:**
  - `web/src/lib/api/pcap.ts`
  - `web/src/lib/server/download-error-page.ts` (new)
  - `web/src/routes/api/[...path]/+server.ts`
  - `web/src/routes/pcap/+page.svelte`
  - visual harness: `web/e2e/visual/fixture-daemon.ts`, `web/e2e/visual/fixtures/pcap.ts`
- **Tests:**
  - `download-error-page.test.ts` (4): status, type, no-store, escaping including `</script>` and U+2028, fallback text.
  - `catchall-proxy.test.ts` (3): HTML only for `reply=page` on a refused download; JSON otherwise; a successful download streams unchanged.
  - `pcap.test.ts`: `reply` is added only when asked.
  - `pcap-page.test.ts` (5): the inline message with the tab closed; wrong source, origin or type ignored; an edit before the reply ignored; a retry clears the message; a blocked pop-up link.
  - New `e2e/visual/pcap-download.visual.ts` at 390 px, in a real browser: a refused window shows the message inline, closes its tab and keeps the fields; a good window saves `nettap_filtered.pcap` once.
- **Lessons:** a new tab can't show an error to the page that opened it unless it is told to. `postMessage` to the opener, with origin and source checks, does that without a second request.
- **Residual risk:**
  - a refused download briefly opens and closes a tab;
  - with no `window.opener` (the blocked-pop-up link), the user reads the explanation on the tab's own page instead.

## Review of #368 (24 Nov)

- **Security review:** no findings. **TypeScript review:** no Critical or High.
- **Medium 1, fixed with a test:** DNS by device shows a daemon reason only for a 400. A 502 carrying raw text (`index_not_found_exception …`) keeps the retry hint and Try again, and the text stays hidden (`dns-page.test.ts`).
- **Medium 2, fixed with a test:** picking a client in the NXDOMAIN table after a typo clears the IP error (the "typo after a lookup" test).
- **Deploy script:** `deploy-qa-fixes-2026-11-23.sh` step 7 now checks through nginx:
  - DNS by device for `not-an-address` → 400;
  - a 2001-window download with `reply=page` → `404 text/html`;
  - the same download without it → `404 application/json`.
- **Follow-ups, not done here:**
  - **Low 3:** the subnet calculator accepts malformed input such as `1..2.3` and `/24abc`. The lead is filing it in Linear.
  - **Lows 4 and 5:** deferred by the lead. Their details are in the TypeScript review of #368.

## Verification

- `cd web && npx vitest run`: all pass. `npx svelte-check`: 0 errors, 2 warnings that were already there (DrawerSection, KVRow). `npm run check:colors`: clean.
- `cd daemon && python3 -m pytest -q`: no new failures. The 127 failures and collection errors on this Mac are the same set on `origin/main`: `psutil` isn't installed in the system Python.
- Visual suite (under the shared lock): 416 passed, 67 skipped, no baseline changed. The PCAP specs were re-run after the last fixture edit: 2 passed. `npm run check:e2e`: clean.
- Device checks (the owner runs them; there is no deploy in this PR):
  - #4: with the daemon token, `GET /api/dns/device/not-an-address` → 400 `{"error": "That is not an IP address."}`.
  - #13: through the app, the same download URL with `&reply=page` for a 2001 window → 404 `text/html` with "No capture file holds packets from this window."; without it → 404 JSON.
