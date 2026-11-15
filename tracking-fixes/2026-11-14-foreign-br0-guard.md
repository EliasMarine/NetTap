# NetTap no longer treats every `br0` as its own, 2026-11-14

**Linear:** NET-287
**Branch:** `fix/foreign-br0-guard-net287`
**Status:** fixed in code, device run pending. Deploy: rebuild `nettap-storage-daemon` and `nettap-web`;
the shell changes take effect on the next `install.sh` / `setup-bridge.sh` run.

## Problem

On a host that already has a `br0` (a VM/LXD/KVM host, a netplan bridge, Unraid), NetTap treated that
bridge as its own:
- bridge setup (installer, `setup-bridge.sh`, the daemon's `/api/bridge/create`) added WAN/LAN to it and
  retuned STP, forward delay, ageing and the bridge-nf sysctls;
- teardown removed every port and deleted it, taking the host's uplink and VMs off the network;
- bypass changed promisc on its ports;
- the NIC-in-use guard checked only the default route and addresses, so it offered a port of another
  bridge or a bond, and Go Live could report "live" on someone else's bridge.

Found during the Unraid research, not in the field.

## Root cause

There was no ownership marker. The name `br0` was the only test.

## Fix

- **Ownership rule.** `br0` is NetTap's if (1) its `ifalias` is `nettap`, or (2) the legacy fallback
  holds: it has ports, every port is a `- <port>` line in `10-nettap-bridge.yaml`, it has no global
  IPv4/IPv6 address, and no default route goes through it. A failed or unreadable address or route read
  refuses. One copy per language: `bridge_is_nettaps()` in `daemon/services/bridge_manager.py`, and
  `nettap_bridge_owned` / `refuse_foreign_bridge` in `scripts/common.sh`.
- **Marker.** NetTap sets the alias right after `ip link add` and before any reconfigure change. If that
  fails, a `br0` made in the same call is deleted again and nothing else runs.
- **Refusals, before anything changes:** daemon create, preview (400), teardown and readiness; bypass
  enable/disable (409); `setup-bridge.sh` setup, reconfigure and `--teardown`; `harden-bridge.sh`;
  `bypass-mode.sh`; `install.sh` unless `--skip-bridge`.
- **After a reboot.** The daemon's `99-nettap-bridge.conf` now also sets
  `net.ipv6.conf.br0.disable_ipv6 = 1`, as the script's did, so a daemon-made `br0` can't pick up a SLAAC
  address from the modem side and fail the legacy rule.
- **NIC guard.** A port with any master is in use, unless the master is NetTap's own `br0`.
- **`setup-bridge.sh --teardown`** releases WAN/LAN only if their `master` really is `br0`.
- **Web.** The bypass buttons (Bridge status card, Go Live) show the daemon's refusal text for a 409. A
  500 still shows the generic text, because its body carries exception text.
- **Recovery** for a NetTap `br0` that fails both rules: `sudo ip link set br0 alias nettap`. Every
  refusal, in the daemon and in the shell scripts, names it.
- Replaced logic is kept as OLD CODE blocks.
- Rejected: a cross-process lock and identity tracking; restoring the marker after a reboot (rule 2 covers
  netplan's rebuild); teardown deleting the persistence files (the netplan file can hold the management
  address).

## Files

- Daemon: `daemon/services/bridge_manager.py`, `daemon/services/bridge_health.py`, `daemon/api/setup.py`,
  `daemon/api/bridge.py`.
- Daemon tests: `daemon/tests/test_bridge_ownership.py` (new), `test_bridge_manager.py`,
  `test_setup_bridge_preview.py`, `test_bridge_api.py`.
- Shell: `scripts/common.sh`, `scripts/bridge/setup-bridge.sh`, `scripts/install/install.sh`.
- Shell tests: `tests/scripts/helpers/bridge_stubs.bash` (new),
  `tests/scripts/test_setup_bridge_foreign_br0.bats` (new), `test_setup_bridge_dry_run.bats`,
  `test_install.bats`.
- Web: `web/src/lib/api/bridge.ts`, `web/src/lib/components/BridgeStatus.svelte`,
  `web/src/routes/go-live/+page.svelte`, with `bridge.test.ts`, `BridgeStatus.render.test.ts`,
  `GoLive.test.ts`.
- Docs: `Debugging/BRIDGE-ARCHITECTURE.md` (§2 Bridge ownership, §7 row),
  `Debugging/DEPLOYMENT-ISSUES.md` (Chain 36).

## Tests

- Each new test failed on the old code first (old files swapped in, then restored): ownership pytest
  20/21, bypass and preview 6, the 409 API test, the new bats file 9/9, the install refusal, 5 vitest.
  The ones that passed on old code are the "NetTap's own bridge still works" guards.
- After the fast-forward to `origin/main` (2b38309f): daemon pytest 5073 passed, 5 skipped, 0 failed;
  bats `tests/scripts/` 393 ok; shellcheck (CI form) clean; vitest 398 files, 5305 tests passed;
  svelte-check 0 errors (2 old warnings); `check:colors` clean; ruff format and check clean on the
  changed Python.
- Before the fast-forward: visual `routes.visual.ts` + `firstrun.visual.ts` 163 passed; full visual
  317 passed, 54 skipped.
- Plan: `/codex-review` approved in 4 rounds (PLAN.md rev 5).

## Next

- Device run. The G11 runs mirror mode (no `br0`, its capture NIC has no master), so nothing should
  change there. A pre-fix bridge-mode box rebuilds `br0` from the file with no address, so rule 2 passes;
  after the first NetTap setup it also has the alias.
- Out of scope, tracked separately: renaming the bridge (NET-289), bypass when no `br0` exists,
  `uninstall.sh`, and the ERR-trap rollback that other `run` failures in `setup-bridge.sh` skip.
- Accepted residual: a foreign, address-less `br0` whose every port is in a leftover NetTap netplan file
  still passes, because it looks exactly like NetTap's bridge.

## Lessons

A well-known interface name (`br0`, `eth0`, `docker0`) is not ownership. Mark what you create, and fail
closed on anything you can't prove is yours. A read that can fail (`ip_json` returns `[]` for an empty
list, a failed command and bad JSON alike) can't be evidence of absence; use a checked read.
