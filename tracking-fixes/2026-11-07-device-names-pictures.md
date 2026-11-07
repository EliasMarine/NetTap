# Device names and pictures (NET-200)

**Status:** built, reviewed, merged and deployed (see the PR and the deploy result below)
**Branch:** `feature/device-names-pictures`
**Plan:** `.codex-review/2026-11-07-device-names-pictures/PLAN.md` (Codex approved in round 4; the log is beside it)

## What changed

On a device's page the owner can now:

- **Rename** the device. Their name comes before the UniFi alias, DHCP, mDNS and the maker on every page that names devices: Devices (cards, list rows and table), the device pages, Home's top devices, Connections, Packets, Certificates, the address and domain pages, traffic categories and IoT. "Use the discovered name" clears it, and the device page shows "Found on the network as …" meanwhile.
- **Change the picture**: pick one of the 12 built-in device icons, or upload a photo. "Reset to default" goes back to the category icon.

## Why it needed more than a field

- The registry's `friendly_name` was documented as "user-set via API", but no API set it, and a UniFi alias overwrote it on every refresh. The refresh loop also rewrites whole documents, so an owner's edit stored in the index could be lost. The owner's data therefore lives in its own store on the daemon's data volume (`device_custom.json` + `device-pictures/`).
- The config backup's `device_aliases` section read an `aliases` key from `device_baseline.json`, which is a flat MAC map. It always exported `{}`, and its import planted an "aliases" pseudo-MAC. It now carries the store's names, and the new `device_pictures` section carries icons and photos. A backup from before this change (which has `device_aliases` but no `device_pictures`) leaves the current names alone instead of wiping them.
- Request limits: adapter-node refused bodies over 512K and aiohttp over 1 MiB, so a backup holding photos couldn't be restored. Backup restore (`/api/backup/import` and `/validate`) now takes up to 16 MB on all three layers: nginx, nettap-web (`BODY_SIZE_LIMIT`) and the daemon (`client_max_size`). The rest of the web app is capped at 1 MB in nginx, so the sign-in endpoints can't be made to parse megabytes of JSON before the login check. Photos are capped at 256 KB each and 8 MB in total, which keeps any backup under that limit.

## Safety decisions (from the Codex plan review)

- The owner's name is presentation only. Classification (`_device_category`, IoT `_categorize_device`) still runs on the discovered name, so a name like "Front door cam" never moves a laptop into IoT.
- Photo files are immutable and content-named (`<mac>-<sha256 prefix>.<ext>`). A change writes the file, commits the metadata atomically, swaps the in-memory copy, then deletes old-minus-new references. A crash at any step leaves the last committed state served.
- The startup sweep of unreferenced photos runs only on metadata that passes full schema validation. An unreadable file deletes nothing, refuses writes (503), and makes the backup export fail instead of producing an incomplete backup.
- Photo types come from magic bytes only (PNG, JPEG, WebP; SVG and anything else refused). They are served with `nosniff`, their own Content-Type and `default-src 'none'`. A photo URL serves only under its own `?v=<hash>`; anything else is a 404 with `no-store`, which the web proxy now passes on.
- Restore replaces each present section after validating all of it, all or nothing.
- On the MAC page, a save bumps an edit revision so an older in-flight load can't overwrite the saved device, and a save's reply is dropped if the page moved to another device.

## PR #214 review fixes

The two-angle review (security engineer, Python and TypeScript reviewers) found no Critical or High issues. Fixed before merge:

- Backup export and import ran on the event loop. With up to 8 MB of photos to read and hash, they now run in a worker thread (`run_blocking`).
- An icon sent as a list or object raised TypeError, which no handler mapped to a 400. It is now a plain ValueError on the route, in restore and in metadata loading.
- The byte budget didn't cap the file count: one 16 MB backup of 3-byte JPEGs could create about 400,000 photo files under the store lock. The store now holds at most 2,000 devices (`DEVICES_MAX`).
- Restore errors logged up to 32 characters of the uploaded MAC key as-is. They are now quoted with `repr`, so a line break can't forge a log line.
- The 16 MB body limit had applied to every web route, sign-in included. See the request limits above.
- Clearing something that isn't set no longer rewrites the metadata file.
- Web: the `infra` icon showed as the generic one. A save while the next device loaded could land on the old device; the page now refuses it and merges only the owner's fields. Network and 413 errors read in plain English. A broken list-row photo falls back to the icon. The IP page's Hostname row keeps the discovered name. Focus returns to the opening button after a save, and a status region announces it. The JPEG fallback paints white under the picture.

