# nettap.dev marketing site published, 2026-11-15

**Linear:** NET-292
**Branch:** `feature/marketing-site`
**Status:** live at https://nettap.dev since 2026-11-16 00:41 UTC (first deploy from the branch). PR pending.

## Problem

NetTap had no public website. The owner approved a full mockup on 2026-11-15: a home page with a 3D hero and a features page listing 91 features in 11 groups. It lived outside the repo (`nettap-dev-mockup/`) with raw three.js builds (3.7 MB) and an inline import map, so it couldn't run under a strict CSP and had no deploy path.

## Fix

- `website/site/` is the mockup source. `features.html` and `404.html` are now generated into `dist/` by `website/build-features.py` (one shared `head()`), so no generated HTML is committed.
- **Paths:** every asset and nav link is root-relative, so the 404 page also works for nested paths like `/a/b/c`. `/features` is a clean URL.
- **Head:** a canonical link, an OG image (1200×630, rendered from the live hero scene) and an apple-touch-icon. Plus `robots.txt` and `sitemap.xml`.
- **Build:** `website/build.sh` bundles the hero with esbuild and three.js from `web/node_modules` (no new dependency). The result is 927 KB minified, 256 KB gzipped, down from 3.7 MB. It also minifies the CSS, stamps a `nettap-release` meta into every page, and fails if the CSP hash no longer matches the one inline script.
- **CSP:** `script-src 'self'` plus the hash of `document.documentElement.classList.add('js')` plus `cdnjs.buymeacoffee.com`. Google Fonts style and font origins are allowed for the BMC footer button only, and inline styles for its `<style>` and the static `style="--i:n"` attributes.
- **nginx:** `website/nginx/nettap.dev.conf` is the master copy. It has:
  - port 80 with the ACME webroot plus a 301 to https, www → apex;
  - HSTS, nosniff, DENY framing, the CSP;
  - gzip for CSS, JS and SVG (nginx.conf only gzips HTML);
  - `expires -1` for pages, CSS and JS, and 30 days for fonts and images.
- **Deploy:**
  - `website/deploy.sh` (Mac) uploads `releases/<UTC>-<sha>`, then `website/deploy-remote.sh` runs on nginx-local as root.
  - Before any change it checks: `nginx -t` passes, no name clash, `000-default` still holds `default_server`, and it records a baseline of all 24 other-site answers.
  - It takes one snapshot of the vhost, its symlink and `current`; on the first deploy it bootstraps the certificate (webroot, `--deploy-hook "systemctl reload nginx"`); installs the vhost; and switches `current` atomically.
  - It then verifies 8 URLs plus the release stamp, re-checks the baseline, checks the renewal config and does a first-time renewal dry run with `--run-deploy-hooks`.
  - Any failure restores the snapshot. Pruning runs only after success. `--rollback` follows each release's recorded predecessor.
- **Accessibility:** the footer column titles went from `h4` to `h2`, same styling, fixing Lighthouse heading-order.

## Tests

- **Local (preview.py, production headers):** Playwright on WebGPU and forced WebGL 2, at 1440, 900 and 390 px:
  - no CSP violations, no console errors;
  - the hero goes live;
  - no horizontal overflow;
  - the BMC button renders;
  - `/features` 200, `/nope` and `/a/b/c` styled 404s.
- **Failure path on the real box:** a deliberately broken vhost. The cert was issued, nginx rejected the full conf, and the script restored no vhost, no `current`, deleted the candidate and left `nginx -t` green.
- **First live deploy:** caught a reload race. `systemctl reload` returns before the new workers serve, so the first check hit old workers and the script rolled back correctly. Fixed with a 5-try retry in `check`.
- **Live deploy:** 8/8 checks passed, every other site answered as before, and the renewal dry run passed.
- **Rollback history live test:** A→B→C→rollback (served B)→D→rollback (served B, not C). Pass. Pruning dropped A.
- **Live https Playwright run:** same as local, all pass, while releases switched underneath.
- **Live gzip and caching:** as designed. Cert: Let's Encrypt YE1, `nettap.dev` + `www`, until 2027-02-13.
- **Lighthouse on the live site:**
  - desktop: 100 performance, 98 accessibility (before the heading fix), 100 best practices, 100 SEO;
  - mobile: performance 70 (TBT 3.1 s from one "unattributable" 3.4 s task: the 3D hero's GPU start-up in the emulated phone), 100 best practices, 100 SEO.
- `shellcheck -S warning website/*.sh`: clean.
- **Plan:** `/codex-review` approved in 4 rounds (atomic releases, a whole-deploy snapshot, the other-site baseline, prune-after-success, predecessor rollback).

## Lessons

- `systemctl reload nginx` is asynchronous. Checks right after it can reach old workers, so poll.
- certbot `--deploy-hook` is saved as `renew_hook` in the renewal conf, and `--dry-run` skips it unless `--run-deploy-hooks` is passed.
- macOS ships openrsync: `-rlt --delete --exclude` work, so ownership and modes are set on the server instead.
- A fresh worktree has no `web/node_modules`. Run `npm ci` before `website/build.sh`.

## Next

- Owner decision: mobile Lighthouse 70 vs the 3D hero on phones. A still poster on narrow screens would likely score 95+.
- Follow-ups the inventory found, not in this change: README says DHCP gateway is recommended; doc errors (180-day alerts, Malcolm 26.02.0, three notification channels).
