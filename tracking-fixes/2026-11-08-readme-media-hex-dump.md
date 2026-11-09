# README screenshots and tour video, and the packet drawer's raw bytes fit again

**Date:** 2026-11-08
**Branch:** `docs/readme-media`
**Linear:** NET-212 (README media), NET-213 (hex dump fix)
**Status:** PR open, not merged. Merging deploys nothing: the hex dump fix reaches the G11 with the next web deploy.

## What the owner asked for

Screenshots and a video for the GitHub repo. Later: short captions in the video, a screenshot of the expanded globe, and screenshots of Packet analysis. The owner reviewed the media before anything was pushed.

## What changed

- **`npm run capture:media`** (`web/e2e/visual/media.capture.spec.ts`) makes everything again in about a minute:
  - 11 stills: 1440×900 at 2x, shrunk with an ffmpeg 256-colour palette to 230–770 KB.
  - The tour: an MP4 (about 33 s) and a GIF for the README (800 px, 12 fps, kept under 8 MB by an assertion).
  - **Demo data only.** It uses the visual harness's fixture daemon: RFC 1918 and 5737 addresses, `example.com` names, London as home. No real network appears.
  - **Captions** are drawn into the page while it records: one pill per screen, on a band that fades the bottom of the content to black, so a caption never half-covers a heading. The tour ends on a card with the brand mark and the README's tagline, and fades in and out so the GIF loops cleanly.
- **README:** the GIF under the badges links to the MP4. The new Screenshots section has the expanded globe full width, then a 2×5 grid. `docs/index.md` embeds the video and three stills.
- **The `media` Playwright project exists only under `NETTAP_CAPTURE_MEDIA`**, so `npm run test:visual`, plain e2e runs and CI never open a headed browser or rewrite the committed media. `web/playwright.visual.config.test.ts` checks this and fails if the gate is removed.
- **Fix: the packet drawer's raw bytes** (`web/src/routes/packets/HexDump.svelte`). The drawer is `c-4`, about 320 px inside at 1440 px, but 16 bytes per row in `--text-xs` mono needs about 380 px. Every row was cut off and the ASCII column sat behind a sideways scroll that macOS hides. It now shows 8 bytes per row (about 290 px) on desktop and phone, and the first view is still 256 bytes (32 rows). The old constants are kept as `OLD CODE`. Test: `HexDump.test.ts`.

## Lessons

- **Headless SwiftShader can't record the globe.** WebGL in software is so slow that the screencast starves it and the globe never reports ready. Capture runs headed on the real GPU, with `--hide-scrollbars`, because Playwright hides scrollbars only in headless mode.
- **Playwright's `recordVideo` encodes VP8 at 1 Mbit/s**, which smears motion. Chrome's own screencast (CDP `Page.startScreencast`, JPEG at quality 95) is sharp:
  - Frames come only when the screen changes, and at up to about 120 Hz on a ProMotion display.
  - Each frame's duration is the gap to the next one. Never clamp them to 1/30 s: that stretched a 31 s tour to 100 s.
  - The last frame is held until stop, measured with a clock offset taken at the first frame.
- **A sidebar link's accessible name includes its badge** ("Alerts 214000 alerts in the last 24 hours"), and the brand mark also links to `/`. Click sidebar entries by `href` instead.
- **For a small GIF:** `mpdecimate` after the `fps` filter, with `-fps_mode vfr`, so static stretches cost almost nothing. A clean source also makes a smaller GIF than a noisy one.
