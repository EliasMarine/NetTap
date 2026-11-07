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
- Request limits: adapter-node refused bodies over 512K and aiohttp over 1 MiB, so a backup holding photos couldn't be restored. nginx, nettap-web (`BODY_SIZE_LIMIT`) and the daemon (`client_max_size`) are all 16 MB now. Photos are capped at 256 KB each and 8 MB in total, which keeps any backup under that limit.

## Safety decisions (from the Codex plan review)

- The owner's name is presentation only. Classification (`_device_category`, IoT `_categorize_device`) still runs on the discovered name, so a name like "Front door cam" never moves a laptop into IoT.
- Photo files are immutable and content-named (`<mac>-<sha256 prefix>.<ext>`). A change writes the file, commits the metadata atomically, swaps the in-memory copy, then deletes old-minus-new references. A crash at any step leaves the last committed state served.
- The startup sweep of unreferenced photos runs only on metadata that passes full schema validation. An unreadable file deletes nothing, refuses writes (503), and makes the backup export fail instead of producing an incomplete backup.
- Photo types come from magic bytes only (PNG, JPEG, WebP; SVG and anything else refused). They are served with `nosniff`, their own Content-Type and `default-src 'none'`. A photo URL serves only under its own `?v=<hash>`; anything else is a 404 with `no-store`, which the web proxy now passes on.
- Restore replaces each present section after validating all of it, all or nothing.
- On the MAC page, a save bumps an edit revision so an older in-flight load can't overwrite the saved device, and a save's reply is dropped if the page moved to another device.

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

- Daemon pytest: 3940 passed, 0 failed (baseline on main: 3863 passed, 0 failed).
- Web: Vitest 3991 passed; svelte-check 0 errors (the same 2 warnings as main); colour gate clean.

## Lessons

- Check the request limits of every layer (nginx, adapter-node, aiohttp) before designing anything that carries files. adapter-node's 512K default is easy to miss.
- A dead backup section can turn harmful once its data source becomes real. Old backups still carry its empty value, so restore has to recognise them.
- Content-named immutable files plus "old refs minus new refs" cleanup avoid deleting a file that is re-uploaded with identical bytes.
