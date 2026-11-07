# 2026-11-07 — Packet analysis, PR 2: the /packets page (NET-188)

**Status:** merged as PR #198 (`0fc218b`) and deployed to the G11 on 2026-11-07: 39 ✓, 0 ✗.

## What changed

- **The new Packet analysis page at `/packets`,** under Investigate in the sidebar. It replaces the TShark tool: `/tools/tshark` now sends a 308 redirect to `/packets`, and the old page's code is kept as OLD CODE.
  - **The first visit** shows:
    - what's kept: the oldest packet, the capture files, whether capture is on, and the packet reader;
    - a question builder: a device, who it talks to, a port, what kind of traffic, when, and how many packets. Before the search runs, it shows the filter it wrote and the files it will read;
    - five common questions;
    - a library of 37 ready-made filters;
    - a filter editor with field suggestions and a live check;
    - the saved capture files.
  - **The results** show:
    - the question, with the exact filter and the files read;
    - four KPIs, counted only over the packets shown: Packets, Lasted, Data, and TShark noticed;
    - the packets, each with a plain-English sentence where the case is unambiguous, otherwise TShark's Info line;
    - a drawer with every layer and the raw bytes;
    - "the conversation over time" and "who sent what";
    - a download of exactly these packets.
- **Connections:** both drawers have "Open these packets". This is the connection's exact two-way five-tuple over its time span plus 1 s at each end, split into 30-minute segments when the connection is longer. When a record has no ports, the label says it is all traffic between the two addresses.
- **Utilities** (`web/src/lib/utils/packet-*.ts`), each with its tests:
  - `packet-query`: questions to filters, the URL state, and connection windows with exact BigInt-nanosecond maths;
  - `packet-describe`: the sentences;
  - `packet-stats`: the KPIs, chart and senders, counted from the rows;
  - `packet-library`: the 37 filters, the "What" kinds and the common questions, in `packet-library.json`.
- **A device check (`scripts/remote/verify-packet-library.py`, Step 5b of `deploy-packet-analysis.sh`):** the G11's own TShark compiles every library filter and every "What" filter, through the daemon's real filter check.

## Accuracy rules the page keeps

- **"All of them"** appears only when the daemon read the whole window to the end. A search that's still being written says "All saved so far", and one stopped at the limit says "First N". A search that hit its deadline is never shown as complete.
- **Every figure says what it covers,** for example "in the packets shown".
- **Exactness of a connection link** travels in the URL (`exact=1|0`). It is never worked out from the filter text, which the user can edit.
- **Placeholder filters never run as written.** "Lookups that skip your router" asks for the router's address. "One conversation" is offered from a packet's drawer, with that packet's stream number and the same window.
- **Device-chosen text** (Info, field values, file names, filters) renders as text. There is no `{@html}` in any of the new code.

## Decisions

- **Device anchor:** a device matches `ip.addr` (or `ipv6.addr`), so both directions count.
- **"The internet"** is an address outside the LAN (the NET-160 rule) and outside the local-only blocks, plus global IPv6 (2000::/3). The address blocks are written as a set to keep filters under the daemon's 500-character limit.
- **Site names match exactly.** "www.example.com" is a different name from "example.com", and the page says so.
- **The "When" pills are 5, 15 and 30 minutes, plus a from/to range,** because the daemon caps a window at 30 minutes. The mockup's "Last hour" can't be searched.
- **"TShark noticed"** counts note, warning and error. Chat-level items go under "Routine notes".
- **"Open PCAP Search"** is a plain link, because `/pcap` reads no URL parameters.

## Known limits

- **A replaced search isn't stopped on the daemon.** It runs to its deadline (about 40 s), because the proxy can't pass the browser's cancel through after reading the body. Meanwhile a new search may get the busy message.
- **Download is a form post,** so the browser shows its own progress. A daemon error therefore opens as the daemon's JSON message.

## Verification

- **Web:** the full Vitest suite, svelte-check, the colour gate, the production build, and the visual tests for /packets.
- **Device:** `deploy-packet-analysis.sh` on the G11 at `main` `0fc218b` gave 39 ✓ and 0 ✗.
  - The capture index holds 1,838 files.
  - Search rows match an independent read of the same files: a boundary case gave 213 = 213, and the cut-short cases gave 528 = 528 and 256 = 256.
  - Step 5b: the library has 37 filters in 6 groups, and the device's TShark accepted 46 of 46 (the library plus the "What" filters).
