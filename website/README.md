# nettap.dev

The public NetTap website: a home page and a features page, static files only.

- `site/`: the source, served as-is apart from the hero JS and the CSS. `features.html` and `404.html` are generated from the `GROUPS` list in `build-features.py`, reusing `index.html`'s icons, nav and footer.
- `build.sh`: builds `site/` into `dist/`. It bundles and minifies the 3D hero with esbuild and three.js from `web/node_modules` (run `cd web && npm ci` once), minifies the CSS and stamps the release name into each page. It fails if the CSP hash in `nginx/nettap.dev.conf` no longer matches the inline script.
- `preview.py`: serves `dist/` on http://127.0.0.1:8787 with the production headers (CSP included) and the same `/features` and 404 handling as nginx.
- `nginx/nettap.dev.conf`: the master copy of the vhost. Edit it here, never on the server.
- `deploy.sh`: publishes to `nginx-local` (192.168.1.24) over ssh. `deploy-remote.sh` runs on the server: it checks nginx and records how every other site answers, then switches to a new release in `releases/` and verifies it. Any failure puts the vhost and the live release back as they were. `deploy.sh --rollback` serves the previous release again.

```bash
website/build.sh && python3 website/preview.py   # look at it locally
website/deploy.sh                                # publish
website/deploy.sh --rollback                     # undo the last publish
```

The certificate is Let's Encrypt via the webroot method (`/var/www/letsencrypt`), renewed by certbot.timer, which reloads nginx. Cloudflare DNS for nettap.dev is DNS-only.