Kept as is: photos are cached `private, max-age=31536000, immutable`. The URL carries the content hash, so a new photo is a new URL. The cost is that a removed photo stays in that browser's cache.

## Files

- Daemon:
  - `services/device_custom.py` (new store)
  - `api/device_custom.py` (new routes)
  - `services/device_registry.py` (owner name first, `with_names`)
  - `api/devices_v2.py` (with_names, owner-name search)
  - `api/devices.py` (owner fields after classification)
  - `services/traffic_classifier.py` + `api/traffic.py` (batched `lookup_many` gives the MAC; owner fields)
  - `services/iot_monitor.py` + `api/iot.py` (`_device_name`)
  - `services/config_backup.py` (both sections, old-backup guard)
  - `api/server.py` (wiring, 16 MiB)
- Infra: `docker/nginx.conf`, `docker/docker-compose.yml`.
- Web:
  - API: `lib/api/devices-registry.ts`, `lib/api/devices.ts`, `routes/api/[...path]/+server.ts`
  - Utilities: `lib/utils/device-picture.ts`, `lib/utils/device-names.ts`
  - Components: `DeviceTile.svelte`, `DeviceList.svelte`
  - Device page: `routes/devices/mac/[mac]/DeviceCustomise.svelte` + `+page.svelte`
  - Other pages: `routes/devices/+page.svelte`, `routes/devices/[ip]/+page.svelte`, `routes/+page.svelte`
- Tests:
  - Daemon: `test_device_custom.py`, `test_device_custom_routes.py`, `test_device_custom_surfaces.py`, plus the fixture in `test_config_backup.py`
  - Web: Vitest for the client, tile, list, names, picture util, the component, the MAC page race, and the proxy headers
- Deploy: `scripts/remote/deploy-device-names-pictures.sh` + `verify-device-names.py`.

## Test results

- Daemon pytest: 3949 passed, 0 failed (baseline on main: 3863 passed, 0 failed).
- Web: Vitest 4029 passed; svelte-check 0 errors (the same 2 warnings as main); colour gate clean; visual 283 passed.
- CI: all 18 checks green on the final head. Squash-merged as `351018e1` (PR #214).

## Deploy (G11, 2026-11-07)

`bash scripts/remote/deploy-device-names-pictures.sh` passed every check:

- **Limits:** nginx serves 10m (server), 1m (web app) and 16m (backup restore); `BODY_SIZE_LIMIT` is 16M and the daemon's limit is 16777216.
- **End to end**, on a real device (`BC:24:11:F2:AB:CB`, left as it was):
  - rename and clear, with the discovered name still shown;
  - pick an icon, then a photo, which is served as PNG with `nosniff`;
  - a stale version gets a 404 with `no-store`, an SVG and an unknown device are refused;
  - a backup carries both sections.
- **Sign-in:** the page loads (200). A 2 MB sign-in POST gets 413 at nginx, and an unauthenticated 2 MB backup import gets 401 from the login check.

Status: done. Not tried in a real browser: the photo crop (canvas WebP or JPEG) and the focus return; both are covered only under jsdom.

## Lessons

- Check the request limits of every layer (nginx, adapter-node, aiohttp) before designing anything that carries files. adapter-node's 512K default is easy to miss.
- A dead backup section can turn harmful once its data source becomes real. Old backups still carry its empty value, so restore has to recognise them.
- Content-named immutable files plus "old refs minus new refs" cleanup avoid deleting a file that is re-uploaded with identical bytes.
