# Security Review

## Review Metadata

* Review Folder: `feature-device-names-pictures`
* Report Path: `security-reviews/feature-device-names-pictures/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-07T12:44:51-08:00`
* Inspected Branch or PR: `feature/device-names-pictures`
* Current Commit: `275fe61`
* Review Scope: `uncommitted-only` (staged)
* Diff Sources: `git diff --cached`
* Dirty Working Tree Included: `no` (two small ponytail-review edits were made after staging; they are lean and fallback only and are restaged before commit)

## Files Reviewed

* daemon/api/device_custom.py (new)
* daemon/services/device_custom.py (new)
* daemon/api/devices.py
* daemon/api/devices_v2.py
* daemon/api/iot.py
* daemon/api/server.py
* daemon/api/traffic.py
* daemon/services/config_backup.py
* daemon/services/device_registry.py
* daemon/services/iot_monitor.py
* daemon/services/traffic_classifier.py
* docker/docker-compose.yml
* docker/nginx.conf
* web/src/routes/api/[...path]/+server.ts
* web/src/lib/api/devices-registry.ts
* web/src/lib/components/ui/DeviceTile.svelte
* web/src/lib/utils/device-picture.ts (new)
* web/src/routes/devices/mac/[mac]/DeviceCustomise.svelte (new)
* web/src/routes/devices/mac/[mac]/+page.svelte
* scripts/remote/deploy-device-names-pictures.sh (new)
* scripts/remote/verify-device-names.py (new)
* Tests and docs (daemon/tests/*, web/**/*.test.ts, tracking-fixes/*, web/DESIGN-SYSTEM.md) were excluded by design.

## Coverage Summary

* Changed symbols analyzed: 24 (the 5 new route handlers, `_run`/`_apply`/`_body`, `normalize_mac`, `clean_name`, `decode_image`, `sniff`, `_photo_record`, the store's `_write_photo`/`_commit`/`_change`/`_sweep`/`_load`/`_validated`/`photo`/`export`/`restore`, `ConfigBackup.export_config`/`import_config`, `DeviceRegistry.get_display_name`/`get_name`/`with_names`, `handle_registry_search`, `_with_owner`, `IoTMonitor._device_name`, `get_category_devices`, `create_app` body limit, the proxy image passthrough)
* Inbound callers inspected: 9 (route registration in `server.py`, the daemon auth middleware, the web session hook, the catch-all proxy, `daemonFetch`, backup routes, the IoT and traffic handlers, the deploy verifier)
* Outbound callees inspected: 8 (`write_file_atomic`, `tempfile.mkstemp`/`os.replace`/`os.unlink`, `DeviceRegistry._normalize_mac`, `registry.get_device`/`get_devices`, `fingerprint.lookup_many`, aiohttp `request.json`, Svelte interpolation and `<img src>`, `web.Response` content type)
* Sinks considered: path traversal (photo file names, sweep, unlink), file write/delete, content-type confusion and stored XSS (SVG, polyglots), auth bypass on new routes, CSRF on PUT/DELETE, cache poisoning of versioned photo URLs, secret exposure in logs and responses
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* Trusted rule memory: none
* Limitations / unresolved edges: none
* Not covered (by design): DoS/ReDoS (including the raised 16 MB body limits), rate limiting, dependency CVEs, generic hardening; run the two-angle review for those
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
